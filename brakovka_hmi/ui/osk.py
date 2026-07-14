"""Disable Raspberry Pi / desktop on-screen keyboard for this Qt app.

The HMI uses its own NumericKeypadDialog. System OSK (matchbox, onboard,
squeekboard, Qt virtualkeyboard, Wayland text-input) must not appear on
QSpinBox / QLineEdit focus.
"""

from __future__ import annotations

import os

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QApplication, QWidget


def prepare_env_for_app_keyboard() -> None:
    """Call before QApplication() so Qt does not load a system IM plugin."""
    # Empty / "none" disables Qt input-method plugins (incl. qtvirtualkeyboard).
    os.environ.setdefault("QT_IM_MODULE", "none")
    # Avoid ibus/fcitx grabbing focus on some Pi images.
    os.environ.setdefault("GTK_IM_MODULE", "none")
    os.environ.setdefault("XMODIFIERS", "@im=none")


class _BlockSoftwareInputPanelFilter(QObject):
    """Swallow RequestSoftwareInputPanel so the compositor OSK stays hidden."""

    def eventFilter(self, obj, event) -> bool:  # noqa: ANN001
        et = event.type()
        if et == QEvent.Type.RequestSoftwareInputPanel:
            return True
        if et == QEvent.Type.InputMethod:
            return True
        return False


_osk_filter: _BlockSoftwareInputPanelFilter | None = None


def disable_system_virtual_keyboard(app: QApplication) -> None:
    """Install app-wide filter and hide Qt input method panel."""
    global _osk_filter
    try:
        im = app.inputMethod()
        im.setVisible(False)
        im.hide()
    except Exception:
        pass

    if _osk_filter is None:
        _osk_filter = _BlockSoftwareInputPanelFilter(app)
        app.installEventFilter(_osk_filter)


def disable_widget_input_method(widget: QWidget) -> None:
    """Mark a widget so it never requests the system OSK."""
    widget.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, False)
    widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    # QAbstractSpinBox / QLineEdit
    line_edit = getattr(widget, "lineEdit", None)
    if callable(line_edit):
        edit = line_edit()
        if edit is not None:
            edit.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, False)
            edit.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            edit.setReadOnly(True)
            try:
                edit.setInputMethodHints(Qt.InputMethodHint.ImhNone)
            except Exception:
                pass
