# lowvol_uptrend: commands for the registered run

**Do not run any of this until the owner has registered family_batch3 (K = 1) on master and this branch holds the approved pre-registration commit.** Nothing here has been run on the real lake. The spec hash printed by the plan step must equal the one in `PREREGISTRATION.md` (`52e7ee3ccc2e150d7e4b6b54266bb2c73a8788612691ece475bfa7d1bb0e9e68`).

Work from the strategy worktree (`F:\Projects\Ravi\StockBot_wt_lowvol_uptrend`, branch `lowvol_uptrend`). Every output goes under `docs/strategies/lowvol_uptrend/results_run1/`:

```
results_run1/
  run/        manifest.json trades.json equity_curve.json daily.json blocked.json     (step 2)
  baseline/   actual_trades.csv baseline_draws.csv baseline_meta.json                   (step 3)
  benchmark.json                                                                      (step 4)
  gates.json                                                                          (step 5)
  family_results.json                                                                 (step 6)
```
`results_run1/` is the member directory for `scripts/validate_family.py --member lowvol_uptrend=<results_run1>` (it reads `run/` and `baseline/`). Each script refuses to write into a non-empty directory, so a second run needs a new folder and the owner's approval.

## 0. Settings (once per shell)
Windows cmd:
```
cd /d F:\Projects\Ravi\StockBot_wt_lowvol_uptrend
set STOCKBOT_DB=F:\Projects\Ravi\StockBot\finsight.db
set STOCKBOT_VIEW=memory
```
Git Bash (the commands in steps 1 to 6 below are for Git Bash; in cmd use backslashes in the paths):
```
cd /f/Projects/Ravi/StockBot_wt_lowvol_uptrend
export STOCKBOT_DB='F:\Projects\Ravi\StockBot\finsight.db'
export STOCKBOT_VIEW=memory
```
Check the database first: `sha256` of `finsight.db` must be `dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752` (cmd: `certutil -hashfile %STOCKBOT_DB% SHA256`; Git Bash: `sha256sum "$(cygpath "$STOCKBOT_DB")"`). Check it again after the last step.

## 1. Plan only (prints the window, spec hash, shared-config hash and asof_view; runs nothing)
```
py -3 scripts/research_lowvol_uptrend.py --out docs/strategies/lowvol_uptrend/results_run1/run
```
Confirm `"asof_view": "memory"`, the window 2016-01-01 to 2026-10-16 and the spec hash.

## 2. The registered run (one backtest, `--execute` is required)
```
py -3 scripts/research_lowvol_uptrend.py --execute --out docs/strategies/lowvol_uptrend/results_run1/run > docs/strategies/lowvol_uptrend/results_run1_run.log 2>&1
```
The log prints the plan first; `run/manifest.json` carries `"asof_view": "memory"`, the `symbol_links` block and the `stale_exit` block. If it is interrupted, do not look at partial output; restarting the IDENTICAL run (same spec hash, same data, same seeds) into a new empty folder is the only allowed repeat, and only with the owner's approval.

## 3. B1 baseline (matched random, 20 draws per trade, seed 20261111)
```
py -3 scripts/baseline_matched_random_lowvol_uptrend.py --run-dir docs/strategies/lowvol_uptrend/results_run1/run --out-dir docs/strategies/lowvol_uptrend/results_run1/baseline
```
It prints `asof_view: memory`, hashes the database before and after (add `--no-hash` only to skip the hash; size and mtime are still compared) and writes `unchanged` into `baseline_meta.json`.

## 4. B2 benchmark (reads the Nifty index series only)
```
py -3 scripts/benchmark_nifty_matched_lowvol_uptrend.py --run-dir docs/strategies/lowvol_uptrend/results_run1/run --lake "$STOCKBOT_DB" --out-json docs/strategies/lowvol_uptrend/results_run1/benchmark.json
```

## 5. Gates (the shared validation_gates beside the observed values; point estimates)
```
py -3 scripts/evaluate_validation_gates_lowvol_uptrend.py --run-dir docs/strategies/lowvol_uptrend/results_run1/run --lake "$STOCKBOT_DB" --out-json docs/strategies/lowvol_uptrend/results_run1/gates.json --baseline-dir docs/strategies/lowvol_uptrend/results_run1/baseline
```
Do not pass `--t1`; the registered conclusion comes from step 6. `--baseline-dir` only adds the end-of-window draw counts. The output also prints the stale-exit lines (trades closed by SYMBOL_NO_BARS and the stress line at 0.5 x the last close).

## 6. Joint validation, family of ONE (after steps 2 and 3)
```
py -3 scripts/validate_family.py --member lowvol_uptrend=docs/strategies/lowvol_uptrend/results_run1 --expect-k 1 --lake "$STOCKBOT_DB" --out-json docs/strategies/lowvol_uptrend/results_run1/family_results.json
```
(B = 10,000, blocks 2 and 3, seed 20261111 are the defaults; `--expect-k 1` refuses any other member count.) `validate_family.py` does not print the end-of-window or stale-exit counts: read them from `run/manifest.json` (`end_of_window.trades`, `stale_exit`) and `baseline/baseline_meta.json` (`end_of_window_trades`, `end_of_window_draws`, `stale_exit_draws`), or run step 5 with `--baseline-dir`.

## What the run does with trades open at the window end
They are closed at the last close (2026-10-16) with normal costs and slippage and COUNT as usable trades; random draws likewise (PREREGISTRATION section 7a). In `run/trades.json` such a trade has `exit_reason` `END_OF_WINDOW_COUNTED` (the shared gate code would drop the exact string `END_OF_WINDOW`), engine label in `exit_reason_engine`.

## What the run does with symbols that stop having bars
The shared rule (data.symbol_links_enabled true, engine.stale_exit_sessions 20): a renamed stock is one symbol under its latest name; a position whose symbol has no bar for 20 consecutive sessions is closed at its last close (reason `SYMBOL_NO_BARS`), with normal costs, and counts as a usable trade. They are reported with a stress line at 0.5 x the last close.

## Expected times and resources (estimates, NOT measured on the real lake: nothing here has been run)
- Step 2, engine run, memory view: the counts over the 130 signal sessions took the time shown in `counts/summary.json` (`seconds`). The engine adds a step of every open position on every one of about 2,700 sessions. Estimate **15 to 45 minutes**.
- Step 3, baseline: about 20 draws per trade; a draw runs until its trailing stop fires or the window ends (long holds), as for riskadj_momentum. Estimate **2 to 4 hours** on the memory view; to be measured.
- Add up to **16 minutes** the first time the lake file is read cold (once per process).
- About **1 GB** of memory per process. Run **at most two** of these at once on this machine; a partial run is never a result.
- Steps 4 and 5 take seconds to minutes; step 6 takes minutes to tens of minutes (B = 10,000, 1,000 placebo replications).
