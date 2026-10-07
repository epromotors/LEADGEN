"""
logger.py — Centralised IST-aware rotating file logger for LeadGen OS.

Creates a daily log file at:
    <LEADGEN root>/logs/leadgen_YYYY-MM-DD.log

Rotation:  midnight IST (UTC+05:30)
Retention: 3 days  (older files deleted automatically)
Format:    2026-04-19 18:05:44 IST [INFO] engine.audit_engine: message…

Usage:
    from app.logger import setup_logging
    setup_logging()               # call once at startup in main.py

Every module that does `logging.getLogger(__name__)` will then automatically
write to both the rotating file AND stdout (uvicorn's console).
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone, timedelta
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path


# ── IST timezone ──────────────────────────────────────────────────────────────
IST = timezone(timedelta(hours=5, minutes=30))


class _ISTFormatter(logging.Formatter):
    """Formats log timestamps in Indian Standard Time (IST / UTC+5:30)."""

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:  # noqa: N802
        ist_dt = datetime.fromtimestamp(record.created, tz=IST)
        if datefmt:
            return ist_dt.strftime(datefmt)
        return ist_dt.strftime("%Y-%m-%d %H:%M:%S IST")

    def format(self, record: logging.LogRecord) -> str:
        # Prefix each line with IST timestamp
        record.asctime = self.formatTime(record)
        return super().format(record)


class _ISTRotatingHandler(TimedRotatingFileHandler):
    """
    Rotates the log file at midnight IST every day.
    Keeps the 3 most-recent log files (backupCount=3 means today + 2 older days).
    """

    def __init__(self, log_dir: Path) -> None:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "leadgen.log"
        super().__init__(
            filename=str(log_path),
            when="midnight",      # rotate at midnight (local time)
            interval=1,           # every 1 day
            backupCount=3,        # keep today + 2 previous days
            encoding="utf-8",
            delay=False,
        )
        # Override the suffix to embed IST date in the rotated filename
        self.suffix = "%Y-%m-%d"
        self.namer  = self._ist_namer

    @staticmethod
    def _ist_namer(default_name: str) -> str:
        """Rename rotated file to leadgen_YYYY-MM-DD.log using IST date."""
        base_dir  = os.path.dirname(default_name)
        ist_date  = datetime.now(tz=IST).strftime("%Y-%m-%d")
        return os.path.join(base_dir, f"leadgen_{ist_date}.log")

    def computeRollover(self, current_time: float) -> float:
        """Compute rollover at midnight IST instead of local time."""
        ist_now  = datetime.fromtimestamp(current_time, tz=IST)
        midnight = ist_now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        return midnight.timestamp()


# ── Public API ────────────────────────────────────────────────────────────────

def setup_logging(log_dir: Path | None = None) -> None:
    """
    Configure the root Python logger with:
    - A rotating IST-aware file handler  →  logs/leadgen*.log
    - A stream handler                   →  stdout (uvicorn console)

    Call exactly once from main.py before the FastAPI app starts.
    """
    # Resolve log directory: <project root>/logs  (4 levels up from this file)
    if log_dir is None:
        # this file: backend/app/logger.py  →  go up to LEADGEN root
        project_root = Path(__file__).resolve().parents[2]
        log_dir = project_root / "logs"

    fmt = _ISTFormatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    # ── File handler (rotating, IST midnight, 3-day retention) ───────────────
    file_handler = _ISTRotatingHandler(log_dir)
    file_handler.setFormatter(fmt)
    file_handler.setLevel(logging.INFO)

    # ── Console handler (same format, goes to uvicorn stdout) ─────────────────
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(fmt)
    console_handler.setLevel(logging.INFO)

    # ── Root logger ───────────────────────────────────────────────────────────
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Avoid adding duplicate handlers if setup_logging is called more than once
    if not any(isinstance(h, _ISTRotatingHandler) for h in root.handlers):
        root.addHandler(file_handler)

    # Replace uvicorn's plain StreamHandler if present; otherwise add ours
    has_stream = any(
        isinstance(h, logging.StreamHandler) and not isinstance(h, _ISTRotatingHandler)
        for h in root.handlers
    )
    if not has_stream:
        root.addHandler(console_handler)

    # Silence noisy third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)  # set to INFO to log SQL
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)     # reduce HTTP access spam

    logging.getLogger(__name__).info(
        "Logging initialised -> %s [retention: 3 days, rotation: midnight IST]",
        log_dir / "leadgen.log",
    )


def get_log_dir() -> Path:
    """Return the resolved log directory path."""
    project_root = Path(__file__).resolve().parents[2]
    return project_root / "logs"
