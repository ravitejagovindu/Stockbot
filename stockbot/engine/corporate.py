"""Corporate actions on OPEN positions, generic (ENGINE_CONTRACT section 7).

Splits and bonuses rescale every generic price field (entry, initial stop, live stop, target, highest high, last close), divide the shares by the factor
(floor; the fractional remainder is paid in cash at the ex-date open), scale a queued market exit (pending_exit) with them and call ``ExitPolicy.on_corporate_action`` for the policy-owned prices. R (``risk_inr``),
days held and counters are unchanged. Anything the engine cannot rescale (rights, mergers, demergers, unparsable ratios) puts the position on HOLD:
flagged, excluded from trade statistics. Dividends are ignored (gross-return engine). Only actions known by the as-of date (ex_date <= as_of) arrive here.
Mirrors the F3 behaviour of ``stockbot.engine.corporate_action_events`` (which stays for the legacy simulator until Phase 10).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import date
from typing import Iterable

from stockbot.data.adjustments import action_factor
from stockbot.engine.types import Position

RESCALED_TYPES = ("SPLIT", "BONUS")
IGNORED_TYPES = ("DIVIDEND",)


def _day(d) -> date:
    return date.fromisoformat(d) if isinstance(d, str) else (d.date() if hasattr(d, "date") and callable(d.date) else d)


def action_key(a: dict) -> str:
    return f"{_day(a['ex_date']).isoformat()}:{str(a.get('action_type', '')).upper()}"


def due_actions(actions: Iterable[dict], entry_date, through_date, already: Iterable[str] = ()) -> list:
    """Actions with entry_date < ex_date <= through_date that are not yet applied and not ignorable, in (ex_date, type) order."""
    done, e, t = set(already), _day(entry_date), _day(through_date)
    out = [a for a in actions if e < _day(a["ex_date"]) <= t and str(a.get("action_type", "")).upper() not in IGNORED_TYPES and action_key(a) not in done]
    return sorted(out, key=lambda a: (_day(a["ex_date"]), str(a.get("action_type", ""))))


@dataclass(frozen=True)
class CAOutcome:
    position: Position
    fractional_cash: float = 0.0
    total_factor: float = 1.0
    applied: tuple = ()
    review: tuple = ()
    factors: tuple = ()          # (key, factor, fractional_cash) per rescaled action


def _rescaled_pending(pos: Position, factor: float, new_shares: int) -> int:
    """A market exit queued for the next open scales with the shares: a full exit stays a full exit (exactly the new shares), a partial one is floored."""
    if pos.pending_exit <= 0:
        return pos.pending_exit
    if pos.pending_exit >= pos.shares_remaining:
        return new_shares
    return min(new_shares, int(math.floor(pos.pending_exit / factor + 1e-9)))


def _rescale(pos: Position, factor: float, ex_price: float, policy) -> tuple:
    exact = pos.shares_remaining / factor
    n = int(math.floor(exact + 1e-9))
    frac = exact - n
    if frac < 1e-9:
        frac = 0.0
    new = replace(
        pos, entry_price=pos.entry_price * factor, initial_stop=pos.initial_stop * factor, live_stop=pos.live_stop * factor,
        target=None if pos.target is None else pos.target * factor, highest_high=pos.highest_high * factor, last_close=pos.last_close * factor,
        shares_remaining=n, shares_initial=pos.shares_initial / factor, pending_exit=_rescaled_pending(pos, factor, n),
        exit_state=policy.on_corporate_action(pos.exit_state, factor) if policy is not None else pos.exit_state,
    )
    return new, frac


def apply_actions(pos: Position, actions: Iterable[dict], ex_price: float, policy=None) -> CAOutcome:
    """Apply the due actions in order. ``ex_price`` = the ex-date open (new basis), used for the cash in lieu of fractional shares."""
    p, cash, total, applied, review, facs = pos, 0.0, 1.0, [], [], []
    for a in actions:
        key = action_key(a)
        if str(a.get("action_type", "")).upper() not in RESCALED_TYPES:
            review.append(key)
            continue
        try:
            factor = action_factor(a)
        except ValueError:
            review.append(key)
            continue
        if factor == 1.0:
            applied.append(key)
            continue
        p, frac = _rescale(p, factor, ex_price, policy)
        c = frac * ex_price
        cash += c
        total *= factor
        applied.append(key)
        facs.append((key, factor, c))
    if cash:
        p = replace(p, gross_pnl=p.gross_pnl + (cash / ex_price) * (ex_price - p.entry_price))
    p = replace(p, ca_done=tuple(p.ca_done) + tuple(applied) + tuple(review), hold=p.hold or bool(review))
    return CAOutcome(p, cash, total, tuple(applied), tuple(review), tuple(facs))
