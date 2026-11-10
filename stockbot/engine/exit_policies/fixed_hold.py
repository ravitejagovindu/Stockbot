"""FixedHold: exit the whole position at the open of the session after ``hold_sessions`` sessions held. Id ``fixed_hold_<N>``. Standard library and the interface only.

Sessions are counted by the engine (``StepContext.days_held``, the entry session is 1, a session without a bar is not counted). The policy keeps no state and never
touches the stop; the initial stop stays where the ticket put it, and the engine executes a queued exit before it checks the stop.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from stockbot.engine.exit_policy import MarketAtNextOpen, PolicyActions


@dataclass(frozen=True)
class FixedHold:
    hold_sessions: int

    def __post_init__(self) -> None:
        if type(self.hold_sessions) is not int or self.hold_sessions < 1:
            raise ValueError(f"hold_sessions must be a positive integer, got {self.hold_sessions!r}")

    @property
    def id(self) -> str:
        return f"fixed_hold_{self.hold_sessions}"

    def initial_state(self, position, view) -> dict:
        return {}

    def step(self, position, bar, view, ctx) -> PolicyActions:
        if ctx.days_held >= self.hold_sessions:
            return PolicyActions(requests=(MarketAtNextOpen(position.shares_remaining, "TIME_EXIT"),))
        return PolicyActions()

    def on_corporate_action(self, exit_state: Mapping[str, Any], factor: float) -> dict:
        return dict(exit_state)
