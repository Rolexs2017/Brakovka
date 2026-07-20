from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

try:
    from gpiozero import DigitalOutputDevice  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    DigitalOutputDevice = None

from pymodbus.client import AsyncModbusSerialClient
from pymodbus.exceptions import ModbusIOException

from .config import RS485_DE_GPIO, SerialConfig, VfdConfig

log = logging.getLogger(__name__)

# UART+GPIO DE or USB RS485 (auto DE when rs485_de is null).
DE_CONTROL_VERSION = "v11-usb-or-gpio-de"


@dataclass
class VfdCommand:
    run: bool = False
    reverse: bool = False
    speed_setpoint_hz: float = 0.0


def _ensure_pin_factory() -> None:
    try:
        from .gpio_io import _configure_pin_factory

        _configure_pin_factory(probe_pin=23)
    except Exception as exc:
        log.warning("Pin factory setup for RS485 DE failed: %s", exc)


class Rs485Vfd:
    """
    Async Modbus RTU over serial port.

    * **USB RS485** (``rs485_de: null``): adapter auto-switches DE; no GPIO.
    * **SP3485 on GPIO14/15/16**: software DE on ``rs485_de`` (default GPIO16).
    """

    def __init__(
        self,
        serial: SerialConfig | None = None,
        vfd: VfdConfig | None = None,
    ) -> None:
        serial = serial or SerialConfig()
        vfd = vfd or VfdConfig()

        class _DummyDe:
            def on(self) -> None: ...

            def off(self) -> None: ...

        self._de = _DummyDe()
        self._de_ok = False
        self._de_error = ""
        self._de_timer: threading.Timer | None = None
        raw_de = getattr(serial, "rs485_de", RS485_DE_GPIO)
        self._de_pin: int | None = int(raw_de) if raw_de is not None and int(raw_de) > 0 else None
        self._use_gpio_de = self._de_pin is not None

        if self._use_gpio_de:
            if DigitalOutputDevice is not None:
                _ensure_pin_factory()
                try:
                    self._de = DigitalOutputDevice(
                        self._de_pin,
                        active_high=bool(serial.rs485_active_high),
                        initial_value=False,
                    )
                    self._de_ok = True
                    log.info(
                        "RS485 DE on GPIO%s ready (software, active_high=%s)",
                        self._de_pin,
                        serial.rs485_active_high,
                    )
                except Exception as exc:
                    self._de = _DummyDe()
                    self._de_error = f"{type(exc).__name__}: {exc}"
                    log.error("RS485 DE GPIO%s unavailable: %s", self._de_pin, self._de_error)
            else:
                self._de_error = "gpiozero.DigitalOutputDevice not importable"
        else:
            self._de_ok = True
            log.info("RS485 USB/auto DE on %s (no GPIO)", serial.port)

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
        kwargs: dict = dict(
            port=self._serial.port,
            baudrate=self._serial.baudrate,
            parity=self._serial.parity,
            stopbits=self._serial.stopbits,
            bytesize=self._serial.bytesize,
            timeout=self._serial.timeout_s,
            retries=self._serial.retries,
        )
        if self._use_gpio_de:
            kwargs["trace_packet"] = self._trace_packet
        return AsyncModbusSerialClient(**kwargs)

    @property
    def de_ok(self) -> bool:
        return self._de_ok

    @property
    def de_error(self) -> str:
        return self._de_error

    @property
    def connected(self) -> bool:
        return self._client_alive()

    def _rx_mode(self) -> None:
        if not self._use_gpio_de:
            return
        try:
            self._de.off()
        except Exception:
            pass

    def _tx_mode(self) -> None:
        if not self._use_gpio_de:
            return
        try:
            self._de.on()
        except Exception:
            pass

    def _cancel_de_timer(self) -> None:
        t = self._de_timer
        self._de_timer = None
        if t is not None:
            try:
                t.cancel()
            except Exception:
                pass

    def _get_pyserial(self):
        ctx = getattr(self._client, "ctx", None)
        transport = getattr(ctx, "transport", None) if ctx is not None else None
        if transport is None:
            transport = getattr(self._client, "transport", None)
        if transport is not None:
            for name in ("serial", "_serial", "sync_serial"):
                ser = getattr(transport, name, None)
                if ser is not None and hasattr(ser, "write"):
                    return ser
        return None

    def _flush_rx(self) -> None:
        ser = self._get_pyserial()
        if ser is None:
            return
        try:
            ser.reset_input_buffer()
        except Exception:
            pass

    def _discard_tx_echo(self, nbytes: int) -> None:
        ser = self._get_pyserial()
        if ser is None or nbytes <= 0:
            return
        try:
            n = int(getattr(ser, "in_waiting", 0) or 0)
            if n <= 0:
                return
            junk = ser.read(min(n, int(nbytes)))
            if junk:
                log.debug("RS485 discarded %s echo byte(s)", len(junk))
        except Exception:
            pass

    def _frame_time_s(self, nbytes: int) -> float:
        baud = max(1.0, float(self._serial.baudrate))
        return (max(0, int(nbytes)) * 10.0) / baud

    def _switch_to_rx_after_tx(self, nbytes: int) -> None:
        self._rx_mode()
        time.sleep(0.001)
        self._discard_tx_echo(int(nbytes))

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
            self._flush_rx()
            self._tx_mode()
            before = float(self._serial.de_delay_before_tx_s)
            if before > 0:
                time.sleep(before)
            self._arm_rx_after_tx(len(data))
        elif not sending:
            self._cancel_de_timer()
            self._rx_mode()
        return data

    def _disable_kernel_rs485(self) -> None:
        """Ensure UART is not in RTS0 RS485 mode (would fight GPIO DE)."""
        ser = self._get_pyserial()
        if ser is None:
            return
        try:
            if hasattr(ser, "rs485_mode"):
                ser.rs485_mode = None
        except Exception:
            pass
        try:
            if hasattr(ser, "rtscts"):
                ser.rtscts = False
        except Exception:
            pass

    async def connect(self) -> None:
        if self._connected and bool(getattr(self._client, "connected", False)):
            return
        self._rx_mode()
        try:
            await self._client.connect()
        except Exception as exc:
            self._connected = False
            log.error("Modbus connect exception: port=%s err=%s", self._serial.port, exc)
            return
        self._connected = bool(getattr(self._client, "connected", False))
        if self._connected:
            self._fail_count = 0
            self._disable_kernel_rs485()
            self._rx_mode()
            log.info(
                "Modbus connected %s: port=%s baud=%s unit=%s de_mode=%s de_ok=%s",
                DE_CONTROL_VERSION,
                self._serial.port,
                self._serial.baudrate,
                self._unit_id,
                f"GPIO{self._de_pin}" if self._use_gpio_de else "USB/auto",
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
