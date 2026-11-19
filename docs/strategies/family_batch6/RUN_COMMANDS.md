# family_batch6: commands for the registered runs (two members, K = 2)

**Do not run any of this until the owner has registered `family_batch6` (K = 2) on master and this branch holds the registered pre-registration commit.** Nothing here has been run on the real lake. The plan step of each member must print its own spec hash: `riskadj_momentum` `72dbec2c3da600cfe6de049a64efd530171ef2f539075f53e57a05e972ef27dc`, `riskadj_momentum_daily` `5b06f092df061bff1532093d21ea21c88c3f2db64ddd66e0cbe81bd5c0446e19`.

Work only in the run worktree (branch `half-risk-run`, `F:\Projects\Ravi\StockBot_wt_halfrisk`); never switch branches in the main folder. Output folders (each is the member directory for `validate_family.py`: `DIR/run` and `DIR/baseline`):
```
docs/strategies/family_batch6/results/
  riskadj_momentum/         run/ (manifest trades equity_curve daily blocked)   baseline/ (actual_trades.csv baseline_draws.csv baseline_meta.json)   benchmark.json   gates.json
  riskadj_momentum_daily/   run/                                                 baseline/                                                           benchmark.json   gates.json
  family_results.json   comparison.json   comparison.md
```
Each script refuses a non-empty output directory; a repeat needs a fresh folder and the owner's approval.

## 0. Settings (Git Bash, once per shell; the same in every step of both members)
```
cd /f/Projects/Ravi/StockBot_wt_halfrisk
export STOCKBOT_DB='F:\Projects\Ravi\StockBot\finsight.db'
export STOCKBOT_VIEW=memory
export STOCKBOT_NON_EQ=held
export STOCKBOT_RISK_PCT=0.5
B=docs/strategies/family_batch6/results
```
(cmd: `set STOCKBOT_RISK_PCT=0.5` etc.) `STOCKBOT_RISK_PCT` is the per-run override of `max_loss_pct_per_trade` (accepted 0.1 to 1.0; printed to stderr at the start of every script that reads it; recorded in the manifest and `baseline_meta.json`). **It must be set identically for the research, baseline and gates steps of both members; the baseline refuses a value that differs from its run's, and `validate_family` refuses a mixed pair. Never set it in a paper or live shell (those refuse it).** Before the first step record `sha256sum "$(cygpath "$STOCKBOT_DB")" > $B/sha_before.txt` and `py -3 scripts/guard.py status --json > $B/guard_before.json` (read-only); repeat into `sha_after.txt` and `guard_after.json` after the last step. The hash must be equal and the correction counter unchanged. (The hash is NOT compared with the pre-guard `dcade465...`.) Create `$B` first (`mkdir -p $B`; the scripts only refuse non-empty `run/` and `baseline/` folders).

## Member 1: riskadj_momentum (monthly)
### 1.1 Plan only (runs nothing)
```
py -3 scripts/research_riskadj_momentum.py --out $B/riskadj_momentum/run
```
Confirm `asof_view` memory, window 2016-01-01 to 2026-10-16, the spec hash above, and the line `RISK OVERRIDE ON: max_loss_pct_per_trade = 0.5` on stderr.
### 1.2 The run
```
py -3 scripts/research_riskadj_momentum.py --execute --out $B/riskadj_momentum/run > $B/riskadj_momentum_run.log 2>&1
```
Check `run/manifest.json` before going on: `asof_view` memory; **`risk_override` with `max_loss_pct_per_trade` 0.5 and base 1.0**; a `non_eq_view` block; a `non_eq_events` block; `db_check` clean (`unchanged` true, sha256 before = after). If `risk_override` or `non_eq_view` is missing, or `db_check` is not clean: STOP and report (it is not a result).
### 1.3 B1 baseline
```
py -3 scripts/baseline_matched_random_riskadj_momentum.py --run-dir $B/riskadj_momentum/run --out-dir $B/riskadj_momentum/baseline
```
`baseline_meta.json` must carry `risk_override` 0.5 and `finsight_db.unchanged` true.
### 1.4 B2 benchmark
```
py -3 scripts/benchmark_nifty_matched_riskadj_momentum.py --run-dir $B/riskadj_momentum/run --lake "$STOCKBOT_DB" --out-json $B/riskadj_momentum/benchmark.json
```
### 1.5 Gates (point estimates; no --t1)
```
py -3 scripts/evaluate_validation_gates_riskadj_momentum.py --run-dir $B/riskadj_momentum/run --lake "$STOCKBOT_DB" --out-json $B/riskadj_momentum/gates.json --baseline-dir $B/riskadj_momentum/baseline
```

## Member 2: riskadj_momentum_daily (any day)
```
py -3 scripts/research_riskadj_momentum_daily.py --out $B/riskadj_momentum_daily/run                                                         # plan only
py -3 scripts/research_riskadj_momentum_daily.py --execute --out $B/riskadj_momentum_daily/run > $B/riskadj_momentum_daily_run.log 2>&1       # the run; same manifest checks as 1.2
py -3 scripts/baseline_matched_random_riskadj_momentum_daily.py --run-dir $B/riskadj_momentum_daily/run --out-dir $B/riskadj_momentum_daily/baseline
py -3 scripts/benchmark_nifty_matched_riskadj_momentum_daily.py --run-dir $B/riskadj_momentum_daily/run --lake "$STOCKBOT_DB" --out-json $B/riskadj_momentum_daily/benchmark.json
py -3 scripts/evaluate_validation_gates_riskadj_momentum_daily.py --run-dir $B/riskadj_momentum_daily/run --lake "$STOCKBOT_DB" --out-json $B/riskadj_momentum_daily/gates.json --baseline-dir $B/riskadj_momentum_daily/baseline
```

## 3. Joint validation: ONE call for both members (after both members' steps)
```
py -3 scripts/validate_family.py --member riskadj_momentum=$B/riskadj_momentum --member riskadj_momentum_daily=$B/riskadj_momentum_daily --expect-k 2 --lake "$STOCKBOT_DB" --out-json $B/family_results.json
```
(B = 10,000, blocks 2 and 3, seed 20261111 are the defaults; the Max-T runs over both members; both members must share the window and the override value, otherwise it refuses.)

## 4. The comparison table (read-only; stored numbers only)
```
py -3 scripts/family_batch6_comparison.py --batch6 $B --out-json $B/comparison.json --out-md $B/comparison.md
py -3 scripts/noneq_comparison_riskadj_momentum_daily.py --old docs/strategies/riskadj_momentum_daily/results_run2_noneq --new $B/riskadj_momentum_daily --lake "$STOCKBOT_DB" --out-json $B/noneq_held_list_daily.json
```
The second command lists the any-day member's trades that held a stock through a BE/BZ spell (descriptive).

## Order, timing, locks and the daily data job
- **One heavy job at a time**: never two of the research or baseline steps together, and no other heavy job (validation, the data job's catch-up) alongside. About 1 GB of memory per process; the memory view reads the lake once per process (up to about 16 minutes cold).
- **Time estimate (from the earlier runs; NOT measured for this trial):** research about 80 minutes and baseline about 61 minutes per member (the any-day member's batch-5 timings: 4,799 s and 3,688 s; the monthly member is expected to be faster), the short steps about 2 minutes, validate_family about 1 minute. So **about 2.4 hours per member, about 5 hours for both**; half-size positions may allow more entries (more trades in the baseline), so add a margin.
- **Run locks:** a research, baseline or validation step takes the run lock (`stockbot/data/guard/runlock.py`, folder `F:\Projects\Ravi\StockBotData\locks`). While a run holds it **the daily data job cannot write**: its retries wait and it catches up after the lock is released (`docs/shared/daily-update/SCHEDULER.md`). **The runs must not span the 19:30 IST data job**: start a member before about 14:00 IST, or split the two members across two mornings. Never delete a lock by hand. A long step records the database sha256 before and after; any difference makes the run INVALID (exit code 3).
- **Resuming between members:** the two members are independent runs. Finish all five steps of one member (check its manifest and `db_check` and commit its folder, results files only), then start the other in a fresh shell with the settings of section 0 (the override value must be the same). The family call (section 3) needs both folders. If the db hash changed between the members (the data job ran in between and loaded a new day), that is allowed only if the window stays 2016-01-01 to 2026-10-16 and each run's own `db_check` is clean: record the hashes of both runs in the report; the rows dated up to 2026-10-16 are unchanged by the guard.
- **If a step crashes:** no partial output is a result. Stop and tell the owner; a repeat from scratch into a fresh folder (`results_retry1/`) needs the owner's approval.

## After the runs (owner, on master)
`record_family_results(path=<family_ledger.csv>, family_id="family_batch6", results={"riskadj_momentum": <the member's entry of family_results.json>, "riskadj_momentum_daily": <...>}, git_sha=<commit>)`: both members must be present (the ledger refuses anything else). The run report writes the exact command; the run block never writes the ledger row itself.
