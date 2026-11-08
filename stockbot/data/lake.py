"""Read-only access to the market-data lake (SQLite).

Backtest, live and validation open the lake ONLY through ``open_lake``: a SQLite connection in ``mode=ro`` plus ``PRAGMA query_only``, so a write
raises ``sqlite3.OperationalError`` ("attempt to write a readonly database").  Ingestion tooling (which does write) does not use this module.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from stockbot.config.paths import lake_path


def open_lake(path: Optional[str | Path] = None) -> sqlite3.Connection:
    """Open the lake read-only. ``path`` defaults to ``STOCKBOT_DB`` or <repo>/finsight.db. Raises FileNotFoundError if the file is missing."""
    p = Path(path) if path is not None else lake_path()
    if not p.exists():
        raise FileNotFoundError(f"lake database not found: {p}")
    con = sqlite3.connect(f"file:{p.resolve().as_posix()}?mode=ro", uri=True, timeout=60)
    con.execute("PRAGMA query_only=ON")
    return con
