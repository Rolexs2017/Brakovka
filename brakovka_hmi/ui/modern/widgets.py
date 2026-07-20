from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from brakovka_hmi.ui.modern import theme as t

_ASSETS_DIR = Path(__file__).resolve().parent.parent.parent / "assets"
LOGO_HEIGHT = 28


def _logo_label(filename: str) -> QLabel:
    label = QLabel()
    path = _ASSETS_DIR / filename
    pix = QPixmap(str(path))
    if not pix.isNull():
        pix = pix.scaledToHeight(LOGO_HEIGHT, Qt.TransformationMode.SmoothTransformation)
        label.setPixmap(pix)
        label.setFixedSize(pix.size())
    return label


def make_compact_header(parent: QWidget | None = None) -> QWidget:
    bar = QWidget(parent)
    bar.setObjectName("topBar")
    bar.setFixedHeight(t.HEADER_HEIGHT)
    row = QHBoxLayout(bar)
    row.setContentsMargins(12, 6, 12, 6)
    row.setSpacing(10)
    row.addWidget(_logo_label("IVCORE.png"))
    row.addStretch(1)
    row.addWidget(_logo_label("logo.png"))
    return bar


class MetricTile(QFrame):
    """Compact metric: label on top, large value + unit."""

    def __init__(self, title: str, unit: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("metricTile")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(2)

        self._title = QLabel(title)
        self._title.setObjectName("metricTitle")
        self._value = QLabel("—")
        self._value.setObjectName("metricValue")
        unit_lbl = QLabel(unit)
        unit_lbl.setObjectName("metricUnit")

        val_row = QHBoxLayout()
        val_row.setSpacing(6)
        val_row.addWidget(self._value)
        val_row.addWidget(unit_lbl, 0, Qt.AlignmentFlag.AlignBottom)
        val_row.addStretch()

        layout.addWidget(self._title)
        layout.addLayout(val_row)

    def set_value(self, text: str) -> None:
        if self._value.text() == text:
            return
        self._value.setText(text)


class HeroSpeed(QFrame):
    """Large speed readout for the main dashboard."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("heroSpeed")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(0)

        cap = QLabel("Скорость")
        cap.setObjectName("heroCaption")
        self._value = QLabel("—")
        self._value.setObjectName("heroValue")
        f = QFont(self.font())
        f.setPointSize(42)
        f.setWeight(QFont.Weight.Bold)
        self._value.setFont(f)
        unit = QLabel("м/мин")
        unit.setObjectName("heroUnit")

        layout.addWidget(cap)
        layout.addWidget(self._value)
        layout.addWidget(unit)

    def set_value(self, text: str) -> None:
        if self._value.text() == text:
            return
        self._value.setText(text)


def build_stylesheet() -> str:
    return f"""
    QMainWindow, QWidget {{
        background-color: {t.BG};
        color: {t.TEXT};
        font-family: "Segoe UI", "Ubuntu", sans-serif;
    }}
    #topBar {{
        background-color: {t.PANEL};
        border-bottom: 1px solid {t.BORDER};
    }}
    #sidebar {{
        background-color: {t.PANEL};
        border-right: 1px solid {t.BORDER};
    }}
    QPushButton#navCompact {{
        border: none;
        border-radius: 10px;
        margin: 3px 8px;
        padding: 10px 4px;
        background-color: transparent;
        color: {t.TEXT_DIM};
        font-size: 9pt;
        font-weight: 600;
    }}
    QPushButton#navCompact:checked {{
        background-color: {t.PANEL_ELEVATED};
        color: {t.ACCENT};
    }}
    QPushButton#navCompact:hover:!checked {{
        background-color: rgba(88, 166, 255, 0.08);
        color: {t.TEXT};
    }}
    #connPill {{
        font-size: 9pt;
        font-weight: 600;
        padding: 6px 8px;
        border-radius: 8px;
    }}
    #connPill[connected="true"] {{
        color: {t.OK};
        background-color: rgba(63, 185, 80, 0.12);
    }}
    #connPill[connected="false"] {{
        color: {t.ERROR};
        background-color: rgba(248, 81, 73, 0.12);
    }}
    #content {{
        background-color: {t.BG};
    }}
    #pageTitle {{
        font-size: 13pt;
        font-weight: 600;
        color: {t.TEXT_DIM};
        padding: 0 0 4px 0;
    }}
    #stateChip {{
        font-size: 11pt;
        font-weight: 700;
        color: {t.ACCENT};
        background-color: rgba(88, 166, 255, 0.12);
        border: 1px solid {t.BORDER};
        border-radius: 999px;
        padding: 6px 16px;
    }}
    QFrame#heroSpeed {{
        background-color: {t.PANEL};
        border: 1px solid {t.BORDER};
        border-radius: 14px;
    }}
    QLabel#heroCaption {{
        color: {t.TEXT_DIM};
        font-size: 10pt;
    }}
    QLabel#heroValue {{
        color: {t.TEXT};
    }}
    QLabel#heroUnit {{
        color: {t.TEXT_DIM};
        font-size: 11pt;
        padding-top: 2px;
    }}
    QFrame#metricTile {{
        background-color: {t.PANEL};
        border: 1px solid {t.BORDER};
        border-radius: 12px;
    }}
    QLabel#metricTitle {{
        color: {t.TEXT_DIM};
        font-size: 9pt;
    }}
    QLabel#metricValue {{
        font-size: 20pt;
        font-weight: 700;
        color: {t.TEXT};
    }}
    QLabel#metricUnit {{
        color: {t.TEXT_DIM};
        font-size: 9pt;
        padding-bottom: 4px;
    }}
    QFrame#card {{
        background-color: {t.PANEL};
        border: 1px solid {t.BORDER};
        border-radius: 12px;
    }}
    QLabel#cardTitle {{
        color: {t.TEXT_DIM};
        font-size: 9pt;
    }}
    QLabel#cardValue {{
        font-size: 18pt;
        font-weight: 700;
        color: {t.TEXT};
    }}
    QLabel#cardUnit {{
        color: {t.TEXT_DIM};
        font-size: 9pt;
        padding-top: 6px;
    }}
    QLabel#screenTitle {{
        font-size: 14pt;
        font-weight: 600;
        color: {t.TEXT};
    }}
    QLabel#stateBadge {{
        background-color: rgba(88, 166, 255, 0.1);
        border: 1px solid {t.BORDER};
        border-radius: 8px;
        padding: 8px 14px;
        font-size: 12pt;
        font-weight: 700;
    }}
    QPushButton#cmd {{
        min-height: 48px;
        border-radius: 12px;
        border: 1px solid {t.BORDER};
        background-color: {t.PANEL_ELEVATED};
        color: {t.TEXT};
        font-size: 11pt;
        font-weight: 600;
    }}
    QPushButton#cmd:hover {{
        border-color: {t.ACCENT};
        color: {t.ACCENT};
    }}
    QPushButton#cmdStop {{
        min-height: 48px;
        border-radius: 12px;
        border: 1px solid {t.ERROR};
        background-color: rgba(248, 81, 73, 0.08);
        color: {t.TEXT};
        font-size: 11pt;
        font-weight: 700;
    }}
    QPushButton#cmdStop:hover {{
        background-color: rgba(248, 81, 73, 0.18);
        color: {t.ERROR};
    }}
    QPushButton#primary {{
        background-color: rgba(88, 166, 255, 0.14);
        border: 1px solid {t.ACCENT};
        border-radius: 10px;
        padding: 10px 18px;
        font-weight: 600;
        color: {t.TEXT};
    }}
    QPushButton#primary:hover {{
        background-color: rgba(88, 166, 255, 0.24);
    }}
    QLabel#lampText {{
        color: {t.TEXT};
        font-size: 10pt;
    }}
    QLineEdit, QDoubleSpinBox, QSpinBox {{
        background-color: {t.PANEL_ELEVATED};
        border: 1px solid {t.BORDER};
        border-radius: 8px;
        padding: 8px;
        color: {t.TEXT};
        min-height: 36px;
        font-size: 12pt;
    }}
    QDoubleSpinBox:focus, QSpinBox:focus {{
        border-color: {t.ACCENT};
    }}
    QPushButton#settingsGroup {{
        text-align: center;
        padding: 14px 10px;
        border: 1px solid {t.BORDER};
        border-radius: 12px;
        background-color: {t.PANEL};
        color: {t.TEXT};
        font-size: 11pt;
        font-weight: 600;
    }}
    QPushButton#settingsGroup:hover {{
        border-color: {t.ACCENT};
        color: {t.ACCENT};
    }}
    QRadioButton#pidMethod {{
        min-height: 40px;
        color: {t.TEXT};
        font-size: 10pt;
    }}
    QRadioButton#pidMethod::indicator {{
        width: 22px;
        height: 22px;
    }}
    QRadioButton#pidMethod::indicator:unchecked {{
        border: 2px solid {t.BORDER};
        border-radius: 11px;
        background-color: {t.PANEL_ELEVATED};
    }}
    QRadioButton#pidMethod::indicator:checked {{
        border: 2px solid {t.ACCENT};
        border-radius: 11px;
        background-color: rgba(88, 166, 255, 0.35);
    }}
    QWidget#trendPlot {{
        background-color: {t.PANEL};
        border: 1px solid {t.BORDER};
        border-radius: 12px;
    }}
    QProgressBar {{
        border: none;
        border-radius: 4px;
        background-color: {t.PANEL_ELEVATED};
        text-align: center;
        color: {t.TEXT_DIM};
        min-height: 8px;
        max-height: 8px;
        font-size: 8pt;
    }}
    QProgressBar::chunk {{
        background-color: {t.ACCENT};
        border-radius: 4px;
    }}
    QListWidget#journalList {{
        background-color: {t.PANEL};
        border: 1px solid {t.BORDER};
        border-radius: 12px;
        color: {t.TEXT};
        font-size: 10pt;
        padding: 4px;
    }}
    QListWidget#journalList::item {{
        padding: 8px 10px;
        border-bottom: 1px solid {t.BORDER};
    }}
    QListWidget#journalList::item:selected {{
        background-color: rgba(88, 166, 255, 0.14);
    }}
    """
