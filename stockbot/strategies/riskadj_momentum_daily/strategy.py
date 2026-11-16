"""riskadj_momentum_daily: riskadj_momentum with ONE rule change (every session is a signal session) and a fixed re-entry cooldown. Long-only "risk-adjusted 12-1 momentum". It only PROPOSES (symbol, stop,
rank); sizing, caps, arbitration, fills, costs, corporate actions and the exit (its own ``rmd_trailing_atr3_floor8``, ``exits.py``) belong to the engine. Signals are taken on the session close, entry is the
engine's next-open fill. Copied from riskadj_momentum (nothing is imported from that folder); the differences are marked CHANGE below.

The rule (every number is read from ``spec.params`` so ``config_hash`` covers it):
  signal sessions  CHANGE: EVERY session of the calendar (``params["signal"] == "every_session"``). The only condition is that the 252-session calendar window exists;
  history          READING (as riskadj_momentum, docs/strategies/riskadj_momentum_daily/BRIEF.md): the calendar window is the last ``ret_long`` (252) sessions ending at the signal session
                   (``view.sessions(lookback=252)``); the symbol needs a bar on the signal session, at least ``min_closes`` (240) adjusted closes inside that window, and ``ret_long`` + 1 (253) adjusted
                   bars of its OWN (``view.adjusted_bars(sym, lookback=253)``), because the offsets t-21 and t-252 are counted on the symbol's own bars. A symbol with fewer than 253 own bars has no signal;
  momentum         ret = close[t-21] / close[t-252] - 1 on adjusted closes; ret > 0 strictly;
  volatility       vol = sample standard deviation (ddof = 1) of the daily log returns of the symbol's own consecutive adjusted closes from t-252 through t-21; vol > 0 strictly;
  score            ret / vol. Order: higher score first; exact ties by higher raw ``tie_adtv_sessions``-session ADTV (``view.adtv``, none counts as 0); then symbol. No rounding;
  cooldown         CHANGE: a symbol whose position of THIS strategy was closed by STOP_HIT is not proposed until ``reentry_cooldown_sessions`` (21) sessions have passed after the exit session: the exit session
                   and the 21 sessions after it are blocked, the 22nd session after the exit is the first allowed signal session. Only STOP_HIT starts a cooldown (SYMBOL_NO_BARS, operator-reported reasons and
                   everything else do not; END_OF_WINDOW never reaches the strategy). The exits come ONLY from the engine-owned history in ``strategy_state["_exits"]`` (class attribute
                   ``exit_history_sessions``; see ``stockbot.engine.exit_history``), the sessions from ``view.sessions``. Linked (renamed) names are the same symbol: both sides go through
                   ``view.resolve_symbol``. A blocked name is skipped BEFORE the ranking, so the next names move up and the top ``top_n`` is still filled from the allowed ones;
  proposals        the first ``top_n`` (25), each with an explicit ordinal rank (top_n for the first, down to 1);
  stop             signal close - max(``atr_mult`` x ATR14, ``stop_floor`` x signal close), a price in the as-of basis; ATR14 = Wilder ATR on the adjusted high, low, close of the symbol's last 252 bars
                   as of the signal session (``indicators.atr_last``); reference_price is the signal close; no target. A stop at or below zero makes the name unusable: it is skipped.
"""
from __future__ import annotations

import math
from datetime import date
from typing import Any, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

from stockbot.strategies.base import Proposal
from stockbot.strategies.riskadj_momentum_daily.exits import ID as EXIT_ID
from stockbot.strategies.riskadj_momentum_daily.indicators import atr_last
from stockbot.strategies.spec import StrategySpec

SPEC = StrategySpec(
    id="riskadj_momentum_daily",
    version="1.0.0",
    params={"ret_long": 252, "ret_skip": 21, "min_closes": 240, "top_n": 25, "atr_period": 14, "atr_mult": 3.0, "stop_floor": 0.08, "tie_adtv_sessions": 20,
            "signal": "every_session", "reentry_cooldown_sessions": 21},
    universe_overrides={},
    exit_policy=EXIT_ID,
    status="research",
    prereg_ref="docs/strategies/riskadj_momentum_daily/PREREGISTRATION.md",     # the config hash covers it
    validation_ref=None,
    expected_trade_rate=8.1,        # trades per month; set from the counts study slot arithmetic (docs/strategies/riskadj_momentum_daily/PREREGISTRATION.md section 6)
    smallest_edge_of_interest=0.15,     # R per trade, net of costs (owner, fixed)
)


def register(registry) -> StrategySpec:
    """Register the spec in ``registry`` (a StrategyRegistry). Explicit on purpose: importing this package registers nothing, so the default registry stays empty."""
    return registry.register(SPEC)


EXITS_KEY = "_exits"                      # the engine-owned key (stockbot.engine.exit_history.KEY; a test pins the equality; a strategy may not import the engine module)
COOLDOWN_REASON = "STOP_HIT"


def is_signal_session(view) -> bool:
    """CHANGE: every session is a signal session (the caller still needs the 252-session calendar window)."""
    return True


def cooldown_symbols(strategy_state: Mapping[str, Any], view, cooldown: int) -> set:
    """Canonical symbols that may not be proposed today: closed by STOP_HIT within the last ``cooldown`` + 1 sessions of the calendar (exit session = day 0 ... the ``cooldown``-th session after it)."""
    hist = (strategy_state or {}).get(EXITS_KEY) or ()
    if not hist:
        return set()
    cal = view.sessions(lookback=int(cooldown) + 1)
    if not cal:
        return set()
    first = cal[0].isoformat()
    canon = getattr(view, "resolve_symbol", None) or (lambda s: s)
    return {canon(sym) for sym, session, reason in hist if reason == COOLDOWN_REASON and str(session) >= first}


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


class RiskAdjMomentumDailyStrategy:
    exit_history_sessions = 25            # opt-in to the engine-owned exit history (a class attribute, not a spec field); must be at least reentry_cooldown_sessions + 1

    def __init__(self, spec: StrategySpec = SPEC):
        self.spec = spec

    def propose(self, view, eligible: Sequence[str], as_of: date, strategy_state: Mapping[str, Any], overlays: Mapping[str, Any]) -> tuple[list, dict]:
        p = self.spec.params
        if not is_signal_session(view):
            return [], dict(strategy_state)
        cooling = cooldown_symbols(strategy_state, view, int(p["reentry_cooldown_sessions"]))
        n_long = int(p["ret_long"])
        cal = view.sessions(lookback=n_long)
        if len(cal) < n_long:                                   # the calendar window does not exist yet
            return [], dict(strategy_state)
        win_start = cal[0]
        top_n, tie_n = int(p["top_n"]), int(p["tie_adtv_sessions"])
        sigs: list = []                                         # (symbol, score, close, atr, ret, vol)
        for sym in eligible:
            if sym in cooling:
                continue
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
