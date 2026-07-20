from __future__ import annotations

import os
import sys

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from brakovka_hmi.bridge import LocalBridge
from brakovka_pi.pid_tune import (
    PID_TUNE_METHOD_HINTS,
    PID_TUNE_METHOD_LABELS,
    PID_TUNE_METHOD_ORDER,
    PidTuneMethod,
)
from brakovka_hmi.snapshot import MOVING_STATES, MachineSnapshot, MachineState
from brakovka_hmi.sounds import play_error, play_ok
from brakovka_hmi.ui.form_guard import EditableFormMixin
from brakovka_hmi.ui.trend_plot import DualTrendPlot
from brakovka_hmi.ui.virtual_keyboard import TouchDoubleSpinBox, TouchSpinBox

_FIELD_W = 140

PAGE_HUB = 0
PAGE_SPEED = 1
PAGE_PID = 2
PAGE_ROLL = 3
PAGE_SERVICE = 4
PAGE_PID_TREND = 5


def _form() -> QFormLayout:
    f = QFormLayout()
    f.setVerticalSpacing(6)
    f.setHorizontalSpacing(12)
    f.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
    return f


def _fix_field(w) -> None:
    w.setFixedWidth(_FIELD_W)


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
        self._title = QLabel("Настройки")
        self._title.setObjectName("screenTitle")
        title_row.addWidget(self._title)
        title_row.addStretch()
        self._dirty_label = QLabel("")
        self._dirty_label.setStyleSheet("color: #ffb020; font-size: 11pt; font-weight: 600;")
        title_row.addWidget(self._dirty_label)
        root.addLayout(title_row)

        self._stack = QStackedWidget()
        root.addWidget(self._stack, stretch=1)

        self._build_fields()
        self._stack.addWidget(self._build_hub_page())
        self._stack.addWidget(self._build_speed_page())
        self._stack.addWidget(self._build_pid_page())
        self._stack.addWidget(self._build_roll_page())
        self._stack.addWidget(self._build_service_page())
        self._stack.addWidget(self._build_pid_trend_page())

        footer = QHBoxLayout()
        self._btn_back = QPushButton("← К группам")
        self._btn_back.setObjectName("cmd")
        self._btn_back.setMinimumHeight(40)
        self._btn_save = QPushButton("Сохранить уставки")
        self._btn_save.setObjectName("primary")
        self._btn_save.setMinimumHeight(40)
        footer.addWidget(self._btn_back)
        footer.addStretch()
        footer.addWidget(self._btn_save)
        root.addLayout(footer)

        self._btn_save.clicked.connect(self._save)
        self._btn_emu.clicked.connect(self._toggle_emulator)
        self._btn_vfd_addr_save.clicked.connect(self._save_vfd_unit_id)
        self._btn_invert.clicked.connect(self._toggle_encoder_invert)
        self._btn_calibrate.clicked.connect(self._calibrate_roll)
        self._btn_autotune.clicked.connect(self._start_autotune)
        self._btn_abort_tune.clicked.connect(self._abort_autotune)
        self._btn_quit.clicked.connect(self.quit_requested.emit)
        self._btn_clear_logs.clicked.connect(self._clear_logs)

        self._last_pulses = 0
        self._encoder_invert = False
        self._prev_autotune_status = ""
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
            self._mpm_per_hz,
            self._roll_dia,
        )
        self._init_form_guard(
            list(self._form_widgets_list),
            dirty_changed=self._on_dirty_changed,
        )
        self._on_pid_method_changed()
        self._show_page(PAGE_HUB)
        self._refresh_emulator_ui()
        self._refresh_invert_ui()
        self._refresh_vfd_unit_ui()

    def _build_fields(self) -> None:
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

        self._pid_method_group: QButtonGroup | None = None
        self._pid_method_buttons: dict[str, QRadioButton] = {}

        self._mpm_per_hz = TouchDoubleSpinBox(keypad_title="Feedforward (м/мин)/Гц")
        self._mpm_per_hz.setRange(0.01, 1000.0)
        self._mpm_per_hz.setDecimals(3)

        self._roll_dia = TouchSpinBox(keypad_title="Диаметр мерительного ролика")
        self._roll_dia.setRange(20, 1000)
        self._roll_dia.setSuffix(" мм")

        self._vfd_unit_id = TouchSpinBox(keypad_title="Адрес Modbus ПЧ")
        self._vfd_unit_id.setRange(1, 247)

        self._cal_length = TouchDoubleSpinBox(keypad_title="Фактическая длина")
        self._cal_length.setRange(0.01, 10000.0)
        self._cal_length.setDecimals(2)
        self._cal_length.setSuffix(" м")
        self._cal_length.setValue(10.0)

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
            self._cal_length,
            self._vfd_unit_id,
        ):
            _fix_field(w)

    def _group_button(self, text: str, subtitle: str, page: int) -> QPushButton:
        btn = QPushButton(f"{text}\n{subtitle}")
        btn.setObjectName("settingsGroup")
        btn.setMinimumHeight(88)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(lambda _=False, p=page: self._show_page(p))
        return btn

    def _build_hub_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setSpacing(12)
        hint = QLabel("Выберите группу параметров")
        hint.setStyleSheet("color: #8aa4b8; font-size: 10pt;")
        lay.addWidget(hint)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        grid.addWidget(
            self._group_button("Скорость", "JOG, реверс, разгон, натяжение", PAGE_SPEED),
            0,
            0,
        )
        grid.addWidget(
            self._group_button("PID", "Метод автонастройки, Kp / Ti / Kd", PAGE_PID),
            0,
            1,
        )
        grid.addWidget(
            self._group_button("Ролик", "Диаметр, калибровка, инверт", PAGE_ROLL),
            1,
            0,
        )
        grid.addWidget(
            self._group_button("Сервис", "Адрес ПЧ, эмуляция, журнал, выход", PAGE_SERVICE),
            1,
            1,
        )
        lay.addLayout(grid)
        lay.addStretch()
        return page

    def _build_speed_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setSpacing(8)
        cols = QHBoxLayout()
        left = _form()
        right = _form()
        left.addRow("Рабочая скорость", self._speed)
        left.addRow("Натяжение", self._tension)
        left.addRow("Скорость JOG", self._jog)
        left.addRow("Скорость реверса", self._reverse)
        right.addRow("Скорость замедления", self._slowdown)
        right.addRow("Время разгона", self._accel)
        right.addRow("Время торможения", self._decel)
        right.addRow("Выдержка тормоза", self._brake_delay)
        cols.addLayout(left, stretch=1)
        cols.addLayout(right, stretch=1)
        lay.addLayout(cols)
        lay.addStretch()
        return page

    def _build_pid_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setSpacing(10)

        method_title = QLabel("Метод автонастройки")
        method_title.setStyleSheet("color: #8aa4b8; font-size: 10pt; font-weight: 600;")
        lay.addWidget(method_title)

        self._pid_method_group = QButtonGroup(page)
        self._pid_method_group.setExclusive(True)
        self._pid_method_buttons.clear()

        method_row = QHBoxLayout()
        method_row.setSpacing(8)
        method_row.setContentsMargins(0, 0, 0, 0)
        for method in PID_TUNE_METHOD_ORDER:
            rb = QRadioButton(PID_TUNE_METHOD_LABELS[method], page)
            rb.setObjectName("pidMethod")
            rb.setMinimumHeight(44)
            rb.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            rb.setCursor(Qt.CursorShape.PointingHandCursor)
            self._pid_method_group.addButton(rb)
            self._pid_method_buttons[method] = rb
            method_row.addWidget(rb, stretch=1)
        lay.addLayout(method_row)

        self._pid_method_hint = QLabel(PID_TUNE_METHOD_HINTS[PidTuneMethod.RELAY.value])
        self._pid_method_hint.setWordWrap(True)
        self._pid_method_hint.setStyleSheet("color: #8aa4b8; font-size: 9pt;")
        lay.addWidget(self._pid_method_hint)

        self._pid_params_summary = QLabel("")
        self._pid_params_summary.setWordWrap(True)
        self._pid_params_summary.setStyleSheet("color: #e8f1f8; font-size: 10pt;")
        lay.addWidget(self._pid_params_summary)

        coeffs_title = QLabel("Коэффициенты")
        coeffs_title.setStyleSheet("color: #8aa4b8; font-size: 10pt; font-weight: 600;")
        lay.addWidget(coeffs_title)

        form = _form()
        form.addRow("PID Kp", self._kp)
        form.addRow("PID Ti", self._ti)
        form.addRow("PID Kd", self._kd)
        self._mpm_per_hz_label = QLabel("FF (м/мин)/Гц")
        form.addRow(self._mpm_per_hz_label, self._mpm_per_hz)
        lay.addLayout(form)

        # Connect after widgets exist — setChecked fires toggled immediately.
        for rb in self._pid_method_buttons.values():
            rb.toggled.connect(self._on_pid_method_radio_toggled)
        self._pid_method_buttons[PidTuneMethod.RELAY.value].setChecked(True)

        tune_row = QHBoxLayout()
        tune_row.setSpacing(10)
        self._btn_autotune = QPushButton("Автонастройка PID")
        self._btn_autotune.setObjectName("cmd")
        self._btn_autotune.setMinimumWidth(200)
        self._btn_abort_tune = QPushButton("Стоп автонастройки")
        self._btn_abort_tune.setObjectName("cmdStop")
        self._btn_abort_tune.setEnabled(False)
        self._btn_pid_trend = QPushButton("График")
        self._btn_pid_trend.setObjectName("cmd")
        self._btn_pid_trend.setMinimumWidth(120)
        self._btn_pid_trend.clicked.connect(lambda: self._show_page(PAGE_PID_TREND))
        tune_row.addWidget(self._btn_autotune)
        tune_row.addWidget(self._btn_abort_tune)
        tune_row.addWidget(self._btn_pid_trend)
        tune_row.addStretch()
        lay.addLayout(tune_row)

        self._autotune_status = QLabel(
            "Автонастройка PID: выберите метод и запустите тест (только в Ожидании)."
        )
        self._autotune_status.setWordWrap(True)
        self._autotune_status.setStyleSheet("color: #8aa4b8; font-size: 9pt;")
        lay.addWidget(self._autotune_status)
        lay.addStretch()

        for w in (self._kp, self._ti, self._kd, self._mpm_per_hz):
            w.valueChanged.connect(self._update_pid_summary_from_form)
        return page

    def _build_pid_trend_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setSpacing(8)

        self._pid_trend_info = QLabel("Метод: —")
        self._pid_trend_info.setWordWrap(True)
        self._pid_trend_info.setStyleSheet("color: #e8f1f8; font-size: 10pt; font-weight: 600;")
        lay.addWidget(self._pid_trend_info)

        hint = QLabel(
            "Тренд ~60 с: скорость (м/мин, бирюзовый) и выход PID (% от 320 Гц, оранжевый)."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #8aa4b8; font-size: 9pt;")
        lay.addWidget(hint)
        self._pid_trend = DualTrendPlot(window_s=60.0)
        lay.addWidget(self._pid_trend, stretch=1)
        clear_row = QHBoxLayout()
        self._btn_clear_trend = QPushButton("Очистить график")
        self._btn_clear_trend.setObjectName("cmd")
        self._btn_clear_trend.clicked.connect(self._pid_trend.clear)
        clear_row.addWidget(self._btn_clear_trend)
        clear_row.addStretch()
        lay.addLayout(clear_row)
        return page

    def _build_roll_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setSpacing(10)
        form = _form()
        form.addRow("Диаметр мерн. ролика", self._roll_dia)
        lay.addLayout(form)

        cal_title = QLabel("Калибровка")
        cal_title.setStyleSheet("color: #8aa4b8;")
        lay.addWidget(cal_title)

        cal_row = QHBoxLayout()
        cal_row.setSpacing(10)
        self._cal_pulses = QLabel("Импульсы: —")
        self._cal_pulses.setStyleSheet("color: #e8f1f8; font-size: 11pt;")
        self._btn_calibrate = QPushButton("Калибровать ролик")
        self._btn_calibrate.setObjectName("cmd")
        cal_row.addWidget(self._cal_pulses)
        cal_row.addWidget(QLabel("Факт. длина"))
        cal_row.addWidget(self._cal_length)
        cal_row.addWidget(self._btn_calibrate)
        cal_row.addStretch()
        lay.addLayout(cal_row)

        invert_row = QHBoxLayout()
        invert_row.setSpacing(12)
        self._btn_invert = QPushButton()
        self._btn_invert.setObjectName("cmd")
        self._btn_invert.setMinimumWidth(260)
        self._invert_hint = QLabel("Знак направления мерного ролика. Применяется сразу.")
        self._invert_hint.setWordWrap(True)
        self._invert_hint.setStyleSheet("color: #8aa4b8; font-size: 9pt;")
        invert_row.addWidget(self._btn_invert)
        invert_row.addWidget(self._invert_hint, stretch=1)
        lay.addLayout(invert_row)
        lay.addStretch()
        return page

    def _build_service_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setSpacing(12)

        vfd_row = QHBoxLayout()
        vfd_row.setSpacing(10)
        self._btn_vfd_addr_save = QPushButton("Сохранить адрес")
        self._btn_vfd_addr_save.setObjectName("cmd")
        self._btn_vfd_addr_save.setMinimumWidth(180)
        self._vfd_addr_hint = QLabel(
            "Modbus RTU slave address частотника (serial.unit_id). "
            "Должен совпадать с настройкой на ПЧ. Применяется после перезапуска."
        )
        self._vfd_addr_hint.setWordWrap(True)
        self._vfd_addr_hint.setStyleSheet("color: #8aa4b8; font-size: 9pt;")
        vfd_form = _form()
        vfd_form.addRow("Адрес Modbus ПЧ", self._vfd_unit_id)
        vfd_row.addLayout(vfd_form)
        vfd_row.addWidget(self._btn_vfd_addr_save)
        vfd_row.addWidget(self._vfd_addr_hint, stretch=1)
        lay.addLayout(vfd_row)

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
        lay.addLayout(emu_row)

        clear_row = QHBoxLayout()
        clear_row.setSpacing(12)
        self._btn_clear_logs = QPushButton("Очистить статистику")
        self._btn_clear_logs.setObjectName("cmdStop")
        self._btn_clear_logs.setMinimumWidth(220)
        self._btn_clear_logs.setMinimumHeight(44)
        self._clear_logs_hint = QLabel(
            "Обнуляет файлы журнала (brakovka_info.log / brakovka_error.log) "
            "и удаляет ротированные копии. Экран «Журнал» станет пустым."
        )
        self._clear_logs_hint.setWordWrap(True)
        self._clear_logs_hint.setStyleSheet("color: #8aa4b8; font-size: 9pt;")
        clear_row.addWidget(self._btn_clear_logs)
        clear_row.addWidget(self._clear_logs_hint, stretch=1)
        lay.addLayout(clear_row)

        self._btn_quit = QPushButton("Закрыть приложение")
        self._btn_quit.setObjectName("cmdStop")
        self._btn_quit.setMinimumHeight(44)
        lay.addWidget(self._btn_quit, alignment=Qt.AlignmentFlag.AlignLeft)
        lay.addStretch()
        return page

    def _show_page(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        titles = {
            PAGE_HUB: "Настройки",
            PAGE_SPEED: "Настройки · Скорость",
            PAGE_PID: "Настройки · PID",
            PAGE_ROLL: "Настройки · Ролик",
            PAGE_SERVICE: "Настройки · Сервис",
            PAGE_PID_TREND: "Настройки · PID · График",
        }
        self._title.setText(titles.get(index, "Настройки"))
        # From trend go back to PID group, not hub.
        if index == PAGE_PID_TREND:
            self._btn_back.setText("← К PID")
            try:
                self._btn_back.clicked.disconnect()
            except Exception:
                pass
            self._btn_back.clicked.connect(lambda: self._show_page(PAGE_PID))
        else:
            self._btn_back.setText("← К группам")
            try:
                self._btn_back.clicked.disconnect()
            except Exception:
                pass
            self._btn_back.clicked.connect(lambda: self._show_page(PAGE_HUB))
        self._btn_back.setVisible(index != PAGE_HUB)
        self._btn_save.setVisible(
            index in (PAGE_HUB, PAGE_SPEED, PAGE_PID, PAGE_ROLL)
        )

    def showEvent(self, event) -> None:  # noqa: ANN001
        super().showEvent(event)
        self._show_page(PAGE_HUB)
        self._refresh_emulator_ui()
        self._refresh_invert_ui()
        self._refresh_vfd_unit_ui()

    def update_snapshot(self, snap: MachineSnapshot) -> None:
        self._last_pulses = int(snap.encoder_pulses)
        self._cal_pulses.setText(f"Импульсы: {self._last_pulses}")
        if snap.connected and self._stack.currentIndex() == PAGE_PID_TREND:
            self._pid_trend.push(float(snap.speed_mpm), float(snap.pid_out_pct))
        moving = snap.state in MOVING_STATES
        idle = snap.state == MachineState.IDLE
        tuning = bool(snap.autotune_active)
        self._btn_calibrate.setEnabled(snap.connected and not moving and not tuning)
        self._btn_invert.setEnabled(snap.connected and not tuning)
        self._btn_autotune.setEnabled(snap.connected and idle and not tuning)
        self._btn_abort_tune.setEnabled(snap.connected and tuning)
        for btn in self._pid_method_buttons.values():
            btn.setEnabled(snap.connected and not tuning)

        if snap.connected and not self.form_is_locked():
            self._refresh_pid_visualization(snap)

        st = snap.autotune_status or "idle"
        msg = snap.autotune_message or ""
        if tuning:
            self._autotune_status.setText(f"Автонастройка: {msg or 'идёт…'}")
            self._autotune_status.setStyleSheet("color: #ffb020; font-size: 9pt;")
        elif st == "ok":
            self._autotune_status.setText(f"Автонастройка: {msg}")
            self._autotune_status.setStyleSheet("color: #3ddc84; font-size: 9pt;")
            if self._prev_autotune_status != "ok":
                try:
                    settings = self._bridge.read_settings()
                    if settings:
                        self._kp.blockSignals(True)
                        self._ti.blockSignals(True)
                        self._kd.blockSignals(True)
                        self._kp.setValue(float(settings.get("pid_kp", 0.0)))
                        self._ti.setValue(float(settings.get("pid_ti", 0.0)))
                        self._kd.setValue(float(settings.get("pid_kd", 0.0)))
                        self._mpm_per_hz.setValue(float(settings.get("mpm_per_hz", 1.0)))
                        self._set_pid_tune_method(str(settings.get("pid_tune_method", "relay")))
                        self._kp.blockSignals(False)
                        self._ti.blockSignals(False)
                        self._kd.blockSignals(False)
                        self.clear_form_dirty()
                except Exception:
                    pass
        elif st in ("fail", "aborted"):
            self._autotune_status.setText(f"Автонастройка: {msg or st}")
            self._autotune_status.setStyleSheet("color: #ff4d4d; font-size: 9pt;")
        else:
            self._autotune_status.setText(
                "Автонастройка PID: выберите метод и запустите тест (только в Ожидании)."
            )
            self._autotune_status.setStyleSheet("color: #8aa4b8; font-size: 9pt;")
        self._prev_autotune_status = st

    def _on_pid_method_radio_toggled(self, checked: bool) -> None:
        if not checked:
            return
        self._mark_form_dirty()
        self._on_pid_method_changed()

    def _selected_pid_tune_method(self) -> str:
        for method, btn in self._pid_method_buttons.items():
            if btn.isChecked():
                return method
        return PidTuneMethod.RELAY.value

    def _set_pid_tune_method(self, method: str) -> None:
        if not self._pid_method_buttons:
            return
        btn = self._pid_method_buttons.get(method)
        for b in self._pid_method_buttons.values():
            b.blockSignals(True)
        if btn is not None:
            btn.setChecked(True)
        else:
            self._pid_method_buttons[PidTuneMethod.RELAY.value].setChecked(True)
        for b in self._pid_method_buttons.values():
            b.blockSignals(False)
        self._on_pid_method_changed()

    def _format_pid_summary(
        self,
        *,
        method: str,
        kp: float,
        ti: float,
        kd: float,
        mpm_per_hz: float,
    ) -> str:
        label = PID_TUNE_METHOD_LABELS.get(method, method)
        parts = [
            f"Метод: {label}",
            f"Kp={kp:.2f}",
            f"Ti={ti:.2f}",
        ]
        if method == PidTuneMethod.PI_FF.value:
            parts.append(f"FF={mpm_per_hz:.3f} (м/мин)/Гц")
            parts.append("Kd не используется")
        else:
            parts.append(f"Kd={kd:.3f}")
        return "  ·  ".join(parts)

    def _refresh_pid_visualization(self, snap: MachineSnapshot) -> None:
        method = str(snap.pid_tune_method or PidTuneMethod.RELAY.value)
        summary = self._format_pid_summary(
            method=method,
            kp=float(snap.pid_kp),
            ti=float(snap.pid_ti),
            kd=float(snap.pid_kd),
            mpm_per_hz=float(snap.mpm_per_hz),
        )
        self._pid_params_summary.setText(summary)
        if hasattr(self, "_pid_trend_info"):
            self._pid_trend_info.setText(summary)

    def _on_pid_method_changed(self) -> None:
        if not hasattr(self, "_pid_method_hint"):
            return
        method = self._selected_pid_tune_method()
        self._pid_method_hint.setText(
            PID_TUNE_METHOD_HINTS.get(method, "")
        )
        is_ff = method == PidTuneMethod.PI_FF.value
        self._mpm_per_hz.setVisible(is_ff)
        self._mpm_per_hz_label.setVisible(is_ff)
        self._kd.setEnabled(not is_ff)
        summary = self._format_pid_summary(
            method=method,
            kp=float(self._kp.value()),
            ti=float(self._ti.value()),
            kd=float(self._kd.value()),
            mpm_per_hz=float(self._mpm_per_hz.value()),
        )
        if hasattr(self, "_pid_params_summary"):
            self._pid_params_summary.setText(summary)
        if hasattr(self, "_pid_trend_info"):
            self._pid_trend_info.setText(summary)

    def _update_pid_summary_from_form(self, *_args) -> None:
        if not hasattr(self, "_pid_params_summary"):
            return
        method = self._selected_pid_tune_method()
        summary = self._format_pid_summary(
            method=method,
            kp=float(self._kp.value()),
            ti=float(self._ti.value()),
            kd=float(self._kd.value()),
            mpm_per_hz=float(self._mpm_per_hz.value()),
        )
        self._pid_params_summary.setText(summary)
        if hasattr(self, "_pid_trend_info"):
            self._pid_trend_info.setText(summary)

    def _autotune_dialog_text(self) -> str:
        method = self._selected_pid_tune_method()
        if method == PidTuneMethod.STEP_IMC.value:
            return (
                "Будет открытый ступенчатый тест частоты ПЧ и расчёт PID по IMC.\n"
                "Материал должен быть заправлен. СТОП — прерывание.\n\n"
                "Запустить?"
            )
        if method == PidTuneMethod.PI_FF.value:
            return (
                "Будет ступенчатый тест для калибровки feedforward (м/мин)/Гц "
                "и небольших PI-коррекций.\n"
                "Материал должен быть заправлен. СТОП — прерывание.\n\n"
                "Запустить?"
            )
        return (
            "Будет короткий тестовый прогон на скорости JOG с колебаниями частоты ПЧ "
            "(relay / Ziegler–Nichols).\n"
            "Материал должен быть заправлен. СТОП — прерывание.\n\n"
            "Запустить?"
        )

    def _start_autotune(self) -> None:
        reply = QMessageBox.question(
            self,
            "Автонастройка PID",
            self._autotune_dialog_text(),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        # Persist selected method before starting (controller reads it at autotune start).
        if not self._bridge.write_settings({"pid_tune_method": self._selected_pid_tune_method()}):
            play_error()
            QMessageBox.warning(self, "Автонастройка PID", "Не удалось сохранить метод PID.")
            return
        if self._bridge.start_pid_autotune():
            play_ok()
            self._autotune_status.setText("Автонастройка: запуск…")
        else:
            play_error()
            QMessageBox.warning(
                self,
                "Автонастройка PID",
                "Не удалось запустить. Нужны: Ожидание, связь, нет аварии ПЧ/Modbus.",
            )

    def _abort_autotune(self) -> None:
        if self._bridge.abort_pid_autotune():
            play_ok()
        else:
            play_error()

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
        self._mpm_per_hz.setValue(float(settings.get("mpm_per_hz", 1.0)))
        self._set_pid_tune_method(str(settings.get("pid_tune_method", "relay")))
        self._roll_dia.setValue(int(round(settings.get("roll_diameter_mm", 200.0))))

        for w in widgets:
            w.blockSignals(False)
        self._on_pid_method_changed()

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

    def _refresh_vfd_unit_ui(self) -> None:
        try:
            unit_id = int(self._bridge.read_vfd_unit_id())
        except Exception:
            unit_id = 1
        self._vfd_unit_id.blockSignals(True)
        self._vfd_unit_id.setValue(unit_id)
        self._vfd_unit_id.blockSignals(False)

    def _save_vfd_unit_id(self) -> None:
        unit_id = int(self._vfd_unit_id.value())
        try:
            current = int(self._bridge.read_vfd_unit_id())
        except Exception:
            current = unit_id
        if unit_id == current:
            QMessageBox.information(
                self,
                "Адрес Modbus ПЧ",
                f"Адрес уже сохранён: {unit_id}.",
            )
            return
        reply = QMessageBox.question(
            self,
            "Адрес Modbus ПЧ",
            f"Сохранить адрес Modbus ПЧ: {unit_id}?\n\n"
            "Изменение вступит в силу после перезапуска приложения.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        if self._bridge.write_vfd_unit_id(unit_id):
            play_ok()
            self._refresh_vfd_unit_ui()
            QMessageBox.information(
                self,
                "Адрес Modbus ПЧ",
                f"Адрес {unit_id} сохранён в settings.json.\n"
                "Перезапустите приложение для применения.",
            )
        else:
            play_error()
            QMessageBox.warning(self, "Адрес Modbus ПЧ", "Не удалось сохранить настройку.")

    def _clear_logs(self) -> None:
        from brakovka_pi.logutil import clear_log_files, current_log_dir

        reply = QMessageBox.question(
            self,
            "Очистить статистику",
            "Обнулить файлы журнала (info/error) и удалить ротированные копии?\n\n"
            f"Каталог: {current_log_dir()}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        touched, errors = clear_log_files()
        if errors:
            play_error()
            QMessageBox.warning(
                self,
                "Очистить статистику",
                "Очистка выполнена с ошибками:\n" + "\n".join(errors),
            )
            return
        play_ok()
        QMessageBox.information(
            self,
            "Очистить статистику",
            f"Журнал очищен ({touched} файл(ов)).",
        )

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
            "pid_tune_method": self._selected_pid_tune_method(),
            "mpm_per_hz": float(self._mpm_per_hz.value()),
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
        self._btn_vfd_addr_save.setEnabled(enabled)
        self._btn_clear_logs.setEnabled(enabled)
        self._btn_invert.setEnabled(enabled)
        if not enabled:
            self._btn_autotune.setEnabled(False)
            self._btn_abort_tune.setEnabled(False)
