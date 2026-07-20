from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QLabel, QVBoxLayout, QWidget

from brakovka_hmi.snapshot import MachineSnapshot, StatusFlag
from brakovka_hmi.ui.modern.widgets import FlagChip, PageBar, Panel, StatCard

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


class StatusScreen(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._lamps: list[tuple[StatusFlag, FlagChip]] = []
        self._gpio_lamps: dict[str, FlagChip] = {}
        self._last_gpio_hint = ""
        self._last_gpio_pins: tuple[int, int, int, int, int] | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)

        self._bar = PageBar("Статус оборудования")
        root.addWidget(self._bar)

        cards = QGridLayout()
        cards.setHorizontalSpacing(10)
        cards.setVerticalSpacing(10)
        self._state = StatCard("status", "Состояние")
        self._speed = StatCard("speed", "Скорость", "м/мин")
        self._motor = StatCard("motor", "Привод", "об/мин")
        self._brake = StatCard("brake", "Тормоз", "%")
        self._freq = StatCard("freq", "Частота ПЧ", "Гц")
        self._tension = StatCard("tension", "Натяжение", "Н")
        self._enc_pulses = StatCard("encoder", "Импульсы энкодера")
        cards.addWidget(self._state, 0, 0)
        cards.addWidget(self._speed, 0, 1)
        cards.addWidget(self._motor, 0, 2)
        cards.addWidget(self._brake, 1, 0)
        cards.addWidget(self._freq, 1, 1)
        cards.addWidget(self._tension, 1, 2)
        cards.addWidget(self._enc_pulses, 2, 0, 1, 3)
        root.addLayout(cards)

        flags_panel = Panel("Флаги статуса")
        flag_grid = QGridLayout()
        flag_grid.setHorizontalSpacing(8)
        flag_grid.setVerticalSpacing(8)
        cols = 2
        for i, (bit, icon_name, label, alarm) in enumerate(STATUS_ITEMS):
            chip = FlagChip(icon_name, label, alarm=alarm)
            self._lamps.append((bit, chip))
            flag_grid.addWidget(chip, i // cols, i % cols)
        flags_panel.body_layout().addLayout(flag_grid)
        root.addWidget(flags_panel)

        gpio_panel = Panel("Цифровые входы GPIO")
        gpio_body = gpio_panel.body_layout()
        self._gpio_hint = QLabel("")
        self._gpio_hint.setObjectName("hintText")
        self._gpio_hint.setWordWrap(True)
        gpio_body.addWidget(self._gpio_hint)
        gpio_grid = QGridLayout()
        gpio_grid.setHorizontalSpacing(8)
        gpio_grid.setVerticalSpacing(8)
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
            gpio_grid.addWidget(chip, i // 2, i % 2)
        gpio_body.addLayout(gpio_grid)
        root.addWidget(gpio_panel)
        root.addStretch()

    def update_snapshot(self, snap: MachineSnapshot) -> None:
        self._bar.set_badge(snap.state_name)
        self._state.set_value(snap.state_name)
        self._speed.set_value(f"{snap.speed_mpm:.1f}")
        self._motor.set_value(f"{snap.motor_cmd_rpm:.1f}")
        self._brake.set_value(f"{snap.brake_pct:.1f}")
        self._freq.set_value(f"{snap.vfd_freq_out_hz:.1f}")
        self._tension.set_value(f"{snap.tension_n:.1f}")
        self._enc_pulses.set_value(f"{snap.encoder_pulses}")

        flags = snap.status_flags
        for bit, chip in self._lamps:
            chip.set_active(bool(flags & bit))

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
            hint = (
                f"Зелёный — кнопка нажата (active LOW). Pin factory: {factory}."
            )
        else:
            detail = snap.gpio_error.strip()
            if not detail:
                detail = "нет связи с контроллером" if not snap.connected else "GPIO не опубликован"
            hint = f"GPIO недоступен: {detail}"
        if hint != self._last_gpio_hint:
            self._last_gpio_hint = hint
            self._gpio_hint.setText(hint)

        self._gpio_lamps["start"].set_active(snap.gpio_available and snap.gpio_start)
        self._gpio_lamps["stop"].set_active(snap.gpio_available and snap.gpio_stop)
        self._gpio_lamps["jog"].set_active(snap.gpio_available and snap.gpio_jog)
        self._gpio_lamps["reverse"].set_active(snap.gpio_available and snap.gpio_reverse)
        self._gpio_lamps["reset_wound"].set_active(
            snap.gpio_available and snap.gpio_reset_wound
        )
