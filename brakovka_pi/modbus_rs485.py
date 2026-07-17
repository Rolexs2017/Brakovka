from __future__ import annotations

import logging
import time
from dataclasses import dataclass

try:
    from serial.rs485 import RS485Settings
except Exception:  # pragma: no cover
    RS485Settings = None  # type: ignore

from pymodbus.client import AsyncModbusSerialClient
from pymodbus.exceptions import ModbusIOException

from .config import RS485_RTS0_GPIO, SerialConfig, VfdConfig

log = logging.getLogger(__name__)

DE_CONTROL_VERSION = "v6-uart-rts0-only"


@dataclass
class VfdCommand:
    run: bool = False
    reverse: bool = False
    speed_setpoint_hz: float = 0.0


class Rs485Vfd:
    """
    Async Modbus RTU over /dev/serial0 (PL011 / ttyAMA0).

    DE/RE for Waveshare SP3485 (RSE): UART0 RTS0 on **GPIO17** via pyserial
    ``RS485Settings`` (kernel auto-toggles RTS around TX).

    Wiring: TX=GPIO14, RX=GPIO15, DE/RE=GPIO17 (RTS0 ALT3).
    Enable in /boot/firmware/config.txt: ``gpio=17=a3`` (+ disable-bt).
    """

    def __init__(
        self,
        serial: SerialConfig | None = None,
        vfd: VfdConfig | None = None,
    ) -> None:
        serial = serial or SerialConfig()
        vfd = vfd or VfdConfig()

        self._de_ok = RS485Settings is not None
        self._de_error = "" if self._de_ok else "serial.rs485.RS485Settings not available"
        self._de_patched = False
        if self._de_ok:
            log.info(
                "RS485 DE via UART RTS0 (GPIO%s ALT3), active_high=%s",
                RS485_RTS0_GPIO,
                serial.rs485_active_high,
            )

        self._serial = serial
        self._vfd = vfd
        self._client = self._build_client()
        self._unit_id = serial.unit_id
        self._connected = False
        self._fail_count = 0
        self._last_reconnect_t = 0.0
        self._reconnect_period_s = float(serial.reconnect_period_s)
        self._fails_before_reconnect = max(1, int(serial.fails_before_reconnect))

    def _build_client(self) -> AsyncModbusSerialClient:
        return AsyncModbusSerialClient(
            port=self._serial.port,
            baudrate=self._serial.baudrate,
            parity=self._serial.parity,
            stopbits=self._serial.stopbits,
            bytesize=self._serial.bytesize,
            timeout=self._serial.timeout_s,
            retries=self._serial.retries,
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

    def _get_serial_transport(self):
        ctx = getattr(self._client, "ctx", None)
        transport = getattr(ctx, "transport", None) if ctx is not None else None
        if transport is None:
            transport = getattr(self._client, "transport", None)
        return transport

    def _get_pyserial(self):
        """Underlying pyserial.Serial for AsyncModbusSerialClient (if any)."""
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
                if obj is not None and hasattr(obj, "write") and hasattr(obj, "rs485_mode"):
                    return obj
                if obj is not None:
                    inner = getattr(obj, "serial", None) or getattr(obj, "_serial", None)
                    if inner is not None and hasattr(inner, "write"):
                        return inner
        return None

    def _apply_uart_rts(self) -> bool:
        """Enable kernel/pyserial RS485 RTS auto-direction (GPIO17 = RTS0)."""
        if RS485Settings is None:
            self._de_error = "RS485Settings unavailable"
            self._de_ok = False
            return False

        ser = self._get_pyserial()
        if ser is None:
            self._de_error = "pyserial handle not found after connect"
            self._de_ok = False
            log.error("RS485 %s: %s", DE_CONTROL_VERSION, self._de_error)
            return False

        active_high = bool(self._serial.rs485_active_high)
        before = float(self._serial.de_delay_before_tx_s)
        after = float(self._serial.de_turnaround_s)
        try:
            if hasattr(ser, "rtscts"):
                ser.rtscts = False
            settings = RS485Settings(
                rts_level_for_tx=active_high,
                rts_level_for_rx=not active_high,
                loopback=False,
                delay_before_tx=before if before > 0 else None,
                delay_before_rx=after if after > 0 else None,
            )
            ser.rs485_mode = settings
            self._de_ok = True
            self._de_patched = True
            self._de_error = ""
            log.info(
                "RS485 %s: UART RTS0 DE enabled (GPIO%s, rts_tx=%s delay_tx=%.3f delay_rx=%.3f)",
                DE_CONTROL_VERSION,
                RS485_RTS0_GPIO,
                active_high,
                before,
                after,
            )
            return True
        except Exception as exc:
            self._de_ok = False
            self._de_error = f"{type(exc).__name__}: {exc}"
            log.error(
                "RS485 %s: failed to set rs485_mode (RTS0): %s — "
                "check gpio=17=a3 in config.txt and DE wired to GPIO17",
                DE_CONTROL_VERSION,
                self._de_error,
            )
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
            self._apply_uart_rts()
            log.info(
                "Modbus connected %s: port=%s baud=%s unit=%s de_ok=%s de_control=%s",
                DE_CONTROL_VERSION,
                self._serial.port,
                self._serial.baudrate,
                self._unit_id,
                self._de_ok,
                self._de_patched,
            )
        else:
            log.error("Modbus connect failed: port=%s", self._serial.port)

    async def close(self) -> None:
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
        """Close and reopen Modbus serial client. Rate-limited unless force=True."""
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
