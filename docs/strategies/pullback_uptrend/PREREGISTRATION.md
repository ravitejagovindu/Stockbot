# pullback_uptrend: pre-registration (DRAFT, NOT REGISTERED)

Drafted 2026-11-12 at the end of stage 1. **Nothing in this file has been registered in any ledger.** Every number the owner has not fixed is marked **PROPOSED**; none of them is decided here. No return, P&L, win rate or forward price change of this strategy has been computed or looked at: the only measurements are the stage-1 counts (`docs/strategies/pullback_uptrend/counts/`, `counts.md` and `summary.json`) and test results. The strategy is a member of family_batch1 (K = 4, `docs/strategies/family_batch1/FAMILY.md`); its registration is the owner's single `FAMILY_REGISTRATION` row on master, not a row written from this branch.

## 1. What would be registered
One strategy, one configuration, one backtest run, one decision, inside a K = 4 family corrected jointly by Max-T. No parameter sweep, no variants, no second run unless a bug is found (then it is a new trial and needs a new approval).

## 2. The rule and parameters (exactly the spec)
`stockbot/strategies/pullback_uptrend/strategy.py`, `SPEC` at the registered commit:
- id `pullback_uptrend`, version `1.0.0`, status `research`, exit_policy `fixed_hold_5`, universe_overrides `{}`, overlays `{}`, validation_ref empty.
- `expected_trade_rate`: **owner to set** (section 6: 31.7 per month with the shared sector cap, 39.0 without). `smallest_edge_of_interest`: **owner to supply** (not invented here). `prereg_ref`: set in the registration commit, as for near_52w_high (the hash covers it).
- params `{"min_bars": 250, "sma_period": 200, "sma_min_closes": 198, "rsi_period": 2, "rsi_max": 10.0, "top_n": 25, "stop_fraction": 0.92, "tie_adtv_sessions": 20}`.
- Universe: shared `universe.eligibility`, no overrides.
- Signal on the session close: adjusted close > SMA200 and RSI(2) < 10 (strict). SMA200 = mean of the symbol's adjusted closes inside the last 200 Nifty-calendar sessions, at least 198 of them present; the symbol needs its own last 250 adjusted bars and a bar on the signal date. With fewer than 200 sessions in the Nifty calendar there is no SMA200 and no signal.
- RSI(2): Wilder smoothing (`stockbot.data.indicators.rma`, seeded with the simple mean of the first two changes, then avg = (avg + x) / 2) over the symbol's last 250 adjusted closes; avg_loss 0 gives 100 (50 if avg_gain is also 0). Tested against hand-computed values and an independent recursion.
- Order: RSI ascending; exact RSI ties by higher raw 20-session ADTV; then symbol. The first 25 are proposed with an explicit ordinal rank (25 down to 1).
- Entry: the engine's next-open fill. Stop: 0.92 x the signal-day adjusted close (as-of basis). Exit: `fixed_hold_5` (entry session is session 1, market exit at the open of session 6, five closes held) or the stop, whichever is first. Long only; no regime filter; no target.
- Spec hash: **to be recorded in the registration commit** (`SPEC.config_hash()` changes when `prereg_ref`, the trade rate or the edge are set).

## 3. Window (PROPOSED, owner decides)
- **Finding of the counts study:** the first session on which a signal can exist is **2016-08-30** (the Nifty calendar starts 2015-11-09 and SMA200 needs 200 sessions); the 163 sessions from 2016-01-01 to 2016-08-29 have none by the rule's own definition. PROPOSED: the same window as the other family members, **2016-01-01 to 2026-10-16** (FAMILY.md requires one common window; `validate_family.py` refuses different ones), accepting that the first 163 sessions are empty and that monthly series for 2016-01 to 2016-08 are zero for this member. The alternative (start 2016-09-01 for the whole family) is the owner's call.
- Two DESCRIPTIVE sub-period reports (as for near_52w_high): 2016 to 2019 and 2020 to 2026-10-16, by entry date; never used to select, change or stop anything.
- The TEST/TUNE labels in `shared.yaml` do not apply (nothing tuned, one run), as decided for near_52w_high.

## 4. Execution, cost and risk settings in force (shared, not overridable; quoted from `stockbot/config/shared.yaml` at the branch base 055c703)
entry_fill NEXT_OPEN; entry_slippage_pct 0.10; exit_slippage_pct 0.10; max_entry_gap_up_pct 3.0. Costs: stt_buy_pct 0.10, stt_sell_pct 0.10, brokerage_per_order_inr 0.0, exchange_txn_pct 0.00297, sebi_fee_pct 0.0001, stamp_duty_buy_pct 0.015, gst_pct 18.0, dp_charge_per_sell_inr 15.34, stcg_tax_pct 0.0. Portfolio: max_loss_pct_per_trade 1.0, max_concurrent_positions 12, max_total_portfolio_risk_pct 15.0, max_sector_exposure_pct 15.0. Backtest initial_equity 1,000,000. Universe: min_adtv_cr 25, min_listing_age_trading_days 252, min_market_cap_cr 5000 (PARKED, KI-001). **Cost note:** a 5-session hold pays the round-trip costs on every trade, so costs weigh about eight times more per day held than for a 40-session hold; the gates are net of costs.

## 5. Data snapshot
`finsight.db`, sha256 `dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752`, 3,432,767,488 bytes, mtime 2026-11-08 12:38:02.892612 +0530, last session 2026-10-16. Unchanged (size and mtime) across the whole stage-1 counts run.

## 6. Counts that inform the registration (counts only; `counts/counts.md`, measured 2026-11-12)
- Signals per session (from 2016-08-30, 2,511 sessions): median 11, p5 1, p95 72, max 287; 51,441 signal name-sessions; the top-25 cut binds on 628 sessions (25%).
- Occupancy model (12 slots, 5-session hold, a held symbol skipped): 4,659 entries (39.0 a month) without the sector cap, 3,786 (**31.7 a month**) with the shared 15% sector cap (position size 12.5% of equity at the 8% stop, so one position per sector at a time; unmapped symbols share one UNKNOWN sector). It ignores stops (more entries), and the risk cap, costs, gap-up cap and fill blocks (fewer). PROPOSED `expected_trade_rate`: **31.7**, the capped figure, as for near_52w_high; the owner decides. The expected trade count over the window is about 3,800 (near_52w_high: 786).
- Concentration: 828 distinct symbols; largest 0.6% of entries; top-10 share 5.3%.
- Nifty regime (close vs its 200-session average, 198 of 200 needed): 81.5% of signal name-sessions (3,672 of the 4,659 uncapped entries) fall with the Nifty ABOVE its average, 18.5% below, none in the 163 undefined sessions; the Nifty is above on 71.8% of sessions and below on 22.1%.
- Clustering: the busiest 10% of sessions hold 41% of the signal name-sessions; on Nifty days down 1% or more (10% of sessions) the median is 29 signals a session against 11 on other days, and 21% of all signals fall on those days; on days down 2% or more (2.3% of sessions), 4.8% of signals.
- Data quality: 3,161 signal name-sessions have a split or bonus inside the 250-bar window (adjusted by the engine); 2,220 have a demerger, merger, rights or OTHER action inside it (NOT adjusted by the engine), which can fake a pullback; no guard is proposed (the same accepted limitation as near_52w_high).
- Runtime: shared eligibility median 9.0 s and scoring median 5.5 s per session on a machine shared with other jobs, so a full backtest is projected at roughly 10 hours before the engine's own work (to be measured, not promised).

## 7. Baselines (as in FAMILY.md; same for every member)
- **B1:** matched-random entries at trade level through the shared simulator (`draw_matched_random`): 20 draws per actual trade, at least 10 filled, seed 20261111, same eligibility, same `fixed_hold_5` exit and same relative stop (8% below the entry reference).
- **B2:** the Nifty matched to the strategy's own daily invested share, the rest at the shared risk-free rate (6.5%); annualised alpha after the shared tax rate (0.0) feeds the alpha gate.
- No full-engine random replicates.

## 8. Tests (family procedure, `scripts/validate_family.py`)
- **T1 (decision test):** per member, D(m) = sum over trades entered in month m of (actual net R minus the mean net R of that trade's random draws); the K = 4 monthly series tested together with ONE Westfall-Young step-down Max-T (one-sided, family-wise 0.05, B = 10,000, studentized circular block bootstrap, the same block draw for all series, seed 20261111), block lengths 2 and 3 months; "found" only if the adjusted p is at most 0.05 at both.
- **T2:** paired statistics, reported only. **T3:** placebo size check of the joint procedure (limits 0.025 to 0.075; outside is "size unreliable", the owner decides, nothing is recalibrated).
- With about 3,800 trades and a 5-day hold, the monthly series has many trades per month and the member's power is likely higher than near_52w_high's, but trades cluster in sell-off days (section 6) and are therefore correlated: the effective sample is smaller than the nominal one. **No power figure is computed here (PROPOSED: the owner and reviewer decide whether to run `power_calc.py`-style arithmetic for this member before registration).** The F9 power study covers the Max-T procedure at portfolio level only.

## 9. Validation gates today (`validation_gates`, shared; current value and testability at ~3,800 trades, KI-002)
| gate | value | testable at this trade count? |
|---|---|---|
| min_trades | 40 | yes (about 3,800 expected) |
| min_expectancy_r | 0.15 | yes (point estimate); the interval is wide for a clustered series |
| min_profit_factor | 1.3 | yes (point estimate) |
| max_drawdown_pct | 20.0 | yes; **backtest 20.0 versus paper 12.0**: a pass here can still fail 12% in paper |
| min_alpha_after_tax_pct | -2.0 | yes (B2) |
Gate pass/fail levels are the shared ones; this draft proposes none of its own. KI-002: gates stated as point estimates do not account for sampling error; the registered rule is T1 AND all gates on point estimates, as for near_52w_high.

## 10. Decision rule (PROPOSED, as for near_52w_high; the owner decides)
DEMONSTRATED only if T1 finds the member (adjusted p at most 0.05 at both block lengths) AND every shared gate is met on its point estimate; otherwise "NOT DEMONSTRATED (registered rule not met; this is not evidence of no edge)". Status stays `research` whatever the outcome.

## 11. Registration call (family route; NOT run; the owner writes it on master)
```
register_family(path=<family_ledger.csv>, family_id="family_batch1", members=[<four spec hashes incl. pullback_uptrend's>], gate_params=<shared validation_gates>, git_sha="<COMMIT SHA OF THE APPROVED PRE-REGISTRATION>", reason="family_batch1 K=4")
```
(exact keyword form per `stockbot/validation/ledger/__init__.py`; one row for all four members, budget 4.) Results go in one `record_family_results` row after the joint validation.

## 12. Limitations
- No signals before 2016-08-30; the first 163 sessions of the window are empty.
- Sector map: unmapped symbols share one UNKNOWN sector, which the 15% cap limits to one open position at this position size; 23% of uncapped entries (10% with the cap) are such names.
- Unadjusted corporate actions inside the window can fake a pullback (2,220 signal name-sessions); no guard.
- No historical ASM/GSM exclusion (KI-003); EQ-only lake (gaps).
- Occupancy numbers are a counts model, not a forecast of engine trades.
- Strongly clustered signals (sell-offs), a short hold and real costs: the net edge per trade is the open question; nothing about it has been looked at.
- Exact RSI ties are rare (no rounding); the ADTV tie-break seldom matters.

## 13. Decisions needed from the owner
1. Window (common 2016-01-01 start with an empty first 163 sessions, or 2016-09-01 for the family).
2. `expected_trade_rate` (31.7 proposed) and `smallest_edge_of_interest`.
3. Whether to compute a power figure before registration.
4. Confirm the decision rule and the T1/T2/T3 settings for this member, and the common B1/B2 settings.
