# trend_breakout_100d: pre-registration (DRAFT, Stage 1; NOT registered)

Drafted 2026-11-12 on branch `trend_breakout_100d`. Nothing here is registered in any ledger; registration is one `FAMILY_REGISTRATION` row for the four members of `family_batch1`, written by the owner on master (`docs/strategies/family_batch1/FAMILY.md`). No return, P&L, win rate or forward price change of this strategy has been computed or looked at. Everything marked PROPOSED is for the owner and reviewer to fix or change. Structure follows `docs/strategies/near_52w_high/PREREGISTRATION.md`; where the family file fixes a rule, this draft only points to it.

## 1. What is registered
One strategy, one configuration, one backtest run, one decision, inside the K = 4 family. No sweep, no variants. Any rerun is a new trial needing the owner's approval (FAMILY.md).

## 2. The rule (exactly the spec)
`stockbot/strategies/trend_breakout_100d/strategy.py`, `SPEC` at the registered commit:
- id `trend_breakout_100d`, version `1.0.0`, status `research`, exit_policy `trailing_pct_15`, universe_overrides `{}`, overlays `{}`, validation_ref empty. `expected_trade_rate`, `smallest_edge_of_interest` and `prereg_ref` are None in this draft: the owner sets them (section 9).
- params `{"min_bars": 200, "min_present": 198, "breakout_lookback": 100, "sma_period": 200, "top_n": 25, "stop_fraction": 0.85, "adtv_sessions": 20}`.
- Universe: shared `universe.eligibility`, no overrides.
- Data rule: 200 own bars, a bar on the signal date, at least 198 of the last 200 Nifty sessions present (while the calendar is shorter than 200 sessions, the calendar so far, at most 2 missing).
- Signal (on the session close, adjusted prices, as-of basis): close > max close of the symbol's previous 100 bars (today excluded, strict) AND close > mean of the last 200 closes (today included).
- Order: raw 20-session ADTV descending (none counts as 0), then symbol ascending; the first 25 are proposed with an explicit ordinal rank (25 down to 1). The order does not look at how far the close is above anything (liquidity-neutral on purpose, owner).
- Entry: the engine's next-open fill. Stop: 0.85 x the signal-day adjusted close. Exit: library policy `trailing_pct_15` (stop trails 15% under the highest close since entry; first applies the bar after entry; the entry bar is tested against the initial stop) or the stop. Long only; no regime filter; no target.
- **Spec hash at this draft: `07963c2aa6932f2b6efb79acce9e980d8c43aa9480378c48fe28acc597b22d80`.** It will change when the owner sets the three fields above; the registered hash is the final one.
- Shared `validation_gates` as in force: min_trades 40, min_expectancy_r 0.15, min_profit_factor 1.3, max_drawdown_pct 20.0, min_alpha_after_tax_pct -2.0 (ltcg_tax_pct 0.0, risk_free_pct 6.5). Hash recorded at registration.

## 3. Window
One registered run, 2016-01-01 to 2026-10-16 (the family window). Two DESCRIPTIVE sub-period reports (2016-2019, 2020-2026 by entry date) as for near_52w_high; never used to select, change or stop anything. Regime (Nifty above/below its 200-day mean) is reported descriptively only; it is not a filter and not a test.

## 4. Execution, cost, risk settings (shared, not overridable; quoted from `shared.yaml` on 2026-11-12)
entry_fill NEXT_OPEN; entry_slippage_pct 0.10; exit_slippage_pct 0.10; max_entry_gap_up_pct 3.0. max_loss_pct_per_trade 1.0, max_concurrent_positions 12, max_total_portfolio_risk_pct 15.0, max_sector_exposure_pct 15.0. Cost stack, initial equity and universe values as in the near_52w_high pre-registration section 4 (re-quote from `shared.yaml` at registration).

## 5. Data snapshot
`finsight.db` sha256 `dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752`, 3,432,767,488 bytes, mtime 2026-11-08 12:38:02 +0530, last session 2026-10-16. Checked unchanged before and after the Stage 1 counts run.

## 6. The run
A research wiring script analogous to `scripts/research_near_52w_high.py` (NOT yet written; Stage 1 does not include it) runs `run_backtest` once with `policies=None` so the library builds `trailing_pct_15` from the spec. Scoring this rule measured a median 4.4 s a session (mean 6.9 s) plus eligibility 11.9 s median, under heavy machine load; expect many hours, detached with logs.

## 7. Baselines (family-fixed; FAMILY.md)
B1 matched-random at trade level, seed 20261111, 20 draws per trade, at least 10 filled, through `draw_matched_random`/`simulate_ticket` with the same relative stop and the library `TrailingStop(15)` (the draws use the same exit rule as the strategy). B2 Nifty matched to the invested share with the shared risk-free rate on the rest. Paired comparison: per trade, net R minus mean net R of its draws. **Open point for the owner:** T2's forward-return horizons (1, 5, 10, 20) stop at 20 sessions, which is only part of a trailing-stop trade's life. T1 uses full-trade net R and is unaffected.

## 8. Tests (family-fixed; FAMILY.md)
T1: one joint Westfall-Young Max-T over the four members' monthly paired series, B = 10,000, seed 20261111, blocks 2 and 3 months, significant at both; T2 reported only; T3 joint placebo size check with limits 0.025 to 0.075. Conclusion: DEMONSTRATED only if found by T1 and every shared gate is met; otherwise "NOT DEMONSTRATED (registered rule not met; this is not evidence of no edge)".

## 9. Trade count, power, what the test can detect (PROPOSED)
Stage 1 counts (`Claude_Docs/TREND_BREAKOUT_100D_SIGNAL_COUNTS.md`): the rule gives a signal on 2,568 of 2,674 sessions (median 17, mean 23.8 names; 1,624 sessions with 12 or more), so supply is not the limit; the 12 slots are.
The trade count depends on how long the 15% trailing stop keeps a position, a forward-price quantity not read in Stage 1. Mechanical bracket (12 slots always refilled; stops, risk cap, costs, gap-up cap, cash cap ignored): assumed hold 20 / 40 / 60 / 100 / 150 / 250 sessions gives 1,503 / 781 / 528 / 324 / 216 / 132 entries over the sample (11.8 / 6.1 / 4.2 / 2.5 / 1.7 / 1.0 a month); the shared sector cap changes these by at most about 2%. **Every assumed hold, including 250 sessions, gives more than 40 trades (the stop condition is not met).** Stops that fire early shorten holds and raise the count; the ignored blocks lower it.
`expected_trade_rate` is not set by me; the owner decides. Power: the near_52w_high arithmetic (`power_calc.py`, sd_pair 1.2 R, DEFF 2, 786 nominal trades, about 61% power at 0.15 R with the dual-block rule) does not carry over. At 324 nominal trades (100-session hold) and the same assumptions the effective sample is about 160, and the smallest edge detected at 80% power is roughly 0.28 R with the dual-block rule (about 0.23 R for an ideal test); these are my scaling of the near_52w_high arithmetic and were not re-run with `power_calc.py`. Long trailing-stop holds overlap heavily, so DEFF could be larger. **This strategy is likely underpowered for 0.15 R if holds are long.** smallest_edge_of_interest is left to the owner. A non-significant result is "not demonstrated", never "no edge".
Gates at this trade count: min_trades is testable as a count; min_expectancy_r, min_profit_factor and min_alpha_after_tax_pct are point estimates only (KI-002); max_drawdown_pct is one observed path.

## 10. Overlap with near_52w_high (counts, Stage 1)
83.9% of this strategy's signal name-sessions (53,500 of 63,740) were also near_52w_high candidates the same day (nearness >= 0.95 and that rule's gap guard); 84.2% of the proposed top-25 name-sessions. Yearly range 68% to 95%. Overlap is with that rule's candidate set, not with its top 25. The two strategies are close to one signal. Joint Max-T handles correlated members, but the family gains little independent evidence from this pair; near_52w_high was NOT DEMONSTRATED (T1 adjusted p about 0.41).

## 11. Regime split (counts, Stage 1; Nifty close above/below the mean of its last 200 closes)
Above: 1,920 sessions (71.8%), 53,324 signal name-sessions (83.7%), median 22 a session. Below: 591 sessions (22.1%), 8,491 signals (13.3%), median 5. n/a (fewer than 200 Nifty bars; the Nifty calendar starts 2015-11-09): 163 sessions, all in 2016, 1,925 signals. 2026 is mostly "below" (159 of 196 sessions) with 6,297 signals, so recent signals are not a bull-market-only phenomenon. Descriptive only.

## 12. Limitations
No historical ASM/GSM exclusion (KI-003); UNKNOWN sector bucket and the shared 15% sector cap; unadjusted corporate actions (demerger, merger, rights, OTHER) are not handled, so a price jump from one can create a breakout; EQ-only lake gaps; the 100-session maximum uses the symbol's own previous 100 bars (equal to the calendar's 100 sessions unless it has 1 to 2 missing); the occupancy model is a bracket under assumed holds, not a forecast; the eligible universe is small in 2016 (median 144 names) and the first 163 sessions have no regime label; slots fill together on day one, so modelled entries cluster (entries per year at long assumed holds are multiples of 12); prices are not dividend-adjusted; the counts ran under heavy shared-machine load, so the timings are not a speed benchmark.

## 13. Registration
Not drafted as a single-member call: this strategy registers with the other three as one `register_family(..., members=[...four specs...], ...)` by the owner on master, after the four Stage 1 reports are reviewed. `<PREREG_COMMIT_SHA>` is the commit holding the final text of the four pre-registrations.
