# Daily data update: report (build and catch-up)

Branch `daily-data-update` (from master 74e41a8). No strategy folder, pre-registration, ledger row or stored result was touched. No backtest was run. The Task Scheduler task was NOT registered; paper trading was NOT started. STOPPED for the owner's review and merge.

## 1. Summary
- **Built:** one daily job, `scripts/daily_data_update.py` (logic in `stockbot/data/ingestion/daily_update.py`), and run locks (`stockbot/data/guard/runlock.py`). One session date at a time, oldest first; each day is sealed only after every writer and every check of that day passed; a failed day stays unsealed and stops the run.
- **Real catch-up done on `finsight.db`:** 22 session days loaded and sealed (2026-10-19 to 2026-11-18, including the Sunday Muhurat session 2026-11-08), 11 calendar dates with no file (NO_FILE), 0 failed days. Run first on a scratch copy (green), then on the real file.
- **Everything up to 2026-10-16 is unchanged:** per-table proof for all 26 existing tables (row count and sha256 of every row that existed before the run, plus the rows dated up to 2026-10-16): identical; `integrity_check` ok; guard audit ok (6,919 days, 6,291,683 rows); correction counter 0; no window open.
- **Seals now:** `market_data_lake` and `market_data_non_eq` through 2026-11-18; `asm_gsm_daily_snapshot` and `asm_gsm_snapshot_raw` through 2026-11-18 (the ASM/GSM snapshot of 2026-11-18 was taken in the same run: 180 ASM and 76 GSM rows).
- **Tests:** 26 new tests (fixtures: new day, sealed day, half-loaded day, unparsable price, NO_FILE and 3-day re-check, weekend with and without a file, locks in both directions, stale rule, byte-identical sealed history, audit). Full G2 on the real file with `STOCKBOT_DATA_TESTS=1` and `STOCKBOT_FINAL_CHECK=1` (both printed at the top of the log): **1,631 passed, 0 skipped, 0 failed** (29 min 36 s). A first G2 had 1 failure (the JSON data catalogue was stale after the catch-up: `test_the_row_counts_in_the_catalogue_equal_the_live_counts`); I regenerated `data_catalogue.json` from the real file (commit 1b79f7e, no code change) and re-ran the whole G2.
- **New file hash (information only):** `finsight.db` sha256 `72885644a16599a42253afa3110ab900d9c32b378a8d736b9b4498427912465e`, 3,594,948,608 bytes, `-wal` 0 bytes, unchanged by G2.

## 2. How it works
| Step | What |
|---|---|
| Download | Original bhavcopy, same URL patterns and order as `scripts/archive_raw_bhavcopy.py` (loaded from that script, so they cannot drift): UDIFF, FULL, LEGACY. Accepted only if the date INSIDE the file equals the requested date (a holiday returns the previous session's file: rejected). Saved UNMODIFIED to `F:\Projects\Ravi\StockBotData\raw_bhavcopy\YYYY\` (never overwritten; an existing file is reused after checking its sha256 against `MANIFEST.csv`) and a row `date,file_name,url,bytes,sha256,pattern,status` is added. |
| Parse first | The whole file is parsed before anything is written: unparsable or blank price, duplicate symbol, wrong date, no EQ rows = the day is REFUSED, nothing written, nothing zero-filled. |
| Write | EQ rows: `BhavcopyIngestor.store_day` (existing). BE/BZ/BL rows: new `store_day_non_eq` (refuses a sealed date before deleting; delete and insert in ONE transaction). Nifty 50 / India VIX rows (NSE index file `ind_close_all_DDMMYYYY.csv`, saved under `raw_index\`, Yahoo as fallback): new `write_index`, same rules. All writes open the database through `guard.connect_writer`; the SQLAlchemy writers use the new `writers.writer_session` (a real `BEGIN IMMEDIATE`, because `connect_writer` returns an autocommit connection and would otherwise make the delete and the insert separate transactions). |
| Checks | Row count per table equals the file's independent count (EQ; BE+BZ+BL total and per series); index and VIX rows present and positive; no (symbol, date) in both the lake and the BE/BZ rows; prices positive; every date inside the file equals the requested date; EQ count within 0.80 to 1.25 of the previous session (reported, blocks only when zero). |
| Seal | `market_data_lake` and `market_data_non_eq` sealed through the day in ONE transaction, only after all writers and checks passed. |
| Calendar | A session is any date for which NSE publishes a file; weekdays AND Saturdays/Sundays are tried and loaded only if a valid file with that exact date exists. No file after all URLs = NO_FILE, journalled in `F:\Projects\Ravi\StockBotData\daily\calendar.csv`; re-checked on each of the next 3 days (at most once per calendar day), then it stays a holiday. A network error is an ERROR (retried), never a holiday. Today's date before 23:45 IST with no file is PENDING (exit 3), not NO_FILE. |
| Stop rule | The run stops at the first day that fails (the seal only moves forward, so a later day is never loaded over a day that could still be filled). |
| Retry | Task Scheduler repetition: 19:30 IST, every 20 minutes for 4 hours (last at 23:30). With `--scheduled` the job attempts today's date only between 19:30 and 23:45; every run also catches up earlier missing dates, oldest first. Optional 08:30 `--catch-up-only` task for the morning re-check. |
| After the price days | ASM/GSM snapshot (only when today's session is loaded and sealed; both tables sealed only when BOTH lists were stored; source unavailable = reported, never blocks prices). Corporate actions (NSE range API, `corporate_actions_log` insert-only: new events added, identical skipped, a differing stored event reported and NOT changed; failure = reported). |
| Log and summary | `F:\Projects\Ravi\StockBotData\logs\daily_update_YYYYMMDD_HHMMSS.log`; one-screen summary (date, files downloaded, rows per table and series, checks, seal status, errors, exit code). `--plan` lists the dates it would check (no network, no write, no lock). |
| Exit codes | 0 done, 1 a day failed, 3 today's file not published yet, 4 locked by a run, 5 stale lock. |

### Locks (exact paths and rule)
- Folder `F:\Projects\Ravi\StockBotData\locks\` (`STOCKBOT_LOCK_DIR` overrides it). `daily_update.lock` is held by the daily job; `run_<pid>_<YYYYmmddHHMMSS>.lock` by each backtest / validation step / baseline. Each file is JSON (kind, pid, host, started_at, database file, label) and concerns one database file only.
- The daily job refuses to write while a run lock exists for the same database file (exit 4, the scheduler retries). A run refuses to start while the daily job holds its lock (`RunRefused`, exit 4).
- **Stale = older than 12 hours AND no live process with that pid.** It is reported, the caller exits with 5, and the lock is NEVER deleted silently (the message names the file and the `Remove-Item` command). A lock whose process is gone but is younger than 12 hours still blocks.
- Taken by: `run_backtest` (the shared runner), the `short_step` wrapper (gates, benchmarks, `validate_family`), and `fingerprint()` in `near_high_signal_count` (baselines and signal counts: held until the process exits).

## 3. Table of loaded days (real file; EQ rows / non-EQ rows (BE, BL, BZ) / index rows)
| Date | EQ | Non-EQ | BE | BL | BZ | Idx |
|---|---|---|---|---|---|---|
| 2026-10-19 | 2698 | 263 | 224 | 0 | 39 | 2 |
| 2026-10-21 | 2694 | 257 | 222 | 5 | 30 | 2 |
| 2026-10-22 | 2694 | 253 | 221 | 2 | 30 | 2 |
| 2026-10-23 | 2706 | 252 | 219 | 0 | 33 | 2 |
| 2026-10-26 | 2709 | 263 | 221 | 0 | 42 | 2 |
| 2026-10-27 | 2712 | 246 | 213 | 0 | 33 | 2 |
| 2026-10-28 | 2711 | 244 | 211 | 1 | 32 | 2 |
| 2026-10-29 | 2712 | 247 | 215 | 0 | 32 | 2 |
| 2026-10-30 | 2703 | 251 | 216 | 2 | 33 | 2 |
| 2026-11-02 | 2714 | 258 | 218 | 0 | 40 | 2 |
| 2026-11-03 | 2744 | 227 | 194 | 1 | 32 | 2 |
| 2026-11-04 | 2739 | 230 | 197 | 1 | 32 | 2 |
| 2026-11-05 | 2742 | 233 | 200 | 0 | 33 | 2 |
| 2026-11-06 | 2746 | 236 | 201 | 2 | 33 | 2 |
| 2026-11-08 (Sunday, Muhurat) | 2738 | 227 | 193 | 0 | 34 | 2 |
| 2026-11-09 | 2743 | 245 | 203 | 1 | 41 | 2 |
| 2026-11-11 | 2746 | 234 | 198 | 2 | 34 | 2 |
| 2026-11-12 | 2748 | 235 | 200 | 1 | 34 | 2 |
| 2026-11-13 | 2744 | 241 | 206 | 1 | 34 | 2 |
| 2026-11-16 | 2760 | 238 | 197 | 0 | 41 | 2 |
| 2026-11-17 | 2760 | 230 | 191 | 5 | 34 | 2 |
| 2026-11-18 | 2756 | 225 | 191 | 0 | 34 | 2 |

All 22 days: every check ok, sealed. Rows added: `market_data_lake` 60,063 (EQ plus 44 index rows), `market_data_non_eq` 5,335, `corporate_actions_log` 119, `asm_gsm_daily_snapshot` 254, `asm_gsm_snapshot_raw` 2, `asm_gsm_snapshot_log` 2.

**Dates with no file (NO_FILE):** 2026-10-17, 10-18, 10-20, 10-24, 10-25, 10-31, 11-01, 11-07, 11-10, 11-14, 11-15 (weekends, plus weekday holidays such as 10-20 and 11-10; the full-file URL answered with the previous session's file on those, which is rejected). Journalled in `calendar.csv`; the 3-day re-check applies to the ones within three days of today (11-14, 11-15).

## 4. Every shared file touched
| File | Why |
|---|---|
| `stockbot/backtest/runner.py` | `run_backtest` takes and releases the run lock (the old body is now `_run_backtest`; behaviour otherwise identical) |
| `stockbot/data/guard/runcheck.py` | `short_step` takes the run lock around the step |
| `stockbot/data_checks/near_high_signal_count.py` | `fingerprint()` holds the run lock until the process ends (covers baselines and signal counts) |
| `stockbot/data/guard/writers.py` | new `writer_session` |
| `stockbot/data/ingestion/bhavcopy_ingestor.py` | new `store_day_non_eq` |
| `stockbot/data/ingestion/snapshot_asm_gsm.py` | the writer is now `run(db, date, ...)`, opens the database through `connect_writer`, raw and parsed rows in one `tx`; `main` calls it (existing tests unchanged and green) |
| `tests/conftest.py` | autouse fixture sends run locks of every test to a throw-away folder |
| `docs/guides/CODEBASE_GUIDE.md`, `codebase_guide_data.json`, `codebase_guide.html`, `DATA_GUIDE.md` (C.28), `data_guide_data.json`, `data_guide.html`, `data_catalogue.{md,json}` | new modules and script, non-EQ table now extended daily, catalogue regenerated from the real file |
| `docs/shared/db-guard/GUARD.md`, `docs/shared/non-eq-series/STATUS.md` | pointers to the daily job and locks |
New: `stockbot/data/guard/runlock.py`, `stockbot/data/ingestion/daily_update.py`, `scripts/daily_data_update.py`, `tests/unit/test_daily_update.py`, `docs/shared/daily-update/{STATUS,SCHEDULER}.md`, `proof_old_rows.py`. Outside the repository: `F:\Projects\Ravi\StockBotData\raw_bhavcopy\` (22 files and 22 `MANIFEST.csv` rows added), `raw_index\` (index files), `daily\`, `logs\`, and `finsight.db`. Not touched: every strategy folder, pre-registration, ledger row, stored result, `shared.yaml`.

## 5. What ran and what did not
Ran: backup verification (sha256 `4ce224bb…3057`, integrity ok); fresh read-only copy `F:\Projects\Ravi\Backups\finsight_pre_daily_update_2026-11-18.db` (sha256 `4538bf135364c39d5e6bf1f96915391187ef6f8a36ab5e010d979268c9d5fe8c` as expected, integrity ok, set read-only); the whole catch-up on a scratch copy (green: 21 days, per-table proof identical, audit ok); the same on the real file; per-table proof, audit and status on the real file; catalogue regeneration; full G2 twice (first: 1 failure, stale catalogue JSON; second: 1,631 passed, 0 skipped).
Did NOT run: any backtest; the Task Scheduler registration (commands only); paper trading; the scheduled retry loop itself (one manual run each on scratch and real; the window logic is covered by tests only); the optional 08:30 re-check.

## 6. Anything unsafe or to decide
1. **A late file behind a seal cannot be loaded.** The seal moves forward only. If a NO_FILE date later gets a file after a LATER day was already sealed, the load is refused (the lake is sealed through the later date) and needs a guard `correct`. Waiting for every NO_FILE to expire before loading the next day was rejected because every holiday would block the pipeline for 3 days. Real holidays have no file; the risk is a special session published late.
2. **Dead-process lock younger than 12 hours blocks.** After a crash or reboot mid-run the job exits with 4 on every retry until the lock is removed by hand or 12 hours pass (then it reports STALE, exit 5, and still waits for you to remove it). By design: never delete silently.
3. **Process ids can be reused** (the liveness check is by pid and host only); a stale lock whose pid was reused by another program counts as live.
4. **Corporate actions:** the daily range fetch (all equities, from 2026-10-17 to today + 45 days) inserted 119 new events; **85 fetched events differ from a stored row with the same key** (same symbol, ex-date and action type but different ratio or text) and were reported, not applied. They are not listed in a file; run the loader on a dump to inspect them. Corporate-action failure never blocks the price load (INSERT_ONLY table, late facts are allowed by design).
5. **Symbol renames:** new days use the symbol NSE prints that day; the lake stores the latest name for old dates (F2 relabelling). A rename after 2026-10-16 is not linked automatically (`symbol_links.csv`, `isin_symbol_map` are not extended by this job).
6. **BL rows share a symbol with EQ rows** by design (stage 2); the "no symbol in both tables" check therefore covers BE and BZ only, and reports the BL overlap as information.
7. **Rows `source`:** new EQ rows carry `source = nse_bhavcopy_raw`, index rows the index-file URL (or `yahoo:<ticker>`); the 12 sessions 2026-10-01 to 2026-10-16 still have `source` NULL (unchanged, sealed).
8. The date adapter of sqlite3 emits a DeprecationWarning (pre-existing `store_day` binding of a `date`); harmless on Python 3.13.

## 7. Database check
`finsight.db` after the run and after G2: sha256 `72885644a16599a42253afa3110ab900d9c32b378a8d736b9b4498427912465e`, 3,594,948,608 bytes, `-wal` 0 bytes; guard audit ok; correction counter 0; per-table proof identical for all 26 existing tables; every new day sealed. Pre-run backup: `F:\Projects\Ravi\Backups\finsight_pre_daily_update_2026-11-18.db`. Proof files and logs: `F:\Projects\Ravi\StockBot_scratch\daily\` (not committed).
