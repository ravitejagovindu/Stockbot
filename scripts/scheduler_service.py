"""The StockBot scheduler service: a small always-running Python process that replaces the Windows Task Scheduler for the daily job. Start it in a PowerShell window in the main folder:

  py -3 scripts\\scheduler_service.py

What it does (times IST, Asia/Kolkata; details and roll-back in docs/shared/daily-update/SERVICE.md):
  * single instance: ``<locks>\\scheduler_service.pid`` holds the pid; a live pid refuses the start, a dead pid is replaced. The file is NOT named ``*.lock`` on purpose: every ``*.lock`` in that folder is read
    by the run-lock code, and this is not a run lock on finsight.db;
  * on start: ``daily_data_update.py --catch-up-only`` once; and if the start is between 19:30 and 23:30 the day's job is attempted at once (a missed 19:30; the job is idempotent);
  * 19:30 every day: ``daily_job.py --scheduled`` (data step, then the momentum_calm paper step), one subprocess at a time, with the retry rule in ``decide`` below;
  * 08:30 every day: ``daily_data_update.py --catch-up-only`` (what the Windows "StockBot Daily Data Recheck" task does; no retry loop);
  * log: ``<StockBotData>\\logs\\scheduler_service.log`` (rotating); a toast (winotify, if installed) when retrying stops without success.
It never edits data itself: every action is a subprocess of an existing script. Ctrl+C waits for a running job to finish (the job is started in its own process group so the Ctrl+C does not reach it)."""
from __future__ import annotations

import argparse
import json
import logging
import os
import socket
import subprocess
import sys
import threading
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Callable, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DATA_ROOT = Path(os.environ.get("STOCKBOT_DATA_ROOT") or r"F:\Projects\Ravi\StockBotData")
RUN_AT = time(19, 30)                    # first attempt of the day
LAST_ATTEMPT = time(23, 30)              # no attempt after this (19:30 + 12 x 20 minutes)
LATE_LIMIT = time(23, 45)                # the data job itself attempts today's date only until here; a missed 19:30 is never run after it
RETRY_MINUTES = 20
CATCH_UP_AT = time(8, 30)
TZ = "Asia/Kolkata"
log = logging.getLogger("scheduler_service")

Runner = Callable[[list], int]


# ------------------------------------------------------------------------------------------------------------------------------ the retry rule (pure)
@dataclass(frozen=True)
class Decision:
    action: str                          # "done" | "retry" | "stop"
    next_at: Optional[datetime] = None
    alert: bool = False
    reason: str = ""


def decide(exit_code: int, now: datetime) -> Decision:
    """What to do after an attempt of ``daily_job.py --scheduled`` that ended with ``exit_code`` at ``now`` (IST wall clock).
      0  done for the day: no further attempt today.
      5  stale lock: needs the owner; retrying changes nothing: stop, alert.
      3  NSE file not published yet        } retry in 20 minutes, none after 23:30. On a Saturday or Sunday exit 3 is
      4  a lock is held                    } the normal "no session" answer (special weekend sessions are rare; the
      1  a day failed                      } 08:30 catch-up checks the date again): stop, no alert.
      2  the paper step refused (lake not sealed through the date, a mode / freshness refusal): retry like 3. A market holiday does NOT reach 2: on a holiday the data step ends with 3
         (today's file is PENDING) before the paper step is called, so 2 only appears after the data step succeeded.
      any other code: treated like 1 (retry)."""
    if exit_code == 0:
        return Decision("done", reason="done for the day")
    if exit_code == 5:
        return Decision("stop", alert=True, reason="stale lock: needs the owner, not retried")
    if exit_code == 3 and now.weekday() >= 5:
        return Decision("stop", reason="no NSE file on a weekend: not retried (the 08:30 catch-up checks it again)")
    nxt = now + timedelta(minutes=RETRY_MINUTES)
    if nxt.date() != now.date() or nxt.time() > LAST_ATTEMPT:
        return Decision("stop", alert=True, reason=f"exit {exit_code} and no attempt left today (last attempt {LAST_ATTEMPT:%H:%M})")
    return Decision("retry", next_at=nxt, reason=f"exit {exit_code}")


def late_start_attempt_due(now: datetime) -> bool:
    """A start after 19:30 and up to 23:30 attempts the day's job once at once (a missed 19:30); before 19:30 or after 23:30 it does not (after 23:45 a missed day is never run late)."""
    return RUN_AT <= now.time() <= LAST_ATTEMPT


# ------------------------------------------------------------------------------------------------------------------------------ single instance
class AlreadyRunning(RuntimeError):
    pass


def take_instance_file(path: Path, pid: int, alive: Callable[[int], bool]) -> None:
    """Create ``path`` holding this pid. A live pid in an existing file refuses (AlreadyRunning); a dead or unreadable one is replaced."""
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps({"kind": "scheduler_service", "pid": pid, "host": socket.gethostname(), "started_at": datetime.now().isoformat(timespec="seconds")})
    for _ in range(2):
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                old = int(json.loads(path.read_text(encoding="utf-8"))["pid"])
            except Exception:  # noqa: BLE001 - unreadable: treated as dead, replaced
                old = 0
            if old and alive(old):
                raise AlreadyRunning(f"another scheduler_service is running (pid {old}, file {path})")
            log.info("replacing the instance file of dead pid %s", old)
            path.unlink()
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
        return
    raise AlreadyRunning(f"could not take {path}")


def release_instance_file(path: Path, pid: int) -> None:
    try:
        if int(json.loads(path.read_text(encoding="utf-8"))["pid"]) == pid:
            path.unlink()
    except Exception:  # noqa: BLE001
        pass


# ------------------------------------------------------------------------------------------------------------------------------ the service
def subprocess_runner(argv: list) -> int:
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)          # Ctrl+C in the console must not reach a running job
    return subprocess.call(argv, cwd=str(ROOT), creationflags=flags)


def toast(title: str, msg: str) -> None:
    try:
        from winotify import Notification, audio
        t = Notification(app_id="StockBot scheduler", title=title, msg=msg[:200], duration="long")
        t.set_audio(audio.Default, loop=False)
        t.show()
    except Exception:  # noqa: BLE001 - never crash because a toast is not possible
        pass


class Service:
    def __init__(self, runner: Runner = subprocess_runner, now_fn: Callable[[], datetime] = datetime.now, notify: Callable[[str, str], None] = toast, python: str = sys.executable):
        self.runner, self.now_fn, self.notify, self.python = runner, now_fn, notify, python
        self._busy = threading.Lock()                  # at most one job subprocess at a time
        self.done_on: Optional[date] = None
        self.scheduler = None

    # -- the two subprocesses
    def _argv(self, script: str, *args: str) -> list:
        return [self.python, str(ROOT / "scripts" / script), *args]

    def catch_up(self, why: str) -> Optional[int]:
        if not self._busy.acquire(blocking=False):
            log.info("catch-up (%s) skipped: a job is running", why)
            return None
        try:
            log.info("catch-up (%s): daily_data_update.py --catch-up-only", why)
            rc = self.runner(self._argv("daily_data_update.py", "--catch-up-only"))
            log.info("catch-up (%s) exit %s", why, rc)
            return rc
        finally:
            self._busy.release()

    def attempt(self, why: str = "19:30") -> Optional[Decision]:
        now = self.now_fn()
        if now.time() > LATE_LIMIT:
            log.info("attempt (%s) skipped: %s is after %s; the next start's catch-up fills the gap", why, f"{now:%H:%M}", f"{LATE_LIMIT:%H:%M}")
            return None
        if self.done_on == now.date():
            log.info("attempt (%s) skipped: today is already done", why)
            return None
        if not self._busy.acquire(blocking=False):
            log.info("attempt (%s) skipped: a job is running", why)
            return None
        try:
            log.info("attempt (%s): daily_job.py --scheduled", why)
            rc = self.runner(self._argv("daily_job.py", "--scheduled"))
        finally:
            self._busy.release()
        d = decide(rc, self.now_fn())
        log.info("attempt (%s) exit %s -> %s%s", why, rc, d.action, f" (next attempt {d.next_at:%H:%M})" if d.next_at else f" ({d.reason})")
        if d.action == "done":
            self.done_on = now.date()
        elif d.action == "retry":
            self._schedule_retry(d.next_at)
        elif d.alert:
            log.error("ALERT: %s", d.reason)
            self.notify("StockBot daily job stopped", f"{now.date()}: exit {rc}: {d.reason}")
        return d

    def _schedule_retry(self, at: datetime) -> None:
        if self.scheduler is None:
            return
        from apscheduler.triggers.date import DateTrigger
        self.scheduler.add_job(self.attempt, DateTrigger(run_date=at, timezone=TZ), kwargs={"why": f"retry {at:%H:%M}"}, id="retry", replace_existing=True, misfire_grace_time=300)

    def start_actions(self) -> None:
        log.info("service start (pid %s)", os.getpid())
        self.catch_up("start")
        now = self.now_fn()
        if late_start_attempt_due(now):
            log.info("started at %s, after the 19:30 slot: attempting the day's job now", f"{now:%H:%M}")
            self.attempt("late start")
        else:
            log.info("started at %s: no attempt due now (next 19:30)", f"{now:%H:%M}")

    def run(self) -> None:
        from apscheduler.schedulers.blocking import BlockingScheduler
        from apscheduler.triggers.cron import CronTrigger
        self.scheduler = BlockingScheduler(timezone=TZ)
        grace = int((datetime.combine(date.today(), LATE_LIMIT) - datetime.combine(date.today(), RUN_AT)).total_seconds())
        self.scheduler.add_job(self.attempt, CronTrigger(hour=RUN_AT.hour, minute=RUN_AT.minute, timezone=TZ), id="daily_19_30", misfire_grace_time=grace, coalesce=True, max_instances=1)
        self.scheduler.add_job(self.catch_up, CronTrigger(hour=CATCH_UP_AT.hour, minute=CATCH_UP_AT.minute, timezone=TZ), kwargs={"why": "08:30"}, id="catch_up_08_30", misfire_grace_time=3600, coalesce=True, max_instances=1)
        self.start_actions()
        try:
            self.scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            log.info("stop requested: waiting for a running job to finish")
        finally:
            if self.scheduler.running:
                self.scheduler.shutdown(wait=True)
            log.info("service stopped")


def setup_logging(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    h = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    h.setFormatter(fmt)
    c = logging.StreamHandler()
    c.setFormatter(fmt)
    log.setLevel(logging.INFO)
    log.addHandler(h)
    log.addHandler(c)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="StockBot scheduler service (19:30 daily job with retries, 08:30 catch-up).")
    ap.add_argument("--data-root", default=str(DATA_ROOT), help="folder holding locks\\ and logs\\ (default the StockBotData folder)")
    a = ap.parse_args(argv)
    root = Path(a.data_root)
    setup_logging(root / "logs" / "scheduler_service.log")
    from stockbot.data.guard.runlock import pid_alive
    inst = root / "locks" / "scheduler_service.pid"
    try:
        take_instance_file(inst, os.getpid(), pid_alive)
    except AlreadyRunning as exc:
        log.error("%s", exc)
        print(f"REFUSED: {exc}")
        return 2
    try:
        Service().run()
    finally:
        release_instance_file(inst, os.getpid())
    return 0


if __name__ == "__main__":
    sys.exit(main())
