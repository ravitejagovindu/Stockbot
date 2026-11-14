# FAST-VIEW_REPORT (branch fast-view, from de36639)

## Result in one paragraph
An in-memory as-of view (`MemoryAsOfView`) answers exactly like the SQL `AsOfView` on every check: 0 differences over 444 real sessions, byte-identical 12-month run outputs, 143 real-lake tests passing under the memory view. It is 4.3x faster on the 12-month run (2,003 s to 466 s). The matched-random baseline meets its target (22.3 min). **The engine-only full run misses its target: 55.2 min against 45.** Per the brief I stopped there and did not widen scope. Default stays the SQL view.

## What was built
- `stockbot/data/asof_memory.py` (new): `MemoryAsOfView(AsOfView)`. Loads `market_data_lake` once (chunks of 500k rows, numpy arrays sorted by symbol and date, about 270 MB) and `corporate_actions_log` lazily. Replaces only fetches: `raw_bars`, `corporate_actions`, `sessions`, `_symbols_on_as_of`, `_lake_first_date`, `_first_and_count`. Adjustment, ADTV, listing age, the future-data check, earnings (still SQL) and eligibility are the inherited, unchanged code. Lake opened only through `open_lake`; nothing written anywhere.
- Switch, one place: `AsOfView.__new__` redirects a direct `AsOfView(...)` call when `STOCKBOT_VIEW=memory` (unset or anything else = SQL). Subclasses are built as themselves.
- `docs/shared/fast-view/diff_views.py`: the diff harness; `BRIEF.md`, `STATUS.md`.
- `tests/unit/test_asof_memory.py`: 64 tests on a fixture lake.

## Shared files touched (and why)
1. `stockbot/data/asof.py`: the switch (`__new__`), and two small fetch primitives (`_symbols_on_as_of`, `_first_and_count`) pulled out of `symbols_trading` / `symbol_info` so the logic is shared and not copied. SQL text and results unchanged (all existing as-of tests pass).
2. `docs/guides/CODEBASE_GUIDE.md`: one row for `asof_memory.py` (a guide test demands it). Expect a small merge conflict. `codebase_guide.html` was not regenerated; the guide tests pass.
Not touched: any strategy folder or pre-registration, `scripts/*_<id>.py`, engine, universe, config, ledgers, the DB.

## Proof (all results)
1. **Existing tests, both views.** SQL view: 236 passed. Memory view (`STOCKBOT_VIEW=memory`, with `STOCKBOT_DATA_TESTS=1`): 143 passed, including the 120 golden as-of samples (frozen sha256 of raw and adjusted frames), the real-DB parity tests, engine, corporate-action, baseline and research tests. One existing test cannot pass under the memory view by design: `test_near_high_signal_count.py::test_every_sql_statement_is_bounded_by_the_session_being_evaluated` counts SQL statements and the memory view issues none (it passes on the SQL view and in G1/G2, which run the default view).
2. **Diff harness, 444 sessions** (first, last, every month end, 100 random seed 20261113, the session before/of/after the ex-date of 20 random SPLIT, BONUS, DEMERGER and RIGHTS actions): symbols_trading, symbol_info and adtv for every trading symbol, sha256 of adjusted_bars and raw_bars per symbol, eligible_symbols as ordered lists. About 788,000 symbol-sessions, **0 differences** (two shards, 222 sessions each).
3. **End to end**, near_52w_high research script, window 2025-10-01 to 2026-09-30 (247 sessions), once per view: `trades.json`, `daily.json`, `equity_curve.json` and `blocked.json` are **byte-identical** (cmp). `manifest.json`: no key differs, so nothing had to be ignored. No return or P&L was read; only file bytes and counts.
4. **Edge cases** in a fixture lake, both views, exact frame equality (`check_exact`, dtypes, index type): split, bonus, split plus bonus on one day, rights, demerger (no ratio), a name with a 40-session gap, a late listing, a name that stops, integer-valued prices, a zero-volume row, a future-dated action, a Saturday, a date before and after the lake, FutureDataError, the switch, read-only behaviour.

## Speed and memory
| | SQL view | memory view | target |
|---|---|---|---|
| 12-month engine run (247 sessions) | 2,003 s | 466 s | |
| Full 2016-2026 engine-only run (2,674 sessions) | about 4 h (as stated in the brief; not re-measured) | **3,312 s = 55.2 min** | 45 min: **MISSED** |
| Matched-random baseline (774 trades, 14,630 draws) | about 2 h (as stated) | **1,340 s = 22.3 min** | 45 min: met |

Memory: peak RSS about 1.0 GB per process (995 MB measured for the full load; 987 MB in the diff shards). Far below 6 GB. Load: 27 s with the file cached, **975 s on a cold read** (disk bound; other sessions were reading the same file).

**Where the time goes (cProfile, 12-month memory run, 972 s under the profiler):** the data fetch is no longer the cost (`raw_bars` own time 18 s). `eligible_symbols` 552 s cumulative, almost all in `adtv` (468k calls, 530 s: pandas Series arithmetic and `rolling.mean`, 181 s in `compute_adtv`); the strategy's `propose` 384 s, almost all in `adjusted_bars` (137k calls, 337 s: DataFrame construction and `compute_row_factors`). It is pandas object overhead in logic the brief says must not change.

## Deviations and choices
- Switch lives in `AsOfView.__new__` (zero call-site edits, nothing in strategy-owned scripts changed). A subclass is not redirected, so `ForwardCappedView` in the baseline script reads through SQL for the final session only (one session; its outputs were not compared across views).
- Baseline outputs were not compared byte for byte between views (the brief required that only for the engine run). The baseline run used the memory view only.
- The loader reads `corporate_actions_log` lazily because some legacy test lakes lack the table (the SQL view only fails when actions are asked for; the memory view now does the same).
- The "EQ series rows" filter: `market_data_lake` has no series column; it holds only EQ rows plus the two index series (DATA_GUIDE section D), so the whole table is loaded.
- The 444-session diff ran on 2 shards (not 4) to stay under the machine's memory limit. One earlier load test was stopped by the system for memory pressure and re-run alone.
- The full-window engine run and the baseline run are backtests of the registered near_52w_high strategy, run only for timing (outputs not read, kept in the scratchpad, not in the repo).

## Tests at the end
- **G1** (`tests/unit tests/integration`): 943 passed, 8 skipped, 1 failed (guide test wanting a row for `asof_memory.py`). Fixed with the guide row; the guide tests then pass (52 passed, 7 skipped).
- **Full G2** (`STOCKBOT_DATA_TESTS=1 STOCKBOT_FINAL_CHECK=1 pytest tests`, after the commit): **1,073 passed**, 0 failed, 0 skipped, 17 min 14 s. G2 contains G1; a separate full G1 re-run after the guide-row fix was not done.
- **G3** (`tests/unit/test_g3_fixture_baseline.py`): 2 passed (also inside G2).
- `finsight.db` sha256 before and after: dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752 (unchanged).

## Not run
- A full engine run or baseline on the SQL view (the brief's old timings are quoted, not re-measured).
- The memory view on the live adapter / live runner (they construct `AsOfView` and would honour the switch, untested).
- A baseline byte comparison between views.
- Regeneration of `codebase_guide.html` / data guide HTML.

## Decisions needed
1. **Engine target missed (55.2 vs 45 min).** Closing the gap needs changes in logic this task fixed: for example computing ADTV for all symbols in one vectorised pass per session, or caching `adjusted_bars` across sessions (both must be proven identical like the view was). Do you want that as a follow-up task? How much it would save is not measured.
2. **Default.** The proof passed, so the default can move to the memory view whenever you say. It is left on SQL as the brief asked.
3. Cold-load cost (16 min on a cold file) is a one-time price per process; with one run per process it adds to the first run only.
