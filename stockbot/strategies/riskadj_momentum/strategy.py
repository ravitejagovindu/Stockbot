"""riskadj_momentum: long-only "risk-adjusted 12-1 momentum", rebalanced monthly. It only PROPOSES (symbol, stop, rank); sizing, caps, arbitration, fills, costs, corporate actions and
the exit (its own ``trailing_atr3_floor8``, ``exits.py``) belong to the engine. Signals are taken on the session close, entry is the engine's next-open fill.

The rule (every number is read from ``spec.params`` so ``config_hash`` covers it):
  signal sessions  only the first trading session of each calendar month: its (year, month) differs from the previous session's of the calendar (``view.sessions``). With no previous
                   session (the first session of the calendar) there is no signal. On every other session the strategy proposes nothing;
  history          READING (ambiguity in the brief, see docs/strategies/riskadj_momentum/BRIEF.md): the calendar window is the last ``ret_long`` (252) sessions ending at the signal
                   session (``view.sessions(lookback=252)``); the symbol needs a bar on the signal session, at least ``min_closes`` (240) adjusted closes inside that window, and
                   ``ret_long`` + 1 (253) adjusted bars of its OWN (``view.adjusted_bars(sym, lookback=253)``), because the offsets t-21 and t-252 are counted on the symbol's own bars:
                   t is its last bar, t-21 its bar 21 positions earlier, t-252 its bar 252 positions earlier. Without gaps these are the same sessions as the calendar's; with gaps
                   they reach further back in calendar time. A symbol with fewer than 253 own bars has no signal;
  momentum         ret = close[t-21] / close[t-252] - 1 on adjusted closes; ret > 0 strictly;
  volatility       vol = sample standard deviation (ddof = 1) of the daily log returns of the symbol's own consecutive adjusted closes from t-252 through t-21 (231 returns when
                   there are no gaps); vol > 0 strictly (a flat series has none);
  score            ret / vol. Order: higher score first; exact ties by higher raw ``tie_adtv_sessions``-session ADTV (``view.adtv``, none counts as 0); then symbol. No rounding;
  proposals        the first ``top_n`` (25), each with an explicit ordinal rank (top_n for the first, down to 1) so the engine's own order (rank, then symbol) reproduces this order;
  stop             signal close - max(``atr_mult`` x ATR14, ``stop_floor`` x signal close), a price in the as-of basis; ATR14 = Wilder ATR on the adjusted high, low, close of the
                   symbol's last 252 bars as of the signal session (``indicators.atr_last``); reference_price is the signal close; no target. A stop that would be at or below zero
                   (ATR above a third of the price) makes the name unusable: it is skipped.
"""
from __future__ import annotations

import math
from datetime import date
from typing import Any, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

from stockbot.strategies.base import Proposal
from stockbot.strategies.riskadj_momentum.exits import ID as EXIT_ID
from stockbot.strategies.riskadj_momentum.indicators import atr_last
from stockbot.strategies.spec import StrategySpec

SPEC = StrategySpec(
    id="riskadj_momentum",
    version="1.0.0",
    params={"ret_long": 252, "ret_skip": 21, "min_closes": 240, "top_n": 25, "atr_period": 14, "atr_mult": 3.0, "stop_floor": 0.08, "tie_adtv_sessions": 20},
    universe_overrides={},
    exit_policy=EXIT_ID,
    status="research",
    prereg_ref="docs/strategies/riskadj_momentum/PREREGISTRATION.md",     # the config hash covers it
    validation_ref=None,
    expected_trade_rate=1.9,        # trades per month; set from the stage-1 slot arithmetic (docs/strategies/riskadj_momentum/PREREGISTRATION.md section 6)
    smallest_edge_of_interest=0.15,     # R per trade, net of costs (owner, fixed)
)


def register(registry) -> StrategySpec:
    """Register the spec in ``registry`` (a StrategyRegistry). Explicit on purpose: importing this package registers nothing, so the default registry stays empty."""
    return registry.register(SPEC)


def is_signal_session(view) -> bool:
    """True on the first trading session of a calendar month (its month differs from the previous session's); False when there is no previous session."""
    cal = view.sessions(lookback=2)
    return len(cal) == 2 and (cal[-1].year, cal[-1].month) != (cal[-2].year, cal[-2].month)


def assess(bars: pd.DataFrame, as_of: date, win_start: date, p: Mapping[str, Any]) -> tuple:
    """The rule on ONE symbol. ``bars``: adjusted bars (last ``ret_long`` + 1), ``win_start``: the first date of the last ``ret_long`` calendar sessions.
    Returns (reason, data): reason "ok" with data {close, ret, vol, score, atr} or one of "short" (fewer than ret_long + 1 own bars), "stale" (no bar on the signal date), "gap" (fewer than
    min_closes closes inside the window), "bad_price" (a non-positive or non-finite close), "ret_not_positive", "vol_not_positive", "atr_missing"."""
    n_long, n_skip = int(p["ret_long"]), int(p["ret_skip"])
    if len(bars) < n_long + 1:
        return "short", None
    if bars.index[-1] != as_of:
        return "stale", None
    close = bars["close_adj"].astype(float)
    if sum(1 for d in bars.index if d >= win_start) < int(p["min_closes"]):
        return "gap", None
    c = close.to_numpy()
    if not np.isfinite(c[-(n_long + 1):]).all() or (c[-(n_long + 1):] <= 0).any():
        return "bad_price", None
    c_skip, c_long = c[-1 - n_skip], c[-1 - n_long]                  # close at t-21 and t-252 on the symbol's own bars
    ret = float(c_skip / c_long - 1.0)
    if not ret > 0.0:
        return "ret_not_positive", {"ret": ret}
    vol = float(np.std(np.diff(np.log(c[-1 - n_long:-n_skip])), ddof=1))      # closes t-252 .. t-21 inclusive
    if not (math.isfinite(vol) and vol > 0.0):
        return "vol_not_positive", {"ret": ret, "vol": vol}
    atr = atr_last(bars, int(p["atr_period"]))
    if atr is None:
        return "atr_missing", {"ret": ret, "vol": vol}
    return "ok", {"close": float(c[-1]), "ret": ret, "vol": vol, "score": ret / vol, "atr": atr}


def initial_stop(close: float, atr: float, p: Mapping[str, Any]) -> tuple:
    """(stop, distance): signal close minus max(atr_mult x ATR, stop_floor x close)."""
    dist = max(float(p["atr_mult"]) * atr, float(p["stop_floor"]) * close)
    return close - dist, dist


def order_signals(view, sigs: Sequence, top_n: int, tie_n: int) -> tuple[list, dict]:
    """``sigs`` = [(symbol, score, ...)] -> (the same tuples in rank order, {symbol: adtv} for names whose ADTV was needed). Score descending, exact ties by higher raw ``tie_n``-session
    ADTV, then symbol. The ADTV is fetched only for tie groups that start inside the first ``top_n``."""
    sigs = sorted(sigs, key=lambda c: (-c[1], c[0]))
    ordered: list = []
    adtv_of: dict = {}
    i = 0
    while i < len(sigs):
        j = i
        while j + 1 < len(sigs) and sigs[j + 1][1] == sigs[i][1]:
            j += 1
        grp = sigs[i:j + 1]
        if len(grp) > 1 and i < top_n:
            for c in grp:
                adtv_of[c[0]] = view.adtv(c[0], tie_n) or 0.0
            grp = sorted(grp, key=lambda c: (-adtv_of[c[0]], c[0]))
        ordered.extend(grp)
        i = j + 1
    return ordered, adtv_of


class RiskAdjMomentumStrategy:
    def __init__(self, spec: StrategySpec = SPEC):
        self.spec = spec

    def propose(self, view, eligible: Sequence[str], as_of: date, strategy_state: Mapping[str, Any], overlays: Mapping[str, Any]) -> tuple[list, dict]:
        p = self.spec.params
        if not is_signal_session(view):
            return [], dict(strategy_state)
        n_long = int(p["ret_long"])
        cal = view.sessions(lookback=n_long)
        if len(cal) < n_long:                                   # the calendar window does not exist yet
            return [], dict(strategy_state)
        win_start = cal[0]
        top_n, tie_n = int(p["top_n"]), int(p["tie_adtv_sessions"])
        sigs: list = []                                         # (symbol, score, close, atr, ret, vol)
        for sym in eligible:
            reason, d = assess(view.adjusted_bars(sym, lookback=n_long + 1), as_of, win_start, p)
            if reason == "ok":
                stop, _ = initial_stop(d["close"], d["atr"], p)
                if stop > 0.0:
                    sigs.append((sym, d["score"], d["close"], d["atr"], d["ret"], d["vol"]))
        ordered, adtv_of = order_signals(view, sigs, top_n, tie_n)
        proposals = []
        for k, (sym, score, close, atr, ret, vol) in enumerate(ordered[:top_n]):
            stop, dist = initial_stop(close, atr, p)
            proposals.append(Proposal(self.spec.id, sym, as_of, close, stop, None, float(top_n - k),
                                      {"score": score, "ret": ret, "vol": vol, "atr": atr, "stop_distance": dist, "adtv": adtv_of.get(sym)}))
        return proposals, dict(strategy_state)

    def confirm_fill(self, proposal: Proposal, fill_price: float, view) -> Optional[str]:
        return None
