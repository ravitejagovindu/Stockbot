# Owner guides: report

Documentation task. No change to engine, config, schema or data. Nothing started beyond the brief.

## Deliverables (on `master`, pushed)

| item | path | lines |
|---|---|---|
| Codebase guide | `docs/guides/CODEBASE_GUIDE.md` (copy: `Claude_Docs/CODEBASE_GUIDE.md`) | 753 |
| Data guide | `docs/guides/DATA_GUIDE.md` (copy: `Claude_Docs/DATA_GUIDE.md`) | 742 |
| Measured catalogue (embedded by link in the data guide) | `docs/guides/data_catalogue.md` | 949 |
| Generator (read-only) | `scripts/gen_data_catalogue.py` (wrapper) over `stockbot/data_checks/data_catalogue.py` | 7 + 215 |
| Consistency test | `tests/unit/test_guides_consistent.py` | 172 |

Diagrams (Mermaid): codebase guide **8** (dependency flowchart, `decide()` sequence, backtest sequence, daily EOD sequence, position state diagram, validation flowchart, ingestion flowchart, testing flowchart); data guide **6** (ER diagram, source-to-engine flowchart, daily data sequence, corporate-action flowchart, earnings and ASM/GSM flowchart, `AsOfView` sequence). Each has an explanation under it. I could not render them on GitHub from here: I checked the syntax against Mermaid's rules (no semicolons or angle brackets in messages, quoted flowchart labels, valid ER cardinalities) but please open both files on GitHub once and tell me if any diagram fails to draw.

Copies in `Claude_Docs/` are snapshots under the same file names; `docs/guides/` is the canonical place and the one the test checks.

## Commits

| SHA | what |
|---|---|
| `2aae57f` | `Claude_Docs/STOCKBOT_RESTRUCTURE_STOP5_CLOSED.md` (it was not on the remote before) |
| `a9d43af` | guides, catalogue, generator, test, and the two copies in `Claude_Docs/` |
| the commit carrying this report | `Claude_Docs/STOCKBOT_GUIDES_REPORT.md` (SHA given in the chat message) |

## Test results

| check | before | after | note |
|---|---|---|---|
| G1 (`tests/unit` + `tests/integration`) | 494 passed, 1 skipped | **505 passed, 2 skipped**, 0 failed (3 min 13 s; again after the commit: 505 / 2) | +11 passed = the 10 offline guide tests and the new wrapper's `--help` test; +1 skipped = the env-gated guide test |
| G2 (`STOCKBOT_DATA_TESTS=1 STOCKBOT_FINAL_CHECK=1 py -m pytest tests`) | 616 passed, 0 skipped (STOP 5) | **628 passed**, 0 skipped, 0 failed (32 min 15 s) | +12 = the same 11 plus the env-gated guide test, which ran against the real lake (read-only) and passed |
| G3 (`tests/unit/test_g3_fixture_baseline.py`) | 2 passed | 2 passed | |
| G4 `finsight.db` | sha256 `dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752`, modified 2026-11-08 12:38:02 +0530, 3,432,767,488 bytes | **identical** (re-hashed at the end) | the lake was opened only through `open_lake` (`mode=ro`) |

"Unchanged" holds in the sense that no existing test changed result and no expected value was touched; the counts rose only by the new tests, which a new test file necessarily does.

**Fail-before evidence** (new test): before the guides existed, 9 of the 10 offline tests failed (the 10th is the checker's own self-test). Then, with the finished guides, six defects were seeded one at a time and the test caught every one, with the files restored after each run and a clean control run passing: a table name removed from the data guide (offline and env-gated versions), a non-existent path added to the codebase guide, a package removed, a script removed, a trigger name removed. The first version of the package check had a lenient fallback that would have accepted a bare last name such as `db`; I removed it.

## How the numbers are marked

Every number in `DATA_GUIDE.md` is either **measured on 2026-11-09** from `finsight.db` (the guide's opening says so, and the catalogue prints its own measurement time, 11:10) or carries "from report X" (the 81 holiday copies, the KI figures, the six filler dates). Per-table measured lines, the coverage tables and the five SQL examples (each was run; results quoted) are all from that day. This is a convention stated once at the top plus explicit "from report" tags, not a per-number footnote.

## Things you should know that the guides state as fact (no recommendation made)

1. **The lake ends 2026-10-16 and nothing in the repository appends a new session.** The range downloader writes only to the staging table; `BhavcopyIngestor`, `OHLCVIngestor` and `IndexVIXIngestor` have no caller anywhere. The October rows came from the old pipeline that was removed in Phase 9. `run_eod` will report `DataFreshnessError` for any later date. This is not on `PRE_LIVE_LIST.md`.
2. **The trading calendar starts 2015-11-09.** `sessions()` is the `NIFTY50_INDEX` series, which starts then; the lake holds 706 earlier dates (2013-01-01 to 2015-11-06) with no Nifty row, so they cannot be decided or backtested. The shared config's 2015-2019 window therefore effectively starts 2015-11-09.
3. **No module evaluates `validation_gates`.** They are configuration values only.
4. `shares_outstanding_pit`, which your brief lists, is **not a table** in the database (an ORM class only; F2b was closed). The guide says so.
5. `market_data_lake.source` and `loaded_at` are empty on most rows (not a reliable provenance field); `market_data_lake_yahoo_archive` has misleading `_raw` column names (the values are Yahoo-adjusted).
6. `python -m stockbot.live.main` runs `init_db()` on whatever `DATABASE_URL` points to (default `finsight.db`, relative to the current folder), so starting the old API is a possible writer of the lake. I did not run it.
7. `stockbot/live/main.py` still says the scheduler fires at 17:00; `scheduler.py` uses 19:00 IST while `data.eod_source` is `bhavcopy` (the guide gives 19:00).
8. The KI-004 text gives 145 of 2,900 lake symbols without earnings data; by the definition I could measure (mapped query symbols with no non-empty response) it is 341 of 3,238. Both are in the data guide with their definitions.

## Housekeeping answers

- **STOP5_CLOSED note:** pushed in `2aae57f`.
- **The +3 lines of `.gitignore` in merge commit `9298770`:** they were not made by the merge. They came from Phase 9.3 commit `5097cb8` and the merge only carried them: a blank line, the comment `# Live state database and ticket files (generated)` and `state/`. Purpose: keep `state/live_state.db` and `state/tickets/` out of git.
- **Did the daily ASM/GSM task run on 2026-11-09? No.** There is no StockBot task in Windows Task Scheduler (I listed every non-Microsoft task on 2026-11-09), there is no snapshot log in `logs/` or in `F:\Projects\Ravi\StockBotSnapshot\`, and neither database holds a 2026-11-09 row. The only runs ever made were by hand on 2026-11-08: in `finsight.db` at 10:58:09, `reportASM` OK "179 rows" and `reportGSM` OK "76 rows", giving 253 snapshot rows (`ASM_LT` 129, `ASM_ST` 48, `GSM` 76); in the stand-alone database at 16:39:11 the same two lines and the same 253 rows. (It was before the schedule's 19:00 time when I looked, but no task exists to fire then.) The scheduling command is in `docs/ASM_GSM_SNAPSHOT.md`.

## Deviations and limits

- The disk reads about 0.4 to 1 MB/s, so a first version of the generator stalled for over 40 minutes on full scans of the three multi-million-row tables. I stopped my own two processes by process id and changed the generator: on tables above 1,000,000 rows it skips per-column non-null counts and only measures distinct symbols and dates through an index. As a result the catalogue shows "not counted (large table)" for those columns, and `market_data_lake_yahoo_archive` has no first/last date. This is stated in the catalogue and the guide. A final run takes about 30 seconds once the disk cache is warm.
- During that work I issued one over-broad command to kill Python processes; it was denied and did not run, and I then stopped only my own two processes. No other process was touched.
- "Three sample rows for every table" is met by the catalogue (every table, first two and last by id) and by inline rows for the core tables in the data guide; I did not duplicate all of them in the guide.
- "Written by / read by" in the inventory comes from searching the code for each table name, not from running anything.
- The test keeps a short allowlist of paths that exist only after a first run or are git-ignored (`state/`, `logs/`, `finsight.db`, `ui/node_modules`, `data/db/` ...), so it passes in a clean clone.

STOP. Nothing else was started.
