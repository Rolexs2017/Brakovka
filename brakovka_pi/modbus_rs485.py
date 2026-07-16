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

from .config import SerialConfig, VfdConfig

log = logging.getLogger(__name__)

# Bump when changing DE logic — printed at connect so Pi file version is obvious.
DE_CONTROL_VERSION = "v4-timer+ctx.transport"


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
    Async Modbus RTU over /dev/serial0 with Waveshare SP3485 RSE on GPIO (DE).

    Half-duplex: RSE/DE must go LOW before the slave reply, or the Pi never sees RX.
    Primary DE release: threading.Timer from trace_packet (works on pymodbus 3.x).
    Secondary: patch client.ctx.transport.intern_write_ready when available.
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
        self._de_patched = False

        if DigitalOutputDevice is not None:
            _ensure_pin_factory()
            try:
                self._de = DigitalOutputDevice(
                    serial.rs485_de,
                    active_high=bool(serial.rs485_active_high),
                    initial_value=False,
                )
                self._de_ok = True
                log.info(
                    "RS485 RSE/DE on GPIO%s ready (active_high=%s)",
                    serial.rs485_de,
                    serial.rs485_active_high,
                )
            except Exception as exc:
                self._de = _DummyDe()
                self._de_error = f"{type(exc).__name__}: {exc}"
                log.error("RS485 DE GPIO%s unavailable: %s", serial.rs485_de, self._de_error)
        else:
            self._de_error = "gpiozero.DigitalOutputDevice not importable"

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

    def _rx_mode(self) -> None:
        try:
            self._de.off()
        except Exception:
            pass

    def _tx_mode(self) -> None:
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

    def _frame_time_s(self, nbytes: int) -> float:
        baud = max(1.0, float(self._serial.baudrate))
        return (max(0, int(nbytes)) * 10.0) / baud

    def _arm_de_rx_after_tx(self, nbytes: int) -> None:
        """Drop RSE to RX after on-wire time (+ slack for async UART write)."""
        self._cancel_de_timer()
        delay = (
            self._frame_time_s(nbytes)
            + float(self._serial.de_turnaround_s)
            + 0.020  # pymodbus async scheduling slack
        )
        timer = threading.Timer(delay, self._rx_mode)
        timer.daemon = True
        self._de_timer = timer
        timer.start()

    def _trace_packet(self, sending: bool, data: bytes) -> bytes:
        if sending and data:
            self._tx_mode()
            before = float(self._serial.de_delay_before_tx_s)
            if before > 0:
                time.sleep(before)
            self._arm_de_rx_after_tx(len(data))
            self._de_patched = True  # timer path is active
        elif not sending:
            self._cancel_de_timer()
            self._rx_mode()
        return data

    def _get_serial_transport(self):
        ctx = getattr(self._client, "ctx", None)
        transport = getattr(ctx, "transport", None) if ctx is not None else None
        if transport is None:
            transport = getattr(self._client, "transport", None)
        return transport

    def _patch_de_turnaround(self) -> None:
        """Optional sharper DE drop via SerialTransport.intern_write_ready."""
        transport = self._get_serial_transport()
        if transport is None:
            log.warning(
                "RS485 %s: ctx.transport missing — using trace_packet Timer only",
                DE_CONTROL_VERSION,
            )
            return

        log.info(
            "RS485 %s transport=%s has_iwr=%s",
            DE_CONTROL_VERSION,
            type(transport).__name__,
            hasattr(transport, "intern_write_ready"),
        )

        if not hasattr(transport, "intern_write_ready"):
            return

        before_s = float(self._serial.de_delay_before_tx_s)
        after_s = float(self._serial.de_turnaround_s)
        frame_time = self._frame_time_s
        tx = self._tx_mode
        rx = self._rx_mode
        cancel = self._cancel_de_timer

        if hasattr(transport, "write"):
            orig_write = transport.write

            def write_de(data) -> None:  # noqa: ANN001
                cancel()
                tx()
                if before_s > 0:
                    time.sleep(before_s)
                orig_write(data)

            transport.write = write_de  # type: ignore[method-assign]

        orig_iwr = transport.intern_write_ready

        def intern_write_ready_de() -> None:
            pending = b""
            buf = getattr(transport, "intern_write_buffer", None)
            if buf:
                pending = b"".join(buf)
            nbytes = len(pending)
            orig_iwr()
            if getattr(transport, "get_write_buffer_size", lambda: 0)() == 0 and nbytes:
                cancel()
                time.sleep(frame_time(nbytes) + after_s)
                rx()

        transport.intern_write_ready = intern_write_ready_de  # type: ignore[method-assign]
        self._de_patched = True
        log.info("RS485 %s: intern_write_ready patch installed", DE_CONTROL_VERSION)

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
            self._patch_de_turnaround()
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
            # Force full reopen on next ensure_connected (stale transport / hung port).
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
            # Delta CP2000: frequency (2001H) then operation command (2000H).
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
