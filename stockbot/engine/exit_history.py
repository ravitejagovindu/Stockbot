"""Engine-owned exit history for strategies that opt in (decision of 2026-11-16).

A strategy opts in with a CLASS attribute ``exit_history_sessions = N`` (N > 0; not a spec field, so no spec, config or gates hash depends on it). For such a strategy the engine records
each of ITS OWN closed positions as ``[canonical symbol, exit session (ISO), exit reason]`` under the reserved key ``KEY`` of the strategy's state, BEFORE proposals are requested, and keeps
only the entries whose exit session lies in the last N sessions of the view's calendar (as-of day included). The same record is appended when an operator-reported exit closes a position in live
(``engine.reports.apply_effect``; pruning there waits for the next ``decide``). The key is engine-owned: whatever a strategy returns, ``decide`` puts its own copy back. A strategy that does not
opt in gets exactly the state it gets without this module: no key, no byte changed.

Reasons are the engine's: STOP_HIT, SYMBOL_NO_BARS, POLICY_EXIT, TARGET ...; a position still open at the end of a backtest window is closed by the runner AFTER the last ``decide`` and never appears here.
Entries are in the order the positions were closed within a session and in session order across sessions; JSON-serialisable (lists of three strings).
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

KEY = "_exits"


def history_sessions(strategy) -> int:
    """N of the opt-in attribute; 0 when the strategy does not opt in."""
    try:
        return max(0, int(getattr(strategy, "exit_history_sessions", 0) or 0))
    except (TypeError, ValueError):
        return 0


def entries(closed: Iterable, sid: str, session, canon) -> list:
    """The records for the trades of strategy ``sid`` in ``closed`` (ClosedTrade objects), in order."""
    return [[canon(c.symbol), session.isoformat(), c.exit_reason] for c in closed if c.strategy_id == sid]


def merged(prior: Sequence, new: Sequence, calendar: Sequence) -> list:
    """prior + new, pruned to exit sessions on or after the first date of ``calendar`` (the view's last N sessions); everything is kept if the calendar is empty."""
    cutoff = calendar[0].isoformat() if calendar else None
    return [list(e) for e in list(prior) + list(new) if cutoff is None or str(e[1]) >= cutoff]


def with_history(state: Mapping[str, Any], history: Sequence) -> dict:
    """``state`` with the engine's history under KEY (a copy; the input is not changed)."""
    out = dict(state)
    out[KEY] = [list(e) for e in history]
    return out
