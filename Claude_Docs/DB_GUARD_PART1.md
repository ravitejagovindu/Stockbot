# DB guard, Part 1: inventory and proposal

Branch `db-guard` (from origin/master 683d5e8), docs only. Nothing was written to `finsight.db` (opened read-only and immutable; sha256 re-checked at the end of this report) and no code was changed. Measurements were taken from the real file read-only and from throw-away fixture databases. Part 2 starts only after your written approval.

## 0. Summary and decisions

**What the inventory found**
1. 25 tables, no views, 2 triggers (both on `trade_analytics_log`), 1 internal table (`sqlite_sequence`). The backtest and validation path reads only six: `market_data_lake`, `corporate_actions_log`, `earnings_symbol_map`, `earnings_api_raw`, `earnings_board_meeting` (and `earnings_results_filing` through the data checks). The paper/live read path also reads `asm_gsm_daily_snapshot`.
2. **R1 already half exists.** `stockbot/data/lake.py: open_lake` opens `mode=ro` plus `PRAGMA query_only` and every backtest, baseline, validation and live-read script uses it. Six baseline scripts and four signal-count scripts already hash the file before and after. What is new is putting the hash in every run's manifest and marking a difference INVALID.
3. **No code or test compares the real file to the pinned hash.** The pin lives in procedure text (BRIEF/RUN_COMMANDS/PREREGISTRATION in strategy folders, `docs/restructure/BASELINE.md`), in `check_all.py` (prints size and mtime for a human to compare) and in recorded `data_snapshot` blocks. Section 3 lists every place.
4. **The file is in WAL mode** (header bytes 2/2; `finsight.db-wal` is 0 bytes, `-shm` is touched by every read-only connection). `stockbot/data/db/connection.py` runs `PRAGMA journal_mode=WAL` on every ORM connect, so any process that imports it against the real file can rewrite the header.
5. **Writers use `INSERT OR REPLACE`, `ON CONFLICT DO UPDATE` and delete-then-insert** (lake, securities, shares, corporate actions, earnings calendar). Under INSERT_ONLY/sealed rules those statements will be refused, which is the point, but each writer needs one reviewed change in Part 2 (section 2.3).
6. **A full-file sha256 takes 41 s of CPU but 8 min 14 s wall-clock when the disk is busy or cold** (measured). Two hashes per run (R1) therefore cost about 1.5 to 16 minutes, small against a research run (about 1.5 h) and large against a 30 s gates run (section 4.4).
7. Late-arriving corporate actions are the one thing the date rule cannot see: `corporate_actions_log` has `ex_date` up to 2026-11-06 (after the lake's last session 2026-10-16) and a backtest reads rows by `ex_date <= as_of`, so a row inserted later with an old ex_date changes past adjusted prices. INSERT_ONLY cannot stop that by design; R4 must record a content digest for such tables (section 2.2).

**Proposed classes (section 2):** 5 DATED_APPEND_ONLY (`market_data_lake`, `shares_outstanding`, `asm_gsm_daily_snapshot`, `asm_gsm_snapshot_raw`, `index_gap_fill`), 10 INSERT_ONLY (`corporate_actions_log`, `earnings_board_meeting`, `earnings_results_filing`, `earnings_api_raw`, `earnings_symbol_map`, `isin_symbol_map`, `securities_master`, `market_data_lake_yahoo_archive`, `account_ledger`, `trade_analytics_log`), 10 EXEMPT with reasons (staging, logs, legacy and live-state tables).

**Decisions I need from you** (recommended default first; detail in section 6.2):
| # | Decision | Recommended |
|---|---|---|
| D1 | Correction window form | `guard correct --reason R -- <sql file or command>`: open, run and close in ONE transaction (cannot stay open); keep `open-correction`/`close-correction` as a pair with a hard 15-minute expiry for interactive use |
| D2 | Counter for INSERT_ONLY tables | manifest records, per read table, a content digest (row count, max id, sha256 of rows); the correction counter covers only sealed/DATED changes and windows |
| D3 | File hash cost in R1 | hash before and after every backtest-type process, as designed (1.5 to 16 minutes per run, section 4.4); steps under 2 minutes may instead verify size, mtime, guard counter and sealed dates if you prefer |
| D4 | Reference tables (`securities_master`, `isin_symbol_map`) | INSERT_ONLY; changes to an existing row go through `guard correct`, and the change log is the version history |
| D5 | State database `state/live_state.db` | out of scope (separate file, append-only journal by design) unless you want it under the guard too |
| D6 | Backup | reuse `F:\Projects\Ravi\Backups\finsight_pre_restructure_2026-11-08.db` after verifying it equals `dcade…`, no new 3.4 GB copy (your single-backup policy) |
| D7 | Strategy folders that say "sha256 must be dcade…" | left as they are (historical); the migrated file has a new hash, the pre-migration backup stays the frozen reference |

## 1. Inventory

Source: `sqlite_master` of the real file (read-only, immutable), `MIN`/`MAX` on the date columns, and a scan of every `.py` file for each table name (read or write verbs). "Backtest reads" = read by `AsOfView`, `MemoryAsOfView`, the engine, the validation or the baseline code.

### 1.1 Tables

| Table | Rows | Date column(s), range | Primary / unique key | Backtest reads |
|---|---|---|---|---|
| market_data_lake | 5,634,334 (3,627 symbols incl. NIFTY50_INDEX 2,710 days, INDIA_VIX 3,077 days; `source` NULL on 2,515,960 rows, `nse_bhavcopy_raw` 3,118,323, a few yahoo/index csv) | trade_date 2013-01-01 to 2026-10-16 | id AUTOINCREMENT; UNIQUE(symbol, trade_date); sqlite_sequence 8,464,249 | **yes** (`asof.py:129,209,266,269,283`, `asof_memory.py:37`) |
| corporate_actions_log | 22,997 (DIVIDEND 20,912, SPLIT 452, BONUS 463, RIGHTS 341, DEMERGER 108, MERGER 91, OTHER 630) | ex_date 2010-01-04 to 2026-11-06; loaded_at 2026-11-07 | id; UNIQUE(symbol, ex_date, action_type) | **yes** (`asof.py:196,203`, `asof_memory.py:105,115`) |
| earnings_board_meeting | 164,819 | bm_date 2012-01-03 to 2026-11-07 | id; UNIQUE(query_symbol, row_hash) | **yes** (`asof.py:245`) |
| earnings_api_raw | 6,476 | fetched_at 2026-11-08 | (endpoint, query_symbol) | **yes** (`asof.py:235`, existence only) |
| earnings_symbol_map | 3,258 | none | (lake_symbol, query_symbol) | **yes** (`asof.py:225,227`) |
| earnings_results_filing | 173,410 | to_date 2005-02-28 to 2024-12-31 | id; UNIQUE(query_symbol, row_hash) | no (checks only: `earnings_coverage.py`, `earnings_validate.py`) |
| earnings_collect_log | 6,477 | at 2026-11-08 | none | no |
| asm_gsm_daily_snapshot | 253 | snapshot_date 2026-11-08 (one day) | (snapshot_date, framework, symbol) | paper/live read (`live/runner.py:98-102`); no backtest |
| asm_gsm_snapshot_raw | 2 | snapshot_date 2026-11-08 | (snapshot_date, endpoint) | no |
| asm_gsm_snapshot_log | 2 | snapshot_date 2026-11-08 | none | no |
| asm_gsm_list | 0 | effective_date | id; UNIQUE(symbol, framework) | no (legacy refresher) |
| market_data_lake_staging | 5,599,040 | trade_date 2013-01-01 to 2026-09-30 | UNIQUE(symbol, trade_date) | no (F2 provenance scripts only) |
| market_data_lake_yahoo_archive | 2,829,905 | trade_date 2020-01-01 to 2026-09-30 | id; UNIQUE(symbol, trade_date) | no |
| bhavcopy_fetch_log | 5,021 (OK 3,405; HOLIDAY_OR_MISSING 1,616) | trade_date 2013-01-01 to 2026-09-30 | trade_date | no |
| index_gap_fill | 51 | trade_date 2014-12-15 to 2026-09-30 | (symbol, trade_date) | no (merged into the lake by `f2_swap`) |
| isin_symbol_map | 853 | first_date/last_date 2013-01-01 to 2026-09-30; applied_at 2026-11-07 | none (no key) | no (the engine reads `data/reference/symbol_links.csv`, built by `scripts/build_symbol_links.py`) |
| securities_master | 2,965 | listing_date 1995-02-08 to 2026-10-22; created/updated 2026-10-21 | symbol | no |
| shares_outstanding | 2,217 (one snapshot, `yahoo_finance_current`) | effective_date 2020-01-01 only | id; UNIQUE(symbol, effective_date) | no (market-cap gate parked, KI-001) |
| regime_state | 1,747 | eval_date 2019-10-01 to 2026-10-16 | id; eval_date UNIQUE | no (legacy kill switch, UI) |
| pipeline_run_log | 11 | run_date 2026-10-01 to 2026-10-16 | id; run_date UNIQUE | no |
| active_positions | 0 | entry_date | id; UNIQUE(symbol, entry_date) | no |
| daily_watchlist | 0 | run_date | id; UNIQUE(run_date, symbol) | no |
| account_ledger | 0 | transaction_date | id | no |
| trade_analytics_log | 0 | exit_date | id; **own triggers `trg_tal_no_update`, `trg_tal_no_delete`** | no |
| earnings_calendar | 0 | event_date | id; UNIQUE(symbol, event_date, event_type) | no |
| sqlite_sequence | 7 | none | internal | n/a |

### 1.2 Who writes (file:line) and who reads (non-test code)

| Table | Writers | Other readers |
|---|---|---|
| market_data_lake | `stockbot/data/ingestion/bhavcopy_ingestor.py:156,163` (delete the day, then `to_sql` append); `ohlcv_ingestor.py:431` (INSERT OR REPLACE); `index_vix_ingestor.py:385-394` (ON CONFLICT DO UPDATE); `local_csv_ingestor.py:81` (to_sql); one-offs `scripts/provenance/f2_swap.py:82-188`, `fix_blocker1_index_data.py:65,67`, `ingest_historical_2018_2019.py:125,216` | data checks (`quality_checker`, `copy_detector`, `data_catalogue`, `f2_*`), `live/api/portfolio.py:47`, provenance scripts, `scripts/build_symbol_links.py`, addendum scripts |
| corporate_actions_log | `corporate_actions_ingestor.py:431` (ON CONFLICT DO UPDATE), `nse_corporate_actions_history.py:159,177`, `f2_load_corporate_actions.py:103`, one-off `f2_swap.py:97,101` | `f2_engine_scan`, `f2_verify_engine_path`, `build_symbol_links`, `stale_symbols_*` |
| earnings_* (5 tables) | `collect_earnings_history.py:52-67,195,211-227` (INSERT OR IGNORE; `earnings_api_raw` INSERT OR REPLACE only when fetched first time) | `earnings_coverage`, `earnings_validate`, `data_catalogue` |
| asm_gsm_* (daily, raw, log) | `snapshot_asm_gsm.py:40-48,107-126` (INSERT OR IGNORE); `merge_asm_gsm_snapshots.py:31` (`--apply`) | `live/runner.py:98-102`, `data_catalogue` |
| asm_gsm_list | `asm_gsm_refresher.py:395,411` | `models.py:96` |
| market_data_lake_staging | `ingest_raw_bhavcopy_range.py:37,191-199` (delete+insert per date) | F2 provenance scripts, `copy_detector`, `f2_*` |
| market_data_lake_yahoo_archive | `f2_swap.py:84,131` (one-off) | `f2_event_evidence.py`, `f2_post_swap_checks` |
| bhavcopy_fetch_log | `ingest_raw_bhavcopy_range.py:53,193,200` | provenance, `data_catalogue` |
| index_gap_fill | `f2_index_gap_fill.py:42,54`, `f2_index_gap_fill_yahoo.py:26` | `f2_swap.py:156,250` |
| isin_symbol_map | `f2_swap.py:180,184` (one-off) | `build_symbol_links`, `f2_*`, `collect_earnings_history.py:174,180` |
| securities_master | `securities_ingestor.py:100,133` (INSERT OR REPLACE), `migration_securities_master.py:12` | provenance triage, `f2_build_fund_symbols` |
| shares_outstanding | `shares_outstanding_ingestor.py` (ON CONFLICT DO UPDATE), `fix_blocker2_shares_outstanding.py:87` | `f2b_build_pit_shares` |
| regime_state | `scripts/provenance/regime/regime_filter.py` (upsert, ORM) | `live/api/regime.py`, `analytics_loop.py:50` |
| pipeline_run_log | `live/idempotency.py:88-93` (ORM) | `health_check.py` |
| active_positions, daily_watchlist, account_ledger, trade_analytics_log | `live/position_service.py:27-50`, `analytics_loop.py:132-155`, `live/api/ledger.py:52-74`, migrations | `live/equity.py`, `live/api/*`, `paper_report.py`, `validation/trade_metrics.py:19` |
| earnings_calendar | `earnings_calendar_ingestor.py` (ORM upsert) | none |

Tables are also created by code, not only by `schema.sql`: `collect_earnings_history.py` and `snapshot_asm_gsm.py` run `CREATE TABLE IF NOT EXISTS`; `init_db()` runs `schema.sql` (`live/main.py:47`). This is the R5 gap (section 4.5).

## 2. Proposed classes

### 2.1 Table by table

| Table | Class | Reason |
|---|---|---|
| market_data_lake | DATED_APPEND_ONLY on trade_date | the history every backtest reads; a day is loaded, then sealed |
| shares_outstanding | DATED_APPEND_ONLY on effective_date | point-in-time snapshot by date; not read by backtests today |
| asm_gsm_daily_snapshot | DATED_APPEND_ONLY on snapshot_date | one snapshot per day, read by the live path |
| asm_gsm_snapshot_raw | DATED_APPEND_ONLY on snapshot_date | the raw evidence of that day's snapshot |
| index_gap_fill | DATED_APPEND_ONLY on trade_date | record of rows added to the lake for index gaps |
| corporate_actions_log | INSERT_ONLY | facts can arrive late; no date rule; rows never change (needs the writer change in 2.3) |
| earnings_board_meeting, earnings_results_filing | INSERT_ONLY | collected facts, de-duplicated by row_hash |
| earnings_api_raw | INSERT_ONLY | raw response kept as first fetched; a refetch is a correction |
| earnings_symbol_map | INSERT_ONLY | mapping read by backtests; changes are corrections |
| isin_symbol_map, securities_master | INSERT_ONLY | reference tables, see 2.2 |
| market_data_lake_yahoo_archive | INSERT_ONLY | archive of rows replaced in F2; never changes again |
| account_ledger | INSERT_ONLY | a ledger of money movements is never edited |
| trade_analytics_log | INSERT_ONLY | already append-only by its own two triggers; the guard records it and keeps those triggers |
| market_data_lake_staging | EXEMPT | staging: raw bhavcopy is deleted and re-inserted per date by design |
| bhavcopy_fetch_log, asm_gsm_snapshot_log, earnings_collect_log | EXEMPT | fetch logs, rewritten on retry, not read by any result |
| regime_state | EXEMPT | legacy kill-switch state, derived from the lake, upserted per date |
| pipeline_run_log, active_positions, daily_watchlist | EXEMPT | live-system working tables (RUNNING to COMPLETE, positions updated daily); empty or tiny |
| asm_gsm_list, earnings_calendar | EXEMPT | legacy, empty, no reader |
| sqlite_sequence and the guard's own tables | exempt by construction | internal |

### 2.2 Reference tables and point-in-time reading
`securities_master` (symbol, company_name, series, listing_date, isin) and `isin_symbol_map` (isin, symbol, first/last date, class, canonical) are updated in place by their writers today. No backtest reads them: the engine reads the derived file `data/reference/symbol_links.csv` (its sha256 is already in every manifest). Proposal: INSERT_ONLY; a change to an existing row (rename, ISIN change) is a deliberate `guard correct` and the change log (time, key, before, after, reason) is the version history, so "what did we believe on date T" is answerable from the log without versioned copies. If a future strategy needs a point-in-time sector or listing status from these tables, the manifest records their content digest like every INSERT_ONLY table read (D2), and a dated view can be added then.
For INSERT_ONLY tables read by a backtest the correction counter is not enough, because a legitimate new row (a late corporate action) is not a correction yet changes what a past date sees. So R4 for INSERT_ONLY tables records `row_count`, `max_id` and a `sha256` over the rows (corporate_actions_log: 22,997 rows, well under a second; earnings_board_meeting 164,819 rows, a few seconds).

### 2.3 Writer changes Part 2 needs (all explained in the report; none done now)
| Writer | Statement now | Why it clashes | Change |
|---|---|---|---|
| `corporate_actions_ingestor.py:431` | ON CONFLICT DO UPDATE | updates existing rows | INSERT OR IGNORE; an update becomes `guard correct` |
| `securities_ingestor.py:100,133` | INSERT OR REPLACE | replaces rows | insert new symbols only; changes via `guard correct` |
| `ohlcv_ingestor.py:431`, `index_vix_ingestor.py:385-394`, `bhavcopy_ingestor.py:156,163`, `local_csv_ingestor.py:81` | upsert / delete-then-insert on the lake | a sealed date must be refused; an unsealed day may be deleted and reloaded | no change for unsealed days; each writer seals the day after a successful load (`guard seal`) |
| `shares_outstanding_ingestor.py` | ON CONFLICT DO UPDATE | updates snapshot | new `effective_date` per run; same-date refresh needs a correction |
| one-off `scripts/provenance/f2_swap.py` etc. | bulk replace | historic, finished | none (they would need a correction window if ever re-run) |

## 3. Everything that pins or checks the lake hash, mtime, size or last date

| # | Place | What it does now | Replacement under R1/R4 |
|---|---|---|---|
| 1 | `stockbot/backtest/manifest.py:37-39` `data_snapshot_id` | records file name, size, mtime_ns, last_session (no hash: "not hashed on every run") | add `sha256_before`, `sha256_after`, per-table guard record; keep size/mtime as labels |
| 2 | `stockbot/backtest/runner.py:41,74` | opens via `open_lake`; passes `lake_path` to the manifest | compute the before/after hash around the run; non-zero exit if different |
| 3 | `stockbot/data_checks/near_high_signal_count.py:458 fingerprint` (+ own copy `scripts/strategies/short_term_reversal/signal_count.py:437`) | path, size, mtime_ns, mtime_iso, sha256; used before/after | one shared helper in the guard module; the two copies call it |
| 4 | six baseline scripts (`baseline_matched_random_{lowvol_uptrend:281, near_52w_high:148, pullback_uptrend:148, riskadj_momentum:281, riskadj_momentum_daily:328, short_term_reversal:148}.py`) | fingerprint before/after; `baseline_meta.json` `finsight_db.unchanged` | same helper; INVALID on difference |
| 5 | four signal-count scripts (`signal_count_{lowvol_uptrend:144,162; riskadj_momentum:109,127; riskadj_momentum_daily:121,134; pullback_uptrend:338,345}.py`), `near_high_signal_count.py:511,523` | fingerprint before/after | same helper |
| 6 | `stockbot/data_checks/check_all.py:57` (G4) | prints size and mtime for a human to compare with `BASELINE.md` | prints guard status (installed, classes, counter, sealed dates) |
| 7 | `docs/restructure/BASELINE.md` row G4, CODEBASE_GUIDE.md lines 319, 426, 430, 750, 798, `codebase_guide_data.json` 1457, 1694 | text: "sha256/size/mtime must match the baseline" (read by guide tests only as text) | reworded to "guard installed, counter and sealed dates recorded"; the old hash stays as a label |
| 8 | strategy folders (BRIEF, PREREGISTRATION, RUN_COMMANDS, STATUS, counts, results): "sha256 must be dcade…" | instructions and recorded values | **not touched** (your rule). Historical results keep the old file. After migration a new run records the new file's hash; the backup is the frozen reference |
| 9 | tests comparing a FIXTURE file before/after: `test_near_high_signal_count.py:270-308`, `test_short_term_reversal_signal_count.py:237-240`, `test_asof_memory.py:172`, `test_engine_backtest.py:74` | check that a run did not change a fixture file | stay (they test the mechanism); `test_engine_backtest.py:74` extended for the new manifest fields |
| 10 | `stockbot/data_checks/data_catalogue.py:151,262` and `docs/guides/data_catalogue.{md,json}`, tests `test_data_catalogue_json.py:46`, `test_data_guide_html.py:194` | record db size and mtime of the measured file | regenerate after migration; the guides tests also require every `sqlite_master` object to be described in DATA_GUIDE.md (`test_guides_consistent.py:142,179`), so the guard tables and triggers need entries |
| 11 | `tests/data_integrity/*` (G2, env-gated) | read-only on the real file; no pinned hash or row counts in code | unchanged |

There is no test or script that fails when the real file's hash differs from `dcade…`.

## 4. How R1 to R6 work in SQLite

### 4.1 Guard state (all in the same file, names prefixed `_guard_`)
```sql
CREATE TABLE _guard_registry(tbl TEXT PRIMARY KEY, class TEXT NOT NULL,        -- DATED_APPEND_ONLY | INSERT_ONLY | EXEMPT
                             date_col TEXT, key_cols TEXT, reason TEXT);       -- reason required for EXEMPT
CREATE TABLE _guard_seal(tbl TEXT PRIMARY KEY, sealed_through TEXT NOT NULL,   -- ISO date; '0000-00-00' = nothing sealed
                         sealed_at TEXT, sealed_by TEXT);
CREATE TABLE _guard_day_checksum(tbl TEXT, day TEXT, n_rows INTEGER, sha256 TEXT, sealed_at TEXT, PRIMARY KEY(tbl, day));
CREATE TABLE _guard_window(id INTEGER PRIMARY KEY CHECK(id=1), is_open INTEGER NOT NULL, reason TEXT, opened_at TEXT, expires_at TEXT, opened_by TEXT);
CREATE TABLE _guard_counter(id INTEGER PRIMARY KEY CHECK(id=1), corrections INTEGER NOT NULL);
CREATE TABLE _guard_change_log(id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, tbl TEXT, op TEXT, key TEXT, before_json TEXT, after_json TEXT, reason TEXT, correction_no INTEGER);
```
The state tables are themselves protected: no delete; `_guard_seal.sealed_through` may only move forward unless a window is open; `_guard_change_log` and `_guard_day_checksum` are insert-only; `_guard_window` and `_guard_counter` change only through the open/close path (the counter only goes up).

### 4.2 Trigger sketch (generated per table by the guard module from the registry; shown for `market_data_lake`)
```sql
-- is the window open? = (SELECT is_open FROM _guard_window)=1 AND (SELECT expires_at FROM _guard_window) > strftime('%Y-%m-%dT%H:%M:%f','now')
CREATE TRIGGER g_mdl_bi BEFORE INSERT ON market_data_lake
WHEN NEW.trade_date <= (SELECT sealed_through FROM _guard_seal WHERE tbl='market_data_lake') AND NOT <window open>
BEGIN SELECT RAISE(ABORT,'guard: market_data_lake is sealed through <date>; use guard correct to add or change sealed rows'); END;
CREATE TRIGGER g_mdl_bu BEFORE UPDATE ON market_data_lake
WHEN (OLD.trade_date <= <sealed> OR NEW.trade_date <= <sealed>) AND NOT <window open> BEGIN SELECT RAISE(ABORT,'guard: sealed row; update refused'); END;
CREATE TRIGGER g_mdl_bd BEFORE DELETE ON market_data_lake
WHEN OLD.trade_date <= <sealed> AND NOT <window open> BEGIN SELECT RAISE(ABORT,'guard: sealed row; delete refused'); END;
-- change log while a window is open (AFTER triggers write json_object of every column):
CREATE TRIGGER g_mdl_lu AFTER UPDATE ON market_data_lake WHEN (OLD.trade_date <= <sealed> OR NEW.trade_date <= <sealed>) AND <window open>
BEGIN INSERT INTO _guard_change_log(at,tbl,op,key,before_json,after_json,reason,correction_no)
 VALUES(strftime('%Y-%m-%dT%H:%M:%f','now'),'market_data_lake','UPDATE',OLD.symbol||'|'||OLD.trade_date,json_object(...OLD...),json_object(...NEW...),<reason>,<counter>); END;
-- same for AFTER INSERT (back-dated) and AFTER DELETE.
```
INSERT_ONLY adds: BEFORE UPDATE and BEFORE DELETE always refuse (outside a window); BEFORE INSERT refuses when a row with the same key already exists (`WHEN EXISTS(SELECT 1 FROM t WHERE <key cols> = NEW.<key cols>)`), which is what stops `INSERT OR REPLACE` (SQLite's REPLACE deletes the old row without firing DELETE triggers unless `recursive_triggers` is on, so the delete trigger alone is not enough).
Details that matter: the date test uses `<=` on ISO text (all date columns are ISO text; `DATE` affinity stores text); an `UPDATE` that moves a row across the seal is refused (the OLD **or** NEW date test); `ON CONFLICT DO UPDATE` fires the BEFORE UPDATE trigger, so upserts of sealed rows are refused too.

### 4.3 Seal, window, audit
* `seal <table> <date>`: one transaction; checks the table has no row dated after `<date>` that was not meant to be sealed (shows the count, requires `--yes` beyond the row-count of the most recent load day); writes per-day checksums for every day in `(old sealed_through, date]`; then moves `sealed_through` forward. Moving it back needs a window.
* **Window.** `open-correction "<reason>"` sets `is_open=1, reason, opened_at, expires_at = now + 15 min (hard maximum)`, and increments `_guard_counter`; `close-correction` clears it. The triggers test `expires_at > now`, so a window forgotten open is inert after 15 minutes without anyone closing it, and every guard command first closes an expired window and prints it. Recommended primary form (D1): `guard correct --reason R -- <sql file>` opens, runs the SQL, closes and re-checksums the touched days in one transaction; the window never exists outside that transaction. Runs refuse to start (INVALID) while a window is open (R4 records `window_open`).
* **Audit.** Recomputes the per-day checksums of sealed days (only the days stored) and prints every day whose checksum or row count differs, the registry/trigger comparison (missing triggers = reported), and any change-log gap. Needs a full pass over the sealed tables (estimate 1 to 3 minutes for the lake at 5.6M rows, to be measured in Part 2); not run per backtest.

### 4.4 Cost
Measured on fixture databases only (a lake-shaped table with the real indexes), 300,000 rows loaded in 2,000-row day batches; trigger = one lookup in the one-row seal table plus the window row per inserted row, AFTER triggers fire only when a window is open:

| Measurement (fixture, 300,000 rows, 3 runs each) | no guard | guard (3 triggers + state tables) |
|---|---|---|
| In memory, insert CPU per row | 6.5, 7.6, 7.3 µs | 11.5, 12.6, 11.9 µs (about +5 µs a row) |
| In memory, one 2,000-row day | 14 to 17 ms | 25 to 26 ms (about +9 ms) |
| On disk (fsync off), per row | 99, 80 µs | 100, 75 µs (the difference is inside the run-to-run noise of this disk) |
| On disk with an fsync per day, per row | dominated by the disk: 0.4 to 0.9 s per commit measured while the disk was busy | same |

Reading: the trigger adds about 5 µs of CPU per inserted row. A one-day load of about 2,100 rows costs about +10 ms; a 2,700-day, 5.6M-row bulk load costs about +26 s of CPU on top of a disk-bound load that takes minutes (the same fixture takes 80 to 100 µs a row on disk, which is 8 to 9 minutes for 5.6M rows, with or without the guard). SELECT cost is zero (no trigger fires).

Extrapolation, labelled as an estimate: a one-day insert (about 2,100 rows) adds a few milliseconds; a 2,700-day bulk load (5.6M rows) adds per-row overhead times 5.6M (see the figures above); the seal step adds the checksum pass (one indexed read per day, about 2,100 rows a day). R1's two full-file sha256 hashes: measured 41 s CPU, 8 min 14 s wall-clock on this machine with a busy disk, so **budget 1.5 minutes warm to about 16 minutes cold per backtest-type run**. Because the hash is a safety check and not a result, I suggest it stays "before and after the whole run" (research, baseline) and that the very short steps (gates, benchmark) hash once at start and once at end of their own process, which is the same cost scale as their 30-second runs; if you prefer, shorter steps can verify `size + mtime_ns + guard counter + sealed dates` and leave the full hash to the long steps (D3).

### 4.5 R5 (uniform), what cannot be enforced in the schema
SQLite has no trigger on `CREATE TABLE`. R5 is therefore three things: (a) `guard install` registers every existing table and refuses to finish while a table is neither guarded nor on the exempt list with a reason; (b) every writer connects through `guard.connect_writer(path)` which calls `ensure()` (installs triggers for any registered table that lacks them and reports an unregistered table); (c) a test builds a fixture database through every table-creating path (`schema.sql`, the `CREATE TABLE IF NOT EXISTS` blocks in `collect_earnings_history.py` and `snapshot_asm_gsm.py`) and fails if a table is unregistered, plus the same check on the real file in G2.

### 4.6 ATTACH, copies, backups
Triggers and state tables live in the file, so a byte copy, `VACUUM INTO`, the backup API or `.dump` carry the guard (a copy has its own seal and counter, and its window state if one was open: a scratch copy can be corrected freely without touching the original). `ATTACH` of a guarded file: writes to its tables from any connection fire ITS triggers (trigger bodies resolve names inside their own database). The reverse, an unguarded connection attaching a guarded file, is protected as well. A new file made by `to_sql` into a fresh database, or by `CREATE TABLE AS`, is not guarded; R4 records the guard state and the manifest says "guard absent" for such a file.

### 4.7 What cannot be prevented (stated plainly)
1. `DROP TRIGGER`, `DROP TABLE`, `ALTER TABLE`, `PRAGMA writable_schema=ON`: SQLite has no DDL triggers. A person or script that removes the triggers can then change sealed rows. R6 (per-day checksums) detects that afterwards; it does not stop it.
2. Replacing, deleting or editing the file outside SQLite (copying an old file over it, a hex edit). R1's before/after file hash catches it for runs; the audit catches content changes.
3. Raising `sealed_through` by anyone seals more history (that only adds protection) and an accidental seal of a half-loaded day is possible; `seal` guards against it with the row-count check, nothing in the file does.
4. A writer that uses a different file never touches the guard.
5. The window is trusted as a flag: any process can open it with one `UPDATE` on `_guard_window`. To make that visible rather than impossible, a trigger on `_guard_window` writes the opener's reason/time to the change log and increments the counter, so a window opened outside the tool still leaves a counter change and an entry (reason empty).
6. Rows after the sealed date are free by design.

## 5. Migration of the real file (Part 2 step 6, for approval)
1. Stop writers: nothing else is running against the file (no ingest job exists today; confirmed by `tasklist` and the unused `-wal` of 0 bytes).
2. **Backup.** `F:\Projects\Ravi\Backups\finsight_pre_restructure_2026-11-08.db` (3,432,767,488 bytes) was recorded as byte-equal to today's file; verify its sha256 equals `dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752` and `PRAGMA integrity_check` is `ok`; if it does, no new copy is made (D6). If it does not, copy the live file to `F:\Projects\Ravi\Backups\finsight_pre_dbguard_<date>.db` (about 4 to 16 minutes, 116 GB free) and verify the copy against `dcade…`.
3. **Proof of content, before.** For every one of the 25 tables: row count and a sha256 over all rows (every column, ordered by primary key or rowid, in a fixed text encoding), computed by a read-only script, plus `PRAGMA integrity_check` and the schema text of the 25 tables and 2 triggers. Measured expectation: a few minutes for the three multi-million-row tables.
4. **Apply** (`guard install`): one transaction creating the `_guard_*` tables, registering the 25 classes, writing the seals (`market_data_lake` sealed through 2026-10-16, the other DATED tables through their last date; this is a proposal for you to confirm in D8 below), computing per-day checksums, creating the triggers. Existing triggers on `trade_analytics_log` stay.
5. **Proof of content, after.** The same per-table checksums and counts; they must be identical for all 25 tables; the schema text of the 25 tables unchanged; `integrity_check` ok. Only the new objects differ.
6. **What the new hash is for**: information only (the new file's identity in later manifests as "post-guard file hash"); no code or test compares it to a pinned value.
7. **Rollback**: restore the backup over the live file (hash-verified), or `guard uninstall` (drops triggers and `_guard_*` tables, leaves data), then the same per-table proof against the "before" numbers. Both are tested on a scratch copy first.
8. Then full G2 on the real file.

## 6. Risks and open questions

### 6.1 Risks to backtest correctness (must be none) and how it is proved
* Triggers fire only on INSERT/UPDATE/DELETE; they are never evaluated by SELECT, so no query a backtest issues is changed. The engine, `AsOfView` and `MemoryAsOfView` run only SELECTs through `open_lake` (`mode=ro`, `query_only`).
* New tables are not referenced by any query; `_has_table` checks name specific tables only.
* The memory view loads `market_data_lake` and `corporate_actions_log` by `SELECT` on the same rows.
* **Proof in Part 2:** (i) per-table content checksums before/after the migration (identical); (ii) every existing golden, parity and digest test unchanged and byte-identical, run on a scratch copy with the guard installed (G1, full G2, G3), including `tests/data_integrity/test_asof_view_real_db.py`, the SQL = memory equivalence tests and the engine scan; (iii) the manifest-based proof: the research step re-run is NOT done (registered results are never re-run); instead the fixture-lake backtest (G3 baseline reproducibility, the 120-sample as-of equivalence) is run with and without the guard and its outputs compared byte for byte.
* The one behavioural risk is a writer that today silently replaces a sealed row and will now be refused. That is the intended effect; the writers in 2.3 are listed so none fails by surprise.
* ORM engine `PRAGMA journal_mode=WAL` stays as is; guard installation does not change the journal mode.

### 6.2 Open questions with recommended defaults
| # | Question | Recommended default |
|---|---|---|
| D1 | Correction window shape | one-command `guard correct` plus the 15-minute-expiry pair (section 4.3) |
| D2 | Manifest record for INSERT_ONLY tables read | row count, max id, sha256 of rows (section 2.2) |
| D3 | Hash in short steps | hash before/after every process (safety), accept the cost; or `size+mtime+counter+sealed` for steps under 2 minutes |
| D4 | Reference tables | INSERT_ONLY + change log as history |
| D5 | `state/live_state.db` (the engine journal) | out of scope for now |
| D6 | Backup | reuse the verified `pre_restructure` copy |
| D7 | Old strategy docs naming `dcade…` | untouched; new file hash is a new label |
| D8 | Initial seal dates | each DATED table sealed through its last date today (lake 2026-10-16; the 2026-10-01..16 lake sessions with `source` NULL stay sealed as they are: they came from the old pipeline and were never compared to raw, see daily-ingest INVENTORY) |
| D9 | Day checksum content | all columns except `id`, `created_at`, `loaded_at` (surrogate and timestamps change on a legitimate reload) |
| D10 | `corporate_actions_log` rows with `ex_date` after the last lake session (2026-11-06 > 2026-10-16) | allowed (INSERT_ONLY has no date rule) |
| D11 | Existing CLI naming | `py -3 scripts/guard.py install|status|seal|open-correction|close-correction|audit` plus `correct`, module `stockbot/data/guard/` |
| D12 | Writers' `seal` call | each ingestion command seals its day after a successful load (a flag-less default; `--no-seal` for dry runs) |

### 6.3 Shared files Part 2 would touch (none touched in Part 1)
`stockbot/data/lake.py` (guard-aware open + hash helper), `stockbot/backtest/manifest.py` and `runner.py` (R4 fields, INVALID), `stockbot/data_checks/near_high_signal_count.py` and `scripts/strategies/short_term_reversal/signal_count.py` (fingerprint → shared helper), the six `baseline_matched_random_*` and four `signal_count_*` scripts and `validate_family.py` (manifest fields), `stockbot/data_checks/check_all.py`, `stockbot/data/db/connection.py` and `schema.sql` (guard-aware creation), the ingestors listed in 2.3, `tests/unit/test_engine_backtest.py`, new tests, `docs/guides/*` (DATA_GUIDE, guide JSON/HTML, catalogue; tests require them), `docs/restructure/BASELINE.md`. Each will be listed with its reason in the Part 2 report. No strategy folder, pre-registration, ledger row or stored result is touched.

## 7. Database check
`finsight.db` sha256 at the end of Part 1: `dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752` (unchanged; the file was only opened read-only and immutable). Fixture benchmark scripts are in the session scratchpad, not in the repository.
