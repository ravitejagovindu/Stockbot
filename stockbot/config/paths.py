"""Shared filesystem locations (the only place that knows where the lake file is)."""
from __future__ import annotations

import os
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def lake_path() -> Path:
    """The lake database: ``STOCKBOT_DB`` if set, else <repo>/finsight.db."""
    return Path(os.environ.get("STOCKBOT_DB") or repo_root() / "finsight.db")
