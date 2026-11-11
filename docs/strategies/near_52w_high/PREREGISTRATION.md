# near_52w_high: pre-registration (DRAFT. NOT REGISTERED. Nothing here is decided until the owner and reviewer approve it.)

Drafted 2026-11-11 at STOP 3. Every number marked **PROPOSED** is a proposal for the owner and reviewer to accept, change or reject; nothing marked PROPOSED has been decided. No return, P&L, win rate or forward price change of this strategy has been computed or looked at. The only measurements so far are counts (STOP 1, STOP 2) and run times.

## 1. What is registered
One strategy, one configuration, one backtest run, one decision. No parameter sweep, no variants, no second run unless a bug is found (then it is a new trial and needs a new approval).

## 2. The rule and parameters (exactly the spec)
`stockbot/strategies/near_52w_high/strategy.py`, `SPEC` at the commit that is registered:
- id `near_52w_high`, version `1.0.0`, status `research`, exit_policy `fixed_hold_40`, universe_overrides `{}`, overlays `{}`, expected_trade_rate 6.2 per month, smallest_edge_of_interest 0.15 R (see section 9: not supported by the power numbers), validation_ref empty.
- params `{"window": 252, "min_bars": 250, "threshold": 0.95, "top_n": 25, "stop_fraction": 0.85, "tie_adtv_sessions": 20}`.
- Universe: shared `universe.eligibility`, no overrides (ADTV above Rs25 crore on raw 20-session ADTV, listing age 252 trading days, and the other shared rules).
- Nearness = adjusted close today divided by the highest adjusted close of the symbol's last 252 bars (point-in-time, `AsOfView.adjusted_bars`). Candidate: nearness >= 0.95. Gap guard: at least 250 bars inside the last 252 Nifty sessions, 252 own bars, a bar on the signal date.
- Order: nearness descending; ties by higher raw 20-session ADTV; then symbol. The first 25 are proposed with an explicit ordinal rank (25 down to 1).
- Entry: the engine's next-open fill. Stop: 0.85 x the signal-day adjusted close (as-of basis). Exit: `fixed_hold_40` (the entry session is session 1, a market exit at the open of session 41, 40 closes held) or the stop, whichever is first. Long only; no regime filter; no target.
- Spec hash at the current commit: `e157b0bb2bc0c7ca4853c4756473bc46be74b17bee85194a78eec40319ebd245`. **The hash covers every spec field, `prereg_ref` included.** If `prereg_ref` is set to this file's path in the registration commit (PROPOSED), the registered hash becomes `359c8331091abf15f14cfaaf47f4fcf49f65835d876b6fb1ece56fa78287ab26` (computed for the path `docs/strategies/near_52w_high/PREREGISTRATION.md`; it is recomputed at registration). The run must use the same spec as the registered one.

## 3. Window and descriptive sub-periods
- **Registered run:** 2016-01-01 to 2026-10-16 (window A), one run. `shared.yaml` `backtest.regimes` labels (TEST and TUNE) do not apply to this strategy: nothing is tuned and there is one registered run (owner decision, 2026-11-11).
- **Two DESCRIPTIVE sub-period reports:** 2016-01-01 to 2019-12-31 and 2020-01-01 to 2026-10-16 (trades assigned by entry date). They repeat the statistics of section 8 and are reported, but are **never used to select, change or stop anything**, carry no pass or fail, and are not part of any multiplicity count.

## 4. Execution, cost and risk settings in force (quoted from `stockbot/config/shared.yaml`, shared, not overridable)
entry_fill NEXT_OPEN; entry_slippage_pct 0.10; exit_slippage_pct 0.10; max_entry_gap_up_pct 3.0. Costs: stt_buy_pct 0.10, stt_sell_pct 0.10, brokerage_per_order_inr 0.0, exchange_txn_pct 0.00297, sebi_fee_pct 0.0001, stamp_duty_buy_pct 0.015, gst_pct 18.0, dp_charge_per_sell_inr 15.34, stcg_tax_pct 0.0. Portfolio: max_loss_pct_per_trade 1.0, max_concurrent_positions 12, max_total_portfolio_risk_pct 15.0, max_sector_exposure_pct 15.0. Backtest initial_equity 1,000,000. Universe: min_adtv_cr 25, min_listing_age_trading_days 252, min_market_cap_cr 5000 (PARKED, KI-001, not applied).
Shared-config hash and spec hash are recorded by the run manifest (`stockbot/backtest/manifest.py`).

## 5. Data snapshot
`finsight.db`, sha256 `dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752`, 3,432,767,488 bytes, mtime 2026-11-08 12:38:02.892612 +0530 (mtime_ns 1794121682892612300), last session 2026-10-16. Re-checked unchanged at every STOP. If the file differs at STOP 4 the run does not start and the owner decides. The manifest records file name, size, mtime and last session.

## 6. The run (STOP 4)
`py scripts/research_near_52w_high.py --execute --out <new directory>` with the defaults (window A), once. The manifest, `trades.json` and `equity_curve.json` are saved. Trades flagged `excluded_ca` (a corporate action the engine cannot rescale puts the position on HOLD) and `END_OF_WINDOW` closures are reported by count and excluded from expectancy, profit factor and the paired tests (PROPOSED).

## 7. Baselines (PROPOSED)
**B1. Matched-random entries, trade level.** `stockbot.validation.random_baseline.draw_matched_random` (no new code for the core): for every actual trade, on the same signal session, **m = 20 symbols** drawn at random (seed 20261111, `random.Random`) from the shared-eligible pool of that date excluding the actual trade's own symbol (no pool filter, no ASM ranges), each given the actual trade's relative stop distance applied to the draw's signal close (about 15%), and simulated with `simulate_ticket` and the library policy `FixedHold(40)`: the same next-open fill, slippage, gap rule, corporate-action rebasing, stepping, costs and exit as the strategy. A pair is kept only if at least 10 of its 20 draws filled (PROPOSED); unfilled draws and dropped pairs are counted and reported by reason, and if more than 5% of trades lose their pair the result is flagged. **Matching to the strategy's occupancy** holds by construction: every random draw has the same entry date as its actual trade, so the baseline has the strategy's own entry timing and, apart from stops, the same 40-session holding window. It does not run through the 12-slot, sector and cash caps (no portfolio effects); see the design note below.
**B2. Nifty benchmark matched to the invested share.** Daily: benchmark return = s(t-1) x Nifty (NIFTY50_INDEX close-to-close) + (1 - s(t-1)) x risk_free_pct / 252, where s is the strategy's own invested share of equity at the previous close, taken from the run (1 - cash_after / equity). The constant-share version (the run's mean invested share) is reported alongside. Price index and price returns on both sides (dividends are in neither); tax rate 0.0 (ltcg_tax_pct and stcg_tax_pct are 0), so after-tax equals pre-tax.
**Paired comparison.** Per trade: net R (R is `compute_trade_r` net of costs) of the actual trade minus the mean net R of its retained random draws.

### Design note: why trade-level and not full random portfolios
A random baseline that runs random entries through the whole engine (caps included) is one full backtest per replicate. One strategy run is 3.5 hours or more (STOP 2 measurement: shared eligibility about 3.7 s and scoring about 1.1 s median per session over 2,674 sessions is about 3.6 hours before the engine's own work, so 4 to 5 hours is a fair planning figure). Even 100 replicates would be 400 to 500 hours. The trade-level design needs one pass of simulated paths (estimate below). **What it gives up:** the random draws are not subject to the slot, sector and cash caps; there is no random equity curve, so no drawdown or monthly-return comparison with a random portfolio; the paired statistic is attributed by entry month, not by the month in which the return accrues (so overlapping holds make neighbouring months dependent, which the 3-month blocks are meant to absorb). **What it keeps:** identical entry dates, identical eligibility, identical exit rule and stop distance, identical costs and fills. **Optional (PROPOSED: not included):** 3 to 5 full-engine random-strategy replicates for drawdown and utilisation context only (12 to 25 hours), never an input to a test.

## 8. Tests (PROPOSED)
- **T1, primary.** Paired monthly series: for each entry month m (130 months, 2016-01 to 2026-10), D(m) = sum over trades entered in m of (actual net R minus mean random net R). One-sided test of mean D > 0 with `WestfallYoungMaxTBootstrap` (studentized, null-centred, circular blocks, K = 1, B = 10,000, alpha 0.05, seed 20261111) at **block lengths 2 and 3 months; significant at both** (the dual rule of the F9 pre-registration, in months). With K = 1 the Westfall-Young step-down is a single studentized block-bootstrap test; the family budget is 1.
- **T2, secondary, reported only.** `paired_statistics` (seed 20261111): forward-return horizons 1, 5, 10, 20, date-clustered bootstrap, sign-flip permutation p (Bonferroni alpha 0.0125), net-R expectancy comparison with a clustered t and a one-sided skill p.
- **T3, placebo size check (PROPOSED, new small script).** Because F9 found the monthly dual rule liberal (size 0.0625 to 0.063 against 0.05) and the strategy's holds overlap, the same T1 pipeline is applied to placebo data built from B1 itself: for each trade one random draw stands in for the actual trade and the mean of the other draws is its comparator; 1,000 replications (B = 1,000 each). The rejection rate is the empirical size on this strategy's own dependence structure, reported with its standard error. **If it is above 0.075 or below 0.025 (PROPOSED), T1 is labelled "size unreliable" and the owner and reviewer decide; no p-value is recalibrated by me.**
- **Confidence intervals:** 95% block-bootstrap (3-month blocks) intervals for the mean net R per trade, the mean paired difference and the annualised alpha.
- **Reported always:** trade count (closed, excluded), entries per month and per year, occupancy and invested share seen, sector-cap blocks, largest drawdown on the daily equity curve, profit factor, win rate, expectancy, the sub-period reports of section 3.
- **Gates evaluation.** No code evaluates `validation_gates` today. A clearly named new script (`scripts/evaluate_validation_gates_near_52w_high.py`, PROPOSED name, committed before registration with fixture-lake tests) computes each registered gate value from the run and reports it next to the gate number.

## 9. Power, effective sample and what the test can detect
Computed by `docs/strategies/near_52w_high/power_calc.py` (standard library; reads no data; run before drafting this text). These are **assumption-based**, not measurements. The F9 study (`docs/F9_POWER_RESULTS.md`) is the only measured evidence of this test's behaviour and it used random-entry portfolios at 2.6 trades a month over 81 months.

**Nominal and effective sample.** Nominal: about 786 closed trades in 2016 to 2026 (STOP 1 counts model, 6.17 a month; stops would add trades, the ignored blocks would remove some). Overlap: a trade is open for 40 sessions (about 1.9 months) and about 12 trades are open at once (mean 11.7, full on 85% of sessions), so a trade overlaps about two dozen others. Effective sample: in time, 130 monthly observations, or about 68 non-overlapping hold-length blocks (130 / 1.9), or 43 blocks of the 3-month length used in T1. In trades, the nominal 786 divided by a design effect DEFF of 1 to 3 is **about 260 to 790 effective trades; central 390 (DEFF 2)**. The design effect is an assumption (the paired differences of concurrent trades share sector and style moves that matching only partly removes); it is not measured and cannot be measured before STOP 4 without looking at returns.
**Method.** Normal approximation, one-sided alpha 0.05: SE = sd_pair / sqrt(n / DEFF); power = Phi(edge / SE - c); detectable edge at 80% power MDE = (c + 0.842) x SE. sd_pair (SD of one trade's net R minus its matched random mean) is assumed 0.9, 1.2 or 1.5 R (a 40-session move of 15% to 20% against a 15% stop gives a single-trade R SD of about 1.0 to 1.3; pairing removes part of it). c = 1.645 is the ideal one-sided test; c = 2.2 is the effective critical value fitted to the F9 table for the monthly dual-block rule.

| sd_pair | DEFF | effective trades | MDE at 80% power, ideal c | MDE, dual-rule c | power at 0.15 R (ideal / dual) | power at 0.20 R (ideal / dual) |
|---|---|---|---|---|---|---|
| 0.9 | 2.0 | 393 | 0.113 | 0.138 | 0.95 / 0.87 | 1.00 / 0.99 |
| **1.2** | **2.0** | **393** | **0.151** | **0.184** | **0.80 / 0.61** | **0.95 / 0.87** |
| 1.2 | 1.0 | 786 | 0.106 | 0.130 | 0.97 / 0.90 | 1.00 / 0.99 |
| 1.2 | 3.0 | 262 | 0.184 | 0.225 | 0.65 / 0.43 | 0.85 / 0.69 |
| 1.5 | 2.0 | 393 | 0.188 | 0.230 | 0.63 / 0.41 | 0.84 / 0.67 |
| 1.5 | 3.0 | 262 | 0.230 | 0.282 | 0.49 / 0.28 | 0.70 / 0.48 |

(the full 12-row grid is in `PREREGISTRATION_power_output.txt`). **Statement.** Under the central assumptions (sd_pair 1.2, DEFF 2) the registered rule detects **0.18 R at 80% power** (0.15 R if the test were ideal), and has **61% power at 0.15 R**. **0.15 R is therefore not reliably detectable**: it is detectable at 80% only in the favourable corner (an ideal test with sd_pair <= 1.2 and DEFF <= 1.5; the dual rule needs DEFF of about 1). In the unfavourable corner the detectable edge is 0.23 to 0.28 R. A cross-check that scales the F9 monthly result by the higher trade rate and longer window gives 0.13 R at 80% power, but it assumes F9's shorter holds and dependence and ignores F9's liberal size, so I treat it as the optimistic bound. Detecting 0.15 R at 80% power with sd_pair 1.2 needs about 790 **nominal** trades at DEFF 2 with an ideal test and about 1,180 with the dual rule (594 and 888 at DEFF 1.5; 1,187 and 1,776 at DEFF 3). At 74 trades a year that is 10.7 years in the ideal case and 16 years with the dual rule, so the 10.8-year window is just enough for an ideal test and about 5 years short for the dual rule. **A "not significant" result at this sample size is not evidence of no edge** (the same statement as KI-002).
**Consequence for smallest_edge_of_interest.** Per the owner's rule (0.15 R is confirmed only if the power numbers support it): **they do not support it robustly.** The honest alternatives are (a) keep 0.15 R as the economic threshold and register that the test has about 60% power there (central case), or (b) set the smallest edge of interest to 0.20 R (central power 87% with the dual rule). I do not choose; this is decision D2 in the STOP 3 report.

## 10. Gates: what exists today, whether it is testable at this trade count (KI-002), and the PROPOSED use
`validation_gates` (shared, cannot be overridden; hash `d70800991ed5e6550fe8a89c050e6b3f989ac99f2a2d6cfaa133761771ab9e64`):

| gate | value today | testable at about 790 trades? | PROPOSED use |
|---|---|---|---|
| min_trades | 40 | **Yes, as a count** (790 nominal against 40; KI-002 was written for 2.6 trades a month). It is a floor only: 40 trades have almost no power. | closed, non-excluded trades >= 40 |
| min_expectancy_r | 0.15 | **Only as a point estimate.** n is no longer the problem, but the bar is on the strategy's own absolute net R per trade, with SE about 0.05 to 0.08 R (sd_trade 1.3 assumed, DEFF 1 to 3); a 95% lower bound above 0.15 needs a true value of about 0.23 to 0.28 R. A true expectancy of 0 passes the point bar about 0.1% to 3% of the time. | point estimate >= 0.15, reported with its 95% interval |
| min_profit_factor | 1.3 | Point estimate only; no sampling distribution is defined for it in the repo. | reported with a block-bootstrap interval; point estimate >= 1.3 |
| max_drawdown_pct | 15.0 | **Computable, single path.** One observed number; there is no test and no interval for it. | observed largest drawdown on daily equity <= 15 |
| min_alpha_after_tax_pct | -2.0 | **Computable, not testable.** Annualised alpha against the B2 benchmark; its sampling error over 10.8 years is of the order of 4 percentage points on my assumptions (about 3.8% monthly paired SD, independent months), larger than the floor. | point estimate >= -2.0, reported with its interval |
| ltcg_tax_pct, risk_free_pct | 0.0, 6.5 | Inputs (tax rate and benchmark cash rate), not gates. | used in B2 and in the alpha |

`paper_criteria` (shared; evaluated later in the paper phase, not at STOP 4):

| criterion | value today | testable at this trade rate? |
|---|---|---|
| min_days | 90 | Yes (a calendar floor). At 6.2 trades a month it is about 18 trades, far below the next line. |
| min_closed_trades | 60 | Yes (a count). At 6.2 a month it takes about 9.7 months of paper trading, so this, not min_days, sets the length. |
| max_expectancy_gap_r | 0.25 | **Weak.** The SE of a 60-trade paper expectancy is about 0.2 R (sd 1.3, DEFF 1.5), so noise alone breaches a 0.25 R gap about one time in four. |
| max_win_rate_gap_pts | 12.0 | **Weak.** The SE of a 60-trade win rate is about 6 points (iid); the gap is about 1.9 SE. Overlap makes it worse. |
| min_profit_factor | 1.2 | Point estimate on 60 trades: very noisy. |
| max_drawdown_pct | 12.0 | Computable, single path. |
| max_skipped_ticket_rate | 0.40 | Yes (an operational count). |
Note: `stockbot/live/paper_report.py` reads `paper_criteria` from the old strategy config and the old paper tables (PRE_LIVE_LIST item 7); the paper phase is out of scope here.

**Decision rule, PROPOSED (not decided).** The single registered conclusion: T1 significant at both block lengths **and** every gate in the table above met on its point estimate. Anything else is reported as "not demonstrated", with the interval and the detectable edge, and **not** as evidence of no edge. T2, T3, the sub-periods and the diagnostics never change that conclusion. The numbers 0.075 and 0.025 (T3), 10 of 20 draws, 5% pair loss, m = 20 and the seeds are PROPOSED.

## 11. Limitations carried into this pre-registration
1. **No historical ASM/GSM exclusion** (KI-003): snapshots exist only from 2026-11-08, so the shared surveillance exclusion is not applied in 2016 to 2026; both the strategy and the baseline ignore it.
2. **UNKNOWN sector bucket.** A quarter of the symbols the strategy picks with the ADTV tie-break (75 of 302; a third under the first ordering) have no sector in `data/reference/sector_map.csv` and share one bucket that the 15% cap holds to two positions at a time (the same as live). In the tie-break occupancy model 13% of entries are in that bucket.
3. **Unadjusted corporate actions inside the window.** Demerger, merger, rights and OTHER actions are not adjusted by the engine; a median of about 13 valid names a session have one inside their 252-bar window, with no extra guard (owner decision). A price jump from such an action can create or hide a "new high". Positions hit by an action the engine cannot rescale go on HOLD and are excluded from the statistics.
4. **EQ-only lake gaps** (PRE_LIVE_LIST item 11): the gap guard drops about 4% to 6% of the eligible names in 2022 and 2024 to 2026; a name that moves out of EQ looks like an absence and a re-listing. The lake keeps 934 symbols whose last bar is before 2026-10-16 (delisted, renamed, merged, suspended or moved out of EQ); the cause for each was not examined here.
5. **Cap-bound trade count.** The model's 6.17 entries a month is set by 12 slots and a 40-session hold (about 74 a year), not by the signal; the count does not grow with a stronger signal, and the effective sample is smaller than the nominal one because the trades overlap.
6. Also: prices are not adjusted for dividends (the lake holds split and bonus adjustments only) on both sides of every comparison; the market-cap gate is parked (KI-001); the random baseline has no portfolio effects (section 7); the power figures are assumption-based; F9 measured the monthly dual rule's size as 0.0625 to 0.063 (liberal); the strategy and the STOP 1 study tool are two implementations of one rule tied together by a fixture test; the backtest is single-process and takes hours; entry skipped for a gap above 3% is shared behaviour.

## 12. What was looked at before this draft, and what was decided from it (for the record)
Counts only, never returns: the STOP 1 counts study (eligible, valid, candidate and proposed counts, occupancy and concentration models, data-quality counts, run time). Decisions taken after seeing it, on non-outcome grounds: the tie-break (nearness, then ADTV, then symbol) after the alphabetical skew of the first order showed in the entry counts; window A; expected_trade_rate 6.2; no extra guard for unadjusted actions; the UNKNOWN sector accepted. The fixture-lake backtests in the unit tests use synthetic data only. The rule's numbers (252, 250, 0.95, 25, 0.85, 40) were fixed in the task brief before any look and were not changed. PROPOSED: record the counts studies in the exploratory ledger (`record_exploratory`) for completeness (decision D5).

## 13. Registration (family route; nothing is run now)
Why the family route: it is the ledger path built for strategies (a member is anything with `id`, `version` and `config_hash()`); it fixes the budget, hash-chains the row, requires the results row to cover every registered member, and leaves the old CFG-01..06 trial ledger and its chain untouched. With one member the budget is 1 and no multiplicity correction is applied; that is honest because exactly one configuration is registered. The old trial ledger's `register` is tied to `pre_registered_configs.yaml` and the six CFG candidates, which belong to the rejected breakout family.
```python
import dataclasses
from stockbot.config.shared import load_shared_config
from stockbot.strategies.near_52w_high import SPEC          # the spec as committed in the registration commit
from stockbot.validation.ledger import FAMILY_LEDGER, register_family

cfg = load_shared_config()
register_family(path=FAMILY_LEDGER, family_id="near_52w_high", members=[SPEC],
                gate_params=dataclasses.asdict(cfg.validation_gates), git_sha="<PREREG_COMMIT_SHA>")
```
Then `stockbot.validation.prereg_lock.verify_ledger(FAMILY_LEDGER)` (raises if any row was altered, deleted or reordered) and `family_budget(FAMILY_LEDGER, "near_52w_high") == 1`. After the run: `record_family_results(path=FAMILY_LEDGER, family_id="near_52w_high", results={"near_52w_high": {...}}, git_sha=...)`. The row records the commit SHA, the member's id, version and config hash, the budget and the hash of the shared gates (`d70800...`); the window, tests and decision rule live in this file at that commit.
Order of operations at STOP 4 (PROPOSED): 1. owner approves this file in writing; 2. write and test (fixture lake only) the validation scripts, set `prereg_ref` in the spec, finalise this file (PROPOSED values become fixed values), commit; 3. that commit's SHA goes into `register_family`; 4. verify the chain; 5. run the backtest once with that spec; 6. baselines, tests, gates; 7. report.

## 14. Run-time plan (estimates; nothing was run)
Strategy backtest: 4 to 5 hours (at least 3.5). B1: eligibility is recomputed per actual trade by `draw_matched_random` (about 786 x 3.7 s, roughly 50 minutes) plus 15,720 simulated paths at an unmeasured 0.15 to 0.5 s each (0.7 to 2.2 hours): about 1.5 to 3 hours, and it can be split over processes. B2, T1, T2, T3, gates: minutes. Total wall time about 6 to 8 hours single-process, run detached with logs. Memory: the earlier long runs needed little RAM, but the 3.4 GB file reads are slow when the cache is cold (STOP 2 measured it 10 to 45 times slower).

## 15. Open decisions (also listed in the STOP 3 report)
D1 `prereg_ref` in the spec and the hash it changes; D2 the smallest edge of interest; D3 the primary statistic and the dual-block rule (T1) and the placebo thresholds; D4 baseline design and draws (B1, m = 20, trade-level) and the optional full-engine reference runs; D5 exploratory-ledger entry for the counts studies; D6 whether the TEST and TUNE labels' removal needs a recorded note; D7 the PROPOSED decision rule and every number marked PROPOSED.
