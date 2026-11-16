"""lowvol_uptrend: long-only "low volatility inside an uptrend", rebalanced monthly. It only PROPOSES (symbol, stop, rank); sizing, caps, arbitration, fills, costs, corporate actions and
the exit (its own ``lv_trailing_atr3_floor8``, ``exits.py``) belong to the engine. Signals are taken on the session close, entry is the engine's next-open fill.

The rule (every number is read from ``spec.params`` so ``config_hash`` covers it):
  signal sessions  only the first trading session of each calendar month (its (year, month) differs from the previous calendar session's). No previous session, no signal;
  history          READING (same as riskadj_momentum, docs/strategies/lowvol_uptrend/BRIEF.md): the calendar window is the last ``vol_window`` (252) sessions ending at the signal session
                   (``view.sessions(lookback=252)``); the symbol needs a bar on the signal session, at least ``min_closes`` (240) adjusted closes inside that window, and ``vol_window`` + 1 (253)
                   adjusted bars of its OWN (``view.adjusted_bars(sym, lookback=253)``): 253 closes give the 252 daily log returns of the volatility. Fewer own bars: no signal;
  uptrend          signal close > SMA200, where the SMA is the mean of the symbol's adjusted closes that fall inside the calendar's last ``sma_window`` (200) sessions, and at least
                   ``sma_min_closes`` (198) of those 200 closes must be present. Strictly greater;
  volatility       vol = sample standard deviation (ddof = 1) of the 252 daily log returns of the symbol's own consecutive adjusted closes (the last 253 own bars, ending at the signal
                   session); vol > 0 strictly (a flat series has none);
  order            LOWEST vol first; exact ties by higher raw ``tie_adtv_sessions``-session ADTV (``view.adtv``, none counts as 0); then symbol. No rounding;
  proposals        the first ``top_n`` (25), each with an explicit ordinal rank (top_n for the first, down to 1) so the engine's own order (rank, then symbol) reproduces this order;
  stop             signal close - max(``atr_mult`` x ATR14, ``stop_floor`` x signal close), a price in the as-of basis; ATR14 = Wilder ATR on the adjusted high, low, close of the symbol's
                   last 252 bars as of the signal session (``indicators.atr_last``); reference_price is the signal close; no target. A stop at or below zero makes the name unusable: skipped.
"""
from __future__ import annotations

import math
from datetime import date
from typing import Any, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

from stockbot.strategies.base import Proposal
from stockbot.strategies.lowvol_uptrend.exits import ID as EXIT_ID
from stockbot.strategies.lowvol_uptrend.indicators import atr_last
from stockbot.strategies.spec import StrategySpec

SPEC = StrategySpec(
    id="lowvol_uptrend",
    version="1.0.0",
    params={"vol_window": 252, "min_closes": 240, "sma_window": 200, "sma_min_closes": 198, "top_n": 25, "atr_period": 14, "atr_mult": 3.0, "stop_floor": 0.08, "tie_adtv_sessions": 20},
    universe_overrides={},
    exit_policy=EXIT_ID,
    status="research",
    prereg_ref="docs/strategies/lowvol_uptrend/PREREGISTRATION.md",     # the config hash covers it
    validation_ref=None,
    expected_trade_rate=1.3,        # trades per month; set from the counts study slot arithmetic (docs/strategies/lowvol_uptrend/PREREGISTRATION.md section 6)
    smallest_edge_of_interest=0.15,     # R per trade, net of costs (owner, fixed)
)


def register(registry) -> StrategySpec:
    """Register the spec in ``registry`` (a StrategyRegistry). Explicit on purpose: importing this package registers nothing, so the default registry stays empty."""
    return registry.register(SPEC)


def is_signal_session(view) -> bool:
    """True on the first trading session of a calendar month (its month differs from the previous session's); False when there is no previous session."""
    cal = view.sessions(lookback=2)
    return len(cal) == 2 and (cal[-1].year, cal[-1].month) != (cal[-2].year, cal[-2].month)


def assess(bars: pd.DataFrame, as_of: date, win_start: date, sma_start: date, p: Mapping[str, Any]) -> tuple:
    """The rule on ONE symbol. ``bars``: adjusted bars (last ``vol_window`` + 1), ``win_start``: first date of the last ``vol_window`` calendar sessions, ``sma_start``: first date of the
    last ``sma_window`` calendar sessions. Returns (reason, data): reason "ok" with data {close, vol, sma, atr} or one of "short" (fewer than vol_window + 1 own bars), "stale" (no bar on the
    signal date), "gap" (fewer than min_closes closes inside the window), "bad_price", "sma_gap" (fewer than sma_min_closes closes inside the SMA window), "below_sma" (close <= SMA200),
    "vol_not_positive", "atr_missing"."""
    n = int(p["vol_window"])
    if len(bars) < n + 1:
        return "short", None
    if bars.index[-1] != as_of:
        return "stale", None
    if sum(1 for d in bars.index if d >= win_start) < int(p["min_closes"]):
        return "gap", None
    c = bars["close_adj"].astype(float).to_numpy()
    if not np.isfinite(c[-(n + 1):]).all() or (c[-(n + 1):] <= 0).any():
        return "bad_price", None
    idx = [i for i, d in enumerate(bars.index) if d >= sma_start]
    if len(idx) < int(p["sma_min_closes"]):
        return "sma_gap", None
    sma = float(np.mean(c[idx]))
    if not c[-1] > sma:
        return "below_sma", {"sma": sma}
    vol = float(np.std(np.diff(np.log(c[-(n + 1):])), ddof=1))
    if not (math.isfinite(vol) and vol > 0.0):
        return "vol_not_positive", {"sma": sma, "vol": vol}
    atr = atr_last(bars, int(p["atr_period"]))
    if atr is None:
        return "atr_missing", {"sma": sma, "vol": vol}
    return "ok", {"close": float(c[-1]), "vol": vol, "sma": sma, "atr": atr}


def initial_stop(close: float, atr: float, p: Mapping[str, Any]) -> tuple:
    """(stop, distance): signal close minus max(atr_mult x ATR, stop_floor x close)."""
    dist = max(float(p["atr_mult"]) * atr, float(p["stop_floor"]) * close)
    return close - dist, dist


def order_signals(view, sigs: Sequence, top_n: int, tie_n: int) -> tuple[list, dict]:
    """``sigs`` = [(symbol, vol, ...)] -> (the same tuples in rank order, {symbol: adtv} for names whose ADTV was needed). Vol ascending, exact ties by higher raw ``tie_n``-session ADTV,
    then symbol. The ADTV is fetched only for tie groups that start inside the first ``top_n``."""
    sigs = sorted(sigs, key=lambda c: (c[1], c[0]))
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


class LowVolUptrendStrategy:
    def __init__(self, spec: StrategySpec = SPEC):
        self.spec = spec

    def propose(self, view, eligible: Sequence[str], as_of: date, strategy_state: Mapping[str, Any], overlays: Mapping[str, Any]) -> tuple[list, dict]:
        p = self.spec.params
        if not is_signal_session(view):
            return [], dict(strategy_state)
        n = int(p["vol_window"])
        cal = view.sessions(lookback=n)
        if len(cal) < n:                                        # the calendar window does not exist yet
            return [], dict(strategy_state)
        win_start, sma_start = cal[0], cal[-int(p["sma_window"])]
        top_n, tie_n = int(p["top_n"]), int(p["tie_adtv_sessions"])
        sigs: list = []                                         # (symbol, vol, close, atr, sma)
        for sym in eligible:
            reason, d = assess(view.adjusted_bars(sym, lookback=n + 1), as_of, win_start, sma_start, p)
            if reason == "ok":
                stop, _ = initial_stop(d["close"], d["atr"], p)
                if stop > 0.0:
                    sigs.append((sym, d["vol"], d["close"], d["atr"], d["sma"]))
        ordered, adtv_of = order_signals(view, sigs, top_n, tie_n)
        proposals = []
        for k, (sym, vol, close, atr, sma) in enumerate(ordered[:top_n]):
            stop, dist = initial_stop(close, atr, p)
            proposals.append(Proposal(self.spec.id, sym, as_of, close, stop, None, float(top_n - k),
                                      {"vol": vol, "sma200": sma, "atr": atr, "stop_distance": dist, "adtv": adtv_of.get(sym)}))
        return proposals, dict(strategy_state)

    def confirm_fill(self, proposal: Proposal, fill_price: float, view) -> Optional[str]:
        return None
