from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from brakovka_hmi.ui.modern import icons as ic
from brakovka_hmi.ui.modern import theme as t
from brakovka_hmi.ui.modern.widgets import PageBar, Panel
from brakovka_pi.logutil import JournalEntry, current_log_dir, read_journal_entries

_LEVEL_LABEL = {
    "CRITICAL": "КРИТ",
    "ERROR": "АВАРИЯ",
    "WARNING": "ПРЕДУПР",
    "INFO": "ИНФО",
    "DEBUG": "ОТЛАДКА",
}

_LEVEL_COLOR = {
    "CRITICAL": t.ERROR,
    "ERROR": t.ERROR,
    "WARNING": t.WARN,
    "INFO": t.TEXT_DIM,
    "DEBUG": t.TEXT_MUTED,
}


class JournalScreen(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._filter = "all"
        self._last_fingerprint = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)

        self._bar = PageBar("Журнал событий")
        root.addWidget(self._bar)

        panel = Panel()
        body = panel.body_layout()

        filt_row = QHBoxLayout()
        filt_row.setSpacing(8)
        self._btn_all = QPushButton("  Все")
        self._btn_alarms = QPushButton("  Аварии")
        self._btn_info = QPushButton("  Инфо")
        self._btn_refresh = QPushButton("  Обновить")
        for btn, name in (
            (self._btn_all, "filter"),
            (self._btn_alarms, "warning"),
            (self._btn_info, "journal"),
            (self._btn_refresh, "refresh"),
        ):
            btn.setObjectName("chipBtn")
            btn.setCheckable(name != "refresh")
            btn.setIcon(ic.icon(name, color=t.TEXT_DIM, size=16))
            btn.setIconSize(ic.icon_size(16))
            btn.setMinimumHeight(40)
        self._btn_all.setChecked(True)
        filt_row.addWidget(self._btn_all)
        filt_row.addWidget(self._btn_alarms)
        filt_row.addWidget(self._btn_info)
        filt_row.addStretch()
        filt_row.addWidget(self._btn_refresh)
        body.addLayout(filt_row)

        self._list = QListWidget()
        self._list.setObjectName("journalList")
        self._list.setUniformItemSizes(False)
        self._list.setWordWrap(True)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body.addWidget(self._list, stretch=1)

        self._status = QLabel("")
        self._status.setObjectName("journalHint")
        body.addWidget(self._status)
        root.addWidget(panel, stretch=1)

        self._btn_all.clicked.connect(lambda: self._set_filter("all"))
        self._btn_alarms.clicked.connect(lambda: self._set_filter("alarms"))
        self._btn_info.clicked.connect(lambda: self._set_filter("info"))
        self._btn_refresh.clicked.connect(self.refresh)

        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self.refresh)
        self.refresh()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.refresh()
        self._timer.start()

    def hideEvent(self, event) -> None:  # noqa: N802
        self._timer.stop()
        super().hideEvent(event)

    def _set_filter(self, mode: str) -> None:
        self._filter = mode
        self._btn_all.setChecked(mode == "all")
        self._btn_alarms.setChecked(mode == "alarms")
        self._btn_info.setChecked(mode == "info")
        self._last_fingerprint = ""
        self.refresh()

    def refresh(self) -> None:
        log_dir = current_log_dir()
        self._bar.set_badge(str(log_dir.name))
        try:
            entries = read_journal_entries(
                max_per_file=400,
                alarms_only=self._filter == "alarms",
                info_only=self._filter == "info",
            )
        except Exception as exc:
            self._status.setText(f"Ошибка чтения журнала: {exc}")
            return

        fingerprint = f"{self._filter}|{len(entries)}|{entries[0].raw if entries else ''}"
        if fingerprint == self._last_fingerprint:
            return
        self._last_fingerprint = fingerprint

        bar = self._list.verticalScrollBar()
        at_top = bar.value() <= bar.minimum()
        prev_scroll = bar.value()

        self._list.clear()
        for entry in entries:
            self._list.addItem(self._make_item(entry))

        if at_top:
            self._list.scrollToTop()
        else:
            bar.setValue(prev_scroll)

        self._status.setText("Записей нет" if not entries else f"Записей: {len(entries)}")

    def _make_item(self, entry: JournalEntry) -> QListWidgetItem:
        level = entry.level or "INFO"
        level_ru = _LEVEL_LABEL.get(level, level)
        ts = entry.timestamp or "—"
        src = entry.logger.split(".")[-1] if entry.logger else ""
        head = f"{ts}  [{level_ru}]"
        if src:
            head = f"{head}  {src}"
        text = f"{head}\n{entry.message}" if entry.message else head
        item = QListWidgetItem(text)
        item.setForeground(QColor(_LEVEL_COLOR.get(level, t.TEXT)))
        item.setData(Qt.ItemDataRole.UserRole, entry.raw)
        return item
