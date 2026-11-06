"""engine_core/corporate_action_events.py — corporate actions during an OPEN position (F3).

Approach (documented decision): when an ex-date falls inside a holding period, every price-denominated piece of
position state (entry, initial stop, live stop, target, highest high) is multiplied by the action's factor and the
share count is divided by it (floor; the fractional remainder is paid out as cash-in-lieu at the ex-date price).
A pure split or bonus therefore leaves P&L, R (measured against the invariant ``risk_inr``) and costs unchanged.

Handled: SPLIT, BONUS (via ``adjustments.action_factor``). Ignored: DIVIDEND (gross-return engine, no adjustment).
Anything else (RIGHTS, MERGER, demergers, unparseable ratios) is returned in ``review`` — the caller flags the
position for manual review and excludes the resulting trade from statistics.

The same function is used by ``backtest.simulator.Simulator`` and ``position_lifecycle.PositionLifecycleManager``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Iterable

from engine_core.adjustments import action_factor
from engine_core.lifecycle_rules import PosState, rescale_for_action

RESCALED_TYPES = ("SPLIT", "BONUS")
IGNORED_TYPES = ("DIVIDEND",)


@dataclass
class CAResult:
    pos: PosState
    fractional_shares: float = 0.0
    total_factor: float = 1.0
    applied: list = field(default_factory=list)   # action keys that were rescaled
    review: list = field(default_factory=list)    # action keys needing manual review


def _as_date(d) -> date:
    if isinstance(d, str):
        return date.fromisoformat(d)
    return d.date() if hasattr(d, "date") and callable(getattr(d, "date")) else d


def action_key(a: dict) -> str:
    return f"{_as_date(a['ex_date']).isoformat()}:{str(a.get('action_type', '')).upper()}"


def due_actions(actions: Iterable[dict], entry_date, through_date, already: Iterable[str] = ()) -> list:
    """Actions with entry_date < ex_date <= through_date that are not in ``already`` and are not ignorable."""
    done = set(already)
    entry_d, thr = _as_date(entry_date), _as_date(through_date)
    out = []
    for a in actions:
        ex = _as_date(a["ex_date"])
        if not (entry_d < ex <= thr):
            continue
        if str(a.get("action_type", "")).upper() in IGNORED_TYPES:
            continue
        if action_key(a) in done:
            continue
        out.append(a)
    return sorted(out, key=lambda a: (_as_date(a["ex_date"]), str(a.get("action_type", ""))))


def apply_actions_to_position(pos: PosState, actions: Iterable[dict], ex_price: float) -> CAResult:
    """Rescale ``pos`` for each due action in order. ``ex_price`` = first post-action price (ex-date open, new basis)."""
    res = CAResult(pos=pos)
    for a in actions:
        key = action_key(a)
        atype = str(a.get("action_type", "")).upper()
        if atype not in RESCALED_TYPES:
            res.review.append(key)
            continue
        try:
            factor = action_factor(a)
        except ValueError:
            res.review.append(key)
            continue
        if factor == 1.0:
            res.applied.append(key)
            continue
        res.pos, frac = rescale_for_action(res.pos, factor, ex_price)
        res.fractional_shares += frac
        res.total_factor *= factor
        res.applied.append(key)
    return res
