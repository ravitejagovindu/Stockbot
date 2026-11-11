# near_52w_high: pre-registration (FINAL TEXT, approved by the owner on 2026-11-11; registration happens at STOP 4B)

Written at STOP 3, finalised at STOP 4A (2026-11-11). **Approved by the owner on 2026-11-11** at the STOP 3 review, with the reviewer: the owner took decisions D1 to D7 and the drawdown-gate decision below, and the reviewer checks this final text against them before STOP 4B. Nothing in this file has been registered in any ledger yet. No return, P&L, win rate or forward price change of this strategy has been computed or looked at. The only measurements so far are counts (STOP 1, STOP 2), run times, and the power arithmetic of section 9.

## 0. Approval record (what was decided, and by whom)
Owner and reviewer, 2026-11-11, STOP 3 review:
- **D1** (owner): `prereg_ref` in the spec is `docs/strategies/near_52w_high/PREREGISTRATION.md`, set in the registration commit; the new spec hash is stated in section 2.
- **D2** (owner): smallest_edge_of_interest stays 0.15 R, with the plain statement of section 9.
- **D3** (owner): T1, T2 and T3 approved as written in section 8, with the T3 limits 0.075 and 0.025; "size unreliable" means the owner and reviewer decide and nobody recalibrates.
- **D4** (owner): B1 (20 draws per trade, minimum 10 filled, seed 20261111, same eligibility, same `fixed_hold_40` exit, same relative stop) and B2 (Nifty matched to the invested share, 6.5% on the rest) approved as written in section 7. No full-engine random replicates.
- **D5** (owner): the registration does not touch the exploratory ledger (it is pinned by a hash test). Section 12 is the record of the counts-only studies.
- **D6** (owner): keep the note that the TEST/TUNE labels in `shared.yaml` do not apply to this strategy (section 3).
- **D7** (owner): the STOP 4B run (6 to 8 hours) is approved, detached, with logs. A restart of the IDENTICAL registered run after a crash (same spec hash, same shared-config hash, same data snapshot, same seeds, and no results looked at) is not a new trial. Any other rerun is a new trial and needs a new approval.
- **Drawdown gate** (owner): the owner accepts a maximum drawdown of 20%. `validation_gates.max_drawdown_pct` was changed from 15.0 to 20.0 in `stockbot/config/shared.yaml` as a reviewed shared change, in its own commit, applying to every strategy. `paper_criteria.max_drawdown_pct` stays 12.0: **a strategy that passes 20% in backtest can still fail 12% in paper.**
- **Decision rule** (owner): as drafted: T1 significant at both block lengths **and** every gate met on its point estimate, with the drawdown gate at 20.0. Every number that the draft flagged as a proposal is fixed as written below.

## 1. What is registered
One strategy, one configuration, one backtest run, one decision. No parameter sweep, no variants, no second run unless a bug is found (then it is a new trial and needs a new approval).

## 2. The rule and parameters (exactly the spec)
`stockbot/strategies/near_52w_high/strategy.py`, `SPEC` at the registered commit:
- id `near_52w_high`, version `1.0.0`, status `research`, exit_policy `fixed_hold_40`, universe_overrides `{}`, overlays `{}`, expected_trade_rate 6.2 per month, smallest_edge_of_interest 0.15 R (net of costs), `prereg_ref` = `docs/strategies/near_52w_high/PREREGISTRATION.md`, validation_ref empty.
- params `{"window": 252, "min_bars": 250, "threshold": 0.95, "top_n": 25, "stop_fraction": 0.85, "tie_adtv_sessions": 20}`.
- Universe: shared `universe.eligibility`, no overrides (ADTV above Rs25 crore on raw 20-session ADTV, listing age 252 trading days, and the other shared rules).
- Nearness = adjusted close today divided by the highest adjusted close of the symbol's last 252 bars (point-in-time, `AsOfView.adjusted_bars`). Candidate: nearness >= 0.95. Gap guard: at least 250 bars inside the last 252 Nifty sessions, 252 own bars, a bar on the signal date.
- Order: nearness descending; ties by higher raw 20-session ADTV; then symbol. The first 25 are proposed with an explicit ordinal rank (25 down to 1).
- Entry: the engine's next-open fill. Stop: 0.85 x the signal-day adjusted close (as-of basis). Exit: `fixed_hold_40` (the entry session is session 1, a market exit at the open of session 41, 40 closes held) or the stop, whichever is first. Long only; no regime filter; no target.
- **Spec hash with `prereg_ref` set: `359c8331091abf15f14cfaaf47f4fcf49f65835d876b6fb1ece56fa78287ab26`** (the hash before `prereg_ref` was set was `e157b0bb2bc0c7ca4853c4756473bc46be74b17bee85194a78eec40319ebd245`). The hash covers every spec field. The registered hash is the new one, and the run must use the same spec.
- **Shared validation_gates hash after the drawdown change: `805efac844810c62d6f5d74b706d7cfb0b042c5fbc3cf217add54116d783cd2f`** (the old hash, with 15.0, was `d70800991ed5e6550fe8a89c050e6b3f989ac99f2a2d6cfaa133761771ab9e64`).

## 3. Window and descriptive sub-periods
- **Registered run:** 2016-01-01 to 2026-10-16 (window A), one run. The TEST/TUNE labels in `shared.yaml` (`backtest.regimes`) do not apply to this strategy: nothing is tuned and there is one registered run (owner decision).
- **Two DESCRIPTIVE sub-period reports:** 2016-01-01 to 2019-12-31 and 2020-01-01 to 2026-10-16 (trades assigned by entry date). They repeat the statistics of section 8 and are reported, but are **never used to select, change or stop anything**, carry no pass or fail, and are not part of any multiplicity count.

## 4. Execution, cost and risk settings in force (quoted from `stockbot/config/shared.yaml`, shared, not overridable)
entry_fill NEXT_OPEN; entry_slippage_pct 0.10; exit_slippage_pct 0.10; max_entry_gap_up_pct 3.0. Costs: stt_buy_pct 0.10, stt_sell_pct 0.10, brokerage_per_order_inr 0.0, exchange_txn_pct 0.00297, sebi_fee_pct 0.0001, stamp_duty_buy_pct 0.015, gst_pct 18.0, dp_charge_per_sell_inr 15.34, stcg_tax_pct 0.0. Portfolio: max_loss_pct_per_trade 1.0, max_concurrent_positions 12, max_total_portfolio_risk_pct 15.0, max_sector_exposure_pct 15.0. Backtest initial_equity 1,000,000. Universe: min_adtv_cr 25, min_listing_age_trading_days 252, min_market_cap_cr 5000 (PARKED, KI-001, not applied).
Shared-config hash and spec hash are recorded by the run manifest (`stockbot/backtest/manifest.py`).

## 5. Data snapshot
`finsight.db`, sha256 `dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752`, 3,432,767,488 bytes, mtime 2026-11-08 12:38:02.892612 +0530 (mtime_ns 1794121682892612300), last session 2026-10-16. Re-checked unchanged at every STOP. If the file differs at STOP 4B the run does not start and the owner decides. The manifest records file name, size, mtime and last session.

## 6. The run (STOP 4B)
`py scripts/research_near_52w_high.py --execute --out <new directory>` with the defaults (window A), once, detached with logs. It writes `manifest.json`, `trades.json`, `equity_curve.json`, `daily.json` (equity and cash at every close) and `blocked.json` (the shared caps' blocks). Trades flagged `excluded_ca` (a corporate action the engine cannot rescale puts the position on HOLD) and `END_OF_WINDOW` closures are reported by count and excluded from expectancy, profit factor and the paired tests.

## 7. Baselines (fixed)
**B1. Matched-random entries, trade level** (`scripts/baseline_matched_random_near_52w_high.py`, using `stockbot.validation.random_baseline.draw_matched_random` unchanged): for every usable trade, on the same signal session, **m = 20 symbols** drawn at random (seed 20261111, `random.Random`) from the shared-eligible pool of that date excluding the trade's own symbol (no pool filter, no ASM ranges), each given the actual trade's relative stop distance applied to the draw's signal close (about 15%), and simulated with `simulate_ticket` and the library policy `FixedHold(40)`: the same next-open fill, slippage, gap rule, corporate-action rebasing, stepping, costs and exit as the strategy. A pair is kept only if **at least 10** of its 20 draws filled; unfilled draws and dropped pairs are counted and reported by reason, and if more than 5% of trades lose their pair the result is flagged. **Matching to the strategy's occupancy** holds by construction: every random draw has the same entry date as its actual trade, so the baseline has the strategy's own entry timing and, apart from stops, the same 40-session holding window. It does not run through the 12-slot, sector and cash caps (no portfolio effects). Forward returns for T2 are read only up to 20 sessions after the entry and are blanked where a split or bonus falls inside that horizon.
**B2. Nifty matched to the invested share** (`scripts/benchmark_nifty_matched_near_52w_high.py`): daily benchmark return = s(t-1) x Nifty (NIFTY50_INDEX close-to-close) + (1 - s(t-1)) x risk_free_pct / 252 with risk_free_pct 6.5, where s is the strategy's own invested share of equity at the previous close from the run (1 - cash / equity). The constant-share version (the run's mean invested share) is reported alongside. Price index and price returns on both sides (dividends are in neither); the tax rate is the shared `ltcg_tax_pct` (0.0; `stcg_tax_pct` is also 0.0), so after-tax equals pre-tax. Alpha = strategy CAGR minus benchmark CAGR over the run, in percentage points.
**Paired comparison.** Per trade: net R (`compute_trade_r`, net of costs) of the actual trade minus the mean net R of its retained random draws.
**No full-engine random replicates** (owner decision D4).

### Design note: why trade-level and not full random portfolios
A random baseline that runs random entries through the whole engine (caps included) is one full backtest per replicate, 4 to 5 hours each (STOP 2: shared eligibility about 3.7 s and scoring about 1.1 s median per session over 2,674 sessions is about 3.6 hours before the engine's own work). 100 replicates would be 400 to 500 hours. **What the trade-level design gives up:** the random draws are not subject to the slot, sector and cash caps; there is no random equity curve, so no drawdown or monthly-return comparison with a random portfolio; the paired statistic is attributed by entry month, not by the month in which the return accrues (overlapping holds make neighbouring months dependent, which the 3-month blocks and the T3 check address). **What it keeps:** identical entry dates, identical eligibility, identical exit rule and stop distance, identical costs and fills.

## 8. Tests (fixed)
- **T1, primary** (`scripts/validate_near_52w_high.py`). Paired monthly series: for each entry month m (130 months, 2016-01 to 2026-10, empty months 0), D(m) = sum over trades entered in m of (actual net R minus mean random net R). One-sided test of mean D > 0 with `WestfallYoungMaxTBootstrap` (studentized, null-centred, circular blocks, K = 1, B = 10,000, alpha 0.05, seed 20261111) at **blocks 2 and 3 months; significant at both** (the dual rule of the F9 pre-registration, in months). With K = 1 the step-down is a single studentized block-bootstrap test; the family budget is 1.
- **T2, secondary, reported only.** `paired_statistics` (seed 20261111): forward-return horizons 1, 5, 10, 20, date-clustered bootstrap, sign-flip permutation p (Bonferroni alpha 0.0125), net-R expectancy comparison with a clustered t and a one-sided skill p. Never a decision input.
- **T3, placebo size check.** Because F9 found the monthly dual rule liberal (size 0.0625 to 0.063 against 0.05) and the strategy's holds overlap, the same T1 pipeline is applied to placebo data built from B1 itself: for each paired trade one random draw stands in for the actual trade and the mean of its other draws is its comparator; 1,000 replications (B = 1,000 each). The rejection rate is the empirical size on this strategy's own dependence structure, reported with its standard error. **If it is above 0.075 or below 0.025, T1 is labelled "size unreliable" and the owner and reviewer decide; nobody recalibrates a p-value.**
- **Confidence intervals:** 95% circular block-bootstrap (3-month blocks) intervals for the mean net R per trade, the mean paired difference per trade, the profit factor and the annualised alpha.
- **Reported always:** trade count (closed, usable, excluded, END_OF_WINDOW), entries per month and per year, occupancy and invested share seen, sector-cap blocks, largest drawdown on the daily equity curve, profit factor, win rate, expectancy, and the sub-period reports of section 3 (descriptive).
- **Gates evaluation** (`scripts/evaluate_validation_gates_near_52w_high.py`): computes every registered gate from the run and prints it beside the gate value read from the shared config; `--t1` adds the registered conclusion.

## 9. Power, effective sample and what the test can detect
Computed by `docs/strategies/near_52w_high/power_calc.py` (standard library; reads no data). These are **assumption-based**, not measurements. The F9 study (`docs/F9_POWER_RESULTS.md`) is the only measured evidence of this test's behaviour and it used random-entry portfolios at 2.6 trades a month over 81 months.

**Nominal and effective sample.** Nominal: about 786 closed trades in 2016 to 2026 (STOP 1 counts model, 6.17 a month; stops would add trades, the ignored blocks would remove some). A trade is open for 40 sessions (about 1.9 months) and about 12 are open at once (mean 11.7, full on 85% of sessions), so a trade overlaps about two dozen others. Effective sample: in time, 130 monthly observations, or about 68 non-overlapping hold-length blocks (130 / 1.9), or 43 blocks of the 3-month length used in T1. In trades, the nominal 786 divided by a design effect DEFF of 1 to 3 is **about 260 to 790 effective trades; central 390 (DEFF 2)**. The design effect is an assumption; it cannot be measured before the registered decision without looking at returns.
**Method.** Normal approximation, one-sided alpha 0.05: SE = sd_pair / sqrt(n / DEFF); power = Phi(edge / SE - c); smallest edge detected at 80% power = (c + 0.842) x SE. sd_pair (SD of one trade's net R minus its matched random mean) is assumed 0.9, 1.2 or 1.5 R. c = 1.645 is the ideal one-sided test; c = 2.2 is the effective critical value fitted to the F9 table for the monthly dual-block rule.

| sd_pair | DEFF | effective trades | smallest edge at 80% power, ideal c | dual-rule c | power at 0.15 R (ideal / dual) | power at 0.20 R (ideal / dual) |
|---|---|---|---|---|---|---|
| 0.9 | 2.0 | 393 | 0.113 | 0.138 | 0.95 / 0.87 | 1.00 / 0.99 |
| **1.2** | **2.0** | **393** | **0.151** | **0.184** | **0.80 / 0.61** | **0.95 / 0.87** |
| 1.2 | 1.0 | 786 | 0.106 | 0.130 | 0.97 / 0.90 | 1.00 / 0.99 |
| 1.2 | 3.0 | 262 | 0.184 | 0.225 | 0.65 / 0.43 | 0.85 / 0.69 |
| 1.5 | 2.0 | 393 | 0.188 | 0.230 | 0.63 / 0.41 | 0.84 / 0.67 |
| 1.5 | 3.0 | 262 | 0.230 | 0.282 | 0.49 / 0.28 | 0.70 / 0.48 |

(the full 12-row grid is in `PREREGISTRATION_power_output.txt`).

**In plain words (decision D2).** smallest_edge_of_interest stays 0.15 R. **The central-case power at 0.15 R is about 61%** (sd_pair 1.2, DEFF 2, dual-block rule). **Across the assumptions the power at 0.15 R ranges from 28% to 90%** (sd_pair 1.2 to 1.5 and DEFF 1 to 3, dual-block rule; it reaches 99% only in the most favourable corner of the full grid, sd_pair 0.9 with DEFF 1). The smallest edge the registered rule detects with 80% power is about 0.18 R in the central case and 0.23 to 0.28 R in the unfavourable corner. So 0.15 R is not reliably detectable. **A non-significant result is "not demonstrated" and never "no edge"** (the same statement as KI-002). **The power figures will be replaced by the observed dispersion and dependence at STOP 4 only after the registered decision is made**, and not before.
Detecting 0.15 R at 80% power with sd_pair 1.2 needs about 790 nominal trades at DEFF 2 with an ideal test and about 1,180 with the dual rule (594 and 888 at DEFF 1.5; 1,187 and 1,776 at DEFF 3). At 74 trades a year that is 10.7 years in the ideal case and 16 years with the dual rule, so the 10.8-year window is just enough for an ideal test and about 5 years short for the dual rule. A cross-check that scales the F9 monthly result by the higher trade rate and longer window gives 0.13 R at 80% power, but it assumes F9's shorter holds and ignores its liberal size, so it is the optimistic bound.

## 10. Gates: what exists today, whether it is testable at this trade count (KI-002), and how each is used
`validation_gates` (shared, cannot be overridden; hash `805efac844810c62d6f5d74b706d7cfb0b042c5fbc3cf217add54116d783cd2f`):

| gate | value today | testable at about 790 trades? | use in the registered rule |
|---|---|---|---|
| min_trades | 40 | **Yes, as a count** (790 nominal against 40; KI-002 was written for 2.6 trades a month). It is a floor only: 40 trades have almost no power. | closed, usable trades >= 40 |
| min_expectancy_r | 0.15 | **Only as a point estimate.** n is no longer the problem, but the bar is on the strategy's own absolute net R per trade, with SE about 0.05 to 0.08 R (sd_trade 1.3 assumed, DEFF 1 to 3); a 95% lower bound above 0.15 needs a true value of about 0.23 to 0.28 R. A true expectancy of 0 passes the point bar about 0.1% to 3% of the time. | point estimate >= 0.15, reported with its 95% interval |
| min_profit_factor | 1.3 | Point estimate only; no sampling distribution is defined for it in the repo. | point estimate >= 1.3, reported with a block-bootstrap interval |
| max_drawdown_pct | 20.0 | **Computable, single path.** One observed number; there is no test and no interval for it. Changed from 15.0 (reviewed shared change, owner, 2026-11-11, every strategy). | observed largest drawdown on the daily equity curve <= 20.0 |
| min_alpha_after_tax_pct | -2.0 | **Computable, not testable.** Annualised alpha against the B2 benchmark; its sampling error over 10.8 years is of the order of 4 percentage points on my assumptions (about 3.8% monthly paired SD, independent months), larger than the floor. | point estimate >= -2.0, reported with its interval |
| ltcg_tax_pct, risk_free_pct | 0.0, 6.5 | Inputs (tax rate and benchmark cash rate), not gates. | used in B2 and in the alpha |

`paper_criteria` (shared; evaluated later in the paper phase, not at STOP 4B; **paper_criteria.max_drawdown_pct stays 12.0: a strategy that passes 20% in backtest can still fail 12% in paper**):

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

**Decision rule (as drafted, owner decision).** The single registered conclusion: T1 significant at both block lengths **and** every gate in the table above met on its point estimate (drawdown at 20.0). Anything else is reported as "not demonstrated", with the interval and the detectable edge, and **not** as evidence of no edge. T2, T3, the sub-periods and the diagnostics never change that conclusion. T3's limits 0.075 and 0.025 only label T1 "size unreliable", which sends the decision to the owner and reviewer.

## 11. Limitations carried into this pre-registration
1. **No historical ASM/GSM exclusion** (KI-003): snapshots exist only from 2026-11-08, so the shared surveillance exclusion is not applied in 2016 to 2026; both the strategy and the baseline ignore it.
2. **UNKNOWN sector bucket.** A quarter of the symbols the strategy picks with the ADTV tie-break (75 of 302; a third under the first ordering) have no sector in `data/reference/sector_map.csv` and share one bucket that the 15% cap holds to two positions at a time (the same as live; accepted by the owner). In the tie-break occupancy model 13% of entries are in that bucket.
3. **Unadjusted corporate actions inside the window.** Demerger, merger, rights and OTHER actions are not adjusted by the engine; a median of about 13 valid names a session have one inside their 252-bar window, with no extra guard (owner decision). A price jump from such an action can create or hide a "new high". Positions hit by an action the engine cannot rescale go on HOLD and are excluded from the statistics.
4. **EQ-only lake gaps** (PRE_LIVE_LIST item 11): the gap guard drops about 4% to 6% of the eligible names in 2022 and 2024 to 2026; a name that moves out of EQ looks like an absence and a re-listing. The lake keeps 934 symbols whose last bar is before 2026-10-16 (delisted, renamed, merged, suspended or moved out of EQ); the cause for each was not examined here.
5. **Cap-bound trade count.** The model's 6.17 entries a month is set by 12 slots and a 40-session hold (about 74 a year), not by the signal; the count does not grow with a stronger signal, and the effective sample is smaller than the nominal one because the trades overlap.
6. Also: prices are not adjusted for dividends (the lake holds split and bonus adjustments only) on both sides of every comparison; the market-cap gate is parked (KI-001); the random baseline has no portfolio effects (section 7); the power figures are assumption-based; F9 measured the monthly dual rule's size as 0.0625 to 0.063 (liberal); the strategy and the STOP 1 study tool are two implementations of one rule tied together by a fixture test; the backtest is single-process and takes hours; an entry skipped for a gap above 3% is shared behaviour; the drawdown gate is 20% in backtest while the paper gate stays 12%.

## 12. What was looked at before this text, and what was decided from it (the record of the counts-only studies)
**The registration does not touch the exploratory ledger** (it is pinned by a hash test; owner decision D5). **Section 12 is the record of the counts-only studies.** Counts only, never returns: the STOP 1 counts study (eligible, valid, candidate and proposed counts, occupancy and concentration models, data-quality counts, run time) and its tie-break rerun. Decisions taken after seeing them, on non-outcome grounds: the tie-break (nearness, then ADTV, then symbol) after the alphabetical skew of the first order showed in the entry counts; window A; expected_trade_rate 6.2; no extra guard for unadjusted actions; the UNKNOWN sector accepted. The fixture-lake backtests in the unit tests use synthetic data only. The rule's numbers (252, 250, 0.95, 25, 0.85, 40) were fixed in the task brief before any look and were not changed.

## 13. Registration (family route; STOP 4B only; nothing is run now)
Why the family route: it is the ledger path built for strategies (a member is anything with `id`, `version` and `config_hash()`); it fixes the budget, hash-chains the row, requires the results row to cover every registered member, and leaves the old CFG-01..06 trial ledger and its chain untouched. With one member the budget is 1 and no multiplicity correction is applied; that is honest because exactly one configuration is registered.
```python
import dataclasses
from stockbot.config.shared import load_shared_config
from stockbot.strategies.near_52w_high import SPEC          # the spec as committed in the finalisation commit
from stockbot.validation.ledger import FAMILY_LEDGER, register_family

cfg = load_shared_config()
register_family(path=FAMILY_LEDGER, family_id="near_52w_high", members=[SPEC],
                gate_params=dataclasses.asdict(cfg.validation_gates), git_sha="<PREREG_COMMIT_SHA>")
```
`<PREREG_COMMIT_SHA>` is the SHA of the finalisation commit, the commit that contains this file in this final form, the scripts and the spec with `prereg_ref` set. A file cannot contain its own commit SHA, so the placeholder stays in the text and the real SHA (`git rev-parse` of that commit, quoted in the STOP 4A report) goes into the call at STOP 4B. Then `stockbot.validation.prereg_lock.verify_ledger(FAMILY_LEDGER)` and `family_budget(FAMILY_LEDGER, "near_52w_high") == 1`; after the run `record_family_results(path=FAMILY_LEDGER, family_id="near_52w_high", results={"near_52w_high": {...}}, git_sha=...)`. The row records the commit SHA, the member's id, version and config hash (`359c8331...`), the budget and the hash of the shared gates (`805efac8...`).
Order of operations at STOP 4B: 1. the reviewer checks this final text against the owner's decisions and the owner approves in writing; 2. register with the finalisation commit SHA; 3. verify the chain and the budget; 4. run `scripts/research_near_52w_high.py --execute` once; 5. `scripts/baseline_matched_random_near_52w_high.py`; 6. `scripts/validate_near_52w_high.py`; 7. `scripts/evaluate_validation_gates_near_52w_high.py --t1 <results>`; 8. report as measured, with intervals, without interpretation beyond the registered decision rule.

## 14. Run-time plan (estimates; nothing was run)
Strategy backtest: 4 to 5 hours (at least 3.5). B1: eligibility is recomputed per actual trade by `draw_matched_random` (about 786 x 3.7 s, roughly 50 minutes) plus 15,720 simulated paths at an unmeasured 0.15 to 0.5 s each (0.7 to 2.2 hours): about 1.5 to 3 hours. B2, T1, T2, T3, gates: minutes. Total wall time about 6 to 8 hours single-process, run detached with logs. The 3.4 GB file reads are slow when the cache is cold (STOP 2 measured it 10 to 45 times slower).
