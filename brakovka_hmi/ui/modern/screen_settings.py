from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from brakovka_hmi.ui.modern.widgets import SettingsTile
from brakovka_hmi.ui.screen_settings import (
    PAGE_PID,
    PAGE_ROLL,
    PAGE_SERVICE,
    PAGE_SPEED,
    SettingsScreen as BaseSettingsScreen,
)


class SettingsScreen(BaseSettingsScreen):
    """Modern settings hub with icon tiles."""

    def _group_button(self, text: str, subtitle: str, page: int) -> QPushButton:
        icons = {
            PAGE_SPEED: "speed",
            PAGE_PID: "pid",
            PAGE_ROLL: "calibrate",
            PAGE_SERVICE: "service",
        }
        btn = SettingsTile(icons.get(page, "settings"), text, subtitle)
        btn.clicked.connect(lambda _=False, p=page: self._show_page(p))
        return btn

    def _build_hub_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setSpacing(14)
        hint = QLabel("Выберите группу параметров")
        hint.setObjectName("hintText")
        lay.addWidget(hint)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        grid.addWidget(
            self._group_button("Скорость", "JOG, реверс, разгон, натяжение", PAGE_SPEED),
            0, 0,
        )
        grid.addWidget(
            self._group_button("PID", "Автонастройка, Kp / Ti / Kd", PAGE_PID),
            0, 1,
        )
        grid.addWidget(
            self._group_button("Ролик", "Диаметр, калибровка, инверт", PAGE_ROLL),
            1, 0,
        )
        grid.addWidget(
            self._group_button("Сервис", "ПЧ, эмуляция, журнал, выход", PAGE_SERVICE),
            1, 1,
        )
        lay.addLayout(grid)
        lay.addStretch()
        return page

    def __init__(self, bridge, parent=None) -> None:
        super().__init__(bridge, parent)
        from brakovka_hmi.ui.modern import icons as ic

        self._title.setObjectName("screenTitle")
        self._dirty_label.setObjectName("dirtyBadge")
        self._btn_back.setIcon(self._back_icon())
        self._btn_back.setIconSize(ic.icon_size(18))
        self._btn_save.setIcon(self._save_icon())
        self._btn_save.setIconSize(ic.icon_size(18))

    @staticmethod
    def _back_icon():
        from brakovka_hmi.ui.modern import icons as ic
        from brakovka_hmi.ui.modern import theme as t
        return ic.icon("back", color=t.TEXT, size=18)

    @staticmethod
    def _save_icon():
        from brakovka_hmi.ui.modern import icons as ic
        from brakovka_hmi.ui.modern import theme as t
        return ic.icon("save", color=t.ACCENT, size=18)
