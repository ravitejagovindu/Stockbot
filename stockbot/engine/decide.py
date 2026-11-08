"""The decision function (ENGINE_CONTRACT section 6): ONE pure function that backtest, paper and live all call, for exactly ONE session.

``decide(as_of, state, view, strategies, shared_config, event_data, ...) -> (Decisions, State)``

Pure: no database, network, clock or randomness of its own; all market data comes through the as-of ``view`` (the future is unreachable); everything it remembers
is in ``State``. A strategy only proposes; sizing, caps, arbitration, fills, costs, corporate actions and the fixed execution assumptions are shared code.
Order of work for session T:
  0. validate inputs (one session; ``as_of`` is the first session after ``state.as_of``);
  1. evaluate the declared overlays (so exit policies see today's signal);
  2. pending tickets from the previous session are filled at T's open (shared gap rules, per-strategy ``confirm_fill``, sizing from the FILL price);
  3. every open position (a position filled this morning too, decision C1) gets its corporate actions, then is stepped through T's bar (engine.stepping);
  4. each strategy proposes on the eligible universe; proposals are sized and admitted together by ``risk.arbitrate`` against one set of caps;
  5. the new State is the fold of the Decisions (engine.apply), so a journal of Decisions rebuilds State exactly.
Modes: "backtest" and "paper" simulate fills (assumed); "live" does the same but every assumed fill / exit is also flagged UNRECONCILED_* because the live
adapter applies the operator's real fills before calling ``decide`` and reality overrides any inference (decision D4). ``strict`` (default True): an
exception in a strategy, overlay or exit policy propagates (decision C4); only the live adapter passes strict=False and then it is flagged and skipped.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any, Mapping, Optional, Sequence

from stockbot.engine.apply import apply_decisions
from stockbot.engine.corporate import apply_actions, due_actions
from stockbot.engine.exit_policy import Bar
from stockbot.engine.fills import fill_ticket
from stockbot.engine.stepping import step_position
from stockbot.engine.types import Blocked, ClosedTrade, CorporateActionApplied, Decisions, Flag, PositionUpdate, State, Ticket
from stockbot.risk.arbitration import OpenPos, Proposal as RiskProposal, admission_order, arbitrate
from stockbot.risk.caps import CapLimits
from stockbot.risk.costs import CostModel
from stockbot.risk.sizing import size_position
from stockbot.universe.eligibility import eligible_symbols

MODES = ("backtest", "paper", "live")


class EngineInputError(ValueError):
    """The call itself is wrong (not one session, unknown policy, overlay version mismatch ...): never swallowed, not even in live."""


@dataclass(frozen=True)
class EventData:
    """Plain data the adapters read into the engine: sector per symbol and ASM/GSM ranges (fail-closed exclusion)."""
    sectors: Mapping[str, str] = field(default_factory=dict)
    asm_ranges: Mapping[str, Sequence] = field(default_factory=dict)       # SYMBOL -> [(start, end), ...]


def bar_of(view, symbol: str) -> Optional[Bar]:
    """The split-adjusted bar of the as-of session, or None if the symbol has no bar on that date."""
    df = view.adjusted_bars(symbol, lookback=1)
    if df.empty or df.index[-1] != view.as_of:
        return None
    r = df.iloc[-1]
    return Bar(float(r["open_adj"]), float(r["high_adj"]), float(r["low_adj"]), float(r["close_adj"]))


def _equity(cash: float, positions) -> float:
    return cash + sum(p.shares_remaining * p.last_close for p in positions)


def _validate_session(as_of: date, state: State, view) -> None:
    if view.as_of != as_of:
        raise EngineInputError(f"view.as_of {view.as_of} != as_of {as_of}")
    ses = view.sessions(lookback=3)
    if not ses or ses[-1] != as_of:
        raise EngineInputError(f"{as_of} is not a trading session of the view")
    if state.as_of is not None:
        if as_of <= state.as_of:
            raise EngineInputError(f"as_of {as_of} is not after the state's {state.as_of}")
        if len(ses) < 2 or ses[-2] != state.as_of:
            raise EngineInputError(f"decide() handles exactly one session: state is at {state.as_of} but the session before {as_of} is {ses[-2] if len(ses) > 1 else None}; "
                                   "the adapter must call decide once per missed session")


def decide(as_of: date, state: State, view, strategies: Sequence, shared_config, event_data: EventData, *, policies: Mapping[str, Any],
           overlays: Optional[Mapping[str, Any]] = None, strict: bool = True, mode: str = "backtest") -> tuple[Decisions, State]:
    if mode not in MODES:
        raise EngineInputError(f"mode must be one of {MODES}")
    _validate_session(as_of, state, view)
    overlays = dict(overlays or {})
    by_id = {}
    for s in strategies:
        if s.spec.id in by_id:
            raise EngineInputError(f"duplicate strategy id {s.spec.id}")
        by_id[s.spec.id] = s
    ids = sorted(by_id)
    for sid in ids:
        if by_id[sid].spec.exit_policy not in policies:
            raise EngineInputError(f"strategy {sid}: unknown exit policy {by_id[sid].spec.exit_policy!r}")
    for pos in state.positions:
        if pos.exit_policy_id not in policies:
            raise EngineInputError(f"open position {pos.position_id}: unknown exit policy {pos.exit_policy_id!r}")

    ex, pr = shared_config.execution, shared_config.portfolio_risk
    costs = CostModel.from_shared(shared_config.costs)
    limits = CapLimits(pr.max_concurrent_positions, pr.max_total_portfolio_risk_pct, pr.max_sector_exposure_pct)
    flags: list = []
    blocked: list = []
    audit: list = []
    fills: list = []
    exits: list = []
    closed: list = []
    applied_ca: list = []
    updates: dict = {}
    cash, realised = state.cash, state.realised_pnl_net

    def guard(what, strategy_id, fn, default):
        """strict: let the exception propagate; live (strict=False): flag it and use ``default``."""
        if strict:
            return fn()
        try:
            return fn()
        except EngineInputError:
            raise
        except Exception as exc:                                    # noqa: BLE001 - live isolation
            flags.append(Flag("ERROR_" + what.upper(), f"{type(exc).__name__}: {exc}", strategy_id))
            return default

    # ---- 1) overlays (once per session each) ------------------------------------------------------------------------------------------------
    declared = {}
    for sid in ids:
        for oid, ver in by_id[sid].spec.overlays.items():
            declared[oid] = ver
    overlay_state = dict(state.overlay_state)
    signals: dict = {}
    for oid in sorted(declared):
        ov = overlays.get(oid)
        if ov is None or ov.version != declared[oid]:
            raise EngineInputError(f"overlay {oid}@{declared[oid]} declared but {'missing' if ov is None else 'registered as ' + ov.version}")
        out = guard("overlay", None, lambda: ov.evaluate(view, overlay_state.get(oid, {})), None)
        if out is not None:
            signals[oid], overlay_state[oid] = out[0], out[1]
        else:
            flags.append(Flag("OVERLAY_UNAVAILABLE", oid))

    def overlays_for(sid):
        return {o: signals[o] for o in by_id[sid].spec.overlays if o in signals} if sid in by_id else {}

    # ---- 2) fills of yesterday's tickets at today's open ------------------------------------------------------------------------------------
    eq_now = _equity(cash, state.positions)                       # marked at the previous close, before today's moves
    held = {p.symbol for p in state.positions}
    new_positions: list = []
    for t in state.pending:
        strat = by_id.get(t.strategy_id)
        if strat is None:
            blocked.append(Blocked(t.strategy_id, t.symbol, "STRATEGY_NOT_REGISTERED", "fill"))
            continue
        policy = policies[strat.spec.exit_policy]
        plan = fill_ticket(
            t, bar_of(view, t.symbol), as_of, execution=ex, risk_pct=pr.max_loss_pct_per_trade, equity=eq_now, cash=cash, costs=costs, policy_id=policy.id,
            held=t.symbol in held, corporate_action_today=any(a["ex_date"] == as_of for a in view.corporate_actions(t.symbol)),
            confirm=lambda prop, price, strat=strat, t=t: guard("confirm_fill", t.strategy_id, lambda: strat.confirm_fill(prop, price, view), "CONFIRM_FILL_ERROR"),
            initial_exit_state=lambda pos, policy=policy, t=t: guard("exit_policy", t.strategy_id, lambda: dict(policy.initial_state(pos, view)), {}))
        if not plan.ok:
            blocked.append(Blocked(t.strategy_id, t.symbol, plan.reason, "fill"))
            continue
        cash += plan.cash_delta
        held.add(t.symbol)
        new_positions.append(plan.position)
        fills.append(plan.fill)
        audit.append(("fill", {"ticket": t.ticket_id, "price": plan.fill.price, "shares": plan.fill.shares}))
        if mode == "live":
            flags.append(Flag("UNRECONCILED_FILL", "assumed fill; the operator's report overrides", t.strategy_id, t.symbol))

    # ---- 3) corporate actions, then step every open position through today's bar (new positions too: entry-bar stop) ---------------------------
    still_open: list = []
    for pos in list(state.positions) + new_positions:
        bar = bar_of(view, pos.symbol)
        if bar is None:
            flags.append(Flag("NO_BAR_POSITION_NOT_STEPPED", "", pos.strategy_id, pos.symbol))
            still_open.append(pos)
            updates[pos.position_id] = pos
            continue
        policy = policies[pos.exit_policy_id]
        due = due_actions(view.corporate_actions(pos.symbol), pos.entry_date, as_of, pos.ca_done)
        if due:
            out = apply_actions(pos, due, bar.open, policy)
            pos = out.position
            cash += out.fractional_cash
            applied_ca.extend(CorporateActionApplied(pos.position_id, k, f, c) for k, f, c in out.factors)
            if out.review:
                flags.append(Flag("CORPORATE_ACTION_HOLD", ",".join(out.review), pos.strategy_id, pos.symbol))
        res = guard("exit_policy_step", pos.strategy_id, lambda: step_position(pos, bar, as_of, view, policy, costs, ex.exit_slippage_pct, overlays_for(pos.strategy_id)), None)
        if res is None:                                                # live isolation: keep the position as is, flag already recorded
            pos = replace(pos, last_close=bar.close)
            still_open.append(pos)
            updates[pos.position_id] = pos
            continue
        cash += res.cash_delta
        exits.extend(res.exits)
        for f in res.flags:
            if f in ("STOP_HIT", "GAP_THROUGH_STOP"):
                continue
            flags.append(Flag(f, "", pos.strategy_id, pos.symbol))
        if mode == "live":
            for e in res.exits:
                flags.append(Flag("UNRECONCILED_EXIT", f"assumed {e.reason}; the operator's report overrides", pos.strategy_id, pos.symbol))
        if res.closed:
            p = res.position
            net = p.gross_pnl - p.costs_paid
            realised += net
            closed.append(ClosedTrade(p.position_id, p.strategy_id, p.symbol, p.entry_date, as_of, p.entry_price, p.initial_stop, p.shares_initial, p.risk_inr,
                                      p.gross_pnl, p.costs_paid, net, res.exits[-1].reason if res.exits else "UNKNOWN", p.hold))
        else:
            still_open.append(res.position)
            updates[res.position.position_id] = res.position

    # ---- 4) proposals -> sizing -> arbitration ----------------------------------------------------------------------------------------------
    equity = _equity(cash, still_open)
    strategy_state = dict(state.strategy_state)
    open_view = [OpenPos(p.symbol, p.sector, p.shares_remaining * p.entry_price, max(0.0, p.shares_remaining * (p.entry_price - p.live_stop)), p.strategy_id)
                 for p in still_open]
    elig_cache: dict = {}
    risk_props: list = []
    originals: dict = {}
    for sid in ids:
        strat = by_id[sid]
        okey = json.dumps(strat.spec.universe_overrides, sort_keys=True)
        if okey not in elig_cache:
            elig_cache[okey] = eligible_symbols(view, shared_config.universe, overrides=strat.spec.universe_overrides, asm_ranges=event_data.asm_ranges)
        eligible = elig_cache[okey]
        out = guard("propose", sid, lambda: strat.propose(view, tuple(eligible), as_of, strategy_state.get(sid, {}), overlays_for(sid)), None)
        if out is None:
            continue
        props, strategy_state[sid] = list(out[0]), dict(out[1])
        elig_set = set(eligible)
        for p in props:
            if p.strategy_id != sid:
                raise EngineInputError(f"strategy {sid} returned a proposal tagged {p.strategy_id}")
            if p.symbol not in elig_set:
                blocked.append(Blocked(sid, p.symbol, "NOT_ELIGIBLE", "propose"))
                continue
            if (sid, p.symbol) in originals:
                blocked.append(Blocked(sid, p.symbol, "DUPLICATE_PROPOSAL", "propose"))
                continue
            size = size_position(equity=equity, risk_pct=pr.max_loss_pct_per_trade, entry=p.reference_price, stop=p.stop)
            if not size.ok:
                blocked.append(Blocked(sid, p.symbol, size.reason, "sizing"))
                continue
            sector = event_data.sectors.get(p.symbol)
            risk_props.append(RiskProposal(sid, p.symbol, sector, size.position_value, size.risk_amount, p.rank))
            originals[(sid, p.symbol)] = (p, size, sector)
    tickets: list = []
    decisions_by_key = {(d.strategy_id, d.symbol): d for d in arbitrate(risk_props, limits=limits, equity=equity, open_positions=open_view)}
    for rp in admission_order(risk_props):
        d = decisions_by_key[(rp.strategy_id, rp.symbol)]
        p, size, sector = originals[(rp.strategy_id, rp.symbol)]
        if not d.accepted:
            blocked.append(Blocked(rp.strategy_id, rp.symbol, d.reason, "risk"))
            continue
        tickets.append(Ticket(f"{rp.strategy_id}:{rp.symbol}:{p.signal_date.isoformat()}", rp.strategy_id, rp.symbol, sector, p.signal_date, p.reference_price, p.stop,
                              p.target, size.shares, size.risk_amount, size.position_value, as_of, p.rank, dict(p.metadata)))
        audit.append(("ticket", {"strategy": rp.strategy_id, "symbol": rp.symbol, "shares": size.shares}))

    dec = Decisions(as_of=as_of, fills=tuple(fills), exits=tuple(exits), closed=tuple(closed), position_updates=tuple(PositionUpdate(k, v) for k, v in updates.items()),
                    new_tickets=tuple(tickets), blocked=tuple(blocked), corporate_actions_applied=tuple(applied_ca), flags=tuple(flags), audit=tuple(audit),
                    cash_after=cash, realised_pnl_after=realised, strategy_state_after=strategy_state, overlay_state_after=overlay_state)
    return dec, apply_decisions(state, dec)
