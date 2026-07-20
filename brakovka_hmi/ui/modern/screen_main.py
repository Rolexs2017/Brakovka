from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from brakovka_hmi.bridge import LocalBridge
from brakovka_hmi.snapshot import CmdBit, MachineSnapshot
from brakovka_hmi.ui.modern.widgets import HeroSpeed, MetricTile


class MainScreen(QWidget):
    """Compact operator dashboard — speed hero + metrics grid."""

    def __init__(self, bridge: LocalBridge, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._bridge = bridge

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        top = QHBoxLayout()
        title = QLabel("Пульт")
        title.setObjectName("pageTitle")
        self._state = QLabel("ОЖИДАНИЕ")
        self._state.setObjectName("stateChip")
        top.addWidget(title)
        top.addStretch()
        top.addWidget(self._state)
        root.addLayout(top)

        self._hero = HeroSpeed()
        root.addWidget(self._hero)

        metrics = QGridLayout()
        metrics.setHorizontalSpacing(10)
        metrics.setVerticalSpacing(10)
        self._diameter = MetricTile("Диаметр", "мм")
        self._wound = MetricTile("Намотка", "м")
        self._remaining = MetricTile("Остаток", "м")
        self._target = MetricTile("Цель", "м")
        metrics.addWidget(self._diameter, 0, 0)
        metrics.addWidget(self._wound, 0, 1)
        metrics.addWidget(self._remaining, 1, 0)
        metrics.addWidget(self._target, 1, 1)
        root.addLayout(metrics)

        self._progress = QProgressBar()
        self._progress.setRange(0, 1000)
        self._progress.setFormat("%p%")
        self._progress.setTextVisible(True)
        root.addWidget(self._progress)

        cmd_row = QHBoxLayout()
        cmd_row.setSpacing(8)
        self._btn_start = QPushButton("Пуск")
        self._btn_start.setObjectName("cmd")
        self._btn_jog = QPushButton("Jog")
        self._btn_jog.setObjectName("cmd")
        self._btn_rev = QPushButton("Рев")
        self._btn_rev.setObjectName("cmd")
        self._btn_stop = QPushButton("Стоп")
        self._btn_stop.setObjectName("cmdStop")
        for btn in (self._btn_start, self._btn_jog, self._btn_rev, self._btn_stop):
            cmd_row.addWidget(btn, stretch=1)
        root.addLayout(cmd_row)

        aux = QHBoxLayout()
        self._btn_reset_wound = QPushButton("Сброс намотки")
        self._btn_reset_wound.setObjectName("cmd")
        aux.addWidget(self._btn_reset_wound)
        aux.addStretch()
        root.addLayout(aux)

        self._btn_start.clicked.connect(lambda: self._bridge.pulse_command(CmdBit.START))
        self._btn_stop.clicked.connect(lambda: self._bridge.pulse_command(CmdBit.STOP))
        self._btn_jog.pressed.connect(lambda: self._bridge.set_held_command(CmdBit.JOG, True))
        self._btn_jog.released.connect(lambda: self._bridge.set_held_command(CmdBit.JOG, False))
        self._btn_rev.pressed.connect(lambda: self._bridge.set_held_command(CmdBit.REVERSE, True))
        self._btn_rev.released.connect(lambda: self._bridge.set_held_command(CmdBit.REVERSE, False))
        self._btn_reset_wound.clicked.connect(
            lambda: self._bridge.pulse_command(CmdBit.RESET_WOUND)
        )

        root.addStretch()

    def update_snapshot(self, snap: MachineSnapshot) -> None:
        self._state.setText(snap.state_name)
        self._hero.set_value(f"{snap.speed_mpm:.1f}")
        self._diameter.set_value(f"{snap.diameter_mm:.0f}")
        self._wound.set_value(f"{snap.wound_m:.1f}")
        self._remaining.set_value(f"{snap.remaining_m:.1f}")
        self._target.set_value(f"{snap.target_length_m:.0f}")
        self._progress.setValue(int(snap.progress_pct * 10))

    def set_commands_enabled(self, enabled: bool) -> None:
        for btn in (
            self._btn_start,
            self._btn_stop,
            self._btn_jog,
            self._btn_rev,
            self._btn_reset_wound,
        ):
            btn.setEnabled(enabled)
