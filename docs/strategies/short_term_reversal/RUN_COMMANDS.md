# short_term_reversal: commands for the registered run

**Do not run any of this until the owner has registered family_batch1 (K = 2) on master and this branch holds the approved pre-registration commit.** Nothing here has been run on the real lake. The spec hash printed by the plan step must equal the one in `PREREGISTRATION.md` (`57b86c47d0c5cbdc1325e19230c103b84bc08c6be6b495aadb99d1aa84ec6168` at the stage-2 commit).

Work from the strategy worktree (`F:\Projects\Ravi\StockBot_wt_reversal`, branch `short_term_reversal`). Every output goes under `docs/strategies/short_term_reversal/results_run1/`:

```
results_run1/
  run/        manifest.json trades.json equity_curve.json daily.json blocked.json     (step 2)
  baseline/   actual_trades.csv baseline_draws.csv baseline_meta.json                   (step 3)
  benchmark.json                                                                      (step 4)
  gates.json                                                                          (step 5)
```
`results_run1/` is the member directory for `scripts/validate_family.py --member short_term_reversal=<results_run1>` (it reads `run/` and `baseline/`). Each script refuses to write into a non-empty directory, so a second run needs a new folder and the owner's approval.

## 0. Settings (once per shell)
Windows cmd:
```
cd /d F:\Projects\Ravi\StockBot_wt_reversal
set STOCKBOT_DB=F:\Projects\Ravi\StockBot\finsight.db
set STOCKBOT_VIEW=memory
```
Git Bash:
```
cd /f/Projects/Ravi/StockBot_wt_reversal
export STOCKBOT_DB='F:\Projects\Ravi\StockBot\finsight.db'
export STOCKBOT_VIEW=memory
```
Check the database first: `sha256` of `finsight.db` must be `dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752` (cmd: `certutil -hashfile %STOCKBOT_DB% SHA256`; Git Bash: `sha256sum "$(cygpath "$STOCKBOT_DB")"`). Check it again after the last step.

## 1. Plan only (prints the window, spec hash, shared-config hash and asof_view; runs nothing)
```
py -3 scripts\research_short_term_reversal.py --out docs\strategies\short_term_reversal\results_run1\run
```
Git Bash: `py -3 scripts/research_short_term_reversal.py --out docs/strategies/short_term_reversal/results_run1/run`. Confirm `"asof_view": "memory"`, the window 2016-01-01 to 2026-10-16 and the spec hash.

## 2. The registered run (one backtest, `--execute` is required)
cmd:
```
py -3 scripts\research_short_term_reversal.py --execute --out docs\strategies\short_term_reversal\results_run1\run > docs\strategies\short_term_reversal\results_run1_run.log 2>&1
```
Git Bash:
```
py -3 scripts/research_short_term_reversal.py --execute --out docs/strategies/short_term_reversal/results_run1/run > docs/strategies/short_term_reversal/results_run1_run.log 2>&1
```
The log prints `asof_view: memory` at the start; `run/manifest.json` carries `"asof_view": "memory"`. If it is interrupted, do not look at partial output; restarting the IDENTICAL run (same spec hash, same data, same seeds) into a new empty folder is the only allowed repeat, and only with the owner's approval.

## 3. B1 baseline (matched random, 20 draws per trade, seed 20261111)
cmd:
```
py -3 scripts\baseline_matched_random_short_term_reversal.py --run-dir docs\strategies\short_term_reversal\results_run1\run --out-dir docs\strategies\short_term_reversal\results_run1\baseline
```
Git Bash:
```
py -3 scripts/baseline_matched_random_short_term_reversal.py --run-dir docs/strategies/short_term_reversal/results_run1/run --out-dir docs/strategies/short_term_reversal/results_run1/baseline
```
It prints `asof_view: memory`, hashes the database before and after (add `--no-hash` only to skip the hash; size and mtime are still compared) and writes `unchanged` into `baseline_meta.json`.

## 4. B2 benchmark (reads the Nifty index series only)
cmd:
```
py -3 scripts\benchmark_nifty_matched_short_term_reversal.py --run-dir docs\strategies\short_term_reversal\results_run1\run --lake %STOCKBOT_DB% --out-json docs\strategies\short_term_reversal\results_run1\benchmark.json
```
Git Bash:
```
py -3 scripts/benchmark_nifty_matched_short_term_reversal.py --run-dir docs/strategies/short_term_reversal/results_run1/run --lake "$STOCKBOT_DB" --out-json docs/strategies/short_term_reversal/results_run1/benchmark.json
```

## 5. Gates (the shared validation_gates beside the observed values; point estimates)
cmd:
```
py -3 scripts\evaluate_validation_gates_short_term_reversal.py --run-dir docs\strategies\short_term_reversal\results_run1\run --lake %STOCKBOT_DB% --out-json docs\strategies\short_term_reversal\results_run1\gates.json
```
Git Bash:
```
py -3 scripts/evaluate_validation_gates_short_term_reversal.py --run-dir docs/strategies/short_term_reversal/results_run1/run --lake "$STOCKBOT_DB" --out-json docs/strategies/short_term_reversal/results_run1/gates.json
```
Do not pass `--t1` (it reads the single-strategy T1 file); the registered conclusion for the family comes from step 6.

## 6. Joint validation (after BOTH members have finished their steps 2 to 3; run once, family-wise)
Git Bash (cmd: use `^` for line continuation and backslashes):
```
py -3 scripts/validate_family.py --member short_term_reversal=docs/strategies/short_term_reversal/results_run1 --member pullback_uptrend=<pullback_uptrend member dir> --expect-k 2 --lake "$STOCKBOT_DB" --out-json <family results json>
```
(B = 10,000, blocks 2 and 3, seed 20261111 are the defaults.)

## Expected times and resources
- Engine-only registered run (step 2): about **55 minutes** on the memory view (the figure measured for the full 2016-2026 window on the earlier run; the SQL view takes several hours). This strategy scans every eligible symbol every session (an 11-bar window each), so its own timing is to be measured, not promised.
- Matched-random baseline (step 3): about **22 minutes** on the memory view for near_52w_high (774 trades). This strategy is expected to have about 3,000 to 3,300 trades (the occupancy model: 23.0 to 25.6 a month), several times more, so the baseline will take longer; the figure for this member is to be measured.
- Add up to **16 minutes** the first time the lake file is read cold (once per process).
- About **1 GB** of memory per process. Run **at most two** of these at once on this machine (another strategy's session may be running; if a run is killed for memory, wait and re-run it alone; a partial run is never a result).
- Steps 4 and 5 take seconds to minutes; step 6 takes minutes to tens of minutes (B = 10,000, 1,000 placebo replications).
