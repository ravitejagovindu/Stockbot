# Scheduler service report (branch `scheduler-service`, 2026-11-21)

## Summary
- **Built:** `scripts/scheduler_service.py`, a Python `BlockingScheduler` (Asia/Kolkata) that replaces the Windows task for the daily job: single-instance pid file, catch-up on start, `daily_job.py --scheduled` at 19:30 with the retry rule, 08:30 catch-up, rotating log, toast on a stop without success (winotify if installed). Every action is a subprocess of an existing script (same interpreter, working directory the main folder; the job in its own process group so Ctrl+C does not kill it mid-write).
- **Not changed:** `daily_data_update.py`, `paper_run.py`, `daily_job.py`, `stockbot/live/scheduler.py`, any strategy rule/parameter/gate/registered config. No Task Scheduler task was enabled, changed, disabled or deleted ("Update" stayed Disabled, "Recheck" stayed Ready). The service and the jobs were never run for real; tests use a fake runner and temporary folders.
- **Needs the owner:** (1) disable the Windows "Recheck" task when the service is used (it does the 08:30 catch-up itself); (2) **do not start `stockbot/live/main.py` while the service is the scheduler** (finding below); (3) start the service by hand in a PowerShell window; (4) confirm the first real day.

## Exit-code table (retry decision, `decide` in the script)
| exit | meaning (from `daily_job.py` / `daily_data_update.py` / `paper_run.py`) | decision |
|---|---|---|
| 0 | data step done (or nothing to do) and paper step processed | done for the day; no further attempt that day |
| 1 | a day failed in the data step (or another error) | retry in 20 min |
| 2 | paper step refused (lake not sealed through the date, mode/freshness/surveillance refusal) | retry in 20 min |
| 3 | today's NSE file not published yet (data step) | retry in 20 min; Saturday/Sunday: stop, no alert |
| 4 | a lock on this database is held | retry in 20 min |
| 5 | stale lock | stop, ALERT line and toast; no retry (needs the owner) |
| other | unknown | treated like 1 (retry) |
Retries: next attempt = now + 20 min, none after 23:30 (19:30 + 12 x 20 min = 23:30); a stop at the limit without success writes an ALERT line and a toast. Nothing runs late after 23:45 (a missed 19:30 is not run after 23:45; a start between 19:30 and 23:30 attempts the day at once; the next start's catch-up fills earlier dates).

## The exit 2 decision
Read from the code: `paper_run.py` returns 2 when the lake is not sealed through the date and for mode/freshness/surveillance refusals; it returns 4 for locks. A weekday holiday (no session) would also give "not sealed", so by exit code alone the two cannot be told apart. But `daily_job.py` only calls the paper step after the data step exited 0, and on a holiday the data step ends with 3 (today's file stays PENDING until 23:45), so a holiday never reaches the paper step. Exit 2 therefore only occurs after the data step sealed today, where it is a real refusal. **Chosen:** exit 2 retries like 3/4/1 (bounded by 23:30); weekday holidays retry quickly (a few seconds per attempt) until 23:30 and end with an alert; weekends: an exit 3 is not retried and raises no alert. The job has no trading-day calendar (it tries every date and journals "no file"), so no "same session calendar" exists to skip weekday holidays in advance; none was invented. Trade-off: a weekday holiday produces about 13 quick attempts and one toast.

## Tests
`tests/unit/test_scheduler_service.py`, 22 tests, all with fakes and temp folders: every exit code (0, 1, 2, 3, 4, 5, unknown), the 23:30 boundary (23:10 -> 23:30 allowed, 23:11 stop), twelve retries fit 19:30 to 23:30, weekend exit 3, a missed 19:30 (late-start window 19:30 to 23:30, nothing after 23:45), the single-instance guard (live pid refuses, dead pid replaced, unreadable replaced, release removes only its own pid, file is not `*.lock`), catch-up on start with a fake runner (first call is `--catch-up-only`; late start also attempts the job; after 23:45 only the catch-up), one subprocess at a time, retry and alert behaviour, the subprocess runner (same interpreter, main folder), and the job registration (19:30 and 08:30 in Asia/Kolkata, loop not started). Guide test passes with the new CODEBASE_GUIDE row.
Full suite (`STOCKBOT_DATA_TESTS=1 STOCKBOT_FINAL_CHECK=1`): NOT YET RUN at the time of this commit. It takes about an hour and the folder had to be back on master before 08:25, so it is being run on a throwaway copy of this branch outside the repo (the real finsight.db read-only); its result is added in a follow-up note below if the owner has it, otherwise in the hand-over message. The known data-catalogue row-count failure is pre-existing.

## Not yet tested (a real day)
The real 19:30 subprocess, a real retry sequence, the toast, the log file on disk, Ctrl+C during a running job, behaviour after sleep or reboot, and `winotify` being installed. First confirmed by the owner on a real day.

## Finding: `stockbot/live/main.py` starts the OLD scheduler
`stockbot/live/main.py` (the FastAPI app, `lifespan`) calls `stockbot.live.scheduler.start_scheduler()` at startup, which schedules `run_eod_job` daily at 19:00 IST (bhavcopy source). So starting the live app WOULD start a second scheduler. With `book=None` its `run_eod_job` uses the EMPTY default book (no strategy), so it would not run momentum_calm, but it WOULD initialise `state/live_state.db` with the shared `paper_start_equity` (1,000,000, not 200,000) if the state database does not exist yet, and it runs without the data/paper ordering, locks or sealed-data check of `paper_run.py`. No code was added (as instructed). Until this is resolved: do not start `stockbot/live/main.py` while the service runs, and do not start it before `state/live_state.db` exists.

## Docs
`docs/shared/daily-update/SERVICE.md`: start, stop, check, what it does at 19:30 and 08:30, reboot/sleep behaviour, the two-schedulers warning, the Recheck task to be disabled by the owner (not done here), roll-back to the Windows task.
