from __future__ import annotations

from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from brakovka_hmi.bridge import LocalBridge
from brakovka_hmi.snapshot import CmdBit, MachineSnapshot
from brakovka_hmi.ui.modern.semantics import snapshot_level
from brakovka_hmi.ui.modern.widgets import CmdButton, HeroCard, PageBar, StatCard


class MainScreen(QWidget):
    def __init__(self, bridge: LocalBridge, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._bridge = bridge

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)

        self._bar = PageBar("Пульт управления")
        root.addWidget(self._bar)

        self._hero = HeroCard("Намотка потребительского ролика", "м", "length")
        root.addWidget(self._hero)

        metrics = QGridLayout()
        metrics.setHorizontalSpacing(12)
        metrics.setVerticalSpacing(12)
        self._diameter = StatCard("diameter", "Диаметр рулона", "мм")
        self._speed = StatCard("speed", "Скорость", "м/мин")
        self._remaining = StatCard("length", "Остаток", "м")
        self._target = StatCard("target", "Целевая длина", "м")
        metrics.addWidget(self._diameter, 0, 0)
        metrics.addWidget(self._speed, 0, 1)
        metrics.addWidget(self._remaining, 1, 0)
        metrics.addWidget(self._target, 1, 1)
        root.addLayout(metrics)

        self._progress = QProgressBar()
        self._progress.setRange(0, 1000)
        self._progress.setFormat("Прогресс  %p%")
        self._progress.setTextVisible(True)
        root.addWidget(self._progress)

        cmd_row = QHBoxLayout()
        cmd_row.setSpacing(10)
        self._btn_start = CmdButton("play", "Пуск", variant="ok")
        self._btn_jog = CmdButton("jog", "Jog", variant="warn")
        self._btn_rev = CmdButton("reverse", "Реверс", variant="warn")
        self._btn_stop = CmdButton("stop", "Стоп", variant="alarm")
        for btn in (self._btn_start, self._btn_jog, self._btn_rev, self._btn_stop):
            cmd_row.addWidget(btn, stretch=1)
        root.addLayout(cmd_row)

        aux = QHBoxLayout()
        self._btn_reset_wound = CmdButton("reset", "Сброс намотки")
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
        level = snapshot_level(snap)
        self._bar.set_badge(snap.state_name, level)
        self._hero.set_level(level)
        self._hero.set_value(f"{snap.wound_m:.1f}")
        self._diameter.set_value(f"{snap.diameter_mm:.0f}")
        self._speed.set_value(f"{snap.speed_mpm:.1f}")
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
