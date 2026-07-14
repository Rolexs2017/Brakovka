from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path


_LOG_FMT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_DATE_FMT = "%Y-%m-%d %H:%M:%S"
_configured = False


class _LevelFilter(logging.Filter):
    """Pass only records in [min_level, max_level]."""

    def __init__(self, min_level: int, max_level: int) -> None:
        super().__init__()
        self.min_level = min_level
        self.max_level = max_level

    def filter(self, record: logging.LogRecord) -> bool:
        return self.min_level <= record.levelno <= self.max_level


def default_log_dir() -> Path:
    env = os.getenv("BRAKOVKA_LOG_DIR")
    if env:
        return Path(env)
    # Project root: .../rpi_python/logs
    return Path(__file__).resolve().parents[1] / "logs"


def setup_logging(log_dir: Path | None = None) -> Path:
    """
    File-only logging (no console/serial):
      - brakovka_info.log  — INFO and WARNING (machine work)
      - brakovka_error.log — ERROR and CRITICAL
    """
    global _configured
    root = logging.getLogger()
    if _configured and root.handlers:
        return Path(getattr(setup_logging, "_log_dir", default_log_dir()))

    directory = log_dir or default_log_dir()
    directory.mkdir(parents=True, exist_ok=True)
    setup_logging._log_dir = directory  # type: ignore[attr-defined]

    fmt = logging.Formatter(_LOG_FMT, datefmt=_DATE_FMT)
    root.setLevel(logging.INFO)

    # Avoid duplicate handlers on re-entry
    root.handlers.clear()

    info_path = directory / "brakovka_info.log"
    info_handler = RotatingFileHandler(
        info_path,
        maxBytes=5_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    info_handler.setLevel(logging.INFO)
    info_handler.addFilter(_LevelFilter(logging.INFO, logging.WARNING))
    info_handler.setFormatter(fmt)
    root.addHandler(info_handler)

    error_path = directory / "brakovka_error.log"
    error_handler = RotatingFileHandler(
        error_path,
        maxBytes=5_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.addFilter(_LevelFilter(logging.ERROR, logging.CRITICAL))
    error_handler.setFormatter(fmt)
    root.addHandler(error_handler)

    # asyncua: harmless standard address-space noise
    logging.getLogger("asyncua.server.address_space").setLevel(logging.WARNING)
    logging.getLogger("asyncua.common.xmlimporter").setLevel(logging.WARNING)
    logging.getLogger("asyncua").setLevel(logging.WARNING)

    _configured = True
    logging.getLogger(__name__).info(
        "Logging to %s (info=%s, error=%s)",
        directory,
        info_path.name,
        error_path.name,
    )
    return directory
