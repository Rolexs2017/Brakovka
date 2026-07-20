"""HMI window factory — classic or modern shell."""

from brakovka_hmi.ui.gui import create_main_window, resolve_gui_variant

# ``MainWindow(...)`` builds the shell selected in settings / BRAKOVKA_GUI.
MainWindow = create_main_window

__all__ = ["MainWindow", "create_main_window", "resolve_gui_variant"]
