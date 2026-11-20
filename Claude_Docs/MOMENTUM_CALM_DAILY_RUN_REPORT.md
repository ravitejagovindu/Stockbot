# momentum_calm_daily: run report (family_batch8, K = 1)

Branch `momentum-calm-daily` (worktree `F:\Projects\Ravi\StockBot_wt_mc_daily`), started from master 85e91df (family_batch8 registered; the pre-registration and run-command text on this branch are byte-identical to 7ae7ccd; ledger hash chain verified; `family_budget` 1; spec hash `814dce51b04fbfb7d2463822fd81176643e4a4e35bcc2b3861745270104bd152`; gates hash `e9b6407f908ff102dd25d9bc3b21a78a52b24c0ea082bba2cd3bb08f81188054`). Run 2026-11-20 09:14 IST to about 11:30 IST, every registered step exactly once, no crash, no repeat. `STOCKBOT_VIEW=memory`, `STOCKBOT_NON_EQ=held`, `STOCKBOT_RISK_PCT` not set.

## Summary
**Verdict by the decision rule: NOT DEMONSTRATED (registered rule not met; this is not evidence of no edge).** T1 is not significant at either block and the drawdown gate is missed; the other four gates are met on their point estimates.

| item | value |
|---|---|
| T1 adjusted p, 2-month blocks | **0.1391** (not significant) |
| T1 adjusted p, 3-month blocks | **0.1216** (not significant) |
| T3 placebo size | 0.049 ("size ok") |
| min_trades >= 40 | 821 usable (828 closed) **met** |
| min_expectancy_r >= 0.15 | 0.1664 (interval 0.020 to 0.335) **met** |
| min_profit_factor >= 1.3 | 1.3455 (0.972 to 1.875) **met** |
| max_drawdown_pct <= 20 | **35.80 NOT met** |
| min_alpha_pct >= 0 | 2.0255 (cash-credited, pre-tax; interval -4.75 to 9.57) **met** (raw alpha 1.0159) |

- Stale exits: **2** (`SYMBOL_NO_BARS`: GSKCONS and JBCHEPHARM, total net P&L +24,448). With the 0.5x stress line all gates met: False (same as the point result). Baseline stale-exit draws: 21.
- `SELL_CAPPED_NON_EQ` events: **0**. `NOT_EQ_SERIES` blocks: **0**. `symbol_no_bars_exits`: 2.
- Mean invested share **0.8570** (p5 0.0, p95 1.0); mean open positions 10.23, max 12; entries per month 6.32.
- **Fees (sum of the closed trades' `costs`): 279,239 INR. Profit before fees (sum of gross P&L) 2,067,008; net profit 1,787,769. Fees are 13.5% of the profit before fees (15.6% of the net profit).**
- End-of-window: 8 trades (counted as usable), 151 baseline draws. Baseline: 16,031 draws; pool exclusions per entry (rule C, as registered): 6,945 held and 7,374 cooldown symbol-checks excluded out of 276,702 checked.
- Implied-return line printed by the gates script: 76.09 trades a year x 0.1664 R x 1.0% = 12.66% a year, beside the matched Nifty CAGR 8.97%. Sub-periods (descriptive): 2016-2019 233 trades, expectancy 0.129, PF 1.243, max drawdown 19.6, alpha negative; 2020-2026 588 trades, expectancy 0.181, PF 1.370, max drawdown 28.9.
- Reading in context (as the pre-registration says, the side-by-side decides nothing): the filter did not rescue T1 for the any-day rule (family_batch5 0.4236 / 0.4270 here 0.1391 / 0.1216, still above 0.05) and the drawdown stayed at 35.8%, close to the unfiltered any-day runs at 1.0% risk. As registered, the baseline pool was NOT restricted to calm stocks, so any benefit of holding calm stocks is counted as this strategy's edge; this is the eleventh look at the same ten years.

## Descriptive side-by-side (stored numbers; `results_run1/comparison.md`; decides nothing)
| item | batch4 any-day (1.0%, EQ only) | batch5 any-day (1.0%, BE/BZ) | batch6 any-day (0.5%, BE/BZ) | batch7 momentum_calm monthly (1.0%, BE/BZ) | **batch8 momentum_calm_daily (1.0%, BE/BZ)** |
|---|---|---|---|---|---|
| trades | 1048 | 1061 | 1077 | 585 | **828** |
| expectancy (net R) | 0.2079 | 0.1581 | 0.1543 | 0.1706 | **0.1664** |
| profit factor | 1.4331 | 1.3202 | 1.3562 | 1.4950 | **1.3455** |
| max drawdown % | 36.15 | 45.61 | 24.87 | 24.94 | **35.80** |
| cash-credited alpha % | 7.0611 | 3.0158 | 3.3119 | 3.8067 | **2.0255** |
| T1 adjusted p (2 / 3) | 0.0461 / 0.0499 | 0.4236 / 0.427 | 0.4243 / 0.4304 | 0.028 / 0.0306 | **0.1391 / 0.1216** |
| net profit | 3,582,675 | 2,190,428 | 1,040,143 | 1,874,407 | **1,787,769** |
| fees | 402,653 | 331,121 | 155,190 | 219,043 | **279,239** |
| mean invested share | 0.8030 | 0.7975 | 0.4457 | 0.6654 | **0.8570** |

The strategy's own worst fall (peak to trough; recovery), from each stored equity curve: batch4 36.1% (2018-01-09 to 2020-03-23, recovered 2020-09-15); batch5 45.6% (2018-01-09 to 2020-03-23, recovered 2021-03-23); batch6 24.9% (2018-01-09 to 2020-03-23, recovered 2021-05-06); batch7 24.9% (2021-10-14 to 2022-06-22, recovered 2023-09-05); **momentum_calm_daily 35.8% (2018-08-29 to 2020-03-23, recovered 2021-01-11)**. Caveats as registered: batch4 was EQ-only while the others hold BE/BZ bars, batch6 runs at half risk, and batch7 is the monthly rule, so the runs differ in more than the filter.

## db_check and guard
- Research (long step): `db_check` unchanged, full file sha256 before = after, correction counter 0 before and after, sealed dates and table digests identical. Baseline (long step): unchanged, same verification. Benchmark, gates and validate_family (short steps): "database check ... unchanged".
- **File sha256 before = after = `2c25a7b873d2ea47a7ee182e2d105ffc42743fcacad4fc3b7b16cfe04df771e0`** (`sha_before.txt`, `sha_after.txt`, equal). **Correction counter 0 before and 0 after**; `guard_before.json` and `guard_after.json` are identical.
- Manifest checks after research: `asof_view` memory; `non_eq_view` present; `non_eq_events` present; **no `risk_override`**; `end_of_window` block; baseline_meta has no `risk_override` and `finsight_db.unchanged` true.
- No run lock was present at the start and none was removed.

## Timings (`results_run1/timings.txt`)
research 4,954 s (about 83 min); baseline 2,820 s (about 47 min); benchmark 27 s; gates 29 s; validate_family 62 s; comparison 1 s. Total about 2 hours 12 minutes of step time (the estimate was 3 to 3.5 hours).

## What ran and what did not
Ran once each: plan, research, baseline, benchmark, gates, one `validate_family --expect-k 1`, the comparison, the sha256 and guard checks before and after. Did NOT run: any second run, any ledger write, any other script. No rule, parameter, gate, config or script logic was changed. The results folder `docs/strategies/momentum_calm_daily/results_run1/` holds the result files, the step logs, `timings.txt` and the sha and guard files.

## Ledger row (NOT written; the owner writes it on master)
```
record_family_results(path=<family_ledger.csv>, family_id="family_batch8",
                      results={"momentum_calm_daily": <the "momentum_calm_daily" entries of docs/strategies/momentum_calm_daily/results_run1/family_results.json>},
                      git_sha=<the commit that carries results_run1>)
```
`family_results.json` is the file `validate_family.py` wrote; use the same call form as for family_batch7 (the ledger accepts exactly the one registered member).
