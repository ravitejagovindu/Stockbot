# Non-EQ series, stage 2: report (build)

Branch `non-eq-series` (master 717f5cf merged by fast-forward). Own worktree only. No strategy folder, pre-registration, ledger row or stored result was touched. No backtest was run on the real lake and no re-evaluation was started. STOPPED for the owner's review.

## Summary
- **Built and migrated.** The table `market_data_non_eq` is in the real `finsight.db`: 589,172 rows (BE 517,788, BZ 68,190, BL 3,194), 2013-01-01 to 2026-10-16, sealed through 2026-10-16 (3,416 days), guard class DATED_APPEND_ONLY.
- **The 25 existing tables are identical** before and after (schema, row count, row digest of every table, including `market_data_lake` 5,634,334 rows). The only change in the compare is `sqlite_sequence`: two rows added (`market_data_non_eq` 589,172 and `_guard_change_log` 0). Nothing removed or changed. Integrity check ok before and after. Guard audit ok (6,873 days, 6,226,029 rows), correction counter 0, no unregistered table, no missing trigger.
- **Procedure followed.** Old backup verified (sha256 dcade465...b752, integrity ok). Fresh copy of the guarded file made, read-only, sha256 4ce224bb...3057, integrity ok. The whole backfill, guard install and seal ran first on a scratch copy; only when scratch was green (compare, audit, full G2) was the real file migrated.
- **Switch OFF reproduces every stored result.** `STOCKBOT_NON_EQ=held` is default OFF. With it off nothing in the engine reads the new table, the manifest has no `non_eq_view`, and the golden fixtures and the SQL-vs-memory equivalence tests pass byte-identically.
- **Tests.** Full suite on the code: 1,474 passed, 130 skipped, 0 failed (G1). Full suite on the scratch copy: 1,474 passed (G2 scratch). Full suite on the real migrated file: 1,474 passed, 130 skipped, 0 failed (G2 real). The new file `tests/unit/test_non_eq_series.py` has 37 tests (property test with 6 seeds, static `Position()` test, switch-off identity, SQL vs memory views, backfill checks).
- **Owner rule enforced in the shared engine:** a restricted series is never bought (`NOT_EQ_SERIES` at proposal, `NOT_EQ_SERIES_AT_FILL` at fill, also in `engine/path.py`); a held position may be held or sold; eligibility, ADTV, ranking and entries read EQ rows only.
- **The sell model is a fixed assumption, not evidence** (owner decision Q2): at most 10% of the bar's volume per session, exit slippage doubled, no fill on a single-price bar, limit rules as written.

## Owner decisions as built
- Q1: only BE, BZ, BL are loaded. Q2: the sell model of DESIGN section 5. Q3: eligibility unchanged. Q4: with the switch on, the held-position stop reference (highest close since entry) and the ATR of the strategy-owned exit policies read held bars (through `engine/held_view.py`, so no strategy file changed); with the switch off nothing changes. Q5: joins by ISIN. Q6: later, not now.

## What was built
- `stockbot/data/non_eq.py` (table DDL, switch, parsing of an archived file), registry rule in `stockbot/data/guard/registry.py`.
- `scripts/backfill_non_eq.py`: sha256 of every file against MANIFEST.csv (refuses on mismatch), independent per-day count (plain csv vs pandas), refuses a duplicate or unparsable price (nothing zero-filled), writes through `guard.connect_writer`, one transaction per year, per-day count check after loading, seal, WAL checkpoint, refuses a non-empty table.
- Engine reads: `held_raw_bars`, `held_adjusted_bars`, `series_on` in both views (`asof.py`, `asof_memory.py`); `held_bar_of` and the two gates in `decide.py`; `path.py`; `series_rule.py`; `held_view.py`; the stale rule `no_bars_for` reads held bars.
- Sell model in `engine/stepping.py` (only when a bar carries a non-EQ series, i.e. switch on).

## Deviations from DESIGN.md (and why)
- **The key includes `series`: UNIQUE (symbol, trade_date, series).** BL (block-deal window) rows share a symbol and date with EQ rows (3,104 days) or BE rows (50 days), so (symbol, trade_date) cannot be unique. BL is loaded (Q1) but never forms a bar; a bar is one row per day with priority EQ > BE > BZ.
- "Single-price low-volume bar" is read as high == low and volume < shares held.
- The remainder of a capped stop or queued exit is carried as a pending exit (`STOP_HIT`, flag `SELL_CAPPED_NON_EQ`) at the next open.
- The `END_OF_WINDOW` closure still uses the last close with normal slippage (not modelled for BE/BZ).

## Every shared file touched
`stockbot/data/guard/registry.py`, `stockbot/data/guard/runcheck.py` (the guard record names the new table only when the switch is on), `stockbot/data/asof.py`, `stockbot/data/asof_memory.py`, `stockbot/engine/decide.py`, `stockbot/engine/path.py`, `stockbot/engine/stepping.py`, `stockbot/engine/stale.py`, `stockbot/engine/exit_policy.py` (Bar gains `volume` and `series` with defaults), `stockbot/backtest/manifest.py` (adds `non_eq_view` only when the switch is on; not part of `shared_config_hash`), `scripts/archive_raw_bhavcopy.py` (date format and `--redo`), `tests/fixtures/real_schema.sql`, `tests/unit/test_db_guard.py` (26 tables, 6 DATED). New files: `stockbot/data/non_eq.py`, `stockbot/engine/series_rule.py`, `stockbot/engine/held_view.py`, `scripts/backfill_non_eq.py`, `tests/unit/test_non_eq_series.py`. Docs: `CODEBASE_GUIDE.md`, `DATA_GUIDE.md` (section C.28), `data_guide_data.json`, `data_guide.html`, `data_catalogue.{md,json}` (regenerated from the migrated file), `docs/shared/non-eq-series/STATUS.md`. Outside the repo: `F:\Projects\Ravi\StockBotData\raw_bhavcopy\` (one file and one MANIFEST row added, see below) and `finsight.db` (new table only).

## The 2020-07-13 EQ difference (finding)
Stage 1 reported 1,384 EQ rows in the file against 1,392 in the lake. **Cause: my archive script, not the lake.** The legacy file for that day writes its date as "13-Jul-20" (two-digit year), which the script's date parser rejected, so it kept the `sec_bhavdata_full` file, which lacks 8 EQ symbols (EXCEL, GISOLUTION, GTNTEX, HBSL, NAGREEKCAP, PRADIP, RADAAN, TREJHARA). The legacy original (`cm13JUL2020bhav.csv.zip`, sha256 fbb63a75...d9d88, 71,297 bytes) has 1,392 EQ rows, equal to the lake and to the F2 staging and fetch log. I fixed the parser (added "%d-%b-%y"), fetched the legacy file next to the other one (nothing overwritten; MANIFEST.csv gained one row, the last row of a date wins) and the backfill reads it. BE, BZ and BL counts are identical in both files, so the stage-1 BE/BZ/BL inventory is unaffected; only the stage-1 EQ count for that day (1,384) and the sentence "one difference" are corrected here. **The lake was not changed.**

## What ran and what did not
- Ran: archive verify (all 3,416 sha256 match), backfill on scratch and then on the real file, per-table proofs (backup vs scratch, backup vs real), integrity checks of both backups and of the scratch and real files, guard audit and status on scratch and real, G1, G2 scratch, G2 real, guide tests including the env-gated ones against the real file.
- Did not run: any backtest on the real lake, any re-evaluation of the registered runs, the daily job (it does not yet load non-EQ rows).

## New file hash (information only)
`F:\Projects\Ravi\StockBot\finsight.db` after the migration: sha256 `4538bf135364c39d5e6bf1f96915391187ef6f8a36ab5e010d979268c9d5fe8c`, 3,581,857,792 bytes. Pre-migration backup: `F:\Projects\Ravi\Backups\finsight_pre_non_eq_2026-11-17.db` (sha256 4ce224bb...3057, read-only).

## What remains unsafe
- The fill-model numbers (10%, double slippage, no fill on a single-price bar) are assumptions. Price band, queue position, a resting limit order and multi-day circuit locks are not modelled.
- Eligibility of a stock that returns to EQ after a long BE spell is unchanged (Q3).
- The lake and archive end on 2026-10-16 (Q6); the daily job does not yet load non-EQ rows or seal the new table, so any live use needs that job first.
- `DROP TRIGGER` and similar changes are detectable only by the guard audit, not prevented.
- The 2020-07-13 archive holds two files for that day; the backfill reads the legacy one.

## Addendum (2026-11-18): G2 on the real file with the data tests switched on
**Correction to the summary.** The "1,474 passed, 130 skipped" G2 on the real file above was run WITHOUT `STOCKBOT_DATA_TESTS=1` and `STOCKBOT_FINAL_CHECK=1`, so the env-gated tests were skipped. It was not comparable with the guard task's G2 (1,567 passed, 0 skipped) and should not have been reported as the real-file G2.

**The 130 skips (exact reasons).** 129 skipped on "needs STOCKBOT_DATA_TESTS=1 and the real database" (or the same text for the guide checks): `data_integrity/test_asof_view_real_db.py` 57, `data_integrity/test_corporate_actions_real_db.py` 58, `data_integrity/test_calendar_integrity.py` 3, `data_integrity/test_golden_frozen.py` 2, `data_integrity/test_entry_bar_real_lake.py` 1, `unit/test_data_guide_html.py` 6, `unit/test_guides_consistent.py` 1, `unit/test_market_switch.py` 1 ("real-lake replay: STOCKBOT_DATA_TESTS=1"). 1 skipped on "the allowlists must be empty at STOP 5 (run with STOCKBOT_FINAL_CHECK=1)" (`unit/test_import_boundaries.py`).

**Why the passed count looked lower.** The two runs have different totals, not different failures: guard task 1,567 tests (0 skipped); this task 1,604 = 1,567 + 37 new tests in `tests/unit/test_non_eq_series.py`. Passed fell from 1,567 to 1,474 only because 130 tests were skipped.

**Re-run.** Full G2 on the real `F:\Projects\Ravi\StockBot\finsight.db` with `STOCKBOT_DATA_TESTS=1`, `STOCKBOT_FINAL_CHECK=1` (both printed at the start of the log; `STOCKBOT_VIEW` and `STOCKBOT_NON_EQ` unset): **1,604 passed, 0 skipped, 0 failed** (1 h 44 min). No code was changed.

**After the run.** File sha256 `4538bf135364c39d5e6bf1f96915391187ef6f8a36ab5e010d979268c9d5fe8c`, unchanged (3,581,857,792 bytes, modified 2026-11-18 06:27, `-wal` empty). Guard audit ok (6,873 days, 6,226,029 rows checked, no problems), correction counter 0, no correction window open, no unregistered table, no missing trigger, change log 0 rows, `market_data_non_eq` registered DATED_APPEND_ONLY and sealed through 2026-10-16.
