"""Shared filesystem locations (the only place that knows where the lake file is)."""
from __future__ import annotations

import os
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def lake_path() -> Path:
    """The lake database: ``STOCKBOT_DB`` if set, else <repo>/finsight.db."""
    return Path(os.environ.get("STOCKBOT_DB") or repo_root() / "finsight.db")


def state_db_path() -> Path:
    """The live state database (separate from the lake): STOCKBOT_STATE_DB if set, else <repo>/state/live_state.db."""
    return Path(os.environ.get("STOCKBOT_STATE_DB") or repo_root() / "state" / "live_state.db")


def tickets_dir() -> Path:
    """Where the EOD runner writes its ticket files: STOCKBOT_TICKETS_DIR if set, else <repo>/state/tickets."""
    return Path(os.environ.get("STOCKBOT_TICKETS_DIR") or repo_root() / "state" / "tickets")
