# family_batch6 run report (monthly and any-day momentum at 0.5% risk, K = 2)

Run 2026-11-19 10:59 to about 15:00 IST, worktree `F:\Projects\Ravi\StockBot_wt_halfrisk`, branch `half-risk-run` (fast-forwarded to master 3fdcbf3; text commit 7db6988, ledger commit 3fdcbf3). Results: `docs/strategies/family_batch6/results/`. Every registered step ran exactly once (settings of RUN_COMMANDS.md section 0: `STOCKBOT_VIEW=memory`, `STOCKBOT_NON_EQ=held`, `STOCKBOT_RISK_PCT=0.5`); no rule, parameter, gate, config or script logic was changed; one heavy job at a time; nothing ran near 19:30 IST.

## Summary
**Both members: NOT DEMONSTRATED (registered rule not met; this is not evidence of no edge).** At half risk the **drawdown gate is still missed by both** (23.7% and 24.9% against 20%), although it fell sharply (from 34.3% and 36.1% / 45.6%); T1 is not significant for either member at either block. All other four gates are met on point estimates by both.

| | riskadj_monthly (`riskadj_momentum`) | any-day (`riskadj_momentum_daily`) |
|---|---|---|
| T1 adjusted p, 2-month blocks (Max-T over K = 2) | **0.0861** (not significant) | **0.4243** (not significant) |
| T1 adjusted p, 3-month blocks | **0.0943** (not significant) | **0.4304** (not significant) |
| Gate min_trades >= 40 | 767: met | 1,074: met |
| Gate min_expectancy_r >= 0.15 | **0.1771** (0.019 to 0.354): met | **0.1543** (0.022 to 0.306): met |
| Gate min_profit_factor >= 1.3 | **1.4024** (0.986 to 1.977): met | **1.3562** (1.008 to 1.808): met |
| Gate max_drawdown_pct <= 20 | **23.6844: NOT met** | **24.8724: NOT met** |
| Gate min_alpha_pct >= 0 (cash-credited, pre-tax) | **2.7115** (-2.356 to 8.316): met (raw alpha -1.98) | **3.3119** (-3.254 to 10.442): met (raw alpha -0.54) |
| All gates met | No (4 of 5) | No (4 of 5) |
| Verdict by the decision rule | NOT DEMONSTRATED | NOT DEMONSTRATED |
| Stale exits (SYMBOL_NO_BARS) | 1 (net +3,326) | 1 (GSKCONS 2020-03-19 to 2020-05-14, net +7,418) |
| SELL_CAPPED_NON_EQ events | 0 | 0 |
| NOT_EQ_SERIES blocks | 0 | 1 |
| Mean invested share | 0.3188 (p95 0.565) | 0.4457 (p95 0.655) |
| Closed / usable trades | 770 / 767 (9 closed at the window end, counted) | 1,077 / 1,074 (10 at the window end, counted) |
| Entries a month; mean open positions | 5.9; 7.6 | 8.26; 10.6 |
| Implied annual return (non-gating) vs matched Nifty CAGR | 6.29% vs 7.43% | 7.68% vs 7.38% |

T3 placebo size (joint): 0.052, limits 0.025 to 0.075: **size ok**. Stress line (stale exits at 0.5 x last close): all gates met remains False for both (the drawdown gate is missed anyway). Sub-periods (descriptive): monthly 2016-2019 expectancy 0.226 R, drawdown 7.7%; 2020-2026 0.157 R, drawdown 18.2%; any-day 2016-2019 0.163 R, drawdown 16.3%; 2020-2026 0.151 R, drawdown 18.0% (the whole-window drawdown is larger than either sub-period's, as the run is one path). No stock selection changed, so T1 followed the pattern the text expected: the any-day member's p stays near its batch-5 value (0.4236 / 0.4270 to 0.4243 / 0.4304); the monthly member's p is 0.0861 / 0.0943 (batch 2: 0.0082 / 0.0096 with K = 1, EQ only, 1.0% risk), so its change comes from the different capital path and BE/BZ treatment together with the stricter K = 2 correction; they cannot be separated.

## Side-by-side with earlier runs (descriptive; `comparison.md`; stored numbers only)
Monthly member:
| item | family_batch2 (EQ only, 1.0% risk) | family_batch6 (BE/BZ, 0.5% risk) |
|---|---|---|
| closed trades | 650 | 770 |
| expectancy (net R) | 0.2109 | 0.1771 |
| profit factor | 1.4504 | 1.4024 |
| max drawdown % | 34.32 | 23.68 |
| cash-credited alpha % | 5.45 | 2.71 |
| T1 adjusted p (2 / 3 month) | 0.0082 / 0.0096 | 0.0861 / 0.0943 |
| net profit (INR) | 2,101,956 | 770,799 |
| mean invested share | 0.604 | 0.319 |

Any-day member:
| item | family_batch4 (EQ only, 1.0%) | family_batch5 (BE/BZ, 1.0%) | family_batch6 (BE/BZ, 0.5%) |
|---|---|---|---|
| closed trades | 1,048 | 1,061 | 1,077 |
| expectancy (net R) | 0.2079 | 0.1581 | 0.1543 |
| profit factor | 1.4331 | 1.3202 | 1.3562 |
| max drawdown % | 36.15 | 45.61 | 24.87 |
| cash-credited alpha % | 7.06 | 3.02 | 3.31 |
| T1 adjusted p (2 / 3 month) | 0.0461 / 0.0499 | 0.4236 / 0.4270 | 0.4243 / 0.4304 |
| net profit (INR) | 3,582,675 | 2,190,428 | 1,040,143 |
| mean invested share | 0.803 | 0.798 | 0.446 |
Reading (descriptive, decides nothing; the earlier results stand as recorded): halving the risk roughly halves the invested share and net profit, cuts the drawdown to about 24 to 25% for both rules, leaves expectancy and profit factor near the batch 5 level, and does not move T1. For the monthly member two things changed against batch 2 (risk and BE/BZ), so the table cannot attribute them. Paper trading stays at 1.0%; nothing here decides a paper or live setting.

## Any-day member: trades that held a stock through a BE/BZ spell (16, `noneq_held_list_daily.json`)
IIFL (2017-09-26 to 2017-10-30, 9 BE sessions), BOMDYEING (2018-06-29 to 2018-07-06, 3), CGPOWER (2021-05-17 to 2021-06-10, 2), ATGL (2021-05-17 to 2021-06-16, 6), TANLA (2021-06-07 to 2021-06-17, 7), MAGMA (2021-03-25 to 2021-06-21, 9), GPIL (2021-06-02 to 2021-08-04, 33), TRIDENT (2022-01-19 to 2022-02-11, 15), ZENTEC (2023-08-14 to 2023-09-12, 18), JBMA (2023-08-08 to 2023-09-25, 17), NEWGEN (2023-10-26 to 2024-01-20, 56), SHAILY (2024-12-16 to 2025-01-27, 20), E2E (2026-02-02 to 2026-02-24, 1), QPOWER (2026-05-18 to 2026-07-03, 32), DIACABS (2026-03-17 to 2026-09-03, 23), HFCL (2026-07-27 to 2026-09-03, 1). All 16 exited on a BE bar; no sell was capped (SELL_CAPPED_NON_EQ = 0), so the 10%-of-volume cap and the lock rule did not bind in either member.

## Baselines
Monthly: 15,073 draws for 767 usable trades, 767 pairs kept, none dropped, no flag; end-of-window draws 165. Any-day: 20,976 draws for 1,074 usable trades, 1,073 pairs kept, 1 dropped, no flag; end-of-window draws 136. Both baselines' `baseline_meta.json` carry `risk_override` 0.5 and `finsight_db.unchanged` true. Unfilled draws are listed in the baseline meta files (mainly GAP_UP_TOO_LARGE and CORP_ACTION_ON_EXEC_DATE).

## db_check (control)
| Check | Result |
|---|---|
| Run manifests (both members) | `asof_view` memory; `non_eq_view` present; **`risk_override` 0.5, base 1.0**; `non_eq_events` present; `db_check.unchanged` true, sha256 before = after |
| Baseline meta (both) | `risk_override` 0.5; `finsight_db.unchanged` true |
| Benchmark, gates, validate_family, comparison | short steps: "database check: unchanged", correction counter 0 |
| File sha256 before the first step / after the last | `81e90beff580f962628596031978c918b06e8876cd9ac5bfeb39b3b2377e50d0` / **identical** (`sha_before.txt`, `sha_after.txt`) |
| `guard status --json` before vs after | **byte-identical**; correction counter 0 before and after |
Note: this hash differs from the batch 5 run's (`72885644...`) because the daily data job loaded later sessions in between; the window ends 2026-10-16, so no row dated after it is read, and each run's own `db_check` is clean.

## Timings (seconds)
| Step | Monthly | Any-day |
|---|---|---|
| Research | 2,731 | 4,718 |
| Baseline | 2,604 | 3,672 |
| Benchmark | 26 | 26 |
| Gates | 29 | 27 |
validate_family (both members, K = 2, B = 10,000, blocks 2 and 3, seed 20261111): 92 s; comparison and BE/BZ list: about 1 s each. Total about 4 hours 10 minutes of machine time.

## Ledger: command for the owner (NOT executed; no ledger row written)
On master after merging this branch (the commit SHA is the merge commit or the results commit of this branch):
```
py -3 -c "
import json, pathlib
from stockbot.validation.ledger import record_family_results
fam = json.loads(pathlib.Path('docs/strategies/family_batch6/results/family_results.json').read_text())
record_family_results(path=pathlib.Path('stockbot/validation/ledger/records/family_ledger.csv'), family_id='family_batch6',
                      results={'riskadj_momentum': fam, 'riskadj_momentum_daily': fam}, git_sha='<COMMIT SHA>')"
```
(Both members' results are the one joint `family_results.json`, as the batch 4 row stored the whole file; the ledger needs exactly the two registered ids and nothing else.)

## What ran and what did not
Ran, each once: merge check and verification (hash chain, budget 2, both spec hashes, text identical to 7db6988), `sha_before` and `guard_before`, Member 1 (plan, research, baseline, benchmark, gates), Member 2 (the same), one `validate_family --expect-k 2`, the comparison and the BE/BZ held list, `sha_after` and `guard_after`. Manifest checks passed after each research step (automatic check in the run script, then reread for this report). Did not run: any second run, any tuning, any change of code or config, any ledger write, any merge to master. Not examined: why the any-day drawdown at half risk (24.9%) is nearly equal to the monthly member's (23.7%) although their invested shares differ.
