"""GET /v1/job: the daily-job status built from the scheduler service's log. The fixture is a copy of the real log of 23-25 Nov 2026: on the 24th the NSE file never came
(12 attempts with exit 3, then the ALERT), the 08:30 catch-up on the 25th ended 0, and the 25th's 19:30 attempt ended 0."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from conftest import AUTH, TOKEN, example
from fastapi.testclient import TestClient

from bff import jobstatus as J
from bff import models as M
from bff import sources as S
from bff.app import create_app
from world import build_world, sector_stub, signal_stub

IST = timezone(timedelta(hours=5, minutes=30))
REAL = (Path(__file__).parent / "fixtures" / "scheduler_service_real.log").read_text(encoding="utf-8")
LINES = REAL.splitlines()
PID = {"pid": 9100, "started_at": "2026-11-23T17:43:25"}


def at(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=IST)


def upto(prefix: str):
    i = next(k for k, ln in enumerate(LINES) if ln.startswith(prefix))
    return LINES[: i + 1]


def build(lines, now, alive=True, lock=False, sealed=date(2026, 11, 23), expected=date(2026, 11, 24), pid=PID):
    return J.build_job(J.parse_log(lines), at(now), pid, alive, lock, sealed, expected)


# ------------------------------------------------------------------------------------------------------------------------------ the real log
def test_the_real_log_is_what_the_brief_describes():
    p = J.parse_log(LINES)
    on24 = [a for a in p.attempts if a.at.date() == date(2026, 11, 24)]
    assert len(on24) == 12 and all(a.exit_code == 3 for a in on24) and on24[-1].action == "stop" and on24[-1].alert
    assert [c.exit_code for c in p.catchups] == [0, 0, 0] and p.catchups[-1].at == datetime(2026, 11, 25, 8, 30, 32)
    assert p.attempts[-1].at == datetime(2026, 11, 25, 19, 47, 49) and p.attempts[-1].action == "done"
    assert p.last_pid == 9100 and not p.service_stopped and p.open_attempt is None


def test_25_nov_after_the_job_is_done():
    j = build(LINES, "2026-11-25T19:48:00", sealed=date(2026, 11, 25), expected=date(2026, 11, 25))
    assert (j.today.state, j.today.attempts, j.today.lastExitCode, j.today.lastAttemptAt) == ("DONE", 1, 0, "2026-11-25T19:47:49+05:30")
    assert j.today.message == "Done for the day. The job finished at 19:47."
    assert j.nextAttemptAt is None
    assert j.service.running and j.service.pid == 9100 and j.service.startedAt == "2026-11-23T17:43:25+05:30"
    assert (j.data.latestSealedDate, j.data.expectedAsOf) == (date(2026, 11, 25), date(2026, 11, 25))
    assert [(d.date.isoformat(), d.state, d.attempts, d.lastExitCode) for d in j.history] == [
        ("2026-11-23", "DONE", 1, 0), ("2026-11-24", "NO_FILE", 12, 3), ("2026-11-25", "DONE", 1, 0)]
    assert j.history[1].finishedAt == "2026-11-24T23:11:04+05:30"
    assert [(a.at[:16], a.exitCode, a.decision) for a in j.attempts[:4]] == [
        ("2026-11-25T19:47", 0, "done"), ("2026-11-25T08:30", 0, "catch-up"), ("2026-11-24T23:11", 3, "alert"), ("2026-11-24T22:51", 3, "retry")]


def test_24_nov_end_of_day_is_no_file_probably_a_holiday():
    j = build(upto("2026-11-24 23:11:04,790"), "2026-11-24T23:15:00")
    assert j.today.state == "NO_FILE" and j.today.attempts == 12 and j.today.lastExitCode == 3
    assert "holiday" in j.today.message and "!" not in j.today.message
    assert j.nextAttemptAt is None


def test_24_nov_evening_is_retrying_with_the_next_attempt_time():
    j = build(upto("2026-11-24 20:30:38"), "2026-11-24T20:35:00")
    assert (j.today.state, j.today.attempts) == ("RETRYING", 4)
    assert j.nextAttemptAt == "2026-11-24T20:50:00+05:30"
    assert j.today.message == "The NSE file is not published yet. Next attempt at 20:50."
    assert j.history[-1].finishedAt is not None


def test_an_attempt_without_a_result_is_running():
    j = build(upto("2026-11-24 19:50:12"), "2026-11-24T19:52:00")
    assert j.today.state == "RUNNING" and j.nextAttemptAt is None
    assert j.today.lastAttemptAt == "2026-11-24T19:50:12+05:30"
    assert j.history[-1].state == "RUNNING" and j.history[-1].finishedAt is None


def test_the_data_jobs_lock_means_running():
    j = build(upto("2026-11-24 19:30:12"), "2026-11-24T19:31:00", lock=True)
    assert j.today.state == "RUNNING"           # a retry decision is logged, but the data job's lock is there: a job is running right now (the lock wins)
    assert build(upto("2026-11-24 19:30:12"), "2026-11-24T19:31:00", lock=False).today.state == "RETRYING"
    j2 = build(LINES[:-2] + ["2026-11-25 19:30:00,011 INFO attempt (19:30): daily_job.py --scheduled"], "2026-11-25T19:35:00", lock=True)
    assert j2.today.state == "RUNNING"
    j3 = build(LINES[:-2], "2026-11-25T19:35:00", lock=True)                        # no attempt logged yet today, but the lock is there
    assert j3.today.state == "RUNNING"


def test_before_1930_on_a_weekday_is_waiting_and_the_service_off_has_no_next_attempt():
    j = build(LINES, "2026-11-26T10:00:00", sealed=date(2026, 11, 25), expected=date(2026, 11, 25))       # Thursday morning
    assert (j.today.state, j.today.attempts, j.today.lastExitCode, j.today.lastAttemptAt) == ("WAITING", 0, None, None)
    assert j.nextAttemptAt == "2026-11-26T19:30:00+05:30" and j.today.message == "Waiting for the 19:30 job."
    off = build(LINES, "2026-11-26T10:00:00", alive=False, sealed=date(2026, 11, 25), expected=date(2026, 11, 25))
    assert off.service.running is False and off.service.pid == 9100 and off.nextAttemptAt is None


def test_a_weekday_with_no_attempt_after_the_window_is_an_alert():
    j = build(LINES, "2026-11-26T23:50:00", sealed=date(2026, 11, 25), expected=date(2026, 11, 26))
    assert j.today.state == "ALERT"
    assert build(LINES, "2026-11-26T20:00:00", alive=False).today.state == "ALERT"      # the service is off after 19:30 and nothing ran


def test_a_weekend_is_weekend_with_or_without_the_normal_exit_3_stop():
    sat_log = LINES + ["2026-11-28 19:30:00,010 INFO attempt (19:30): daily_job.py --scheduled",
                       "2026-11-28 19:30:07,220 INFO attempt (19:30) exit 3 -> stop (no NSE file on a weekend: not retried (the 08:30 catch-up checks it again))"]
    j = build(sat_log, "2026-11-28T20:00:00", expected=date(2026, 11, 27))
    assert (j.today.state, j.today.attempts, j.today.lastExitCode) == ("WEEKEND", 1, 3)
    assert j.today.message == "No market session today (weekend)." and j.nextAttemptAt is None
    sun = build(LINES, "2026-11-29T09:00:00", expected=date(2026, 11, 27))                  # Sunday morning, nothing yet
    assert sun.today.state == "WEEKEND" and sun.nextAttemptAt == "2026-11-29T19:30:00+05:30"
    assert [d.state for d in sun.history if d.date in (date(2026, 11, 28), date(2026, 11, 29))] == ["WEEKEND", "WEEKEND"]


def test_another_alert_is_an_alert_with_the_reason():
    log = LINES[:-2] + ["2026-11-25 19:30:00,011 INFO attempt (19:30): daily_job.py --scheduled",
                        "2026-11-25 19:30:08,500 INFO attempt (19:30) exit 5 -> stop (stale lock: needs the owner, not retried)",
                        "2026-11-25 19:30:08,501 ERROR ALERT: stale lock: needs the owner, not retried"]
    j = build(log, "2026-11-25T19:40:00", sealed=date(2026, 11, 24), expected=date(2026, 11, 25))
    assert j.today.state == "ALERT" and j.today.message == "The job stopped and needs a look: stale lock: needs the owner, not retried."
    assert j.attempts[0].decision == "alert" and j.attempts[0].exitCode == 5


def test_a_retry_that_never_got_a_final_answer_is_an_alert_the_next_day():
    log = upto("2026-11-24 19:30:12")
    j = build(log + ["2026-11-25 08:30:00,005 INFO catch-up (08:30): daily_data_update.py --catch-up-only", "2026-11-25 08:30:30,000 INFO catch-up (08:30) exit 0"],
              "2026-11-25T09:00:00")
    assert [d.state for d in j.history if d.date == date(2026, 11, 24)] == ["ALERT"]


def test_the_service_stopped_line_means_off_even_when_the_pid_looks_alive():
    j = build(LINES + ["2026-11-25 21:00:00,000 INFO stop requested: waiting for a running job to finish", "2026-11-25 21:00:05,000 INFO service stopped"], "2026-11-25T21:01:00",
              sealed=date(2026, 11, 25), expected=date(2026, 11, 25))
    assert j.service.running is False
    assert build(LINES + ["2026-11-25 21:10:00,000 INFO service start (pid 9100)"], "2026-11-25T21:11:00").service.running is True


def test_history_is_at_most_ten_days_and_the_attempt_list_at_most_twenty():
    many = []
    for n in range(1, 25):
        d = date(2026, 12, 1) + timedelta(days=n)
        many += [f"{d} 19:30:00,100 INFO attempt (19:30): daily_job.py --scheduled", f"{d} 19:40:00,100 INFO attempt (19:30) exit 0 -> done (done for the day)"]
    j = build(many, "2026-12-25T19:50:00", sealed=date(2026, 12, 25), expected=date(2026, 12, 25))
    assert len(j.history) == 10 and j.history[-1].date == date(2026, 12, 25) and j.history[0].date == date(2026, 12, 16)
    assert len(j.attempts) == 20 and j.attempts[0].at > j.attempts[-1].at


# ------------------------------------------------------------------------------------------------------------------------------ tolerance
def test_garbage_unknown_and_half_written_lines_are_ignored():
    messy = ["", "garbage without a time", "\x00\x00\x00", "2026-13-45 99:99:99,000 INFO attempt (19:30) exit 0 -> done", "2026-11-25 19:30:00,011 INFO something new and unknown",
             *LINES[:-2], "2026-11-25 19:30:00,011 INFO attempt (19:30): daily_job.py --scheduled", "2026-11-25 19:47:4"]
    j = build(messy, "2026-11-25T19:35:00")
    assert j.today.state == "RUNNING" and j.history[0].date == date(2026, 11, 23)


def test_nothing_usable_in_the_log_is_not_a_result():
    for lines in ([], ["garbage"], ["2026-11-25 19:30:00,011 INFO something unknown"]):
        assert J.parse_log(lines).recognised == 0


def test_parse_is_total_on_arbitrary_text():
    import random
    rnd = random.Random(3)
    alphabet = "attempt exit -> done retry stop ALERT catch-up service start (pid 123) 2026-11-2 19:30:00,0 INFO ERROR\n\r\t:()"
    for _ in range(300):
        text = "".join(rnd.choice(alphabet) for _ in range(rnd.randint(0, 200)))
        J.parse_log(text.splitlines())


# ------------------------------------------------------------------------------------------------------------------------------ the readers
def test_rotated_files_are_read_oldest_first_and_a_half_written_last_line_does_not_matter(tmp_path):
    log = tmp_path / "scheduler_service.log"
    (tmp_path / "scheduler_service.log.2").write_text("2026-11-22 19:30:00,100 INFO attempt (19:30): daily_job.py --scheduled\n", encoding="utf-8")
    (tmp_path / "scheduler_service.log.1").write_text("2026-11-23 19:30:00,100 INFO attempt (19:30): daily_job.py --scheduled\n", encoding="utf-8")
    log.write_text("2026-11-24 19:30:00,100 INFO attempt (19:30): daily_job.py --scheduled\n2026-11-24 19:4", encoding="utf-8")
    lines = S.read_scheduler_log(log)
    assert [ln[:10] for ln in lines] == ["2026-11-22", "2026-11-23", "2026-11-24", "2026-11-24"]


def test_missing_log_is_a_source_error(tmp_path):
    with pytest.raises(S.SourceError):
        S.read_scheduler_log(tmp_path / "scheduler_service.log")


def test_instance_file_and_lock_existence(tmp_path):
    assert S.read_instance_file(tmp_path) is None
    (tmp_path / "scheduler_service.pid").write_text(json.dumps(PID), encoding="utf-8")
    assert S.read_instance_file(tmp_path) == PID
    (tmp_path / "scheduler_service.pid").write_text("not json", encoding="utf-8")
    assert S.read_instance_file(tmp_path) is None
    assert S.daily_lock_exists(tmp_path) is False
    (tmp_path / "daily_update.lock").write_text("do not read me", encoding="utf-8")
    assert S.daily_lock_exists(tmp_path) is True


def test_process_alive_for_this_process_and_a_dead_one():
    import os
    assert S.process_alive(os.getpid()) is True
    assert S.process_alive(0) is False and S.process_alive(-5) is False
    assert S.process_alive(2_000_000_000) is False


# ------------------------------------------------------------------------------------------------------------------------------ HTTP
@pytest.fixture
def job_world(tmp_path):
    w = build_world(tmp_path, "empty")
    data = w.settings.data_root
    (data / "logs").mkdir(parents=True, exist_ok=True)
    (data / "locks").mkdir(parents=True, exist_ok=True)
    (data / "logs" / "scheduler_service.log").write_text(REAL, encoding="utf-8")
    (data / "locks" / "scheduler_service.pid").write_text(json.dumps(PID), encoding="utf-8")
    return w


def client(w, now="2026-11-25T19:48:00", alive=True, **kw):
    app = create_app(w.settings, now_fn=lambda: at(now), signal_fn=signal_stub, sector_for=sector_stub, pid_alive_fn=lambda pid: alive)
    return TestClient(app, base_url="http://testserver", raise_server_exceptions=False, **kw)


def kind(v):
    return "null" if v is None else "bool" if isinstance(v, bool) else "number" if isinstance(v, (int, float)) else "str" if isinstance(v, str) else type(v).__name__


def shape(a, b, path="$"):
    if isinstance(a, dict) and isinstance(b, dict):
        assert set(a) == set(b), f"{path}: {sorted(set(a) ^ set(b))}"
        for k in a:
            shape(a[k], b[k], f"{path}.{k}")
    elif isinstance(a, list) and isinstance(b, list):
        if a and b:
            shape(a[0], b[0], f"{path}[0]")
    elif a is not None and b is not None:
        assert kind(a) == kind(b), path


def test_the_endpoint_has_the_shape_of_the_example_and_validates(job_world):
    r = client(job_world).get("/v1/job", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    M.Job.model_validate(body)
    shape(body, example("job.json"))
    assert body["today"]["state"] == "DONE" and body["apiVersion"] == "1" and body["service"]["pid"] == 9100


def test_the_endpoint_needs_the_token_and_never_returns_it(job_world):
    c = client(job_world)
    assert c.get("/v1/job").status_code == 401
    assert c.get("/v1/job", headers={"X-Paper-Token": "wrong"}).status_code == 401
    r = c.get("/v1/job", headers=AUTH)
    assert TOKEN not in r.text and "token" not in r.text.lower()


def test_missing_or_unusable_log_is_503_not_ready_never_500(job_world):
    log = job_world.settings.data_root / "logs" / "scheduler_service.log"
    c = client(job_world)
    log.write_text("garbage only\n\x00\x00\n", encoding="utf-8")
    r = c.get("/v1/job", headers=AUTH)
    assert r.status_code == 503 and r.json()["error"]["code"] == "NOT_READY"
    log.unlink()
    r = c.get("/v1/job", headers=AUTH)
    assert r.status_code == 503 and r.json() == {"apiVersion": "1", "error": {"code": "NOT_READY", "message": "Today's data is not ready yet."}}


def test_missing_pid_file_and_unreadable_lake_still_answer(job_world):
    (job_world.settings.data_root / "locks" / "scheduler_service.pid").unlink()
    job_world.settings.lake.unlink()
    body = client(job_world).get("/v1/job", headers=AUTH).json()
    assert body["service"] == {"running": False, "pid": None, "startedAt": None}
    assert body["data"]["latestSealedDate"] is None and body["dataAsOf"] == body["expectedAsOf"]
    M.Job.model_validate(body)


def test_still_running_and_service_off_over_http(job_world):
    log = job_world.settings.data_root / "logs" / "scheduler_service.log"
    log.write_text("\n".join(upto("2026-11-24 19:50:12")) + "\n", encoding="utf-8")
    assert client(job_world, now="2026-11-24T19:52:00").get("/v1/job", headers=AUTH).json()["today"]["state"] == "RUNNING"
    log.write_text(REAL, encoding="utf-8")
    off = client(job_world, now="2026-11-26T10:00:00", alive=False).get("/v1/job", headers=AUTH).json()
    assert off["service"]["running"] is False and off["nextAttemptAt"] is None


def test_the_endpoint_writes_and_creates_nothing(job_world):
    root = job_world.settings.data_root
    watched = [root / "logs", root / "locks", root / "daily"]

    def snap():
        return {str(d): sorted((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in d.iterdir()) for d in watched}

    before = snap()
    c = client(job_world)
    for _ in range(3):
        c.get("/v1/job", headers=AUTH)
    assert snap() == before


def test_a_lock_file_is_only_checked_for_not_read(job_world, monkeypatch):
    (job_world.settings.data_root / "locks" / "daily_update.lock").write_text("secret contents", encoding="utf-8")
    opened = []
    real_open = open

    def spy(file, *a, **k):
        opened.append(str(file))
        return real_open(file, *a, **k)

    monkeypatch.setattr("builtins.open", spy)
    body = client(job_world).get("/v1/job", headers=AUTH).json()
    assert not any(p.endswith("daily_update.lock") for p in opened)
    assert body["today"]["state"] == "DONE"          # done earlier today stays done even while a lock exists


def test_post_is_not_allowed(job_world):
    assert client(job_world).post("/v1/job", headers=AUTH).status_code == 405
