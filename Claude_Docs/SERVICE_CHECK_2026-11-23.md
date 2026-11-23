# Scheduler service check, 2026-11-23 17:29 IST (read-only)

## Verdict
**Service is OFF.** No scheduler_service process, no pid file and no log file exist. The main folder's master is also 3 commits behind origin, so `scripts\scheduler_service.py` is not in the main folder yet (it is on origin/master). Nothing was started, stopped, enabled, disabled, run or removed.

Start commands for the owner (NOT run by this check), in a PowerShell window that stays open:
```powershell
cd F:\Projects\Ravi\StockBot
git pull                                  # the main folder is on master at 5a5f8d0; origin/master (d0b9879) holds scripts\scheduler_service.py
py -3 scripts\scheduler_service.py
```
Before starting: the Windows task "StockBot Daily Data Recheck" is still Ready (08:30); SERVICE.md says the owner must disable it when the service is used. Also see "Other facts" (paper account and data).

## 1. Service process: NOT OK
Command: `Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*scheduler_service*" } | Select-Object ProcessId, CommandLine, CreationDate`
Output: none (zero processes). Zero means the service is off.

## 2. Pid file: NOT OK
Command: `Get-Content F:\Projects\Ravi\StockBotData\locks\scheduler_service.pid`
Output: the file does not exist ("pid file missing"). Nothing to compare with check 1.

## 3. Log: NOT OK
Command: `Get-Content F:\Projects\Ravi\StockBotData\logs\scheduler_service.log -Tail 40`
Output: the file does not exist ("log missing"). No start, no catch-up and no attempt was ever logged, so the service has never run on this machine (with the default data root). Not a stale log: there is no log.

## 4. Windows tasks: OK for "Update", note for "Recheck"
Command: `Get-ScheduledTask -TaskName "StockBot*" | Select-Object TaskName, State`
```
StockBot Daily Data Recheck    Ready
StockBot Daily Data Update  Disabled
```
"Update" is Disabled (last run 2026-11-20 21:30, result 4, next-run display 23-11-2026 19:30 is not active). "Recheck" is Ready and ran today 08:30 (result 0, next 24-11-2026 08:30); its logs `daily_update_20261121_083004.log`, `..._20261122_083005.log`, `..._20261123_083004.log` exist. Both Disabled was the expected state when the service is in use; right now no service runs, so only the 08:30 catch-up is active.

## 5. Live app (stockbot/live/main.py, uvicorn/FastAPI): OK
Command: `Get-CimInstance Win32_Process | Where-Object { $_.Name -like "python*" -or $_.Name -like "uvicorn*" } | Select-Object ProcessId, CommandLine`
Output: none. No python or uvicorn process is running, so the old scheduler is not running either.

## 6. Main folder: branch OK, commit older than expected
Commands: `git branch --show-current` -> `master`; `git log -1 --format="%h %s"` -> `5a5f8d0 Merge paper-lock-fix: paper_run blocks only on a lock for the same database`.
Expected d0b9879 or later: NOT yet. After `git fetch origin`, `origin/master` is `d0b9879 Merge scheduler-service: Python scheduler service for the daily job`; local master is 3 commits behind and has no `scripts\scheduler_service.py`. No `git pull` was done (not part of this check).

## Other facts (read-only)
- `F:\Projects\Ravi\StockBotData\locks\` exists and is empty (no run lock, no pid file).
- `state\live_state.db` does not exist: the paper account has not been started.
- No `daily_update_*.log` between 2026-11-20 21:30 and the three 08:30 catch-up logs: the 19:30 data job has not run since 2026-11-20 (task Disabled, service never started). Whether the lake holds the 2026-11-23 session was not checked; the job only attempts today's date from 19:30.
