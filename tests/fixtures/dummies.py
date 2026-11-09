"""Dummy strategy, exit policies and overlay for engine tests. They live under tests/ ONLY: no strategy is designed here.

ScriptedStrategy proposes exactly what its script says (symbol, stop, target, rank on given signal dates) and nothing else.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Mapping, Optional

from stockbot.engine.exit_policy import Limit, MarketAtNextOpen, PolicyActions
from stockbot.strategies.base import Proposal
from stockbot.strategies.spec import StrategySpec


def make_spec(sid="dummy", policy="fixed", **kw) -> StrategySpec:
    return StrategySpec(id=sid, version="0.1.0", exit_policy=policy, **kw)


class ScriptedStrategy:
    """script: {"2019-12-02": [{"symbol": "FIXCO", "stop": 159.1, "target": None, "rank": 0.0}, ...]}; reject_fill_above: confirm_fill rejects higher fills."""

    def __init__(self, spec: StrategySpec, script: Mapping[str, list], reject_fill_above: Optional[float] = None, boom_on: Optional[str] = None):
        self.spec, self.script, self.reject_fill_above, self.boom_on = spec, script, reject_fill_above, boom_on
        self.seen_eligible: dict = {}
        self.seen_overlays: dict = {}
        self.last_proposals: list = []

    def propose(self, view, eligible, as_of: date, strategy_state, overlays):
        self.seen_eligible[as_of.isoformat()] = tuple(eligible)
        self.seen_overlays[as_of.isoformat()] = dict(overlays)
        if self.boom_on == as_of.isoformat():
            raise RuntimeError("scripted failure")
        out = []
        for row in self.script.get(as_of.isoformat(), []):
            sym = row["symbol"]
            ref = float(view.adjusted_bars(sym, lookback=1)["close_adj"].iloc[-1])
            out.append(Proposal(self.spec.id, sym, as_of, ref, float(row["stop"]), row.get("target"), float(row.get("rank", 0.0)), dict(row.get("metadata", {}))))
        self.last_proposals = list(out)
        return out, {"n": int(strategy_state.get("n", 0)) + len(out)}

    def confirm_fill(self, proposal, fill_price, view):
        if self.reject_fill_above is not None and fill_price > self.reject_fill_above:
            return "FILL_ABOVE_LIMIT"
        return None


class FixedPolicy:
    """Stop stays where it is. Optional: time exit after ``max_days`` (market at next open), limit target at ``target_r`` R, breakeven stop after ``breakeven_r`` R."""

    def __init__(self, id="fixed", max_days: Optional[int] = None, target_r: Optional[float] = None, breakeven_r: Optional[float] = None, boom: bool = False):
        self.id, self.max_days, self.target_r, self.breakeven_r, self.boom = id, max_days, target_r, breakeven_r, boom

    def initial_state(self, position, view):
        return {"ref": position.entry_price}

    def step(self, position, bar, view, ctx):
        if self.boom:
            raise RuntimeError("policy failure")
        one_r = position.entry_price - position.initial_stop
        stop, req = None, []
        if self.breakeven_r is not None and position.highest_high >= position.entry_price + self.breakeven_r * one_r:
            stop = max(position.live_stop, position.entry_price)
        if self.target_r is not None:
            req.append(Limit(position.shares_remaining, position.entry_price + self.target_r * one_r, "TARGET"))
        if self.max_days is not None and ctx.days_held >= self.max_days:
            req.append(MarketAtNextOpen(position.shares_remaining, "TIME_EXIT"))
        return PolicyActions(new_live_stop=stop, new_exit_state=dict(position.exit_state), requests=tuple(req))

    def on_corporate_action(self, exit_state, factor):
        d = dict(exit_state)
        if "ref" in d:
            d["ref"] = d["ref"] * factor
        return d


class ViewReadingPolicy(FixedPolicy):
    """Reads the as-of close through the VIEW (decision C3) and stores it in its exit state, so a test can prove the view was passed and was as-of."""

    def step(self, position, bar, view, ctx):
        close = float(view.adjusted_bars(position.symbol, lookback=1)["close_adj"].iloc[-1])
        return PolicyActions(new_exit_state={**dict(position.exit_state), "seen_close": close, "seen_as_of": view.as_of.isoformat()})


class LoweringPolicy(FixedPolicy):
    def step(self, position, bar, view, ctx):
        return PolicyActions(new_live_stop=position.live_stop - 5.0)


class CountingOverlay:
    """Pure overlay: counts sessions it has been evaluated for; the signal says whether the count is even."""
    id = "counter"
    version = "1.0.0"

    def evaluate(self, view, overlay_state):
        n = int(overlay_state.get("n", 0)) + 1
        return {"n": n, "even": n % 2 == 0, "as_of": view.as_of.isoformat()}, {"n": n}
