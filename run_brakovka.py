#!/usr/bin/env python3
"""Brakovka — controller + in-process Qt HMI (one process).

Headless (OPC-UA only for SCADA):
  BRAKOVKA_HMI=0 python run_brakovka.py
  # or: python -m brakovka_pi
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import threading

from brakovka_pi.controller import run_controller
from brakovka_pi.logutil import setup_logging


def _run_controller_thread(
    bridge,
    stop_event: threading.Event,
    ready_event: threading.Event,
    error_box: list,
    gpio,
) -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    async_stop = asyncio.Event()

    def _watch_stop() -> None:
        while not stop_event.wait(0.2):
            pass
        loop.call_soon_threadsafe(async_stop.set)

    watcher = threading.Thread(target=_watch_stop, name="hmi-stop-watch", daemon=True)
    watcher.start()

    async def _runner() -> None:
        await run_controller(
            hmi_bridge=bridge,
            stop_event=async_stop,
            hmi_ready=ready_event,
            gpio=gpio,
        )

    try:
        loop.run_until_complete(_runner())
    except Exception as exc:
        logging.getLogger(__name__).exception("Controller failed: %s", exc)
        error_box.append(exc)
        ready_event.set()
    finally:
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception:
            pass
        loop.close()


def main() -> int:
    setup_logging()
    log = logging.getLogger("run_brakovka")

    # Match deploy/check_gpio.sh / Trixie (no pigpiod).
    os.environ.setdefault("GPIOZERO_PIN_FACTORY", "lgpio")

    use_hmi = os.getenv("BRAKOVKA_HMI", "1") != "0"
    if not use_hmi:
        log.info("HMI disabled (BRAKOVKA_HMI=0), running headless controller")
        asyncio.run(run_controller())
        return 0

    # Init GPIO on the main thread before the controller thread / Qt.
    # lgpio + gpiozero are more reliable here than inside the asyncio worker.
    from brakovka_pi.config import load_runtime_config
    from brakovka_pi.gpio_io import GpioInputs

    _emu, gpio_cfg, *_rest = load_runtime_config()
    gpio_inputs = GpioInputs(gpio_cfg)
    log.info(
        "GPIO pre-init: available=%s factory=%s error=%s",
        gpio_inputs.available,
        gpio_inputs.pin_factory or "-",
        gpio_inputs.error or "(none)",
    )

    # Before QApplication: disable Raspberry / desktop on-screen keyboard plugins.
    from brakovka_hmi.ui.osk import disable_system_virtual_keyboard, prepare_env_for_app_keyboard

    prepare_env_for_app_keyboard()

    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication

    from brakovka_hmi.bridge import LocalBridge
    from brakovka_hmi.ui.gui import create_main_window, resolve_gui_variant
    from brakovka_pi.settings import load_settings

    ui_cfg = load_settings().ui
    ui_title = str(ui_cfg.get("window_title", "Brakovka HMI"))
    ui_fullscreen = bool(ui_cfg.get("fullscreen", True))
    ui_width = int(ui_cfg.get("width", 1280))
    ui_height = int(ui_cfg.get("height", 800))

    bridge = LocalBridge()
    # So Status screen has GPIO state even before controller loop starts.
    bridge.publish_gpio_levels(gpio_inputs.read_levels())

    stop_event = threading.Event()
    ready_event = threading.Event()
    error_box: list = []

    ctrl_thread = threading.Thread(
        target=_run_controller_thread,
        args=(bridge, stop_event, ready_event, error_box, gpio_inputs),
        name="brakovka-controller",
        daemon=True,
    )
    ctrl_thread.start()

    # Wait briefly for controller attach / early failure
    ready_event.wait(timeout=15.0)
    if error_box:
        log.error("Controller failed to start: %s", error_box[0])
        return 1

    app = QApplication(sys.argv)
    app.setApplicationName(ui_title)
    app.setStyle("Fusion")
    disable_system_virtual_keyboard(app)

    from brakovka_hmi.sounds import init_sounds

    init_sounds(enabled=bool(ui_cfg.get("sounds_enabled", True)))

    base_font = QFont("Segoe UI", 10)
    if base_font.pointSize() <= 0:
        base_font.setPointSize(10)
    app.setFont(base_font)

    log.info("HMI variant: %s", resolve_gui_variant(ui_cfg))

    window = create_main_window(
        bridge,
        title=ui_title,
        width=ui_width,
        height=ui_height,
        fullscreen=ui_fullscreen,
        ui_cfg=ui_cfg,
    )
    window.show_for_display()

    code = app.exec()

    stop_event.set()
    bridge.stop()
    ctrl_thread.join(timeout=8.0)
    if ctrl_thread.is_alive():
        log.warning("Controller thread did not stop in time")
    return int(code)


if __name__ == "__main__":
    raise SystemExit(main())
