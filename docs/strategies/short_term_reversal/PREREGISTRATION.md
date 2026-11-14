# short_term_reversal: pre-registration (DRAFT, NOT REGISTERED)

Stage-1 draft 2026-11-12; finalised at stage 2 (2026-11-14) with the owner's decisions below. **Nothing in this file has been registered in any ledger; it stays DRAFT until the owner registers the family on master.** No return, P&L, win rate or forward price change of this strategy has been computed or looked at. The only measurements are counts (`docs/strategies/short_term_reversal/results_stage1/counts.md`, measured 2026-11-12, and the stage-2 re-count under the new sector rule `results_stage2/counts_new_sector_rule.md`), the power arithmetic of section 9, and test results. The strategy is a member of family_batch1 (K = 2: `short_term_reversal`, `pullback_uptrend`; `docs/strategies/family_batch1/FAMILY.md`); its registration is the owner's single `FAMILY_REGISTRATION` row on master, not a row written from this branch.

## 0. Owner decisions (final, stage 2)
- Rule numbers unchanged from stage 1: ret5 band -0.30 to -0.07 (both ends inclusive), `min_bars` 10, `top_n` 25, stop 0.92 x signal close, exit `fixed_hold_5`.
- The stage-1 readings of the edge cases are accepted: a name needs a bar exactly 5 sessions back (no anchor bar, no signal); ret5 is computed on adjusted closes; exactly -7% and exactly -30% are inside the band.
- `expected_trade_rate` = **23.0** a month (unchanged). `smallest_edge_of_interest` = **0.15** R per trade net of costs. `prereg_ref` = `docs/strategies/short_term_reversal/PREREGISTRATION.md`.
- Window for BOTH family members: **2016-01-01 to 2026-10-16**.
- Family `family_batch1`, **K = 2**, joint Westfall-Young Max-T.
- The occupancy model under the registered sector rule (every unmapped symbol its own sector) gives **25.63** a month, not 23.0; the registered `expected_trade_rate` stays 23.0 (section 11).

## 1. What is registered
One strategy, one configuration, one backtest run, one decision, inside a K = 2 family corrected jointly by Max-T. No parameter sweep, no variants; any second run is a new trial and needs a new approval.

## 2. The rule and parameters (exactly the spec)
`stockbot/strategies/short_term_reversal/strategy.py`, `SPEC` at the registered commit:
- id `short_term_reversal`, version `1.0.0`, status `research`, exit_policy `fixed_hold_5`, universe_overrides `{}`, overlays `{}`, validation_ref empty, `expected_trade_rate` 23.0, `smallest_edge_of_interest` 0.15, `prereg_ref` `docs/strategies/short_term_reversal/PREREGISTRATION.md`.
- params `{"lookback_sessions": 5, "min_bars": 10, "ret_floor": -0.30, "ret_cap": -0.07, "top_n": 25, "stop_fraction": 0.92, "tie_adtv_sessions": 20}`.
- Universe: shared `universe.eligibility`, no overrides.
- Data: at least `min_bars` (10) own bars, a bar on the signal date, and a bar on the session 5 calendar sessions earlier (Nifty calendar); a name without that anchor bar is not a signal.
- ret5 = adjusted close[t] / adjusted close[t-5 sessions] - 1, point-in-time as-of basis (`AsOfView.adjusted_bars`), rounded to 12 decimals. Signal: -0.30 <= ret5 <= -0.07, both ends inclusive. The floor guards against unadjusted corporate-action artifacts.
- Order: ret5 ascending (deepest fall first); ties by higher raw 20-session ADTV; then symbol. The first 25 are proposed with an explicit ordinal rank (25 down to 1).
- Entry: the engine's next-open fill. Stop: 0.92 x the signal-day adjusted close. Exit: `fixed_hold_5` (entry session is session 1, a market exit at the open of session 6, five closes held) or the stop, whichever is first. Long only; no regime filter; no target.
- **Spec hash at the stage-2 commit: `57b86c47d0c5cbdc1325e19230c103b84bc08c6be6b495aadb99d1aa84ec6168`** (`SPEC.config_hash()`, recomputed in this session; it covers every spec field, `prereg_ref`, the trade rate and the edge included). The registration commit records the hash again; it must equal this one unless a spec field is changed first.
- **Shared validation_gates hash: `e9b6407f908ff102dd25d9bc3b21a78a52b24c0ea082bba2cd3bb08f81188054`** (section 10).

## 3. Window and descriptive sub-periods
- **Registered run:** 2016-01-01 to 2026-10-16, one run (the family window; `validate_family.py` refuses members with different windows). The TEST/TUNE labels in `shared.yaml` do not apply: nothing is tuned.
- Two DESCRIPTIVE sub-period reports, 2016-01-01 to 2019-12-31 and 2020-01-01 to 2026-10-16 (trades by entry date): reported, never used to select, change or stop anything, no pass or fail.

## 4. Execution, cost and risk settings in force (shared, from `stockbot/config/shared.yaml`, not overridable)
entry_fill NEXT_OPEN; entry_slippage_pct 0.10; exit_slippage_pct 0.10; max_entry_gap_up_pct 3.0. Costs: stt_buy_pct 0.10, stt_sell_pct 0.10, brokerage 0.0, exchange_txn_pct 0.00297, sebi_fee_pct 0.0001, stamp_duty_buy_pct 0.015, gst_pct 18.0, dp_charge_per_sell_inr 15.34, stcg_tax_pct 0.0. Portfolio: max_loss_pct_per_trade 1.0, max_concurrent_positions 12, max_total_portfolio_risk_pct 15.0, max_sector_exposure_pct 15.0. Initial equity 1,000,000. Universe: min_adtv_cr 25, min_listing_age_trading_days 252, min_market_cap_cr 5000 (PARKED, KI-001).
**Sector rule (shared-rules):** a mapped symbol belongs to its sector in `data/reference/sector_map.csv`; every unmapped symbol is its own sector (`UNMAPPED:<SYMBOL>`), so the 15% cap never pools unmapped names.
**What these mean for this rule (arithmetic):** the 8% stop gives a position of 12.5% of equity, so the 15% sector cap allows ONE position per mapped sector and cash allows at most 8 positions; the cash cap, not the 12-position cap, binds. Round-trip friction is about 0.43% of position value (0.2% slippage, 0.2% STT, about 0.03% other), about 0.05 R at an 8% stop, against the 0.15 R edge of interest.

## 5. Data snapshot and view
`finsight.db`, sha256 `dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752`, last session 2026-10-16. Re-checked at every stage; if it differs at the registered run the run does not start. **The registered run uses `STOCKBOT_VIEW=memory`** (the in-memory as-of view), proven to give byte-identical outputs to the SQL view (0 differences over 444 real sessions; byte-identical 12-month research and baseline outputs on merged code; `Claude_Docs/FAST-VIEW_REPORT.md`, `Claude_Docs/FAST-VIEW_FOLLOWUP_REPORT.md`). Every run manifest and baseline meta records `asof_view`.

## 6. The run
One run, `scripts/research_short_term_reversal.py --execute`, window of section 3, shared config, exit policy from the spec (built by `run_backtest` from the spec), the shared `SectorLookup`, no ASM/GSM ranges for the historical window (limitation 1). Output layout and exact commands: `docs/strategies/short_term_reversal/RUN_COMMANDS.md`; member directory `docs/strategies/short_term_reversal/results_run1/` (`run/`, `baseline/`, `benchmark.json`, `gates.json`). The wiring is proven on fixture lakes only (`tests/unit/test_research_short_term_reversal.py`, `tests/unit/test_short_term_reversal_validation_scripts.py`).

## 7. Baselines (family rules)
- **B1:** matched-random entries at trade level through the shared simulator (`draw_matched_random`): **20 draws per actual trade**, at least 10 filled, **seed 20261111**, same eligibility, same `fixed_hold_5` exit and same relative stop, no portfolio caps. Script `scripts/baseline_matched_random_short_term_reversal.py`.
- **B2:** the Nifty matched to the member's own daily invested share, the rest at the shared risk-free rate (6.5%); the member's idle cash is credited at the same rate after the fact; the annualised, **pre-tax, cash-credited** alpha feeds the alpha gate (`stockbot/validation/benchmark_alpha.py`). Script `scripts/benchmark_nifty_matched_short_term_reversal.py`.
- Design limits as for near_52w_high: the random draws are not subject to the slot, sector and cash caps; there is no random equity curve. For this rule the holds are short (5 sessions), so overlap between trades is small, but entries cluster on a few market-wide fall days (section 11).

## 8. Tests (family procedure, `scripts/validate_family.py --expect-k 2`)
- **T1 (decision test):** per member, D(m) = sum over trades entered in month m of (actual net R minus the mean net R of that trade's random draws); the **K = 2** monthly series tested together with ONE Westfall-Young step-down Max-T (one-sided, family-wise 0.05, **B = 10,000**, studentized circular block bootstrap, the same block draw for both series, seed 20261111), **block lengths 2 and 3 months; BOTH must be significant** (adjusted p at most 0.05 at both).
- **T2:** paired statistics, reported only. **T3:** placebo size check of the joint procedure (limits 0.025 to 0.075; outside is "size unreliable", the owner decides, nothing is recalibrated).
- Reported always for this member: trade count (closed, usable, excluded, END_OF_WINDOW), entries per month and year, invested share, sector-cap blocks, largest drawdown, profit factor, win rate, expectancy, the sub-periods of section 3.
- **Decision rule:** DEMONSTRATED only if T1 finds the member (adjusted p at most 0.05 at BOTH block lengths, 2 and 3 months) AND every shared gate is met on its point estimate; otherwise "NOT DEMONSTRATED (registered rule not met; this is not evidence of no edge)". Status stays `research` whatever the outcome.

## 9. Power (assumption-based, nothing measured)
Normal approximation as in near_52w_high section 9: SE = sd_pair / sqrt(n / DEFF); smallest edge at 80% power = (c + 0.842) x SE; c = 1.645 (ideal one-sided) or 2.2 (the effective value fitted to the F9 monthly dual-block rule). n = 2,931 nominal trades (the stage-1 model, 2016-2026; 3,263 under the new sector rule), sd_pair 0.9, 1.2 or 1.5 R, DEFF 1 to 3 (assumed; cannot be measured without looking at returns). The figures are single-test, so they are optimistic for a joint test (the critical value is higher), a little less so for K = 2 than for K = 4.

| sd_pair | DEFF | effective trades | smallest edge at 80% power, ideal c | dual-rule c | power at 0.15 R (ideal / dual) |
|---|---|---|---|---|---|
| 1.2 | 1 | 2931 | 0.055 | 0.067 | 1.00 / 1.00 |
| **1.2** | **2** | **1466** | **0.078** | **0.095** | **1.00 / 1.00** |
| 1.2 | 3 | 977 | 0.095 | 0.117 | 0.99 / 0.96 |
| 1.5 | 3 | 977 | 0.119 | 0.146 | 0.93 / 0.82 |
| 0.9 | 2 | 1466 | 0.058 | 0.072 | 1.00 / 1.00 |

In plain words: on these assumptions 0.15 R is detectable with high power at the nominal trade count. Three things pull the other way and are not in the table: trades are NOT independent (entries cluster on market-fall days: 659 of 2,710 sessions had more than 25 signals, the 10 worst market days carry 1.8% of all signals against 0.37% if spread evenly, so the DEFF could be larger than 3 in the monthly series); the monthly series that T1 uses has only about 130 points however many trades there are; and friction of about 0.05 R is paid on every trade. A non-significant result is "not demonstrated", never "no edge".

## 10. Validation gates (`validation_gates`, shared; read at run time)
Gates hash (`stockbot.validation.prereg_lock.gates_hash` of the shared gates): **`e9b6407f908ff102dd25d9bc3b21a78a52b24c0ea082bba2cd3bb08f81188054`**.
| gate | value | note |
|---|---|---|
| min_trades | 40 | far above the floor at about 3,000 expected |
| min_expectancy_r | 0.15 | point estimate |
| min_profit_factor | 1.3 | point estimate |
| max_drawdown_pct | 20.0 | **backtest 20.0 versus paper 12.0** (`paper_criteria.max_drawdown_pct` stays 12.0): a pass here can still fail 12% in paper |
| min_alpha_pct | 0.0 | annualised, **pre-tax**, member's idle cash credited at the risk-free rate (6.5%), against the matched Nifty |
KI-002: gates stated as point estimates do not account for sampling error; the registered rule is T1 AND all gates on point estimates, as for near_52w_high.

## 11. Counts that inform the registration (counts only; nothing about returns)
Measured 2026-11-12 (stage 1) over 2,710 sessions 2015-11-09 to 2026-10-16, finsight.db size and mtime unchanged: 59,055 signals 2016-2026 (median 10 a session; 658 of 2,674 sessions above 25); the 10 worst market days carry 1.8% of all signals; ties: 10 of 33,108 proposed names in a tie group, none straddling the cut; stop fit 8.00% against a 6.67% minimum (fits).

**Expected trade rate (mechanical occupancy model, 2016-2026; ignores stops, entry gaps, the gap-up cap and costs):**

| model | entries | per month |
|---|---|---|
| position cap only (`plain`) | 4,772 | 37.48 |
| + sector cap, stage 1 (unmapped symbols pooled in ONE sector) | 3,523 | 27.67 |
| + sector cap and cash (8 slots), stage 1: **registered `expected_trade_rate` 23.0** | 2,931 | **23.02** |
| + sector cap, new rule (each unmapped symbol its own sector) | 4,553 | 35.76 |
| + sector cap and cash (8 slots), new rule | 3,263 | **25.63** |

Under the new rule the sector cap blocks 1,350 candidates instead of 9,665, and the shared slots are full on 19.5% of sessions instead of 15.1%. The registered `expected_trade_rate` stays **23.0** (owner decision); the model under the registered sector rule gives **25.63**, 2.6 a month (11%) higher. The re-count was verified from the cached stage-1 candidate lists with no database read (`results_stage2/`); its sector figures are recomputed under the new rule (proposed names per session span a median of 8 sectors, most in one sector median 2; the largest mapped sector holds 14.9% of signals; 36.0% of signals are unmapped names).
Data quality: 204 signal-sessions have a demerger, merger, rights or OTHER action inside the 6-bar window (unadjusted by the engine) and 108 a split or bonus (adjusted); the floor dropped 574 name-sessions, 72 with a corporate action in the window; `no_anchor` 1,139 name-sessions.
No decision was taken from the counts: the rule's numbers are the owner's and were not changed.

## 12. Limitations
1. No historical ASM/GSM exclusion (KI-003); both the strategy and the baseline ignore it.
2. **Sector map:** 913 of 1,385 ever-eligible symbols are unmapped; each is its own sector, so the sector cap does not limit concentration among them (36.0% of signals are such names). Concentration is limited only by the 12.5% position size, the 8-slot cash limit and the mapped sectors' cap.
3. **No dividends** in the lake: price returns only, for the strategy, the baselines and the Nifty benchmark.
4. **Unadjusted corporate actions:** demerger, merger, rights and OTHER actions inside the window are not adjusted by the engine and can fake a fall (204 signal-sessions); only the -0.30 floor guards artifacts.
5. Entries whose next open gaps below the stop, and the 3% gap-up cap, block or skip trades; they could not be counted without a price after the signal. Fills after a big fall day are where this matters most.
6. **The registered run uses `STOCKBOT_VIEW=memory`**, proven byte-identical to the SQL view (section 5); the SQL view is not re-run for this strategy.
7. The market-cap gate is parked (KI-001); the random baseline has no portfolio effects.
8. `no_anchor` and the first five sessions of the lake produce no signal.
9. The counts study and the strategy share one implementation (`scan`, `order_candidates`); the study's Nifty move is an index measure, not a return of the strategy.
10. Strongly clustered entries (market-fall days), a short hold and real costs: the net edge per trade is the open question; nothing about it has been looked at.

## 13. Registration (family route; NOT run; the owner writes it on master)
```
register_family(path=<family_ledger.csv>, family_id="family_batch1",
                members=["57b86c47d0c5cbdc1325e19230c103b84bc08c6be6b495aadb99d1aa84ec6168", <spec hash of pullback_uptrend>],   # TWO specs, K = 2
                gate_params=<dataclasses.asdict(load_shared_config().validation_gates)>,                                        # gates_sha256 e9b6407f...8054
                git_sha="<COMMIT SHA OF THE APPROVED PRE-REGISTRATION>", reason="family_batch1 K=2")
```
(exact keyword form per `stockbot/validation/ledger/__init__.py`; one row for both members, budget 2.) After the two registered runs, their B1 and B2:
```
py scripts/validate_family.py --member short_term_reversal=docs/strategies/short_term_reversal/results_run1 --member pullback_uptrend=<pullback_uptrend member dir> --expect-k 2 --lake <finsight.db> --out-json <FILE>
```
then one `record_family_results` row carrying a result for each of the two members. (The `--expect-k 2` and the two `--member` entries are the registered family size.)

## 14. Run-time plan
Registered run on the memory view: about 55 minutes for an engine-only full-window run of near_52w_high (measured); this member's own timing and its baseline (about 3,000 trades, 20 draws each) are to be measured, not promised; the baseline will take longer than near_52w_high's 22 minutes. Up to 16 minutes extra for a cold read of the lake file; about 1 GB per process; at most two runs at once.

## 15. Decisions still needed from the owner
1. Register the family on master (K = 2) once both members' pre-registrations are final.
2. Note the model's 25.63 a month against the registered 23.0 before registering (no change made).
