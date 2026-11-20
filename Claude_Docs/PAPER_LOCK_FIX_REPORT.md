# Paper lock fix report (branch `paper-lock-fix`, 2026-11-20)

## What was wrong
`scripts/paper_run.py` refused (exit 4) when ANY `*.lock` file existed in `F:\Projects\Ravi\StockBotData\locks\`. The data job (`runlock.locks_for`) only counts locks for the same database file (plus unreadable locks). On 2026-11-20 ten leftover `run_*.lock` files from my own killed pytest runs (pids 15196 and 4580, temporary pytest lakes, not `finsight.db`) made every paper step return 4. The data step itself worked (2026-11-20 loaded and sealed at 19:30), so `daily_job.py` ended with 4 on every repeat and `state\live_state.db` was never created. The tests missed it because they only used an empty directory or a single unreadable lock.

## The fix
`scripts/paper_run.py`: `locks_held(db=None)` now returns the names from `runlock.locks_for(<the lake the run reads>)`. A lock for another database does not block; a lock on the same database, or an unreadable lock file (it concerns every database), still blocks with exit 4. No other behaviour changed (sealed-data check, start cash, run_eod call, exit codes). `daily_data_update.py` and the runlock module were not edited.

## Tests (`tests/unit/test_momentum_calm_paper.py`, 5 new)
- empty lock directory: does not block;
- lock for another database: does not block, and the paper step runs (exit 0);
- lock on the same database: blocks, exit 4, no state database created;
- unreadable lock: blocks;
- one lock for another database plus one on this database: only the latter is named.
The earlier test (an unreadable `daily_update.lock` blocks) still passes. Paper tests and `test_f6_baseline_and_locks.py`: 20 passed.

## Full suite
`STOCKBOT_DATA_TESTS=1 STOCKBOT_FINAL_CHECK=1`: **1860 passed, 1 failed** (59 min). The failure is `tests/unit/test_data_guide_html.py::test_the_row_counts_in_the_catalogue_equal_the_live_counts`, pre-existing and unrelated (the data catalogue is behind the live lake; it failed the same way before this work). No other failure.

## Step A: stale test locks (owner-authorised)
- Before: no python process running; 10 `run_*.lock` files, all kind `run`, pids 15196 (1) and 4580 (9), all dead, all pointing at temporary pytest lakes (`...\appdata\local\temp\pytest-of-ravit\...\lake.db`), none at `finsight.db`.
- Removed first (9): `run_15196_20261120111117.lock`, `run_4580_20261120112129`, `...112453`, `...112643`, `...112956`, `...113138`, `...113846`, `...114810`, `...115051` (write times 16:41:17 to 17:20:51, each condition checked in the removal loop).
- Kept first: `run_4580_20261120115510.lock` (17:25:10, 10 seconds after the 17:25 cutoff, read literally). The owner then explicitly authorised it; pid 4580 re-checked not running, db a pytest temp lake; removed.
- Result: all 10 removed, nothing else touched. The six `run_13984_*` locks that appeared during this work belonged to the live full-suite run (pid 13984) and were left alone; they were gone when it finished and the lock directory is empty.
- Not touched: `finsight.db`, `state\`, any Task Scheduler task (the 19:30 task stayed Disabled throughout), `daily_job.py` and `paper_run.py` were not run against the real state.

## Open
- The 19:30 task is still Disabled and has no repetition. Re-enabling it (and the restart-on-failure setup) is the owner's decision after this fix is merged.
- `state\live_state.db` does not exist yet; the first real `paper_run.py` run creates it with 200,000 INR.
