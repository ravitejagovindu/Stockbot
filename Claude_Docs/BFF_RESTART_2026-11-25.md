# BFF restart, 25 Nov 2026

## Verdict

**Done and working.** The main folder was updated to the stage 5 merge, only the BFF was restarted, and `GET /v1/job` now answers 200 with the expected values. The scheduler service (pid 9100) was alive before and after and was not touched.

## What was done

1. Main folder: branch `master`, tracked files clean. `git pull --ff-only origin master` moved it to **650bbba** "Merge android-jobstatus: daily job status screen and GET /v1/job, read-only (stage 5)".
2. Scheduler service pid **9100**: alive before, alive after (same pid).
3. BFF: `bff\stop_bff.ps1` stopped the old process (pid 12136); `bff\start_bff.ps1` started the new one, detached and minimized: **pid 13864**, listening on **100.125.195.111:8765** (the Tailscale address only), started 21:26:26. It will not survive a reboot (start it again with the script).

## Verification (token read from the token file, never printed)

| Check | Result |
|---|---|
| `GET /v1/health` | 200; status ok; dataAsOf 2026-11-25; expectedAsOf 2026-11-25; latestSealedDate 2026-11-25 |
| `GET /v1/job` | 200 |
| service.running | true (pid 9100, started 2026-11-23T17:43:25+05:30) |
| today.state | DONE (date 2026-11-25) |
| today.attempts | 1 (last exit code 0; "Done for the day. The job finished at 19:47.") |
| data.latestSealedDate | 2026-11-25 (expectedAsOf 2026-11-25); nextAttemptAt null |
| history | 2026-11-23 DONE (1 attempt); 2026-11-24 NO_FILE (12 attempts); 2026-11-25 DONE (1 attempt) |
| attempts listed | 17 (14 job attempts and 3 catch-ups) |
| `/v1/job` without a token / with a wrong token | 401 / 401 |
| token in the `/v1/job` answer | no |
| last 10 lines of `bff.log` | no error lines; the token is not in them (it is not anywhere in the file) |

The log's last lines also show the phone's two `/v1/job` requests at 21:25 getting 404 from the old BFF, which is what the restart fixed; the phone's next refresh will get the real answer.

## APK

`F:\Projects\Ravi\StockBotData\android\stockbot-paper-debug.apk` exists: 10,061,336 bytes, modified 25-11-2026 21:19:51. The previous build is `stockbot-paper-debug-prev.apk`: 10,225,806 bytes, modified 24-11-2026 20:23:04. Nothing was copied to the phone.

## Not done / notes

- No job, paper step or backtest was run; the scheduler service was not stopped, restarted or touched.
- The BFF does not start at boot; after a reboot or a Tailscale restart run `bff\start_bff.ps1`.
