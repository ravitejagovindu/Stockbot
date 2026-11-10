"""A strategy-owned exit policy as the exit-policies rules allow it (test double: it lives under tests/ ONLY and designs no strategy).

It imports only the interface types from stockbot.engine.exit_policy (checked by tests/unit/test_exit_policy_isolation.py with the AST), never the shared
library stockbot.engine.exit_policies, another engine module or another strategy. A real one would sit in stockbot/strategies/<name>/.
"""
from __future__ import annotations

from stockbot.engine.exit_policy import MarketAtNextOpen, PolicyActions


class OwnExit:
    """Exit at the next open once ``days`` sessions have been held; counts the bars it saw in its own state."""

    def __init__(self, days: int = 2, id: str = "alpha_exit_2"):
        self.id, self.days = id, days

    def initial_state(self, position, view):
        return {"bars_seen": 0, "ref": position.entry_price}

    def step(self, position, bar, view, ctx):
        seen = int(position.exit_state.get("bars_seen", 0)) + 1
        req = (MarketAtNextOpen(position.shares_remaining, "OWN_EXIT"),) if ctx.days_held >= self.days else ()
        return PolicyActions(new_exit_state={**dict(position.exit_state), "bars_seen": seen}, requests=req)

    def on_corporate_action(self, exit_state, factor):
        d = dict(exit_state)
        if "ref" in d:
            d["ref"] = d["ref"] * factor
        return d
