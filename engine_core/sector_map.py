"""engine_core/sector_map.py — symbol-to-sector lookup from a committed CSV.

The sector map CSV must be present at ``data/reference/sector_map.csv``
with headers: ``symbol,sector``.

Symbols not found in the CSV are mapped to ``"UNKNOWN"`` which is treated as
its own capped bucket in the heat-cap gate.
"""
import csv
from functools import lru_cache
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "data" / "reference" / "sector_map.csv"


@lru_cache(maxsize=1)
def _load() -> dict:
    """Load and cache the sector map CSV.  Raises FileNotFoundError if missing."""
    if not _PATH.exists():
        raise FileNotFoundError(f"{_PATH} missing — the sector cap cannot run without it")
    with open(_PATH, newline="", encoding="utf-8") as f:
        return {r["symbol"].strip().upper(): r["sector"].strip() for r in csv.DictReader(f)}


def sector_for(symbol: str) -> str:
    """Return the sector for ``symbol``, or ``"UNKNOWN"`` if not in the map."""
    return _load().get(symbol.upper(), "UNKNOWN")  # UNKNOWN is its own capped bucket
