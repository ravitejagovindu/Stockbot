"""
FInsight Trading Engine — Structured Logging Configuration (Phase 7)

Configures structured JSON logging for all pipeline runs.
All logs are written to logs/finsight.jsonl and also printed to console.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path


LOGS_DIR = Path(__file__).parent / "logs"
LOGS_DIR.mkdir(exist_ok=True)
LOG_FILE = LOGS_DIR / "finsight.jsonl"


class JSONLHandler(logging.Handler):
    """
    Writes structured JSON log entries to a JSONL file.
    One JSON object per line — easily parseable for analytics.
    """

    def __init__(self, filepath: Path):
        super().__init__()
        self.filepath = filepath

    def emit(self, record: logging.LogRecord):
        try:
            entry = {
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "level": record.levelname,
                "logger": record.name,
                "message": self.format(record),
                "module": record.module,
                "funcName": record.funcName,
            }
            if record.exc_info:
                import traceback
                entry["exception"] = traceback.format_exception(*record.exc_info)

            with open(self.filepath, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            self.handleError(record)


def setup_logging(log_level: str = "INFO") -> None:
    """
    Configure structured logging for the FInsight engine.
    Call once at application startup.
    """
    level = getattr(logging, log_level.upper(), logging.INFO)

    # Root logger
    root = logging.getLogger()
    root.setLevel(level)

    # Clear existing handlers
    root.handlers.clear()

    # Console handler (human-readable)
    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    root.addHandler(console)

    # JSONL file handler (structured, for analytics)
    jsonl = JSONLHandler(LOG_FILE)
    jsonl.setLevel(level)
    root.addHandler(jsonl)

    # Silence noisy third-party loggers
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.INFO)

    logging.getLogger(__name__).info(
        f"[LOGGING] Structured logging configured. Level: {log_level}. Log file: {LOG_FILE}"
    )
