"""scripts/scheduler_service.py: the retry rule, the single-instance guard and the start-up catch-up. Fakes and temporary folders only: no test runs a real job, touches finsight.db or the real lock folder."""
import importlib.util
import json
import os
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("scheduler_service", ROOT / "scripts" / "scheduler_service.py")
SS = importlib.util.module_from_spec(spec)
import sys
sys.modules["scheduler_service"] = SS
spec.loader.exec_module(SS)

FRI = datetime(2026, 11, 20)            # a Friday
SAT = datetime(2026, 11, 21)


def at(h, m, base=FRI):
    return base.replace(hour=h, minute=m)


# ------------------------------------------------------------------ the retry rule
def test_exit_0_is_done_for_the_day():
    d = SS.decide(0, at(19, 31))
    assert d.action == "done" and d.next_at is None and not d.alert


@pytest.mark.parametrize("code", [1, 2, 3, 4, 7])
def test_failures_retry_in_20_minutes(code):
    d = SS.decide(code, at(19, 31))
    assert d.action == "retry" and d.next_at == at(19, 51) and not d.alert


def test_exit_5_stops_with_an_alert_at_any_time():
    for t in (at(19, 31), at(21, 0), at(23, 0)):
        d = SS.decide(5, t)
        assert d.action == "stop" and d.alert and d.next_at is None


def test_the_last_attempt_is_23_30_and_nothing_is_scheduled_after_it():
    assert SS.decide(3, at(23, 10)).next_at == at(23, 30)               # 23:30 itself is still allowed
    d = SS.decide(3, at(23, 11))
    assert d.action == "stop" and d.alert and d.next_at is None          # 23:31 would be after the limit
    assert SS.decide(4, at(23, 30)).action == "stop"
    assert SS.decide(1, at(23, 50)).action == "stop"


def test_twelve_retries_fit_between_19_30_and_23_30():
    t, n = at(19, 30), 0
    while True:
        d = SS.decide(3, t)
        if d.action != "retry":
            break
        t, n = d.next_at, n + 1
    assert n == 12 and t == at(23, 30)


def test_a_missing_file_on_a_weekend_is_not_retried_and_raises_no_alert():
    d = SS.decide(3, at(19, 31, SAT))
    assert d.action == "stop" and not d.alert
    assert SS.decide(4, at(19, 31, SAT)).action == "retry"               # only exit 3 is the weekend "no session" answer
    assert SS.decide(3, at(19, 31, FRI)).action == "retry"               # a weekday holiday keeps retrying until 23:30


def test_a_missed_19_30_is_attempted_at_a_late_start_only_up_to_23_30():
    assert not SS.late_start_attempt_due(at(19, 29))
    assert SS.late_start_attempt_due(at(19, 30)) and SS.late_start_attempt_due(at(21, 5)) and SS.late_start_attempt_due(at(23, 30))
    assert not SS.late_start_attempt_due(at(23, 31)) and not SS.late_start_attempt_due(at(8, 0))


# ------------------------------------------------------------------ single instance
def test_a_live_pid_refuses_and_a_dead_pid_is_replaced(tmp_path):
    f = tmp_path / "locks" / "scheduler_service.pid"
    SS.take_instance_file(f, 111, lambda p: True)
    assert json.loads(f.read_text())["pid"] == 111
    with pytest.raises(SS.AlreadyRunning):
        SS.take_instance_file(f, 222, lambda p: p == 111)                # 111 is alive
    assert json.loads(f.read_text())["pid"] == 111                       # unchanged
    SS.take_instance_file(f, 333, lambda p: False)                       # 111 is dead: replaced
    assert json.loads(f.read_text())["pid"] == 333


def test_an_unreadable_instance_file_is_replaced_and_release_removes_only_own_file(tmp_path):
    f = tmp_path / "scheduler_service.pid"
    f.write_text("garbage")
    SS.take_instance_file(f, 5, lambda p: True)
    assert json.loads(f.read_text())["pid"] == 5
    SS.release_instance_file(f, 6)
    assert f.exists()                                                    # another pid's file stays
    SS.release_instance_file(f, 5)
    assert not f.exists()


def test_the_instance_file_is_not_a_run_lock_file(tmp_path):
    f = tmp_path / "locks" / "scheduler_service.pid"
    SS.take_instance_file(f, 1, lambda p: False)
    assert not list((tmp_path / "locks").glob("*.lock"))                 # runlock.locks_for reads *.lock only


# ------------------------------------------------------------------ the service with a fake runner
class Fake:
    def __init__(self, codes):
        self.codes, self.calls = list(codes), []

    def __call__(self, argv):
        self.calls.append([Path(argv[1]).name, *argv[2:]])
        return self.codes.pop(0) if self.codes else 0


def service(runner, now, notes=None):
    clock = {"now": now}
    s = SS.Service(runner=runner, now_fn=lambda: clock["now"], notify=lambda t, m: (notes if notes is not None else []).append((t, m)), python="py")
    return s, clock


def test_start_runs_the_catch_up_first_then_no_attempt_before_19_30():
    r = Fake([0])
    s, _ = service(r, at(8, 0))
    s.start_actions()
    assert r.calls == [["daily_data_update.py", "--catch-up-only"]]


def test_a_start_at_21_00_runs_the_catch_up_then_attempts_the_job_once_at_once():
    r = Fake([0, 0])
    s, _ = service(r, at(21, 0))
    s.start_actions()
    assert r.calls == [["daily_data_update.py", "--catch-up-only"], ["daily_job.py", "--scheduled"]]
    assert s.done_on == FRI.date()
    s.attempt("again")
    assert len(r.calls) == 2                                             # done today: no further attempt


def test_a_start_after_23_45_runs_only_the_catch_up_and_never_a_late_job():
    r = Fake([0])
    s, _ = service(r, at(23, 50))
    s.start_actions()
    assert r.calls == [["daily_data_update.py", "--catch-up-only"]]
    assert s.attempt("x") is None and len(r.calls) == 1


def test_a_failed_attempt_is_retried_and_the_decision_is_returned():
    r = Fake([3])
    s, _ = service(r, at(19, 30))
    d = s.attempt()
    assert d.action == "retry" and d.next_at == at(19, 50) and s.done_on is None


def test_exit_5_raises_a_toast_and_the_last_failure_at_23_30_raises_one():
    notes = []
    s, _ = service(Fake([5]), at(19, 30), notes)
    s.attempt()
    assert len(notes) == 1 and "stale lock" in notes[0][1]
    notes2 = []
    s2, _ = service(Fake([3]), at(23, 30), notes2)
    assert s2.attempt().action == "stop" and len(notes2) == 1


def test_only_one_job_subprocess_at_a_time():
    r = Fake([])
    s, _ = service(r, at(19, 30))
    assert s._busy.acquire(blocking=False)                               # a job is "running"
    assert s.attempt() is None and s.catch_up("08:30") is None and r.calls == []
    s._busy.release()


def test_the_subprocess_runner_uses_the_same_interpreter_and_the_main_folder(monkeypatch):
    seen = {}
    monkeypatch.setattr(SS.subprocess, "call", lambda argv, cwd=None, creationflags=0: seen.update(argv=argv, cwd=cwd, flags=creationflags) or 0)
    s = SS.Service(runner=SS.subprocess_runner)
    assert s.runner(s._argv("daily_job.py", "--scheduled")) == 0
    assert seen["argv"][0] == SS.sys.executable and seen["argv"][1].endswith(os.path.join("scripts", "daily_job.py")) and seen["argv"][2] == "--scheduled"
    assert Path(seen["cwd"]) == ROOT


def test_run_registers_the_19_30_and_08_30_jobs_in_ist_without_starting_the_loop(monkeypatch):
    from apscheduler.schedulers.blocking import BlockingScheduler
    captured = {}

    monkeypatch.setattr(BlockingScheduler, "start", lambda self: captured.update(tz=str(self.timezone), ids=sorted(j.id for j, *_ in self._pending_jobs)))
    r = Fake([0])
    s, _ = service(r, at(8, 0))
    s.run()
    assert captured["tz"] == "Asia/Kolkata" and captured["ids"] == ["catch_up_08_30", "daily_19_30"]
    assert r.calls == [["daily_data_update.py", "--catch-up-only"]]
