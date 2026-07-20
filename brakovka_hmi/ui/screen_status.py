from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QLabel, QVBoxLayout, QWidget

from brakovka_hmi.snapshot import MachineSnapshot, StatusFlag
from brakovka_hmi.ui.widgets import StatusLamp, ValueCard


STATUS_ITEMS = [
    (StatusFlag.RUNNING, "Станок в работе (RUN)"),
    (StatusFlag.MOVING, "Движение"),
    (StatusFlag.BRAKE, "Тормоз активен"),
    (StatusFlag.ENCODER_ERROR, "Ошибка энкодера"),
    (StatusFlag.MAGNET_ERROR, "Ошибка магнита AS5600"),
    (StatusFlag.EMULATOR, "Режим эмулятора"),
    (StatusFlag.WATCHDOG, "Сбой Watchdog"),
    (StatusFlag.VFD_FAULT, "Авария ПЧ"),
    (StatusFlag.VFD_WARNING, "Предупреждение ПЧ"),
    (StatusFlag.MODBUS_ERROR, "Ошибка Modbus (нет связи с ПЧ)"),
]


class StatusScreen(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._lamps: list[tuple[StatusFlag, StatusLamp]] = []
        self._gpio_lamps: dict[str, StatusLamp] = {}
        self._last_gpio_hint = ""
        self._last_gpio_pins: tuple[int, int, int, int, int] | None = None

        root = QVBoxLayout(self)
        root.setSpacing(8)
        title = QLabel("Статус")
        title.setObjectName("screenTitle")
        root.addWidget(title)

        cards = QGridLayout()
        cards.setHorizontalSpacing(12)
        cards.setVerticalSpacing(12)
        self._state = ValueCard("Состояние автомата")
        self._speed = ValueCard("Скорость", "м/мин")
        self._motor = ValueCard("Привод", "об/мин")
        self._brake = ValueCard("Тормоз", "%")
        self._freq = ValueCard("Частота ПЧ", "Гц")
        self._tension = ValueCard("Натяжение", "Н")
        self._enc_pulses = ValueCard("Импульсы энкодера (накопительный)")
        cards.addWidget(self._state, 0, 0)
        cards.addWidget(self._speed, 0, 1)
        cards.addWidget(self._motor, 1, 0)
        cards.addWidget(self._brake, 1, 1)
        cards.addWidget(self._freq, 2, 0)
        cards.addWidget(self._tension, 2, 1)
        cards.addWidget(self._enc_pulses, 3, 0)
        root.addLayout(cards)

        lamps_title = QLabel("Флаги статуса")
        lamps_title.setStyleSheet("color: #8aa4b8; margin-top: 4px;")
        root.addWidget(lamps_title)

        lamp_grid = QGridLayout()
        lamp_grid.setHorizontalSpacing(12)
        lamp_grid.setVerticalSpacing(4)
        lamp_cols = 3
        for i, (bit, label) in enumerate(STATUS_ITEMS):
            lamp = StatusLamp(label)
            self._lamps.append((bit, lamp))
            lamp_grid.addWidget(lamp, i // lamp_cols, i % lamp_cols)
        root.addLayout(lamp_grid)

        gpio_title = QLabel("Цифровые входы GPIO (кнопки)")
        gpio_title.setStyleSheet("color: #8aa4b8; margin-top: 8px;")
        root.addWidget(gpio_title)

        self._gpio_hint = QLabel("")
        self._gpio_hint.setWordWrap(True)
        self._gpio_hint.setStyleSheet("color: #8aa4b8; font-size: 9pt;")
        root.addWidget(self._gpio_hint)

        gpio_grid = QGridLayout()
        gpio_grid.setHorizontalSpacing(12)
        gpio_grid.setVerticalSpacing(4)
        gpio_items = [
            ("start", "GPIO 23 — Старт"),
            ("stop", "GPIO 24 — Стоп"),
            ("jog", "GPIO 25 — JOG"),
            ("reverse", "GPIO 8 — Реверс"),
            ("reset_wound", "GPIO 7 — Сброс метража потребителя"),
        ]
        for i, (key, label) in enumerate(gpio_items):
            lamp = StatusLamp(label)
            self._gpio_lamps[key] = lamp
            gpio_grid.addWidget(lamp, i // 3, i % 3)
        root.addLayout(gpio_grid)
        root.addStretch()

    def update_snapshot(self, snap: MachineSnapshot) -> None:
        self._state.set_value(snap.state_name)
        self._speed.set_value(f"{snap.speed_mpm:.1f}")
        self._motor.set_value(f"{snap.motor_cmd_rpm:.1f}")
        self._brake.set_value(f"{snap.brake_pct:.1f}")
        self._freq.set_value(f"{snap.vfd_freq_out_hz:.1f}")
        self._tension.set_value(f"{snap.tension_n:.1f}")
        self._enc_pulses.set_value(f"{snap.encoder_pulses}")

        flags = snap.status_flags
        for bit, lamp in self._lamps:
            lamp.set_active(bool(flags & bit))

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
                f"GPIO {pins[4]} — Сброс метража потребителя"
            )

        if snap.gpio_available:
            factory = snap.gpio_pin_factory or "?"
            hint = (
                f"Зелёный — кнопка нажата (active LOW). Pin factory: {factory}. "
                "Работают и в режиме эмуляции ПЧ/энкодера."
            )
        else:
            detail = snap.gpio_error.strip()
            if not detail:
                if not snap.connected:
                    detail = "нет связи с контроллером"
                else:
                    detail = "контроллер не опубликовал уровни GPIO"
            hint = f"GPIO недоступен: {detail}"
        if hint != self._last_gpio_hint:
            self._last_gpio_hint = hint
            self._gpio_hint.setText(hint)

        self._gpio_lamps["start"].set_active(snap.gpio_available and snap.gpio_start)
        self._gpio_lamps["stop"].set_active(snap.gpio_available and snap.gpio_stop)
        self._gpio_lamps["jog"].set_active(snap.gpio_available and snap.gpio_jog)
        self._gpio_lamps["reverse"].set_active(
            snap.gpio_available and snap.gpio_reverse
        )
        self._gpio_lamps["reset_wound"].set_active(
            snap.gpio_available and snap.gpio_reset_wound
        )
