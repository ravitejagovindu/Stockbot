"""Symbol links: a renamed stock is ONE symbol under its LATEST name in the as-of views (data layer only; the lake is never modified, the link is applied on read).

``data/reference/symbol_links.csv`` (built by ``scripts/build_symbol_links.py`` from ``isin_symbol_map.csv`` and the lake) lists the accepted renames: old_symbol -> new_symbol with their
``latest_symbol`` (chains A -> B -> C resolve to C). ``Links.members(symbol)`` is the chain, oldest first; ``Links.resolve(symbol)`` is the latest name (the symbol itself when it is not linked).

The switch is ``data.symbol_links_enabled`` in shared.yaml. ``active()`` returns the Links in force, or None when the switch is off (every view then behaves exactly as before).
Tests use ``override(...)`` to switch the feature on or off, or to inject a link table for a fixture lake, without touching any file.
"""
from __future__ import annotations

import csv
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional

from stockbot.config.paths import repo_root

LINKS_FILE = "symbol_links.csv"


class Links:
    """Immutable link table. ``pairs`` = [(old_symbol, new_symbol), ...]; each old symbol has one successor, each new symbol one predecessor."""

    def __init__(self, pairs: Iterable):
        nxt: dict = {}
        prv: dict = {}
        for old, new in pairs:
            if old in nxt or new in prv or old == new:
                raise ValueError(f"ambiguous or self link: {old} -> {new}")
            nxt[old], prv[new] = new, old
        latest: dict = {}
        chains: dict = {}
        for s in set(nxt) | set(prv):
            head, walked = s, {s}
            while head in prv:
                head = prv[head]
                if head in walked:
                    raise ValueError(f"link cycle at {head}")
                walked.add(head)
            chain, cur = [head], head
            while cur in nxt:
                cur = nxt[cur]
                if cur in chain:
                    raise ValueError(f"link cycle at {cur}")
                chain.append(cur)
            for m in chain:
                latest[m] = chain[-1]
                chains[m] = tuple(chain)
        self._latest, self._chains = latest, chains
        self.pairs = tuple(sorted(set((o, n) for o, n in pairs)))

    def resolve(self, symbol: str) -> str:
        return self._latest.get(symbol, symbol)

    def members(self, symbol: str) -> tuple:
        """The chain containing ``symbol`` (oldest first, latest last); () when the symbol is not linked."""
        return self._chains.get(symbol, ())

    def __bool__(self) -> bool:
        return bool(self._latest)

    def linked_symbols(self) -> frozenset:
        return frozenset(self._latest)


@lru_cache(maxsize=1)
def _from_file() -> Links:
    p = repo_root() / "data" / "reference" / LINKS_FILE
    if not p.exists():
        return Links(())
    with open(p, newline="", encoding="utf-8") as f:
        return Links([(r["old_symbol"].strip(), r["new_symbol"].strip()) for r in csv.DictReader(f) if r.get("old_symbol")])


@lru_cache(maxsize=1)
def _config_enabled() -> bool:
    from stockbot.config.shared import load_shared_config
    return bool(load_shared_config().data.symbol_links_enabled)


_OVERRIDE: dict = {}


def enabled() -> bool:
    return bool(_OVERRIDE["enabled"]) if "enabled" in _OVERRIDE else _config_enabled()


def active() -> Optional[Links]:
    """The Links in force, or None when the switch is off or the table is empty."""
    if not enabled():
        return None
    links = _OVERRIDE["links"] if "links" in _OVERRIDE else _from_file()
    return links if links else None


@contextmanager
def override(*, enabled: Optional[bool] = None, links: Optional[Links] = None):
    """Test helper: force the switch and/or the link table inside the block (nothing on disk changes)."""
    saved = dict(_OVERRIDE)
    try:
        if enabled is not None:
            _OVERRIDE["enabled"] = enabled
        if links is not None:
            _OVERRIDE["links"] = links
        yield
    finally:
        _OVERRIDE.clear()
        _OVERRIDE.update(saved)


def resolve(symbol: str) -> str:
    links = active()
    return links.resolve(symbol) if links is not None else symbol


def members(symbol: str) -> tuple:
    links = active()
    return links.members(symbol) if links is not None else ()
