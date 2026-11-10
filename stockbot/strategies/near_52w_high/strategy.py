"""near_52w_high: long-only "near the 52-week high" strategy. It only PROPOSES (symbol, stop, rank); sizing, caps, arbitration, fills, costs, corporate actions and the exit
(fixed_hold_40 from the shared library, or the stop) belong to shared code.

The rule (every number is read from ``spec.params``, so ``config_hash`` covers it):
  nearness   adjusted close today / highest adjusted close of the symbol's last ``window`` (252) bars, from ``view.adjusted_bars`` (point-in-time, as-of basis);
  gap guard  the symbol needs ``window`` bars of its own, a bar on the as-of date, and at least ``min_bars`` (250) bars inside the last ``window`` calendar sessions
             (the dates of ``view.sessions``); while the calendar is shorter than ``window`` sessions the window is the calendar so far and at most window - min_bars may be missing;
  candidate  nearness >= ``threshold`` (0.95);
  order      nearness descending; ties by higher raw ``tie_adtv_sessions``-session ADTV (``view.adtv``, the figure shared eligibility uses; none counts as 0); then symbol;
  proposals  the first ``top_n`` (25), each with an explicit ordinal rank (top_n for the first, down to 1) so that the engine's own order (rank, then symbol) reproduces this order;
  stop       ``stop_fraction`` (0.85) x the signal-day adjusted close, a price in the as-of basis; reference_price is that close; no target.
Standard library only; imports nothing from another strategy.
"""
from __future__ import annotations

import math
from datetime import date
from typing import Any, Mapping, Optional, Sequence

from stockbot.strategies.base import Proposal
from stockbot.strategies.spec import StrategySpec

SPEC = StrategySpec(
    id="near_52w_high",
    version="1.0.0",
    params={"window": 252, "min_bars": 250, "threshold": 0.95, "top_n": 25, "stop_fraction": 0.85, "tie_adtv_sessions": 20},
    universe_overrides={},
    exit_policy="fixed_hold_40",
    status="research",
    prereg_ref=None,
    validation_ref=None,
    expected_trade_rate=6.2,            # trades per month: the STOP 1 occupancy model (cap-bound); the owner set 6.2
    smallest_edge_of_interest=0.15,     # R per trade, net of costs: the owner's proposal, to be confirmed at STOP 3 against the power numbers
)


def register(registry) -> StrategySpec:
    """Register the spec in ``registry`` (a StrategyRegistry). Explicit on purpose: importing this package registers nothing, so the default registry stays empty."""
    return registry.register(SPEC)


class NearHighStrategy:
    def __init__(self, spec: StrategySpec = SPEC):
        self.spec = spec

    def propose(self, view, eligible: Sequence[str], as_of: date, strategy_state: Mapping[str, Any], overlays: Mapping[str, Any]) -> tuple[list, dict]:
        p = self.spec.params
        window, min_bars, threshold = int(p["window"]), int(p["min_bars"]), float(p["threshold"])
        top_n, stop_fraction, tie_n = int(p["top_n"]), float(p["stop_fraction"]), int(p["tie_adtv_sessions"])
        cal = view.sessions(lookback=window)
        win_start, wlen = (cal[0] if cal else as_of), len(cal)
        max_missing = window - min_bars
        cands: list = []                                           # (symbol, nearness, adjusted close)
        for sym in eligible:
            bars = view.adjusted_bars(sym, lookback=window)
            if len(bars) < window or bars.index[-1] != as_of:
                continue
            in_window = sum(1 for d in bars.index if d >= win_start)
            if wlen - in_window > max_missing:
                continue
            close = bars["close_adj"]
            c_now, c_max = float(close.iloc[-1]), float(close.max())
            if not (math.isfinite(c_now) and math.isfinite(c_max) and c_now > 0 and c_max > 0):
                continue
            nearness = c_now / c_max
            if nearness >= threshold:
                cands.append((sym, nearness, c_now))
        cands.sort(key=lambda c: (-c[1], c[0]))
        ordered: list = []                                         # tie groups that start inside the cut are ordered by ADTV; later groups are never used
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
        proposals = [Proposal(self.spec.id, sym, as_of, c_now, stop_fraction * c_now, None, float(top_n - k),
                              {"nearness": nearness, "adtv": adtv_of.get(sym)})
                     for k, (sym, nearness, c_now) in enumerate(ordered[:top_n])]
        return proposals, dict(strategy_state)

    def confirm_fill(self, proposal: Proposal, fill_price: float, view) -> Optional[str]:
        return None
