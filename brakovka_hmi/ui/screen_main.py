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
from brakovka_hmi.ui.widgets import ValueCard


class MainScreen(QWidget):
    def __init__(self, bridge: LocalBridge, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._bridge = bridge

        root = QVBoxLayout(self)
        root.setSpacing(8)
        title = QLabel("Главный")
        title.setObjectName("screenTitle")
        root.addWidget(title)

        self._state = QLabel("ОЖИДАНИЕ")
        self._state.setObjectName("stateBadge")
        self._state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self._state)

        cards = QGridLayout()
        cards.setHorizontalSpacing(12)
        cards.setVerticalSpacing(12)
        self._speed = ValueCard("Скорость", "м/мин")
        self._diameter = ValueCard("Диаметр рулона", "мм")
        self._wound = ValueCard("Намотка", "м")
        self._remaining = ValueCard("Остаток", "м")
        self._target = ValueCard("Уставка потребителя", "м")
        cards.addWidget(self._speed, 0, 0)
        cards.addWidget(self._diameter, 0, 1)
        cards.addWidget(self._wound, 1, 0)
        cards.addWidget(self._remaining, 1, 1)
        cards.addWidget(self._target, 2, 0, 1, 2)
        root.addLayout(cards)

        self._progress = QProgressBar()
        self._progress.setRange(0, 1000)
        self._progress.setFormat("Прогресс длины: %p%")
        root.addWidget(self._progress)

        cmd_row = QHBoxLayout()
        self._btn_start = QPushButton("ПУСК")
        self._btn_start.setObjectName("cmd")
        self._btn_stop = QPushButton("СТОП")
        self._btn_stop.setObjectName("cmdStop")
        self._btn_jog = QPushButton("ТОЛЧОК (JOG)")
        self._btn_jog.setObjectName("cmd")
        self._btn_rev = QPushButton("РЕВЕРС")
        self._btn_rev.setObjectName("cmd")

        for btn in (self._btn_start, self._btn_jog, self._btn_rev):
            cmd_row.addWidget(btn)
        cmd_row.addWidget(self._btn_stop)
        root.addLayout(cmd_row)

        reset_row = QHBoxLayout()
        self._btn_reset_wound = QPushButton("Сброс намотки")
        self._btn_reset_wound.setObjectName("cmd")
        reset_row.addWidget(self._btn_reset_wound)
        reset_row.addStretch()
        root.addLayout(reset_row)

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
        self._speed.set_value(f"{snap.speed_mpm:.1f}")
        self._diameter.set_value(f"{snap.diameter_mm:.0f}")
        self._wound.set_value(f"{snap.wound_m:.2f}")
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
