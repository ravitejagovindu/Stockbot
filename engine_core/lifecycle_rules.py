"""engine_core/lifecycle_rules.py — pure lifecycle + execution rules (no DB, no pandas)."""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Optional

INITIAL_RISK, RISK_FREE_1_TO_1, TRAILING_ATR = "INITIAL_RISK", "RISK_FREE_1_TO_1", "TRAILING_ATR"
PARABOLIC_TRAILING, PENDING_MANUAL_EXIT = "PARABOLIC_TRAILING", "PENDING_MANUAL_EXIT"


@dataclass(frozen=True)
class LifecycleRules:
    """Immutable rule-set derived from strategy_config.yaml.

    Create via :meth:`from_config` rather than instantiating directly.
    """

    time_decay_sessions: int
    trail_mult_normal: float
    trail_mult_kill: float
    parabolic_enabled: bool
    parabolic_thresh_atr: float
    parabolic_lookback: int
    parabolic_mult: float
    partial_enabled: bool
    partial_ladder: tuple          # ((rr_trigger, exit_pct), ...) ascending
    ratchet_enabled: bool
    ratchet_active_in_bull: bool
    ratchet_rungs: tuple           # ((trigger_rr, lock_rr), ...) ascending

    @staticmethod
    def from_config(cfg: dict) -> "LifecycleRules":
        """Build LifecycleRules from the full strategy config dict."""
        risk, tm = cfg["risk"], cfg["trade_management"]
        par, pp, pr = cfg.get("parabolic_stop", {}), cfg.get("partial_profit", {}), cfg.get("profit_ratchet", {})
        ladder = tuple(sorted(((float(r["rr_trigger"]), float(r["exit_pct"])) for r in pp.get("exit_ladder", [])),
                              key=lambda x: x[0]))
        rungs = tuple(sorted(((float(r["trigger_rr"]), float(r["lock_rr"])) for r in pr.get("rungs", [])),
                             key=lambda x: x[0]))
        return LifecycleRules(
            time_decay_sessions=int(tm["time_decay_sessions"]),
            trail_mult_normal=float(risk.get("trailing_stop_atr_multiplier", 2.5)),
            trail_mult_kill=float(risk.get("trailing_stop_atr_multiplier_kill_switch", 2.0)),
            parabolic_enabled=bool(par.get("enabled", False)),
            parabolic_thresh_atr=float(par.get("acceleration_threshold_atr", 3.0)),
            parabolic_lookback=int(par.get("acceleration_lookback_days", 5)),
            parabolic_mult=float(par.get("parabolic_atr_multiplier", 1.0)),
            partial_enabled=bool(pp.get("enabled", False)),
            partial_ladder=ladder,
            ratchet_enabled=bool(pr.get("enabled", False)),
            ratchet_active_in_bull=bool(pr.get("active_in_bull", False)),
            ratchet_rungs=rungs,
        )


@dataclass
class PosState:
    """Mutable state for one open position."""

    entry_price: float
    initial_stop: float
    live_stop: float
    target: float
    state: str = INITIAL_RISK
    days_held: int = 0
    highest_high: float = 0.0
    shares_remaining: int = 0
    last_partial_rr: float = 0.0
    partial_count: int = 0

    @property
    def one_r(self) -> float:
        """Initial risk per share (entry - initial stop)."""
        return self.entry_price - self.initial_stop


@dataclass(frozen=True)
class Bar:
    """Split-ADJUSTED prices for a single trading session."""

    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class BarCtx:
    """Per-session context values required by the lifecycle engine."""

    atr14: float
    kill_switch: bool
    is_bull: bool
    close_n_ago: Optional[float] = None   # see parabolic_ref_close()


@dataclass(frozen=True)
class Exit:
    """A single exit event (stop, time-decay or partial profit)."""

    reason: str       # STOP_HIT | TIME_DECAY | PARTIAL_PROFIT
    price: float
    shares: int


@dataclass
class BarResult:
    """Outcome of advancing a position by one bar."""

    pos: PosState
    closed: bool
    exits: list = field(default_factory=list)
    flags: list = field(default_factory=list)


def parabolic_ref_close(closes: list, lookback: int) -> Optional[float]:
    """Same reference the live code used: closes[-lookback] with lookback=min(lookback, len)."""
    lb = min(lookback, len(closes))
    return float(closes[-lb]) if lb >= 2 else None


def advance_one_bar(pos: PosState, bar: Bar, ctx: BarCtx, rules: LifecycleRules,
                    exit_slippage_pct: float = 0.0) -> BarResult:
    """Advance one position by one trading bar. Never mutates ``pos``.

    Order:
    (0) pending time-decay exit at today's OPEN ->
    (1) stop check vs the stop live at yesterday's close, gap-aware (fill = min(open, stop)) ->
    (2) age/high ->
    (3) state machine + trailing + ratchet ->
    (4) partial profit (limit sell: fill = max(open, limit)).
    """
    p = replace(pos)
    exits: list = []
    flags: list = []
    slip = 1.0 - exit_slippage_pct / 100.0

    if p.state == PENDING_MANUAL_EXIT:
        exits.append(Exit("TIME_DECAY", bar.open * slip, p.shares_remaining))
        p.shares_remaining = 0
        return BarResult(p, True, exits, ["TIME_DECAY_EXIT"])

    if bar.low <= p.live_stop:
        exits.append(Exit("STOP_HIT", min(bar.open, p.live_stop) * slip, p.shares_remaining))
        p.shares_remaining = 0
        return BarResult(p, True, exits, ["STOP_HIT"] + (["GAP_THROUGH_STOP"] if bar.open < pos.live_stop else []))

    p.days_held += 1
    p.highest_high = max(p.highest_high, bar.high)
    one_r = p.one_r
    mult = rules.trail_mult_kill if ctx.kill_switch else rules.trail_mult_normal

    if p.state == INITIAL_RISK:
        if p.highest_high >= p.entry_price + one_r:
            p.state, p.live_stop = RISK_FREE_1_TO_1, max(p.live_stop, p.entry_price)
        elif p.days_held >= rules.time_decay_sessions:
            p.state = PENDING_MANUAL_EXIT
            flags.append("TIME_DECAY_FLAGGED")
    elif p.state == RISK_FREE_1_TO_1:
        if p.highest_high > p.target:
            p.state = TRAILING_ATR
            p.live_stop = max(p.live_stop, p.highest_high - mult * ctx.atr14)

    if p.state == TRAILING_ATR:
        para = (rules.parabolic_enabled and ctx.atr14 > 0 and ctx.close_n_ago is not None
                and (bar.close - ctx.close_n_ago) >= rules.parabolic_thresh_atr * ctx.atr14)
        if para:
            p.state = PARABOLIC_TRAILING
        else:
            p.live_stop = max(p.live_stop, p.highest_high - mult * ctx.atr14)
    if p.state == PARABOLIC_TRAILING:
        p.live_stop = max(p.live_stop, p.highest_high - rules.parabolic_mult * ctx.atr14)

    ratchet_on = rules.ratchet_enabled and (rules.ratchet_active_in_bull or not ctx.is_bull)
    if ratchet_on and one_r > 0 and p.state != PENDING_MANUAL_EXIT:
        hi_rr = (p.highest_high - p.entry_price) / one_r
        for trig, lock in rules.ratchet_rungs:
            if hi_rr >= trig:
                p.live_stop = max(p.live_stop, p.entry_price + lock * one_r)

    if rules.partial_enabled and rules.partial_ladder and one_r > 0 and p.shares_remaining > 0:
        cur_rr = (bar.high - p.entry_price) / one_r
        for trig, pct in rules.partial_ladder:
            if trig > p.last_partial_rr and cur_rr >= trig:
                n = math.floor(p.shares_remaining * pct / 100.0)
                if n > 0:
                    limit = p.entry_price + trig * one_r
                    exits.append(Exit("PARTIAL_PROFIT", max(bar.open, limit) * slip, n))
                    p.shares_remaining -= n
                    p.last_partial_rr = trig
                    p.partial_count += 1
                    flags.append(f"PARTIAL_{n}_SHARES")
                break

    return BarResult(p, False, exits, flags)


@dataclass(frozen=True)
class EntryPlan:
    """Decision on whether/how to fill a ticket at the next open."""

    ok: bool
    reason: str
    fill_price: float = 0.0
    shares: int = 0
    rr_at_fill: float = 0.0


def plan_entry_fill(*, ticket_entry: float, stop: float, target: float, next_open: float, equity: float,
                    risk_pct: float, slippage_pct: float, max_gap_up_pct: float, min_rr: float,
                    cash: Optional[float] = None) -> EntryPlan:
    """Decide whether/how a ticket generated at close T is filled at open T+1 (paper + backtest)."""
    if next_open <= stop:
        return EntryPlan(False, "GAP_THROUGH_STOP")
    if next_open > ticket_entry * (1 + max_gap_up_pct / 100.0):
        return EntryPlan(False, "GAP_UP_TOO_LARGE")
    fill = next_open * (1 + slippage_pct / 100.0)
    risk_ps = fill - stop
    if risk_ps <= 0:
        return EntryPlan(False, "NONPOSITIVE_RISK")
    rr = (target - fill) / risk_ps
    if rr < min_rr:
        return EntryPlan(False, f"RR_AT_FILL_TOO_LOW({rr:.2f})", fill, 0, rr)
    shares = math.floor(equity * risk_pct / 100.0 / risk_ps)
    if cash is not None:
        shares = min(shares, math.floor(cash / fill))
    if shares < 1:
        return EntryPlan(False, "SIZE_ZERO", fill, 0, rr)
    return EntryPlan(True, "OK", fill, shares, rr)
