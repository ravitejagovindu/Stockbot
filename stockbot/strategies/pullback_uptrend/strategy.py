"""pullback_uptrend: long-only "short pullback inside a long uptrend". It only PROPOSES (symbol, stop, rank); sizing, caps, arbitration, fills, costs, corporate actions and the exit
(fixed_hold_5 from the shared library, or the stop) belong to shared code.

The rule (every number is read from ``spec.params``, so ``config_hash`` covers it); signals are taken on the session close, entry is the engine's next-open fill:
  history    the symbol needs ``min_bars`` (250) adjusted bars of its own and a bar on the as-of date (``view.adjusted_bars``, point-in-time, as-of basis);
  trend      adjusted close > SMA200, where the SMA is the mean of the symbol's closes inside the last ``sma_period`` (200) calendar sessions (the dates of ``view.sessions``)
             and at least ``sma_min_closes`` (198) of those 200 sessions must have a close. If the calendar has fewer than 200 sessions there is no SMA200 and no signal;
  pullback   RSI(``rsi_period`` = 2) < ``rsi_max`` (10), strictly. RSI is Wilder-smoothed (``stockbot.data.indicators.rma``: seeded with the simple mean of the first ``period``
             changes, then avg = (avg x (period-1) + x) / period) over the symbol's last 250 adjusted closes. avg_loss = 0 gives 100 (50 when avg_gain is also 0);
  order      RSI ascending (lowest first); exact ties by higher raw ``tie_adtv_sessions``-session ADTV (``view.adtv``, the figure shared eligibility uses; none counts as 0);
             then symbol. No rounding of RSI;
  proposals  the first ``top_n`` (25), each with an explicit ordinal rank (top_n for the first, down to 1) so that the engine's own order (rank, then symbol) reproduces this order;
  stop       ``stop_fraction`` (0.92) x the signal-day adjusted close, a price in the as-of basis; reference_price is that close; no target.
"""
from __future__ import annotations

import math
from datetime import date
from typing import Any, Mapping, Optional, Sequence

import pandas as pd

from stockbot.data.indicators import rma
from stockbot.strategies.base import Proposal
from stockbot.strategies.spec import StrategySpec

SPEC = StrategySpec(
    id="pullback_uptrend",
    version="1.0.0",
    params={"min_bars": 250, "sma_period": 200, "sma_min_closes": 198, "rsi_period": 2, "rsi_max": 10.0, "top_n": 25, "stop_fraction": 0.92, "tie_adtv_sessions": 20},
    universe_overrides={},
    exit_policy="fixed_hold_5",
    status="research",
    prereg_ref=None,
    validation_ref=None,
    expected_trade_rate=None,           # set by the owner from the stage-1 counts
    smallest_edge_of_interest=None,     # the owner supplies it; never invented here
)


def register(registry) -> StrategySpec:
    """Register the spec in ``registry`` (a StrategyRegistry). Explicit on purpose: importing this package registers nothing, so the default registry stays empty."""
    return registry.register(SPEC)


def rsi_wilder(closes: Sequence[float], period: int = 2) -> Optional[float]:
    """Wilder RSI of the LAST close of ``closes`` (oldest first), or None if there are fewer than ``period`` + 1 closes."""
    s = pd.Series([float(c) for c in closes])
    if len(s) < period + 1:
        return None
    ch = s.diff()
    avg_gain = float(rma(ch.clip(lower=0.0), period).iloc[-1])
    avg_loss = float(rma((-ch).clip(lower=0.0), period).iloc[-1])
    if not (math.isfinite(avg_gain) and math.isfinite(avg_loss)):
        return None
    if avg_loss == 0.0:
        return 50.0 if avg_gain == 0.0 else 100.0
    return 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)


def evaluate(bars: pd.DataFrame, as_of: date, win_start: date, p: Mapping[str, Any]) -> Optional[dict]:
    """The rule on ONE symbol: returns {close, sma, rsi} if every history and trend condition holds (RSI not yet compared with its limit), else None.
    ``bars`` are adjusted bars (last ``min_bars``), ``win_start`` the first date of the last ``sma_period`` calendar sessions."""
    if len(bars) < int(p["min_bars"]) or bars.index[-1] != as_of:
        return None
    close = bars["close_adj"]
    win = close[[d >= win_start for d in bars.index]]
    if len(win) < int(p["sma_min_closes"]):
        return None
    c_now, sma = float(close.iloc[-1]), float(win.mean())
    if not (math.isfinite(c_now) and math.isfinite(sma) and c_now > 0 and sma > 0) or not c_now > sma:
        return None
    rsi = rsi_wilder(close.tolist(), int(p["rsi_period"]))
    return None if rsi is None else {"close": c_now, "sma": sma, "rsi": rsi}


def order_signals(view, sigs: Sequence, top_n: int, tie_n: int) -> tuple[list, dict]:
    """``sigs`` = [(symbol, rsi, close)] in any order -> (the same triples in rank order, {symbol: adtv} for the names whose ADTV was needed). RSI ascending, exact RSI ties by higher raw
    ``tie_n``-session ADTV, then symbol. The ADTV is fetched only for tie groups that start inside the first ``top_n`` (the order beyond the cut is never used)."""
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


class PullbackUptrendStrategy:
    def __init__(self, spec: StrategySpec = SPEC):
        self.spec = spec

    def propose(self, view, eligible: Sequence[str], as_of: date, strategy_state: Mapping[str, Any], overlays: Mapping[str, Any]) -> tuple[list, dict]:
        p = self.spec.params
        cal = view.sessions(lookback=int(p["sma_period"]))
        if len(cal) < int(p["sma_period"]):                    # no SMA200 yet
            return [], dict(strategy_state)
        win_start = cal[0]
        top_n, stop_fraction, tie_n, rsi_max = int(p["top_n"]), float(p["stop_fraction"]), int(p["tie_adtv_sessions"]), float(p["rsi_max"])
        sigs: list = []                                        # (symbol, rsi, close)
        for sym in eligible:
            r = evaluate(view.adjusted_bars(sym, lookback=int(p["min_bars"])), as_of, win_start, p)
            if r is not None and r["rsi"] < rsi_max:
                sigs.append((sym, r["rsi"], r["close"]))
        ordered, adtv_of = order_signals(view, sigs, top_n, tie_n)
        proposals = [Proposal(self.spec.id, sym, as_of, c_now, stop_fraction * c_now, None, float(top_n - k), {"rsi": rsi, "adtv": adtv_of.get(sym)})
                     for k, (sym, rsi, c_now) in enumerate(ordered[:top_n])]
        return proposals, dict(strategy_state)

    def confirm_fill(self, proposal: Proposal, fill_price: float, view) -> Optional[str]:
        return None
