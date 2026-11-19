# momentum_calm: run report (family_batch7, K = 1)

Branch `momentum-calm` (worktree `F:\Projects\Ravi\StockBot_wt_momentum_calm`), started from master ee14b35 (family_batch7 registered; the pre-registration text on this branch is byte-identical to 6d8aad2; ledger hash chain verified; `family_budget` 1; spec hash `d215b84c5b2c340929a7bf4bef3d01e3da4f8e613d35fd0a9bc62edc96cbad55`; gates hash `e9b6407f908ff102dd25d9bc3b21a78a52b24c0ea082bba2cd3bb08f81188054`). Run 2026-11-19 22:56 IST to 2026-11-20 about 00:45 IST, every registered step exactly once, no crash, no repeat. `STOCKBOT_VIEW=memory`, `STOCKBOT_NON_EQ=held`, `STOCKBOT_RISK_PCT` not set. The owner told me to run at night (after the 14:00 cutoff in the task); the run finished far before the next 19:30 data job.

## Summary
**Verdict by the decision rule: NOT DEMONSTRATED (registered rule not met; this is not evidence of no edge).** T1 is significant at both blocks, four of the five gates are met on their point estimates, and the drawdown gate is missed.

| item | value |
|---|---|
| T1 adjusted p, 2-month blocks | **0.028** (significant) |
| T1 adjusted p, 3-month blocks | **0.0306** (significant) |
| T3 placebo size | 0.062 ("size ok") |
| min_trades >= 40 | 579 usable (585 closed) **met** |
| min_expectancy_r >= 0.15 | 0.1706 (interval 0.009 to 0.355) **met** |
| min_profit_factor >= 1.3 | 1.4950 (1.041 to 2.137) **met** |
| max_drawdown_pct <= 20 | **24.94 NOT met** |
| min_alpha_pct >= 0 | 3.8067 (cash-credited, pre-tax; interval -2.23 to 10.51) **met** (raw alpha 1.4230) |

- Because the drawdown gate fails, the rule is not met although T1 passed. Status stays `research`.
- Stale exits: **1** (GSKCONS, 2020-04-03 to 2020-05-14, net P&L +6,523; `SYMBOL_NO_BARS`). With the 0.5x stress line all gates met: False (same as the point result; drawdown 25.3). Baseline stale-exit draws: 10.
- `SELL_CAPPED_NON_EQ` events: **0**. `NOT_EQ_SERIES` blocks: **0**. `symbol_no_bars_exits`: 1.
- Mean invested share **0.6654** (p5 0.0, p95 0.9999); mean open positions 7.02, max 12; entries per month 4.45.
- Months with fewer than 25 picks: **1** (2020-05-04, 23 calm candidates), taken from the overlap check (`OVERLAP.json`; the engine does not store its proposals). The first 11 months of the window (2016-01 to 2016-11) have no signal by the rule's definition.
- End-of-window: 7 trades (counted as usable), 112 baseline draws. Baseline: 11,419 draws.
- Implied-return line printed by the gates script: 53.66 trades a year x 0.1706 R x 1.0% = 9.15% a year, beside the matched Nifty CAGR 8.88%. Sub-periods (descriptive): 2016-2019 156 trades, expectancy 0.170, PF 1.497, max drawdown 18.4; 2020-2026 423 trades, expectancy 0.171, PF 1.495, max drawdown 23.6.

## Descriptive side-by-side (stored numbers; `results_run1/comparison.md`; decides nothing)
| item | family_batch2 monthly (1.0%, EQ only) | family_batch6 monthly (0.5%, BE/BZ) | family_batch3 low volatility (1.0%, EQ only) | **family_batch7 momentum_calm (1.0%, BE/BZ)** |
|---|---|---|---|---|
| trades | 650 | 770 | 413 | **585** |
| expectancy (net R) | 0.2109 | 0.1771 | 0.1413 | **0.1706** |
| profit factor | 1.4504 | 1.4024 | 1.3069 | **1.4950** |
| max drawdown % | 34.32 | 23.68 | 25.97 | **24.94** |
| cash-credited alpha % | 5.4538 | 2.7115 | -2.4336 | **3.8067** |
| T1 adjusted p (2 / 3) | 0.0082 / 0.0096 | 0.0861 / 0.0943 | 0.192 / 0.188 | **0.028 / 0.0306** |
| net profit | 2,101,956 | 770,799 | 894,581 | **1,874,407** |
| mean invested share | 0.6044 | 0.3188 | 0.7343 | **0.6654** |

The strategy's own worst fall (peak to trough; recovery), from each stored equity curve: batch2 34.3% (2024-02-08 to 2025-10-14, not recovered); batch6 23.7% (2024-02-08 to 2025-11-06, not recovered); batch3 26.0% (2021-10-18 to 2022-06-20, recovered 2023-11-30); **momentum_calm 24.9% (2021-10-14 to 2022-06-22, recovered 2023-09-05)**. Reading caveats, as in the pre-registration: batch2 and batch3 were EQ-only while this run held BE/BZ bars, so the runs differ in more than the strategy; the comparison is descriptive and decides nothing. As the registered text said (section 5), the baseline pool was riskadj_momentum's unchanged pool (not restricted to calm stocks), so any benefit of simply holding calm stocks counts as this strategy's edge in T1; this is the tenth look at the same ten years and a T1 pass here is weak evidence.

## db_check and guard
- Research (long step): `db_check` unchanged, full file sha256 before = after, -wal 0 bytes, guard counter 0, sealed dates and table digests identical. Baseline (long step): unchanged, same verification. Benchmark, gates and validate_family (short steps): "database check ... unchanged".
- **File sha256 before = after = `850221b83c143e7b6149b36da2957b3b05d51bf964f79568cd7c9a43efd19e95`** (`sha_before.txt`, `sha_after.txt`, equal). **Correction counter 0 before and 0 after**; `guard_before.json` and `guard_after.json` are identical.
- Manifest checks after research: `asof_view` memory; `non_eq_view` present; `non_eq_events` present; **no `risk_override`**; `end_of_window` block; baseline_meta has no `risk_override`.
- No run lock was in the folder at the start and none was removed.

## Timings (`results_run1/timings.txt`)
research 2,744 s (about 46 min); baseline 1,976 s (about 33 min); benchmark 26 s; gates 27 s; validate_family 56 s; comparison 2 s. Total about 80 minutes (the estimate was about 2.4 hours).

## What ran and what did not
Ran once each: plan, research, baseline, benchmark, gates, one `validate_family --expect-k 1`, the comparison, the sha256 and guard checks before and after. Did NOT run: any second run, any ledger write, any other script. No rule, parameter, gate, config or script logic was changed. The results folder `docs/strategies/momentum_calm/results_run1/` holds the result files, the step logs, `timings.txt` and the sha and guard files.

## Ledger row (NOT written; the owner writes it on master)
```
record_family_results(path=<family_ledger.csv>, family_id="family_batch7",
                      results={"momentum_calm": <the "momentum_calm" entries of docs/strategies/momentum_calm/results_run1/family_results.json>},
                      git_sha=<the commit that carries results_run1>)
```
`family_results.json` is the file `validate_family.py` wrote; use the same call form as for family_batch6 (the ledger accepts exactly the one registered member).
