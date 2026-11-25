# Android stage 5 report: the "Daily job" status screen and `GET /v1/job`

## Summary

The app has a fifth tab, **Job**, that answers "did tonight's job run?", and the BFF has a new read-only endpoint `GET /v1/job` behind it. Everything is read-only: no write endpoint, no trigger, no retry, no button that starts anything. The work was done on branch `android-jobstatus` in a temporary worktree (`..\StockBot_wt_jobstatus`, created from origin/master and removed at the end); the main folder stayed on `master` throughout. The running scheduler service (pid 9100) and the running BFF (pid 12136) were not touched and are still alive.

**The BFF that is already running was started before this endpoint existed, so it must be restarted to serve `/v1/job`.** I did not restart it. Until you do (after merging this branch: `bff\stop_bff.ps1`, then `bff\start_bff.ps1`; or stop pid 12136 and start it again), the real Job screen shows its calm one-line error with Retry; the other four screens keep working.

## What was built

- **Contract v1.1 (additive, apiVersion stays 1):** `GET /v1/job` in `openapi.yaml`, a section in `CONTRACT.md` (fields, state table), a section in `SOURCE_MAP.md`, and six example files (`job.json` = Done, `job_running.json`, `job_retrying.json`, `job_no_file.json`, `job_alert.json`, `job_service_off.json`). The examples are real output of the BFF's own builder on the real 23 to 25 Nov log, plus an invented earlier week (16 to 22 Nov) so the history has ten days.
- **BFF:** `bff\jobstatus.py` (log parser and state rules, pure), readers in `bff\sources.py` (log and rotated files, the instance file, the existence of the daily lock file, a safe "is this pid alive" check), the `/v1/job` route and models. It reads the scheduler log (rotated files included), `locks\scheduler_service.pid`, whether `locks\daily_update.lock` exists (never its content), the sealed date (same read as `/v1/health`) and `daily\calendar.csv`. Nothing is written or created; the token is never read or returned.
- **App:** a "Job" tab (the bottom bar now has five tabs). Top: a big state chip (colour, icon and word together), one plain sentence, service on or off, next attempt, data as of vs expected and whether it is behind. Below: the last 10 days as a strip of chips (weekday, icon, day of the month), then today's attempts (time, exit code, decision). Pull-to-refresh and refresh on open and on return, the offline copy with the usual "Can't reach your laptop. Showing data from ..." line, light and dark themes. There is no button that changes anything. Icons are drawn by hand (check, play, circular arrow, ring with a slash, triangle, clock, pause), so no icon library was added.
- **Mock data first:** the existing mock repository serves the six job examples (Done, Running, Retrying, No file, Alert, Service off); the debug menu (long-press the title) has a "Job screen" list, and adb takes `--es tab JOB --es jobscenario RETRYING`. The network repository is wired to `/v1/job` with the same parser, the 8 s timeouts, one retry and the offline copy as the other screens.

## The state rules (first match wins; per calendar day)

| State | Rule |
|---|---|
| DONE | an attempt that day ended with exit 0 |
| RUNNING | today only: an attempt began and no result is logged yet, or the data job's lock file exists (a lock wins over an earlier retry decision) |
| NO_FILE | the service stopped with its ALERT line and the last exit was 3 (the message says it is probably a market holiday) |
| ALERT | the service stopped with its ALERT line for any other reason (for example exit 5, a stale lock); a past weekday whose last answer was a retry or that has no attempt; today with no attempt after the window while the service is off |
| RETRYING | today only: the last logged decision was a retry; `nextAttemptAt` is the logged retry time |
| WEEKEND | Saturday or Sunday with no DONE (the service's normal exit 3 stop on a weekend has no alert) |
| WAITING | a weekday with no attempt yet and before 19:30 (or the service is up and it is not past 23:30) |

`nextAttemptAt` is null when the day is done or over, a job is running, or the service is off; while waiting it is 19:30 today. `service.running` is true when the instance file's pid is a live process (Windows OpenProcess and GetExitCodeProcess, never a signal) and the log's last service line is not "service stopped". An unknown state or decision from a newer server is shown as Alert in the app and never crashes.

## Tests run and results

- `py -m pytest tests\bff` (in the worktree): **269 passed** (it was 227; 42 new). New: `tests\bff\test_job.py` built from a copy of the real log (`tests\bff\fixtures\scheduler_service_real.log`): the real 25 Nov (DONE), the 24 Nov end of day (NO_FILE), 24 Nov evening (RETRYING with the next attempt), a still-running attempt, the lock-file rule, before 19:30 (WAITING) and service off, a weekday with nothing logged, Saturday and Sunday, another ALERT (exit 5), a retry that never got a final answer, "service stopped", the 10-day and 20-attempt limits, garbage and half-written lines, a fuzz test that the parser accepts any text, rotated files, a missing log (503), an unreadable log (503, never 500), a missing pid file and lake, no file written or created in `logs\`, `locks\` or `daily\`, the lock file's content never opened, no token in the answer, POST refused. `test_contract_models.py` now also validates the job examples and checks the job models against `openapi.yaml`.
- `gradlew test assembleDebug lintDebug --no-daemon`: **BUILD SUCCESSFUL; 97 JVM tests, 0 failures** (it was 84); lint **0 errors, 6 warnings** (the five dependency-version notices and the backup-rules notice; one more version notice than before). New: `JobStatusTest` (every example, the consistency of each example with its own state rules, the mock path, unknown values, word and colour mapping per state and theme, time and text formatting, the attempts list), plus job cases in the network repository test and the example-file test.
- Guide test only (`tests\unit\test_guides_consistent.py`): 11 passed, 1 skipped (needs `STOCKBOT_DATA_TESTS=1`). The whole repository suite and the backtests were not run (not asked for and they are heavy); "the whole suite stays green" was taken to mean the BFF suite and the guide test.
- Emulator screenshots (dark and light) in `docs\android\screens\stage5\`: `job-done-*`, `job-retrying-*`, `job-no_file-*`, `job-service_off-*` (8 images, sample data). The app did not crash on any of them.
- APK: `F:\Projects\Ravi\StockBotData\android\stockbot-paper-debug.apk` (new) and `stockbot-paper-debug-prev.apk` (the stage 4 build, kept). The phone was not touched.

## Anything uncertain

- **The brief said 13 attempts with exit 3 on 24 Nov; the real log has 12** (19:30, then retries at 19:50 and every 20 minutes to 23:11), then the ALERT. The tests use what the log actually says.
- **NO_FILE is inferred**, not read: the log has no "holiday" word. An exit 3 that lasted to the end of the day gives NO_FILE with a message that says it is probably a holiday. A real NSE outage would look the same.
- **A running job is only seen in two ways:** an attempt-start line with no result after it, or the data job's lock file. A backtest's run lock is deliberately not counted. If the service is killed mid-attempt, the dangling start line makes today read RUNNING until a later line appears.
- **Log times are local naive times**, read as IST (the laptop's zone). If the laptop's zone ever changed, they would be wrong.
- **The history only covers days the log covers** (it starts on 23 Nov) and shortens if the log rotates; days before it are not guessed. The six example files show ten days because the earlier week in them is invented.
- **Weekend attempts:** the service also attempts on Saturday and Sunday (exit 3, then a stop without alert), which is why a weekend with that line is WEEKEND with one attempt.
- **The contract test of `nextAttemptAt` on weekends before 19:30** returns 19:30 (the service does attempt on weekends); I did not check this against a real weekend log because none exists yet (23 to 25 Nov are weekdays).
- The Job screen needs the BFF restart above before it shows real data.
