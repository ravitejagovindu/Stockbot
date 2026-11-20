# momentum_calm_daily: commands for the registered run (one member, K = 1)

**Do not run any of this until the owner has registered `family_batch8` (K = 1) on master and this branch holds the registered pre-registration commit.** Nothing here has been run on the real lake (the overlap check is the only step that touched it, counts only). The plan step must print the spec hash `814dce51b04fbfb7d2463822fd81176643e4a4e35bcc2b3861745270104bd152`.

Work only in the strategy worktree (branch `momentum-calm-daily`, `F:\Projects\Ravi\StockBot_wt_mc_daily`); never switch branches in the main folder. Print folder and branch before you start and after every commit. Output folder `docs/strategies/momentum_calm_daily/results_run1/` (not created yet), also the member directory for `validate_family.py`:
```
results_run1/
  run/        manifest.json trades.json equity_curve.json daily.json blocked.json     (step 2)
  baseline/   actual_trades.csv baseline_draws.csv baseline_meta.json                   (step 3)
  benchmark.json                                                                      (step 4)
  gates.json                                                                          (step 5)
  family_results.json                                                                 (step 6)
  comparison.json comparison.md                                                       (step 7)
```
Each script refuses a non-empty output directory; a repeat needs a fresh folder and the owner's approval.

## 0. Settings (Git Bash, once per shell; the same in every step)
```
cd /f/Projects/Ravi/StockBot_wt_mc_daily
export STOCKBOT_DB='F:\Projects\Ravi\StockBot\finsight.db'
export STOCKBOT_VIEW=memory
export STOCKBOT_NON_EQ=held
unset STOCKBOT_RISK_PCT
D=docs/strategies/momentum_calm_daily/results_run1
mkdir -p $D
```
**`STOCKBOT_RISK_PCT` must NOT be set** (standard 1.0% risk; a manifest that carries `risk_override` is invalid). `STOCKBOT_NON_EQ=held` must be set identically in the research, baseline and gates steps. Before the first step record `sha256sum "$(cygpath "$STOCKBOT_DB")" > $D/sha_before.txt` and `py -3 scripts/guard.py status --json > $D/guard_before.json` (read-only); repeat into `sha_after.txt` and `guard_after.json` after the last step. The hash must be equal and the correction counter unchanged.

## 1. Plan only (runs nothing)
```
py -3 scripts/research_momentum_calm_daily.py --out $D/run
```
Confirm: `asof_view` memory, window 2016-01-01 to 2026-10-16, the spec hash above, exit policy `mcd_trailing_atr3_floor8`, status `research`, NO `RISK OVERRIDE ON` line on stderr, and `lake` = `F:\Projects\Ravi\StockBot\finsight.db`.

## 2. The run
```
py -3 scripts/research_momentum_calm_daily.py --execute --out $D/run > $D/research.log 2>&1
```
Check `run/manifest.json` before going on: `asof_view` memory; a `non_eq_view` block and a `non_eq_events` block; **no `risk_override`**; `end_of_window` block; `db_check` clean (`unchanged` true, sha256 before = after). If `non_eq_view` is missing, `risk_override` is present, or `db_check` is not clean: STOP and report (it is not a result).

## 3. B1 baseline (20 draws per trade, seed 20261111; the any-day pool rule C unchanged, pool NOT restricted to calm stocks)
```
py -3 scripts/baseline_matched_random_momentum_calm_daily.py --run-dir $D/run --out-dir $D/baseline > $D/baseline.log 2>&1
```
`baseline_meta.json` must carry `finsight_db.unchanged` true, `pool_exclusions` and no `risk_override`.

## 4. B2 benchmark
```
py -3 scripts/benchmark_nifty_matched_momentum_calm_daily.py --run-dir $D/run --lake "$STOCKBOT_DB" --out-json $D/benchmark.json
```

## 5. Gates (point estimates; no --t1)
```
py -3 scripts/evaluate_validation_gates_momentum_calm_daily.py --run-dir $D/run --lake "$STOCKBOT_DB" --out-json $D/gates.json --baseline-dir $D/baseline
```

## 6. Joint validation (T1, T2, T3)
```
py -3 scripts/validate_family.py --member momentum_calm_daily=$D --expect-k 1 --lake "$STOCKBOT_DB" --out-json $D/family_results.json
```
(B = 10,000, blocks 2 and 3, seed 20261111 are the defaults; `--expect-k 1` refuses any other member count.) `validate_family.py` does not print the end-of-window or stale-exit counts: read them from `run/manifest.json` (`end_of_window.trades`, `stale_exit`, `non_eq_events`) and `baseline/baseline_meta.json` (`end_of_window_trades`, `end_of_window_draws`, `stale_exit_draws`).

## 7. The descriptive side-by-side (read-only; stored numbers only; opens no database)
```
py -3 scripts/momentum_calm_daily_comparison.py --calm-daily $D --out-json $D/comparison.json --out-md $D/comparison.md
```
The table sets momentum_calm_daily beside the any-day runs of family_batch4, family_batch5 and family_batch6 and the monthly momentum_calm run of family_batch7 (trades, expectancy, profit factor, max drawdown, alpha, T1 p, net profit, fees, mean invested share, worst-fall dates). It decides nothing.

## Order, timing, locks and the daily data job
- **One heavy job at a time**: never research and baseline together, and no other heavy job alongside. About 1 GB of memory per process; the memory view reads the lake once per process (up to about 16 minutes cold; the overlap check showed a start of roughly 10 to 12 minutes before its first output).
- **Time estimate (from the earlier any-day run and the monthly momentum_calm run; NOT measured for this trial):** the plain any-day engine run took about 80 minutes (4,799 s in family_batch5) and its baseline about 60 minutes (3,688 s). This strategy evaluates sigma252 for every eligible name on every session, so **I expect research about 90 to 120 minutes and baseline about 60 to 75 minutes**, the short steps a few minutes each and validate_family about 1 minute: **about 3 to 3.5 hours in total**, with a margin because the trade count may differ.
- **Run locks:** a research, baseline or validation step takes the run lock (`stockbot/data/guard/runlock.py`, folder `F:\Projects\Ravi\StockBotData\locks`). **While a run holds it the daily data job cannot write**: the job waits (its retries report LOCKED) and catches up after the lock is released (`docs/shared/daily-update/SCHEDULER.md`). Never delete a lock by hand; if the data job holds its own lock, WAIT. A long step records the database sha256 before and after; any difference makes the run INVALID (exit code 3).
- **Database checks:** every short step prints a "database check ... unchanged" line; research and baseline also hash the file. Anything else means STOP.
- **If a step crashes:** no partial output is a result. Stop and tell the owner; a repeat from scratch into a fresh folder (`results_run1_retry1/`) needs the owner's approval.

## After the run (owner, on master)
`record_family_results(path=<family_ledger.csv>, family_id="family_batch8", results={"momentum_calm_daily": <the member's entry of family_results.json>}, git_sha=<commit>)`; the run report writes the exact command and the run block never writes the ledger row itself.
