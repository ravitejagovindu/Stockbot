# momentum_calm: commands for the registered run (one member, K = 1)

**Do not run any of this until the owner has registered `family_batch7` (K = 1) on master and this branch holds the registered pre-registration commit.** Nothing here has been run on the real lake (the overlap check is the only step that has touched it, counts only). The plan step must print the spec hash `d215b84c5b2c340929a7bf4bef3d01e3da4f8e613d35fd0a9bc62edc96cbad55`.

Work only in the strategy worktree (branch `momentum-calm`, `F:\Projects\Ravi\StockBot_wt_momentum_calm`); never switch branches in the main folder. Print folder and branch before you start and after every commit. Output folder `docs/strategies/momentum_calm/results_run1/` (not created yet), also the member directory for `validate_family.py`:
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
cd /f/Projects/Ravi/StockBot_wt_momentum_calm
export STOCKBOT_DB='F:\Projects\Ravi\StockBot\finsight.db'
export STOCKBOT_VIEW=memory
export STOCKBOT_NON_EQ=held
unset STOCKBOT_RISK_PCT
D=docs/strategies/momentum_calm/results_run1
mkdir -p $D
```
**`STOCKBOT_RISK_PCT` must NOT be set** (standard 1.0% risk; a run manifest that carries `risk_override` is invalid). `STOCKBOT_NON_EQ=held` must be set identically in the research, baseline and gates steps. Before the first step record `sha256sum "$(cygpath "$STOCKBOT_DB")" > $D/sha_before.txt` and `py -3 scripts/guard.py status --json > $D/guard_before.json` (read-only); repeat into `sha_after.txt` and `guard_after.json` after the last step. The hash must be equal and the correction counter unchanged.

## 1. Plan only (runs nothing)
```
py -3 scripts/research_momentum_calm.py --out $D/run
```
Confirm: `asof_view` memory, window 2016-01-01 to 2026-10-16, the spec hash above, exit policy `mc_trailing_atr3_floor8`, status `research`, NO `RISK OVERRIDE ON` line on stderr, and `lake` = `F:ProjectsRaviStockBotinsight.db` (the plan prints the default path of the worktree if `STOCKBOT_DB` is not exported).

## 2. The run
```
py -3 scripts/research_momentum_calm.py --execute --out $D/run > $D/research.log 2>&1
```
Check `run/manifest.json` before going on: `asof_view` memory; a `non_eq_view` block and a `non_eq_events` block; **no `risk_override`**; `end_of_window` block; `db_check` clean (`unchanged` true, sha256 before = after). If `non_eq_view` is missing, `risk_override` is present, or `db_check` is not clean: STOP and report (it is not a result).

## 3. B1 baseline (20 draws per trade, seed 20261111; riskadj_momentum's pool rule unchanged)
```
py -3 scripts/baseline_matched_random_momentum_calm.py --run-dir $D/run --out-dir $D/baseline > $D/baseline.log 2>&1
```
`baseline_meta.json` must carry `finsight_db.unchanged` true and no `risk_override`.

## 4. B2 benchmark
```
py -3 scripts/benchmark_nifty_matched_momentum_calm.py --run-dir $D/run --lake "$STOCKBOT_DB" --out-json $D/benchmark.json
```

## 5. Gates (point estimates; no --t1)
```
py -3 scripts/evaluate_validation_gates_momentum_calm.py --run-dir $D/run --lake "$STOCKBOT_DB" --out-json $D/gates.json --baseline-dir $D/baseline
```

## 6. Joint validation (T1, T2, T3)
```
py -3 scripts/validate_family.py --member momentum_calm=$D --expect-k 1 --lake "$STOCKBOT_DB" --out-json $D/family_results.json
```
(B = 10,000, blocks 2 and 3, seed 20261111 are the defaults; `--expect-k 1` refuses any other member count.) `validate_family.py` does not print the end-of-window or stale-exit counts: read them from `run/manifest.json` (`end_of_window.trades`, `stale_exit`) and `baseline/baseline_meta.json` (`end_of_window_trades`, `end_of_window_draws`, `stale_exit_draws`).

## 7. The descriptive side-by-side (read-only; stored numbers only; opens no database)
```
py -3 scripts/momentum_calm_comparison.py --calm $D --out-json $D/comparison.json --out-md $D/comparison.md
```
The table sets momentum_calm beside family_batch2 monthly momentum, family_batch6 monthly half-risk and family_batch3 low volatility (trades, expectancy, profit factor, max drawdown, alpha, T1 p, net profit, mean invested share, worst-fall dates). It decides nothing.

## Order, timing, locks and the daily data job
- **One heavy job at a time**: never research and baseline together, and no other heavy job alongside. About 1 GB of memory per process; the memory view reads the lake once per process (up to about 16 minutes cold; the overlap check showed a slow start of roughly 12 minutes before its first output).
- **Time estimate (from the earlier monthly run; NOT measured for this trial): research about 80 minutes, baseline about 60 minutes**, short steps about 2 minutes each, validate_family about 1 minute: **about 2.4 hours** in total, plus a margin (the calm filter may change the number of trades and so the baseline's draws).
- **Run locks:** a research, baseline or validation step takes the run lock (`stockbot/data/guard/runlock.py`, folder `F:\Projects\Ravi\StockBotData\locks`). While a run holds it **the daily data job cannot write**; its retries wait and it catches up afterwards (`docs/shared/daily-update/SCHEDULER.md`). **Start only in the morning, before about 14:00 IST, and never span the 19:30 IST data job.** If the data job holds its lock, WAIT: never delete a lock by hand. A long step records the database sha256 before and after; any difference makes the run INVALID (exit code 3).
- **Database checks:** every short step (overlap, benchmark, gates, validate_family, comparison where it opens the lake) prints a "database check ... unchanged" line; research and baseline also hash the file. A line saying anything else means STOP.
- **If a step crashes:** no partial output is a result. Stop and tell the owner; a repeat from scratch into a fresh folder (`results_run1_retry1/`) needs the owner's approval.

## After the run (owner, on master)
`record_family_results(path=<family_ledger.csv>, family_id="family_batch7", results={"momentum_calm": <the member's entry of family_results.json>}, git_sha=<commit>)`; the run report writes the exact command and the run block never writes the ledger row itself.
