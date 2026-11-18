# riskadj_momentum_daily re-run with BE/BZ data (family_batch5): commands

**Do not run any of this until the owner has registered `family_batch5` (K = 1) on master and this branch holds the registered pre-registration commit.** Nothing here has been run on the real lake. The spec hash printed by the plan step must equal `5b06f092df061bff1532093d21ea21c88c3f2db64ddd66e0cbe81bd5c0446e19`.

Work only in the worktree `F:\Projects\Ravi\StockBot_wt_rmd_noneq` (branch `rmd-noneq-run`). Output folder `docs/strategies/riskadj_momentum_daily/results_run2_noneq/` (the old `results_run1/` is never written to):
```
results_run2_noneq/
  run/       manifest.json trades.json equity_curve.json daily.json blocked.json
  baseline/  actual_trades.csv baseline_draws.csv baseline_meta.json
  benchmark.json   gates.json   family_results.json   comparison.json   comparison.md
```
Each script refuses a non-empty output directory; a repeat needs a fresh folder and the owner's approval.

## 0. Settings (Git Bash, once per shell)
```
cd /f/Projects/Ravi/StockBot_wt_rmd_noneq
export STOCKBOT_DB='F:\Projects\Ravi\StockBot\finsight.db'
export STOCKBOT_VIEW=memory
export STOCKBOT_NON_EQ=held
D=docs/strategies/riskadj_momentum_daily/results_run2_noneq
```
(cmd: `set STOCKBOT_VIEW=memory` and `set STOCKBOT_NON_EQ=held`.) Record `sha256sum "$(cygpath "$STOCKBOT_DB")"` and `py -3 scripts/guard.py status --json` (read-only) before and after. The hash is NOT compared with `dcade465...` (the file changed legitimately); the run's own `db_check` is the control.

## 1. Plan only (runs nothing)
```
py -3 scripts/research_riskadj_momentum_daily.py --out $D/run
```
Confirm `"asof_view": "memory"`, window 2016-01-01 to 2026-10-16 and the spec hash.

## 2. The run (one backtest)
```
py -3 scripts/research_riskadj_momentum_daily.py --execute --out $D/run > $D/run.log 2>&1
```
Check `run/manifest.json`: `"asof_view": "memory"`, a `non_eq_view` block (`switch` STOCKBOT_NON_EQ=held, `volume_cap_per_session` 0.1, `exit_slippage_multiplier` 2.0), a `non_eq_events` block, and **`db_check` clean** (counter unchanged, sealed dates unchanged, digests equal before and after). If `non_eq_view` is missing the switch was not set: report and stop (a partial or wrong run is never a result).

## 3. B1 baseline (20 draws per trade, seed 20261111; same switch)
```
py -3 scripts/baseline_matched_random_riskadj_momentum_daily.py --run-dir $D/run --out-dir $D/baseline
```

## 4. B2 benchmark
```
py -3 scripts/benchmark_nifty_matched_riskadj_momentum_daily.py --run-dir $D/run --lake "$STOCKBOT_DB" --out-json $D/benchmark.json
```

## 5. Gates (point estimates; no --t1)
```
py -3 scripts/evaluate_validation_gates_riskadj_momentum_daily.py --run-dir $D/run --lake "$STOCKBOT_DB" --out-json $D/gates.json --baseline-dir $D/baseline
```

## 6. Joint validation, family of ONE
```
py -3 scripts/validate_family.py --member riskadj_momentum_daily=$D --expect-k 1 --lake "$STOCKBOT_DB" --out-json $D/family_results.json
```
(B = 10,000, blocks 2 and 3, seed 20261111 are the defaults.)

## 7. The comparison table (read-only; after steps 2 to 6)
```
py -3 scripts/noneq_comparison_riskadj_momentum_daily.py --old docs/strategies/riskadj_momentum_daily/results_run1 --new $D --lake "$STOCKBOT_DB" --out-json $D/comparison.json --out-md $D/comparison.md
```

## Run locks and the data job
A research or validation step takes the run lock (`stockbot/data/guard/runlock.py`, folder `F:\Projects\Ravi\StockBotData\locks`). **While a run holds it the daily data job cannot write**: its retries wait and it catches up afterwards (`docs/shared/daily-update/SCHEDULER.md`). Expect the data job to be late by the length of the run; never delete a lock by hand. A long step also records the database sha256 before and after; any difference makes the run INVALID (exit code 3).

## Memory and time (estimates, NOT measured)
One heavy job at a time: about 1 GB per process; the memory view reads the lake once (up to about 16 minutes cold). Run 1 of this strategy took hours for the research and baseline steps (`results_run1_*.time.json`); this run adds the held-bar reads, so expect the same order or somewhat longer. Never start steps 2 and 3 together, and do not run another heavy job (the data job's catch-up, a validation) alongside.

## If it crashes
No partial output is a result. Repeat the IDENTICAL run from scratch into a fresh folder (`results_run2_noneq_retry1/`) with the owner's approval, and report both.
