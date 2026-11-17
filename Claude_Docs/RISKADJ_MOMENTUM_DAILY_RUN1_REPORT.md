# riskadj_momentum_daily: registered run 1 (family_batch4, K = 1)

Registered on master 6f25689 (ledger row_hash f6c6c6e792274e3d7ef01ef734275abef96900d33bd24035cd7dc8a69ee48a2d). Run ONCE, in the order of RUN_COMMANDS.md, with no parameter, code or config change, no re-run and no variant. Branch `riskadj_momentum_daily`. Facts only; nothing below is a recommendation.

## 1. Pre-checks
| Check | Result |
|---|---|
| Tree | clean; `git merge --ff-only origin/master` reached 6f25689 |
| Ledger (read-only) | `family_batch4` FAMILY_REGISTRATION present, K = 1, gates hash e9b6407f…8054, config hash of riskadj_momentum_daily 5b06f092…1e19 |
| Plan | spec hash 5b06f092df061bff1532093d21ea21c88c3f2db64ddd66e0cbe81bd5c0446e19; window 2016-01-01 to 2026-10-16; asof_view memory; exit policy `rmd_trailing_atr3_floor8`; `reentry_cooldown_sessions` 21 |
| Manifest | overlays none (`overlays: []`); symbol links enabled (41 linked pairs, file sha256 9d953ad4…84c7); stale exit 20 sessions; git_sha 6f25689e…; shared_config_hash da459624…6248; seed null |
| finsight.db sha256 | dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752 before and after (also `unchanged: true` in baseline_meta.json) |

## 2. Timings and restarts
| Step | Wall-clock | Exit code |
|---|---|---|
| research (--execute) | 5,417 s (19:35:40 to 21:05:59) | 0 |
| baseline | 4,229 s | 0 |
| benchmark | 28 s | 0 |
| gates | 26 s | 0 |
| validate_family | 64 s | 0 |

Restarts: none. Peak memory: NOT measured. The timing wrapper recorded the `py` launcher process (8.8 MB), not the python child, so its peak-memory field is meaningless; an interactive look during the baseline showed one python process of about 520 MB. (A background waiting loop of mine was stopped by Claude Code for low system memory; it was only a `sleep` loop and had no effect on the run.)

## 3. The run
| Item | Value |
|---|---|
| Sessions | 2,674 |
| Trades closed | 1,048 |
| Usable | 1,044 (4 excluded for corporate actions, `excluded_ca`) |
| END_OF_WINDOW_COUNTED (counted as usable) | 11 |
| SYMBOL_NO_BARS (stale exit) | 18 |
| Exit reasons (all closed) | STOP_HIT 1,019; SYMBOL_NO_BARS 18; END_OF_WINDOW_COUNTED 11 |
| Entries per month | 8.03 (gates script: entries over the window's months); 8.73 mean over the 120 months from first to last entry, median 8, min 0, max 32 |
| Invested share | mean 0.8030; p5 0.0; p95 0.99999 |
| Open positions | mean 10.55, max 12 |
| Holding time, sessions (usable) | median 21, p25 11, p75 35, max 246, mean 26.9 |
| Holding time, calendar days | median 31, p25 17, p75 52, max 361 |

### Proposals blocked (`blocked.json`, name-sessions: 60,423)
| Stage | Reason | Name-sessions |
|---|---|---|
| risk | BLOCKED_BY_RISK (no detail stored) | 36,596 |
| risk | ALREADY_HELD | 19,700 |
| risk | BLOCKED_BY_RISK, sector cap (FINANCIALS 1,503; CONSUMER 939; IT 353; HEALTHCARE 337; INDUSTRIALS 335; ENERGY 185; AUTO 125; CHEMICALS 115; METALS 84; SERVICES 66) | 4,052 |
| fill | GAP_UP_TOO_LARGE | 34 |
| fill | SIZE_ZERO | 32 |
| fill | CORP_ACTION_ON_EXEC_DATE | 7 |
| fill | NO_BAR_OR_ALREADY_HELD | 2 |

### What the cooldown removed
The strategy skips a name in cooldown BEFORE the ranking, so those skips are not in `blocked.json` and **the number of names the cooldown actually removed from a top 25 is not stored**. Getting it needs a re-scoring of all 2,674 sessions (about 98 minutes, read-only lake), which I did not run. What the stored files give:
| Item | Value |
|---|---|
| Stop-outs that started a cooldown (STOP_HIT exits) | 1,019 |
| Name-sessions inside a cooldown (exit session and the 21 after it, cut at the window end) | 22,299 (an upper bound on removed names: it counts every cooldown day, qualifying or not) |
| Entries of the same symbol 1 to 21 sessions after a stop exit | 0 |
| Shortest gap from a stop exit to the next entry of that symbol | 23 sessions |
| Baseline pool exclusions (draw-pool symbols dropped, summed over 1,044 trades) | held 8,649; cooldown 9,755; own symbol 1,044; checked 350,996; kept 332,592 |

## 4. Gates (shared `validation_gates`, point estimates; interval = block bootstrap, B 10,000, 3-month blocks, seed 20261111)
| Gate | Registered | Observed | 95% interval | Met |
|---|---|---|---|---|
| min_trades | >= 40 | 1,044 | - | met |
| min_expectancy_r | >= 0.15 | 0.2079 | 0.068 to 0.372 | met |
| min_profit_factor | >= 1.3 | 1.4331 | 1.051 to 1.945 | met |
| max_drawdown_pct | <= 20.0 | 36.148 | one path, none | **not met** |
| min_alpha_pct (cash-credited, pre-tax, daily-share benchmark) | >= 0.0 | 7.0611 | -5.160 to 20.981 | met |

All gates met: False.

### Stale-exit stress line (18 SYMBOL_NO_BARS trades sold at 0.5 x last close; stress, not a gate)
Net P&L of the 18 as run: 701,745 INR. Stressed: trades 1,044 met; expectancy 0.1367 (-0.001 to 0.299) not met; profit factor 1.1814 (0.871 to 1.597) not met; max drawdown 59.95% not met; alpha 0.5364 (-16.512 to 20.894) met; total net P&L stressed -1,188,160 INR; all met False.

### Alpha, returns, costs
| Item | Value |
|---|---|
| Years | 10.79 |
| Strategy CAGR, raw (idle cash earns 0) | 15.171% |
| Strategy CAGR, cash credited (6.5% on idle cash, pre-tax) | 16.630% |
| Matched Nifty benchmark CAGR (daily share, the gate's) | 9.569% (constant-share variant 9.861%) |
| Raw alpha | 5.602 pp |
| Cash-credited alpha (gate) | 7.061 pp |
| After-tax alpha at 20% on the end gain (illustrative) | 6.519 pp |
| Implied annual return (96.76 trades a year x 0.2079 R x 1.0%) | 20.12% a year (non-gating) |
| Max drawdown | 36.148% (peak 2018-01-09, trough 2020-03-23) |
| Net P&L, usable trades | 3,628,771 INR on 1,000,000 initial equity |
| Total costs paid (usable trades) | 401,416 INR |
| Gross P&L, usable trades (sum) | 4,030,187 INR; costs are 9.96% of it |
| Gross profit of winning trades | 12,179,110 INR; costs are 3.30% of it |

### Sub-periods (descriptive, no pass or fail)
| Period | Trades | Expectancy R | Profit factor | Max drawdown | Invested share | Alpha |
|---|---|---|---|---|---|---|
| 2016-2019 | 312 | 0.1685 | 1.2986 | 29.08% | 0.705 | -2.14 pp |
| 2020-2026 | 732 | 0.2247 | 1.4610 | 29.40% | 0.860 | 12.70 pp |

## 5. Baseline (B1 matched random, 20 draws per trade, seed 20261111)
| Item | Value |
|---|---|
| Usable trades / pairs kept / pairs dropped | 1,044 / 1,043 / 1 (share dropped 0.096%) |
| Draws total | 20,479 (closed before the window end 20,303; END_OF_WINDOW 176; stale-exit draws 57) |
| Unfilled draws | GAP_UP_TOO_LARGE 270; CORP_ACTION_ON_EXEC_DATE 106; SIZE_ZERO 12; NO_BAR_OR_ALREADY_HELD 7; NO_STOP 5; GAP_THROUGH_STOP 1 |
| Pool exclusions | held 8,649; cooldown 9,755; own symbol 1,044 (checked 350,996, kept 332,592) |
| Flag | none |

## 6. Joint validation (`validate_family.py`, family of ONE, B 10,000, blocks 2 and 3, seed 20261111)
| Test | Result |
|---|---|
| T1, blocks 2 | observed mean 0.6840, t 1.700, adjusted p 0.0461, fwer_significant true |
| T1, blocks 3 | observed mean 0.6840, t 1.700, adjusted p 0.0499, fwer_significant true |
| T3 size check | size 0.05, se 0.00689, verdict "size ok" |
| Tool's stated conclusion | **NOT DEMONSTRATED (registered rule not met; this is not evidence of no edge)** |

(`validate_family.json` shows `end_of_window: 0` in its gate counts block; the 11 end-of-window trades are counted as usable there and the gates script reports 11. RUN_COMMANDS notes that this tool does not print the end-of-window counts.)

### T2 (secondary, reported only; 1,004 paired trades, trades with a blanked forward return left out)
| Window | Trades / entry dates | Paired net R diff (mean; median) | Trade t / clustered t | Skill p (one-sided) | Horizon 20 sessions: actual - random, perm p |
|---|---|---|---|---|---|
| 2016-2019 | 309 / 203 | 0.1409; -0.1685 | 1.97 / 1.80 | 0.0305 | 0.890 R, p 0.1818 (Not Sig) |
| 2020-2026 | 695 / 448 | 0.0487; -0.1981 | 0.76 / 0.75 | 0.2495 | 3.647, p 0.0364 (Suggestive) |
| Pooled | 1,004 / 651 | 0.0771; -0.1918 | 1.55 / 1.53 | 0.0510 | 2.799, p 0.0138 (Suggestive) |

Horizons 1, 5 and 10 sessions are all "Not Sig" in the three windows (pooled perm p 0.1842, 0.1002, 0.0616). Mean net R of actual trades in the pooled window 0.2018 against random 0.1247.

---

# DESCRIPTIVE ADDENDUM (not registered, changes no conclusion)
From stored files only (`scripts/addendum_riskadj_momentum_daily_run1.py`, output `results_run1_addendum.json`); no engine run, no new draws, no lake access.

### (a) Concentration (1,044 usable trades; 1,043 pairs)
| Measure | Top 5 | Top 10 | Top 20 | Mean, all | Mean without top 5 | Mean without top 10 |
|---|---|---|---|---|---|---|
| Net R (total 217.04) | 29.9% (64.93 R) | 42.9% (93.17 R) | 64.4% (139.83 R) | 0.2079 | 0.1464 | 0.1198 |
| Net P&L (total 3,628,771 INR) | 35.3% (1,279,448) | 54.2% (1,965,973) | 84.8% (3,076,767) | 3,476 INR | 2,261 INR | 1,608 INR |
| Paired difference (total 88.92 R) | 70.1% (62.32 R) | 99.2% (88.25 R) | 147.2% (130.94 R) | 0.0853 | 0.0256 | 0.0007 |

### (b) Five deepest drawdown episodes (daily equity)
| # | Peak | Trough | Recovery | Depth |
|---|---|---|---|---|
| 1 | 2018-01-09 | 2020-03-23 | 2020-09-15 | 36.15% |
| 2 | 2024-10-15 | 2026-03-23 | 2026-07-27 | 30.33% |
| 3 | 2022-01-20 | 2023-03-27 | 2023-09-11 | 27.64% |
| 4 | 2020-09-18 | 2020-11-02 | 2021-03-03 | 13.23% |
| 5 | 2024-02-06 | 2024-03-20 | 2024-07-09 | 12.71% |

2020-01-14 to 2020-03-23: equity 1,387,154 on 2020-01-14; lowest 1,095,698 on 2020-03-23; fall from 2020-01-14 to that low 21.01%; maximum drawdown inside the window from the window's own peak 28.33%; drawdown from the run's peak (2018-01-09) on 2020-03-23 36.15%.

### (c) Side by side with riskadj_momentum run 1 (monthly rule), same functions on both stored runs
| Measure | riskadj_momentum_daily | riskadj_momentum run 1 |
|---|---|---|
| Usable trades | 1,044 | 647 |
| Entries per month | 8.03 | 4.98 |
| Invested share (mean) | 0.803 | 0.604 |
| Median hold (sessions) | 21 | 20 |
| Win rate | 41.28% | 40.49% |
| Average win (R) | 1.380 | 1.435 |
| Average loss (R) | -0.616 | -0.622 |
| Expectancy (net R) | 0.2079 | 0.2109 |
| Profit factor | 1.4331 | 1.4504 |
| Strategy CAGR raw / cash-credited | 15.17% / 16.63% | 11.08% / 13.92% |
| Cash-credited alpha | 7.06 pp | 5.45 pp |
| Max drawdown | 36.15% | 34.32% |
| Total costs (INR) | 401,416 | 223,038 |
| Net P&L (INR) | 3,628,771 | 2,203,357 |

Correlation of monthly equity returns (129 common months, 2016-02 to 2026-10): 0.801.

### (d) Re-entries (usable trades; re-buy = an earlier trade of the same symbol in this run ended by STOP_HIT; gap in sessions from the latest such stop exit to the new entry)
| Class | Trades | Mean net R | Median net R | Share positive |
|---|---|---|---|---|
| Re-buy after a stop | 564 | 0.2545 | -0.2014 | 41.7% |
| First-time symbol | 479 | 0.1539 | -0.2112 | 40.9% |
| Earlier trade not a stop | 1 | -0.1899 | -0.1899 | - |

Gap of the 564 re-buys: min 23, p25 28, median 44, p75 134.5, max 2,287 sessions. By gap: 22-30 sessions 179 trades (mean 0.253 R); 31-60 sessions 165 (0.357); 61-120 sessions 67 (0.044); 121-250 sessions 37 (0.833); over 250 sessions 116 (0.048); none inside 0-21 sessions.

---
## Files
`docs/strategies/riskadj_momentum_daily/results_run1/` (run/, baseline/, benchmark.json, gates.json), `results_run1_{research,baseline,benchmark,gates,family}.log` and `.time.json` beside it, `results_run1_addendum.json`; copy of `validate_family.json` in `docs/strategies/family_batch4/results_run1/`; `scripts/addendum_riskadj_momentum_daily_run1.py`.
Largest result file: `run/blocked.json` 9.3 MB (all files under 20 MB).
DB hash at the end: dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752 (identical to the start).
