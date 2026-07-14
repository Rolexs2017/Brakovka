from __future__ import annotations

from PySide6.QtWidgets import (
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from brakovka_hmi.bridge import LocalBridge
from brakovka_hmi.snapshot import CmdBit, MachineSnapshot, MOVING_STATES
from brakovka_hmi.sounds import play_error, play_ok
from brakovka_hmi.ui.form_guard import EditableFormMixin
from brakovka_hmi.ui.virtual_keyboard import TouchDoubleSpinBox, TouchSpinBox
from brakovka_hmi.ui.widgets import ValueCard
from brakovka_pi.roll_geometry import start_diameter_from_length_m


class RollScreen(EditableFormMixin, QWidget):
    def __init__(self, bridge: LocalBridge, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._bridge = bridge
        self._core_diameter_mm = 76.0
        self._commands_enabled = True
        self._motion_locked = False

        root = QVBoxLayout(self)
        root.setSpacing(8)
        title_row = QHBoxLayout()
        title = QLabel("Рулон и длина")
        title.setObjectName("screenTitle")
        title_row.addWidget(title)
        title_row.addStretch()
        self._dirty_label = QLabel("")
        self._dirty_label.setStyleSheet("color: #ffb020; font-size: 11pt; font-weight: 600;")
        title_row.addWidget(self._dirty_label)
        root.addLayout(title_row)

        cards = QGridLayout()
        cards.setHorizontalSpacing(12)
        cards.setVerticalSpacing(0)
        self._wound = ValueCard("Намотка потребительского ролика", "м")
        self._remaining = ValueCard("Остаток рулона", "м")
        self._diameter = ValueCard("Текущий диаметр", "мм")
        cards.addWidget(self._wound, 0, 0)
        cards.addWidget(self._remaining, 0, 1)
        cards.addWidget(self._diameter, 0, 2)
        root.addLayout(cards)

        body = QHBoxLayout()
        body.setSpacing(16)

        form = QFormLayout()
        form.setVerticalSpacing(6)
        self._target_len = TouchSpinBox(keypad_title="Целевая длина")
        self._target_len.setRange(1, 100000)
        self._target_len.setSuffix(" м")
        self._roll_len = TouchSpinBox(keypad_title="Метраж рулона")
        self._roll_len.setRange(1, 1000000)
        self._roll_len.setSuffix(" м")
        self._thickness = TouchDoubleSpinBox(keypad_title="Толщина материала")
        self._thickness.setRange(0.01, 10.0)
        self._thickness.setDecimals(2)
        self._thickness.setSingleStep(0.01)
        self._thickness.setSuffix(" мм")

        self._calc_dia = QLabel("—")
        self._calc_dia.setStyleSheet("color: #00d4ff; font-size: 12pt; font-weight: 600;")

        form.addRow("Целевая длина (потребитель)", self._target_len)
        form.addRow("Метраж разматываемого рулона", self._roll_len)
        form.addRow("Толщина материала", self._thickness)
        form.addRow("Расчётный начальный диаметр", self._calc_dia)
        body.addLayout(form, stretch=1)

        side = QVBoxLayout()
        side.setSpacing(8)
        btn_row = QHBoxLayout()
        self._btn_save = QPushButton("Сохранить уставки")
        self._btn_save.setObjectName("primary")
        self._btn_reset = QPushButton("Сброс рулона")
        self._btn_reset.setObjectName("cmd")
        btn_row.addWidget(self._btn_save)
        btn_row.addWidget(self._btn_reset)
        side.addLayout(btn_row)

        hint = QLabel(
            "Вводится метраж загруженного рулона; начальный диаметр считается "
            "по толщине и диаметру гильзы.\n"
            "«Сброс рулона» — сохранить уставки, обнулить расход и выставить "
            "остаток = метраж (намотку потребителя не трогает)."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #8aa4b8; font-size: 9pt;")
        side.addWidget(hint)
        body.addLayout(side, stretch=1)
        root.addLayout(body)

        self._btn_save.clicked.connect(self._save_settings)
        self._btn_reset.clicked.connect(self._reset_roll)
        self._roll_len.valueChanged.connect(self._refresh_calc_diameter)
        self._thickness.valueChanged.connect(self._refresh_calc_diameter)
        self._init_form_guard(
            [self._target_len, self._roll_len, self._thickness],
            dirty_changed=self._on_dirty_changed,
        )

        initial = bridge.read_settings()
        if initial is not None:
            self._apply_settings(initial)
            self.clear_form_dirty()

        root.addStretch()

    def _on_dirty_changed(self, dirty: bool) -> None:
        self._dirty_label.setText("Не сохранено" if dirty else "")

    def _update_edit_enabled(self) -> None:
        can_edit = self._commands_enabled and not self._motion_locked
        self._btn_save.setEnabled(can_edit)
        self._btn_reset.setEnabled(can_edit)
        for w in getattr(self, "_form_widgets", []):
            w.setEnabled(can_edit)

    def update_snapshot(self, snap: MachineSnapshot) -> None:
        self._wound.set_value(f"{snap.wound_m:.2f}")
        self._remaining.set_value(f"{snap.remaining_m:.1f}")
        self._diameter.set_value(f"{snap.diameter_mm:.0f}")
        self._motion_locked = snap.state in MOVING_STATES
        self._update_edit_enabled()

    def apply_settings_from_device(self, settings: dict) -> None:
        if self.form_is_locked():
            return
        self._apply_settings(settings)

    def _apply_settings(self, settings: dict) -> None:
        self._target_len.blockSignals(True)
        self._roll_len.blockSignals(True)
        self._thickness.blockSignals(True)
        self._target_len.setValue(int(round(settings.get("target_length_m", 0))))
        self._roll_len.setValue(int(round(settings.get("unwind_roll_length_m", 0))))
        self._thickness.setValue(settings.get("material_thickness_mm", 0.0))
        if "core_diameter_mm" in settings:
            self._core_diameter_mm = float(settings["core_diameter_mm"])
        self._target_len.blockSignals(False)
        self._roll_len.blockSignals(False)
        self._thickness.blockSignals(False)
        self._refresh_calc_diameter()

    def _refresh_calc_diameter(self, *_args) -> None:
        length_m = float(self._roll_len.value())
        thickness_m = float(self._thickness.value()) / 1000.0
        core_m = self._core_diameter_mm / 1000.0
        dia_mm = start_diameter_from_length_m(core_m, thickness_m, length_m) * 1000.0
        self._calc_dia.setText(f"{dia_mm:.0f} мм")

    def _save_settings(self) -> None:
        if self._motion_locked:
            play_error()
            return
        ok = self._bridge.write_settings({
            "target_length_m": float(self._target_len.value()),
            "unwind_roll_length_m": float(self._roll_len.value()),
            "material_thickness_mm": float(self._thickness.value()),
        })
        if ok:
            play_ok()
            self.clear_form_dirty()
        else:
            play_error()

    def _reset_roll(self) -> None:
        if self._motion_locked:
            play_error()
            return
        reply = QMessageBox.question(
            self,
            "Сброс рулона",
            "Сохранить уставки и сбросить расход рулона?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._save_settings()
        self._bridge.pulse_command(CmdBit.RESET_ROLL)

    def set_commands_enabled(self, enabled: bool) -> None:
        self._commands_enabled = enabled
        self._update_edit_enabled()
