from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QTimer, Signal

from brakovka_hmi.bridge import LocalBridge
from brakovka_hmi.snapshot import MachineSnapshot

log = logging.getLogger(__name__)


class PollService(QObject):
    snapshot = Signal(object)
    settings = Signal(object)
    connection_changed = Signal(bool)

    def __init__(
        self,
        bridge: LocalBridge,
        *,
        fast_interval_ms: int = 200,
        settings_interval_ms: int = 2000,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._bridge = bridge
        self._connected = False
        self._settings_ticks = 0
        self._settings_every = max(1, settings_interval_ms // max(1, fast_interval_ms))

        self._timer = QTimer(self)
        self._timer.setInterval(fast_interval_ms)
        self._timer.timeout.connect(self._tick)

    def start(self) -> None:
        self._timer.start()
        self._tick()

    def stop(self) -> None:
        self._timer.stop()

    def _tick(self) -> None:
        try:
            snap = self._bridge.read_snapshot()
        except Exception:
            log.exception("HMI snapshot failed")
            snap = MachineSnapshot(connected=False)

        connected = bool(snap.connected)
        if connected != self._connected:
            self._connected = connected
            self.connection_changed.emit(connected)

        self.snapshot.emit(snap)

        self._settings_ticks += 1
        if connected and self._settings_ticks >= self._settings_every:
            self._settings_ticks = 0
            try:
                settings = self._bridge.read_settings()
            except Exception:
                log.exception("HMI settings read failed")
                settings = None
            if settings is not None:
                self.settings.emit(settings)
