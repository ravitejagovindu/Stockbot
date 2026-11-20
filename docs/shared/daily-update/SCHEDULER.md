# Windows Task Scheduler: the daily data job (commands only; NOT registered by the build)

Job: `F:\Projects\Ravi\StockBot\scripts\daily_data_update.py --scheduled`. First attempt 19:30 IST, then every 20 minutes until 23:30, then it stops for the day (4 hours of repetition). The job itself attempts today's date only between 19:30 and 23:45; every run also catches up any earlier missing date, oldest first. A run with nothing to do ends in a second or two.

Python: `C:\Users\ravit\AppData\Local\Programs\Python\Python313\python.exe` (the interpreter `py -3` resolves to on this machine). The task runs from the checkout that holds the script, so `finsight.db` is the one in that checkout (`F:\Projects\Ravi\StockBot\finsight.db`) unless `STOCKBOT_DB` is set.

## Create (PowerShell, as the user who owns the data; laptop-friendly: starts late if the machine was asleep, runs on battery, never two copies at once)
```powershell
$py   = "C:\Users\ravit\AppData\Local\Programs\Python\Python313\python.exe"
$job  = "F:\Projects\Ravi\StockBot\scripts\daily_data_update.py"
$act  = New-ScheduledTaskAction -Execute $py -Argument "`"$job`" --scheduled" -WorkingDirectory "F:\Projects\Ravi\StockBot"
$trg  = New-ScheduledTaskTrigger -Daily -At 19:30
$rep  = (New-ScheduledTaskTrigger -Once -At 19:30 -RepetitionInterval (New-TimeSpan -Minutes 20) -RepetitionDuration (New-TimeSpan -Hours 4)).Repetition
$trg.Repetition = $rep
$set  = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 3)
Register-ScheduledTask -TaskName "StockBot Daily Data Update" -Action $act -Trigger $trg -Settings $set -Description "NSE bhavcopy + index/VIX + ASM/GSM into finsight.db (guarded, sealed per day)"
```
Optional morning re-check of dates that had no file the evening before (and the next 3 days): same script, never tries today's date.
```powershell
$act2 = New-ScheduledTaskAction -Execute $py -Argument "`"$job`" --catch-up-only" -WorkingDirectory "F:\Projects\Ravi\StockBot"
Register-ScheduledTask -TaskName "StockBot Daily Data Recheck" -Action $act2 -Trigger (New-ScheduledTaskTrigger -Daily -At 08:30) -Settings $set
```

## Create (plain `schtasks`, same schedule; no battery or catch-up settings)
```bat
schtasks /Create /TN "StockBot Daily Data Update" /SC DAILY /ST 19:30 /RI 20 /DU 04:00 /TR "\"C:\Users\ravit\AppData\Local\Programs\Python\Python313\python.exe\" \"F:\Projects\Ravi\StockBot\scripts\daily_data_update.py\" --scheduled"
```

## Show
```powershell
Get-ScheduledTask -TaskName "StockBot Daily Data*" | Get-ScheduledTaskInfo      # last run, last result, next run
schtasks /Query /TN "StockBot Daily Data Update" /V /FO LIST
Get-ChildItem F:\Projects\Ravi\StockBotData\logs | Sort-Object LastWriteTime | Select-Object -Last 5
py -3 F:\Projects\Ravi\StockBot\scripts\daily_data_update.py --plan             # which dates it would check; no network, no write, no lock
```
Last result codes: 0 done or nothing to do, 1 a day failed (read the log), 3 today's file is not published yet (normal during the evening window; the next repetition retries), 4 locked by a backtest/validation run (the next repetition retries), 5 STALE lock (read the message, check, remove the lock file by hand, see below).

## Remove
```powershell
Unregister-ScheduledTask -TaskName "StockBot Daily Data Update" -Confirm:$false
Unregister-ScheduledTask -TaskName "StockBot Daily Data Recheck" -Confirm:$false      # if the optional one was created
```
```bat
schtasks /Delete /TN "StockBot Daily Data Update" /F
```

## Locks (exact paths and rule)
* Lock folder: `F:\Projects\Ravi\StockBotData\locks\` (`STOCKBOT_LOCK_DIR` overrides it).
* `F:\Projects\Ravi\StockBotData\locks\daily_update.lock`: held by the daily job while it runs. A backtest, baseline, signal count or validation step refuses to start while it exists (exit code 4).
* `F:\Projects\Ravi\StockBotData\locks\run_<pid>_<YYYYmmddHHMMSS>.lock`: one per running backtest / validation step / baseline (taken by `run_backtest`, the `short_step` wrapper, and `fingerprint()`; removed when the run ends). While any exists for the same database file the daily job writes nothing and exits with code 4, so the scheduler retries 20 minutes later.
* STALE = the lock is older than 12 hours AND no live process has its pid. The job (or run) reports it, exits with code 5 and does NOT delete it. A lock whose process is gone but is younger than 12 hours still blocks (the job may have died mid-write). After checking that nothing is running (and, for a stale `daily_update.lock`, that `py -3 scripts/guard.py audit` is ok and `--plan` shows the dates you expect): `Remove-Item -LiteralPath F:\Projects\Ravi\StockBotData\locks\<file>`.

## Replacement for the 19:30 job: data step + momentum_calm paper step (commands only; NOT run by the build)
`scripts\daily_job.py [--scheduled]` runs `daily_data_update.py` first and runs the paper step (`scripts\paper_run.py`, sealed data only) only when the data step exited 0. Any other data exit code (3 file not published yet, 4 locked, 5 stale lock, 1 failed day) ends the job with that code and no paper step, so the 20-minute repetition retries both. The paper step is idempotent per trading date (a date already in `state\live_state.db` changes nothing), so repetitions on a day that is done end in a second or two. Paper exit codes: 0 processed or already processed, 2 refused (lake not sealed through the date, or a weekday with no session such as a market holiday), 4 a lock is held, 1 other error. The job's own exit code is the paper step's.
Paper state: `F:\Projects\Ravi\StockBot\state\live_state.db` (append-only journal; created on the first run with 200,000 INR) and one ticket file per processed session in `F:\Projects\Ravi\StockBot\state\tickets\` (both untracked, `state/` is in `.gitignore`). `STOCKBOT_RISK_PCT` must NOT be set (the runner refuses); `STOCKBOT_NON_EQ` defaults to `held` inside `paper_run.py`.
The task runs from the checkout, so the checkout MUST be on `master` (a merged branch carrying `scripts\daily_job.py`) when the task fires.

Replace the action of the existing task in place (keeps the trigger, the repetition and the settings):
```powershell
$py  = "C:\Users\ravit\AppData\Local\Programs\Python\Python313\python.exe"
$job = "F:\Projects\Ravi\StockBot\scripts\daily_job.py"
$act = New-ScheduledTaskAction -Execute $py -Argument "`"$job`" --scheduled" -WorkingDirectory "F:\Projects\Ravi\StockBot"
Set-ScheduledTask -TaskName "StockBot Daily Data Update" -Action $act
Get-ScheduledTask -TaskName "StockBot Daily Data Update" | Select-Object -ExpandProperty Actions     # check
```
Or remove and re-create it (same settings as the original block above, only `$job` changes):
```powershell
Unregister-ScheduledTask -TaskName "StockBot Daily Data Update" -Confirm:$false
$py   = "C:\Users\ravit\AppData\Local\Programs\Python\Python313\python.exe"
$job  = "F:\Projects\Ravi\StockBot\scripts\daily_job.py"
$act  = New-ScheduledTaskAction -Execute $py -Argument "`"$job`" --scheduled" -WorkingDirectory "F:\Projects\Ravi\StockBot"
$trg  = New-ScheduledTaskTrigger -Daily -At 19:30
$rep  = (New-ScheduledTaskTrigger -Once -At 19:30 -RepetitionInterval (New-TimeSpan -Minutes 20) -RepetitionDuration (New-TimeSpan -Hours 4)).Repetition
$trg.Repetition = $rep
$set  = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 3)
Register-ScheduledTask -TaskName "StockBot Daily Data Update" -Action $act -Trigger $trg -Settings $set -Description "NSE data update (sealed per day) then the momentum_calm paper step"
```
Plain `schtasks` (delete, then create with the new script):
```bat
schtasks /Delete /TN "StockBot Daily Data Update" /F
schtasks /Create /TN "StockBot Daily Data Update" /SC DAILY /ST 19:30 /RI 20 /DU 04:00 /TR "\"C:\Users\ravit\AppData\Local\Programs\Python\Python313\python.exe\" \"F:\Projects\Ravi\StockBot\scripts\daily_job.py\" --scheduled"
```
Roll back to the data-only job: repeat the first block with `$job = "F:\Projects\Ravi\StockBot\scripts\daily_data_update.py"`.
Check the paper side by hand (read-only): `py -3 F:\Projects\Ravi\StockBot\scripts\paper_run.py --date <YYYY-MM-DD>` only for a date the lake has sealed; look at `F:\Projects\Ravi\StockBot\state\tickets\`.
