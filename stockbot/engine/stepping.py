"""Generic position stepping (ENGINE_CONTRACT section 5): ONE fixed order for every exit policy and for random-entry baselines.

For one position and one session bar:
  1. a market exit requested on the previous bar executes at this bar's open x (1 - exit slippage);
  2. the stop live at the previous close is checked against this bar's low; a hit fills at min(open, stop) x (1 - exit slippage). This also applies to the
     ENTRY bar (decision C1): a position filled at the open is stepped through the same bar. There is NO floor at the bar's low (unfloored = conservative);
  3. days held and the highest high are updated, then the policy's ``step`` runs (stop moves, state, requests); a stop never moves down;
  4. limit requests fill at max(open, limit) x (1 - exit slippage) when the bar's high reaches the limit; market requests are queued for the next open.
BE/BZ sells (a HELD stock's bar on a non-EQ day, only with STOCKBOT_NON_EQ=held; the bar then carries ``series`` and ``volume``): a FIXED ASSUMPTION, not evidence (owner decision Q2, DESIGN.md section 5):
  - at most 10% of the bar's volume is sold per session (shares rounded down); the rest of a stop or open-queued exit is carried to the next session as a pending exit at that session's open;
  - no fill on a single-price bar (high == low) whose volume is below the shares still held;
  - the exit slippage is doubled; the price rules (stop fills at min(open, stop), limits at max(open, limit)) are the EQ rules; costs as for EQ.
Unknown and not modelled: the price band and queue position on that day, a resting limit order, a circuit that stays locked for days.
Costs (``risk.costs``) are settled here, so the backtest, paper/live and the baseline helper produce identical P&L for identical inputs.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping

from stockbot.engine.exit_policy import Bar, ExitPolicy, Limit, MarketAtNextOpen, StepContext
from stockbot.engine.types import ExitRecord, Position
from stockbot.risk.costs import CostModel


@dataclass(frozen=True)
class StepOutcome:
    position: Position
    exits: tuple              # ExitRecord
    cash_delta: float
    closed: bool
    flags: tuple              # strings


NON_EQ_VOLUME_CAP = 0.10          # fixed assumption (owner decision Q2)
NON_EQ_SLIPPAGE_MULT = 2.0        # fixed assumption (owner decision Q2)


def _non_eq(bar: Bar) -> bool:
    return getattr(bar, "series", "EQ") not in (None, "EQ")


def _sellable(bar: Bar, held: int) -> int:
    """Shares that can be sold on a non-EQ bar this session: 0 on a single-price bar with volume below the shares held, else 10% of the volume (rounded down), at most ``held``."""
    vol = float(bar.volume or 0.0)
    if bar.high == bar.low and vol < held:
        return 0
    return int(min(held, int(NON_EQ_VOLUME_CAP * vol)))


def _sell(pos: Position, day, reason: str, price: float, shares: int, costs: CostModel, closed: bool, assumed: bool = True):
    sell_cost = costs.sell_cost(price * shares)
    rec = ExitRecord(pos.position_id, pos.strategy_id, pos.symbol, day, reason, price, shares, sell_cost, closed, assumed)
    return rec, price * shares - sell_cost, (price - pos.entry_price) * shares, sell_cost


def step_position(pos: Position, bar: Bar, day, view, policy: ExitPolicy, costs: CostModel, exit_slippage_pct: float, overlays: Mapping[str, Any] = None) -> StepOutcome:
    """Advance ``pos`` through one session bar. Pure: returns a new Position, never mutates the input."""
    ne = _non_eq(bar)
    slip = 1.0 - (NON_EQ_SLIPPAGE_MULT if ne else 1.0) * exit_slippage_pct / 100.0
    exits: list = []
    flags: list = []
    cash = 0.0
    p = pos

    def book(reason, price, shares, closed):
        nonlocal cash, p
        rec, cash_in, gross, cost = _sell(p, day, reason, price, shares, costs, closed)
        exits.append(rec)
        cash += cash_in
        p = replace(p, shares_remaining=p.shares_remaining - shares, gross_pnl=p.gross_pnl + gross, costs_paid=p.costs_paid + cost)

    # 1) market exit requested on the previous bar
    if p.pending_exit > 0 and p.shares_remaining > 0:
        n = min(p.pending_exit, p.shares_remaining)
        n_fill = min(n, _sellable(bar, p.shares_remaining)) if ne else n
        reason = p.pending_reason or "POLICY_EXIT"
        if n_fill > 0:
            book(reason, bar.open * slip, n_fill, n_fill == p.shares_remaining)
        rest = n - n_fill
        p = replace(p, pending_exit=rest, pending_reason=reason if rest else "", last_close=bar.close)
        if p.shares_remaining == 0:
            return StepOutcome(p, tuple(exits), cash, True, tuple(flags))
        if rest > 0:                                                     # non-EQ sell capped: the rest waits for the next session (no stop test, no policy step this bar)
            flags.append("SELL_CAPPED_NON_EQ")
            p = replace(p, days_held=p.days_held + 1, highest_high=max(p.highest_high, bar.high))
            return StepOutcome(p, tuple(exits), cash, False, tuple(flags))

    # 2) the stop live at the previous close (entry bar included)
    if bar.low <= p.live_stop:
        n = p.shares_remaining
        n_fill = min(n, _sellable(bar, n)) if ne else n
        if n_fill > 0:
            book("STOP_HIT", min(bar.open, p.live_stop) * slip, n_fill, n_fill == n)
        flags.append("STOP_HIT")
        if bar.open < p.live_stop:
            flags.append("GAP_THROUGH_STOP")
        p = replace(p, last_close=bar.close)
        if n_fill == n:
            return StepOutcome(p, tuple(exits), cash, True, tuple(flags))
        flags.append("SELL_CAPPED_NON_EQ")                               # non-EQ: only part (or none) could be sold; the rest is a pending exit at the next open
        p = replace(p, pending_exit=n - n_fill, pending_reason="STOP_HIT", days_held=p.days_held + 1, highest_high=max(p.highest_high, bar.high))
        return StepOutcome(p, tuple(exits), cash, False, tuple(flags))

    # 3) age, high, policy
    p = replace(p, days_held=p.days_held + 1, highest_high=max(p.highest_high, bar.high), last_close=bar.close)
    act = policy.step(p, bar, view, StepContext(days_held=p.days_held, overlays=dict(overlays or {})))
    flags.extend(act.flags)
    new_stop = p.live_stop
    if act.new_live_stop is not None:
        if act.new_live_stop < p.live_stop:
            flags.append("STOP_LOWERING_IGNORED")
        else:
            new_stop = act.new_live_stop
    p = replace(p, live_stop=new_stop, exit_state=dict(act.new_exit_state) if act.new_exit_state is not None else p.exit_state)

    # 4) requests: limits fill on this bar, market requests are queued for the next open
    queued, reason = 0, ""
    cap_left = _sellable(bar, p.shares_remaining) if ne else None          # non-EQ: the session's volume cap is shared by all limit requests of the bar
    for r in act.requests:
        if isinstance(r, Limit):
            n = min(int(r.shares), p.shares_remaining)
            if cap_left is not None:
                n = min(n, cap_left)
            if n > 0 and bar.high >= r.limit_price:
                if cap_left is not None:
                    cap_left -= n
                book(r.reason, max(bar.open, r.limit_price) * slip, n, n == p.shares_remaining)
        elif isinstance(r, MarketAtNextOpen):
            if int(r.shares) > 0:
                queued, reason = queued + int(r.shares), (reason or r.reason)
        else:
            raise TypeError(f"unknown exit request: {r!r}")
    if p.shares_remaining > 0 and queued:
        p = replace(p, pending_exit=min(queued, p.shares_remaining), pending_reason=reason)
    return StepOutcome(p, tuple(exits), cash, p.shares_remaining == 0, tuple(flags))


def close_no_bars(pos: Position, day, costs: CostModel, exit_slippage_pct: float) -> StepOutcome:
    """Close ``pos`` at its last available close x (1 - exit slippage) with the normal sell costs: reason SYMBOL_NO_BARS (see ``stockbot.engine.stale``). Pure."""
    price = pos.last_close * (1.0 - exit_slippage_pct / 100.0)
    rec, cash_in, gross, cost = _sell(pos, day, "SYMBOL_NO_BARS", price, pos.shares_remaining, costs, True)
    p = replace(pos, shares_remaining=0, gross_pnl=pos.gross_pnl + gross, costs_paid=pos.costs_paid + cost, pending_exit=0, pending_reason="")
    return StepOutcome(p, (rec,), cash_in, True, ("SYMBOL_NO_BARS",))
