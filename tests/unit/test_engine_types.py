"""stockbot.engine.types: State and Decisions are plain data and round-trip through JSON without loss; the spec carries overlay ids and versions in its hash."""
import json
from dataclasses import fields, is_dataclass
from datetime import date

import pytest

from stockbot.engine import types as T
from stockbot.strategies.spec import SpecError, StrategySpec

D = date(2020, 3, 2)


def pos(**kw):
    base = dict(position_id="s1:AAA:2020-03-02", strategy_id="s1", symbol="AAA", sector="IT", entry_date=D, entry_price=100.5, initial_stop=95.0, live_stop=97.25,
                target=120.0, shares_initial=100.0, shares_remaining=60, risk_inr=550.0, exit_policy_id="fixed", exit_state={"n": 2, "xs": [1.5, 2.5], "m": {"a": None}},
                highest_high=104.0, days_held=3, last_close=102.0, gross_pnl=-12.5, costs_paid=33.1, ca_done=("2020-03-01:SPLIT",), hold=True, pending_exit=10, pending_reason="TIME")
    base.update(kw)
    return T.Position(**base)


def ticket(**kw):
    base = dict(ticket_id="s1:BBB:2020-02-28", strategy_id="s1", symbol="BBB", sector=None, signal_date=date(2020, 2, 28), reference_price=50.0, stop=47.0, target=None,
                shares_planned=200, risk_planned=600.0, value_planned=10000.0, created_on=date(2020, 2, 28), rank=2.5, metadata={"why": ["x", 1]})
    base.update(kw)
    return T.Ticket(**base)


def full_state():
    return T.State(as_of=D, cash=912345.67, positions=(pos(), pos(position_id="p2", symbol="CCC", target=None, ca_done=())), pending=(ticket(),),
                   strategy_state={"s1": {"k": [1, 2, {"z": 3}]}}, overlay_state={"o": {"on": True, "n": 3}}, realised_pnl_net=-1234.5)


def full_decisions():
    return T.Decisions(
        as_of=D,
        fills=(T.Fill("t", "p", "s1", "AAA", D, 100.5, 100, 12.3, True),),
        exits=(T.ExitRecord("p", "s1", "AAA", D, "STOP_HIT", 94.0, 100, 11.0, True, False),),
        closed=(T.ClosedTrade("p", "s1", "AAA", date(2020, 2, 3), D, 100.5, 95.0, 100.0, 550.0, -650.0, 23.3, -673.3, "STOP_HIT", True),),
        position_updates=(T.PositionUpdate("p", 98.0, {"a": 1}),),
        new_tickets=(ticket(),),
        blocked=(T.Blocked("s2", "AAA", "SYMBOL_HELD_BY_OTHER_STRATEGY", "risk"),),
        corporate_actions_applied=(T.CorporateActionApplied("p", "2020-03-01:SPLIT", 0.5, 12.5),),
        flags=(T.Flag("STRATEGY_ERROR", "boom", "s1", None),),
        audit=(("fill", {"x": 1}), ("exit", {"y": [1, 2]})),
    )


def test_state_round_trips_through_json_without_loss():
    s = full_state()
    again = T.State.from_json(s.to_json())
    assert again == s
    assert again.to_json() == s.to_json()


def test_decisions_round_trip_through_json_without_loss():
    d = full_decisions()
    again = T.Decisions.from_json(d.to_json())
    assert again == d and again.to_json() == d.to_json()


def test_every_engine_type_is_a_frozen_dataclass_of_json_native_values():
    for cls in (T.Position, T.Ticket, T.Fill, T.ExitRecord, T.ClosedTrade, T.PositionUpdate, T.Blocked, T.CorporateActionApplied, T.Flag, T.State, T.Decisions):
        assert is_dataclass(cls) and cls.__dataclass_params__.frozen
        assert fields(cls)
    json.loads(full_state().to_json())
    json.loads(full_decisions().to_json())


def test_unknown_schema_version_is_refused_not_guessed():
    d = json.loads(full_state().to_json())
    d["schema_version"] = 99
    with pytest.raises(ValueError, match="schema_version"):
        T.State.from_plain(d)


def test_empty_state_round_trips():
    s = T.State.initial(1_000_000)
    assert T.State.from_json(s.to_json()) == s and s.as_of is None and s.positions == ()


def test_spec_overlays_are_part_of_the_config_hash():
    a = StrategySpec(id="dummy", version="0.1.0", exit_policy="fixed")
    b = StrategySpec(id="dummy", version="0.1.0", exit_policy="fixed", overlays={"regime": "1.0.0"})
    c = StrategySpec(id="dummy", version="0.1.0", exit_policy="fixed", overlays={"regime": "1.0.1"})
    assert len({a.config_hash(), b.config_hash(), c.config_hash()}) == 3
    assert b.config_hash() == StrategySpec(id="dummy", version="0.1.0", exit_policy="fixed", overlays={"regime": "1.0.0"}).config_hash()
    assert a.overlays == {}


def test_spec_overlay_declarations_are_validated():
    for bad in ({"Bad Id": "1.0.0"}, {"regime": "v1"}, {"regime": 1}):
        with pytest.raises(SpecError):
            StrategySpec(id="dummy", version="0.1.0", exit_policy="fixed", overlays=bad)
