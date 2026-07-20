from __future__ import annotations

import logging
import os

from brakovka_hmi.bridge import LocalBridge

log = logging.getLogger(__name__)

GUI_VARIANTS = frozenset({"classic", "modern"})


def resolve_gui_variant(ui_cfg: dict | None = None) -> str:
    """
    Pick HMI shell: ``modern`` (default on GUI branch) or ``classic``.

    Override via settings ``ui.gui_variant`` or env ``BRAKOVKA_GUI=classic``.
    """
    env = os.getenv("BRAKOVKA_GUI", "").strip().lower()
    if env in GUI_VARIANTS:
        return env
    cfg = ui_cfg or {}
    variant = str(cfg.get("gui_variant", "modern")).strip().lower()
    if variant not in GUI_VARIANTS:
        log.warning("Unknown gui_variant=%r, using modern", variant)
        return "modern"
    return variant


def create_main_window(
    bridge: LocalBridge,
    *,
    title: str = "Brakovka HMI",
    width: int = 1280,
    height: int = 800,
    fullscreen: bool = True,
    variant: str | None = None,
    ui_cfg: dict | None = None,
):
    v = variant or resolve_gui_variant(ui_cfg)
    log.info("HMI gui_variant=%s", v)
    if v == "classic":
        from brakovka_hmi.ui.classic.main_window import MainWindow

        return MainWindow(
            bridge,
            title=title,
            width=width,
            height=height,
            fullscreen=fullscreen,
        )
    from brakovka_hmi.ui.modern.main_window import MainWindow

    return MainWindow(
        bridge,
        title=title,
        width=width,
        height=height,
        fullscreen=fullscreen,
    )
