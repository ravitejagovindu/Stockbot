"""Strategy and overlay interfaces (restructure Phase 6 Part B; ENGINE_CONTRACT sections 4 and 8). Standard library only.

A strategy only PROPOSES: it returns proposals (symbol, stop, optional target, rank) and its own plain-data state. It never receives a connection,
a clock, other strategies' proposals, portfolio caps or other strategies' state. Sizing, caps, arbitration, fills, costs and exits belong to shared code.
``rank`` is meaningful only inside one strategy (decision D6).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Mapping, Optional, Protocol, Sequence, runtime_checkable


@dataclass(frozen=True)
class Proposal:
    strategy_id: str
    symbol: str
    signal_date: date
    reference_price: float            # the signal-session close the proposal is based on (gap-up cap reference)
    stop: float                       # price; the strategy decides it, shared code never derives one
    target: Optional[float] = None    # optional
    rank: float = 0.0
    metadata: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class Strategy(Protocol):
    spec: Any                                                       # StrategySpec

    def propose(self, view, eligible: Sequence[str], as_of: date, strategy_state: Mapping[str, Any], overlays: Mapping[str, Any]) -> tuple[list, dict]:
        """Return (proposals, new_strategy_state). ``view`` is the as-of view; ``eligible`` the symbols that passed the shared universe rules."""

    def confirm_fill(self, proposal: Proposal, fill_price: float, view) -> Optional[str]:
        """Per-strategy fill-time check (for example a minimum R:R at the fill price). Return None to accept or a reject reason."""


@runtime_checkable
class Overlay(Protocol):
    id: str
    version: str

    def evaluate(self, view, overlay_state: Mapping[str, Any]) -> tuple[dict, dict]:
        """Pure: return (signal as a plain mapping, new_overlay_state). Hysteresis lives in the state."""
