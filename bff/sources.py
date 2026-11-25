"""Read-only readers for the BFF. Nothing here writes, locks or creates a file.

* Every SQLite connection is opened with a read-only URI (``file:...?mode=ro``) and ``PRAGMA query_only=ON``, with a short busy timeout, used for one read and closed at once
  (no connection is held between requests). A failed read is retried once; the second failure raises ``SourceError`` and the API answers 503 NOT_READY: never a partial result.
* The lock files are neither read nor written. The daily job's calendar journal (``daily\\calendar.csv``) is read as plain text.
"""
from __future__ import annotations

import csv
import json
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple, TypeVar

from bff import config as _config  # noqa: F401  (puts the repo root on sys.path so ``stockbot`` imports)
from stockbot.engine.types import Decisions

T = TypeVar("T")
RETRY_PAUSE_S = 0.3


class SourceError(RuntimeError):
    """A source cannot be read right now (missing, locked, not initialised). The API turns it into 503 NOT_READY."""


def ro_connect(path: Path, timeout: float = 3.0) -> sqlite3.Connection:
    """A read-only connection: URI ``mode=ro`` plus ``PRAGMA query_only=ON``. A write through it raises ``sqlite3.OperationalError``."""
    path = Path(path)
    if not path.exists():
        raise SourceError(f"database not found: {path.name}")
    con = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True, timeout=timeout)
    con.execute("PRAGMA query_only=ON")
    return con


def read_once_retry(path: Path, fn: Callable[[sqlite3.Connection], T], timeout: float = 3.0) -> T:
    """Open, read with ``fn``, close. One retry after a short pause; then ``SourceError``."""
    last: Optional[Exception] = None
    for attempt in (1, 2):
        try:
            with closing(ro_connect(path, timeout)) as con:
                return fn(con)
        except SourceError:
            raise
        except (sqlite3.Error, ValueError, KeyError, TypeError) as exc:
            last = exc
            if attempt == 1:
                time.sleep(RETRY_PAUSE_S)
    raise SourceError(f"{Path(path).name} could not be read: {type(last).__name__}")


# ------------------------------------------------------------------------------------------------------------------------------ state
@dataclass(frozen=True)
class StateData:
    initial_cash: float                 # rupees, from the journal's ``init`` row
    decisions: Tuple[Decisions, ...]    # one per processed session, oldest first


def read_state(path: Path, timeout: float = 3.0) -> StateData:
    """The ``init`` row and every ``decisions`` row of the journal in ``live_state.db``. No decisions row = not ready."""

    def go(con: sqlite3.Connection) -> StateData:
        rows = con.execute("select kind, payload from journal order by seq").fetchall()
        init = next((json.loads(p) for k, p in rows if k == "init"), None)
        if init is None:
            raise SourceError("the state database is not initialised")
        decisions = tuple(Decisions.from_json(p) for k, p in rows if k == "decisions")
        if not decisions:
            raise SourceError("no session has been processed yet")
        return StateData(float(init["cash"]), decisions)

    return read_once_retry(path, go, timeout)


def read_journal_version(path: Path) -> Tuple[int, int]:
    """(mtime_ns, size) of the state database file: the cache key. 0, 0 when it does not exist."""
    try:
        st = Path(path).stat()
        return st.st_mtime_ns, st.st_size
    except OSError:
        return 0, 0


# ------------------------------------------------------------------------------------------------------------------------------ tickets
def read_tickets(directory: Path, day: date) -> Optional[dict]:
    """state\\tickets\\tickets_<date>.json for the day, or None when there is no such file."""
    p = Path(directory) / f"tickets_{day.isoformat()}.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise SourceError(f"{p.name} could not be read: {type(exc).__name__}") from None


# ------------------------------------------------------------------------------------------------------------------------------ lake
NIFTY = "NIFTY50_INDEX"


@dataclass(frozen=True)
class LakeData:
    sealed_through: Optional[date]
    nifty: Dict[date, float]                       # close_raw of NIFTY50_INDEX by date, from the start date to the end date
    closes: Dict[Tuple[str, date], float]          # close_raw of the requested symbols
    calendar_tail: Tuple[date, ...]                # the last trading days of the Nifty series up to the end date (for the signal-day check), oldest first


def _d(v) -> date:
    return date.fromisoformat(str(v)[:10])


def read_sealed(path: Path, timeout: float = 3.0) -> Optional[date]:
    """The date ``market_data_lake`` is sealed through (``_guard_seal``), or None when the guard table is missing."""

    def go(con: sqlite3.Connection) -> Optional[date]:
        if con.execute("select 1 from sqlite_master where type='table' and name='_guard_seal'").fetchone() is None:
            return None
        r = con.execute("select sealed_through from _guard_seal where tbl='market_data_lake'").fetchone()
        return _d(r[0]) if r and r[0] else None

    return read_once_retry(path, go, timeout)


def read_lake(path: Path, start: date, end: date, symbols: Iterable[str], timeout: float = 3.0) -> LakeData:
    """Sealed-through date, the Nifty closes from ``start`` to ``end``, the closes of ``symbols`` over the same range, and the last Nifty trading days up to ``end``."""
    syms = sorted({s for s in symbols})

    def go(con: sqlite3.Connection) -> LakeData:
        sealed = None
        if con.execute("select 1 from sqlite_master where type='table' and name='_guard_seal'").fetchone() is not None:
            r = con.execute("select sealed_through from _guard_seal where tbl='market_data_lake'").fetchone()
            sealed = _d(r[0]) if r and r[0] else None
        nifty = {_d(r[0]): float(r[1]) for r in con.execute(
            "select trade_date, close_raw from market_data_lake where symbol=? and trade_date>=? and trade_date<=? order by trade_date",
            (NIFTY, start.isoformat(), end.isoformat()))}
        closes: Dict[Tuple[str, date], float] = {}
        for i in range(0, len(syms), 200):
            chunk = syms[i:i + 200]
            q = ",".join("?" * len(chunk))
            for sym, dte, c in con.execute(
                    f"select symbol, trade_date, close_raw from market_data_lake where symbol in ({q}) and trade_date>=? and trade_date<=?",
                    (*chunk, start.isoformat(), end.isoformat())):
                closes[(sym, _d(dte))] = float(c)
        tail = tuple(sorted(_d(r[0]) for r in con.execute(
            "select trade_date from market_data_lake where symbol=? and trade_date<=? order by trade_date desc limit 2", (NIFTY, end.isoformat()))))
        return LakeData(sealed, nifty, closes, tail)

    return read_once_retry(path, go, timeout)


# ------------------------------------------------------------------------------------------------------------------------------ the data job's calendar journal
def read_no_file_days(calendar_csv: Path) -> Set[date]:
    """Dates the daily data job recorded as having no file (holiday assumption) and that no later row shows as loaded. Plain text read; a missing file gives the empty set."""
    try:
        with open(calendar_csv, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    except OSError:
        return set()
    loaded: Set[date] = set()
    nofile: Set[date] = set()
    for r in rows:
        try:
            d = date.fromisoformat(r["date"])
        except (KeyError, ValueError):
            continue
        outcome = (r.get("outcome") or "").strip()
        if outcome in ("LOADED", "ALREADY_SEALED"):
            loaded.add(d)
        elif outcome in ("NO_FILE", "NO_FILE_FINAL"):
            nofile.add(d)
    return nofile - loaded


def read_last_session(path: Path, timeout: float = 3.0) -> Optional[date]:
    """The newest processed session date in the journal (``max(session)`` of the ``decisions`` rows), or None when there is none. A light read for /v1/health."""

    def go(con: sqlite3.Connection) -> Optional[date]:
        r = con.execute("select max(session) from journal where kind='decisions'").fetchone()
        return _d(r[0]) if r and r[0] else None

    return read_once_retry(path, go, timeout)


# ------------------------------------------------------------------------------------------------------------------------------ the scheduler service (for /v1/job)
MAX_LOG_BYTES = 2_000_000


def read_scheduler_log(log_file: Path) -> list:
    """The lines of ``scheduler_service.log`` and its rotated files (``.5`` oldest ... ``.1``, then the live file), oldest first. A file that cannot be read is skipped; none readable = ``SourceError``.
    Plain text reads only: nothing is written, locked or created."""
    log_file = Path(log_file)
    names = [log_file.with_name(f"{log_file.name}.{i}") for i in range(5, 0, -1)] + [log_file]
    lines: list = []
    readable = 0
    for p in names:
        try:
            with open(p, "rb") as f:
                data = f.read(MAX_LOG_BYTES + 1)
        except OSError:
            continue
        readable += 1
        lines.extend(data.decode("utf-8", errors="replace").splitlines())
    if readable == 0:
        raise SourceError("the scheduler log could not be read")
    return lines


def read_instance_file(locks_dir: Path) -> Optional[dict]:
    """The instance file locks/scheduler_service.pid (JSON with the service's pid and start time); None when it is missing or unreadable. It is not a run lock."""
    try:
        d = json.loads((Path(locks_dir) / "scheduler_service.pid").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def daily_lock_exists(locks_dir: Path) -> bool:
    """Whether the daily data job's lock file is present (existence only: the file is never opened or read)."""
    return (Path(locks_dir) / "daily_update.lock").exists()


def process_alive(pid: int) -> bool:
    """True when a process with this pid is running. Windows: OpenProcess + GetExitCodeProcess (never a signal, which would kill it)."""
    if pid <= 0:
        return False
    import os
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.OpenProcess.restype = wintypes.HANDLE
        h = k.OpenProcess(0x1000, False, pid)          # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        try:
            code = wintypes.DWORD()
            return bool(k.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == 259     # STILL_ACTIVE
        finally:
            k.CloseHandle(h)
    try:
        os.kill(pid, 0)                                 # POSIX only: signal 0 checks existence and sends nothing
    except OSError:
        return False
    return True
