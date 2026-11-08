"""Portfolio-level arbitration (restructure Phase 5.2): proposals from several strategies, tagged by strategy id, are admitted against ONE set of caps.

Only ``risk`` applies caps; a strategy never sees another strategy's proposals. The admission order is explicit and deterministic, independent of the
order in which proposals arrive (decision D6): rank is meaningful only inside one strategy, so each strategy's proposals are ordered by (rank, symbol) and the
strategies are interleaved round-robin in strategy-id order. (How a strategy produces its rank is not defined here - no strategy design.) Each accepted proposal joins the virtual portfolio, so
later proposals see the tighter caps; once the caps are full every remaining proposal is blocked, as in the legacy sequential rule.
Same symbol (decision D3): a symbol already held cannot be opened by another strategy; the first in admission order wins.
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


def _get(p, name, default=None):
    return p.get(name, default) if isinstance(p, dict) else getattr(p, name, default)


def admission_order(proposals: Sequence[Proposal]) -> list[Proposal]:
    """Decision D6: rank is meaningful only inside one strategy. Each strategy's proposals are ordered by (-rank, symbol) (higher rank first), then the
    strategies are interleaved round-robin in strategy-id order (every strategy's first choice, then every strategy's second choice, ...). The result does
    not depend on the order in which proposals arrive."""
    by: dict[str, list[Proposal]] = {}
    for p in proposals:
        by.setdefault(p.strategy_id, []).append(p)
    queues = [sorted(by[sid], key=lambda p: (-p.rank, p.symbol)) for sid in sorted(by)]
    out: list[Proposal] = []
    for i in range(max((len(q) for q in queues), default=0)):
        out.extend(q[i] for q in queues if i < len(q))
    return out


def arbitrate(proposals: Sequence[Proposal], *, limits: CapLimits, equity: float, open_positions: Sequence = (), max_positions: Optional[int] = None) -> list[Decision]:
    """Admit proposals in ``admission_order`` against one set of caps. A symbol already held (decision D3) cannot be opened again: by another strategy ->
    ``SYMBOL_HELD_BY_OTHER_STRATEGY``, by the same strategy -> ``ALREADY_HELD``; the first proposal in admission order wins a symbol. Sector and total-risk caps
    see all positions."""
    virtual = list(open_positions)
    holders = {_get(q, "symbol"): _get(q, "strategy_id") for q in virtual}
    full = caps_full(limits=limits, equity=equity, open_positions=virtual, max_positions=max_positions)
    out: list[Decision] = []
    for p in admission_order(proposals):
        if p.symbol in holders:
            other = holders[p.symbol] is not None and holders[p.symbol] != p.strategy_id
            out.append(Decision(p.strategy_id, p.symbol, False, "SYMBOL_HELD_BY_OTHER_STRATEGY" if other else "ALREADY_HELD"))
            continue
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
        holders[p.symbol] = p.strategy_id
        full = caps_full(limits=limits, equity=equity, open_positions=virtual, max_positions=max_positions)
    return out
