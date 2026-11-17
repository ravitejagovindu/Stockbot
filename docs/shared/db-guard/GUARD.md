# The database guard (one page)

`finsight.db` is the ONE database. Readers cannot write to it; writers cannot change sealed history by accident; a deliberate change is explicit and logged. Code: `stockbot/data/guard/` (`registry.py`, `core.py`, `runcheck.py`, `writers.py`); command line: `py -3 scripts/guard.py`.

## The rules
| | Rule |
|---|---|
| R1 Readers | Backtests, research, baselines, validation and the paper/live read path open the file ONLY through `stockbot.data.lake.open_lake` (`mode=ro` plus `query_only`): a write raises an error. A test fails if a reading package opens a database any other way. |
| R1 Runs | A research or baseline run (long step) records the sha256 of the file before and after; a short step (gates, benchmark, validate_family, signal counts) records size, mtime_ns, the `-wal` size, the correction counter, the sealed dates and a digest of every insert-only table it reads. Any difference: `RUN INVALID`, exit code 3, message on stderr. Nothing compares the file with a fixed hash. The manifest of a backtest run carries the `db_check` block (file hashes, counter, sealed dates, digests before and after). |
| R2 Sealed history | Each DATED table has a sealed-through date. For rows dated on or before it: UPDATE, DELETE and INSERT are refused (inside the database, by triggers, so any script is covered). Rows after the date are free (a day being loaded) until a writer seals them: `seal TABLE DATE`. INSERT_ONLY tables refuse UPDATE and DELETE, and an insert that would replace a row with a different one; an identical re-insert is ignored, so idempotent loaders keep working. |
| R3 Corrections | A change to sealed or insert-only rows needs a correction window. Primary form: `py -3 scripts/guard.py correct --reason "why" -- fix.sql` runs the SQL file in ONE transaction (open, run, refresh the day checksums, close). While a window is open every changed row is written to `_guard_change_log` (time, table, key, before, after, reason) and the counter goes up. `open-correction "why"` / `close-correction` is the interactive pair: the window dies by itself after 15 minutes. A window opened with a plain UPDATE still raises the counter and writes a log entry. |
| R4 Traceability | Every backtest manifest says which tables the run read: class, sealed-through date, correction counter, row count / max id / sha256 of insert-only tables, and the file hash before and after. Unchanged counter, seals and digests = sealed history unchanged. |
| R5 Uniform | Every table has a class in `registry.py` (DATED_APPEND_ONLY, INSERT_ONLY, or EXEMPT with a written reason). `install` refuses an unregistered table; `ensure` (called by `connect_writer`) reports one and protects a registered table that lacks its triggers; a test fails if any code path creates a table with no class. |
| R6 Audit | At seal time a checksum of each day's rows (all columns except surrogate ids and load timestamps) is stored. `audit` recomputes them and reports any sealed day that differs, any missing or altered trigger, an unregistered table, an open window. It is not run per backtest. |

## Commands (`--db` defaults to STOCKBOT_DB)
`install [--seal max|none]` · `status [--json]` (read-only) · `seal TABLE DATE` · `correct --reason R -- FILE.sql` · `open-correction R` · `close-correction` · `audit` (read-only) · `uninstall --yes-remove-guard` (removes triggers and `_guard_*` tables; the data is untouched; the flag is required).

## How to add a table
1. Add one `Rule(...)` to `stockbot/data/guard/registry.py`: class, the columns that identify a row (`key`), the date column for a DATED table, the volatile columns (ids, load times) the "same row?" comparison and the day checksum leave out, and for EXEMPT a reason.
2. Create the table through the code that owns it, connect with `guard.connect_writer(path)` (or call `guard.ensure(con)` once): the triggers are installed. `status` must show no unregistered table, `audit` no problem.
3. A loader seals its day after a successful load: `seal TABLE DATE` (the daily job seals once ALL its lake writers have finished: the equity writer and the index/VIX writer share `market_data_lake`).
4. Add the table and its columns to `docs/guides/DATA_GUIDE.md` and the data guide JSON (the guide tests require it).

## How to correct a row
Write the SQL (`UPDATE ... WHERE ...;` statements separated by `;`) in a file and run `py -3 scripts/guard.py correct --reason "what and why" -- file.sql`. It prints the rows logged and the new counter. Every later run's manifest shows the new counter; runs that were open while it happened are INVALID. Never edit a sealed table with the triggers dropped: `audit` reports it (it cannot prevent it).

## What the guard cannot prevent
`DROP TRIGGER`, `DROP TABLE`, `ALTER TABLE`, `PRAGMA writable_schema` (SQLite has no DDL triggers): `audit` finds the result afterwards. Replacing or editing the file outside SQLite: the before/after file hash of a run catches it for that run. Opening a window with a plain `UPDATE _guard_window`: not prevented, but it leaves a counter change and a log entry. Rows after the sealed date are free by design. A new database made by `to_sql` into a fresh file is not guarded (the manifest then says "guard installed: false"). The separate live state database (`state/live_state.db`) is outside the guard.

## What the guard does not change
Every SELECT (triggers fire only on writes). The `-shm` file is not part of any check (every read-only connection to a WAL database touches it); a non-empty `-wal` file IS (the main file alone would not show the whole database). The ORM engine (`stockbot/data/db/connection.py`) no longer switches the journal mode of an existing file.

## Pre-guard reference file
The file as it was BEFORE the guard was installed is kept, read-only, as the **pre-guard reference file**: `F:\Projects\Ravi\Backups\finsight_pre_restructure_2026-11-08.db`, 3,432,767,488 bytes, sha256 `dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752` (verified equal to the live file on 2026-11-17 immediately before the migration; `PRAGMA integrity_check` = ok). Every registered result was produced on a file with that hash; the per-table content of the live file is identical to it (proof in `Claude_Docs/DB_GUARD_REPORT.md`). The live file now has a different hash (it holds the guard tables and triggers: sha256 `4ce224bb27166d4451a38cb5e5ab59fd265e6937cdf3b991926a3b2a47bd3057` on 2026-11-17, for information only; nothing compares the file with any fixed hash).
