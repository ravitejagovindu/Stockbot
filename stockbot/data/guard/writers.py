"""What an ingestion writer uses so it never tries to change a sealed or insert-only row (db-guard section 2.3 of the Part 1 report).

``refuse_if_sealed`` stops a writer BEFORE it deletes anything on a sealed day (the triggers would refuse anyway; this gives the message first and keeps delete-then-insert atomic).
``split_new`` divides rows into new ones (to insert), identical ones (nothing to do) and different ones (a change to an existing fact: NOT applied; the caller reports them and the owner uses
``scripts/guard.py correct``). Both take a ``fetch(sql) -> rows`` callable so they work with a SQLAlchemy session or a sqlite3 connection.
"""
from __future__ import annotations

from typing import Callable, Iterable, Optional, Sequence

from stockbot.data.guard.core import GuardError


class SealedError(GuardError):
    pass


def session_fetch(session) -> Callable:
    from sqlalchemy import text
    return lambda sql: session.execute(text(sql)).fetchall()


def sqlite_fetch(con) -> Callable:
    return lambda sql: con.execute(sql).fetchall()


def sealed_through(fetch: Callable, table: str) -> Optional[str]:
    """The sealed-through date of ``table`` (ISO), or None when the guard is not installed in this database."""
    if not fetch("SELECT name FROM sqlite_master WHERE type='table' AND name='_guard_seal'"):
        return None
    rows = fetch(f"SELECT sealed_through FROM _guard_seal WHERE tbl='{table}'")
    return rows[0][0] if rows else None


def refuse_if_sealed(fetch: Callable, table: str, day) -> None:
    s = sealed_through(fetch, table)
    d = day.isoformat() if hasattr(day, "isoformat") else str(day)[:10]
    if s is not None and d <= s:
        raise SealedError(f"{table} is sealed through {s}: {d} cannot be loaded or reloaded. A deliberate change needs: py -3 scripts/guard.py correct --reason TEXT -- FILE.sql")


def _norm(v):
    if hasattr(v, "isoformat"):
        return v.isoformat()[:10]
    if isinstance(v, float) and v == int(v):
        return float(v)
    return v


def split_new(fetch: Callable, table: str, rows: Iterable[dict], key_cols: Sequence[str], value_cols: Sequence[str]) -> tuple:
    """(new_rows, n_identical, different) where ``different`` is a list of (key, stored_values, offered_values) for rows whose key exists with other values."""
    cols = ", ".join(f'"{c}"' for c in list(key_cols) + list(value_cols))
    nk = len(key_cols)
    stored = {tuple(_norm(v) for v in r[:nk]): tuple(_norm(v) for v in r[nk:]) for r in fetch(f'SELECT {cols} FROM "{table}"')}
    new, same, diff = [], 0, []
    seen: set = set()
    for row in rows:
        k = tuple(_norm(row[c]) for c in key_cols)
        v = tuple(_norm(row.get(c)) for c in value_cols)
        if k in stored:
            if stored[k] == v:
                same += 1
            else:
                diff.append((k, stored[k], v))
        elif k not in seen:
            seen.add(k)
            new.append(row)
    return new, same, diff
