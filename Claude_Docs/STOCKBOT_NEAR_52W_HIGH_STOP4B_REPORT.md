# near_52w_high: STOP 4B report (registered run, results as measured)

Date: 2026-11-11. Branch `near-52w-high`. The strategy's status is unchanged (`research`). Nothing was merged. Nothing was re-run: the backtest, B1, B2, T1/T2/T3 and the gates each ran once. All figures below are as measured; the only interpretation is the registered decision rule.

## 1. The registered conclusion (in the registered words)
**NOT DEMONSTRATED (registered rule not met; this is not evidence of no edge).**
The registered rule is: T1 significant at both block lengths AND every gate met on its point estimate (drawdown gate at 20.0). T1 was not significant at either block length (section 5), and four of the five gates were not met (section 7).

## 2. What was done, in order, with commits
1. **Verification before anything.** HEAD was `6abe8c5`, a descendant of `45db2e4da31de4ceee0a9b84195584dbe1225c84`; `git diff 45db2e4 HEAD` showed no change to `stockbot/`, `scripts/`, `tests/` or `PREREGISTRATION.md` (only the STOP 4A report and STATUS.md); the working tree had no change to those paths; `finsight.db` was sha256 `dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752`, mtime 2026-11-08 12:38:02.8926123 +0530, 3,432,767,488 bytes; the family ledger did not exist yet; at HEAD the spec hash was `359c8331091abf15f14cfaaf47f4fcf49f65835d876b6fb1ece56fa78287ab26` and the gates hash `805efac844810c62d6f5d74b706d7cfb0b042c5fbc3cf217add54116d783cd2f`.
2. **Registration, commit `7176d90`** (the ledger row on its own). `register_family(git_sha="45db2e4da31de4ceee0a9b84195584dbe1225c84")`: row type FAMILY_REGISTRATION, one member `near_52w_high` 1.0.0 with config hash `359c8331...`, budget 1, gates hash `805efac8...`, prev_hash GENESIS, **row_hash `aceb96b894c2bb22debc166190a809d804527dd66ff7154473c43d20635ad7c4`**. `verify_ledger` passed; `family_budget(...) == 1`.
3. **The backtest**, once, detached: `py scripts/research_near_52w_high.py --execute --out F:\Projects\Ravi\StockBot_runs\near_52w_high_4B\run`. It ran from 2026-11-11 13:19:55 to 17:18:58 +0530 (**3 h 59 min**), exited normally, empty stderr. No restart was needed. I opened no trade, equity or P&L figure until every registered step had finished.
4. **In order, each once:** B1 `baseline_matched_random_near_52w_high.py` (17:23:24 to about 19:15, **about 1 h 51 min**); B2 `benchmark_nifty_matched_near_52w_high.py` (20 s); `validate_near_52w_high.py` T1, T2, T3 (39 s); `evaluate_validation_gates_near_52w_high.py --t1` (3 s). All exit code 0, all stderr empty.
5. **Results row, commit `22d3f45`** (the ledger row on its own): FAMILY_RESULTS for `near_52w_high`, carrying the registered conclusion, the T1, T3 and gate outcomes, the manifest identity and the sha256 of every result file. prev_hash `aceb96b8...`, **row_hash `3d0c31d5c5ab5318f8386fa3cd13077e2e02e8cd83f5c51576417033ea16f4dc`**. `verify_ledger` passed again (2 rows, budget 1).
6. This report and the result files (commit below).
7. G1, G2 (full folder) and G3: section 10.

## 3. Identity of the run (manifest, `run/manifest.json`)
Shared-config hash `805c9963d0a37de3f28ef9d1d534884f3376e62f404480327f2c3fc6af0b8dd7` (same as before the run); spec hash `359c8331...` (same); exit policy `fixed_hold_40`; data snapshot `finsight.db` 3,432,767,488 bytes, mtime_ns 1794121682892612300, last session 2026-10-16; window 2016-01-01 to 2026-10-16; initial equity 1,000,000; seed none (the backtest takes none; B1, T1, T2, T3 used 20261111). The manifest's `git_sha` is `7176d90...` (HEAD when it ran; the registered commit is 45db2e4, unchanged in HEAD).

## 4. Trades, entries, occupancy, capital use, caps, concentration (as measured)
- **Trades:** 774 closed; **749 usable** (not END_OF_WINDOW, not excluded_ca); 12 END_OF_WINDOW closures; 13 trades flagged excluded_ca. Entries per month: 5.76 usable (5.95 all closed; the pre-registration expected 6.2). Per year (all closed / usable): 2016 84/84, 2017 81/79, 2018 74/73, 2019 80/79, 2020 73/69, 2021 62/59, 2022 71/71, 2023 62/60, 2024 64/63, 2025 69/68, 2026 (to 16 Oct) 54/44.
- **Exit reasons (usable 749):** TIME_EXIT 591, STOP_HIT 158. Win rate 53.1%. Net R per usable trade: mean 0.0983, median 0.0694, SD 0.947, 5th percentile -1.02, 95th 1.57, minimum -1.80, maximum 8.24.
- **Occupancy and capital use:** open positions mean 11.53, median 12, at 12 on **71.6%** of sessions, never above 12. Invested share of equity mean 73.8% (median 75.1%, 5th percentile 63.8%, 95th 80.8%).
- **Shared caps (blocked.json, candidate-sessions as recorded):** 60,252 blocks in total. **Sector-cap blocks 1,194** on 379 sessions (197 of them in the UNKNOWN sector). `BLOCKED_BY_RISK` with no detail (the book already full; `arbitrate` records it for every remaining proposal) 48,926 on 2,537 sessions; `ALREADY_HELD` 10,050; SIZE_ZERO 63; GAP_UP_TOO_LARGE 14; CORP_ACTION_ON_EXEC_DATE 5.
- **Concentration (usable):** 277 distinct symbols; largest INFY 1.87%; top 10 symbols 13.9%. Entries in the UNKNOWN sector 7.9% (41 symbols). Sector shares: FINANCIALS 14.6%, CONSUMER 10.0%, HEALTHCARE 8.4%, UNKNOWN 7.9%, ENERGY 7.9%, METALS 7.9%, INDUSTRIALS 7.6%, IT 7.3%, AUTO 6.8%, SERVICES 6.4%, CHEMICALS 5.9%, TELECOM 4.7%, REALTY 4.0%, TEXTILES 0.4%, DIVERSIFIED 0.3%.
- **Equity (marked at the close):** 1,000,000 to 1,805,025.55 (+80.5%, before the END_OF_WINDOW closures); net P&L of the usable trades 813,095.79; strategy CAGR 5.63% (B2). **Largest drawdown 30.05%**: peak 2018-08-28, trough 2020-05-18, regained the peak on 2021-06-02; the equity curve was more than 10% below its peak on 45.8% of sessions.

## 5. T1, T3, T2, intervals (registered statistics)
**T1** (130 monthly sums of paired differences, K = 1, B = 10,000, alpha 0.05, seed 20261111, one-sided mean > 0; 746 pairs):
| block | observed mean per month (R) | SE | t | unadjusted p | adjusted p | significant |
|---|---|---|---|---|---|---|
| 2 months | 0.0608 | 0.2225 | 0.273 | 0.4057 | 0.4057 | **no** |
| 3 months | 0.0608 | 0.2225 | 0.273 | 0.4119 | 0.4119 | **no** |
99% bootstrap intervals of the monthly mean: block 2 -0.555 to 0.714; block 3 -0.533 to 0.656. **Dual rule: not significant at both** ("T1 not significant at both block lengths").
**T3** (placebo on the B1 draws, 1,000 replications, B = 1,000): **size 0.054** (SE 0.0071, 54 rejections), limits 0.025 and 0.075: **label "size ok"**.
**95% block-bootstrap intervals (3-month blocks):** mean net R per trade 0.1006 (-0.0138 to 0.2176); mean paired difference per trade 0.0106 (-0.0739 to 0.0942).
**T2** (reported only; 735 pairs, because 11 had a forward return blanked by a split inside the 20-session horizon; seed 20261111). Forward returns in percent, actual mean / random mean / paired difference / clustered t / permutation p (Bonferroni limit 0.0125), pooled: T+1 0.797 / 0.498 / +0.299 / 0.67 / 0.510; T+5 1.243 / 0.882 / +0.361 / 0.74 / 0.462; T+10 1.334 / 1.084 / +0.250 / 0.46 / 0.664; T+20 1.824 / 1.479 / +0.345 / 0.57 / 0.580; all "Not Sig". Net-R expectancy pooled: actual 0.0956, random (trade-averaged) 0.0895, paired difference +0.0061, clustered t 0.187, one-sided skill p 0.4255. By sub-period (descriptive): 2016-2019 (308 pairs) paired net-R difference +0.0494 (clustered t 1.22, skill p 0.112); 2020-2026 (427 pairs) -0.0251 (clustered t -0.53, skill p 0.7055). Mean holding days: actual 35.8, random 34.9.

## 6. B1 and B2
- **B1:** 749 usable trades; 20 draws each; **746 pairs kept, 3 dropped (0.40%), no flag**; 14,630 draws filled; unfilled draws by reason: GAP_UP_TOO_LARGE 165, CORP_ACTION_ON_EXEC_DATE 81, OPEN_AT_END 53, SIZE_ZERO 34, GAP_THROUGH_STOP 14, NO_BAR_OR_ALREADY_HELD 3. Policy `fixed_hold_40`, seed 20261111. `finsight.db` unchanged before and after (the script hashed it).
- **B2 (Nifty matched to the invested share, 6.5% on the rest):** years 10.790; strategy CAGR 5.626%; **benchmark CAGR 10.417% (daily share), alpha -4.791 points**; with the run's mean share held constant (73.8%): benchmark 9.661%, alpha -4.035 points. Tax 0.0.

## 7. The gates table (each gate beside its value; point estimates)
| gate | registered value | observed | 95% interval | met |
|---|---|---|---|---|
| min_trades | >= 40 | 749 | - | **YES** |
| min_expectancy_r | >= 0.15 | 0.0983 | -0.017 to 0.215 | **NO** |
| min_profit_factor | >= 1.3 | 1.2579 | 0.908 to 1.747 | **NO** |
| max_drawdown_pct | <= 20.0 | 30.0479 | - | **NO** |
| min_alpha_after_tax_pct | >= -2.0 | -4.7913 | -10.450 to 1.399 | **NO** |
All gates met on their point estimates: **False**. Gate values were read from the shared config at run time (20.0 is the changed drawdown gate).

## 8. Descriptive sub-periods (values only; no pass or fail; used for nothing)
| period | usable trades | expectancy R | profit factor | max drawdown % | alpha points | mean invested share | T1 (block 2 / block 3 adjusted p) |
|---|---|---|---|---|---|---|---|
| 2016-01-01 to 2019-12-31 | 315 | 0.0510 | 1.127 | 23.19 | -9.14 | 76.2% | 0.2409 / 0.2432 (48 months) |
| 2020-01-01 to 2026-10-16 | 434 | 0.1326 | 1.317 | 22.08 | -2.10 | 72.4% | 0.5649 / 0.5747 (82 months) |

## 9. Observed dispersion and dependence next to the power assumptions (post-decision, descriptive, not a decision input)
Computed after the conclusion above, by `docs/strategies/near_52w_high/observed_4B.py` (not registered code; it reads only the run and baseline files). The pre-registration said these replace the assumptions only after the registered decision.
| quantity | assumed in PREREGISTRATION.md section 9 | observed |
|---|---|---|
| SD of the paired per-trade net-R difference (sd_pair) | 0.9, 1.2 (central), 1.5 | 0.913 |
| design effect of overlapping trades (DEFF) | 1 to 3 (central 2) | 1.33 (variance of the 130 monthly sums over its independent-trade value) |
| effective trades | 262 to 786 (central 393) | 560 (of 746 pairs) |
| lag 1, 2, 3 autocorrelation of the monthly sums | not assumed | 0.136, 0.092, -0.098 |
| smallest edge detected at 80% power, ideal test / dual-rule c | 0.151 / 0.184 (central) | 0.096 / 0.117 |
| power at 0.15 R, ideal / dual | 0.80 / 0.61 (central) | 0.99 / 0.95 |
| power at 0.20 R, ideal / dual | 0.95 / 0.87 (central) | 1.00 / 1.00 |
A check from the monthly series itself (SE of the 130 monthly sums 0.2225, 5.74 paired trades a month) gives 0.096 and 0.118 R per trade at 80% power. These use the same normal-approximation formula as the pre-registration; the dependence enters the registered test only through the block bootstrap, so they are approximate. Observed trade rate 5.76 a month against the expected 6.2 (-7%); observed mean invested share 73.8% against the 78% used in the capital model; observed UNKNOWN-sector entries 7.9% against 13% in the STOP 2 model.

## 10. Tests and database
| check | before STOP 4B (at 45db2e4) | after the run |
|---|---|---|
| G1 `tests/unit tests/integration` | 856 passed, 8 skipped | **856 passed, 8 skipped** (539 s) |
| G3 `test_g3_fixture_baseline.py` | 2 passed | **2 passed** |
| full folder, `STOCKBOT_DATA_TESTS=1 STOCKBOT_FINAL_CHECK=1 pytest tests` | 985 passed | **985 passed, 0 failed, 0 skipped** (2635 s; not killed, not timed out) |
`finsight.db` sha256 / mtime / size: before STOP 4B `dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752` / 2026-11-08 12:38:02.8926123 +0530 / 3,432,767,488; after the backtest, B1 (it hashed before and after) and the last G run: identical (re-read after the last run): `dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752` / 2026-11-08 12:38:02.8926123 +0530 / 3,432,767,488 bytes.

## 11. Deviations, limitations and notes
1. **Progress by session count was not logged.** `scripts/research_near_52w_high.py` (registered content) has no progress output and I did not edit it. I logged only that the process was alive and elapsed time (heartbeat), and opened no figure until the end.
2. **The results row's commit_sha is the registered commit** (45db2e4), not HEAD; the manifest records HEAD (`7176d90`) because the ledger row was committed before the run. Registered content is identical in both (checked with `git diff`).
3. **observed_4B.py is not registered code.** It was written and run after the registered conclusion, for sections 4 and 9 (figures the registered scripts do not print). It is committed with its output for reproducibility.
4. **Result files.** The run files are in `F:\Projects\Ravi\StockBot_runs\near_52w_high_4B\` (outside the repository). Small ones (manifest, trades, equity curve, daily, validation and gates results, B1 meta, B2, the baseline's actual trades, observed figures, logs) are copied to `docs/strategies/near_52w_high/results_4B/`; `blocked.json` (8.7 MB) and `baseline_draws.csv` (3.4 MB) stay outside and are identified by sha256 in the FAMILY_RESULTS ledger row.
5. **Limitations carried from the pre-registration (unchanged):** no historical ASM/GSM exclusion; the UNKNOWN sector bucket; corporate actions the engine does not adjust inside the window (13 trades were flagged excluded_ca and left out of the statistics); EQ-only lake gaps; the cap-bound trade count; price-only returns on both sides; the random baseline has no portfolio effects; T2 uses raw closes (11 pairs left out for a split inside the horizon).
6. **Not decided here:** the strategy's status stays `research`. No rule or parameter was changed; no rerun was made.

## 12. Decisions needed from the owner and reviewer
The registered decision rule has produced its conclusion; it does not ask for a decision. For information: the owner and reviewer decide whether to merge this branch (documents, scripts, ledger rows, results) and what, if anything, follows; any new run or change to the strategy is a new trial under the pre-registration and needs a new approval. I have not merged anything.
