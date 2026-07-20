from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from brakovka_hmi.snapshot import MachineSnapshot, StatusFlag
from brakovka_hmi.ui.modern import icons as ic
from brakovka_hmi.ui.modern import theme as t
from brakovka_hmi.ui.modern.semantics import flag_chip_level, machine_state_level, snapshot_level
from brakovka_hmi.ui.modern.widgets import FlagChip, PageBar, SettingsTile, StatCard

PAGE_HUB = 0
PAGE_METRICS = 1
PAGE_FLAGS = 2
PAGE_GPIO = 3

STATUS_ITEMS = [
    (StatusFlag.RUNNING, "play", "Станок в работе", False),
    (StatusFlag.MOVING, "jog", "Движение", False),
    (StatusFlag.BRAKE, "brake", "Тормоз активен", False),
    (StatusFlag.ENCODER_ERROR, "encoder", "Ошибка энкодера", True),
    (StatusFlag.MAGNET_ERROR, "warning", "Ошибка магнита AS5600", True),
    (StatusFlag.EMULATOR, "service", "Режим эмулятора", False),
    (StatusFlag.WATCHDOG, "warning", "Сбой Watchdog", True),
    (StatusFlag.VFD_FAULT, "warning", "Авария ПЧ", True),
    (StatusFlag.VFD_WARNING, "warning", "Предупреждение ПЧ", True),
    (StatusFlag.MODBUS_ERROR, "warning", "Ошибка Modbus", True),
]

_PAGE_TITLES = {
    PAGE_HUB: "Статус",
    PAGE_METRICS: "Статус · Показания",
    PAGE_FLAGS: "Статус · Флаги",
    PAGE_GPIO: "Статус · GPIO",
}


class StatusScreen(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._lamps: list[tuple[StatusFlag, FlagChip, bool]] = []
        self._gpio_lamps: dict[str, FlagChip] = {}
        self._last_gpio_hint = ""
        self._last_gpio_pins: tuple[int, int, int, int, int] | None = None
        self._last_state_name = ""
        self._last_level = "neutral"

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        self._bar = PageBar("Статус")
        root.addWidget(self._bar)

        self._stack = QStackedWidget()
        root.addWidget(self._stack, stretch=1)

        self._stack.addWidget(self._build_hub_page())
        self._stack.addWidget(self._build_metrics_page())
        self._stack.addWidget(self._build_flags_page())
        self._stack.addWidget(self._build_gpio_page())

        footer = QHBoxLayout()
        self._btn_back = QPushButton("← К группам")
        self._btn_back.setObjectName("cmd")
        self._btn_back.setMinimumHeight(44)
        self._btn_back.setIcon(ic.icon("back", color=t.TEXT, size=18))
        self._btn_back.setIconSize(ic.icon_size(18))
        self._btn_back.clicked.connect(lambda: self._show_page(PAGE_HUB))
        self._btn_back.hide()
        footer.addWidget(self._btn_back)
        footer.addStretch()
        root.addLayout(footer)

        self._show_page(PAGE_HUB)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._show_page(PAGE_HUB)

    def _tile(self, icon: str, title: str, subtitle: str, page: int) -> SettingsTile:
        btn = SettingsTile(icon, title, subtitle)
        btn.clicked.connect(lambda _=False, p=page: self._show_page(p))
        return btn

    def _build_hub_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setSpacing(14)
        hint = QLabel("Выберите группу статуса")
        hint.setObjectName("hintText")
        lay.addWidget(hint)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        grid.addWidget(
            self._tile("speed", "Показания", "Скорость, привод, ПЧ, энкодер", PAGE_METRICS),
            0, 0,
        )
        grid.addWidget(
            self._tile("status", "Флаги", "Состояние станка и аварии", PAGE_FLAGS),
            0, 1,
        )
        grid.addWidget(
            self._tile("service", "GPIO", "Цифровые входы кнопок", PAGE_GPIO),
            1, 0, 1, 2,
        )
        lay.addLayout(grid)
        lay.addStretch()
        return page

    def _scroll_page(self, inner: QWidget) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(inner)
        outer.addWidget(scroll)
        return page

    def _build_metrics_page(self) -> QWidget:
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(0, 0, 4, 8)
        lay.setSpacing(10)

        cards = QGridLayout()
        cards.setHorizontalSpacing(10)
        cards.setVerticalSpacing(10)
        self._state = StatCard("status", "Состояние", compact=True)
        self._speed = StatCard("speed", "Скорость", "м/мин", compact=True)
        self._motor = StatCard("motor", "Привод", "об/мин", compact=True)
        self._brake = StatCard("brake", "Тормоз", "%", compact=True)
        self._freq = StatCard("freq", "Частота ПЧ", "Гц", compact=True)
        self._tension = StatCard("tension", "Натяжение", "Н", compact=True)
        self._enc_pulses = StatCard("encoder", "Импульсы энкодера", compact=True)
        cards.addWidget(self._state, 0, 0)
        cards.addWidget(self._speed, 0, 1)
        cards.addWidget(self._motor, 1, 0)
        cards.addWidget(self._brake, 1, 1)
        cards.addWidget(self._freq, 2, 0)
        cards.addWidget(self._tension, 2, 1)
        cards.addWidget(self._enc_pulses, 3, 0, 1, 2)
        lay.addLayout(cards)
        lay.addStretch()
        return self._scroll_page(inner)

    def _build_flags_page(self) -> QWidget:
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(0, 0, 4, 8)
        lay.setSpacing(10)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        cols = 2
        for i, (bit, icon_name, label, alarm) in enumerate(STATUS_ITEMS):
            chip = FlagChip(icon_name, label, alarm=alarm)
            self._lamps.append((bit, chip, alarm))
            grid.addWidget(chip, i // cols, i % cols)
        lay.addLayout(grid)
        lay.addStretch()
        return self._scroll_page(inner)

    def _build_gpio_page(self) -> QWidget:
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(0, 0, 4, 8)
        lay.setSpacing(10)

        self._gpio_hint = QLabel("")
        self._gpio_hint.setObjectName("hintText")
        self._gpio_hint.setWordWrap(True)
        lay.addWidget(self._gpio_hint)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        cols = 2
        gpio_items = [
            ("start", "play", "GPIO 23 — Старт"),
            ("stop", "stop", "GPIO 24 — Стоп"),
            ("jog", "jog", "GPIO 25 — JOG"),
            ("reverse", "reverse", "GPIO 8 — Реверс"),
            ("reset_wound", "reset", "GPIO 7 — Сброс метража"),
        ]
        for i, (key, icon_name, label) in enumerate(gpio_items):
            chip = FlagChip(icon_name, label)
            self._gpio_lamps[key] = chip
            grid.addWidget(chip, i // cols, i % cols)
        lay.addLayout(grid)
        lay.addStretch()
        return self._scroll_page(inner)

    def _show_page(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        self._bar.set_title(_PAGE_TITLES.get(index, "Статус"))
        self._btn_back.setVisible(index != PAGE_HUB)
        if self._last_state_name:
            self._bar.set_badge(self._last_state_name, self._last_level)

    def update_snapshot(self, snap: MachineSnapshot) -> None:
        self._last_state_name = snap.state_name
        level = snapshot_level(snap)
        self._last_level = level
        self._bar.set_badge(snap.state_name, level)

        state_level = machine_state_level(snap.state)
        self._state.set_value(snap.state_name)
        self._state.set_level(state_level)
        self._speed.set_value(f"{snap.speed_mpm:.1f}")
        self._motor.set_value(f"{snap.motor_cmd_rpm:.1f}")
        self._brake.set_value(f"{snap.brake_pct:.1f}")
        self._freq.set_value(f"{snap.vfd_freq_out_hz:.1f}")
        self._tension.set_value(f"{snap.tension_n:.1f}")
        self._enc_pulses.set_value(f"{snap.encoder_pulses}")

        flags = snap.status_flags
        for bit, chip, alarm in self._lamps:
            active = bool(flags & bit)
            chip.set_chip_level(flag_chip_level(bit, active, alarm=alarm))

        pins = (
            snap.gpio_pin_start,
            snap.gpio_pin_stop,
            snap.gpio_pin_jog,
            snap.gpio_pin_reverse,
            snap.gpio_pin_reset_wound,
        )
        if pins != self._last_gpio_pins:
            self._last_gpio_pins = pins
            self._gpio_lamps["start"].set_label(f"GPIO {pins[0]} — Старт")
            self._gpio_lamps["stop"].set_label(f"GPIO {pins[1]} — Стоп")
            self._gpio_lamps["jog"].set_label(f"GPIO {pins[2]} — JOG")
            self._gpio_lamps["reverse"].set_label(f"GPIO {pins[3]} — Реверс")
            self._gpio_lamps["reset_wound"].set_label(
                f"GPIO {pins[4]} — Сброс метража"
            )

        if snap.gpio_available:
            factory = snap.gpio_pin_factory or "?"
            hint = f"Зелёный — кнопка нажата (active LOW). Pin factory: {factory}."
        else:
            detail = snap.gpio_error.strip()
            if not detail:
                detail = "нет связи с контроллером" if not snap.connected else "GPIO не опубликован"
            hint = f"GPIO недоступен: {detail}"
        if hint != self._last_gpio_hint:
            self._last_gpio_hint = hint
            self._gpio_hint.setText(hint)

        self._gpio_lamps["start"].set_chip_level("ok" if snap.gpio_available and snap.gpio_start else "off")
        self._gpio_lamps["stop"].set_chip_level("ok" if snap.gpio_available and snap.gpio_stop else "off")
        self._gpio_lamps["jog"].set_chip_level("ok" if snap.gpio_available and snap.gpio_jog else "off")
        self._gpio_lamps["reverse"].set_chip_level(
            "ok" if snap.gpio_available and snap.gpio_reverse else "off"
        )
        self._gpio_lamps["reset_wound"].set_chip_level(
            "ok" if snap.gpio_available and snap.gpio_reset_wound else "off"
        )
