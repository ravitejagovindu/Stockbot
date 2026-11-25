"""The daily-job status for GET /v1/job: parse the scheduler service's log and turn it into the contract's answer. Pure: no file is opened here (``bff.sources`` reads the log, the pid file and the lock folder).

The log is written by ``scripts/scheduler_service.py``; the lines this module understands (everything else is ignored, so an unknown, garbled or half-written line is harmless):

    service start (pid 9100)
    attempt (19:30): daily_job.py --scheduled                    an attempt began
    attempt (retry 19:50) exit 3 -> retry (next attempt 20:10)   its result: done | retry | stop
    attempt (retry 23:11) exit 3 -> stop (<reason>)
    ALERT: <reason>                                              (ERROR level) follows a stop that needs the owner
    catch-up (08:30) exit 0                                      the 08:30 data catch-up
    service stopped

Timestamps in the log are the machine's local time, which is IST.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Dict, List, Optional, Sequence, Tuple

from bff import models as M

IST = timezone(timedelta(hours=5, minutes=30))
RUN_AT = time(19, 30)                      # the service's first attempt of the day (scripts/scheduler_service.py RUN_AT)
LAST_ATTEMPT = time(23, 30)                # no attempt after this (LAST_ATTEMPT there)
HISTORY_DAYS = 10
ATTEMPT_LIST = 20

_LINE = re.compile(r"^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2}),\d{3} (\w+) (.*)$")
_START = re.compile(r"^service start \(pid (\d+)\)")
_ATTEMPT_BEGIN = re.compile(r"^attempt \((.+?)\): daily_job\.py --scheduled$")
_ATTEMPT_RESULT = re.compile(r"^attempt \((.+?)\) exit (-?\d+) -> (done|retry|stop)(?: \(next attempt (\d{2}:\d{2})\))?(?: \((.*)\))?$")
_CATCHUP = re.compile(r"^catch-up \((.+?)\) exit (-?\d+)$")
_ALERT = re.compile(r"^ALERT: (.*)$")


@dataclass
class Attempt:
    at: datetime                           # when the result was logged (naive local time)
    why: str
    exit_code: int
    action: str                            # done | retry | stop
    next_hm: Optional[str] = None          # "20:10" for a retry
    reason: str = ""
    alert: bool = False
    alert_text: str = ""


@dataclass
class CatchUp:
    at: datetime
    exit_code: int


@dataclass
class Parsed:
    attempts: List[Attempt] = field(default_factory=list)
    catchups: List[CatchUp] = field(default_factory=list)
    open_attempt: Optional[datetime] = None          # an attempt began and no result line followed it
    service_stopped: bool = False                    # the last service line is "service stopped"
    first_day: Optional[date] = None
    last_pid: Optional[int] = None
    recognised: int = 0                              # how many lines were understood (0 = nothing usable)


def parse_log(lines: Sequence[str]) -> Parsed:
    """Parse log lines in time order. Unknown lines, bad lines and a half-written last line are skipped."""
    p = Parsed()
    for raw in lines:
        m = _LINE.match(raw.rstrip("\r\n"))
        if not m:
            continue
        try:
            at = datetime.strptime(f"{m.group(1)} {m.group(2)}", "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        msg = m.group(4)
        hit = True
        if (s := _START.match(msg)):
            p.service_stopped, p.last_pid, p.open_attempt = False, int(s.group(1)), None
        elif msg.startswith("service stopped") or msg.startswith("stop requested"):
            p.service_stopped = msg.startswith("service stopped") or p.service_stopped
        elif _ATTEMPT_BEGIN.match(msg):
            p.open_attempt = at
        elif (r := _ATTEMPT_RESULT.match(msg)):
            p.attempts.append(Attempt(at, r.group(1), int(r.group(2)), r.group(3), r.group(4), r.group(5) or ""))
            p.open_attempt = None
        elif (c := _CATCHUP.match(msg)):
            p.catchups.append(CatchUp(at, int(c.group(2))))
        elif (a := _ALERT.match(msg)):
            if p.attempts and p.attempts[-1].action == "stop" and not p.attempts[-1].alert:
                p.attempts[-1].alert, p.attempts[-1].alert_text = True, a.group(1).strip()
        else:
            hit = msg.startswith(("catch-up (", "attempt (", "started at", "replacing the instance"))      # known but not needed
        if hit:
            p.recognised += 1
            if p.first_day is None:
                p.first_day = at.date()
    return p


# ------------------------------------------------------------------------------------------------------------------------------ the state of one day
def _on(attempts: Sequence[Attempt], day: date) -> List[Attempt]:
    return [a for a in attempts if a.at.date() == day]


def classify(day: date, recs: Sequence[Attempt], now: datetime, is_today: bool, running: bool, service_running: bool) -> str:
    """DONE | RUNNING | RETRYING | NO_FILE | ALERT | WAITING | WEEKEND for one calendar day (``now`` is naive local time)."""
    last = recs[-1] if recs else None
    weekend = day.weekday() >= 5
    if any(a.action == "done" for a in recs):
        return "DONE"
    if is_today and running:
        return "RUNNING"
    if last is not None and last.alert:
        return "NO_FILE" if last.exit_code == 3 else "ALERT"      # exit 3 to the end of the day: the NSE never published a file, probably a holiday
    if last is not None and last.action == "stop":
        return "WEEKEND" if weekend else "ALERT"                  # the retry rule stops without an alert only for exit 3 on a weekend
    if last is not None:                                          # the last answer was "retry"
        return "RETRYING" if is_today else "ALERT"
    if weekend:
        return "WEEKEND"
    if is_today and (now.time() < RUN_AT or (service_running and now.time() <= LAST_ATTEMPT)):
        return "WAITING"
    return "ALERT"                                                # no attempt was logged on a weekday that is over (or the service is off after 19:30)


def message_for(state: str, recs: Sequence[Attempt]) -> str:
    last = recs[-1] if recs else None
    if state == "DONE":
        done = next(a for a in recs if a.action == "done")
        return f"Done for the day. The job finished at {done.at:%H:%M}."
    if state == "RUNNING":
        return "The job is running now."
    if state == "RETRYING":
        nxt = f" Next attempt at {last.next_hm}." if last and last.next_hm else ""
        what = "The NSE file is not published yet." if last and last.exit_code == 3 else f"The last attempt ended with exit {last.exit_code if last else '?'}."
        return what + nxt
    if state == "NO_FILE":
        return "No data file was published today. It is probably a market holiday, so nothing needs doing."
    if state == "ALERT":
        text = (last.alert_text or last.reason) if last else ""
        return f"The job stopped and needs a look: {text}." if text else "The job did not give a final answer for this day."
    if state == "WAITING":
        return "Waiting for the 19:30 job."
    return "No market session today (weekend)."


def _iso(at: datetime) -> str:
    return at.replace(tzinfo=IST, microsecond=0).isoformat()


def _decision(a: Attempt) -> str:
    return {"done": "done", "retry": "retry"}.get(a.action, "alert" if a.alert else "stopped")


# ------------------------------------------------------------------------------------------------------------------------------ the response
def build_job(parsed: Parsed, now: datetime, pid_info: Optional[dict], pid_alive: bool, lock_exists: bool, sealed: Optional[date], expected: date) -> M.Job:
    """``now`` is timezone-aware; ``pid_info`` is the parsed instance file ({"pid", "started_at"}) or None; ``lock_exists`` says whether the daily data job's lock file is there."""
    local = now.astimezone(IST).replace(tzinfo=None)
    today = local.date()
    service_running = bool(pid_alive) and not parsed.service_stopped
    pid = int(pid_info["pid"]) if pid_info and str(pid_info.get("pid", "")).lstrip("-").isdigit() else None
    started = None
    if pid_info and pid_info.get("started_at"):
        try:
            started = _iso(datetime.fromisoformat(str(pid_info["started_at"])))
        except ValueError:
            started = None
    service = M.JobService(running=service_running, pid=pid, startedAt=started)

    open_today = parsed.open_attempt is not None and parsed.open_attempt.date() == today
    running_now = open_today or lock_exists
    recs_today = _on(parsed.attempts, today)
    state = classify(today, recs_today, local, True, running_now, service_running)
    last = recs_today[-1] if recs_today else None
    last_at = parsed.open_attempt if state == "RUNNING" and open_today else (last.at if last else None)

    next_at: Optional[str] = None
    if service_running:
        if state == "RETRYING" and last and last.next_hm:
            h, m = last.next_hm.split(":")
            next_at = _iso(datetime.combine(today, time(int(h), int(m))))
        elif state in ("WAITING", "WEEKEND") and not recs_today and local.time() < RUN_AT:
            next_at = _iso(datetime.combine(today, RUN_AT))

    today_block = M.JobToday(date=today, state=state, attempts=len(recs_today), lastAttemptAt=_iso(last_at) if last_at else None,
                             lastExitCode=last.exit_code if last else None, message=message_for(state, recs_today))

    first = parsed.first_day or today
    start_day = max(first, today - timedelta(days=HISTORY_DAYS - 1))
    history: List[M.JobDay] = []
    d = start_day
    while d <= today:
        recs = _on(parsed.attempts, d)
        st = today_block.state if d == today else classify(d, recs, local, False, False, False)
        finished = None if (st in ("RUNNING", "WAITING") or not recs) else _iso(recs[-1].at)
        history.append(M.JobDay(date=d, state=st, attempts=len(recs), finishedAt=finished, lastExitCode=recs[-1].exit_code if recs else None))
        d += timedelta(days=1)

    events: List[Tuple[datetime, int, str]] = [(a.at, a.exit_code, _decision(a)) for a in parsed.attempts] + [(c.at, c.exit_code, "catch-up") for c in parsed.catchups]
    events.sort(key=lambda e: e[0], reverse=True)
    attempts = [M.JobAttempt(at=_iso(at), exitCode=code, decision=dec) for at, code, dec in events[:ATTEMPT_LIST]]

    return M.Job(apiVersion="1", dataAsOf=sealed or expected, expectedAsOf=expected, generatedAt=_iso(now.astimezone(IST).replace(tzinfo=None)),
                 service=service, nextAttemptAt=next_at, today=today_block, data=M.JobData(latestSealedDate=sealed, expectedAsOf=expected),
                 history=history, attempts=attempts)
