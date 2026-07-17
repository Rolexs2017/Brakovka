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

from brakovka_hmi.ui import theme as t

_ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
# Same display height for both logos; width follows aspect ratio.
LOGO_DISPLAY_HEIGHT = 52


def _scaled_logo(filename: str, height: int = LOGO_DISPLAY_HEIGHT) -> QPixmap:
    path = _ASSETS_DIR / filename
    pix = QPixmap(str(path))
    if pix.isNull():
        return pix
    return pix.scaledToHeight(
        height,
        Qt.TransformationMode.SmoothTransformation,
    )


def make_logo_label(filename: str, height: int = LOGO_DISPLAY_HEIGHT) -> QLabel:
    label = QLabel()
    label.setObjectName("logoMark")
    pix = _scaled_logo(filename, height)
    if not pix.isNull():
        label.setPixmap(pix)
        label.setFixedSize(pix.size())
    else:
        label.setText(filename)
        label.setFixedHeight(height)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return label


def make_logo_header(parent: QWidget | None = None) -> QWidget:
    """Top bar: IVCORE left, logo right — same height on all screens."""
    bar = QWidget(parent)
    bar.setObjectName("logoHeader")
    bar.setFixedHeight(LOGO_DISPLAY_HEIGHT + 16)
    row = QHBoxLayout(bar)
    row.setContentsMargins(16, 8, 16, 8)
    row.setSpacing(12)
    row.addWidget(make_logo_label("IVCORE.png"), 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    row.addStretch(1)
    row.addWidget(make_logo_label("logo.png"), 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return bar


class ValueCard(QFrame):
    def __init__(self, title: str, unit: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(2)

        self._title = QLabel(title)
        self._title.setObjectName("cardTitle")
        self._title.setWordWrap(True)
        self._value = QLabel("—")
        self._value.setObjectName("cardValue")
        self._unit = QLabel(unit)
        self._unit.setObjectName("cardUnit")

        row = QHBoxLayout()
        row.addWidget(self._value)
        row.addStretch()
        row.addWidget(self._unit)

        layout.addWidget(self._title)
        layout.addLayout(row)

    def set_value(self, text: str) -> None:
        self._value.setText(text)


class StatusLamp(QWidget):
    def __init__(self, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._dot = QLabel("●")
        self._dot.setFixedWidth(18)
        dot_font = QFont(self.font())
        dot_font.setPointSize(12)
        self._dot.setFont(dot_font)
        self._set_dot_active(False)

        self._text = QLabel(label)
        self._text.setObjectName("lampText")
        self._text.setWordWrap(True)
        self._text.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        layout.addWidget(self._dot, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self._text, 1)

    def _set_dot_active(self, active: bool) -> None:
        color = t.OK if active else "#334155"
        self._dot.setStyleSheet(f"color: {color};")

    def set_active(self, active: bool) -> None:
        self._set_dot_active(active)

    def set_label(self, text: str) -> None:
        self._text.setText(text)


def build_stylesheet() -> str:
    return f"""
    QMainWindow, QWidget {{
        background-color: {t.BG};
        color: {t.TEXT};
        font-family: "Segoe UI", "Ubuntu", sans-serif;
    }}
    #sidebar {{
        background-color: {t.PANEL};
        border-right: 1px solid {t.BORDER};
    }}
    #brand {{
        font-size: 18pt;
        font-weight: 700;
        color: {t.BORDER};
        padding: 20px 16px 8px 16px;
    }}
    QPushButton#nav {{
        text-align: left;
        padding: 14px 18px;
        border: 1px solid transparent;
        border-radius: 8px;
        margin: 4px 12px;
        background-color: transparent;
        color: {t.TEXT};
        font-size: 11pt;
    }}
    QPushButton#nav:hover {{
        border-color: {t.BORDER};
    }}
    QPushButton#nav:checked {{
        background-color: rgba(255, 107, 53, 0.18);
        border-color: {t.ACCENT};
        color: {t.ACCENT};
    }}
    #content {{
        background-color: {t.BG};
    }}
    #logoHeader {{
        background-color: {t.BG};
        border-bottom: 1px solid {t.BORDER};
    }}
    #screenTitle {{
        font-size: 16pt;
        font-weight: 600;
        color: {t.TEXT};
        padding: 0 0 8px 0;
    }}
    #connBad {{
        color: {t.ERROR};
        font-weight: 600;
    }}
    QFrame#card {{
        background-color: {t.PANEL};
        border: 1px solid {t.BORDER};
        border-radius: 10px;
    }}
    QLabel#cardTitle {{
        color: {t.TEXT_DIM};
        font-size: 10pt;
    }}
    QLabel#cardValue {{
        font-size: 18pt;
        font-weight: 700;
        color: {t.TEXT};
    }}
    QLabel#cardUnit {{
        color: {t.TEXT_DIM};
        font-size: 10pt;
        padding-top: 8px;
    }}
    QLabel#stateBadge {{
        background-color: rgba(0, 212, 255, 0.12);
        border: 1px solid {t.BORDER};
        border-radius: 8px;
        padding: 10px 16px;
        font-size: 14pt;
        font-weight: 700;
    }}
    QPushButton#cmd {{
        min-height: 40px;
        border-radius: 10px;
        border: 1px solid {t.BORDER};
        background-color: {t.PANEL};
        color: {t.TEXT};
        font-size: 11pt;
        font-weight: 600;
    }}
    QPushButton#cmd:hover {{
        border-color: {t.ACCENT};
        color: {t.ACCENT};
    }}
    QPushButton#cmd:pressed {{
        background-color: rgba(255, 107, 53, 0.25);
    }}
    QPushButton#cmdStop {{
        min-height: 40px;
        border-radius: 10px;
        border: 1px solid {t.ERROR};
        background-color: {t.PANEL};
        color: {t.TEXT};
        font-size: 11pt;
        font-weight: 600;
    }}
    QPushButton#cmdStop:hover {{
        color: {t.ERROR};
    }}
    QLabel#lampText {{
        color: {t.TEXT};
        font-size: 10pt;
    }}
    QLineEdit, QDoubleSpinBox, QSpinBox {{
        background-color: {t.PANEL};
        border: 1px solid {t.BORDER};
        border-radius: 6px;
        padding: 8px;
        color: {t.TEXT};
        min-height: 36px;
        font-size: 12pt;
    }}
    QDoubleSpinBox:focus, QSpinBox:focus {{
        border-color: {t.ACCENT};
    }}
    QPushButton#primary {{
        background-color: rgba(0, 212, 255, 0.15);
        border: 1px solid {t.BORDER};
        border-radius: 8px;
        padding: 10px 18px;
        font-weight: 600;
    }}
    QPushButton#primary:hover {{
        background-color: rgba(0, 212, 255, 0.28);
    }}
    QPushButton#settingsGroup {{
        text-align: center;
        padding: 16px 12px;
        border: 1px solid {t.BORDER};
        border-radius: 10px;
        background-color: {t.PANEL};
        color: {t.TEXT};
        font-size: 12pt;
        font-weight: 600;
    }}
    QRadioButton#pidMethod {{
        min-height: 44px;
        spacing: 10px;
        color: {t.TEXT};
        font-size: 10pt;
        font-weight: 600;
        padding: 6px 8px;
    }}
    QRadioButton#pidMethod::indicator {{
        width: 26px;
        height: 26px;
    }}
    QRadioButton#pidMethod::indicator:unchecked {{
        border: 2px solid {t.BORDER};
        border-radius: 13px;
        background-color: {t.PANEL};
    }}
    QRadioButton#pidMethod::indicator:checked {{
        border: 2px solid {t.BORDER};
        border-radius: 13px;
        background-color: rgba(0, 212, 255, 0.35);
    }}
    QRadioButton#pidMethod:disabled {{
        color: #5a6a78;
    }}
    QPushButton#settingsGroup:hover {{
        border-color: {t.ACCENT};
        color: {t.ACCENT};
    }}
    QPushButton#settingsGroup:pressed {{
        background-color: rgba(255, 107, 53, 0.2);
    }}
    QWidget#trendPlot {{
        background-color: {t.PANEL};
        border: 1px solid {t.BORDER};
        border-radius: 10px;
    }}
    QProgressBar {{
        border: 1px solid {t.BORDER};
        border-radius: 6px;
        background-color: {t.PANEL};
        text-align: center;
        color: {t.TEXT};
        min-height: 22px;
        max-height: 22px;
    }}
    QProgressBar::chunk {{
        background-color: {t.ACCENT};
        border-radius: 5px;
    }}
    QListWidget#journalList {{
        background-color: {t.PANEL};
        border: 1px solid {t.BORDER};
        border-radius: 10px;
        color: {t.TEXT};
        font-size: 11pt;
        padding: 4px;
        outline: none;
    }}
    QListWidget#journalList::item {{
        padding: 10px 12px;
        border-bottom: 1px solid rgba(0, 212, 255, 0.18);
        min-height: 48px;
    }}
    QListWidget#journalList::item:selected {{
        background-color: rgba(255, 107, 53, 0.18);
    }}
    QLabel#journalHint {{
        color: {t.TEXT_DIM};
        font-size: 9pt;
    }}
    """
