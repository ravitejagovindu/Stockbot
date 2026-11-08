"""Portfolio-level arbitration (restructure Phase 5.2): proposals from several strategies, tagged by strategy id, are admitted against ONE set of caps.

Only ``risk`` applies caps; a strategy never sees another strategy's proposals. The admission order is explicit and deterministic, independent of the
order in which proposals arrive: higher ``rank`` first, then strategy id, then symbol. (How a strategy produces its rank is not defined here - no strategy
design - the default 0.0 means "no preference", so ties resolve by strategy id then symbol.) Each accepted proposal joins the virtual portfolio, so
later proposals see the tighter caps; once the caps are full every remaining proposal is blocked, as in the legacy sequential rule.
Not decided here (left to the engine contract, Phase 6 Part A): whether two strategies may hold or propose the same symbol.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from stockbot.risk.caps import CapLimits, caps_full, check_caps


@dataclass(frozen=True)
class Proposal:
    strategy_id: str
    symbol: str
    sector: Optional[str]
    position_value: float
    risk_amount: float
    rank: float = 0.0


@dataclass(frozen=True)
class Decision:
    strategy_id: str
    symbol: str
    accepted: bool
    reason: Optional[str]            # None when accepted


@dataclass(frozen=True)
class OpenPos:
    symbol: str
    sector: Optional[str]
    position_value: float
    risk_amount: float
    strategy_id: Optional[str] = None


def arbitrate(proposals: Sequence[Proposal], *, limits: CapLimits, equity: float, open_positions: Sequence = (), max_positions: Optional[int] = None) -> list[Decision]:
    ordered = sorted(proposals, key=lambda p: (-p.rank, p.strategy_id, p.symbol))
    virtual = list(open_positions)
    full = caps_full(limits=limits, equity=equity, open_positions=virtual, max_positions=max_positions)
    out: list[Decision] = []
    for p in ordered:
        if full:
            out.append(Decision(p.strategy_id, p.symbol, False, "BLOCKED_BY_RISK"))
            continue
        reason = check_caps(limits=limits, equity=equity, open_positions=virtual, sector=p.sector, position_value=p.position_value,
                            risk_amount=p.risk_amount, max_positions=max_positions)
        if reason is not None:
            out.append(Decision(p.strategy_id, p.symbol, False, reason))
            continue
        out.append(Decision(p.strategy_id, p.symbol, True, None))
        virtual.append(OpenPos(p.symbol, p.sector, p.position_value, p.risk_amount, p.strategy_id))
        full = caps_full(limits=limits, equity=equity, open_positions=virtual, max_positions=max_positions)
    return out
