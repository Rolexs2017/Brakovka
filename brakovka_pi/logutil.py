from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path


_LOG_FMT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_DATE_FMT = "%Y-%m-%d %H:%M:%S"
_configured = False

_LINE_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+"
    r"(?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL)\s+"
    r"(?P<name>[^:]+):\s*"
    r"(?P<msg>.*)$"
)

INFO_LOG_NAME = "brakovka_info.log"
ERROR_LOG_NAME = "brakovka_error.log"


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


def current_log_dir() -> Path:
    return Path(getattr(setup_logging, "_log_dir", default_log_dir()))


def clear_log_files(log_dir: Path | None = None) -> tuple[int, list[str]]:
    """
    Clear journal log files used by HMI.

    Truncates active ``brakovka_info.log`` / ``brakovka_error.log`` and deletes
    rotated backups (``.1`` …). Returns (files_touched, error messages).
    """
    directory = log_dir or current_log_dir()
    if not directory.is_dir():
        return 0, [f"Каталог логов не найден: {directory}"]

    touched = 0
    errors: list[str] = []
    active = {INFO_LOG_NAME, ERROR_LOG_NAME}

    for path in sorted(directory.glob("brakovka_*.log*")):
        if not path.is_file():
            continue
        try:
            if path.name in active:
                path.write_text("", encoding="utf-8")
            else:
                path.unlink(missing_ok=True)
            touched += 1
        except OSError as exc:
            errors.append(f"{path.name}: {exc}")

    if touched and not errors:
        logging.getLogger(__name__).info("Journal logs cleared (%s files)", touched)
    return touched, errors


@dataclass(frozen=True)
class JournalEntry:
    timestamp: str
    level: str
    logger: str
    message: str
    raw: str

    @property
    def is_alarm(self) -> bool:
        return self.level in ("ERROR", "CRITICAL", "WARNING")

    @property
    def sort_key(self) -> str:
        return self.timestamp


def _tail_text_lines(path: Path, max_lines: int) -> list[str]:
    if max_lines <= 0 or not path.is_file():
        return []
    try:
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            block = 8192
            data = b""
            while size > 0 and data.count(b"\n") <= max_lines:
                step = min(block, size)
                size -= step
                fh.seek(size)
                data = fh.read(step) + data
            text = data.decode("utf-8", errors="replace")
    except OSError:
        return []
    lines = text.splitlines()
    return lines[-max_lines:]


def _parse_line(line: str) -> JournalEntry | None:
    text = line.strip()
    if not text:
        return None
    m = _LINE_RE.match(text)
    if not m:
        return JournalEntry(
            timestamp="",
            level="INFO",
            logger="",
            message=text,
            raw=text,
        )
    return JournalEntry(
        timestamp=m.group("ts"),
        level=m.group("level"),
        logger=m.group("name").strip(),
        message=m.group("msg").strip(),
        raw=text,
    )


def read_journal_entries(
    *,
    log_dir: Path | None = None,
    max_per_file: int = 400,
    alarms_only: bool = False,
    info_only: bool = False,
) -> list[JournalEntry]:
    """Merge recent lines from info + error logs (newest first)."""
    directory = log_dir or current_log_dir()
    raw_lines: list[str] = []
    raw_lines.extend(_tail_text_lines(directory / INFO_LOG_NAME, max_per_file))
    raw_lines.extend(_tail_text_lines(directory / ERROR_LOG_NAME, max_per_file))

    entries: list[JournalEntry] = []
    for line in raw_lines:
        entry = _parse_line(line)
        if entry is None:
            continue
        if alarms_only and not entry.is_alarm:
            continue
        if info_only and entry.is_alarm:
            continue
        entries.append(entry)

    entries.sort(key=lambda e: e.sort_key, reverse=True)
    seen: set[str] = set()
    unique: list[JournalEntry] = []
    for e in entries:
        if e.raw in seen:
            continue
        seen.add(e.raw)
        unique.append(e)
    return unique
