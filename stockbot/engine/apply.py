"""Fold a session's Decisions into a State (ENGINE_CONTRACT D8): the same pure function is used by ``decide`` to build its returned State and by the live
journal to rebuild a State from stored Decisions, so the two cannot drift apart."""
from __future__ import annotations

from dataclasses import replace

from stockbot.engine.types import Decisions, State


def apply_decisions(state: State, d: Decisions) -> State:
    closed_ids = {c.position_id for c in d.closed}
    updates = {u.position_id: u.position for u in d.position_updates}
    kept = [updates.pop(p.position_id, p) for p in state.positions if p.position_id not in closed_ids]
    # positions opened this session appear only in the updates (fills), in fill order
    for f in d.fills:
        if f.position_id in updates:
            kept.append(updates.pop(f.position_id))
    kept = [p for p in kept if p.position_id not in closed_ids]
    return replace(state, as_of=d.as_of, cash=d.cash_after, positions=tuple(kept), pending=tuple(d.new_tickets), strategy_state=dict(d.strategy_state_after),
                   overlay_state=dict(d.overlay_state_after), realised_pnl_net=d.realised_pnl_after)
