# The scheduler service (replaces the Windows tasks for the daily job)

`scripts\scheduler_service.py` is a small always-running Python process (APScheduler `BlockingScheduler`, timezone Asia/Kolkata). Every action is a subprocess of an existing script; the service edits nothing itself. It was built and unit-tested with fakes only; its first real day is the owner's check (see "Not yet tested").

## Start (a PowerShell window in the main folder, left open)
```powershell
cd F:\Projects\Ravi\StockBot
py -3 scripts\scheduler_service.py
```
The checkout must be on `master` (with this branch merged). On start it logs, runs `daily_data_update.py --catch-up-only` once, and, if the start is between 19:30 and 23:30, attempts the day's job at once (a missed 19:30; the job is idempotent). Then it waits.

## Stop
Ctrl+C in that window. A running job is NOT killed: the service waits for it to finish (the job runs in its own process group, so the Ctrl+C does not reach it). Closing the window kills the service and, on Windows, may kill a running job: prefer Ctrl+C.

## Check
Log: `F:\Projects\Ravi\StockBotData\logs\scheduler_service.log` (rotating, 1 MB x 5). Each start, each attempt with its exit code, each decision (done / retry at HH:MM / stopped) and each skip is one line; there is no heartbeat.
```powershell
Get-Content F:\Projects\Ravi\StockBotData\logs\scheduler_service.log -Tail 30
Get-Content F:\Projects\Ravi\StockBotData\locks\scheduler_service.pid        # the pid of the running service
```
The job's own logs stay in `F:\Projects\Ravi\StockBotData\logs\daily_update_*.log`.

## What it does
* **19:30 IST every day:** `daily_job.py --scheduled` (data step, then the momentum_calm paper step), working directory the main folder, same Python as the service. One job subprocess at a time (an attempt that finds another running is skipped and logged).
* **Retry rule** (`decide` in the script): exit 0 = done for the day, nothing more that day. Exit 1 (a day failed), 2 (paper step refused), 3 (NSE file not published), 4 (a lock is held): next attempt 20 minutes later; the last attempt is 23:30 (19:30 + 12 x 20 minutes). Exit 5 (stale lock): stop, write an `ALERT` line and show a toast; retrying changes nothing and the lock needs the owner. A stop at 23:30 without success also writes `ALERT` and a toast (winotify, when installed; never a crash if not).
* **Exit 2 and holidays:** exit 2 cannot be told apart from a holiday by its code, but a holiday never reaches it: on a market holiday the data step ends with 3 (today's file stays PENDING until 23:45) before the paper step is called, so 2 only appears after the data step succeeded, and then it is a real refusal (retried like the others). A weekday holiday therefore retries (quick, a few seconds each) until 23:30 and ends with an alert; on a Saturday or Sunday an exit 3 is not retried and raises no alert (special weekend sessions are rare; the 08:30 catch-up checks the date again). The job has no trading-day calendar of its own (it tries every date and records "no file").
* **08:30 IST every day:** `daily_data_update.py --catch-up-only` (no retry loop), as the old Recheck task.
* **A missed 19:30:** if the service was not running, nothing runs late after 23:45; the next start's catch-up fills earlier dates, and a start between 19:30 and 23:30 attempts the day at once.
* **Single instance:** `F:\Projects\Ravi\StockBotData\locks\scheduler_service.pid` holds the pid. A live pid refuses a second start (exit 2); a dead pid is replaced. The file is deliberately not named `*.lock` (every `*.lock` in that folder is read by the run-lock code); it is not a run lock on `finsight.db`. It is removed on a clean stop; after a crash or reboot it is replaced on the next start.

## After a reboot or sleep
The service does not survive a reboot: nothing starts it. Start it again by hand after a reboot (step above); its start catch-up and late-start attempt fill the gap. A laptop that sleeps through 19:30 resumes the process: APScheduler runs a missed 19:30 on wake only until 23:45 (misfire grace 4 h 15 min); after that the next start or the 08:30 catch-up fills it.

## Two schedulers must never run the paper step
* The Windows task "StockBot Daily Data Update" is DISABLED by the owner; keep it disabled while the service runs.
* The Windows task "StockBot Daily Data Recheck" (08:30, catch-up only) is still enabled: the owner must DISABLE it when the service is used (the service does the 08:30 catch-up itself). It was not touched by the build.
* `stockbot/live/main.py` (the FastAPI app) starts the old `stockbot/live/scheduler.py` at its startup: do not start that app while the service is the scheduler (see `Claude_Docs/SCHEDULER_SERVICE_REPORT.md`).

## Roll-back to the Windows task
1. Ctrl+C the service (wait for "service stopped"); check `scheduler_service.pid` is gone.
2. Re-enable the data/paper task (its action already points at `daily_job.py --scheduled`; the old 4-hour repetition was removed, so it fires once at 19:30 and does not retry): `Enable-ScheduledTask -TaskName "StockBot Daily Data Update"`. To get the old 20-minute repetition back use the "Create" block in `SCHEDULER.md`.
3. Keep or re-enable the 08:30 Recheck task: `Enable-ScheduledTask -TaskName "StockBot Daily Data Recheck"`.

## Not yet tested
Unit tests cover the retry rule (every exit code, before and after 23:30, weekends, a late start), the single-instance guard, the catch-up on start and the job registration, all with a fake runner. A real day (the 19:30 subprocess, a real retry, a toast, the log file, Ctrl+C during a job) has not been run.
