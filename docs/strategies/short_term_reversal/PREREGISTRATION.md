# short_term_reversal: pre-registration (DRAFT, Stage 1, 2026-11-12; NOT approved, NOT registered)

Draft in the format of `docs/strategies/near_52w_high/PREREGISTRATION.md`. Parts marked **filled at family registration** depend on the family (`docs/strategies/family_batch1/FAMILY.md`, K = 4) and are written by the owner at the single registration. Nothing here has been registered in any ledger. No return, P&L, win rate or forward price change of this strategy has been computed or looked at. The only measurements so far are counts (`docs/strategies/short_term_reversal/results_stage1/counts.md`, measured 2026-11-12) and the power arithmetic of section 9.

## 0. Approval record
Pending. To be filled when the owner and reviewer approve (decisions D1 to Dn, as for near_52w_high). Open questions for the owner are in `STATUS.md` under "Decisions needed".

## 1. What is registered
One strategy, one configuration, one backtest run, one decision, as a member of the family. No parameter sweep, no variants; any second run is a new trial and needs a new approval. **Family id, member list, budget K and the single FAMILY_REGISTRATION row: filled at family registration.**

## 2. The rule and parameters (exactly the spec)
`stockbot/strategies/short_term_reversal/strategy.py`, `SPEC` at the registered commit:
- id `short_term_reversal`, version `1.0.0`, status `research`, exit_policy `fixed_hold_5`, universe_overrides `{}`, overlays `{}`, smallest_edge_of_interest 0.15 R (net of costs), expected_trade_rate 23.0 per month (Stage 1 estimate, section 12; the owner confirms), `prereg_ref` set in the registration commit (as for near_52w_high, D1), validation_ref empty.
- params `{"lookback_sessions": 5, "min_bars": 10, "ret_floor": -0.30, "ret_cap": -0.07, "top_n": 25, "stop_fraction": 0.92, "tie_adtv_sessions": 20}`.
- Universe: shared `universe.eligibility`, no overrides.
- Data: at least `min_bars` (10) own bars, a bar on the signal date, and a bar on the session 5 calendar sessions earlier (Nifty calendar); a name without that anchor bar is not a signal.
- ret5 = adjusted close[t] / adjusted close[t-5 sessions] - 1, point-in-time as-of basis (`AsOfView.adjusted_bars`), rounded to 12 decimals. Signal: -0.30 <= ret5 <= -0.07, both ends inclusive. The floor guards against unadjusted corporate-action artifacts.
- Order: ret5 ascending (deepest fall first); ties by higher raw 20-session ADTV; then symbol. The first 25 are proposed with an explicit ordinal rank (25 down to 1).
- Entry: the engine's next-open fill. Stop: 0.92 x the signal-day adjusted close. Exit: `fixed_hold_5` (entry session is session 1, a market exit at the open of session 6, five closes held) or the stop, whichever is first. Long only; no regime filter; no target.
- **Spec hash at the registered commit: filled at family registration** (the hash covers every spec field, including `prereg_ref` and `expected_trade_rate`; it changes when either is set).
- **Shared validation_gates hash: filled at family registration** (the gates are read from `shared.yaml` at that time).

## 3. Window and descriptive sub-periods
- **Registered run:** 2016-01-01 to 2026-10-16, one run (the family window; `validate_family.py` refuses members with different windows). The TEST/TUNE labels in `shared.yaml` do not apply: nothing is tuned.
- Two DESCRIPTIVE sub-period reports, 2016-01-01 to 2019-12-31 and 2020-01-01 to 2026-10-16 (trades by entry date): reported, never used to select, change or stop anything, no pass or fail.

## 4. Execution, cost and risk settings in force (shared, from `stockbot/config/shared.yaml`, not overridable)
entry_fill NEXT_OPEN; entry_slippage_pct 0.10; exit_slippage_pct 0.10; max_entry_gap_up_pct 3.0. Costs: stt_buy_pct 0.10, stt_sell_pct 0.10, brokerage 0.0, exchange_txn_pct 0.00297, sebi_fee_pct 0.0001, stamp_duty_buy_pct 0.015, gst_pct 18.0, dp_charge_per_sell_inr 15.34, stcg_tax_pct 0.0. Portfolio: max_loss_pct_per_trade 1.0, max_concurrent_positions 12, max_total_portfolio_risk_pct 15.0, max_sector_exposure_pct 15.0. Initial equity 1,000,000. Universe: min_adtv_cr 25, min_listing_age_trading_days 252, min_market_cap_cr 5000 (PARKED, KI-001).
**What these mean for this rule (arithmetic, section 12):** the 8% stop gives a position of 12.5% of equity, so the 15% sector cap allows ONE position per sector (and one at a time in the UNKNOWN bucket) and cash allows at most 8 positions; the cash cap, not the 12-position cap, binds. Round-trip friction is about 0.43% of position value (0.2% slippage, 0.2% STT, about 0.03% other), about 0.05 R at an 8% stop, against the 0.15 R edge of interest.

## 5. Data snapshot
`finsight.db`, sha256 `dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752`, 3,432,767,488 bytes, mtime 2026-11-08 12:38:02.892612 +0530, last session 2026-10-16. Re-checked at every stage; if it differs at the registered run the run does not start.

## 6. The run
**Filled at family registration.** The strategy-specific research wiring script (as `scripts/research_near_52w_high.py`) does not exist yet and is not part of Stage 1; it is a strategy-owned script (`scripts/research_short_term_reversal.py`) to be written, with a fixture-lake test, before registration. One run, window of section 3, detached, with logs.

## 7. Baselines
Per the family rules (FAMILY.md): **B1** matched-random entries at trade level through the shared simulator (seed 20261111, 20 draws per trade, at least 10 filled, same eligibility, same `fixed_hold_5` exit, same relative stop, no portfolio caps); **B2** the Nifty matched to the member's own invested share with the shared risk-free rate on the rest. The existing B1 and B2 scripts are named for near_52w_high and read its spec; member-specific versions (or a family version) are **filled at family registration**. Design limits as for near_52w_high: the random draws are not subject to the slot, sector and cash caps; there is no random equity curve. For this rule the holds are short (5 sessions, mean 5.5 positions open of 8 slots in the Stage 1 model, 2016-2026), so overlap between trades is small, but entries cluster on a few market-wide fall days (section 12).

## 8. Tests
**T1 (decision test), T2, T3, confidence intervals and the decision rule: filled at family registration** (one joint Westfall-Young Max-T over the K monthly series, blocks 2 and 3 months, B 10,000, seed 20261111; member found only if significant at both; conclusion DEMONSTRATED only if found and every shared gate is met, otherwise "NOT DEMONSTRATED (registered rule not met; this is not evidence of no edge)"). Reported always for this member: trade count (closed, usable, excluded, END_OF_WINDOW), entries per month and year, occupancy and invested share seen, sector-cap blocks, largest drawdown, profit factor, win rate, expectancy, the sub-periods of section 3.

## 9. Power (assumption-based, nothing measured)
Normal approximation as in near_52w_high section 9: SE = sd_pair / sqrt(n / DEFF); smallest edge at 80% power = (c + 0.842) x SE; c = 1.645 (ideal one-sided) or 2.2 (the effective value fitted to the F9 monthly dual-block rule). n = 2,931 nominal trades (Stage 1 `shared` model, 2016-2026), sd_pair 0.9, 1.2 or 1.5 R, DEFF 1 to 3 (assumed; cannot be measured without looking at returns). For the joint test the critical value is higher than a single test's; the figures below are single-test, so they are optimistic for a family of 4.

| sd_pair | DEFF | effective trades | smallest edge at 80% power, ideal c | dual-rule c | power at 0.15 R (ideal / dual) |
|---|---|---|---|---|---|
| 1.2 | 1 | 2931 | 0.055 | 0.067 | 1.00 / 1.00 |
| **1.2** | **2** | **1466** | **0.078** | **0.095** | **1.00 / 1.00** |
| 1.2 | 3 | 977 | 0.095 | 0.117 | 0.99 / 0.96 |
| 1.5 | 3 | 977 | 0.119 | 0.146 | 0.93 / 0.82 |
| 0.9 | 2 | 1466 | 0.058 | 0.072 | 1.00 / 1.00 |

In plain words: on these assumptions 0.15 R is detectable with high power at the nominal trade count, much better than for near_52w_high. Three things pull the other way and are not in the table: trades are NOT independent (entries cluster on market-fall days: 659 of 2,710 sessions had more than 25 signals, the 10 worst market days carry 1.8% of all signals against 0.37% if spread evenly, so the DEFF could be larger than 3 in the monthly series); the monthly series that T1 uses has only 130 points however many trades there are; and friction of about 0.05 R is paid on every trade. A non-significant result is "not demonstrated", never "no edge".

## 10. Gates
The shared `validation_gates` (max_drawdown_pct 20.0, min_alpha_after_tax_pct -2.0, min_expectancy_r 0.15, min_profit_factor 1.3, min_trades 40, ltcg_tax_pct 0.0, risk_free_pct 6.5) and `paper_criteria` apply unchanged, per member, read at run time. For this rule the trade count (about 2,900 nominal) is not a constraint for min_trades; testability of each gate is **filled at family registration**. `paper_criteria.max_drawdown_pct` stays 12.0.

## 11. Limitations carried into this pre-registration
1. No historical ASM/GSM exclusion (KI-003); both the strategy and the baseline ignore it.
2. **UNKNOWN sector bucket**: 36.0% of all signals have no sector in `data/reference/sector_map.csv`; under the 15% cap and a 12.5% position they share ONE slot, which is the largest single driver of sector blocks (9,718 blocks in the shared model).
3. **Unadjusted corporate actions**: 204 signal-sessions have a demerger, merger, rights or OTHER action inside the 6-bar window (the engine does not adjust these) and 108 have a split/bonus (adjusted); only the -0.30 floor guards artifacts. The floor dropped 574 name-sessions, 72 of which had a corporate action in the window.
4. Entries whose next open gaps below the stop, and the 3% gap-up cap, block or skip trades; they need a price after the signal and could not be counted at Stage 1. Fills after a big fall day are where this matters most.
5. Prices are not adjusted for dividends on either side of any comparison; the market-cap gate is parked (KI-001); the random baseline has no portfolio effects.
6. `no_anchor` (1,139 name-sessions) and the first five sessions of the lake (no 6-session calendar, 712 name-sessions) produce no signal.
7. The counts study and the strategy share one implementation (`scan`, `order_candidates`); the study's Nifty move (used only to find the 10 worst market days) is an index measure, not a return of the strategy.

## 12. What was looked at before this text (the record of the counts-only study)
Counts only, never returns (measured 2026-11-12, 2,710 sessions 2015-11-09 to 2026-10-16, finsight.db size and mtime unchanged across all four parts): signals per year and month, sessions with more than 25 signals (659), share of signals on the 10 worst market days (1.8%), sector spread, tie rate (10 of 33,108 proposed names in a tie group; no tie ever straddled the cut), stop fit (8.00% against a 6.67% minimum: fits), and a mechanical occupancy model of the shared caps (`plain` 37.5, `sector` 27.7, `shared` 23.0 entries a month for 2016-2026; 2,931 shared entries; shared slots full on 15% of sessions). The model ignores stops (would raise the count), entry gaps, the gap-up cap and costs (would lower it); neither direction is bounded. **No decision was taken from the counts: the rule's numbers (5, 10, -0.30, -0.07, 25, 0.92, fixed_hold_5) are the owner's and were not changed**, and the counts did not show the rule unworkable. The one derived number is `expected_trade_rate` 23.0, for the owner to confirm.

## 13. Registration (family route)
**Filled at family registration.** One FAMILY_REGISTRATION row for all K members (budget K) and one FAMILY_RESULTS row, written by the owner on master (`register_family`, `record_family_results`); the commit SHA placeholder rule of near_52w_high section 13 applies.

## 14. Run-time plan
Strategy backtest: unmeasured; the near_52w_high run took 3 h 59 min and this rule trades about 4 times as often. The Stage 1 counts study took about 4.3 hours wall time in four parallel date segments on a busy disk (about 3 to 10 s per session per process when the disk was shared with other strategy runs).
