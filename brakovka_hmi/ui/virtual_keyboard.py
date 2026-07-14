"""Touch numeric keypad for HMI spinboxes and password entry."""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QDoubleSpinBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from brakovka_hmi.ui import theme as t
from brakovka_hmi.sounds import play_error, play_key, play_ok


def _key_button(text: str, *, object_name: str = "keypadKey") -> QPushButton:
    btn = QPushButton(text)
    btn.setObjectName(object_name)
    btn.setMinimumSize(72, 64)
    btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    font = QFont(btn.font())
    font.setPointSize(16)
    font.setBold(True)
    btn.setFont(font)
    return btn


class NumericKeypadDialog(QDialog):
    """Modal numeric keypad. Returns accepted text via ``value_text()``."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        title: str = "Ввод значения",
        initial: str = "",
        allow_decimal: bool = True,
        allow_negative: bool = False,
        password: bool = False,
        suffix: str = "",
        hint: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setObjectName("keypadDialog")
        self.setStyleSheet(_keypad_stylesheet())

        self._allow_decimal = allow_decimal
        self._allow_negative = allow_negative
        self._password = password
        self._text = ""
        self._replace_on_digit = bool(initial) and not password

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        header = QLabel(title)
        header.setObjectName("keypadTitle")
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(header)

        if hint:
            hint_lbl = QLabel(hint)
            hint_lbl.setObjectName("keypadHint")
            hint_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            hint_lbl.setWordWrap(True)
            root.addWidget(hint_lbl)

        display_row = QHBoxLayout()
        self._display = QLabel()
        self._display.setObjectName("keypadDisplay")
        self._display.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._display.setMinimumHeight(56)
        display_row.addWidget(self._display, stretch=1)
        if suffix:
            unit = QLabel(suffix.strip())
            unit.setObjectName("keypadSuffix")
            display_row.addWidget(unit)
        root.addLayout(display_row)

        grid = QGridLayout()
        grid.setSpacing(8)
        keys = [
            ("7", 0, 0), ("8", 0, 1), ("9", 0, 2),
            ("4", 1, 0), ("5", 1, 1), ("6", 1, 2),
            ("1", 2, 0), ("2", 2, 1), ("3", 2, 2),
            ("0", 3, 0),
        ]
        for label, row, col in keys:
            btn = _key_button(label)
            btn.clicked.connect(lambda _=False, d=label: self._append(d))
            grid.addWidget(btn, row, col)

        if allow_decimal:
            dot = _key_button(".")
            dot.clicked.connect(lambda: self._append("."))
            grid.addWidget(dot, 3, 1)
        else:
            spacer = QWidget()
            spacer.setMinimumSize(72, 64)
            grid.addWidget(spacer, 3, 1)

        back = _key_button("⌫", object_name="keypadAction")
        back.clicked.connect(self._backspace)
        grid.addWidget(back, 3, 2)

        if allow_negative:
            minus = _key_button("±", object_name="keypadAction")
            minus.clicked.connect(self._toggle_sign)
            grid.addWidget(minus, 0, 3)
            clear = _key_button("C", object_name="keypadAction")
            clear.clicked.connect(self._clear)
            grid.addWidget(clear, 1, 3)
            cancel = _key_button("Отмена", object_name="keypadCancel")
            cancel.clicked.connect(self._on_cancel)
            grid.addWidget(cancel, 2, 3)
            ok = _key_button("OK", object_name="keypadOk")
            ok.clicked.connect(self._on_ok)
            grid.addWidget(ok, 3, 3)
        else:
            clear = _key_button("C", object_name="keypadAction")
            clear.clicked.connect(self._clear)
            grid.addWidget(clear, 0, 3)
            cancel = _key_button("Отмена", object_name="keypadCancel")
            cancel.clicked.connect(self._on_cancel)
            grid.addWidget(cancel, 1, 3)
            ok = _key_button("OK", object_name="keypadOk")
            ok.clicked.connect(self._on_ok)
            grid.addWidget(ok, 2, 3, 2, 1)

        root.addLayout(grid)

        if initial:
            self._text = str(initial)
        self._refresh_display()
        self.adjustSize()

    def value_text(self) -> str:
        return self._text

    def _on_ok(self) -> None:
        play_ok()
        self.accept()

    def _on_cancel(self) -> None:
        play_key()
        self.reject()

    def _refresh_display(self) -> None:
        if self._password:
            shown = "•" * len(self._text) if self._text else ""
        else:
            shown = self._text if self._text else "0"
        self._display.setText(shown)

    def _append(self, ch: str) -> None:
        if ch == "." and (not self._allow_decimal or "." in self._text):
            play_error()
            return
        play_key()
        if self._replace_on_digit:
            self._text = ""
            self._replace_on_digit = False
        if ch == ".":
            if not self._text or self._text == "-":
                self._text += "0."
            else:
                self._text += "."
        else:
            if self._text in ("0", "-0") and ch != ".":
                self._text = ("-" if self._text.startswith("-") else "") + ch
            else:
                self._text += ch
        self._refresh_display()

    def _backspace(self) -> None:
        play_key()
        self._replace_on_digit = False
        self._text = self._text[:-1]
        self._refresh_display()

    def _clear(self) -> None:
        play_key()
        self._replace_on_digit = False
        self._text = ""
        self._refresh_display()

    def _toggle_sign(self) -> None:
        play_key()
        self._replace_on_digit = False
        if not self._allow_negative:
            return
        if self._text.startswith("-"):
            self._text = self._text[1:]
        else:
            self._text = "-" + self._text
        self._refresh_display()


def ask_number(
    parent: QWidget | None,
    *,
    title: str,
    value: float,
    minimum: float,
    maximum: float,
    decimals: int = 0,
    suffix: str = "",
) -> float | None:
    """Open keypad and return a clamped number, or None if cancelled."""
    if decimals <= 0:
        initial = str(int(round(value)))
        allow_decimal = False
    else:
        initial = f"{value:.{decimals}f}".rstrip("0").rstrip(".")
        allow_decimal = True

    dlg = NumericKeypadDialog(
        parent,
        title=title,
        initial=initial,
        allow_decimal=allow_decimal,
        allow_negative=minimum < 0,
        suffix=suffix,
        hint=f"Диапазон: {minimum:g} … {maximum:g}",
    )
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return None

    text = dlg.value_text().strip()
    if not text or text in ("-", ".", "-."):
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    number = max(minimum, min(maximum, number))
    if decimals <= 0:
        return float(int(round(number)))
    return round(number, decimals)


def ask_password(
    parent: QWidget | None,
    *,
    title: str = "Пароль",
    prompt: str = "Введите пароль",
) -> str | None:
    dlg = NumericKeypadDialog(
        parent,
        title=title,
        initial="",
        allow_decimal=False,
        allow_negative=False,
        password=True,
        hint=prompt,
    )
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return None
    return dlg.value_text()


def _open_for_spin(spin: QSpinBox | QDoubleSpinBox, title: str) -> None:
    decimals = int(spin.decimals()) if isinstance(spin, QDoubleSpinBox) else 0
    suffix = spin.suffix() if hasattr(spin, "suffix") else ""
    result = ask_number(
        spin.window(),
        title=title,
        value=float(spin.value()),
        minimum=float(spin.minimum()),
        maximum=float(spin.maximum()),
        decimals=decimals,
        suffix=suffix,
    )
    if result is None:
        return
    if isinstance(spin, QDoubleSpinBox):
        spin.setValue(float(result))
    else:
        spin.setValue(int(round(result)))


class _TouchSpinMixin:
    """Open keypad on tap; lineEdit also receives presses on touch panels."""

    _keypad_title: str
    _keypad_open: bool

    def _setup_touch_spin(self, title: str) -> None:
        from brakovka_hmi.ui.osk import disable_widget_input_method

        self._keypad_title = title
        self._keypad_open = False
        self.setButtonSymbols(self.ButtonSymbols.NoButtons)  # type: ignore[attr-defined]
        self.setReadOnly(True)
        edit = self.lineEdit()  # type: ignore[attr-defined]
        edit.setReadOnly(True)
        edit.installEventFilter(self)  # type: ignore[arg-type]
        # NoFocus + WA_InputMethodEnabled=False → Raspberry OSK must not open.
        disable_widget_input_method(self)  # type: ignore[arg-type]

    def eventFilter(self, obj, event) -> bool:  # noqa: ANN001
        if (
            obj is self.lineEdit()  # type: ignore[attr-defined]
            and event.type() == QEvent.Type.MouseButtonPress
            and event.button() == Qt.MouseButton.LeftButton
            and self.isEnabled()  # type: ignore[attr-defined]
        ):
            self._show_keypad()
            return True
        return super().eventFilter(obj, event)  # type: ignore[misc]

    def mousePressEvent(self, event) -> None:  # noqa: ANN001
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():  # type: ignore[attr-defined]
            self._show_keypad()
            event.accept()
            return
        super().mousePressEvent(event)  # type: ignore[misc]

    def _show_keypad(self) -> None:
        if self._keypad_open:
            return
        self._keypad_open = True
        try:
            # Clear focus so Wayland/Qt do not keep requesting the system OSK.
            w = self.window()  # type: ignore[attr-defined]
            if w is not None:
                fw = w.focusWidget()
                if fw is not None:
                    fw.clearFocus()
            _open_for_spin(self, self._keypad_title)  # type: ignore[arg-type]
        finally:
            self._keypad_open = False


class TouchSpinBox(_TouchSpinMixin, QSpinBox):
    """Integer spinbox that opens a virtual keypad on tap."""

    def __init__(self, parent: QWidget | None = None, *, keypad_title: str = "Ввод") -> None:
        super().__init__(parent)
        self._setup_touch_spin(keypad_title)


class TouchDoubleSpinBox(_TouchSpinMixin, QDoubleSpinBox):
    """Float spinbox that opens a virtual keypad on tap."""

    def __init__(self, parent: QWidget | None = None, *, keypad_title: str = "Ввод") -> None:
        super().__init__(parent)
        self._setup_touch_spin(keypad_title)


def _keypad_stylesheet() -> str:
    return f"""
    #keypadDialog {{
        background-color: {t.BG};
        border: 2px solid {t.BORDER};
        border-radius: 12px;
    }}
    #keypadTitle {{
        color: {t.TEXT};
        font-size: 16pt;
        font-weight: 700;
    }}
    #keypadHint {{
        color: {t.TEXT_DIM};
        font-size: 10pt;
    }}
    #keypadDisplay {{
        background-color: {t.PANEL};
        border: 1px solid {t.BORDER};
        border-radius: 8px;
        color: {t.TEXT};
        font-size: 22pt;
        font-weight: 700;
        padding: 8px 14px;
        min-width: 220px;
    }}
    #keypadSuffix {{
        color: {t.TEXT_DIM};
        font-size: 14pt;
        padding-left: 8px;
    }}
    QPushButton#keypadKey {{
        background-color: {t.PANEL};
        border: 1px solid {t.BORDER};
        border-radius: 10px;
        color: {t.TEXT};
        font-size: 16pt;
        font-weight: 700;
        min-width: 72px;
        min-height: 64px;
    }}
    QPushButton#keypadKey:pressed {{
        background-color: rgba(0, 212, 255, 0.25);
        border-color: {t.ACCENT};
    }}
    QPushButton#keypadAction {{
        background-color: {t.PANEL};
        border: 1px solid {t.TEXT_DIM};
        border-radius: 10px;
        color: {t.TEXT};
        font-size: 14pt;
        font-weight: 600;
        min-width: 88px;
        min-height: 64px;
    }}
    QPushButton#keypadAction:pressed {{
        background-color: rgba(255, 107, 53, 0.2);
    }}
    QPushButton#keypadOk {{
        background-color: rgba(61, 220, 132, 0.18);
        border: 1px solid {t.OK};
        border-radius: 10px;
        color: {t.OK};
        font-size: 14pt;
        font-weight: 700;
        min-width: 88px;
        min-height: 64px;
    }}
    QPushButton#keypadOk:pressed {{
        background-color: rgba(61, 220, 132, 0.35);
    }}
    QPushButton#keypadCancel {{
        background-color: rgba(255, 77, 77, 0.12);
        border: 1px solid {t.ERROR};
        border-radius: 10px;
        color: {t.ERROR};
        font-size: 12pt;
        font-weight: 600;
        min-width: 88px;
        min-height: 64px;
    }}
    QPushButton#keypadCancel:pressed {{
        background-color: rgba(255, 77, 77, 0.28);
    }}
    """
