"""Generic position sizing (restructure Phase 5.1): shares from (equity, risk per trade %, entry, stop).

The stop price comes from the strategy's proposal; nothing here knows how a stop is derived (the old strategy's ATR/Donchian stop and 52-week
target stay in the legacy ``engine_core.risk_sizing`` until it is removed). Shares are floored. The arithmetic order is the one the fill-time sizing
used in ``engine_core.lifecycle_rules.plan_entry_fill`` (``equity * risk_pct / 100 / risk_per_share``); the legacy ticket-time form
(``equity * (risk_pct / 100) / risk_per_share``) gives a different floor only when the quotient is an exact integer boundary (133 of 143,952 boundary
cases tested, see tests/unit/test_risk_sizing_generic.py); the fill-time form is the one that decided the executed trades, so it is the one kept.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class SizeResult:
    shares: int
    risk_per_share: float
    risk_amount: float           # shares * risk_per_share
    position_value: float        # shares * entry
    reason: str                  # "OK", "NONPOSITIVE_RISK" or "SIZE_ZERO"

    @property
    def ok(self) -> bool:
        return self.reason == "OK"


def size_position(*, equity: float, risk_pct: float, entry: float, stop: float, cash: Optional[float] = None) -> SizeResult:
    """Floor(equity * risk_pct / 100 / (entry - stop)) shares, optionally capped by affordable shares (cash / entry).

    Raises ValueError for non-finite or non-positive equity / risk_pct / entry. A stop at or above the entry gives NONPOSITIVE_RISK; fewer than one share gives SIZE_ZERO.
    """
    for name, v in (("equity", equity), ("risk_pct", risk_pct), ("entry", entry)):
        if not math.isfinite(v) or v <= 0:
            raise ValueError(f"{name} must be a positive finite number: {v!r}")
    if not math.isfinite(stop):
        raise ValueError(f"stop must be finite: {stop!r}")
    rps = entry - stop
    if rps <= 0:
        return SizeResult(0, rps, 0.0, 0.0, "NONPOSITIVE_RISK")
    shares = math.floor(equity * risk_pct / 100.0 / rps)
    if cash is not None:
        shares = min(shares, math.floor(cash / entry))
    if shares < 1:
        return SizeResult(0, rps, 0.0, 0.0, "SIZE_ZERO")
    return SizeResult(shares, rps, shares * rps, shares * entry, "OK")
