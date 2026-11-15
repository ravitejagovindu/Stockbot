# riskadj_momentum: registered run 1 (family_batch2, K = 1). Report, facts only

Branch `riskadj_momentum`. Registered on master 5ed2bd4 (ledger row_hash `adfea22c992cf4363a36a101b87732e737c68b1bb1751c61cf388b888de2c44f`). Run once. No parameter, code or config change, no variant, no re-run, no ledger edit, 0 restarts. The registered outputs are unchanged and the conclusion stands as the tool states it.

**Tool's stated conclusion: `NOT DEMONSTRATED (registered rule not met; this is not evidence of no edge)`.** T1 found the member at blocks 2 and 3; the gate `max_drawdown_pct` is not met.

## 1. Manifest
| item | value |
|---|---|
| git sha | 5ed2bd4d5bcc48e77a039f348379ec7b9f5802d8 |
| spec (config) hash | 72dbec2c3da600cfe6de049a64efd530171ef2f539075f53e57a05e972ef27dc |
| shared config hash | 816ee5cb71b0618ed5c2065efc6de39f0f4a59ccf51862ceb3928d3665732bb3 |
| gates hash (registered) | e9b6407f908ff102dd25d9bc3b21a78a52b24c0ea082bba2cd3bb08f81188054 |
| asof_view | memory (STOCKBOT_VIEW=memory), no overlays |
| window | 2016-01-01 to 2026-10-16 (2,674 sessions), initial equity 1,000,000 |
| data snapshot | finsight.db, 3,432,767,488 bytes, last session 2026-10-16 |
| exit policy | trailing_atr3_floor8 |

## 2. Trades
- Closed 650; usable 647 (3 flagged excluded_ca: WIPRO 2019-06-04, ANANDRATHI 2024-04-02, STAR 2024-12-03); of the usable, **10 END_OF_WINDOW_COUNTED** (637 closed before the window end).
- Exit reasons (650): STOP_HIT 640, END_OF_WINDOW_COUNTED 10.
- Entries per month 4.98 (115 of 130 months have entries; maximum 12 in a month). The registered `expected_trade_rate` is 1.9.
- Invested share (daily): mean 0.604, p5 0.0, p95 0.954. Open positions: mean 7.98, maximum 12.
- Holding time, sessions: median 20, p25 12, p75 34.75, maximum 2,117 (mean 32.8).

### Facts the pre-registration did not cover: positions held on bars that stop
- **PHILIPCARB**, entered 2018-04-03: the last bar in the lake is 2018-04-19 (a SPLIT 2:10 is logged in `corporate_actions_log` with ex-date 2018-04-19). The position stayed open to 2026-10-16 and was closed there at the last close (stale), reason END_OF_WINDOW_COUNTED: 2,117 sessions, net P&L +1,727 INR.
- **TATASTLBSL**, entered 2021-07-02: the last bar in the lake is 2021-08-05. Same treatment: 1,312 sessions, net P&L +17,906 INR.
- Two more END_OF_WINDOW_COUNTED positions have the same pattern at the end of the window (found by the scan in section 10, item 4): **BLISSGVS** (entered 2026-07-02, last bar 2026-07-02, 74 sessions without a bar, net P&L +505) and **HFCL** (entered 2026-08-04, last bar 2026-09-02, 30 sessions without a bar, net P&L +20,310).
- The 10 END_OF_WINDOW_COUNTED trades were not removed or adjusted anywhere in the registered outputs.

## 3. Gates (point estimate; 95% interval = circular block bootstrap, entry months, 3-month blocks, B = 10,000, seed 20261111)
| gate | registered | observed | 95% interval | met |
|---|---|---|---|---|
| min_trades | >= 40 | 647 | none | met |
| min_expectancy_r | >= 0.15 | 0.2109 | 0.0412 to 0.3976 | met |
| min_profit_factor | >= 1.3 | 1.4504 | 1.0062 to 2.0707 | met |
| max_drawdown_pct | <= 20.0 | 34.32 | none (one path) | **not met** |
| min_alpha_pct | >= 0.0 | 5.4538 | -3.6937 to 16.1350 | met |

all_met: false.

## 4. Alpha, return, drawdown, sub-periods
- Raw alpha 2.610 (strategy CAGR 11.077, benchmark CAGR 8.467). Cash-credited alpha (the gate) 5.454 (strategy CAGR 13.920). Constant-share variant: raw 1.863, cash-credited 4.707. After-tax at 20% (illustrative, never a gate input): 4.980.
- Implied annual return: 59.96 trades a year x 0.2109 R x 1% = 12.65%, beside the matched benchmark CAGR 8.47%.
- Maximum drawdown 34.32%.

| sub-period (descriptive) | trades | expectancy R | profit factor | max drawdown % | alpha | invested share |
|---|---|---|---|---|---|---|
| 2016-2019 | 200 | 0.2453 | 1.527 | 20.35 | 1.967 | 0.543 |
| 2020-2026 | 447 | 0.1956 | 1.430 | 31.33 | 7.462 | 0.640 |

## 5. Baseline (matched random, own draw loop)
- Pairs kept 647, dropped 0, no flag. Draws 12,720 (12,580 STOP_HIT, **140 END_OF_WINDOW**). 20 draws per trade, seed 20261111, stop close - max(3 x ATR14, 8%), policy trailing_atr3_floor8.
- Unfilled draws: GAP_UP_TOO_LARGE 137, CORP_ACTION_ON_EXEC_DATE 63, SIZE_ZERO 11, NO_STOP 4, NO_BAR_OR_ALREADY_HELD 3, GAP_THROUGH_STOP 2.
- Actual net R mean 0.2109; draw mean 0.0877; draw median hold 22 sessions.

## 6. T1 (family_batch2, K = 1, 130 monthly observations, Westfall-Young Max-T, B = 10,000, seed 20261111)
| block | observed mean | SE | t | adjusted p | significant |
|---|---|---|---|---|---|
| 2 | 0.6064 | 0.2996 | 2.0237 | 0.0082 | yes |
| 3 | 0.6064 | 0.2996 | 2.0237 | 0.0096 | yes |

Dual significance: yes (member found).

## 7. T2 (paired statistics, 627 paired trades, secondary)
| window | horizon (sessions) | paired difference | perm p | status |
|---|---|---|---|---|
| 2016-2019 (197) | 1 / 5 / 10 / 20 | -0.043 / 1.239 / 2.356 / 2.686 | 0.9626 / 0.1956 / 0.030 / 0.0374 | Not Sig / Not Sig / Suggestive / Suggestive |
| 2020-2026 (430) | 1 / 5 / 10 / 20 | -0.373 / 0.198 / 0.572 / 0.302 | 0.8094 / 0.927 / 0.7788 / 0.88 | Not Sig at all four |
| pooled (627) | 1 / 5 / 10 / 20 | -0.27 / 0.525 / 1.133 / 1.051 | 0.8056 / 0.6596 / 0.3062 / 0.3866 | Not Sig at all four |

Paired net R: 2016-2019 mean 0.2344 (skill p 0.038); 2020-2026 mean 0.0500 (skill p 0.214); pooled mean 0.1079 (clustered t 1.78, skill p 0.0355).

## 8. T3 (placebo size check)
Size 0.038 (SE 0.006; 38 rejections in 1,000 replications, B = 1,000); limits 0.025 to 0.075: **size ok**.

## 9. Timings, memory, restarts, database
| step | wall clock | peak memory |
|---|---|---|
| research (`--execute`) | 2,984.7 s (49.7 min) | **not captured** |
| baseline | 2,498.6 s (41.6 min) | about 987 MB (sampled) |
| benchmark | 24.0 s | about 481 MB (sampled) |
| gates | 24.0 s | about 436 MB (sampled) |
| validate_family | 58.0 s | about 986 MB (sampled) |

All five steps exited with code 0. Restarts: none. The `peak_working_set_mb` field (about 8.7 MB) in the five `results_run1_*.time.json` files is the Python launcher's peak, not the step's; it is not the step's memory. The step peaks above come from a separate process sampler (20-second samples, so a lower bound). The research peak was not sampled.

`finsight.db` sha256 before the run `dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752`; after the run and again after the addendum below, the same value (size 3,432,767,488, mtime unchanged). The `-wal` file is 0 bytes; the `-shm` file's mtime is today's.

Files: `docs/strategies/riskadj_momentum/results_run1/` (run/, baseline/, benchmark.json, gates.json), `results_run1_{research,baseline,benchmark,gates,family}.time.json`, `docs/strategies/family_batch2/results_run1/validate_family.json` (copy), `results_run1_addendum.json`, `scripts/addendum_riskadj_momentum_run1.py`.

---

# DESCRIPTIVE ADDENDUM (not registered, changes no conclusion)

Computed after the registered run from the stored result files of `results_run1/` with `scripts/addendum_riskadj_momentum_run1.py` (output `results_run1_addendum.json`). No engine run, no new random draw. The lake was read read-only for: the NIFTY closes (as the gates script does), the closes of the two named symbols (item 2), and item 4. Nothing here is a gate, a test or a conclusion; no rule, parameter or decision follows from it.

## A1. Concentration (647 usable trades; 647 pairs)
Each block ranks by its own quantity (highest first); share = sum of the top k / total of all.

| quantity | total | top 5 share | top 10 share | top 20 share | mean, all | mean without top 5 | mean without top 10 |
|---|---|---|---|---|---|---|---|
| net R | 136.48 R | 35.7% | 59.7% | 93.3% | 0.2109 | 0.1366 (642 trades) | 0.0864 (637 trades) |
| net P&L | 2,203,357 INR | 41.3% | 71.3% | 116.0% | 3,405 INR | 2,013 INR | 994 INR |
| paired difference (net R minus the mean of its draws) | 78.83 | 56.6% | 94.5% | 149.9% | 0.1218 | 0.0533 | 0.0069 |

Expectancy R without the top 5 trades: 0.1366; without the top 10: 0.0864. Mean paired difference without the top 5: 0.0533; without the top 10: 0.0069.

## A2. The two positions removed (PHILIPCARB 2018-04-03, TATASTLBSL 2021-07-02) and their baseline pairs
**Method.** Trades, expectancy, profit factor, intervals and T1: exact, from the stored trades and pairs minus those two (control: the same code on the unmodified stored files reproduces 0.21094, 1.45044, 34.3223 and 5.4538 exactly). Drawdown and alpha: the stored daily equity and cash minus an estimated path of the two positions (shares x close, forward-filled until the exit date, realised net P&L afterwards; PHILIPCARB closes before 2018-04-19 multiplied by 0.2, the logged split, because the engine marks on split-adjusted prices). The mark-to-market assumption was checked: on seven dates, engine (equity - cash) equals the sum over open positions of shares x lake close to within 1e-9 relative, including on dates while the two positions were stale. **This is a subtraction, not a re-simulation: slots and cash that the two positions held are not re-used for other trades.**

| gate | registered | observed (two removed) | 95% interval | met | registered run |
|---|---|---|---|---|---|
| min_trades | >= 40 | 645 | none | met | 647 |
| min_expectancy_r | >= 0.15 | 0.2102 | 0.0403 to 0.3966 | met | 0.2109 |
| min_profit_factor | >= 1.3 | 1.4464 | 1.0023 to 2.0644 | met | 1.4504 |
| max_drawdown_pct | <= 20.0 | 34.53 | none | not met | 34.32 |
| min_alpha_pct (cash-credited) | >= 0.0 | 6.1990 | -3.0733 to 16.9392 | met | 5.4538 |

Raw alpha with the two removed 2.803 (registered run 2.610). All gates met: false (same as the registered run). Mean open positions 6.70 (registered run 7.98); mean invested share 0.528 (0.604).

**T1 observed mean (same shared code, B = 10,000, seed 20261111):**
| input | pairs | block 2 mean / t / adjusted p | block 3 mean / t / adjusted p |
|---|---|---|---|
| registered | 647 | 0.6064 / 2.0237 / 0.0082 | 0.6064 / 2.0237 / 0.0096 |
| two positions and their pairs removed | 645 | 0.6003 / 2.0009 / 0.0090 | 0.6003 / 2.0009 / 0.0100 |

**Slot-sessions occupied** (sessions with entry <= date < exit, the gates' open-position convention): PHILIPCARB 2,117; TATASTLBSL 1,312; total 3,429 slot-sessions (a session where both were held counts twice; the two were held together from 2021-07-02).

**Signal-month proposals blocked while each was held** (from `run/blocked.json`):
- No blocked proposal in the whole run carries a position-count or slot reason. The reasons present in the run are `BLOCKED_BY_RISK` with a sector rule (sector exposure above 15%; rules FINANCIALS, CONSUMER, INDUSTRIALS, HEALTHCARE, IT, ENERGY, AUTO, CHEMICALS, METALS, SERVICES, REALTY), `ALREADY_HELD`, `GAP_UP_TOO_LARGE`, `SIZE_ZERO`, `CORP_ACTION_ON_EXEC_DATE`. So the number blocked "for lack of a slot" as a stated reason is **0**.
- All blocked proposals dated inside the hold: PHILIPCARB 2,003 (BLOCKED_BY_RISK 1,661, ALREADY_HELD 317, GAP_UP_TOO_LARGE 13, SIZE_ZERO 7, CORP_ACTION_ON_EXEC_DATE 5); TATASTLBSL 1,222 (BLOCKED_BY_RISK 1,036, ALREADY_HELD 177, GAP_UP_TOO_LARGE 6, CORP_ACTION_ON_EXEC_DATE 2, SIZE_ZERO 1). Both periods overlap, so the two counts include some of the same proposals. The sector rules named in the blocked rows of both holds are listed in the JSON (`stale_positions`).

## A3. Drawdown episodes (daily equity, peak to trough, recovery = first date equity is back at the peak value)
| # | peak date | trough date | recovery date | depth |
|---|---|---|---|---|
| 1 | 2024-02-08 | 2025-10-14 | not recovered by 2026-10-16 | 34.32% |
| 2 | 2018-08-31 | 2019-08-05 | 2020-09-07 | 21.94% |
| 3 | 2022-01-17 | 2023-03-28 | 2023-07-11 | 21.69% |
| 4 | 2018-01-11 | 2018-02-06 | 2018-04-25 | 13.75% |
| 5 | 2018-04-30 | 2018-07-06 | 2018-08-17 | 7.94% |

**Deepest episode (#1), peak 2024-02-08 to trough 2025-10-14:** 418 sessions; invested share mean 0.587 (min 0.116, max 1.000); **124 stop-outs** (all 124 exits in the period were STOP_HIT), net P&L of those stop-outs -791,378 INR; 125 entries in the period.

## A4. The lake
| symbol | bars | first bar | last bar | corporate_actions_log rows around the last bar |
|---|---|---|---|---|
| PHILIPCARB | 1,311 | 2013-01-01 | 2018-04-19 | 1 row in the log in total: 2018-04-19 SPLIT 2:10 (evidence tier WEAK; notes: feed_symbol=PCBL, face value 10 to 2). Nothing after the last bar. `securities_master` has no row for the symbol. The lake holds bars for the symbol **PCBL** from 2018-04-20 to 2026-10-16 (2,105 bars). |
| TATASTLBSL | 2,069 | 2013-01-01 | 2021-08-05 | 6 rows in the log in total, the last 2014-09-15 (DIVIDEND). None within 365 days of the last bar, none after it. `securities_master` has no row for the symbol. |

**Same pattern in other stored runs** (a position whose symbol has no bar for more than 20 sessions while held; sessions are NIFTY50_INDEX bar dates; "terminal" = no further bar until the exit date; "gap" = bars resume before the exit). Counts of flagged trades:

| stored run | trades | flagged | terminal | gap |
|---|---|---|---|---|
| near_52w_high 4B | 774 | 8 | 3 | 5 |
| family_batch1 run1: pullback_uptrend | 4,156 | 4 | 2 | 2 |
| family_batch1 run1: short_term_reversal | 4,288 | 9 | 3 | 6 |
| riskadj_momentum run1 (this run) | 650 | 13 | 4 | 9 |

Terminal cases (all closed END_OF_WINDOW at 2026-10-16; symbol, entry, last bar, sessions held, net P&L INR):
- near_52w_high 4B: GSKCONS 2020-03-27, 2020-04-15, 1,627, +4,206; HEXAWARE 2020-09-24, 2020-10-30, 1,504, +483; DIACABS 2026-07-30, 2026-08-03, 55, -6,922.
- pullback_uptrend: HDFC 2023-07-12, 2023-07-12, 811, -101; AMIORG 2025-04-23, 2025-04-24, 370, -260.
- short_term_reversal: KPIT 2019-02-20, 2019-02-25, 1,897, +897; SUPPETRO 2022-04-05, 2022-04-06, 1,125, -98; GUJGASLTD 2026-06-25, 2026-06-30, 79, -165.
- riskadj_momentum run1: PHILIPCARB, TATASTLBSL (above), BLISSGVS 2026-07-02, 2026-07-02, 75, +505; HFCL 2026-08-04, 2026-09-02, 52, +20,310.

Gap cases (bars resume): near_52w_high 4B: DHANI, ATGL, SUZLON, NACLIND, PFOCUS; pullback_uptrend: DISHTV, MAANALU; short_term_reversal: NDTV, TTML, RELINFRA (two trades), SUVEN, MAANALU; riskadj_momentum run1: BOMDYEING, DHANI, ATGL, ADANIGREEN, GPIL, CGPOWER, FLUOROCHEM, PCJEWELLER, E2E. Longest missing runs 44 to 144 sessions; the full list with dates is in the JSON (`stale_pattern_registered_runs`).

Other stored runs found on disk (market_switch study, five trade files), same scan: flagged trades 5, 8, 5, 1 and 8, of which terminal 2, 3, 2, 1 and 1 (ESSAROIL, EQUITAS, GSKCONS, DIACABS, HDFC, AMIORG, GUJGASLTD); full list in `stale_pattern_other_stored_runs`.
