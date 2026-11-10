"""Resolve exit-policy ids to policy objects, and build the ``policies`` mapping a run needs from the strategy specs.

Library ids encode their parameters, so a strategy's config_hash covers them: ``fixed_hold_<N>`` (N a positive integer, no leading zero) and ``trailing_pct_<P>``
(P an integer 1 to 99, no leading zero). One behaviour has exactly one spelling. A strategy-owned policy (defined inside its own folder) is passed to
``policies_for`` as ``extra``; its id must not start with a library prefix. Anything unknown, malformed or claimed twice fails loudly. Standard library only.
"""
from __future__ import annotations

import re
from typing import Iterable, Mapping, Optional

from stockbot.engine.exit_policies.fixed_hold import FixedHold
from stockbot.engine.exit_policies.trailing_stop import TrailingStop
from stockbot.engine.exit_policy import ExitPolicy

LIBRARY_FORMATS = ("fixed_hold_<N> (N a positive integer without leading zeros)", "trailing_pct_<P> (P an integer 1 to 99 without leading zeros)")
_FIXED = re.compile(r"fixed_hold_([1-9][0-9]*)")
_TRAIL = re.compile(r"trailing_pct_([1-9][0-9]?)")
_LIBRARY_PREFIX = re.compile(r"(fixed_hold|trailing_pct)_")


class UnknownExitPolicyError(ValueError):
    """The id is not a library id (unknown or malformed)."""


class ExitPolicyRegistrationError(ValueError):
    """A strategy-owned policy is invalid or two sources claim one id."""


def resolve(policy_id) -> ExitPolicy:
    """The library policy for ``policy_id``; raises UnknownExitPolicyError for anything else (no stripping, no case folding, no leading zeros)."""
    if isinstance(policy_id, str):
        m = _FIXED.fullmatch(policy_id)
        if m:
            return FixedHold(int(m.group(1)))
        m = _TRAIL.fullmatch(policy_id)
        if m:
            return TrailingStop(int(m.group(1)))
    raise UnknownExitPolicyError(f"unknown or malformed exit policy id {policy_id!r}; library ids are {LIBRARY_FORMATS[0]} and {LIBRARY_FORMATS[1]}; "
                                 "a strategy-owned policy must be registered explicitly (policies_for(..., extra=...))")


def _check_extra(extra: Iterable) -> dict:
    out: dict = {}
    for p in extra:
        if not isinstance(p, ExitPolicy):
            raise ExitPolicyRegistrationError(f"strategy-owned exit policy {p!r} does not implement the ExitPolicy interface")
        pid = p.id
        if not isinstance(pid, str) or not pid.strip():
            raise ExitPolicyRegistrationError(f"strategy-owned exit policy {p!r} has an empty or non-string id")
        if _LIBRARY_PREFIX.match(pid):
            raise ExitPolicyRegistrationError(f"strategy-owned exit policy id {pid!r} starts with a library prefix (fixed_hold_ / trailing_pct_); library ids belong to the library")
        if pid in out:
            raise ExitPolicyRegistrationError(f"exit policy id {pid!r} is claimed by two strategy-owned policies")
        out[pid] = p
    return out


def policies_for(specs: Iterable, extra: Optional[Iterable] = None) -> Mapping[str, ExitPolicy]:
    """The ``policies`` mapping (id -> policy) for strategy specs: library ids through ``resolve``, strategy-owned ones from ``extra`` (policy objects).

    Keys equal ``policy.id`` (the engine looks policies up by ``spec.exit_policy`` and by ``Position.exit_policy_id``). Only the ids the specs use are included.
    Open positions of a strategy that is no longer in ``specs`` are NOT covered: ``decide`` then raises EngineInputError for them (a loud failure, by design).
    """
    owned = _check_extra(extra or ())
    out: dict = {}
    for spec in specs:
        pid = spec.exit_policy
        if pid in out:
            continue
        out[pid] = owned[pid] if pid in owned else resolve(pid)
    return out
