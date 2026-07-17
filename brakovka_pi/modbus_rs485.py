from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

from pymodbus.client import AsyncModbusSerialClient
from pymodbus.exceptions import ModbusIOException

from .config import RS485_RTS0_GPIO, SerialConfig, VfdConfig

log = logging.getLogger(__name__)

# Software RTS0 toggle (GPIO17 ALT3). Kernel TIOCSRS485 on PL011 often leaves RTS stuck HIGH.
DE_CONTROL_VERSION = "v8-uart-rts0-echo-flush"


@dataclass
class VfdCommand:
    run: bool = False
    reverse: bool = False
    speed_setpoint_hz: float = 0.0


class Rs485Vfd:
    """
    Async Modbus RTU over /dev/serial0 (PL011 / ttyAMA0).

    DE/RE for Waveshare SP3485: UART0 **RTS0 on GPIO17** (ALT3), toggled in software
    via ``serial.rts`` around each TX. Idle state is always RX (RTS at RX level).

    Wiring: TX=GPIO14, RX=GPIO15, DE/RE=GPIO17. config.txt: ``gpio=17=a3``.
    """

    def __init__(
        self,
        serial: SerialConfig | None = None,
        vfd: VfdConfig | None = None,
    ) -> None:
        serial = serial or SerialConfig()
        vfd = vfd or VfdConfig()

        self._de_ok = False
        self._de_error = ""
        self._de_patched = False
        self._de_timer: threading.Timer | None = None
        self._serial = serial
        self._vfd = vfd
        self._client = self._build_client()
        self._unit_id = serial.unit_id
        self._connected = False
        self._fail_count = 0
        self._last_reconnect_t = 0.0
        self._reconnect_period_s = float(serial.reconnect_period_s)
        self._fails_before_reconnect = max(1, int(serial.fails_before_reconnect))
        log.info(
            "RS485 DE via UART RTS0 soft (GPIO%s), active_high=%s",
            RS485_RTS0_GPIO,
            serial.rs485_active_high,
        )

    def _build_client(self) -> AsyncModbusSerialClient:
        return AsyncModbusSerialClient(
            port=self._serial.port,
            baudrate=self._serial.baudrate,
            parity=self._serial.parity,
            stopbits=self._serial.stopbits,
            bytesize=self._serial.bytesize,
            timeout=self._serial.timeout_s,
            retries=self._serial.retries,
            trace_packet=self._trace_packet,
        )

    @property
    def de_ok(self) -> bool:
        return self._de_ok

    @property
    def de_error(self) -> str:
        return self._de_error

    @property
    def de_patched(self) -> bool:
        return self._de_patched

    @property
    def connected(self) -> bool:
        return self._client_alive()

    def _rts_tx_level(self) -> bool:
        return bool(self._serial.rs485_active_high)

    def _rts_rx_level(self) -> bool:
        return not self._rts_tx_level()

    def _get_serial_transport(self):
        ctx = getattr(self._client, "ctx", None)
        transport = getattr(ctx, "transport", None) if ctx is not None else None
        if transport is None:
            transport = getattr(self._client, "transport", None)
        return transport

    def _get_pyserial(self):
        transport = self._get_serial_transport()
        if transport is not None:
            for name in ("serial", "_serial", "sync_serial"):
                ser = getattr(transport, name, None)
                if ser is not None and hasattr(ser, "write"):
                    return ser
        ctx = getattr(self._client, "ctx", None)
        if ctx is not None:
            for name in ("comm", "socket", "_sock"):
                obj = getattr(ctx, name, None)
                if obj is not None and hasattr(obj, "rts"):
                    return obj
                if obj is not None:
                    inner = getattr(obj, "serial", None) or getattr(obj, "_serial", None)
                    if inner is not None and hasattr(inner, "rts"):
                        return inner
        return None

    def _set_rts(self, level: bool) -> None:
        ser = self._get_pyserial()
        if ser is None:
            return
        try:
            ser.rts = bool(level)
        except Exception as exc:
            log.debug("RTS set failed: %s", exc)

    def _flush_rx(self) -> None:
        ser = self._get_pyserial()
        if ser is None:
            return
        try:
            ser.reset_input_buffer()
        except Exception:
            pass

    def _discard_rx_noise(self, max_bytes: int = 64) -> None:
        """Drop leftover TX echo / bus garbage so pymodbus does not CRC-fail."""
        ser = self._get_pyserial()
        if ser is None or max_bytes <= 0:
            return
        try:
            n = int(getattr(ser, "in_waiting", 0) or 0)
            if n <= 0:
                return
            junk = ser.read(min(n, max_bytes))
            if junk:
                log.debug(
                    "RS485 discarded %s RX byte(s) before slave frame: %s",
                    len(junk),
                    junk.hex(" "),
                )
        except Exception:
            pass

    def _rx_mode(self) -> None:
        """Idle / receive: RTS at RX level (must not stay HIGH if HIGH=TX)."""
        self._set_rts(self._rts_rx_level())

    def _tx_mode(self) -> None:
        self._set_rts(self._rts_tx_level())

    def _cancel_de_timer(self) -> None:
        t = self._de_timer
        self._de_timer = None
        if t is not None:
            try:
                t.cancel()
            except Exception:
                pass

    def _frame_time_s(self, nbytes: int) -> float:
        baud = max(1.0, float(self._serial.baudrate))
        return (max(0, int(nbytes)) * 10.0) / baud

    def _switch_to_rx_after_tx(self, nbytes: int) -> None:
        """Drop DE to RX, then discard local TX echo (if any) before slave reply."""
        self._rx_mode()
        time.sleep(0.001)
        # Only purge up to our TX length — do not eat the slave response.
        self._discard_rx_noise(max(0, int(nbytes)))

    def _arm_rx_after_tx(self, nbytes: int) -> None:
        self._cancel_de_timer()
        delay = (
            self._frame_time_s(nbytes)
            + float(self._serial.de_turnaround_s)
            + 0.002
        )
        timer = threading.Timer(delay, self._switch_to_rx_after_tx, args=(nbytes,))
        timer.daemon = True
        self._de_timer = timer
        timer.start()

    def _trace_packet(self, sending: bool, data: bytes) -> bytes:
        if sending and data:
            # Clear stale RX before master frame (prevents CRC on leftover bytes).
            self._flush_rx()
            self._tx_mode()
            before = float(self._serial.de_delay_before_tx_s)
            if before > 0:
                time.sleep(before)
            self._arm_rx_after_tx(len(data))
            self._de_patched = True
        elif not sending:
            self._cancel_de_timer()
            self._rx_mode()
        return data

    def _prepare_rts_control(self) -> bool:
        ser = self._get_pyserial()
        if ser is None:
            self._de_ok = False
            self._de_error = "pyserial handle not found after connect"
            log.error("RS485 %s: %s", DE_CONTROL_VERSION, self._de_error)
            return False
        try:
            # Do not use kernel rs485_mode — on Pi PL011 it often leaves RTS stuck HIGH.
            if hasattr(ser, "rs485_mode"):
                try:
                    ser.rs485_mode = None
                except Exception:
                    pass
            if hasattr(ser, "rtscts"):
                ser.rtscts = False
            self._rx_mode()
            self._de_ok = True
            self._de_error = ""
            self._de_patched = True
            log.info(
                "RS485 %s: soft RTS0 ready (GPIO%s, rts_tx=%s idle_rx=%s)",
                DE_CONTROL_VERSION,
                RS485_RTS0_GPIO,
                self._rts_tx_level(),
                self._rts_rx_level(),
            )
            return True
        except Exception as exc:
            self._de_ok = False
            self._de_error = f"{type(exc).__name__}: {exc}"
            log.error("RS485 %s: RTS prepare failed: %s", DE_CONTROL_VERSION, self._de_error)
            return False

    async def connect(self) -> None:
        if self._connected and bool(getattr(self._client, "connected", False)):
            return
        try:
            await self._client.connect()
        except Exception as exc:
            self._connected = False
            log.error("Modbus connect exception: port=%s err=%s", self._serial.port, exc)
            return
        self._connected = bool(getattr(self._client, "connected", False))
        if self._connected:
            self._fail_count = 0
            self._prepare_rts_control()
            log.info(
                "Modbus connected %s: port=%s baud=%s unit=%s de_ok=%s",
                DE_CONTROL_VERSION,
                self._serial.port,
                self._serial.baudrate,
                self._unit_id,
                self._de_ok,
            )
        else:
            log.error("Modbus connect failed: port=%s", self._serial.port)

    async def close(self) -> None:
        self._cancel_de_timer()
        self._rx_mode()
        try:
            self._client.close()
        except Exception:
            pass
        self._connected = False
        self._de_patched = False

    def _client_alive(self) -> bool:
        return self._connected and bool(getattr(self._client, "connected", False))

    def _note_success(self) -> None:
        self._fail_count = 0
        self._connected = True

    def _note_failure(self) -> None:
        self._fail_count += 1
        if not bool(getattr(self._client, "connected", False)):
            self._connected = False
        elif self._fail_count >= self._fails_before_reconnect:
            self._connected = False

    async def reconnect(self, *, force: bool = False) -> bool:
        now = time.monotonic()
        if not force and (now - self._last_reconnect_t) < self._reconnect_period_s:
            return self._client_alive()
        self._last_reconnect_t = now
        log.warning(
            "Modbus reconnect: port=%s fails=%s",
            self._serial.port,
            self._fail_count,
        )
        await self.close()
        self._client = self._build_client()
        await self.connect()
        return self._client_alive()

    async def ensure_connected(self) -> bool:
        if self._client_alive():
            return True
        return await self.reconnect()

    def _decode_status(self, status_word: int, err_code: int | None) -> dict:
        if self._vfd.profile == "delta_cp2000":
            fault_code = 0
            warning_code = 0
            if err_code is not None:
                fault_code = int(err_code) & 0xFF
                warning_code = (int(err_code) >> 8) & 0xFF
            return {
                "status_word": int(status_word),
                "error_code": int(fault_code),
                "fault": fault_code != 0,
                "warning": warning_code != 0,
            }

        fault_bit = bool(status_word & (1 << 4))
        err = int(err_code or 0)
        return {
            "status_word": int(status_word),
            "error_code": err,
            "fault": fault_bit or err != 0,
            "warning": bool(status_word & (1 << 6)),
        }

    async def _read_holding_u16(self, address: int, *, optional: bool = False) -> int | None:
        try:
            rr = await self._client.read_holding_registers(
                address,
                count=1,
                device_id=self._unit_id,
            )
        except ModbusIOException as exc:
            if optional:
                log.debug("Modbus optional read failed addr=0x%04X: %s", address, exc)
                return None
            raise
        except Exception as exc:
            if optional:
                log.debug("Modbus optional read error addr=0x%04X: %s", address, exc)
                return None
            raise
        finally:
            self._rx_mode()

        if rr.isError():
            if optional:
                log.debug("Modbus optional read error response addr=0x%04X: %s", address, rr)
                return None
            log.warning("Modbus error response addr=0x%04X: %s", address, rr)
            self._note_failure()
            return None

        if not getattr(rr, "registers", None):
            if optional:
                return None
            self._note_failure()
            return None
        return int(rr.registers[0])

    async def write_command(self, cmd: VfdCommand) -> bool:
        if not await self.ensure_connected():
            return False

        if cmd.run:
            cmd_word = self._vfd.cmd_reverse if cmd.reverse else self._vfd.cmd_forward
        else:
            cmd_word = self._vfd.cmd_stop

        hz = max(0.0, float(cmd.speed_setpoint_hz))
        hz_scaled = int(round(hz * float(self._vfd.freq_scale)))

        try:
            await self._client.write_register(
                self._vfd.reg_freq, hz_scaled, device_id=self._unit_id
            )
            await self._client.write_register(
                self._vfd.reg_cmd, cmd_word, device_id=self._unit_id
            )
            self._note_success()
            return True
        except ModbusIOException as exc:
            log.warning("Modbus write failed: %s", exc)
            self._note_failure()
            return False
        except Exception as exc:
            log.warning("Modbus write error: %s", exc)
            self._note_failure()
            return False
        finally:
            self._rx_mode()

    async def read_status(self) -> dict:
        if not await self.ensure_connected():
            return {}

        try:
            status_word = await self._read_holding_u16(self._vfd.reg_status)
            if status_word is None:
                return {}

            fault_word: int | None = None
            if self._vfd.reg_fault != self._vfd.reg_status:
                fault_word = await self._read_holding_u16(self._vfd.reg_fault, optional=True)

            freq_out_raw = await self._read_holding_u16(self._vfd.reg_freq_out, optional=True)
        except ModbusIOException as exc:
            log.warning("Modbus read failed: %s", exc)
            self._note_failure()
            return {}
        except Exception as exc:
            log.warning("Modbus read error: %s", exc)
            self._note_failure()
            return {}
        finally:
            self._rx_mode()

        freq_out_hz = (
            float(freq_out_raw) / float(self._vfd.freq_scale)
            if freq_out_raw is not None
            else 0.0
        )
        decoded = self._decode_status(status_word, fault_word)
        self._note_success()

        return {
            **decoded,
            "freq_out_hz": freq_out_hz,
        }
