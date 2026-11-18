"""Run locks: a backtest or validation run and the daily data job never overlap on the same database file.

Why: a run records size, mtime_ns and the guard state of ``finsight.db`` before and after it and is INVALID if anything changed (``runcheck``). The daily job changes the file by design, so the two must not
run at the same time. Nothing here touches the database.

Where (``lock_dir()``): ``STOCKBOT_LOCK_DIR`` if set, else ``F:\\Projects\\Ravi\\StockBotData\\locks`` (``STOCKBOT_DATA_ROOT\\locks`` if that variable is set).
  run_<pid>_<YYYYmmddHHMMSS>.lock   one per backtest / validation run (several runs may read together)
  daily_update.lock                 the daily data job (one at a time)
Each lock is a small JSON file: kind, pid, host, started_at (UTC ISO), the database file it concerns (resolved, lower case), a label.

Rules (the lock only concerns locks that name the SAME database file):
  * the daily job refuses to write while a run lock exists, and exits (exit code 4, "LOCKED") so the scheduler retries;
  * a run refuses to start while the daily job holds its lock (``RunRefused``, exit code 4);
  * STALE = older than 12 hours AND no live process with that pid. A stale lock is REPORTED and the caller STOPS (exit code 5); it is never deleted silently: the message names the file and the
    command that removes it. A lock whose process is gone but is younger than 12 hours still blocks (the job may have died mid-write; waiting is the safe side), and is reported as "process gone".
"""
from __future__ import annotations

import atexit
import json
import os
import socket
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

STALE_HOURS = 12.0
DAILY_NAME = "daily_update.lock"
EXIT_LOCKED = 4
EXIT_STALE = 5
DEFAULT_DATA_ROOT = r"F:\Projects\Ravi\StockBotData"


class LockRefused(SystemExit):
    """Raised (as SystemExit with a code) when a lock stops the caller. ``code`` is EXIT_LOCKED or EXIT_STALE; ``message`` says why."""

    def __init__(self, code: int, message: str):
        super().__init__(code)
        self.message = message
        print(message, file=sys.stderr, flush=True)


class RunRefused(LockRefused):
    pass


def data_root() -> Path:
    return Path(os.environ.get("STOCKBOT_DATA_ROOT") or DEFAULT_DATA_ROOT)


def lock_dir() -> Path:
    return Path(os.environ.get("STOCKBOT_LOCK_DIR") or data_root() / "locks")


def db_key(path) -> str:
    return str(Path(path).resolve()).lower()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.OpenProcess.restype = wintypes.HANDLE
        h = k.OpenProcess(0x1000, False, pid)             # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        try:
            code = wintypes.DWORD()
            ok = k.GetExitCodeProcess(h, ctypes.byref(code))
            return bool(ok) and code.value == 259         # STILL_ACTIVE
        finally:
            k.CloseHandle(h)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@dataclass
class LockInfo:
    path: Path
    kind: str
    pid: int
    host: str
    started_at: datetime
    db: str
    label: str
    age_hours: float
    alive: bool

    @property
    def stale(self) -> bool:
        return self.age_hours > STALE_HOURS and not self.alive

    def describe(self) -> str:
        state = "STALE" if self.stale else ("live process" if self.alive else "process gone")
        return f"{self.path} ({self.kind}, pid {self.pid}, {self.label}, started {self.started_at.isoformat(timespec='seconds')}, {self.age_hours:.1f} h old, {state})"


def _read(p: Path) -> Optional[LockInfo]:
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        started = datetime.fromisoformat(d["started_at"])
        pid = int(d["pid"])
        alive = pid_alive(pid) and d.get("host") == socket.gethostname()
        return LockInfo(p, d["kind"], pid, d.get("host", ""), started, d.get("db", ""), d.get("label", ""), (_now() - started).total_seconds() / 3600.0, alive)
    except Exception:  # noqa: BLE001  an unreadable lock file is treated as a very old lock with a dead process: reported, never deleted
        return LockInfo(p, "unreadable", 0, "", datetime.fromtimestamp(p.stat().st_mtime, timezone.utc), "*", "unreadable lock file",
                        (_now().timestamp() - p.stat().st_mtime) / 3600.0, False)


def locks_for(db, kind: Optional[str] = None, directory: Optional[Path] = None) -> list:
    """The locks in the lock directory that concern the database file ``db`` (an unreadable lock concerns every database)."""
    d = Path(directory) if directory else lock_dir()
    if not d.exists():
        return []
    key = db_key(db)
    out = []
    for p in sorted(d.glob("*.lock")):
        info = _read(p)
        if info is not None and info.db in (key, "*") and (kind is None or info.kind == kind or info.kind == "unreadable"):
            out.append(info)
    return out


def _write(directory: Path, name: str, kind: str, db, label: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    p = directory / name
    body = {"kind": kind, "pid": os.getpid(), "host": socket.gethostname(), "started_at": _now().isoformat(timespec="seconds"), "db": db_key(db), "label": label, "argv": sys.argv[:6]}
    with open(p, "x", encoding="utf-8") as f:                     # 'x': never replaces another process's lock
        json.dump(body, f)
    return p


def release(path: Optional[Path]) -> None:
    try:
        if path is not None:
            Path(path).unlink()
    except FileNotFoundError:
        pass


def _removal_hint(info: LockInfo) -> str:
    return f'To remove it after checking that nothing is running: Remove-Item -LiteralPath "{info.path}"'


# ------------------------------------------------------------------------------------------------------------------------------ runs
def acquire_run(db, label: str, directory: Optional[Path] = None) -> Path:
    """A backtest / validation run takes its lock. Refuses (``RunRefused``) while the daily job holds its lock on the same database, live or stale."""
    d = Path(directory) if directory else lock_dir()
    for info in locks_for(db, kind="daily", directory=d) + locks_for(db, kind="unreadable", directory=d):
        what = "the daily data job is writing this database" if info.kind == "daily" else "an unreadable lock file"
        if info.stale:
            raise RunRefused(EXIT_STALE, f"RUN NOT STARTED: STALE lock ({what}): {info.describe()}. Not deleted. {_removal_hint(info)}")
        raise RunRefused(EXIT_LOCKED, f"RUN NOT STARTED: {what}: {info.describe()}. Start the run again when the daily job has finished.")
    stamp = _now().strftime("%Y%m%d%H%M%S")
    return _write(d, f"run_{os.getpid()}_{stamp}.lock", "run", db, label)


@contextmanager
def run_lock(db, label: str, directory: Optional[Path] = None):
    p = acquire_run(db, label, directory)
    try:
        yield p
    finally:
        release(p)


_HELD: dict = {}


def hold_for_process(db, label: str) -> Optional[Path]:
    """Take the run lock once per (database, process) and keep it until the process exits (for scripts that fingerprint the file first and finish much later). Idempotent."""
    key = (str(lock_dir()), db_key(db))
    if key in _HELD:
        return _HELD[key]
    p = acquire_run(db, label)
    _HELD[key] = p
    atexit.register(release, p)
    return p


# ------------------------------------------------------------------------------------------------------------------------------ daily job
def acquire_daily(db, directory: Optional[Path] = None) -> Path:
    """The daily job takes its lock. Refuses while a run lock (or another daily lock) concerns the same database: LOCKED (exit 4) when it is live or recent, STALE (exit 5) when it is stale."""
    d = Path(directory) if directory else lock_dir()
    others = locks_for(db, directory=d)
    for info in others:
        if info.stale:
            raise LockRefused(EXIT_STALE, f"DAILY JOB STOPPED: STALE lock: {info.describe()}. Not deleted. {_removal_hint(info)}")
    if others:
        raise LockRefused(EXIT_LOCKED, "DAILY JOB DID NOT WRITE: locked by " + "; ".join(i.describe() for i in others) + ". The scheduler retries.")
    try:
        return _write(d, DAILY_NAME, "daily", db, "daily_data_update")
    except FileExistsError:                                          # another database's daily lock (different db key): the file name is shared, so refuse
        info = _read(d / DAILY_NAME)
        raise LockRefused(EXIT_LOCKED, f"DAILY JOB DID NOT WRITE: {DAILY_NAME} exists: {info.describe() if info else d / DAILY_NAME}")
