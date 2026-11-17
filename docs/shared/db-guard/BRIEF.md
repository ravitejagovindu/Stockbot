# db-guard: brief

Branch `db-guard` (from origin/master 683d5e8). Worktree `F:\Projects\Ravi\StockBot_wt_dbguard`. Task: ONE database; readers cannot write; writers cannot change sealed history by accident; deliberate corrections are explicit and logged. Owner-approved design (fixed):

- **R1 Readers.** Backtests, research scripts, baselines, validation and the paper/live READ path open the database read-only at the connection level. Every backtest-type run records the file sha256 before and after in its manifest; a difference marks the run INVALID (non-zero exit, clear message). No code or test compares the file against a pinned hash any more.
- **R2 Writers.** Protection INSIDE the database with triggers. Each protected table has a "sealed through" date. Sealed rows: UPDATE refused, DELETE refused, INSERT dated on or before the sealed date refused. Rows after the sealed date are free until a writer seals that date after a successful load.
- **R3 Corrections.** A deliberate change to sealed rows needs an explicit correction window (opened with a reason by one command, closed by it). While open, changes are allowed and every changed row is written to a change log in the database (time, table, key, before, after, reason). A correction counter increases. The window cannot stay open across commands.
- **R4 Traceability.** Every run's manifest records, per table it reads: sealed-through date, correction counter, file hash before/after.
- **R5 Uniform.** Any new table gets the same treatment when created. A test fails if a table has neither the guard nor an entry in a short exempt list with a reason.
- **R6 Audit.** At seal time a per-day checksum of that day's rows is stored. An audit command recomputes them and reports any difference. Not run per backtest.

## Rules of the work
Plain commits, NO Co-Authored-By / Claude-Session / "Generated with" lines. Until Part 2 step 6, `finsight.db` is NOT modified (STOCKBOT_DB=F:\Projects\Ravi\StockBot\finsight.db, sha256 `dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752`): develop and test on fixture databases and on a scratch COPY only. No strategy folder, pre-registration, ledger row or stored result is touched; no registered result is re-run.

## Parts
- **Part 1** (this one): inventory and proposal, report `Claude_Docs/DB_GUARD_PART1.md`, push, STOP for the owner's written approval.
- **Part 2** (only after written approval of Part 1): guard module and CLI, readers and manifests, replace pinned-hash checks, tests, G1/G2/G3 on a scratch copy, migration of the real file with backup and per-table content proof, docs; report `Claude_Docs/DB_GUARD_REPORT.md`.

## Shared files touched
Part 1: none (new docs and report only).
