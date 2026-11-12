"""trend_breakout_100d: long-only 100-session closing-high breakout inside a long-term uptrend. It only PROPOSES (symbol, stop, rank); sizing, caps, arbitration, fills, costs, corporate
actions and the exit (``trailing_pct_15`` from the shared library, or the stop) belong to shared code.

The rule (every number is read from ``spec.params``, so ``config_hash`` covers it); all prices are ``view.adjusted_bars`` (point-in-time, as-of basis), signal on the session close:
  data       the symbol needs ``min_bars`` (200) bars of its own, a bar on the as-of date, and at least ``min_present`` (198) bars inside the last ``min_bars`` calendar sessions
             (the dates of ``view.sessions``); while the calendar is shorter than that the window is the calendar so far and at most min_bars - min_present may be missing;
  breakout   close today > max(close of the symbol's ``breakout_lookback`` (100) bars BEFORE today)      (strict; today is excluded from the maximum);
  trend      close today > SMA of the ``sma_period`` (200) closes (today included; the mean of the 200 bars the data rule just required);
  order      higher raw ``adtv_sessions`` (20)-session ADTV first (``view.adtv``, the figure shared eligibility uses; none counts as 0), then symbol ascending. Liquidity-neutral on
             purpose: the rank does not look at how far the close is above anything;
  proposals  the first ``top_n`` (25), each with an explicit ordinal rank (top_n for the first, down to 1) so that the engine's own order (rank, then symbol) reproduces this order;
  stop       ``stop_fraction`` (0.85) x the signal-day adjusted close, a price in the as-of basis; reference_price is that close; no target. Exit policy ``trailing_pct_15``.
Standard library only (plus the bars the view returns); imports nothing from another strategy.
"""
from __future__ import annotations

import math
from datetime import date
from typing import Any, Mapping, Optional, Sequence

from stockbot.strategies.base import Proposal
from stockbot.strategies.spec import StrategySpec

SPEC = StrategySpec(
    id="trend_breakout_100d",
    version="1.0.0",
    params={"min_bars": 200, "min_present": 198, "breakout_lookback": 100, "sma_period": 200, "top_n": 25, "stop_fraction": 0.85, "adtv_sessions": 20},
    universe_overrides={},
    exit_policy="trailing_pct_15",
    status="research",
    prereg_ref=None,
    validation_ref=None,
    expected_trade_rate=None,           # set from the Stage 1 counts at the owner's decision
    smallest_edge_of_interest=None,     # the owner supplies it
)


def register(registry) -> StrategySpec:
    """Register the spec in ``registry`` (a StrategyRegistry). Explicit on purpose: importing this package registers nothing, so the default registry stays empty."""
    return registry.register(SPEC)


class TrendBreakoutStrategy:
    def __init__(self, spec: StrategySpec = SPEC):
        self.spec = spec

    def propose(self, view, eligible: Sequence[str], as_of: date, strategy_state: Mapping[str, Any], overlays: Mapping[str, Any]) -> tuple[list, dict]:
        p = self.spec.params
        min_bars, min_present, look = int(p["min_bars"]), int(p["min_present"]), int(p["breakout_lookback"])
        sma_n, top_n, stop_fraction, adtv_n = int(p["sma_period"]), int(p["top_n"]), float(p["stop_fraction"]), int(p["adtv_sessions"])
        need = max(min_bars, sma_n, look + 1)
        cal = view.sessions(lookback=min_bars)
        win_start, wlen = (cal[0] if cal else as_of), len(cal)
        max_missing = min_bars - min_present
        sig: list = []                                                  # (symbol, adjusted close)
        for sym in eligible:
            bars = view.adjusted_bars(sym, lookback=need)
            if len(bars) < need or bars.index[-1] != as_of:
                continue
            in_window = sum(1 for d in bars.index if d >= win_start)
            if wlen - in_window > max_missing:
                continue
            close = bars["close_adj"]
            c_now = float(close.iloc[-1])
            prior_max = float(close.iloc[-(look + 1):-1].max())
            sma = float(close.iloc[-sma_n:].mean())
            if not all(math.isfinite(x) and x > 0 for x in (c_now, prior_max, sma)):
                continue
            if c_now > prior_max and c_now > sma:
                sig.append((sym, c_now))
        adtv_of = {sym: (view.adtv(sym, adtv_n) or 0.0) for sym, _ in sig}
        sig.sort(key=lambda c: (-adtv_of[c[0]], c[0]))
        proposals = [Proposal(self.spec.id, sym, as_of, c_now, stop_fraction * c_now, None, float(top_n - k), {"adtv": adtv_of[sym]})
                     for k, (sym, c_now) in enumerate(sig[:top_n])]
        return proposals, dict(strategy_state)

    def confirm_fill(self, proposal: Proposal, fill_price: float, view) -> Optional[str]:
        return None
