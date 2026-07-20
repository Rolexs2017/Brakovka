from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from brakovka_hmi.bridge import LocalBridge
from brakovka_hmi.services.poller import PollService
from brakovka_hmi.snapshot import MachineSnapshot, StatusFlag
from brakovka_hmi.sounds import play_alarm, play_error, play_ok
from brakovka_hmi.ui.modern import icons as ic
from brakovka_hmi.ui.modern import theme as t
from brakovka_hmi.ui.modern.screen_journal import JournalScreen
from brakovka_hmi.ui.modern.screen_main import MainScreen
from brakovka_hmi.ui.modern.screen_roll import RollScreen
from brakovka_hmi.ui.modern.screen_settings import SettingsScreen
from brakovka_hmi.ui.modern.screen_status import StatusScreen
from brakovka_hmi.ui.modern.widgets import AppHeader, NavButton, build_stylesheet
from brakovka_hmi.ui.virtual_keyboard import ask_password
from brakovka_pi.settings import get_settings_password

log = logging.getLogger(__name__)

SETTINGS_PAGE_INDEX = 2

_NAV = (
    ("home", "Пульт", 0),
    ("roll", "Рулон", 1),
    ("settings", "Настройки", 2),
    ("status", "Статус", 3),
    ("journal", "Журнал", 4),
)

_PAGE_TITLES = {
    0: ("Пульт управления", "Главный экран оператора"),
    1: ("Рулон и длина", "Метраж и уставки"),
    2: ("Настройки", "Параметры станка"),
    3: ("Статус", "Оборудование и GPIO"),
    4: ("Журнал", "События и аварии"),
}


class MainWindow(QMainWindow):
    """Icon rail + modern screens."""

    def __init__(
        self,
        bridge: LocalBridge,
        *,
        title: str = "Brakovka HMI",
        width: int = 1280,
        height: int = 800,
        fullscreen: bool = True,
    ) -> None:
        super().__init__()
        self._bridge = bridge
        self._cached_settings: dict | None = None
        self._current_nav_index = 0
        self._settings_unlocked = False
        self._fullscreen = bool(fullscreen)
        self._prev_alarm_bits = 0
        self._was_connected = False

        self.setWindowTitle(title)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        if self._fullscreen:
            self.setMinimumSize(640, 480)
        else:
            self.setFixedSize(int(width), int(height))
        self.setStyleSheet(build_stylesheet())

        self._poller = PollService(bridge, fast_interval_ms=200, settings_interval_ms=2000)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._header = AppHeader()
        root.addWidget(self._header)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        rail = QWidget()
        rail.setObjectName("navRail")
        rail.setFixedWidth(t.SIDEBAR_WIDTH)
        side = QVBoxLayout(rail)
        side.setContentsMargins(0, 10, 0, 10)
        side.setSpacing(2)

        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        for icon_name, label, index in _NAV:
            btn = NavButton(icon_name, label)
            self._nav_group.addButton(btn, index)
            side.addWidget(btn)
        side.addStretch()
        body.addWidget(rail)

        content = QWidget()
        content.setObjectName("contentArea")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(22, 16, 22, 16)
        content_layout.setSpacing(0)

        self._stack = QStackedWidget()
        self._page_main = MainScreen(bridge)
        self._page_roll = RollScreen(bridge)
        self._page_settings = SettingsScreen(bridge)
        self._page_status = StatusScreen()
        self._page_journal = JournalScreen()
        self._page_settings.quit_requested.connect(self.close)
        for page in (
            self._page_main,
            self._page_roll,
            self._page_settings,
            self._page_status,
            self._page_journal,
        ):
            self._stack.addWidget(page)
        content_layout.addWidget(self._stack)
        body.addWidget(content, stretch=1)

        wrap = QWidget()
        wrap_layout = QHBoxLayout(wrap)
        wrap_layout.setContentsMargins(0, 0, 0, 0)
        wrap_layout.addLayout(body)
        root.addWidget(wrap, stretch=1)

        self._nav_group.idClicked.connect(self._on_nav_clicked)
        self._nav_group.button(0).setChecked(True)
        self._update_nav_icons(0)

        self._poller.snapshot.connect(self._on_snapshot)
        self._poller.settings.connect(self._on_settings)
        self._poller.connection_changed.connect(self._on_connection)
        self._poller.start()

    def show_for_display(self) -> None:
        if self._fullscreen:
            self.showFullScreen()
        else:
            self.show()

    def _update_nav_icons(self, active_index: int) -> None:
        for index, (icon_name, _label, _idx) in enumerate(_NAV):
            btn = self._nav_group.button(index)
            if btn is None:
                continue
            color = t.ACCENT if index == active_index else t.TEXT_DIM
            btn.setIcon(ic.icon(icon_name, color=color, size=26))

    def _set_page_header(self, index: int) -> None:
        title, subtitle = _PAGE_TITLES.get(index, ("Brakovka", "HMI"))
        self._header.set_page(title, subtitle)

    def _page_for_index(self, index: int):
        pages = (
            self._page_main,
            self._page_roll,
            self._page_settings,
            self._page_status,
            self._page_journal,
        )
        if 0 <= index < len(pages):
            return pages[index]
        return None

    def _ask_settings_password(self) -> bool:
        password = ask_password(self, title="Настройки", prompt="Введите пароль")
        if password is None:
            return False
        if password == get_settings_password():
            play_ok()
            return True
        play_error()
        QMessageBox.warning(self, "Настройки", "Неверный пароль.")
        return False

    def _restore_nav(self, index: int) -> None:
        btn = self._nav_group.button(index)
        if btn is not None:
            btn.blockSignals(True)
            btn.setChecked(True)
            btn.blockSignals(False)
        self._update_nav_icons(index)

    def _on_nav_clicked(self, index: int) -> None:
        if index == SETTINGS_PAGE_INDEX:
            if not self._settings_unlocked and not self._ask_settings_password():
                self._restore_nav(self._current_nav_index)
                return
            self._settings_unlocked = True
        elif self._current_nav_index == SETTINGS_PAGE_INDEX:
            self._settings_unlocked = False

        self._current_nav_index = index
        self._stack.setCurrentIndex(index)
        self._update_nav_icons(index)
        self._set_page_header(index)

        if self._cached_settings is None:
            return
        page = self._page_for_index(index)
        if page is not None and hasattr(page, "apply_settings_from_device"):
            page.apply_settings_from_device(self._cached_settings)

    def _on_snapshot(self, snap: object) -> None:
        if not isinstance(snap, MachineSnapshot):
            return
        page = self._page_for_index(self._stack.currentIndex())
        if page is not None and hasattr(page, "update_snapshot"):
            page.update_snapshot(snap)
        self._check_alarms(snap)

    def _check_alarms(self, snap: MachineSnapshot) -> None:
        alarm_mask = int(
            StatusFlag.ENCODER_ERROR
            | StatusFlag.MAGNET_ERROR
            | StatusFlag.WATCHDOG
            | StatusFlag.VFD_FAULT
            | StatusFlag.MODBUS_ERROR
        )
        bits = int(snap.status) & alarm_mask
        risen = bits & ~self._prev_alarm_bits
        self._prev_alarm_bits = bits
        if risen:
            play_alarm()

    def _on_settings(self, settings: object) -> None:
        if not isinstance(settings, dict):
            return
        self._cached_settings = settings
        if not self._page_roll.form_is_locked():
            self._page_roll.apply_settings_from_device(settings)
        if not self._page_settings.form_is_locked():
            self._page_settings.apply_settings_from_device(settings)

    def _on_connection(self, connected: bool) -> None:
        if connected:
            self._header.set_connected(True, "ONLINE")
        else:
            if self._was_connected:
                play_error()
            self._header.set_connected(False, "OFFLINE")
        self._was_connected = connected

        for page in (self._page_main, self._page_roll, self._page_settings):
            page.set_commands_enabled(connected)

    def closeEvent(self, event) -> None:
        self._poller.stop()
        try:
            self._bridge.release_all_held()
        except Exception:
            log.exception("Failed to release held HMI commands")
        super().closeEvent(event)
