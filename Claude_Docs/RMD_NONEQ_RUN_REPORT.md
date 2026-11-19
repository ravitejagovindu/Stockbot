# riskadj_momentum_daily re-run with BE/BZ data (family_batch5): run report

Run 2026-11-18 to 2026-11-19, worktree `F:\Projects\Ravi\StockBot_wt_rmd_noneq`, branch `rmd-noneq-run` (fast-forwarded to master 3d3e595; registration commits 1525d08 and 3d3e595). Results: `docs/strategies/riskadj_momentum_daily/results_run2_noneq/`. Every registered step ran exactly once, with no change to any rule, parameter, gate, config or script logic.

## Summary
**Verdict by the decision rule (this run alone): NOT DEMONSTRATED (registered rule not met; this is not evidence of no edge).** T1 is not significant at either block, and one gate (max drawdown) is missed.

| Item | Value |
|---|---|
| T1 adjusted p, blocks 2 months | **0.4236** (observed mean D 0.0809 R, t 0.203), not significant |
| T1 adjusted p, blocks 3 months | **0.4270** (same mean and t), not significant |
| Gate min_trades >= 40 | 1,059 usable: met |
| Gate min_expectancy_r >= 0.15 | **0.1581** (95% interval 0.033 to 0.300): met |
| Gate min_profit_factor >= 1.3 | **1.3202** (0.982 to 1.758): met |
| Gate max_drawdown_pct <= 20 | **45.61: NOT met** |
| Gate min_alpha_pct >= 0 (cash-credited, pre-tax) | **3.0158** (-9.126 to 16.621): met (raw alpha 1.57) |
| All gates met on point estimates | **No** (4 of 5) |
| T3 placebo size | 0.018, limits 0.025 to 0.075: **"size unreliable"** (the owner decides; nothing recalibrated) |
| Stale-exit (SYMBOL_NO_BARS) trades | **2** (GSKCONS 2020-03-19 to 2020-05-14, net +14,850; ADANIENSOL 2021-04-15 to 2021-07-06, net +76,013); with the 0.5x stress line the expectancy gate fails (0.1500 point value shown as NO, alpha 2.36) |
| SELL_CAPPED_NON_EQ events | **0** |
| NOT_EQ_SERIES blocks (proposals) | **2** |
| Trades closed at the window end (counted) | 10 (baseline draws: 165) |
| Closed trades / usable / sessions | 1,061 / 1,059 (2 excluded for corporate actions) / 2,674 |
| db_check | clean at every step (below) |

The family_batch4 result stands as recorded; this run does not replace it.

## Side-by-side with family_batch4 run 1 (descriptive; `comparison.md`)
| item | family_batch4 run 1 | family_batch5 (BE/BZ) |
|---|---|---|
| trades | 1,048 | 1,061 |
| SYMBOL_NO_BARS exits | 18 | 2 |
| exits on a BE/BZ bar | 16 | 16 |
| trades held through a BE/BZ spell | 17 | 16 |
| expectancy (net R) | 0.2079 | 0.1581 |
| profit factor | 1.4331 | 1.3202 |
| max drawdown % | 36.15 | 45.61 |
| cash-credited alpha % | 7.06 | 3.02 |
| net profit (INR) | 3,582,675 | 2,190,428 |
| T1 adjusted p, 2 / 3-month blocks | 0.0461 / 0.0499 (from the recorded run 1 family row; `results_run1` holds no family file) | 0.4236 / 0.4270 |
| conclusion | as recorded | NOT DEMONSTRATED |

Caveats for reading the table: (1) the rows "exits on a BE/BZ bar" and "held through a BE/BZ spell" are computed by the comparison script from the lake table for BOTH runs; for run 1, which never saw BE/BZ bars, they only show where its trade dates coincide with BE/BZ rows. (2) The two runs differ in more than the stale exits: with the switch on, the 18 stale exits of run 1 become 2 and the rest of the path diverges (13 more trades, a different capital path), so the metric changes cannot be attributed trade by trade; the comparison decides nothing (pre-registration section 6).

## Trades that held a stock through a BE/BZ spell (16; all exited by STOP_HIT; all series BE)
| symbol | entry | exit | non-EQ sessions | first BE/BZ bar |
|---|---|---|---|---|
| IIFL | 2017-09-26 | 2017-10-30 | 9 | 2017-10-17 |
| BOMDYEING | 2018-06-20 | 2018-07-06 | 3 | 2018-07-04 |
| ADANIGREEN | 2021-05-06 | 2021-06-10 | 2 | 2021-06-09 |
| NEULANDLAB | 2021-05-17 | 2021-06-18 | 8 | 2021-06-09 |
| MAGMA | 2021-03-25 | 2021-06-21 | 9 | 2021-06-09 |
| CGPOWER | 2021-06-02 | 2021-07-12 | 24 | 2021-06-09 |
| TRIDENT | 2022-01-19 | 2022-02-11 | 15 | 2022-01-21 |
| PCJEWELLER | 2022-08-30 | 2022-09-28 | 12 | 2022-09-13 |
| JBMA | 2023-08-14 | 2023-09-25 | 17 | 2023-08-31 |
| PRAKASH | 2023-10-17 | 2023-10-25 | 3 | 2023-10-20 |
| NEWGEN | 2023-10-26 | 2024-01-20 | 56 | 2023-11-02 |
| SHAILY | 2024-12-16 | 2025-01-27 | 20 | 2024-12-31 |
| E2E | 2026-02-01 | 2026-02-24 | 1 | 2026-02-24 |
| BLISSGVS | 2026-06-29 | 2026-07-20 | 12 | 2026-07-03 |
| DIACABS | 2026-03-17 | 2026-09-03 | 23 | 2026-08-04 |
| HFCL | 2026-08-03 | 2026-09-03 | 1 | 2026-09-03 |

Every one of these stops fired on a BE bar and sold in full at once: **no sell was ever capped** (SELL_CAPPED_NON_EQ = 0), so the 10%-of-volume cap and the lock rule never bound in this run; the doubled exit slippage and the held-bar marks were the only active parts of the sell model.

## Baseline (B1) and other outputs
20,736 draws for 1,059 usable trades, 1,057 pairs kept (2 dropped, 0.19%, no flag); pool exclusions: 355,918 checked, 337,271 kept, 8,701 held, 9,946 in cooldown; unfilled draws: GAP_UP_TOO_LARGE 309, CORP_ACTION_ON_EXEC_DATE 110, SIZE_ZERO 10, NO_BAR_OR_ALREADY_HELD 7, NO_STOP 4, GAP_THROUGH_STOP 4; 18 stale-exit draws. Sub-periods (descriptive): 2016-2019 expectancy 0.124 R, alpha -6.4%; 2020-2026 expectancy 0.172 R, alpha +8.9%. Mean invested share 0.80, entries 8.15 a month (registered estimate 8.1).

## db_check (control)
| Check | Result |
|---|---|
| Run manifest (`run/manifest.json`) | `asof_view` memory; `non_eq_view` present (STOCKBOT_NON_EQ=held, table `market_data_non_eq`, cap 0.1, slippage multiplier 2.0); `non_eq_events` present; `db_check.unchanged` true, sha256 before = after |
| Baseline meta | `finsight_db.unchanged` true (sha256 before = after) |
| Benchmark, gates, validate_family, comparison | short steps: "database check: unchanged", counter 0 |
| File sha256 before the run / after the last step | `72885644a16599a42253afa3110ab900d9c32b378a8d736b9b4498427912465e` / identical (`sha_before.txt`, `sha_after.txt`) |
| `guard status --json` before vs after | byte-identical (`guard_before.json`, `guard_after.json`); correction counter 0 before and after, window closed, market_data_lake and market_data_non_eq sealed through 2026-11-18 |

## Timings (seconds)
Research 4,799 (80 min); baseline 3,688 (61 min); benchmark 25; gates 28; validate_family 64; comparison under 1. Memory view, one job at a time.

## Ledger: command for the owner (NOT executed here; no ledger row was written)
On master, from the repository root, after this branch is merged (the commit SHA is that of the merge or of `6261b80`, the results commit):
```
py -3 -c "
import json, pathlib
from stockbot.validation.ledger import record_family_results
res = json.loads(pathlib.Path('docs/strategies/riskadj_momentum_daily/results_run2_noneq/family_results.json').read_text())
record_family_results(path=pathlib.Path('stockbot/validation/ledger/records/family_ledger.csv'), family_id='family_batch5',
                      results={'riskadj_momentum_daily': res}, git_sha='<COMMIT SHA>')"
```
(`reason` is optional for the first results row; the family has one registered member, so `results` must contain exactly `riskadj_momentum_daily`.)

## What ran and what did not
Ran, each once: merge check and ledger verification (hash chain ok, `family_budget("family_batch5") == 1`, spec hash `5b06f092...446e19` equal), pre-run hash and guard status, plan, research run, B1 baseline, B2 benchmark, gates, `validate_family --expect-k 1` (B = 10,000, blocks 2 and 3, seed 20261111), the comparison, post-run hash and guard status. Did not run: any second run, any tuning, any change of code or config, any ledger write, any merge to master. The run log, step logs and time files are in the results folder. Not examined: why the drawdown rose from 36% to 46% (no analysis was asked for; the comparison above is descriptive only).
