from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from brakovka_hmi.ui.modern import icons as ic
from brakovka_hmi.ui.modern import theme as t

_ASSETS = Path(__file__).resolve().parent.parent.parent / "assets"
_LOGO_H = 32


def _apply_prop(widget, name: str, value) -> None:
    widget.setProperty(name, value)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def _logo(filename: str) -> QLabel:
    label = QLabel()
    path = _ASSETS / filename
    pix = QPixmap(str(path))
    if not pix.isNull():
        pix = pix.scaledToHeight(_LOGO_H, Qt.TransformationMode.SmoothTransformation)
        label.setPixmap(pix)
        label.setFixedSize(pix.size())
    return label


def build_stylesheet() -> str:
    return f"""
    QMainWindow, QWidget {{
        background-color: {t.BG};
        color: {t.TEXT};
        font-family: {t.FONT};
        font-size: 10pt;
    }}
    #appHeader {{
        background-color: {t.SURFACE};
        border-bottom: 1px solid {t.BORDER};
    }}
    #pageTitle {{
        font-size: 15pt;
        font-weight: 700;
        color: {t.TEXT};
    }}
    #pageSubtitle {{
        font-size: 9pt;
        color: {t.TEXT_DIM};
    }}
    #connBadge {{
        font-size: 9pt;
        font-weight: 700;
        padding: 5px 12px;
        border-radius: 999px;
    }}
    #connBadge[connected="true"] {{
        color: {t.SUCCESS};
        background: rgba(52, 211, 153, 0.12);
        border: 1px solid rgba(52, 211, 153, 0.35);
    }}
    #connBadge[connected="false"] {{
        color: {t.ERROR};
        background: rgba(248, 113, 113, 0.12);
        border: 1px solid rgba(248, 113, 113, 0.35);
    }}
    #navRail {{
        background-color: {t.SURFACE};
        border-right: 1px solid {t.BORDER};
    }}
    QPushButton#navBtn {{
        border: none;
        border-radius: {t.RADIUS_SM}px;
        margin: 3px 10px;
        padding: 12px 12px 12px 10px;
        background: transparent;
        color: {t.TEXT_DIM};
        font-size: {t.FONT_NAV}pt;
        font-weight: 600;
        min-height: 54px;
        text-align: left;
    }}
    QPushButton#navBtn:checked {{
        background: {t.ACCENT_GLOW};
        color: {t.ACCENT};
        border: 1px solid rgba(34, 211, 238, 0.35);
    }}
    QPushButton#navBtn:hover:!checked {{
        background: {t.SURFACE_HOVER};
        color: {t.TEXT};
    }}
    #contentArea {{
        background-color: {t.BG};
    }}
    QScrollArea {{
        background: transparent;
        border: none;
    }}
    #stateBadge {{
        font-size: 10pt;
        font-weight: 700;
        border-radius: 999px;
        padding: 6px 16px;
    }}
    #stateBadge[statusLevel="ok"] {{
        color: {t.SUCCESS};
        background: {t.SUCCESS_BG};
        border: 1px solid {t.SUCCESS_BORDER};
    }}
    #stateBadge[statusLevel="warn"] {{
        color: {t.WARN};
        background: {t.WARN_BG};
        border: 1px solid {t.WARN_BORDER};
    }}
    #stateBadge[statusLevel="alarm"] {{
        color: {t.ERROR};
        background: {t.ERROR_BG};
        border: 1px solid {t.ERROR_BORDER};
    }}
    #stateBadge[statusLevel="neutral"] {{
        color: {t.ACCENT};
        background: {t.ACCENT_GLOW};
        border: 1px solid rgba(34, 211, 238, 0.35);
    }}
    QFrame#heroCard {{
        background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
            stop:0 {t.SURFACE_RAISED}, stop:1 {t.SURFACE});
        border-radius: {t.RADIUS}px;
        border: 2px solid {t.BORDER};
    }}
    QFrame#heroCard[heroLevel="ok"] {{
        border-color: {t.SUCCESS_BORDER};
        background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
            stop:0 rgba(52, 211, 153, 0.12), stop:1 {t.SURFACE});
    }}
    QFrame#heroCard[heroLevel="warn"] {{
        border-color: {t.WARN_BORDER};
        background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
            stop:0 rgba(251, 191, 36, 0.12), stop:1 {t.SURFACE});
    }}
    QFrame#heroCard[heroLevel="alarm"] {{
        border-color: {t.ERROR_BORDER};
        background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
            stop:0 rgba(248, 113, 113, 0.12), stop:1 {t.SURFACE});
    }}
    QLabel#heroLabel {{
        color: {t.TEXT_DIM};
        font-size: 10pt;
        font-weight: 600;
    }}
    QLabel#heroValue {{
        color: {t.TEXT};
        font-size: 48pt;
        font-weight: 800;
    }}
    QLabel#heroUnit {{
        color: {t.ACCENT};
        font-size: 12pt;
        font-weight: 600;
    }}
    QFrame#statCard {{
        background-color: {t.SURFACE};
        border: 1px solid {t.BORDER};
        border-radius: {t.RADIUS_SM}px;
    }}
    QFrame#statCard:hover {{
        border-color: rgba(34, 211, 238, 0.35);
    }}
    QFrame#statCard[cardLevel="ok"] {{
        border-color: {t.SUCCESS_BORDER};
        background-color: rgba(52, 211, 153, 0.06);
    }}
    QFrame#statCard[cardLevel="warn"] {{
        border-color: {t.WARN_BORDER};
        background-color: rgba(251, 191, 36, 0.06);
    }}
    QFrame#statCard[cardLevel="alarm"] {{
        border-color: {t.ERROR_BORDER};
        background-color: rgba(248, 113, 113, 0.06);
    }}
    QLabel#statTitle {{
        color: {t.TEXT_DIM};
        font-size: 9pt;
        font-weight: 600;
    }}
    QLabel#statValue {{
        color: {t.TEXT};
        font-size: {t.FONT_STAT_VALUE}pt;
        font-weight: 700;
    }}
    QLabel#statValueCompact {{
        color: {t.TEXT};
        font-size: {t.FONT_STAT_VALUE_COMPACT}pt;
        font-weight: 700;
    }}
    QLabel#statUnit {{
        color: {t.TEXT_MUTED};
        font-size: 9pt;
        padding-bottom: 3px;
    }}
    QFrame#panel {{
        background-color: {t.SURFACE};
        border: 1px solid {t.BORDER};
        border-radius: {t.RADIUS}px;
    }}
    QLabel#panelTitle {{
        color: {t.TEXT};
        font-size: 11pt;
        font-weight: 700;
    }}
    QLabel#hintText {{
        color: {t.TEXT_DIM};
        font-size: 9pt;
    }}
    QLabel#dirtyBadge {{
        color: {t.WARN};
        font-size: 10pt;
        font-weight: 700;
    }}
    QPushButton#cmdBtn {{
        min-height: 52px;
        border-radius: {t.RADIUS_SM}px;
        border: 1px solid {t.BORDER};
        background-color: {t.SURFACE_RAISED};
        color: {t.TEXT};
        font-size: 10pt;
        font-weight: 700;
        padding: 8px 12px;
    }}
    QPushButton#cmdOk {{
        min-height: 52px;
        border-radius: {t.RADIUS_SM}px;
        border: 1px solid {t.SUCCESS_BORDER};
        background-color: {t.SUCCESS_BG};
        color: {t.SUCCESS};
        font-size: 10pt;
        font-weight: 700;
        padding: 8px 12px;
    }}
    QPushButton#cmdOk:hover {{
        background-color: rgba(52, 211, 153, 0.28);
    }}
    QPushButton#cmdWarn {{
        min-height: 52px;
        border-radius: {t.RADIUS_SM}px;
        border: 1px solid {t.WARN_BORDER};
        background-color: {t.WARN_BG};
        color: {t.WARN};
        font-size: 10pt;
        font-weight: 700;
        padding: 8px 12px;
    }}
    QPushButton#cmdWarn:hover {{
        background-color: rgba(251, 191, 36, 0.28);
    }}
    QPushButton#cmdOk:disabled, QPushButton#cmdWarn:disabled, QPushButton#cmdBtn:disabled {{
        color: {t.TEXT_MUTED};
        background-color: {t.SURFACE};
        border-color: {t.BORDER};
    }}
    QPushButton#cmdBtn:hover {{
        border-color: {t.ACCENT};
        background-color: {t.SURFACE_HOVER};
    }}
    QPushButton#cmdDanger {{
        min-height: 52px;
        border-radius: {t.RADIUS_SM}px;
        border: 1px solid {t.ERROR_BORDER};
        background-color: {t.ERROR_BG};
        color: {t.ERROR};
        font-size: 10pt;
        font-weight: 700;
        padding: 8px 12px;
    }}
    QPushButton#cmdDanger:hover {{
        background-color: rgba(248, 113, 113, 0.28);
    }}
    QPushButton#cmdDanger:disabled {{
        color: {t.TEXT_MUTED};
        background-color: {t.SURFACE};
        border-color: {t.BORDER};
    }}
    QPushButton#cmdAccent {{
        min-height: 48px;
        border-radius: {t.RADIUS_SM}px;
        border: 1px solid rgba(34, 211, 238, 0.55);
        background-color: {t.ACCENT_GLOW};
        color: {t.TEXT};
        font-size: 10pt;
        font-weight: 700;
    }}
    QPushButton#cmdAccent:hover {{
        background-color: rgba(34, 211, 238, 0.28);
    }}
    QPushButton#chipBtn {{
        min-height: 40px;
        border-radius: 999px;
        border: 1px solid {t.BORDER};
        background-color: {t.SURFACE};
        color: {t.TEXT_DIM};
        font-size: 9pt;
        font-weight: 600;
        padding: 6px 14px;
    }}
    QPushButton#chipBtn:checked {{
        background-color: {t.ACCENT_GLOW};
        border-color: rgba(34, 211, 238, 0.45);
        color: {t.ACCENT};
    }}
    QPushButton#settingsTile {{
        text-align: left;
        padding: 16px;
        border: 1px solid {t.BORDER};
        border-radius: {t.RADIUS}px;
        background-color: {t.SURFACE};
        color: {t.TEXT};
        font-size: 11pt;
        font-weight: 700;
    }}
    QPushButton#settingsTile:hover {{
        border-color: rgba(34, 211, 238, 0.45);
        background-color: {t.SURFACE_RAISED};
    }}
    QPushButton#primary {{
        background-color: {t.ACCENT_GLOW};
        border: 1px solid rgba(34, 211, 238, 0.55);
        border-radius: {t.RADIUS_SM}px;
        padding: 10px 18px;
        font-weight: 700;
        color: {t.TEXT};
        min-height: 44px;
    }}
    QPushButton#primary:hover {{
        background-color: rgba(34, 211, 238, 0.28);
    }}
    QPushButton#cmd {{
        min-height: 44px;
        border-radius: {t.RADIUS_SM}px;
        border: 1px solid {t.BORDER};
        background-color: {t.SURFACE_RAISED};
        color: {t.TEXT};
        font-weight: 600;
    }}
    QPushButton#cmdStop {{
        min-height: 44px;
        border-radius: {t.RADIUS_SM}px;
        border: 1px solid rgba(248, 113, 113, 0.55);
        background-color: rgba(248, 113, 113, 0.1);
        color: {t.TEXT};
        font-weight: 700;
    }}
    QPushButton#settingsGroup {{
        text-align: left;
        padding: 14px;
        border: 1px solid {t.BORDER};
        border-radius: {t.RADIUS}px;
        background-color: {t.SURFACE};
        color: {t.TEXT};
        font-weight: 600;
    }}
    QPushButton#settingsGroup:hover {{
        border-color: rgba(34, 211, 238, 0.45);
    }}
    QLabel#screenTitle {{
        font-size: 15pt;
        font-weight: 700;
        color: {t.TEXT};
    }}
    QLabel#lampText {{
        color: {t.TEXT};
        font-size: 9pt;
    }}
    QFrame#card {{
        background-color: {t.SURFACE};
        border: 1px solid {t.BORDER};
        border-radius: {t.RADIUS_SM}px;
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
        color: {t.TEXT_MUTED};
        font-size: 9pt;
    }}
    QFrame#flagChip {{
        background-color: {t.SURFACE};
        border: 1px solid {t.BORDER};
        border-radius: {t.RADIUS_SM}px;
        min-height: 40px;
    }}
    QFrame#flagChip[chipLevel="ok"] {{
        border-color: {t.SUCCESS_BORDER};
        background-color: rgba(52, 211, 153, 0.1);
    }}
    QFrame#flagChip[chipLevel="warn"] {{
        border-color: {t.WARN_BORDER};
        background-color: rgba(251, 191, 36, 0.1);
    }}
    QFrame#flagChip[chipLevel="alarm"] {{
        border-color: {t.ERROR_BORDER};
        background-color: rgba(248, 113, 113, 0.1);
    }}
    QFrame#flagChip[chipLevel="off"] {{
        border-color: {t.BORDER};
        background-color: {t.SURFACE};
    }}
    QLineEdit, QDoubleSpinBox, QSpinBox {{
        background-color: {t.SURFACE_RAISED};
        border: 1px solid {t.BORDER};
        border-radius: 8px;
        padding: 8px 10px;
        color: {t.TEXT};
        min-height: 38px;
        font-size: 12pt;
    }}
    QDoubleSpinBox:focus, QSpinBox:focus, QLineEdit:focus {{
        border-color: {t.ACCENT};
    }}
    QRadioButton#pidMethod {{
        min-height: 40px;
        color: {t.TEXT};
    }}
    QRadioButton#pidMethod::indicator {{
        width: 20px;
        height: 20px;
    }}
    QRadioButton#pidMethod::indicator:unchecked {{
        border: 2px solid {t.BORDER};
        border-radius: 10px;
        background: {t.SURFACE_RAISED};
    }}
    QRadioButton#pidMethod::indicator:checked {{
        border: 2px solid {t.ACCENT};
        border-radius: 10px;
        background: rgba(34, 211, 238, 0.35);
    }}
    QWidget#trendPlot {{
        background-color: {t.SURFACE};
        border: 1px solid {t.BORDER};
        border-radius: {t.RADIUS}px;
    }}
    QProgressBar {{
        border: none;
        border-radius: 6px;
        background-color: {t.SURFACE_RAISED};
        text-align: center;
        color: {t.TEXT_DIM};
        min-height: 14px;
        max-height: 14px;
        font-size: 8pt;
        font-weight: 600;
    }}
    QProgressBar::chunk {{
        background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
            stop:0 {t.SUCCESS}, stop:1 {t.ACCENT});
        border-radius: 6px;
    }}
    QListWidget#journalList {{
        background-color: {t.SURFACE};
        border: 1px solid {t.BORDER};
        border-radius: {t.RADIUS}px;
        color: {t.TEXT};
        font-size: 10pt;
        padding: 6px;
    }}
    QListWidget#journalList::item {{
        padding: 10px 12px;
        border-bottom: 1px solid {t.BORDER};
        border-radius: 6px;
        margin: 2px 0;
    }}
    QListWidget#journalList::item:selected {{
        background-color: {t.ACCENT_GLOW};
    }}
    QLabel#journalHint {{
        color: {t.TEXT_DIM};
        font-size: 9pt;
    }}
    """


class AppHeader(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("appHeader")
        self.setFixedHeight(t.HEADER_HEIGHT)
        row = QHBoxLayout(self)
        row.setContentsMargins(16, 8, 16, 8)
        row.setSpacing(12)
        row.addWidget(_logo("IVCORE.png"))
        col = QVBoxLayout()
        col.setSpacing(0)
        self._title = QLabel("Пульт")
        self._title.setObjectName("pageTitle")
        self._subtitle = QLabel("Brakovka HMI")
        self._subtitle.setObjectName("pageSubtitle")
        col.addWidget(self._title)
        col.addWidget(self._subtitle)
        row.addLayout(col)
        row.addStretch()
        self._conn = QLabel("…")
        self._conn.setObjectName("connBadge")
        self._conn.setProperty("connected", False)
        row.addWidget(self._conn)
        row.addWidget(_logo("logo.png"))

    def set_page(self, title: str, subtitle: str = "Brakovka HMI") -> None:
        self._title.setText(title)
        self._subtitle.setText(subtitle)

    def set_connected(self, connected: bool, text: str) -> None:
        self._conn.setText(text)
        self._conn.setProperty("connected", connected)
        self._conn.style().unpolish(self._conn)
        self._conn.style().polish(self._conn)


class NavButton(QPushButton):
    def __init__(
        self,
        icon_name: str,
        label: str,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("navBtn")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(54)
        self.setIcon(ic.icon(icon_name, color=t.TEXT_DIM, size=24))
        self.setIconSize(ic.icon_size(24))
        self.setText(label)
        self.setToolTip(label)


class StatCard(QFrame):
    def __init__(
        self,
        icon_name: str,
        title: str,
        unit: str = "",
        *,
        compact: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("statCard")
        self.setProperty("cardLevel", "neutral")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.setMinimumHeight(72 if compact else 80)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12 if compact else 14, 10, 12 if compact else 14, 10)
        layout.setSpacing(4)

        top = QHBoxLayout()
        top.setSpacing(6)
        ico = QLabel()
        ico_sz = 20 if compact else 22
        ico.setPixmap(ic.icon(icon_name, color=t.ACCENT, size=ico_sz).pixmap(ico_sz, ico_sz))
        ico.setFixedSize(ico_sz, ico_sz)
        self._title = QLabel(title)
        self._title.setObjectName("statTitle")
        self._title.setWordWrap(True)
        top.addWidget(ico, 0, Qt.AlignmentFlag.AlignTop)
        top.addWidget(self._title, stretch=1)
        layout.addLayout(top)

        val_row = QHBoxLayout()
        val_row.setSpacing(4)
        self._value = QLabel("—")
        self._value.setObjectName("statValueCompact" if compact else "statValue")
        self._value.setWordWrap(True)
        unit_lbl = QLabel(unit)
        unit_lbl.setObjectName("statUnit")
        val_row.addWidget(self._value, stretch=1)
        val_row.addWidget(unit_lbl, 0, Qt.AlignmentFlag.AlignBottom)
        layout.addLayout(val_row)

    def set_value(self, text: str) -> None:
        if self._value.text() != text:
            self._value.setText(text)

    def set_level(self, level: str) -> None:
        if self.property("cardLevel") != level:
            _apply_prop(self, "cardLevel", level)


class HeroCard(QFrame):
    def __init__(
        self,
        caption: str = "Скорость линии",
        unit: str = "м/мин",
        icon_name: str = "speed",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("heroCard")
        self.setProperty("heroLevel", "neutral")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(16)

        ico = QLabel()
        ico.setPixmap(ic.icon(icon_name, color=t.ACCENT, size=40).pixmap(40, 40))
        ico.setFixedSize(40, 40)
        layout.addWidget(ico, 0, Qt.AlignmentFlag.AlignVCenter)

        col = QVBoxLayout()
        col.setSpacing(0)
        cap = QLabel(caption)
        cap.setObjectName("heroLabel")
        self._value = QLabel("—")
        self._value.setObjectName("heroValue")
        f = QFont(self.font())
        f.setPointSize(44)
        f.setWeight(QFont.Weight.ExtraBold)
        self._value.setFont(f)
        unit_lbl = QLabel(unit)
        unit_lbl.setObjectName("heroUnit")
        col.addWidget(cap)
        col.addWidget(self._value)
        col.addWidget(unit_lbl)
        layout.addLayout(col, stretch=1)

    def set_value(self, text: str) -> None:
        if self._value.text() != text:
            self._value.setText(text)

    def set_level(self, level: str) -> None:
        if self.property("heroLevel") != level:
            _apply_prop(self, "heroLevel", level)


class CmdButton(QPushButton):
    _STYLES = {
        "ok": ("cmdOk", t.SUCCESS),
        "warn": ("cmdWarn", t.WARN),
        "alarm": ("cmdDanger", t.ERROR),
        "neutral": ("cmdBtn", t.TEXT),
    }

    def __init__(
        self,
        icon_name: str,
        label: str,
        *,
        variant: str = "neutral",
        danger: bool = False,
        accent: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        if danger:
            variant = "alarm"
        elif accent:
            variant = "ok"
        obj_name, color = self._STYLES.get(variant, self._STYLES["neutral"])
        self.setObjectName(obj_name)
        self._icon_name = icon_name
        self._icon_color = color
        self.setIcon(ic.icon(icon_name, color=color, size=22))
        self.setIconSize(ic.icon_size(22))
        self.setText(label)
        self.setCursor(Qt.CursorShape.PointingHandCursor)


class PageBar(QWidget):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self._title = QLabel(title)
        self._title.setObjectName("screenTitle")
        row.addWidget(self._title)
        row.addStretch()
        self._badge = QLabel("")
        self._badge.setObjectName("stateBadge")
        self._badge.setProperty("statusLevel", "neutral")
        self._badge.hide()
        row.addWidget(self._badge)
        self._dirty = QLabel("")
        self._dirty.setObjectName("dirtyBadge")
        row.addWidget(self._dirty)

    def set_badge(self, text: str, level: str = "neutral") -> None:
        if text:
            self._badge.setText(text)
            _apply_prop(self._badge, "statusLevel", level)
            self._badge.show()
        else:
            self._badge.hide()

    def set_title(self, text: str) -> None:
        self._title.setText(text)

    def set_dirty(self, dirty: bool) -> None:
        self._dirty.setText("Не сохранено" if dirty else "")


class Panel(QFrame):
    def __init__(self, title: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("panel")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(16, 14, 16, 14)
        self._layout.setSpacing(10)
        if title:
            lbl = QLabel(title)
            lbl.setObjectName("panelTitle")
            self._layout.addWidget(lbl)

    def body_layout(self) -> QVBoxLayout:
        return self._layout


class FlagChip(QFrame):
    def __init__(self, icon_name: str, label: str, *, alarm: bool = False) -> None:
        super().__init__()
        self.setObjectName("flagChip")
        self.setProperty("chipLevel", "off")
        self._alarm = alarm
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.setMinimumHeight(44)
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 10, 10, 10)
        row.setSpacing(8)
        self._ico = QLabel()
        self._ico.setFixedSize(18, 18)
        self._ico.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._icon_name = icon_name
        self._label = QLabel(label)
        self._label.setObjectName("lampText")
        self._label.setWordWrap(True)
        row.addWidget(self._ico, 0, Qt.AlignmentFlag.AlignTop)
        row.addWidget(self._label, stretch=1)
        self._chip_level = "off"
        self._refresh_icon("off")

    def set_chip_level(self, level: str) -> None:
        if self._chip_level == level:
            return
        self._chip_level = level
        _apply_prop(self, "chipLevel", level)
        self._refresh_icon(level)

    def set_active(self, active: bool) -> None:
        self.set_chip_level("ok" if active and not self._alarm else ("alarm" if active and self._alarm else "off"))

    def set_label(self, text: str) -> None:
        if self._label.text() != text:
            self._label.setText(text)

    def _refresh_icon(self, level: str) -> None:
        if level == "alarm":
            color, name = t.ERROR, "warning"
        elif level == "warn":
            color, name = t.WARN, "warning"
        elif level == "ok":
            color, name = t.SUCCESS, "check"
        else:
            color, name = t.TEXT_MUTED, self._icon_name
        self._ico.setPixmap(ic.icon(name, color=color, size=18).pixmap(18, 18))


class SettingsTile(QPushButton):
    def __init__(
        self,
        icon_name: str,
        title: str,
        subtitle: str,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("settingsTile")
        self.setMinimumHeight(96)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setText(f"{title}\n{subtitle}")
        self.setIcon(ic.icon(icon_name, color=t.ACCENT, size=28))
        self.setIconSize(ic.icon_size(28))
