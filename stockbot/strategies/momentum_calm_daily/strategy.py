"""momentum_calm_daily: riskadj_momentum_daily behind ONE calm filter. Long-only "12-1 risk-adjusted momentum among the calmest half of stocks", every session a signal session, with a fixed re-entry
cooldown. It only PROPOSES (symbol, stop, rank); sizing, caps, arbitration, fills, costs, corporate actions and the exit (its own ``mcd_trailing_atr3_floor8``, ``exits.py``) belong to the engine. Signals are
taken on the session close, entry is the engine's next-open fill. Copied from riskadj_momentum_daily (a strategy may not import another strategy; ``is_signal_session``, ``cooldown_symbols``, ``assess``,
``initial_stop`` and ``order_signals`` below are VERBATIM copies, and tests/unit/test_momentum_calm_daily_strategy.py proves that with the filter off the proposals equal riskadj_momentum_daily's); the only
addition is the calm filter of momentum_calm (marked CHANGE).

The rule (every number is read from ``spec.params`` so ``config_hash`` covers it):
  signal sessions  as riskadj_momentum_daily: EVERY session of the calendar; the only condition is that the 252-session calendar window exists;
  history          as riskadj_momentum_daily / momentum_calm: a bar on the signal session, at least ``min_closes`` (240) adjusted closes inside the last ``ret_long`` (252) calendar sessions, ``ret_long`` + 1 (253)
                   adjusted bars of its OWN. A symbol failing this (``assess`` reasons short / stale / gap / bad_price) has no sigma252 and is never proposed;
  momentum         ret = close[t-21] / close[t-252] - 1 on adjusted closes, ret > 0 strictly; vol = sample sd of the daily log returns of closes t-252 .. t-21, vol > 0; score = ret / vol. Higher first, exact ties
                   by higher raw ``tie_adtv_sessions``-session ADTV, then symbol;
  CHANGE calm      sigma252 = sample sd (ddof = 1) of the 252 daily log returns of the symbol's own consecutive adjusted closes ending at the signal session (the last 253 own bars: closes t-252 .. t). It is computed
                   for EVERY eligible name that passes the history guards, BEFORE the ret > 0 filter AND BEFORE the cooldown is applied (a name in cooldown still has its sigma252 and still counts in the median);
                   ``median252`` = the median of sigma252 over ALL of those names (an even count: the mean of the two middle values). A name is CALM when sigma252 <= median252 (a tie at the median is calm).
                   Only calm names may be proposed: among them drop the names in cooldown, keep ret > 0 (and the other ``assess`` conditions), rank by score;
  cooldown         as riskadj_momentum_daily: a symbol whose position of THIS strategy was closed by STOP_HIT is not proposed until ``reentry_cooldown_sessions`` (21) sessions have passed after the exit session
                   (the exit session and the 21 sessions after it are blocked; the 22nd is the first allowed). Only STOP_HIT starts it. The exits come ONLY from the engine-owned history in ``strategy_state["_exits"]``
                   (class attribute ``exit_history_sessions``), the sessions from ``view.sessions``; linked names are the same symbol (``view.resolve_symbol``);
  proposals        the first ``top_n`` (25), each with an explicit ordinal rank (top_n for the first, down to 1);
  stop             as riskadj_momentum_daily: signal close - max(``atr_mult`` x ATR14, ``stop_floor`` x signal close); a stop at or below zero makes the name unusable: it is skipped.
"""
from __future__ import annotations

import math
from datetime import date
from typing import Any, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

from stockbot.strategies.base import Proposal
from stockbot.strategies.momentum_calm_daily.exits import ID as EXIT_ID
from stockbot.strategies.momentum_calm_daily.indicators import atr_last
from stockbot.strategies.spec import StrategySpec

SPEC = StrategySpec(
    id="momentum_calm_daily",
    version="1.0.0",
    params={"ret_long": 252, "ret_skip": 21, "min_closes": 240, "top_n": 25, "atr_period": 14, "atr_mult": 3.0, "stop_floor": 0.08, "tie_adtv_sessions": 20,
            "signal": "every_session", "reentry_cooldown_sessions": 21, "calm_vol_window": 252, "calm_cut": "median_of_eligible"},
    universe_overrides={},
    exit_policy=EXIT_ID,
    status="research",
    prereg_ref="docs/strategies/momentum_calm_daily/PREREGISTRATION.md",     # the config hash covers it
    validation_ref=None,
    expected_trade_rate=8.1,        # trades per month, as riskadj_momentum_daily (the filter changes the picks, not the slot arithmetic; see PREREGISTRATION.md)
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


# reasons of ``assess`` that come BEFORE the momentum and volatility tests: the history guards. A name with any of them has no sigma252.
HISTORY_FAILS = ("short", "stale", "gap", "bad_price")


def sigma252(bars: pd.DataFrame, n: int) -> float:
    """CHANGE (the calm filter's measure, as momentum_calm): sample sd (ddof = 1) of the ``n`` daily log returns of the symbol's own consecutive adjusted closes, the last ``n`` + 1 own bars. Call it only
    for a name whose ``assess`` reason is not in HISTORY_FAILS."""
    c = bars["close_adj"].astype(float).to_numpy()
    return float(np.std(np.diff(np.log(c[-(n + 1):])), ddof=1))


def screen(view, eligible: Sequence[str], as_of: date, p: Mapping[str, Any], cooling: Optional[set] = None, calm: bool = True) -> Optional[dict]:
    """One session, no state. ``cooling`` = the symbols in cooldown (``cooldown_symbols``; None or empty: none). Returns {"eligible", "sigma_n" (names with a sigma252, cooldown names included), "median",
    "calm_n", "positive_all" / "positive_calm" (names that pass every riskadj_momentum_daily condition, cooldown names excluded, all names / calm names), "ordered" (the qualifying names in rank order: calm only
    when ``calm``), "adtv_of"}. With ``calm=False`` the filter is off and ``ordered`` is exactly riskadj_momentum_daily's. None if the calendar window does not exist yet."""
    cooling = cooling or set()
    n_long = int(p["ret_long"])
    cal = view.sessions(lookback=n_long)
    if len(cal) < n_long:
        return None
    win_start = cal[0]
    top_n, tie_n, nv = int(p["top_n"]), int(p["tie_adtv_sessions"]), int(p["calm_vol_window"])
    eligible = list(eligible)
    sig_of: dict = {}                                       # symbol -> sigma252 (names that pass the history guards; cooldown names included)
    cands: list = []                                        # (symbol, score, close, atr, ret, vol, sigma252) of the names that pass assess, are not cooling and have a usable stop
    for sym in eligible:
        bars = view.adjusted_bars(sym, lookback=max(n_long + 1, nv + 1))
        reason, d = assess(bars, as_of, win_start, p)
        if reason in HISTORY_FAILS:
            continue
        sig_of[sym] = sigma252(bars, nv)
        if sym in cooling:
            continue
        if reason == "ok":
            stop, _ = initial_stop(d["close"], d["atr"], p)
            if stop > 0.0:
                cands.append((sym, d["score"], d["close"], d["atr"], d["ret"], d["vol"], sig_of[sym]))
    med = float(np.median(list(sig_of.values()))) if sig_of else None
    calm_set = {s for s, v in sig_of.items() if v <= med} if med is not None else set()
    use = [c for c in cands if c[0] in calm_set] if calm else cands
    ordered, adtv_of = order_signals(view, use, top_n, tie_n)
    return {"eligible": len(eligible), "sigma_n": len(sig_of), "median": med, "calm_n": len(calm_set), "positive_all": len(cands),
            "positive_calm": sum(1 for c in cands if c[0] in calm_set), "ordered": ordered, "adtv_of": adtv_of}


class MomentumCalmDailyStrategy:
    exit_history_sessions = 25            # opt-in to the engine-owned exit history (a class attribute, not a spec field); must be at least reentry_cooldown_sessions + 1

    def __init__(self, spec: StrategySpec = SPEC):
        self.spec = spec

    def propose(self, view, eligible: Sequence[str], as_of: date, strategy_state: Mapping[str, Any], overlays: Mapping[str, Any]) -> tuple[list, dict]:
        p = self.spec.params
        if not is_signal_session(view):
            return [], dict(strategy_state)
        cooling = cooldown_symbols(strategy_state, view, int(p["reentry_cooldown_sessions"]))
        s = screen(view, eligible, as_of, p, cooling=cooling, calm=True)
        if s is None:                                           # the calendar window does not exist yet
            return [], dict(strategy_state)
        top_n = int(p["top_n"])
        proposals = []
        for k, (sym, score, close, atr, ret, vol, sig) in enumerate(s["ordered"][:top_n]):
            stop, dist = initial_stop(close, atr, p)
            proposals.append(Proposal(self.spec.id, sym, as_of, close, stop, None, float(top_n - k),
                                      {"score": score, "ret": ret, "vol": vol, "atr": atr, "stop_distance": dist, "adtv": s["adtv_of"].get(sym), "sigma252": sig, "median_sigma252": s["median"]}))
        return proposals, dict(strategy_state)

    def confirm_fill(self, proposal: Proposal, fill_price: float, view) -> Optional[str]:
        return None
