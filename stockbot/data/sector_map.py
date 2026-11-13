"""stockbot/data/sector_map.py — symbol-to-sector lookup from a committed CSV; the ONE sector rule for backtest, paper and live.

The sector map CSV must be present at ``data/reference/sector_map.csv`` with headers: ``symbol,sector``.

A symbol that is not in the CSV (or has a blank sector) is its OWN sector, keyed ``"UNMAPPED:<SYMBOL>"``. The 15% sector cap therefore applies per mapped sector and never pools
unmapped names (before, they shared one ``UNKNOWN`` bucket that held every unmapped name to a single position). The total-risk cap and the position cap are unaffected.
``SectorLookup`` is the mapping-like object every path hands to ``EventData(sectors=...)``.
"""
import csv
from functools import lru_cache
from pathlib import Path

_PATH = Path(__file__).resolve().parents[2] / "data" / "reference" / "sector_map.csv"
UNMAPPED_PREFIX = "UNMAPPED:"
_NOT_A_SECTOR = ("", "UNKNOWN")        # a blank or legacy-placeholder CSV sector means "no sector known"


@lru_cache(maxsize=1)
def _load() -> dict:
    """Load and cache the sector map CSV.  Raises FileNotFoundError if missing."""
    if not _PATH.exists():
        raise FileNotFoundError(f"{_PATH} missing — the sector cap cannot run without it")
    with open(_PATH, newline="", encoding="utf-8") as f:
        return {r["symbol"].strip().upper(): r["sector"].strip() for r in csv.DictReader(f)}


def _mapped_sector(symbol: str):
    sector = _load().get(symbol.strip().upper())
    return None if sector is None or sector.upper() in _NOT_A_SECTOR else sector


def is_mapped(symbol: str) -> bool:
    """True when the CSV gives ``symbol`` a real sector."""
    return _mapped_sector(symbol) is not None


def sector_for(symbol: str) -> str:
    """The sector of ``symbol``; an unmapped symbol is its own sector, ``"UNMAPPED:<SYMBOL>"`` (upper case)."""
    sector = _mapped_sector(symbol)
    return sector if sector is not None else f"{UNMAPPED_PREFIX}{symbol.strip().upper()}"


class SectorLookup:
    """Mapping-like sector source for ``EventData(sectors=...)``, used by the backtest, paper and live wiring alike. Always answers (never None, never the caller's default)."""

    def get(self, symbol: str, default=None) -> str:
        return sector_for(symbol)
