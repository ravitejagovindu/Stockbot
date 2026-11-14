# pullback_uptrend: pre-registration (DRAFT, NOT REGISTERED)

Stage-1 draft 2026-11-12; finalised at stage 2 (2026-11-14) with the owner's decisions below. **Nothing in this file has been registered in any ledger; it stays DRAFT until the owner registers the family on master.** No return, P&L, win rate or forward price change of this strategy has been computed or looked at: the only measurements are the stage-1 counts (`docs/strategies/pullback_uptrend/counts/`), the stage-2 re-count under the new sector rule (`counts_new_sector_rule/`) and test results. The strategy is a member of family_batch1 (K = 2: `short_term_reversal`, `pullback_uptrend`; `docs/strategies/family_batch1/FAMILY.md`); its registration is the owner's single `FAMILY_REGISTRATION` row on master, not a row written from this branch.

## Owner decisions (final, stage 2)
- Rule numbers unchanged from stage 1: close > SMA200 with 198 of 200 closes, RSI(2) Wilder < 10, `min_bars` 250, `top_n` 25, stop 0.92 x signal close, exit `fixed_hold_5`.
- `expected_trade_rate` = **31.7** (a month); `smallest_edge_of_interest` = **0.15** R per trade net of costs; `prereg_ref` = `docs/strategies/pullback_uptrend/PREREGISTRATION.md`.
- Window for BOTH family members: **2016-01-01 to 2026-10-16** (the family tool refuses unequal windows). This member has no signal before 2016-08-30 (its first 163 sessions are empty by the rule's own definition).
- Family: `family_batch1`, **K = 2**, joint Westfall-Young Max-T.

## 1. What would be registered
One strategy, one configuration, one backtest run, one decision, inside a K = 2 family corrected jointly by Max-T. No parameter sweep, no variants, no second run unless a bug is found (then it is a new trial and needs a new approval).

## 2. The rule and parameters (exactly the spec)
`stockbot/strategies/pullback_uptrend/strategy.py`, `SPEC` at the registered commit:
- id `pullback_uptrend`, version `1.0.0`, status `research`, exit_policy `fixed_hold_5`, universe_overrides `{}`, overlays `{}`, validation_ref empty.
- `expected_trade_rate` 31.7, `smallest_edge_of_interest` 0.15, `prereg_ref` `docs/strategies/pullback_uptrend/PREREGISTRATION.md`.
- params `{"min_bars": 250, "sma_period": 200, "sma_min_closes": 198, "rsi_period": 2, "rsi_max": 10.0, "top_n": 25, "stop_fraction": 0.92, "tie_adtv_sessions": 20}`.
- Universe: shared `universe.eligibility`, no overrides.
- Signal on the session close: adjusted close > SMA200 and RSI(2) < 10 (strict). SMA200 = mean of the symbol's adjusted closes inside the last 200 Nifty-calendar sessions, at least 198 of them present; the symbol needs its own last 250 adjusted bars and a bar on the signal date. With fewer than 200 sessions in the Nifty calendar there is no SMA200 and no signal.
- RSI(2): Wilder smoothing (`stockbot.data.indicators.rma`, seeded with the simple mean of the first two changes, then avg = (avg + x) / 2) over the symbol's last 250 adjusted closes; avg_loss 0 gives 100 (50 if avg_gain is also 0). Tested against hand-computed values and an independent recursion.
- Order: RSI ascending; exact RSI ties by higher raw 20-session ADTV; then symbol. The first 25 are proposed with an explicit ordinal rank (25 down to 1).
- Entry: the engine's next-open fill. Stop: 0.92 x the signal-day adjusted close. Exit: `fixed_hold_5` (entry session is session 1, market exit at the open of session 6, five closes held) or the stop, whichever is first. Long only; no regime filter; no target.
- **Spec hash at the stage-2 commit: `81db6427ebc9e11980c2cbbfb86720c7e1e68eeb27073b05c95cc64ce4207044`** (`SPEC.config_hash()`; it covers every spec field, `prereg_ref`, the trade rate and the edge included). The registration commit records the hash again; it must equal this one unless a spec field is changed first.

## 3. Window and sub-periods
- Both members: **2016-01-01 to 2026-10-16**. The first signal can occur on 2016-08-30 (the Nifty calendar starts 2015-11-09 and SMA200 needs 200 sessions); the monthly series for 2016-01 to 2016-08 is zero for this member.
- Two DESCRIPTIVE sub-period reports (as for near_52w_high): 2016 to 2019 and 2020 to 2026-10-16, by entry date; never used to select, change or stop anything.
- The TEST/TUNE labels in `shared.yaml` do not apply (nothing tuned, one run), as decided for near_52w_high.

## 4. Execution, cost and risk settings in force (shared, not overridable)
Read from `config/shared.yaml` at run time; at the time of writing: entry_fill NEXT_OPEN; entry_slippage_pct 0.10; exit_slippage_pct 0.10; max_entry_gap_up_pct 3.0. Costs: stt_buy_pct 0.10, stt_sell_pct 0.10, brokerage_per_order_inr 0.0, exchange_txn_pct 0.00297, sebi_fee_pct 0.0001, stamp_duty_buy_pct 0.015, gst_pct 18.0, dp_charge_per_sell_inr 15.34, stcg_tax_pct 0.0. Portfolio: max_loss_pct_per_trade 1.0, max_concurrent_positions 12, max_total_portfolio_risk_pct 15.0, max_sector_exposure_pct 15.0. Backtest initial_equity 1,000,000. Universe: min_adtv_cr 25, min_listing_age_trading_days 252, min_market_cap_cr 5000 (PARKED, KI-001). **Sector rule (shared-rules):** a mapped symbol belongs to its sector in `data/reference/sector_map.csv`; every unmapped symbol is its own sector (`UNMAPPED:<SYMBOL>`), so the 15% cap never pools unmapped names. **Cost note:** a 5-session hold pays the round-trip costs on every trade, so costs weigh about eight times more per day held than for a 40-session hold; the gates are net of costs.

## 5. Data snapshot and view
`finsight.db`, sha256 `dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752`, last session 2026-10-16. The registered run uses `STOCKBOT_VIEW=memory` (the in-memory as-of view, proven to give byte-identical outputs to the SQL view: 0 differences over 444 real sessions, byte-identical 12-month research and baseline outputs on the merged code; `Claude_Docs/FAST-VIEW_REPORT.md`, `Claude_Docs/FAST-VIEW_FOLLOWUP_REPORT.md`). Each run manifest records `asof_view`.

## 6. Counts that inform the registration (counts only)
- Signals per session (from 2016-08-30, 2,511 sessions): median 11, p5 1, p95 72, max 287; 51,441 signal name-sessions; the top-25 cut binds on 628 sessions (25%).
- Occupancy model (12 slots, 5-session hold, a held symbol skipped), measured twice:

| | entries | per month |
|---|---|---|
| no sector cap | 4,659 | 39.0 |
| with the 15% sector cap, stage 1 (all unmapped symbols in ONE sector, one position at a time among them) | 3,786 | **31.7** (the registered `expected_trade_rate`) |
| with the 15% sector cap, new sector rule (every unmapped symbol its own sector) | 4,338 | **36.3** |

The registered `expected_trade_rate` stays 31.7 (the owner's decision); the re-count under the new rule is 36.3 a month, 4.6 above it, because unmapped names are no longer pooled (sector blocks fall from 19,628 to 5,658; sessions at the 12-position limit rise from 99 to 225). The model ignores stops (more entries) and the risk cap, costs, gap-up cap and fill blocks (fewer). Expected trades over the window: about 3,800 (stage-1 rule) to 4,300 (new rule); near_52w_high: 786.
- Concentration (uncapped): 828 distinct symbols; largest 0.6% of entries; top-10 share 5.3%. With the new sector rule and the cap: 886 distinct symbols.
- Nifty regime (close vs its 200-session average, 198 of 200 needed): 81.5% of signal name-sessions fall with the Nifty ABOVE its average, 18.5% below, none in the 163 undefined sessions.
- Clustering: the busiest 10% of sessions hold 41% of the signal name-sessions; on Nifty days down 1% or more (10% of sessions) the median is 29 signals a session against 11 on other days, and 21% of all signals fall on those days.
- Data quality: 3,161 signal name-sessions have a split or bonus inside the 250-bar window (adjusted by the engine); 2,220 have a demerger, merger, rights or OTHER action inside it (NOT adjusted by the engine), which can fake a pullback; no guard is proposed.
- Runtime: a full registered run is expected at about 55 minutes on the in-memory view (the SQL view is several hours); to be measured, not promised.

## 7. Baselines (as in FAMILY.md; same for every member)
- **B1:** matched-random entries at trade level through the shared simulator (`draw_matched_random`): **20 draws per actual trade**, at least 10 filled, **seed 20261111**, same eligibility, same `fixed_hold_5` exit and same relative stop (8% below the entry reference).
- **B2:** the Nifty matched to the strategy's own daily invested share, the rest at the shared risk-free rate (6.5%); the member's idle cash is credited at the same rate after the fact; the annualised, **pre-tax, cash-credited** alpha feeds the alpha gate (`stockbot/validation/benchmark_alpha.py`).
- No full-engine random replicates.

## 8. Tests (family procedure, `scripts/validate_family.py --expect-k 2`)
- **T1 (decision test):** per member, D(m) = sum over trades entered in month m of (actual net R minus the mean net R of that trade's random draws); the **K = 2** monthly series tested together with ONE Westfall-Young step-down Max-T (one-sided, family-wise 0.05, **B = 10,000**, studentized circular block bootstrap, the same block draw for both series, seed 20261111), **block lengths 2 and 3 months; BOTH must be significant** (adjusted p at most 0.05 at both).
- **T2:** paired statistics, reported only. **T3:** placebo size check of the joint procedure (limits 0.025 to 0.075; outside is "size unreliable", the owner decides, nothing is recalibrated).
- With about 4,000 trades and a 5-day hold the monthly series has many trades per month, but trades cluster in sell-off days (section 6) and are correlated: the effective sample is smaller than the nominal one. No power figure is computed here.

## 9. Validation gates (`validation_gates`, shared; read at run time)
Gates hash (`stockbot.validation.prereg_lock.gates_hash` of the shared gates, computed on this branch): **`e9b6407f908ff102dd25d9bc3b21a78a52b24c0ea082bba2cd3bb08f81188054`**.
| gate | value | note |
|---|---|---|
| min_trades | 40 | far above the floor at about 4,000 expected |
| min_expectancy_r | 0.15 | point estimate |
| min_profit_factor | 1.3 | point estimate |
| max_drawdown_pct | 20.0 | **backtest 20.0 versus paper 12.0**: a pass here can still fail 12% in paper |
| min_alpha_pct | 0.0 | annualised, **pre-tax**, member's idle cash credited at the risk-free rate, against the matched Nifty |
KI-002: gates stated as point estimates do not account for sampling error; the registered rule is T1 AND all gates on point estimates, as for near_52w_high.

## 10. Decision rule
DEMONSTRATED only if T1 finds the member (adjusted p at most 0.05 at BOTH block lengths, 2 and 3 months) AND every shared gate is met on its point estimate; otherwise "NOT DEMONSTRATED (registered rule not met; this is not evidence of no edge)". Status stays `research` whatever the outcome.

## 11. Output layout of the registered run (member directory for `validate_family.py`)
`docs/strategies/pullback_uptrend/results_run1/` holds `run/` (manifest.json, trades.json, equity_curve.json, daily.json, blocked.json), `baseline/` (actual_trades.csv, baseline_draws.csv, baseline_meta.json), `benchmark.json` and `gates.json`. Exact commands: `docs/strategies/pullback_uptrend/RUN_COMMANDS.md`.

## 12. Limitations
- No signals before 2016-08-30; the first 163 sessions of the window are empty.
- **Sector map:** 913 of 1,385 ever-eligible symbols are unmapped. Each is its own sector, so the sector cap does not limit concentration among them (it limits only the mapped sectors).
- **No dividends** in the lake: price returns only, for the strategy, the baselines and the Nifty benchmark.
- **No historical ASM/GSM** exclusion (KI-003); EQ-only lake (gaps).
- **Unadjusted demerger, merger, rights and OTHER actions** inside the window can fake a pullback (2,220 signal name-sessions in the counts study); no guard.
- **The registered run uses `STOCKBOT_VIEW=memory`**, proven byte-identical to the SQL view (see section 5); the SQL view is not re-run for this strategy.
- Occupancy numbers are a counts model, not a forecast of engine trades; the stage-1 31.7 and the new-rule 36.3 a month differ (section 6).
- Strongly clustered signals (sell-offs), a short hold and real costs: the net edge per trade is the open question; nothing about it has been looked at.
- Exact RSI ties are rare (no rounding); the ADTV tie-break seldom matters.

## 13. Registration (family route; NOT run; the owner writes it on master)
```
register_family(path=<family_ledger.csv>, family_id="family_batch1",
                members=[<spec hash of short_term_reversal>, "81db6427ebc9e11980c2cbbfb86720c7e1e68eeb27073b05c95cc64ce4207044"],   # TWO specs, K = 2
                gate_params=<dataclasses.asdict(load_shared_config().validation_gates)>,                                        # gates_sha256 e9b6407f...8054
                git_sha="<COMMIT SHA OF THE APPROVED PRE-REGISTRATION>", reason="family_batch1 K=2")
```
(exact keyword form per `stockbot/validation/ledger/__init__.py`; one row for both members, budget 2.) After the two registered runs, their B1 and B2:
```
py scripts/validate_family.py --member short_term_reversal=<DIR> --member pullback_uptrend=docs/strategies/pullback_uptrend/results_run1 --expect-k 2 --lake <finsight.db> --out-json <FILE>
```
then one `record_family_results` row carrying a result for each of the two members.

## 14. Decisions still needed from the owner
1. Register the family on master (K = 2) once both members' pre-registrations are final.
2. Note the new-rule trade rate (36.3 a month against the registered 31.7) before registering; the registered figure is unchanged.
