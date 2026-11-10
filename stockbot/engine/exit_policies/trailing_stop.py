"""TrailingStop: the stop trails ``percent`` % below the highest close since entry. Id ``trailing_pct_<P>``. Standard library and the interface only.

Reference price: the highest close seen since entry, seeded with the position's entry price (the fill price). A close-based reference avoids any ordering question
about the bar's high and low. State: ``{"highest_close": float}`` in the position's price basis (rescaled by corporate actions with the same factor as the stop).
``step`` proposes a new stop only when it is above the live stop, and the engine applies it from the NEXT bar (it checks the stop before it calls the policy). The
policy requests no exits; the stop does the exiting, filled by the engine at min(open, stop) x (1 - exit slippage). It reads only the bar it is given.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from stockbot.engine.exit_policy import PolicyActions


@dataclass(frozen=True)
class TrailingStop:
    percent: int

    def __post_init__(self) -> None:
        if type(self.percent) is not int or not 1 <= self.percent <= 99:
            raise ValueError(f"percent must be an integer from 1 to 99, got {self.percent!r}")

    @property
    def id(self) -> str:
        return f"trailing_pct_{self.percent}"

    def initial_state(self, position, view) -> dict:
        return {"highest_close": float(position.entry_price)}

    def step(self, position, bar, view, ctx) -> PolicyActions:
        highest = max(float(position.exit_state.get("highest_close", position.entry_price)), float(bar.close))
        candidate = highest * (1 - self.percent / 100)
        return PolicyActions(new_live_stop=candidate if candidate > position.live_stop else None, new_exit_state={"highest_close": highest})

    def on_corporate_action(self, exit_state: Mapping[str, Any], factor: float) -> dict:
        out = dict(exit_state)
        if "highest_close" in out:
            out["highest_close"] = out["highest_close"] * factor
        return out
