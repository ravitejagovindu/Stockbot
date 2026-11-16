# lowvol_uptrend: registered run 1 (family_batch3, K = 1)

Facts only. Registered on master 017b9e4 (ledger row_hash `b2b316be80b4290918f227e4182c70bfa8342e30818cf2f32d34e9969b76054c`). One run, no parameter, code or config change, no restart, no variants. Files: `docs/strategies/lowvol_uptrend/results_run1/` (run, baseline, benchmark.json, gates.json), logs and timing `docs/strategies/lowvol_uptrend/results_run1_*.log|json`, `validate_family.json` at `F:\Projects\Ravi\StockBot_runs\family_batch3\` (copy in `docs/strategies/family_batch3/results_run1/`).

## Tool's stated conclusion
`lowvol_uptrend: NOT DEMONSTRATED (registered rule not met; this is not evidence of no edge)`. T1 not significant at either block; gates met: min_trades, min_profit_factor; not met: min_expectancy_r, max_drawdown_pct, min_alpha_pct.

## Pre-checks
Worktree clean, fast-forwarded to 017b9e4. Plan: spec hash `52e7ee3ccc2e150d7e4b6b54266bb2c73a8788612691ece475bfa7d1bb0e9e68`, window 2016-01-01 to 2026-10-16, asof_view memory, exit policy `lv_trailing_atr3_floor8`, overlays none; symbol links true and stale exit 20 in shared.yaml. Ledger: family_batch3 FAMILY_REGISTRATION, K = 1, gates `e9b6407f…8054`.

## Manifest
git_sha `017b9e44c04831c4c44fe377e3550ead7606ae8e`; spec hash as above; shared_config_hash `da459624294741239ae85230317da357b5b141a62b81f897bfb3d0745e956248`; asof_view memory; window 2016-01-01 to 2026-10-16; initial equity 1,000,000; data snapshot finsight.db 3,432,767,488 bytes, last session 2026-10-16; symbol_links enabled, 41 pairs, file sha256 `9d953ad4…84c7`; stale_exit sessions 20, 2 trades, net P&L total 53,967.25 (GSKCONS 2020-04-03 to 2020-05-14, 6,523.21; JBCHEPHARM 2026-04-02 to 2026-08-13, 47,444.04); end_of_window 6 trades.

## Trades
- Sessions 2,674. Closed trades 413; usable 405; excluded_ca 8; END_OF_WINDOW_COUNTED 6; SYMBOL_NO_BARS 2; STOP_HIT 405 (the 405 includes none of the 6 or 2; 405 + 6 + 2 = 413).
- Entries per month: 3.12 (405 usable over 130 months; the gates' figure); 413 closed over 130 months is 3.18.
- Invested share: mean 0.734, p5 0.000, p95 1.000. Open positions: mean 6.94, max 12.
- Holding time, sessions entry to exit, all 413 closed trades: median 30, p25 15, p75 59, max 329. (T2, calendar days, pairs: pooled actual median 31, max 329.)
- Proposals blocked (2,558 over the run): BLOCKED_BY_RISK sector_CONSUMER 607; ALREADY_HELD 563; sector_FINANCIALS 305; sector_HEALTHCARE 284; sector_ENERGY 159; sector_AUTO 155; sector_IT 138; BLOCKED_BY_RISK (other rule) 123; SIZE_ZERO 92; sector_METALS 80; sector_CHEMICALS 29; sector_INDUSTRIALS 17; CORP_ACTION_ON_EXEC_DATE 3; sector_SERVICES 2; sector_TELECOM 1.

## Gates (point estimates, 95% circular block bootstrap, 3-month blocks)
| gate | registered | observed | 95% interval | met |
|---|---|---|---|---|
| min_trades | >= 40 | 405 | - | YES |
| min_expectancy_r | >= 0.15 | 0.1413 | -0.039 to 0.341 | NO |
| min_profit_factor | >= 1.3 | 1.3069 | 0.875 to 1.966 | YES |
| max_drawdown_pct | <= 20.0 | 25.9724 | - | NO |
| min_alpha_pct | >= 0.0 | -2.4336 | -7.446 to 2.836 | NO |

- Alpha: raw -4.2508 (strategy CAGR 6.1181, matched benchmark CAGR 10.3689); cash-credited, pre-tax (gate) -2.4336 (strategy CAGR 7.9354, benchmark 10.3689); after-tax illustrative at 20%: -2.1910. B2 constant-share variant: raw -3.5311, cash-credited -1.7139. Mean invested share 0.7343.
- Implied annual return: 37.54 trades/year x 0.1413 R x 1.0% = 5.30% a year; matched Nifty CAGR 10.37%.
- Sub-periods (descriptive): 2016-2019: 119 trades, expectancy 0.1470 R, profit factor 1.3306, max drawdown 13.10%, mean invested share 0.643, alpha -4.917. 2020-2026: 286 trades, expectancy 0.1389 R, profit factor 1.3003, max drawdown 24.77%, mean invested share 0.788, alpha -1.044.
- **Stale-exit stress line** (2 SYMBOL_NO_BARS exits at 0.5 x last close, reporting only): min_trades 405 YES; expectancy 0.1161 (-0.059 to 0.315) NO; profit factor 1.2162 (0.817 to 1.821) NO; max drawdown 29.1230 NO; alpha -3.4518 (-8.805 to 2.201) NO; all gates met: False.

## Baseline (B1)
20 draws per trade, seed 20261111, min filled 10. Usable trades 405; pairs kept 405; dropped 0 (share 0.0, no flag); draws 7,963; END_OF_WINDOW trades 6 and draws 142; draws closed before the window end 7,821; SYMBOL_NO_BARS draws 32. Unfilled: GAP_UP_TOO_LARGE 82, CORP_ACTION_ON_EXEC_DATE 40, SIZE_ZERO 10, NO_BAR_OR_ALREADY_HELD 3, NO_STOP 1, GAP_THROUGH_STOP 1. Excluded_ca 8.

## T1 (Westfall-Young Max-T, B = 10,000, seed 20261111)
| block (months) | observed mean D(m) | t | adjusted p | significant |
|---|---|---|---|---|
| 2 | 0.1654 | 0.8538 | 0.192 | no |
| 3 | 0.1654 | 0.8538 | 0.188 | no |
Found by T1: none.

## T2 (forward returns in %, secondary, reported only; 394 paired trades, 106 entry dates; others blanked)
| window | n trades | entry dates | h | actual mean | random mean | paired diff | trade t | clustered t | perm p | status |
|---|---|---|---|---|---|---|---|---|---|---|
| 2016-2019 | 117 | 34 | 1 | 10.193 | 0.418 | 9.776 | 1.20 | 1.36 | 0.1386 | Not Sig |
| | | | 5 | 11.192 | 0.734 | 10.458 | 1.21 | 1.37 | 0.1136 | Not Sig |
| | | | 10 | 11.131 | 0.661 | 10.470 | 1.21 | 1.39 | 0.1140 | Not Sig |
| | | | 20 | 11.444 | 1.494 | 9.951 | 1.11 | 1.22 | 0.2746 | Not Sig |
| 2020-2026 | 277 | 72 | 1 | 4.207 | 1.866 | 2.341 | 0.71 | 0.71 | 0.9526 | Not Sig |
| | | | 5 | 4.622 | 2.520 | 2.103 | 0.63 | 0.63 | 0.9758 | Not Sig |
| | | | 10 | 4.733 | 2.335 | 2.398 | 0.69 | 0.70 | 0.9340 | Not Sig |
| | | | 20 | 4.760 | 2.454 | 2.306 | 0.66 | 0.66 | 0.9186 | Not Sig |
| pooled | 394 | 106 | 1 | 5.985 | 1.436 | 4.549 | 1.36 | 1.44 | 0.2776 | Not Sig |
| | | | 5 | 6.573 | 1.989 | 4.584 | 1.32 | 1.41 | 0.3160 | Not Sig |
| | | | 10 | 6.633 | 1.838 | 4.795 | 1.36 | 1.42 | 0.2896 | Not Sig |
| | | | 20 | 6.745 | 2.169 | 4.576 | 1.26 | 1.34 | 0.3668 | Not Sig |

Net R expectancy (T2): pooled actual 0.1452 (median -0.2643, trimmed -0.0136); random trade-averaged 0.0833; paired difference mean 0.0619 (median -0.1869, trimmed -0.0411, clustered t 0.976, one-sided skill p 0.1805). 2016-2019: actual 0.1393, random 0.0125, paired 0.1267 (clustered t 1.268, p 0.108). 2020-2026: actual 0.1477, random 0.1132, paired 0.0345 (clustered t 0.433, p 0.3445).

## T3 placebo size check
Size 0.038 (se 0.0060; 38 rejections in 1,000 replications, B = 1,000), limits 0.025 to 0.075: "size ok".

## Timings (wrapper wall clock; peak working set of the process tree as sampled every 5 s, so approximate)
| step | wall clock | peak memory |
|---|---|---|
| research (--execute) | 5,497 s (91.6 min) | 984 MB |
| baseline | 1,791 s (29.8 min) | 988 MB |
| benchmark | 28 s | not measured |
| gates | 33 s | not measured |
| validate_family | 62 s | 988 MB |
| addendum (stored files) | under 1 min | not measured |
Restarts: none. Errors: none (stderr logs empty). `finsight.db` sha256 `dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752` before and after (also `unchanged: true` in the baseline meta).

---

# DESCRIPTIVE ADDENDUM (not registered, changes no conclusion)
Stored files only (`results_run1_addendum.json`, script `scripts/addendum_lowvol_uptrend_run1.py`); no engine run, no new draw; lake read-only for (d).

## (a) Concentration (405 usable trades, 405 pairs; ranked within each quantity)
| quantity | total | top 5 share | top 10 share | top 20 share | mean, all | mean without top 5 | mean without top 10 |
|---|---|---|---|---|---|---|---|
| net R | 57.23 | 60.05% | 95.26% | 150.33% | 0.1413 | 0.0572 | 0.0069 |
| net P&L (INR) | 671,136 | 70.22% | 113.03% | 180.03% | 1,657 | 500 | -221 |
| paired difference (R) | 21.51 | 143.63% | 230.44% | 352.03% | 0.0531 | -0.0235 | -0.0710 |

## (b) Five deepest drawdown episodes (daily equity)
| # | peak | trough | recovery | depth |
|---|---|---|---|---|
| 1 | 2021-10-18 | 2022-06-20 | 2023-11-30 | 25.97% |
| 2 | 2024-09-27 | 2026-10-08 | not recovered | 22.90% |
| 3 | 2018-08-28 | 2020-04-03 | 2020-07-24 | 15.49% |
| 4 | 2018-02-01 | 2018-03-07 | 2018-07-12 | 9.24% |
| 5 | 2021-01-11 | 2021-05-04 | 2021-07-01 | 8.14% |

## (c) Overlap with riskadj_momentum run 1
riskadj_momentum run 1 five deepest episodes (peak, trough, recovery, depth): R1 2024-02-08, 2025-10-14, not recovered, 34.32%; R2 2018-08-31, 2019-08-05, 2020-09-07, 21.94%; R3 2022-01-17, 2023-03-28, 2023-07-11, 21.69%; R4 2018-01-11, 2018-02-06, 2018-04-25, 13.75%; R5 2018-04-30, 2018-07-06, 2018-08-17, 7.94%.
Shared calendar months, peak month to trough month (peak month to recovery month in brackets; to the last month if not recovered):
- lowvol #1 (2021-10 peak): with R3: 2022-01 to 2022-06 (6 months) [2022-01 to 2023-07, 19 months]; no other.
- lowvol #2 (2024-09): with R1: 2024-09 to 2025-10 (14 months) [to 2026-10, 26 months]; no other.
- lowvol #3 (2018-08): with R2: 2018-08 to 2019-08 (13 months) [to 2020-07, 24 months]; with R5 only [2018-08, 1 month]; none to trough.
- lowvol #4 (2018-02): with R4: 2018-02 (1 month) [2018-02 to 2018-04, 3 months]; with R5 [2018-04 to 2018-07, 4 months].
- lowvol #5 (2021-01): none.
Correlation of the two runs' monthly equity returns (last equity of the month over the previous month's): Pearson 0.5834 over 129 common months (2016-02 to 2026-10).

## (d) Positions held on any session with no bar for more than 5 sessions (symbol and its linked names, Nifty calendar)
| symbol | entry | exit | exit reason | net P&L | longest run without a bar | held sessions with run over 5 | first such session |
|---|---|---|---|---|---|---|---|
| GSKCONS | 2020-04-03 | 2020-05-14 | SYMBOL_NO_BARS | 6,523.21 | 19 sessions | 14 | 2020-04-23 |
| JBCHEPHARM | 2026-04-02 | 2026-08-13 | SYMBOL_NO_BARS | 47,444.04 | 19 sessions | 14 | 2026-07-24 |
No other position had a run of more than 5 sessions without a bar while held.
