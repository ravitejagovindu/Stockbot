# FAST-VIEW_FOLLOWUP_REPORT (branch fast-view-followup, from master bcf003a)

## Result in one paragraph
On the merged code (new sector rule, cash-credited alpha, renamed gate) the memory view still answers exactly like the SQL view: the 12-month near_52w_high run and the matched-random baseline, each run once per view, give byte-identical output files. Subclasses such as `ForwardCappedView` now follow the switch, every run records which view it used, and the live path refuses the memory view. The default is still the SQL view. All gates pass.

## What ran
| Step | What | Result |
|---|---|---|
| 0 | `git fetch`, `git switch -c fast-view-followup origin/master`; DB sha256 before | matched |
| 1 | Guide JSON entry for `asof_memory.py`, `codebase_guide.html` regenerated (`scripts/build_guide_html.py`, no `--stamp`); guide tests + `test_asof_memory.py`; full G2 on the SQL view | 89 passed, 1 skipped; G2 1,107 passed, 0 failed |
| 2 | `research_near_52w_high.py`, 2025-10-01 to 2026-09-30 (247 sessions, 90 closed trades), once per view | see below |
| 3a | `baseline_matched_random_near_52w_high.py`, same seed (default), on the step 2 SQL run directory, once per view | see below |
| 3b | `AsOfView` subclasses follow the switch | done |
| 3c | Test that a new subclass cannot bypass the switch | done |
| 4 | `active_view_name()`; `asof_view` in the manifests; printed at run start | done, both values tested |
| 5 | Live refuses the memory view | done, tested |
| 6 | "Running with the fast view" in `docs/shared/fast-view/STATUS.md` | done |
| 7 | G1, full G2, G3, DB hash | below |

Step 2 and 3a ran on the final code (after the changes of 3b, 4 and 5), so they prove the shipped state.

### Step 2: view against view (memory run 478 s, SQL run 1,672 s)
| File | Result |
|---|---|
| trades.json | byte-identical (cmp) |
| daily.json | byte-identical |
| equity_curve.json | byte-identical |
| blocked.json | byte-identical |
| manifest.json | one key differs, as intended: `asof_view` ("memory" vs "sql"); every other key equal |

No return or P&L figure was read; only file bytes, key names and counts.

### Step 3a: baseline, view against view (memory 206 s, SQL 424 s; 78 usable trades, 1,505 draws)
| File | Result |
|---|---|
| actual_trades.csv | byte-identical |
| baseline_draws.csv | byte-identical |
| baseline_meta.json | one key differs, as intended: `asof_view`; every other key equal (including the DB fingerprint, `unchanged: true` in both) |

Deviation from "all output files byte-identical": `baseline_meta.json` cannot be byte-identical because step 4 adds the `asof_view` key to it. Compared key by key instead.

### Step 3b: how subclasses follow the switch
`AsOfView.__new__` (asof.py): under `STOCKBOT_VIEW=memory`, a direct `AsOfView(...)` call becomes `MemoryAsOfView`; any other subclass of `AsOfView` is built as a generated class `(Subclass, MemoryAsOfView)` (`asof_memory.memory_variant`, one per class, same name and module). The subclass's own methods come first, and its `super()` calls reach the in-memory fetches. So `ForwardCappedView` (the capped forward read in the baseline script) is now read through the memory view for the final session too. No script was edited for this. A test with a capping subclass compares exact frames between the views and shows the override really acts. This replaces the old statement "a subclass is built as itself" (one assertion in `test_asof_memory.py` updated).

### Step 3c: the guard test
`test_every_asof_subclass_in_the_code_honours_the_switch_or_is_listed_as_exempt` scans `stockbot/` and `scripts/` for classes deriving from `AsOfView` or `MemoryAsOfView` (AST), imports them, and fails if one is not a `MemoryAsOfView` under the switch unless it is in `EXEMPT` with a written reason. `EXEMPT` is empty. It currently sees `MemoryAsOfView` and `ForwardCappedView`.

### Step 4
`active_view_name()` in `stockbot/data/asof.py` is the one place `STOCKBOT_VIEW` is read for the name. `run_manifest` adds `"asof_view"`, `run_backtest` prints `asof_view: <name>` at its start, and the baseline script writes it to `baseline_meta.json` and prints it. The research script's manifest gets it through `run_manifest`. A test shows decisions, trades, equity curve and every other manifest key are unchanged by the view name. Only the manifests gain a key; the step 2 comparison shows no other output differs.

### Step 5
`stockbot/live/__init__.py`: `refuse_memory_view()` raises `MemoryViewNotValidated("memory view is not validated for live; unset STOCKBOT_VIEW")`. Called at the start of `run_eod`, in `LiveAdapter.__init__` and in `health_check.check`; `eod_cli` prints it as `REFUSED:` with exit code 2. Tested at the runner, adapter and health check, and shown not to fire for sql or unset.

## Final gates
- **G1** (`tests/unit tests/integration`): 985 passed, 8 skipped, 0 failed (9 min 26 s).
- **Full G2** (`STOCKBOT_DATA_TESTS=1 STOCKBOT_FINAL_CHECK=1 pytest tests`, default SQL view): 1,114 passed, 0 failed (11 min 0 s). Earlier G2 on the merged code before the changes: 1,107 passed.
- **G3** (`tests/unit/test_g3_fixture_baseline.py`): 2 passed.
- **finsight.db sha256** before and after: dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752 (unchanged).

## Shared files touched, and why
1. `stockbot/data/asof.py`: `active_view_name()`; `__new__` now also redirects subclasses.
2. `stockbot/data/asof_memory.py` (mine from before): `memory_variant`.
3. `stockbot/backtest/manifest.py`: `asof_view` key in the run manifest.
4. `stockbot/backtest/runner.py`: prints the view at the start of a run.
5. `stockbot/live/__init__.py`, `runner.py`, `adapter.py`, `health_check.py`, `eod_cli.py`: the live guard.
6. `scripts/baseline_matched_random_near_52w_high.py`: writes and prints `asof_view` (a strategy-named script; only the view name added, no logic or parameter touched; the registered strategy and pre-registration are untouched).
7. `docs/guides/codebase_guide_data.json` and `docs/guides/codebase_guide.html`: entry for `asof_memory.py`, page regenerated (not stamped). `CODEBASE_GUIDE.md` was already done.
8. `docs/shared/fast-view/STATUS.md`: usage note.
9. Tests: new `tests/unit/test_fast_view_followup.py` (7 tests: 2 parametrised), one assertion changed in `tests/unit/test_asof_memory.py`.
Not touched: strategy folders, pre-registrations, config values, gates, ledgers, the DB.

## Not run
- The memory view on the real live path (it is refused by design; not validated there).
- A full 2016-2026 engine run or baseline in this task (timings quoted from the earlier report: 55 min and 22 min).
- A second baseline comparison on the full window (only the 12-month run was compared view against view).
- `codebase_guide.html` was rebuilt without `--stamp`, so its footer date and commit are as before.

## Decisions needed
1. **Default view.** Still SQL, as instructed. All proofs now pass on merged code; flipping it means changing `active_view_name()`; the live guard reads that same function, so after a flip live would refuse the (default) memory view and the live path would need its own pin to SQL first.
2. **Engine speed gap** (55 min against 45): unchanged; needs a separate task on `adtv` and `adjusted_bars`.
3. Whether to also validate the memory view for live later (the guard is the only thing stopping it).
