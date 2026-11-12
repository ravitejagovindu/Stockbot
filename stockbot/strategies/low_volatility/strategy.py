"""low_volatility: long-only, monthly "lowest 60-day volatility" strategy. It only PROPOSES (symbol, stop, rank); sizing, caps, arbitration, fills, costs, corporate actions
and the exit (fixed_hold_21 from the shared library, or the stop) belong to shared code.

The rule (every number is read from ``spec.params``, so ``config_hash`` covers it):
  signal day  the first trading session of each calendar month: the as-of date's month differs from the month of the previous session of the calendar (``view.sessions``).
              On every other session the strategy proposes nothing;
  history     the symbol needs ``min_bars`` (252) bars of its own (``view.adjusted_bars``) and a bar on the as-of date;
  vol60       the sample standard deviation (ddof = 1) of the last ``vol_window`` (60) daily log returns of the adjusted close (point-in-time, as-of basis), i.e. from the last
              61 adjusted closes. ddof does not change the ranking (every name uses the same 60 returns);
  order       lowest vol60 first; ties by higher raw ``tie_adtv_sessions``-session ADTV (``view.adtv``, the figure shared eligibility uses; none counts as 0); then symbol;
  proposals   the first ``top_n`` (25), each with an explicit ordinal rank (top_n for the first, down to 1) so that the engine's own order (rank, then symbol) reproduces this order;
  stop        ``stop_fraction`` (0.90) x the signal-day adjusted close, a price in the as-of basis; reference_price is that close; no target.
No other filter is applied (no gap guard on the 61-close window, no minimum volatility): names whose window has missing sessions or a zero volatility are COUNTED by ``score``
but ranked as the rule says. Standard library plus numpy; imports nothing from another strategy.
"""
from __future__ import annotations

import math
from datetime import date
from typing import Any, Mapping, Optional, Sequence

import numpy as np

from stockbot.strategies.base import Proposal
from stockbot.strategies.spec import StrategySpec

SPEC = StrategySpec(
    id="low_volatility",
    version="1.0.0",
    params={"rebalance": "first_session_of_month", "min_bars": 252, "vol_window": 60, "top_n": 25, "stop_fraction": 0.90, "tie_adtv_sessions": 20},
    universe_overrides={},
    exit_policy="fixed_hold_21",
    status="research",
    prereg_ref=None,
    validation_ref=None,
)


def register(registry) -> StrategySpec:
    """Register the spec in ``registry`` (a StrategyRegistry). Explicit on purpose: importing this package registers nothing, so the default registry stays empty."""
    return registry.register(SPEC)


def is_signal_session(view, as_of: date) -> bool:
    """True when ``as_of`` is the first session of its calendar month: the previous session of the calendar (Nifty dates up to as_of) is in a different month."""
    cal = view.sessions(lookback=2)
    return len(cal) == 2 and cal[-1] == as_of and (cal[0].year, cal[0].month) != (as_of.year, as_of.month)


class LowVolatilityStrategy:
    def __init__(self, spec: StrategySpec = SPEC):
        self.spec = spec

    def score(self, view, eligible: Sequence[str], as_of: date) -> dict:
        """Counts and the full ranking for ONE as-of date (no signal-day check). Reads only through ``view``.
        ``ranked`` is every valid name as (symbol, vol60, close_adj, adtv or None), in rank order (the ADTV tie-break applied inside the top_n cut only)."""
        p = self.spec.params
        min_bars, w, top_n, tie_n = int(p["min_bars"]), int(p["vol_window"]), int(p["top_n"]), int(p["tie_adtv_sessions"])
        cal = view.sessions(lookback=w + 1)
        win_start = cal[0] if cal else as_of
        out = dict(date=as_of, n_eligible=len(eligible), short=[], stale=[], bad_price=[], valid=[], window_gaps=[], zero_vol=[], ranked=[])
        cands: list = []                                              # (symbol, vol60, close_adj)
        for sym in eligible:
            bars = view.adjusted_bars(sym, lookback=max(min_bars, w + 1))
            if len(bars) < min_bars:
                out["short"].append(sym)
                continue
            if bars.index[-1] != as_of:
                out["stale"].append(sym)
                continue
            close = bars["close_adj"].to_numpy(dtype=float)[-(w + 1):]
            if not (np.all(np.isfinite(close)) and np.all(close > 0)):
                out["bad_price"].append(sym)
                continue
            vol = float(np.std(np.diff(np.log(close)), ddof=1))
            if sum(1 for d in bars.index[-(w + 1):] if d >= win_start) < len(cal):     # a calendar session of the window with no bar (the calendar may be shorter than w + 1 sessions)
                out["window_gaps"].append(sym)                       # counted, still ranked: the rule has no gap guard
            if vol == 0.0:
                out["zero_vol"].append(sym)
            out["valid"].append(sym)
            cands.append((sym, vol, float(close[-1])))
        cands.sort(key=lambda c: (c[1], c[0]))
        ordered: list = []                                            # tie groups that start inside the cut are ordered by ADTV; later groups are never used
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
        out["ranked"] = [(s, v, c, adtv_of.get(s)) for s, v, c in ordered]
        return out

    def propose(self, view, eligible: Sequence[str], as_of: date, strategy_state: Mapping[str, Any], overlays: Mapping[str, Any]) -> tuple[list, dict]:
        if not is_signal_session(view, as_of):
            return [], dict(strategy_state)
        p = self.spec.params
        top_n, stop_fraction = int(p["top_n"]), float(p["stop_fraction"])
        ranked = self.score(view, eligible, as_of)["ranked"]
        proposals = [Proposal(self.spec.id, sym, as_of, close, stop_fraction * close, None, float(top_n - k), {"vol60": vol, "adtv": adtv})
                     for k, (sym, vol, close, adtv) in enumerate(ranked[:top_n]) if math.isfinite(vol)]
        return proposals, dict(strategy_state)

    def confirm_fill(self, proposal: Proposal, fill_price: float, view) -> Optional[str]:
        return None
