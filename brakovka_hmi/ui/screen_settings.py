from __future__ import annotations

import os
import sys

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from brakovka_hmi.bridge import LocalBridge
from brakovka_hmi.snapshot import MOVING_STATES, MachineSnapshot
from brakovka_hmi.sounds import play_error, play_ok
from brakovka_hmi.ui.form_guard import EditableFormMixin
from brakovka_hmi.ui.virtual_keyboard import TouchDoubleSpinBox, TouchSpinBox


class SettingsScreen(EditableFormMixin, QWidget):
    quit_requested = Signal()
    dirty_changed = Signal(bool)

    def __init__(self, bridge: LocalBridge, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._bridge = bridge
        self._emu_desired = False

        root = QVBoxLayout(self)
        root.setSpacing(8)
        title_row = QHBoxLayout()
        title = QLabel("Настройки")
        title.setObjectName("screenTitle")
        title_row.addWidget(title)
        title_row.addStretch()
        self._dirty_label = QLabel("")
        self._dirty_label.setStyleSheet("color: #ffb020; font-size: 11pt; font-weight: 600;")
        title_row.addWidget(self._dirty_label)
        root.addLayout(title_row)

        params_row = QHBoxLayout()
        params_row.setSpacing(16)

        left_form = QFormLayout()
        left_form.setVerticalSpacing(4)
        left_form.setHorizontalSpacing(10)
        left_form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint
        )
        right_form = QFormLayout()
        right_form.setVerticalSpacing(4)
        right_form.setHorizontalSpacing(10)
        right_form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint
        )

        field_w = 140

        self._speed = TouchDoubleSpinBox(keypad_title="Рабочая скорость")
        self._speed.setRange(0.0, 500.0)
        self._speed.setDecimals(1)
        self._speed.setSuffix(" м/мин")

        self._tension = TouchSpinBox(keypad_title="Натяжение")
        self._tension.setRange(0, 10000)
        self._tension.setSuffix(" Н")

        self._jog = TouchDoubleSpinBox(keypad_title="Скорость JOG")
        self._jog.setRange(0.0, 100.0)
        self._jog.setDecimals(1)
        self._jog.setSuffix(" м/мин")

        self._reverse = TouchDoubleSpinBox(keypad_title="Скорость реверса")
        self._reverse.setRange(0.0, 100.0)
        self._reverse.setDecimals(1)
        self._reverse.setSuffix(" м/мин")

        self._slowdown = TouchDoubleSpinBox(keypad_title="Скорость замедления")
        self._slowdown.setRange(0.0, 100.0)
        self._slowdown.setDecimals(1)
        self._slowdown.setSuffix(" м/мин")

        self._accel = TouchDoubleSpinBox(keypad_title="Время разгона")
        self._accel.setRange(0.1, 120.0)
        self._accel.setDecimals(1)
        self._accel.setSuffix(" с")

        self._decel = TouchDoubleSpinBox(keypad_title="Время торможения")
        self._decel.setRange(0.1, 120.0)
        self._decel.setDecimals(1)
        self._decel.setSuffix(" с")

        self._brake_delay = TouchDoubleSpinBox(keypad_title="Выдержка тормоза")
        self._brake_delay.setRange(0.0, 60.0)
        self._brake_delay.setDecimals(1)
        self._brake_delay.setSuffix(" с")

        self._kp = TouchDoubleSpinBox(keypad_title="PID Kp")
        self._kp.setRange(0.0, 100.0)
        self._kp.setDecimals(2)

        self._ti = TouchDoubleSpinBox(keypad_title="PID Ti")
        self._ti.setRange(0.0, 100.0)
        self._ti.setDecimals(2)

        self._kd = TouchDoubleSpinBox(keypad_title="PID Kd")
        self._kd.setRange(0.0, 100.0)
        self._kd.setDecimals(2)

        self._roll_dia = TouchSpinBox(keypad_title="Диаметр мерительного ролика")
        self._roll_dia.setRange(20, 1000)
        self._roll_dia.setSuffix(" мм")

        for w in (
            self._speed,
            self._tension,
            self._jog,
            self._reverse,
            self._slowdown,
            self._accel,
            self._decel,
            self._brake_delay,
            self._kp,
            self._ti,
            self._kd,
            self._roll_dia,
        ):
            w.setFixedWidth(field_w)

        left_form.addRow("Рабочая скорость", self._speed)
        left_form.addRow("Натяжение", self._tension)
        left_form.addRow("Скорость JOG", self._jog)
        left_form.addRow("Скорость реверса", self._reverse)
        left_form.addRow("Скорость замедления", self._slowdown)
        left_form.addRow("Время разгона", self._accel)

        right_form.addRow("Время торможения", self._decel)
        right_form.addRow("Выдержка тормоза", self._brake_delay)
        right_form.addRow("PID Kp", self._kp)
        right_form.addRow("PID Ti", self._ti)
        right_form.addRow("PID Kd", self._kd)
        right_form.addRow("Диаметр мерн. ролика", self._roll_dia)

        params_row.addLayout(left_form, stretch=1)
        params_row.addLayout(right_form, stretch=1)
        root.addLayout(params_row)

        cal_box = QVBoxLayout()
        cal_box.setSpacing(4)
        cal_title = QLabel("Калибровка мерного ролика")
        cal_title.setStyleSheet("color: #8aa4b8; margin-top: 2px;")
        cal_box.addWidget(cal_title)

        cal_row = QHBoxLayout()
        cal_row.setSpacing(10)
        self._cal_pulses = QLabel("Импульсы: —")
        self._cal_pulses.setStyleSheet("color: #e8f1f8; font-size: 11pt;")
        self._cal_length = TouchDoubleSpinBox(keypad_title="Фактическая длина")
        self._cal_length.setRange(0.01, 10000.0)
        self._cal_length.setDecimals(2)
        self._cal_length.setSuffix(" м")
        self._cal_length.setValue(10.0)
        self._cal_length.setFixedWidth(field_w)
        self._btn_calibrate = QPushButton("Калибровать ролик")
        self._btn_calibrate.setObjectName("cmd")
        cal_row.addWidget(self._cal_pulses)
        cal_row.addWidget(QLabel("Факт. длина"))
        cal_row.addWidget(self._cal_length)
        cal_row.addWidget(self._btn_calibrate)
        cal_row.addStretch()
        cal_box.addLayout(cal_row)
        root.addLayout(cal_box)

        invert_row = QHBoxLayout()
        invert_row.setSpacing(12)
        self._btn_invert = QPushButton()
        self._btn_invert.setObjectName("cmd")
        self._btn_invert.setMinimumWidth(280)
        self._invert_hint = QLabel(
            "Меняет знак направления мерного ролика (намотка / размотка). "
            "Применяется сразу."
        )
        self._invert_hint.setWordWrap(True)
        self._invert_hint.setStyleSheet("color: #8aa4b8; font-size: 9pt;")
        invert_row.addWidget(self._btn_invert)
        invert_row.addWidget(self._invert_hint, stretch=1)
        root.addLayout(invert_row)

        emu_row = QHBoxLayout()
        emu_row.setSpacing(12)
        self._btn_emu = QPushButton()
        self._btn_emu.setObjectName("cmd")
        self._btn_emu.setMinimumWidth(220)
        self._emu_hint = QLabel("")
        self._emu_hint.setWordWrap(True)
        self._emu_hint.setStyleSheet("color: #8aa4b8; font-size: 9pt;")
        emu_row.addWidget(self._btn_emu)
        emu_row.addWidget(self._emu_hint, stretch=1)
        root.addLayout(emu_row)

        btn_row = QHBoxLayout()
        self._btn_save = QPushButton("Сохранить уставки")
        self._btn_save.setObjectName("primary")
        self._btn_quit = QPushButton("Закрыть приложение")
        self._btn_quit.setObjectName("cmdStop")
        btn_row.addWidget(self._btn_save)
        btn_row.addStretch()
        btn_row.addWidget(self._btn_quit)
        root.addLayout(btn_row)

        self._btn_save.clicked.connect(self._save)
        self._btn_quit.clicked.connect(self.quit_requested.emit)
        self._btn_emu.clicked.connect(self._toggle_emulator)
        self._btn_invert.clicked.connect(self._toggle_encoder_invert)
        self._btn_calibrate.clicked.connect(self._calibrate_roll)

        self._last_pulses = 0
        self._encoder_invert = False
        self._form_widgets_list = (
            self._speed,
            self._tension,
            self._jog,
            self._reverse,
            self._slowdown,
            self._accel,
            self._decel,
            self._brake_delay,
            self._kp,
            self._ti,
            self._kd,
            self._roll_dia,
        )
        self._init_form_guard(
            list(self._form_widgets_list),
            dirty_changed=self._on_dirty_changed,
        )
        root.addStretch()
        self._refresh_emulator_ui()
        self._refresh_invert_ui()

    def showEvent(self, event) -> None:  # noqa: ANN001
        super().showEvent(event)
        self._refresh_emulator_ui()
        self._refresh_invert_ui()

    def update_snapshot(self, snap: MachineSnapshot) -> None:
        self._last_pulses = int(snap.encoder_pulses)
        self._cal_pulses.setText(f"Импульсы: {self._last_pulses}")
        moving = snap.state in MOVING_STATES
        self._btn_calibrate.setEnabled(snap.connected and not moving)
        self._btn_invert.setEnabled(snap.connected)

    def _on_dirty_changed(self, dirty: bool) -> None:
        self._dirty_label.setText("Не сохранено" if dirty else "")

    def _calibrate_roll(self) -> None:
        length_m = float(self._cal_length.value())
        pulses = self._last_pulses
        if pulses <= 0 or length_m <= 0:
            play_error()
            QMessageBox.warning(
                self,
                "Калибровка",
                "Нужны импульсы > 0 и фактическая длина > 0.\n"
                "Сбросьте метраж, протяните известную длину и повторите.",
            )
            return
        from brakovka_pi.encoder import calibrated_roll_diameter_m

        preview_m = calibrated_roll_diameter_m(length_m, pulses)
        if preview_m is None:
            play_error()
            return
        preview_mm = preview_m * 1000.0
        reply = QMessageBox.question(
            self,
            "Калибровка ролика",
            f"Импульсы: {pulses}\n"
            f"Длина: {length_m:.2f} м\n"
            f"Новый диаметр: {preview_mm:.1f} мм\n\n"
            "Применить и сохранить?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        result = self._bridge.calibrate_roll_diameter(length_m)
        if result is None:
            play_error()
            QMessageBox.warning(
                self,
                "Калибровка",
                "Не удалось применить. Станок должен быть в ожидании.",
            )
            return
        play_ok()
        self._roll_dia.blockSignals(True)
        self._roll_dia.setValue(int(round(result["diameter_mm"])))
        self._roll_dia.blockSignals(False)
        self.clear_form_dirty()
        QMessageBox.information(
            self,
            "Калибровка",
            f"Диаметр ролика: {result['diameter_mm']:.1f} мм",
        )

    def apply_settings_from_device(self, settings: dict) -> None:
        if self.form_is_locked():
            return
        self._apply_settings(settings)
        self._refresh_emulator_ui()
        self._refresh_invert_ui(settings)

    def _apply_settings(self, settings: dict) -> None:
        widgets = self._form_widgets_list
        for w in widgets:
            w.blockSignals(True)

        self._speed.setValue(settings.get("speed_set_mpm", 0.0))
        self._tension.setValue(int(round(settings.get("tension_n", 0))))
        self._jog.setValue(settings.get("jog_speed_mpm", 0.0))
        self._reverse.setValue(settings.get("reverse_speed_mpm", 0.0))
        self._slowdown.setValue(settings.get("slowdown_speed_mpm", 0.0))
        self._accel.setValue(settings.get("accel_sec", 0.0))
        self._decel.setValue(settings.get("decel_sec", 0.0))
        self._brake_delay.setValue(settings.get("brake_delay_sec", 0.0))
        self._kp.setValue(settings.get("pid_kp", 0.0))
        self._ti.setValue(settings.get("pid_ti", 0.0))
        self._kd.setValue(settings.get("pid_kd", 0.0))
        self._roll_dia.setValue(int(round(settings.get("roll_diameter_mm", 200.0))))

        for w in widgets:
            w.blockSignals(False)

    def _refresh_invert_ui(self, settings: dict | None = None) -> None:
        if settings is not None and "encoder_invert" in settings:
            self._encoder_invert = bool(settings.get("encoder_invert"))
        else:
            try:
                self._encoder_invert = bool(self._bridge.get_encoder_invert())
            except Exception:
                pass
        self._btn_invert.setText(
            "Инверт энкодера: ВКЛ" if self._encoder_invert else "Инверт энкодера: ВЫКЛ"
        )

    def _toggle_encoder_invert(self) -> None:
        new_value = not self._encoder_invert
        if self._bridge.set_encoder_invert(new_value):
            play_ok()
            self._encoder_invert = new_value
            self._refresh_invert_ui()
        else:
            play_error()
            QMessageBox.warning(
                self,
                "Инверт энкодера",
                "Не удалось применить. Нет связи с контроллером.",
            )

    def _refresh_emulator_ui(self) -> None:
        try:
            desired = self._bridge.read_emulator_setting()
        except Exception:
            desired = self._bridge.is_emulator_active()
        self._emu_desired = bool(desired)
        active = self._bridge.is_emulator_active()
        self._btn_emu.setText(
            "Эмуляция: ВКЛ" if self._emu_desired else "Эмуляция: ВЫКЛ"
        )

        hints: list[str] = []
        if self._emu_desired != active:
            hints.append("Перезапустите приложение, чтобы применить режим.")
        if not sys.platform.startswith("linux"):
            hints.append("На Windows/macOS эмуляция всегда активна.")
        if os.getenv("BRAKOVKA_EMU", "0") == "1":
            hints.append("BRAKOVKA_EMU=1 принудительно включает эмуляцию.")
        if self._emu_desired and active:
            hints.append(
                "Сейчас виртуальный ПЧ и энкодер; физические кнопки GPIO остаются активны."
            )
        elif not self._emu_desired and not active:
            hints.append("Сейчас работа с реальным ПЧ / AS5600.")
        self._emu_hint.setText(" ".join(hints))

    def _toggle_emulator(self) -> None:
        new_value = not self._emu_desired
        action = "включить" if new_value else "выключить"
        reply = QMessageBox.question(
            self,
            "Эмуляция",
            f"Режим эмуляции будет {action} после перезапуска приложения.\n"
            "Сохранить настройку в settings.json?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        if self._bridge.write_emulator_setting(new_value):
            play_ok()
            self._emu_desired = new_value
            self._refresh_emulator_ui()
            if not sys.platform.startswith("linux") and not new_value:
                QMessageBox.information(
                    self,
                    "Эмуляция",
                    "Флаг сохранён. На этой ОС эмуляция всё равно активна; "
                    "на Raspberry Pi после перезапуска будет реальное железо.",
                )
        else:
            play_error()
            QMessageBox.warning(self, "Эмуляция", "Не удалось сохранить настройку.")

    def _save(self) -> None:
        ok = self._bridge.write_settings({
            "speed_set_mpm": float(self._speed.value()),
            "tension_n": float(self._tension.value()),
            "jog_speed_mpm": float(self._jog.value()),
            "reverse_speed_mpm": float(self._reverse.value()),
            "slowdown_speed_mpm": float(self._slowdown.value()),
            "accel_sec": float(self._accel.value()),
            "decel_sec": float(self._decel.value()),
            "brake_delay_sec": float(self._brake_delay.value()),
            "pid_kp": float(self._kp.value()),
            "pid_ti": float(self._ti.value()),
            "pid_kd": float(self._kd.value()),
            "roll_diameter_mm": float(self._roll_dia.value()),
        })
        if ok:
            play_ok()
            self.clear_form_dirty()
        else:
            play_error()

    def set_commands_enabled(self, enabled: bool) -> None:
        self._btn_save.setEnabled(enabled)
        self._btn_emu.setEnabled(enabled)
        self._btn_invert.setEnabled(enabled)
