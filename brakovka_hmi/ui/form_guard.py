from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QWidget


class _FocusDirtyFilter(QObject):
    def __init__(self, owner: "EditableFormMixin") -> None:
        super().__init__()
        self._owner = owner

    def eventFilter(self, obj, event) -> bool:  # noqa: ANN001
        if event.type() == QEvent.Type.FocusIn:
            self._owner._mark_form_dirty()
        return False


class EditableFormMixin:
    """Не перезаписывать поля с устройства, пока оператор редактирует форму.

    Уставки с UI применяются только по кнопке «Сохранить уставки» / «Сброс рулона».
    Пока форма dirty или в фокусе — опрос контроллера не затирает ввод.
    """

    _form_widgets: list[QWidget]
    _form_dirty: bool
    _focus_filter: _FocusDirtyFilter
    _on_dirty_changed: Callable[[bool], None] | None

    def _init_form_guard(
        self,
        widgets: list[QWidget],
        *,
        dirty_changed: Callable[[bool], None] | None = None,
    ) -> None:
        self._form_widgets = widgets
        self._form_dirty = False
        self._on_dirty_changed = dirty_changed
        self._focus_filter = _FocusDirtyFilter(self)
        for widget in widgets:
            signal = None
            if hasattr(widget, "valueChanged"):
                signal = widget.valueChanged
            elif hasattr(widget, "textChanged"):
                signal = widget.textChanged
            if signal is not None:
                signal.connect(self._mark_form_dirty)
            widget.installEventFilter(self._focus_filter)

    def _notify_dirty_changed(self) -> None:
        cb = getattr(self, "_on_dirty_changed", None)
        if callable(cb):
            cb(self._form_dirty)
        # Optional Qt Signal on the host widget
        sig = getattr(self, "dirty_changed", None)
        if sig is not None and hasattr(sig, "emit"):
            sig.emit(self._form_dirty)

    def _mark_form_dirty(self, *_args) -> None:
        # Radio/spin signals can fire while the form is still being built.
        if not hasattr(self, "_form_dirty"):
            return
        was = self._form_dirty
        self._form_dirty = True
        if not was:
            self._notify_dirty_changed()

    def form_is_locked(self) -> bool:
        if self._form_dirty:
            return True
        return any(widget.hasFocus() for widget in self._form_widgets)

    def clear_form_dirty(self) -> None:
        was = self._form_dirty
        self._form_dirty = False
        if was:
            self._notify_dirty_changed()
