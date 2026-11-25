# Status check, evening of 2026-11-25 (checked 20:40 IST, read-only)

## Verdict
**25 Nov DONE (data sealed, paper processed).** The 19:30 attempt ended `exit 0 -> done (done for the day)` at 19:47:49: the data step loaded and sealed 2026-11-25 (19:30:00 to 19:32:47) and the paper step processed the session (19:32:47 to 19:47:49, about 15 minutes), with no refusal, no retry and no ALERT. Nothing was started, stopped or changed by this check.

## 1. Service: OK
Exactly one scheduler_service process: pid 9100, started 2026-11-23 17:43:18 (same pid and start time: no restart). Pid file holds 9100, alive. Its only python sibling is the BFF (`bff\run.py`, pid 12136).

## 2. Service log: OK
2026-11-25: `19:30:00 attempt (19:30): daily_job.py --scheduled`, `19:47:49 attempt (19:30) exit 0 -> done (done for the day)`. One attempt, no retry, no ALERT (the earlier lines are 24 Nov: 13 attempts with exit 3, ALERT at 23:11, then the 08:30 catch-up on 25 Nov, exit 0). The service does not log the paper step separately; `daily_job.py` returns the paper step's exit code, so exit 0 means the paper step exited 0. At 20:40 no job subprocess is running (python processes: 9100 and 12136 only) and no run lock exists.

## 3. Data: OK
Newest data log `daily_update_20261125_193000.log` (19:30 to 19:32:47): `2026-11-25 LOADED BhavCopy_NSE_CM_0_0_0_20261125_F_0000.csv.zip EQ=2774 NON_EQ=211 BE=176 BL=3 BZ=32 INDEX=2 checks=ok sealed=True`; ASM/GSM stored and sealed; corporate actions already fetched today; `days loaded 1 | skipped 1` (the 2026-11-24 date, which had no file); exit code 0. `guard.py status --json`, sealed through: `market_data_lake` 2026-11-25, `market_data_non_eq` 2026-11-25, `asm_gsm_daily_snapshot` 2026-11-25, `asm_gsm_snapshot_raw` 2026-11-25 (`index_gap_fill` 2026-09-30 and `shares_outstanding` 2020-01-01 are unchanged historical tables). 2026-11-25 is loaded and sealed.

## 4. Paper: OK
`state\live_state.db` (read-only): 3 journal rows: `(1, init)`, `(2, decisions, 2026-11-23)`, `(3, decisions, 2026-11-25)`. as_of 2026-11-25; cash 200000.0; 0 open positions; 0 pending tickets; realised 0.0. Both decisions are empty (0 tickets, 0 fills, 0 exits, 0 blocked, no flags). There is no 2026-11-24 row, as expected: no session that day (no NSE file), and `decide` handled 2026-11-25 as the next session after 2026-11-23. `state\tickets\`: `tickets_2026-11-23.json` (204 bytes, 23-11 19:51:42) and `tickets_2026-11-25.json` (204 bytes, 25-11 19:47:48), both with `tickets: []`. paper_run processed 2026-11-25 (journal row written 19:47:48); no refusal: the day ended with exit 0.

## 5. BFF: OK
`GET /v1/health` with the token header (read from file, never printed): **200**, `status = ok`, `dataAsOf = 2026-11-25`, `expectedAsOf = 2026-11-25`, `latestSealedDate = 2026-11-25`; the body does not echo the token. The BFF therefore already serves the new day.

## 6. Locks: OK
`locks\` holds only `scheduler_service.pid` (50.9 h old, pid 9100 alive): the service's instance file, not a run lock. No run lock, no daily lock, no dead pid. Nothing removed.

## Main folder
`git branch --show-current` -> `master`; `git status --short --untracked-files=no` -> nothing; `git log -1` -> `72b828f Merge paper-bff...` (the main folder was not pulled).

## Notes
- No ticket was expected: the first possible signal is the first trading day of December (2026-12-01); its tickets appear in the 2026-12-01 run, fills on 2026-12-02. That run also does the heavier first-signal screen (253 bars per eligible symbol), so expect it to take longer than the 15 to 19 minutes of a no-signal day.
