from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from brakovka_hmi.bridge import LocalBridge
from brakovka_hmi.services.poller import PollService
from brakovka_hmi.snapshot import MachineSnapshot, StatusFlag
from brakovka_hmi.sounds import play_alarm, play_error, play_ok
from brakovka_hmi.ui import theme as t
from brakovka_hmi.ui.screen_journal import JournalScreen
from brakovka_hmi.ui.screen_main import MainScreen
from brakovka_hmi.ui.screen_roll import RollScreen
from brakovka_hmi.ui.screen_settings import SettingsScreen
from brakovka_hmi.ui.screen_status import StatusScreen
from brakovka_hmi.ui.theme import SIDEBAR_WIDTH
from brakovka_hmi.ui.virtual_keyboard import ask_password
from brakovka_hmi.ui.widgets import build_stylesheet, make_logo_header
from brakovka_pi.settings import get_settings_password

log = logging.getLogger(__name__)

SETTINGS_PAGE_INDEX = 2


class MainWindow(QMainWindow):
    """Original wide-sidebar HMI layout."""

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
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window
        )
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
        root.addWidget(make_logo_header())

        body = QWidget()
        layout = QHBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(SIDEBAR_WIDTH)
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(0, 0, 0, 0)

        brand = QLabel("BRAKOVKA")
        brand.setObjectName("brand")
        side_layout.addWidget(brand)

        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        nav_items = [
            ("Главный", 0),
            ("Рулон", 1),
            ("Настройки", 2),
            ("Статус", 3),
            ("Журнал аварий", 4),
        ]
        for text, index in nav_items:
            btn = QPushButton(text)
            btn.setCheckable(True)
            btn.setObjectName("nav")
            self._nav_group.addButton(btn, index)
            side_layout.addWidget(btn)
        side_layout.addStretch()

        self._conn_label = QLabel("Ожидание контроллера")
        self._conn_label.setObjectName("connBad")
        self._conn_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        side_layout.addWidget(self._conn_label)

        layout.addWidget(sidebar)

        content = QWidget()
        content.setObjectName("content")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(16, 12, 16, 12)
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
        layout.addWidget(content, stretch=1)
        root.addWidget(body, stretch=1)

        self._nav_group.idClicked.connect(self._on_nav_clicked)
        self._nav_group.button(0).setChecked(True)

        self._poller.snapshot.connect(self._on_snapshot)
        self._poller.settings.connect(self._on_settings)
        self._poller.connection_changed.connect(self._on_connection)
        self._poller.start()

    def show_for_display(self) -> None:
        if self._fullscreen:
            self.showFullScreen()
        else:
            self.show()

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
        password = ask_password(
            self,
            title="Настройки",
            prompt="Введите пароль",
        )
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
            self._conn_label.setText("Локальный контроллер")
            self._conn_label.setStyleSheet(f"color: {t.OK}; font-weight: 600;")
        else:
            if self._was_connected:
                play_error()
            self._conn_label.setText("Нет связи")
            self._conn_label.setStyleSheet(f"color: {t.ERROR}; font-weight: 600;")
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
