# momentum_calm paper set-up report (branch `paper-setup`, 2026-11-20)

## Summary
- **Done:** momentum_calm now has a paper path that runs on its own: `scripts/daily_job.py` (data step, then `scripts/paper_run.py` only if the data step exited 0). No manual fill, report or other manual step is needed, so no design note was written (step 6).
- **Paper spec:** a separate object `PAPER_SPEC` = the registered spec with ONLY `status` changed. The registered `SPEC` and its hash are untouched, so no registered-run check is affected. Rule hash identical; config hash differs (status is part of it).
- **Account:** 200,000 INR, no deposits or withdrawals, created once by the paper step. It is kept out of `shared.yaml` on purpose: `runtime.paper_start_equity` is part of `shared_config_hash`, which every registered manifest records.
- **Step 4:** the 85 known notes-prefix differences are now treated as identical. On the saved 2026-11-18 fetch: 85 differences before, 0 after (205 identical). A changed ratio or other wording still counts.
- **Dry run (read-only):** first trading day of November 2026 (2 Nov): 10 tickets from 25 candidates; none skipped for rounding to zero shares in any of the 7 months checked.
- **Not done by design:** the Task Scheduler task was not changed (commands only, in `SCHEDULER.md`); nothing written to `finsight.db`; no strategy rule, parameter, gate or registered config changed.
- **Needs the owner's attention** (see Open issues): the 15% sector cap at this account size, the cash cap at fill, the merge before the task is switched, the missing paper-marks report.

## Step 1: how a paper run proceeds today (code read)
- `scripts/daily_job.py` did not exist. The data job is `scripts/daily_data_update.py`; the paper/live code is `stockbot/live` (`runner.run_eod`, `adapter.LiveAdapter`, `state_store.StateStore`, `scheduler.py`). The older tables and `paper_report.py` are not used by the new runner. Before this work nothing called `run_eod` with a non-empty book.
- `run_eod` (PAPER by default): refuses if `STOCKBOT_RISK_PCT` is set or `STOCKBOT_VIEW=memory`; takes the strategies with status `paper` or `live` (research never runs; LIVE needs status `live` plus a `validation_ref`); freshness check (the lake must hold session T); ASM/GSM names from the day's snapshot (missing = noted in PAPER); initialises the state DB if empty; `LiveAdapter.process` calls `engine.decide` once per unseen session (first run: only the latest session); writes one ticket JSON per session.
- **Signals** are computed on the close of session T from the lake (monthly: only the first trading session of a month). A ticket is created at T.
- **Fills** happen at the open of the NEXT session (T+1), inside `decide` (`execution.entry_fill: NEXT_OPEN`): fill = open x 1.001 (0.10% slippage), shared gap rules (gap through the stop, gap-up above 3%, corporate action that day), shares re-sized from the fill price and capped by cash. Exits: stop tested on every bar, sell with 0.10% slippage, shared costs (STT, exchange, SEBI, stamp, GST, DP charge 15.34 per sell).
- **Operator reports** (`FillReport`, `ExitReport`, `NotTakenReport`) are optional and override the engine's inference. With none, `decide` simulates everything. The adapter calls `decide` with `mode="live"`, so assumed fills and exits also carry `UNRECONCILED_*` flags (informational for paper).
- **State:** `state/live_state.db` (separate SQLite file; append-only journal with `init`, `effect`, `decisions`; snapshot cache; `rebuild()` agrees) and `state/tickets/tickets_<date>.json`. `state/` is untracked. `finsight.db` is only ever opened read-only. Idempotent per date.

## Step 2: the specs and hashes
| | status | config hash |
|---|---|---|
| registered `SPEC` (family_batch7 ledger rows) | research | `d215b84c5b2c340929a7bf4bef3d01e3da4f8e613d35fd0a9bc62edc96cbad55` |
| `PAPER_SPEC` | paper | `dec2618e221884515f8f15bc0a5370275251be3ff12bf97d0047510362bdf8be` |
| rule hash (sha256 of every field except status), both specs | | `f9f31b520eba0888777d06918447000a946dafdd282f66d3e2dcd058c58d4ff9` |

`tests/unit/test_momentum_calm_paper.py` asserts: registered hash unchanged, only `status` differs, rule hash equal, `validation_ref` empty (LIVE stays impossible). No registered file or test was edited and no registered-run check broke (full suite below). Why a separate object: editing `SPEC.status` would change the hash that the ledger rows and the run manifests carry.

## Step 3: account size, whole shares, zero-share rejection
- Start 200,000 INR (`PAPER_START_CASH`), written once as the `init` journal row. The state store has no deposit or withdrawal path and none was added. Idle cash earns nothing; risk 1.0%, 12 positions, caps unchanged.
- Sizing is `floor(equity x 1% / (entry - stop))`; fewer than one share is rejected as `SIZE_ZERO` (at ticket time and again at fill, after the cash cap). Covered by a test.
- Read-only count (`dryrun_summary.md`), the 7 latest monthly signal dates, top 25 candidates each:

| signal date | tickets | skipped: rounds to 0 shares | blocked by risk caps | total ticket value INR |
|---|---|---|---|---|
| 2026-11-02 | 10 | 0 | 15 | 194,894 |
| 2026-10-01 | 8 | 0 | 17 | 172,492 |
| 2026-09-01 | 11 | 0 | 14 | 232,245 |
| 2026-08-03 | 11 | 0 | 14 | 236,529 |
| 2026-07-01 | 9 | 0 | 16 | 184,985 |
| 2026-06-01 | 11 | 0 | 14 | 195,220 |
| 2026-05-04 | 10 | 0 | 15 | 215,679 |

Zero skipped for rounding. But 11 of the 70 tickets have a rounded-down risk below 1,800 INR (more than 10% under the 2,000 target); for example NAVINFLUOR at about 8,400 INR gets 2 shares, risk 1,789.

## Step 4: daily-update comparison
`stockbot/data/ingestion/daily_update.py`: `split_known_prefix_differences` removes from the "differs, not applied" list a row whose ratios are equal and whose stored notes equal `feed_symbol=<SYM>; ` + the fetched notes (same symbol). Stored rows are never changed. A test was added to `tests/unit/test_daily_update.py` (prefix-only is not a difference; other wording, a changed ratio and a wrong symbol still are). Real check, read-only, on the saved `ca_2026-11-18.json` with the job's own parse and `split_new`: 85 differing before, 0 after (205 identical, 0 new; ALUFLUOR has been inserted since).

## Step 5: dry run
Read-only `engine.decide` on a fresh 200,000 account for 2026-11-02 (first trading day of November), through the as-of view of the lake opened read-only; no state DB, no ticket file, no order. ASM/GSM ranges for a past date are not available and were passed empty (the live run reads the day's snapshot). Output in `docs/strategies/momentum_calm/paper/`: `dryrun_2026-11-02.csv`, `_blocked.csv`, `dryrun_summary.md` and six earlier months.

| rank | symbol | ref price | stop | shares | risk INR | value INR |
|---|---|---|---|---|---|---|
| 25 | SBC | 65.34 | 58.68 | 300 | 1,998 | 19,602 |
| 24 | LAURUSLABS | 2,348.00 | 2,127.88 | 9 | 1,981 | 21,132 |
| 23 | SONACOMS | 905.95 | 819.67 | 23 | 1,984 | 20,837 |
| 22 | KTKBANK | 298.40 | 263.40 | 57 | 1,995 | 17,009 |
| 18 | ANANDRATHI | 2,276.90 | 2,094.75 | 10 | 1,822 | 22,769 |
| 16 | HONASA | 452.75 | 403.33 | 40 | 1,977 | 18,110 |
| 15 | NAVINFLUOR | 8,406.00 | 7,511.44 | 2 | 1,789 | 16,812 |
| 6 | GESHIP | 1,600.40 | 1,452.25 | 13 | 1,926 | 20,805 |
| 4 | LLOYDSME | 1,825.10 | 1,674.71 | 13 | 1,955 | 23,726 |
| 2 | THELEELA | 671.05 | 579.88 | 21 | 1,915 | 14,092 |

(Rank 25 = best score. The other 15 of the 25 candidates were blocked by the 15% sector cap.)

Also rehearsed end to end on a TEMPORARY state database (not the real one), 2 Nov to 19 Nov through `paper_run.py`: the 10 tickets of 2 Nov filled on 3 Nov at open x 1.001 (for example SBC 65.3653, 299 shares after the cash cap); 8 positions were open on 19 Nov; the journal rebuild equals the snapshot; re-running a date changed nothing. The temporary files were not kept.

## Step 6: how fills are recorded
Automatic. Price source: the lake's next-session open (split-adjusted bar). Slippage 0.10% each way (shared `execution`), costs from the shared `costs` section (`CostModel`), the same `decide` code as the backtest. The adapter accepts manual reports but does not need them. No manual step exists, so no design note was written.

## Step 7: scheduler
Replacement commands for the 19:30 task are in `docs/shared/daily-update/SCHEDULER.md` (in-place `Set-ScheduledTask`, re-create, `schtasks`, roll-back). NOT run.

## Step 8: tests
Full suite once, `STOCKBOT_DATA_TESTS=1 STOCKBOT_FINAL_CHECK=1`: **1855 passed, 1 failed** (50 min). The one failure is `tests/unit/test_data_guide_html.py::test_the_row_counts_in_the_catalogue_equal_the_live_counts`: the data catalogue is out of date because the daily job has added rows to the lake since it was generated (for example `asm_gsm_daily_snapshot` 507 vs 758). It fails the same way with my changes stashed, so it is not caused by this work; regenerating the catalogue (`py scripts/gen_data_catalogue.py --json --json-only`) was out of scope and not done. New tests: `tests/unit/test_momentum_calm_paper.py` (7) and one in `test_daily_update.py`. CODEBASE_GUIDE rows added for `scripts/paper_run.py`, `scripts/daily_job.py`, `scripts/momentum_calm_paper_dryrun.py` and `stockbot/strategies/momentum_calm/paper.py`.

## What ran / what did not
Ran: every step above on branch `paper-setup`, lake access read-only only. Did not run: any Task Scheduler command; the real `paper_run.py` (it would create `state/live_state.db` and start the account before the owner starts the phase); any write to `finsight.db`; any backtest or validation job.

## Open issues
1. **Sector cap at this size.** The shared 15% sector cap is 30,000 INR and a typical position is about 20,000 INR, so each sector holds one position and 14 to 17 of the 25 candidates are blocked each month (8 to 11 tickets). Shared rule, unchanged; the paper book will hold fewer names than the 12-position backtest on 1,000,000.
2. **Cash cap.** In 2 of 7 months the tickets total more than 200,000 INR (232,245 and 236,529), so late fills are cut by cash (fewer shares than planned, risk under 1%) or rejected if less than one share is affordable.
3. **Whole-share rounding** lowers the realised risk on high-priced stocks (step 3).
4. **Branch and checkout:** the task runs from this folder; `scripts/daily_job.py` exists only on `paper-setup` until it is merged. Do not point the task at it before the merge. The folder was put back on master.
5. **Paper marks:** the shared `paper_criteria` (12% drawdown, 60 trades, 90 days) are unchanged; the owner's marks for this phase (below 35%, at least 30 closed trades) are not coded anywhere, and `stockbot/live/paper_report.py` reads the older tables, not the new state database. No report was built (the PAPER_DECISION note says no dashboard for now).
6. `decide` runs in the adapter with `mode="live"`, so paper tickets carry `UNRECONCILED_*` flags on every assumed fill and exit (informational).
7. Weekday holidays: `paper_run.py` exits 2 (lake not sealed through the date), so the task shows a non-zero last result on those days; harmless.
8. `STOCKBOT_NON_EQ=held` is set inside `paper_run.py` (setdefault); the data step does not depend on it.
