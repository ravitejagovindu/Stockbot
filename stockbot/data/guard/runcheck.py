"""What a backtest-type run checks about the database before and after it (db-guard R1 and R4).

``snapshot(path, full_hash)`` is the one fingerprint: file size, mtime_ns, the size of the ``-wal`` side file, (long steps) the sha256 of the file bytes, and the guard record of the tables the run
reads: correction counter, whether a window is open, the sealed-through date of each DATED table, and for each INSERT_ONLY table row count, max id and a sha256 over its rows (design D2).
``differences`` compares two snapshots; any difference marks the run INVALID (``RunInvalid``: a SystemExit with exit code 3 and a clear message).

Long steps (research, baseline) use ``full_hash=True``. Short steps (gates, benchmark, validate_family, signal counts) use ``full_hash=False`` and say so in their output: they verify size, mtime_ns,
-wal size, correction counter, sealed dates and the table digests instead of hashing 3.4 GB twice (decision D3).

The ``-shm`` file is deliberately NOT part of the check: every read-only connection to a WAL database updates it. The ``-wal`` file is checked by size because a non-empty one means the main file
alone does not show the whole database (a later writer would checkpoint it into the main file and change its bytes).
"""
from __future__ import annotations

import functools
import hashlib
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Optional, Sequence

from stockbot.data.guard import core
from stockbot.data.guard.registry import BACKTEST_READS, DATED, INSERT_ONLY, RULES, backtest_reads

EXIT_INVALID = 3


class RunInvalid(SystemExit):
    def __init__(self, label: str, diffs: Sequence[str]):
        self.diffs = list(diffs)
        super().__init__(EXIT_INVALID)
        self.message = f"RUN INVALID ({label}): the database changed while the run was using it: " + "; ".join(self.diffs)
        print(self.message, file=sys.stderr, flush=True)


def sha256_file(path, chunk: int = 8 * 1024 * 1024) -> str:
    d = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            d.update(block)
    return d.hexdigest()


def _feed(h, row) -> None:
    for v in row:
        if isinstance(v, (bytes, bytearray)):
            h.update(b"b%d:" % len(v))
            h.update(v)
        else:
            h.update(repr(v).encode("utf-8", "surrogatepass"))
        h.update(b"\x1f")
    h.update(b"\n")


def table_digest(con, table: str) -> dict:
    """row count, max rowid and sha256 over every column of every row (ordered by rowid) of ``table``."""
    h, n = hashlib.sha256(), 0
    for row in con.execute(f'SELECT * FROM "{table}" ORDER BY rowid'):
        _feed(h, row)
        n += 1
    mx = con.execute(f'SELECT max(rowid) FROM "{table}"').fetchone()[0]
    return {"row_count": n, "max_id": mx, "sha256": h.hexdigest()}


def guard_record(con, tables: Optional[Iterable[str]] = None) -> dict:
    """The guard state of the tables a run reads (a table missing from this database is left out)."""
    tables = backtest_reads() if tables is None else tables
    have = set(core.tables_in(con))
    out: dict = {"installed": core.installed(con)}
    if out["installed"]:
        w = core.window_state(con)
        out.update(correction_counter=w["corrections"], window_open=w["open"])
    else:
        out.update(correction_counter=None, window_open=None)
    tabs = {}
    for t in tables:
        if t not in have:
            continue
        r = RULES.get(t)
        row: dict = {"class": r.cls if r else None}
        if r is not None and r.cls == DATED:
            row["sealed_through"] = core.current_seal(con, t) if out["installed"] else None
        elif r is not None and r.cls == INSERT_ONLY:
            row.update(table_digest(con, t))
        tabs[t] = row
    out["tables"] = tabs
    return out


def _ro(path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{Path(path).resolve().as_posix()}?mode=ro", uri=True, timeout=60)
    con.execute("PRAGMA query_only=ON")
    return con


def snapshot(path, *, full_hash: bool, tables: Optional[Iterable[str]] = None) -> dict:
    """File and guard fingerprint of the database at ``path`` (read-only; never writes)."""
    p = Path(path)
    st = p.stat()
    wal = Path(str(p) + "-wal")
    con = _ro(p)
    try:
        rec = guard_record(con, tables)
    finally:
        con.close()
    return {"path": str(p), "size": st.st_size, "mtime_ns": st.st_mtime_ns, "mtime_iso": datetime.fromtimestamp(st.st_mtime).isoformat(), "wal_bytes": wal.stat().st_size if wal.exists() else 0,
            "sha256": sha256_file(p) if full_hash else None, "guard": rec}


def differences(before: dict, after: dict) -> list:
    diffs = []
    for k in ("size", "mtime_ns", "wal_bytes"):
        if before.get(k) != after.get(k):
            diffs.append(f"{k} {before.get(k)} -> {after.get(k)}")
    if before.get("sha256") != after.get("sha256"):
        diffs.append(f"sha256 {before.get('sha256')} -> {after.get('sha256')}")
    bg, ag = before.get("guard") or {}, after.get("guard") or {}
    for k in ("installed", "correction_counter", "window_open"):
        if bg.get(k) != ag.get(k):
            diffs.append(f"guard {k} {bg.get(k)} -> {ag.get(k)}")
    for t in sorted(set(bg.get("tables", {})) | set(ag.get("tables", {}))):
        if bg.get("tables", {}).get(t) != ag.get("tables", {}).get(t):
            diffs.append(f"guard table {t}: {bg.get('tables', {}).get(t)} -> {ag.get('tables', {}).get(t)}")
    return diffs


def what_was_checked(full_hash: bool) -> str:
    return ("full file sha256, size, mtime_ns, -wal size, correction counter, sealed dates and table digests" if full_hash
            else "size, mtime_ns, -wal size, correction counter, sealed dates and table digests (short step: the file bytes are not hashed)")


def verdict(before: dict, after: dict, label: str, *, out=None) -> int:
    """0 when nothing changed (prints what was verified); 3 and a clear message when anything changed."""
    out = out or print
    before, after = before or {}, after or {}
    diffs = differences(before, after)
    full = before.get("sha256") is not None
    if diffs:
        out(f"RUN INVALID ({label}): the database changed while the run was using it: " + "; ".join(diffs))
        return EXIT_INVALID
    g = after.get("guard") or {}
    out(f"database check ({label}): unchanged; verified {what_was_checked(full)}; guard installed={g.get('installed')}, correction counter={g.get('correction_counter')}")
    return 0


def manifest_block(before: dict, after: dict) -> dict:
    """What a run manifest records (R4): the file hashes (long steps), size/mtime, and per read table the sealed date or digest, with the correction counter, before and after."""
    return {"verified": what_was_checked(before.get("sha256") is not None), "unchanged": not differences(before, after),
            "file_sha256_before": before.get("sha256"), "file_sha256_after": after.get("sha256"), "wal_bytes_before": before.get("wal_bytes"), "wal_bytes_after": after.get("wal_bytes"),
            "guard_before": before.get("guard"), "guard_after": after.get("guard")}


def _lake_arg(argv: Sequence[str]) -> Optional[str]:
    for i, a in enumerate(argv):
        if a == "--lake" and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith("--lake="):
            return a.split("=", 1)[1]
    return None


def short_step(label: str, *, full_hash: bool = False) -> Callable:
    """Decorator for a script ``main(argv=None) -> int``: snapshot the database (``--lake`` or the default lake) before and after; a difference makes the exit code 3 (INVALID)."""
    def deco(main: Callable) -> Callable:
        @functools.wraps(main)
        def wrapped(argv=None) -> int:
            args = list(sys.argv[1:] if argv is None else argv)
            if any(a in ("-h", "--help") for a in args):
                return main(argv)
            from stockbot.config.paths import lake_path
            p = Path(_lake_arg(args) or lake_path())
            if not p.exists():
                return main(argv)
            from stockbot.data.guard import runlock
            with runlock.run_lock(p, label):                    # the daily data job does not write while this step runs (and the step does not start while the job writes)
                before = snapshot(p, full_hash=full_hash)
                rc = main(argv)
                after = snapshot(p, full_hash=full_hash)
            v = verdict(before, after, label)
            return rc if v == 0 else v
        return wrapped
    return deco
