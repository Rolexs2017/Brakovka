from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, replace
from time import monotonic
from typing import Protocol

from .modbus_rs485 import VfdCommand

log = logging.getLogger(__name__)


class VfdDevice(Protocol):
    connected: bool

    async def write_command(self, cmd: VfdCommand) -> bool: ...
    async def read_status(self) -> dict: ...
    async def reconnect(self, *, force: bool = False) -> bool: ...
    async def close(self) -> None: ...


@dataclass
class VfdIoSnapshot:
    status_word: int = 0
    error_code: int = 0
    freq_out_hz: float = 0.0
    fault: bool = False
    warning: bool = False
    write_ok: bool = True
    read_ok: bool = True


class AsyncVfdBridge:
    """
    Фоновый обмен с ПЧ: управление только кладёт команду и читает снимок.

    PID/рампа в основном цикле не ждут RS485 — write/read идут в отдельной asyncio-задаче.
    """

    def __init__(
        self,
        vfd: VfdDevice,
        *,
        cmd_period_s: float = 0.05,
        poll_period_s: float = 0.2,
        min_delta_hz: float = 0.05,
        slice_s: float = 0.005,
    ) -> None:
        self._vfd = vfd
        self._cmd_period_s = max(0.01, float(cmd_period_s))
        self._poll_period_s = max(0.05, float(poll_period_s))
        self._min_delta_hz = max(0.0, float(min_delta_hz))
        self._slice_s = max(0.002, float(slice_s))

        self._cmd = VfdCommand()
        self._force_write = True
        self._last_sent = VfdCommand()
        self._last_write_t = 0.0
        self._last_poll_t = 0.0

        self._snap = VfdIoSnapshot()
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="brakovka-vfd-io")
        log.info(
            "VFD I/O task started (cmd=%.3f s poll=%.3f s)",
            self._cmd_period_s,
            self._poll_period_s,
        )

    async def stop(self) -> None:
        self._stop.set()
        task = self._task
        if task is not None:
            try:
                await asyncio.wait_for(task, timeout=3.0)
            except Exception:
                task.cancel()
                try:
                    await task
                except Exception:
                    pass
        self._task = None
        try:
            await self._vfd.write_command(
                VfdCommand(run=False, reverse=False, speed_setpoint_hz=0.0)
            )
        except Exception:
            log.exception("VFD final stop failed")

    def set_command(self, cmd: VfdCommand, *, force: bool = False) -> None:
        """Non-blocking: store latest setpoint for the I/O task."""
        # Called from same asyncio loop as _run; no await. Use atomic replace via attrs.
        self._cmd = VfdCommand(
            run=bool(cmd.run),
            reverse=bool(cmd.reverse),
            speed_setpoint_hz=float(cmd.speed_setpoint_hz),
        )
        if force:
            self._force_write = True

    def snapshot(self) -> VfdIoSnapshot:
        return replace(self._snap)

    async def _run(self) -> None:
        while not self._stop.is_set():
            now = monotonic()
            try:
                await self._tick(now)
            except Exception:
                log.exception("VFD I/O tick failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._slice_s)
                break
            except asyncio.TimeoutError:
                pass

    async def _tick(self, now: float) -> None:
        cmd = self._cmd
        force = self._force_write
        due_period = (now - self._last_write_t) >= self._cmd_period_s
        delta = abs(cmd.speed_setpoint_hz - self._last_sent.speed_setpoint_hz)
        changed = (
            cmd.run != self._last_sent.run
            or cmd.reverse != self._last_sent.reverse
            or delta >= self._min_delta_hz
        )
        if force or due_period or changed:
            self._force_write = False
            ok = await self._vfd.write_command(cmd)
            self._last_write_t = monotonic()
            self._last_sent = VfdCommand(
                run=cmd.run,
                reverse=cmd.reverse,
                speed_setpoint_hz=cmd.speed_setpoint_hz,
            )
            self._snap = replace(
                self._snap,
                write_ok=bool(ok),
            )
            if not ok:
                await self._vfd.reconnect()

        if (now - self._last_poll_t) >= self._poll_period_s:
            self._last_poll_t = monotonic()
            st = await self._vfd.read_status()
            if st:
                self._snap = replace(
                    self._snap,
                    status_word=int(st.get("status_word", 0)),
                    error_code=int(st.get("error_code", 0)),
                    freq_out_hz=float(st.get("freq_out_hz", 0.0)),
                    fault=bool(st.get("fault", False)),
                    warning=bool(st.get("warning", False)),
                    read_ok=True,
                )
            else:
                self._snap = replace(
                    self._snap,
                    read_ok=False,
                )