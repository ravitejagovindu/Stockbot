# riskadj_momentum: commands for the registered run

**Do not run any of this until the owner has registered family_batch2 (K = 1) on master and this branch holds the approved pre-registration commit.** Nothing here has been run on the real lake. The spec hash printed by the plan step must equal the one in `PREREGISTRATION.md` (`72dbec2c3da600cfe6de049a64efd530171ef2f539075f53e57a05e972ef27dc`).

Work from the strategy worktree (`F:\Projects\Ravi\StockBot_wt_riskadj`, branch `riskadj_momentum`). Every output goes under `docs/strategies/riskadj_momentum/results_run1/`:

```
results_run1/
  run/        manifest.json trades.json equity_curve.json daily.json blocked.json     (step 2)
  baseline/   actual_trades.csv baseline_draws.csv baseline_meta.json                   (step 3)
  benchmark.json                                                                      (step 4)
  gates.json                                                                          (step 5)
```
`results_run1/` is the member directory for `scripts/validate_family.py --member riskadj_momentum=<results_run1>` (it reads `run/` and `baseline/`). Each script refuses to write into a non-empty directory, so a second run needs a new folder and the owner's approval.

## 0. Settings (once per shell)
Windows cmd:
```
cd /d F:\Projects\Ravi\StockBot_wt_riskadj
set STOCKBOT_DB=F:\Projects\Ravi\StockBot\finsight.db
set STOCKBOT_VIEW=memory
```
Git Bash:
```
cd /f/Projects/Ravi/StockBot_wt_riskadj
export STOCKBOT_DB='F:\Projects\Ravi\StockBot\finsight.db'
export STOCKBOT_VIEW=memory
```
Check the database first: `sha256` of `finsight.db` must be `dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752` (cmd: `certutil -hashfile %STOCKBOT_DB% SHA256`; Git Bash: `sha256sum "$(cygpath "$STOCKBOT_DB")"`). Check it again after the last step.

## 1. Plan only (prints the window, spec hash, shared-config hash and asof_view; runs nothing)
```
py -3 scripts\research_riskadj_momentum.py --out docs\strategies\riskadj_momentum\results_run1\run
```
Git Bash: `py -3 scripts/research_riskadj_momentum.py --out docs/strategies/riskadj_momentum/results_run1/run`. Confirm `"asof_view": "memory"`, the window 2016-01-01 to 2026-10-16 and the spec hash.

## 2. The registered run (one backtest, `--execute` is required)
cmd:
```
py -3 scripts\research_riskadj_momentum.py --execute --out docs\strategies\riskadj_momentum\results_run1\run > docs\strategies\riskadj_momentum\results_run1_run.log 2>&1
```
Git Bash:
```
py -3 scripts/research_riskadj_momentum.py --execute --out docs/strategies/riskadj_momentum/results_run1/run > docs/strategies/riskadj_momentum/results_run1_run.log 2>&1
```
The log prints `asof_view: memory` at the start; `run/manifest.json` carries `"asof_view": "memory"`. If it is interrupted, do not look at partial output; restarting the IDENTICAL run (same spec hash, same data, same seeds) into a new empty folder is the only allowed repeat, and only with the owner's approval.

## 3. B1 baseline (matched random, 20 draws per trade, seed 20261111)
cmd:
```
py -3 scripts\baseline_matched_random_riskadj_momentum.py --run-dir docs\strategies\riskadj_momentum\results_run1\run --out-dir docs\strategies\riskadj_momentum\results_run1\baseline
```
Git Bash:
```
py -3 scripts/baseline_matched_random_riskadj_momentum.py --run-dir docs/strategies/riskadj_momentum/results_run1/run --out-dir docs/strategies/riskadj_momentum/results_run1/baseline
```
It prints `asof_view: memory`, hashes the database before and after (add `--no-hash` only to skip the hash; size and mtime are still compared) and writes `unchanged` into `baseline_meta.json`.

## 4. B2 benchmark (reads the Nifty index series only)
cmd:
```
py -3 scripts\benchmark_nifty_matched_riskadj_momentum.py --run-dir docs\strategies\riskadj_momentum\results_run1\run --lake %STOCKBOT_DB% --out-json docs\strategies\riskadj_momentum\results_run1\benchmark.json
```
Git Bash:
```
py -3 scripts/benchmark_nifty_matched_riskadj_momentum.py --run-dir docs/strategies/riskadj_momentum/results_run1/run --lake "$STOCKBOT_DB" --out-json docs/strategies/riskadj_momentum/results_run1/benchmark.json
```

## 5. Gates (the shared validation_gates beside the observed values; point estimates)
cmd:
```
py -3 scripts\evaluate_validation_gates_riskadj_momentum.py --run-dir docs\strategies\riskadj_momentum\results_run1\run --lake %STOCKBOT_DB% --out-json docs\strategies\riskadj_momentum\results_run1\gates.json --baseline-dir docs\strategiesiskadj_momentumesults_run1aseline
```
Git Bash:
```
py -3 scripts/evaluate_validation_gates_riskadj_momentum.py --run-dir docs/strategies/riskadj_momentum/results_run1/run --lake "$STOCKBOT_DB" --out-json docs/strategies/riskadj_momentum/results_run1/gates.json --baseline-dir docs/strategies/riskadj_momentum/results_run1/baseline
```
Do not pass `--t1`; the registered conclusion comes from step 6. `--baseline-dir` only adds the end-of-window draw counts.

## 6. Joint validation, family of ONE (after steps 2 and 3)
Git Bash:
```
py -3 scripts/validate_family.py --member riskadj_momentum=docs/strategies/riskadj_momentum/results_run1 --expect-k 1 --lake "$STOCKBOT_DB" --out-json docs/strategies/riskadj_momentum/results_run1/family_results.json
```
cmd:
```
py -3 scriptsalidate_family.py --member riskadj_momentum=docs\strategies
iskadj_momentum
esults_run1 --expect-k 1 --lake %STOCKBOT_DB% --out-json docs\strategies
iskadj_momentum
esults_run1amily_results.json
```
(B = 10,000, blocks 2 and 3, seed 20261111 are the defaults; `--expect-k 1` refuses any other member count.) `validate_family.py` does not print the end-of-window counts: read them from `run/manifest.json` (`end_of_window.trades`) and `baseline/baseline_meta.json` (`end_of_window_trades`, `end_of_window_draws`), or run step 5 with `--baseline-dir docs/strategies/riskadj_momentum/results_run1/baseline`, which puts both numbers into `gates.json`.

## What the run does with trades open at the window end
They are closed at the last close (2026-10-16) with normal costs and slippage and COUNT as usable trades; random draws likewise (PREREGISTRATION section 7a). In `run/trades.json` such a trade has `exit_reason` `END_OF_WINDOW_COUNTED` (the shared gate code would drop the exact string `END_OF_WINDOW`), engine label in `exit_reason_engine`.

## Expected times and resources (estimates, NOT measured on the real lake: nothing here has been run)
- Step 2, engine run, memory view: the stage-1 counts over all 130 signal sessions took 332 s. The engine adds a step of every open position on every one of about 2,700 sessions (each reads its last 252 bars for the ATR). Estimate **15 to 45 minutes**.
- Step 3, baseline: about 4,500 draws (226 trades x 20; the real number is unknown until the run), and a draw runs until its trailing stop fires or the window ends, so on average perhaps 100 to 150 sessions, against 5 for the pullback baseline (22 minutes for 774 trades on near_52w_high). Estimate **2 to 4 hours** on the memory view; this member's real figure is to be measured.
- Add up to **16 minutes** the first time the lake file is read cold (once per process).
- About **1 GB** of memory per process. Run **at most two** of these at once on this machine; if a run is killed for memory, wait and re-run it alone; a partial run is never a result.
- Steps 4 and 5 take seconds to minutes; step 6 takes minutes to tens of minutes (B = 10,000, 1,000 placebo replications).
