"""Shared universe eligibility (ENGINE_CONTRACT section 6, step 6): the symbols a strategy may even look at on a given session.

Rules (same semantics as the legacy screener gates 2-4, computed from the as-of view only):
  - not a fund / ETF;
  - raw 20-session ADTV in crores strictly above ``min_adtv_cr`` (raw prices, never adjusted);
  - listing age in trading days at least ``min_listing_age_trading_days``;
  - not under ASM/GSM surveillance on the as-of date (fail-closed: ``asm_ranges`` is supplied by the caller; a symbol listed there is excluded).
The market-cap gate is parked (KI-001) and is NOT applied. Event proximity (results meetings) is a shared MECHANISM (added with the earnings view, D5); whether it blocks
entries, and for how many days, is a per-strategy parameter, so it is not applied here.
A strategy can only tighten ``min_adtv_cr`` / ``min_listing_age_trading_days`` (``StrategySpec.universe_overrides``).
"""
from __future__ import annotations

from datetime import timedelta
from typing import Mapping, Optional, Sequence

CRORE = 1e7


def eligible_symbols(view, universe_cfg, *, overrides: Optional[Mapping] = None, asm_ranges: Optional[Mapping[str, Sequence]] = None, adtv_period: int = 20) -> list:
    """Sorted list of eligible symbols on ``view.as_of``. ``overrides`` may only raise the two thresholds."""
    ov = dict(overrides or {})
    min_adtv = max(float(universe_cfg.min_adtv_cr), float(ov.get("min_adtv_cr", universe_cfg.min_adtv_cr)))
    min_age = max(int(universe_cfg.min_listing_age_trading_days), int(ov.get("min_listing_age_trading_days", universe_cfg.min_listing_age_trading_days)))
    day = view.as_of
    asm = asm_ranges or {}
    out = []
    for sym in view.symbols_trading():
        if any(s <= day <= e for s, e in asm.get(sym.upper(), ())):
            continue
        info = view.symbol_info(sym)
        if info.is_fund_or_etf or info.n_sessions < min_age:
            continue
        adtv = view.adtv(sym, adtv_period)
        if adtv is None or adtv / CRORE <= min_adtv:
            continue
        out.append(sym)
    return sorted(out)


def results_within(view, symbol: str, days: int) -> Optional[bool]:
    """Shared mechanism: is a results meeting, KNOWN as of ``view.as_of`` (intimation date <= as_of), due within the next ``days`` calendar days (as-of day included)?
    Returns None when the symbol has NO earnings data at all - "no data" is never read as "no event". Whether this blocks entries, and ``days``, are per-strategy."""
    if not view.earnings_coverage(symbol):
        return None
    lo, hi = view.as_of, view.as_of + timedelta(days=int(days))
    return any(lo <= m["bm_date"] <= hi for m in view.results_meetings(symbol))
