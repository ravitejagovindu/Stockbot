"""short_term_reversal: long-only 5-session reversal strategy. It only PROPOSES (symbol, stop, rank); sizing, caps, arbitration, fills, costs, corporate actions and the exit
(fixed_hold_5 from the shared library, or the stop) belong to shared code.

The rule (every number is read from ``spec.params``, so ``config_hash`` covers it):
  eligible   the shared eligibility list handed to ``propose`` (no overrides);
  data       the symbol needs ``min_bars`` (10) own bars in ``view.adjusted_bars``, a bar on the as-of date, and a bar on the session ``lookback_sessions`` (5) calendar sessions
             before the as-of date (the calendar is ``view.sessions``, so a missing bar is never silently skipped over);
  ret5       adjusted close[t] / adjusted close[t - 5 sessions] - 1 in the as-of price basis, rounded to 12 decimals so that an exact -7% or -30% is not lost to float noise;
  signal     ``ret_floor`` (-0.30) <= ret5 <= ``ret_cap`` (-0.07), both ends inclusive; the floor guards against unadjusted corporate-action artifacts;
  order      ret5 ascending (the deepest fall first); ties by higher raw ``tie_adtv_sessions``-session ADTV (``view.adtv``, none counts as 0); then symbol;
  proposals  the first ``top_n`` (25), each with an explicit ordinal rank (top_n for the first, down to 1) so that the engine's own order (rank, then symbol) reproduces this order;
  stop       ``stop_fraction`` (0.92) x the signal-day adjusted close, a price in the as-of basis; reference_price is that close; no target.
Standard library only; imports nothing from another strategy. ``scan`` and ``order_candidates`` are public so that the counts study reuses this very rule (one implementation).
"""
from __future__ import annotations

import math
from collections import Counter
from datetime import date
from typing import Any, Mapping, Optional, Sequence

from stockbot.strategies.base import Proposal
from stockbot.strategies.spec import StrategySpec

SPEC = StrategySpec(
    id="short_term_reversal",
    version="1.0.0",
    params={"lookback_sessions": 5, "min_bars": 10, "ret_floor": -0.30, "ret_cap": -0.07, "top_n": 25, "stop_fraction": 0.92, "tie_adtv_sessions": 20},
    universe_overrides={},
    exit_policy="fixed_hold_5",
    status="research",
    prereg_ref="docs/strategies/short_term_reversal/PREREGISTRATION.md",     # owner decision (stage 2); the config hash covers it
    validation_ref=None,
    expected_trade_rate=23.0,           # trades per month: the Stage 1 occupancy model (8 cash-bound slots), 2016-2026 = 23.02; confirmed by the owner. Under the per-symbol UNMAPPED sector rule the same model gives 25.63 (reported, NOT applied)
    smallest_edge_of_interest=0.15,     # R per trade, net of costs (owner's number)
)


def register(registry) -> StrategySpec:
    """Register the spec in ``registry`` (a StrategyRegistry). Explicit on purpose: importing this package registers nothing, so the default registry stays empty."""
    return registry.register(SPEC)


def ret5_of(c_now: float, c_then: float) -> float:
    """close[t] / close[t-5] - 1, rounded to 12 decimals (so 93/100 is exactly -0.07 and 70/100 exactly -0.30, not -0.06999999999999995)."""
    return round(c_now / c_then - 1.0, 12)


def scan(view, eligible: Sequence[str], as_of: date, params: Mapping[str, Any]) -> dict:
    """Every eligible symbol with a usable 5-session return. Reads only through ``view`` (bounded by its as-of date).
    Returns ``cands`` [(symbol, ret5, adjusted close)] for ret5 inside the band (unordered), ``below_floor`` [symbol] (valid, ret5 < floor: the artifact guard) and ``counts``
    (eligible, short, stale, no_anchor, bad_price, adjust_error, valid, below_floor, above_cap, signals)."""
    lb, min_bars = int(params["lookback_sessions"]), int(params["min_bars"])
    lo, hi = float(params["ret_floor"]), float(params["ret_cap"])
    counts: Counter = Counter(eligible=len(eligible))
    cands: list = []
    below: list = []
    cal = view.sessions(lookback=lb + 1)
    if len(cal) < lb + 1 or cal[-1] != as_of:
        counts["no_calendar"] = len(eligible)
        return dict(cands=cands, below_floor=below, counts=counts)
    anchor = cal[0]                                                    # the session lb calendar sessions before the as-of date
    for sym in eligible:
        try:
            bars = view.adjusted_bars(sym, lookback=max(min_bars, lb + 1))
        except ValueError:
            counts["adjust_error"] += 1
            continue
        if len(bars) < min_bars:
            counts["short"] += 1
            continue
        if bars.index[-1] != as_of:
            counts["stale"] += 1
            continue
        if anchor not in bars.index:
            counts["no_anchor"] += 1
            continue
        c_now, c_then = float(bars["close_adj"].iloc[-1]), float(bars.loc[anchor, "close_adj"])
        if not (math.isfinite(c_now) and math.isfinite(c_then) and c_now > 0 and c_then > 0):
            counts["bad_price"] += 1
            continue
        counts["valid"] += 1
        r = ret5_of(c_now, c_then)
        if r < lo:
            counts["below_floor"] += 1
            below.append(sym)
        elif r > hi:
            counts["above_cap"] += 1
        else:
            counts["signals"] += 1
            cands.append((sym, r, c_now))
    return dict(cands=cands, below_floor=below, counts=counts)


def order_candidates(view, cands: Sequence, top_n: int, tie_n: int) -> tuple[list, dict]:
    """Candidates in rank order: ret5 ascending; ties by higher raw ``tie_n``-session ADTV (none counts as 0), then symbol. ADTV is fetched only for tie groups that start inside the
    top ``top_n`` (the order beyond the cut is never used). Returns (ordered [(symbol, ret5, close)], {symbol: adtv} for the names whose tie was broken)."""
    cands = sorted(cands, key=lambda c: (c[1], c[0]))
    ordered: list = []
    adtv_of: dict = {}
    i = 0
    while i < len(cands):
        j = i
        while j + 1 < len(cands) and cands[j + 1][1] == cands[i][1]:
            j += 1
        grp = cands[i:j + 1]
        if len(grp) > 1 and i < top_n:
            for c in grp:
                adtv_of[c[0]] = view.adtv(c[0], tie_n) or 0.0
            grp = sorted(grp, key=lambda c: (-adtv_of[c[0]], c[0]))
        ordered.extend(grp)
        i = j + 1
    return ordered, adtv_of


class ShortTermReversalStrategy:
    def __init__(self, spec: StrategySpec = SPEC):
        self.spec = spec

    def propose(self, view, eligible: Sequence[str], as_of: date, strategy_state: Mapping[str, Any], overlays: Mapping[str, Any]) -> tuple[list, dict]:
        p = self.spec.params
        top_n, stop_fraction, tie_n = int(p["top_n"]), float(p["stop_fraction"]), int(p["tie_adtv_sessions"])
        ordered, adtv_of = order_candidates(view, scan(view, eligible, as_of, p)["cands"], top_n, tie_n)
        proposals = [Proposal(self.spec.id, sym, as_of, c_now, stop_fraction * c_now, None, float(top_n - k), {"ret5": r, "adtv": adtv_of.get(sym)})
                     for k, (sym, r, c_now) in enumerate(ordered[:top_n])]
        return proposals, dict(strategy_state)

    def confirm_fill(self, proposal: Proposal, fill_price: float, view) -> Optional[str]:
        return None
