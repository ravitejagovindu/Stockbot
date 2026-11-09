"""Exit policy interface (ENGINE_CONTRACT section 5). Standard library only.

A policy decides WHAT (a new stop level, requested exits, its own state); the engine's generic stepping (engine.stepping) decides HOW, in one fixed order
that is identical for every policy and for the matched-random baseline. A policy never sees a connection: anything it needs beyond the bar (ATR,
closes N sessions back, overlay signals) it reads through the as-of ``view`` (decision C3) or ``ctx.overlays``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Protocol, runtime_checkable


@dataclass(frozen=True)
class Bar:
    """Split-adjusted OHLC of one session in the as-of price basis."""
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class MarketAtNextOpen:
    """Exit ``shares`` at the next session's open (x exit slippage)."""
    shares: int
    reason: str = "POLICY_EXIT"


@dataclass(frozen=True)
class Limit:
    """Sell ``shares`` at ``limit_price`` when this bar's high reaches it: fill = max(open, limit) x (1 - exit slippage)."""
    shares: int
    limit_price: float
    reason: str = "LIMIT_EXIT"


@dataclass(frozen=True)
class StepContext:
    days_held: int                                             # sessions held including this bar
    overlays: Mapping[str, Any] = field(default_factory=dict)  # signals of the overlays the owning strategy declared


@dataclass(frozen=True)
class PolicyActions:
    new_live_stop: Optional[float] = None       # the engine never lets a stop move down
    new_exit_state: Optional[Mapping[str, Any]] = None
    requests: tuple = ()                        # MarketAtNextOpen | Limit
    flags: tuple = ()                           # strings


@runtime_checkable
class ExitPolicy(Protocol):
    id: str

    def initial_state(self, position, view) -> dict: ...

    def step(self, position, bar: Bar, view, ctx: StepContext) -> PolicyActions: ...

    def on_corporate_action(self, exit_state: Mapping[str, Any], factor: float) -> dict:
        """Rescale the price-valued parts of the policy's own state (``factor`` < 1 for a split or bonus)."""
