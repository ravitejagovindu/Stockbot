# riskadj_momentum: pre-registration (FINAL TEXT, NOT YET REGISTERED)

Stage-1 draft 2026-11-15, final text at stage 2 (2026-11-15). **Nothing in this file has been registered in any ledger; it takes effect only when the owner registers the family on master at the commit that carries this text.** No return, P&L, win rate or forward price of this strategy has been computed or looked at: the only measurements are the stage-1 counts (`docs/strategies/riskadj_momentum/counts/`) and test results on fixture lakes. The strategy is the single member of `family_batch2` (K = 1); its registration is the owner's `FAMILY_REGISTRATION` row on master, not a row written from this branch. **Final spec hash: `72dbec2c3da600cfe6de049a64efd530171ef2f539075f53e57a05e972ef27dc`.**

## Owner decisions (fixed)
- Every rule number below, `smallest_edge_of_interest` 0.15, window **2016-01-01 to 2026-10-16** (kept, with its 11 empty months), K = 1, Max-T B = 10,000 with blocks 2 and 3 months (both significant), B1 20 draws per trade with seed 20261111, gates hash e9b6407f...8054.
- `expected_trade_rate` **1.9** a month (confirmed; section 6 holds the slot arithmetic).
- B1 is a strategy-side script with its own draw loop; every random entry gets the SAME rule on its own symbol (section 7). The readings of the ambiguous rules in the stage-1 report (own-bar t-21 and t-252, 252-bar ATR) are accepted. The power section (9) is accepted as stated.
- **End-of-window rule (fixed before any result): section 7a.**

## 1. What would be registered
One strategy, one configuration, one backtest run, one decision, in a K = 1 family. No parameter sweep, no variants, no second run unless a bug is found (then it is a new trial and needs a new approval).

## 2. The rule and parameters (exactly the spec)
`stockbot/strategies/riskadj_momentum/strategy.py`, `SPEC` at the registered commit:
- id `riskadj_momentum`, version `1.0.0`, status `research`, exit_policy `trailing_atr3_floor8` (strategy-owned, `exits.py`), universe_overrides `{}`, overlays `{}`, validation_ref empty; `expected_trade_rate` 1.9, `smallest_edge_of_interest` 0.15, `prereg_ref` this file.
- params `{"ret_long": 252, "ret_skip": 21, "min_closes": 240, "top_n": 25, "atr_period": 14, "atr_mult": 3.0, "stop_floor": 0.08, "tie_adtv_sessions": 20}`.
- **Spec hash at this stage-1 commit: `72dbec2c3da600cfe6de049a64efd530171ef2f539075f53e57a05e972ef27dc`** (`SPEC.config_hash()`; covers every spec field, the trade rate included). The registration commit records it again; it changes if any spec field is changed first.
- Universe: shared `universe.eligibility`, no overrides.
- Signal sessions: the first trading session of each calendar month (its (year, month) differs from the previous session's); no other session proposes anything.
- Per symbol on a signal session: a bar on the signal session; at least 240 adjusted closes among the last 252 Nifty-calendar sessions ending at it; 253 adjusted bars of its own (t-21 and t-252 are positions 21 and 252 before its last own bar, i.e. the BARS of the symbol, not calendar sessions: with no gaps they coincide).
- ret = adjusted close[t-21] / adjusted close[t-252] - 1, required > 0 (strict). vol = sample standard deviation (ddof 1) of the daily log returns of the symbol's consecutive adjusted closes from t-252 through t-21 (231 returns without gaps), required > 0. score = ret / vol.
- Order: score descending; exact ties by higher raw 20-session ADTV; then symbol. The first 25 are proposed with an explicit ordinal rank 25 down to 1.
- ATR14: Wilder ATR (`stockbot.data.indicators.atr`, true range max(H-L, |H-prevC|, |L-prevC|), seed = mean of the first 14 true ranges, then (avg x 13 + TR) / 14) on the adjusted high, low and close of the symbol's last 252 bars up to the session (hand-computed test, independent recursion test).
- Entry: the engine's next-open fill. **Initial stop = signal close - max(3 x ATR14, 0.08 x signal close).** Long only; no regime filter; no target; no overlay.
- Exit `trailing_atr3_floor8`: reference = highest close since entry (seeded with the entry fill price); each session `stop = max(previous stop, reference - max(3 x ATR14 of that session, 0.08 x reference))`; the stop set on bar T applies from bar T+1; it starts at the strategy's initial stop; it never moves down; no time exit; state `{"highest_close"}` rescaled on corporate actions. The engine's usual rules apply (gap below the stop fills at the open, etc.). Exit policies: `docs/exit_policies/EXIT_POLICIES.md`.

## 3. Window and sub-periods
- **2016-01-01 to 2026-10-16.** The calendar starts 2015-11-09, so a 252-session window first exists in late 2016: **the first signal can occur on 2016-12-01; the 11 signal months of 2016-01 to 2016-11 are empty by the rule's own definition** (counts). Effectively 119 signal months (2016-12 to 2026-10).
- Two DESCRIPTIVE sub-period reports (as for the other members): 2016 to 2019 and 2020 to 2026-10-16, by entry date; never used to select, change or stop anything.

## 4. Execution, cost and risk settings in force (shared, not overridable)
Read from `config/shared.yaml` at run time: entry_fill NEXT_OPEN; entry_slippage_pct 0.10; exit_slippage_pct 0.10; max_entry_gap_up_pct 3.0. Costs: stt_buy_pct 0.10, stt_sell_pct 0.10, brokerage 0, exchange_txn_pct 0.00297, sebi_fee_pct 0.0001, stamp_duty_buy_pct 0.015, gst_pct 18.0, dp_charge_per_sell_inr 15.34, stcg_tax_pct 0.0. Portfolio: max_loss_pct_per_trade 1.0, max_concurrent_positions 12, max_total_portfolio_risk_pct 15.0, max_sector_exposure_pct 15.0. Backtest initial_equity 1,000,000. Universe: min_adtv_cr 25, min_listing_age_trading_days 252, min_market_cap_cr 5000 (PARKED, KI-001). Sector rule: a mapped symbol belongs to its sector in `data/reference/sector_map.csv`; every unmapped symbol is its own sector (`UNMAPPED:<SYMBOL>`). **Consequence of the stop rule:** a position's value is 1% of equity divided by the stop distance, so an 8% stop is a 12.5% position and a 12% stop an 8.3% position (counts: mean 8.8% of equity); with a 15% sector cap at most one position per mapped sector fits whenever positions exceed 7.5% of equity.

## 5. Data snapshot and view
`finsight.db`, sha256 `dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752`, last session 2026-10-16. The registered run would use `STOCKBOT_VIEW=memory` (byte-identical to the SQL view: `Claude_Docs/FAST-VIEW_REPORT.md`); each run manifest records `asof_view`. The counts below were produced on the memory view (332 s for 130 signal sessions); the strategy's tests assert SQL = memory on a fixture.

## 6. Counts that inform the registration (counts only; no forward price read)
Study: `scripts/signal_count_riskadj_momentum.py`; results `docs/strategies/riskadj_momentum/counts/summary.json` and `monthly_counts.json`; spec hash as in section 2.
- **Signal months: 130** (2016-01-01 to 2026-10-01). Shared-eligible names per signal month: median 274.5 (min 125, max 635).
- **Funnel over all 130 months (name-months):** fewer than 253 own bars 1,640; fewer than 240 closes in the window 1,048; no bar on the signal date 0; non-positive or non-finite price 0; ret <= 0 12,580; vol <= 0 0; ATR missing 0; qualifying 25,715 (2 of them have a stop at or below zero and are unusable).
- **Candidates per month:** the 11 months 2016-01 to 2016-11 have none (all eligible names are 'short': the calendar window does not exist yet). The other 119 months have a median of 188 qualifying (min 34, max 534). **Fewer than 25 qualify in 11 months (all the empty ones) and in no month after 2016-11.** Mean by year: 2016 10, 2017 160, 2018 137, 2019 74, 2020 89, 2021 270, 2022 186, 2023 258, 2024 461, 2025 257, 2026 290.
- **Score ties:** none in 25,713 qualifying name-months (0 tie groups, none at the cut); the ADTV tie-break never fires on the real lake.
- **Own-bar offsets versus the calendar:** the symbol's own bar t-252 differs from the calendar's session t-252 for 131 of 25,713 qualifying name-months (0.5%).
- **Sector spread of the top 25** (2,975 name-months): 76.8% mapped, 23.2% UNMAPPED; distinct mapped sectors per month median 7.5; the largest same-sector group in a month has a median of 6 names (max 12); 63.1% of top-25 names share a mapped sector with another top-25 name that month.
- **Initial stop distance (top 25):** median 11.9% of the close, p5 8.0%, p95 19.4%, max 43.6%; **16.0% of names sit at the 8% floor** (3 x ATR below 8%), 84.0% are set by the ATR. **Implied position size** (1% risk / distance): median 8.4% of equity, mean 8.8%, p5 5.2%, p95 12.5%.
- **Overlap of each month's top 25 with the previous month's** (118 pairs): mean 15.5 names (62.2%), median 16, range 10 to 22.
- **Overlap with near_52w_high:** 41.7% of the top-25 name-months were also near_52w_high candidates (that strategy's own rule, every candidate counted) that session; its candidate count has a median of 60.5.
- **Expected trade rate (slot arithmetic, no forward prices).** Concurrent positions are bounded by the 12-position limit and by capital: mean position 8.8% of equity gives 100 / 8.8 = **11.4** positions. In steady state entries a month = slots / average hold in months (an entry replaces an exit; the first months fill the book):

| assumed average hold | entries a month | with slots freed mid-month idle until the next signal session (hold + 0.5 month) | entries over the 119 signal months |
|---|---|---|---|
| 4 months | 2.85 | 2.53 | about 339 (301) |
| 6 months (proposed) | 1.90 | 1.75 | about 226 (209) |
| 8 months | 1.42 | 1.34 | about 170 (160) |

**Proposed `expected_trade_rate` = 1.9** (the 6-month hold, between the two stated assumptions). The holds are assumptions: the real hold depends on the trailing stop and on prices after the signals, which were not looked at. The model ignores the sector cap (which can lower entries when the top names share sectors), the risk and cash caps beyond the capital bound, costs, gap-up blocks and fill blocks.

## 7. Baselines
- **B1:** matched-random entries at trade level: **20 draws per actual trade**, at least 10 filled, **seed 20261111**, drawn on the trade's signal session from the shared-eligible pool (never the trade's own symbol, no pool filter), same fill, slippage, gap rule, corporate-action rebasing, stepping, costs and exit policy `trailing_atr3_floor8`. **Every random entry gets the same stop rule as the strategy, on its own symbol:** initial stop = signal close - max(3 x ATR14, 0.08 x signal close), with ATR14 the symbol's own Wilder ATR over its last 252 adjusted bars up to that session (as-of view), and the trailing exit then runs on the random symbol's own prices. It is NOT the actual trade's relative distance (the shared helper `draw_matched_random` does that, so it is not used for the registered run). The draw loop is the strategy-side `draw_matched_random_own` in `scripts/baseline_matched_random_riskadj_momentum.py`, a copy of the shared loop with the stop rule and the end-of-window closure as parameters; a test proves that with the shared helper's stop rule it returns the shared helper's rows exactly (same seed, same draws), so the copy cannot drift. A draw whose ATR is unavailable or whose stop would be at or below zero is not filled (`NO_STOP`, counted). A pair needs 10 filled draws; more than 5% of trades losing their pair flags the result.
- **B2:** the Nifty matched to the strategy's own daily invested share, the rest at the shared risk-free rate (6.5%); the member's idle cash credited at the same rate; the annualised, pre-tax, cash-credited alpha feeds the alpha gate (`stockbot/validation/benchmark_alpha.py`).
- No full-engine random replicates.

## 7a. End-of-window rule (fixed now, before any result)
Positions still open after the last session of the window (2026-10-16) are **closed at that session's close**, with the normal exit slippage (0.10%) and the normal sell costs, exit reason `END_OF_WINDOW`, and they **count as usable trades** in the gates (min_trades, expectancy, profit factor), in T1 and in T2. The same holds for random draws: a draw still open at the window end is closed at the last close with the same slippage and costs and **counts as filled**. The shared runner already closes the strategy's own open positions this way; what changes is that they are not dropped from the statistics. Implemented in the strategy-side scripts only, shared code untouched: in `trades.json` (the file the shared gate code reads) such a trade carries `exit_reason` `END_OF_WINDOW_COUNTED` because the shared gate code treats the exact string `END_OF_WINDOW` as "not usable"; the engine's own label is kept in `exit_reason_engine`, and `end_of_window` is true. `actual_trades.csv` and `baseline_draws.csv` carry an `end_of_window` column. **The numbers of such trades and of such draws are reported separately in every output**: the research log line and `run/manifest.json` (`end_of_window.trades`), `baseline/baseline_meta.json` (`end_of_window_trades`, `end_of_window_draws`, `draws_closed_before_window_end`) and the gates output (`counts.end_of_window_counted_as_usable`, `counts.baseline_end_of_window_draws` with `--baseline-dir`). `validate_family.py` is shared and does not print them; its member counts include these trades. Consequence to read with the results: a position closed at the window end has an arbitrary, unfinished holding time, so the last months of the window contribute partly unfinished trades to every statistic; the actual trades and their random draws are treated alike.

## 8. Tests (family procedure, K = 1: `scripts/validate_family.py --expect-k 1`)
- **T1 (decision test):** D(m) = sum over trades entered in month m of (actual net R minus the mean net R of that trade's random draws); the K = 1 monthly series tested with the Westfall-Young Max-T step-down (one-sided, family-wise 0.05, **B = 10,000**, studentized circular block bootstrap, seed 20261111), **block lengths 2 and 3 months; BOTH must be significant** (adjusted p at most 0.05 at both). With K = 1 the Max-T correction is the single test.
- **T2:** paired statistics, reported only. **T3:** placebo size check (limits 0.025 to 0.075; outside is "size unreliable", the owner decides, nothing is recalibrated).

## 9. Power (assumptions, labelled; not measured)
T1 tests the monthly mean of D(m). With about 119 signal months and about 1.9 entries a month (about 226 trades; 170 to 339 at the 8 and 4 month holds), a one-sided test at 5% with 80% power detects a true mean excess of `(1.645 + 0.842) x sigma / sqrt(n_eff)` net R per trade, where sigma is the standard deviation of (actual net R minus the mean random-draw net R) of a trade and n_eff the effective number of trades. **ASSUMPTIONS (nothing here was measured):** sigma of 1.0, 1.5 or 2.0 R (a trailing stop with a 3-ATR distance leaves a long right tail), and a design effect of 1.0 (independent trades) or 1.5 (trades entered on the same month start are correlated; momentum names cluster in sectors and in time).

| trades (hold) | sigma R | design effect | detectable edge at 80% power (R per trade) | power at the edge of interest 0.15 R |
|---|---|---|---|---|
| 226 (6 months) | 1.0 | 1.0 | 0.17 | 73% |
| 226 | 1.5 | 1.0 | 0.25 | 44% |
| 226 | 1.5 | 1.5 | 0.30 | 34% |
| 226 | 2.0 | 1.5 | 0.41 | 23% |
| 339 (4 months) | 1.5 | 1.0 | 0.20 | 58% |
| 339 | 1.5 | 1.5 | 0.25 | 44% |
| 170 (8 months) | 1.5 | 1.0 | 0.29 | 37% |
| 170 | 1.5 | 1.5 | 0.35 | 28% |

Under these assumptions an edge of 0.15 R is detectable only if sigma is about 1 R or below; at 1.5 R the test has under 45% power at 0.15 R, and T1 must hold at BOTH block lengths, which lowers the power further. The gate `min_expectancy_r` 0.15 is a point estimate with no such protection.

## 10. Validation gates (`validation_gates`, shared; read at run time)
Gates hash (`stockbot.validation.prereg_lock.gates_hash`): **`e9b6407f908ff102dd25d9bc3b21a78a52b24c0ea082bba2cd3bb08f81188054`**.
| gate | value | note |
|---|---|---|
| min_trades | 40 | well below the roughly 170 to 340 expected |
| min_expectancy_r | 0.15 | point estimate |
| min_profit_factor | 1.3 | point estimate |
| max_drawdown_pct | 20.0 | backtest 20.0 versus paper 12.0 |
| min_alpha_pct | 0.0 | annualised, pre-tax, idle cash credited at the risk-free rate, against the matched Nifty |
KI-002: point-estimate gates do not account for sampling error; the registered rule is T1 AND all gates on point estimates.

## 11. Decision rule
DEMONSTRATED only if T1 finds the member (adjusted p at most 0.05 at BOTH block lengths, 2 and 3 months) AND every shared gate is met on its point estimate; otherwise "NOT DEMONSTRATED (registered rule not met; this is not evidence of no edge)". Status stays `research` whatever the outcome.

## 12. Limitations
- Same as the pullback_uptrend pre-registration: no signals before the first full 252-session window (here 2016-12-01); sector map incomplete (each unmapped symbol its own sector, so the cap does not limit concentration among them); no dividends in the lake (price returns only for the strategy, the baselines and the Nifty); no historical ASM/GSM exclusion (KI-003); EQ-only lake; unadjusted demerger, merger, rights and OTHER actions inside the 252-session lookback can distort the 12-1 return and the volatility (no guard; not counted at this stage); the registered run uses the memory view; occupancy numbers are a counts model, not a forecast.
- **Trades and draws open at the window end are closed at the last close and counted** (section 7a). Their holding time is unfinished and their number is not known in advance (a trailing-stop strategy with holds of several months has many); the last months of the window therefore enter the statistics as partly unfinished trades, for the actual trades and for the random draws alike.
- **Slots freed mid-month stay in cash until the next signal session**: a stop-out on the 5th leaves the slot idle for about a month; the invested share is lower than a daily-rebalanced book would have.
- **Entry months cluster on month starts**: every entry of a month happens on the same one or two days, so the monthly D(m) series has few independent observations per month and trades are correlated; the effective sample is smaller than the nominal one.
- The hold is set by the stop, not by a time limit, so the number of trades depends on the (unobserved) price paths; the trade rate in section 6 is an assumption-driven model.
- Rank is by past risk-adjusted return only; no market-regime filter, no overlay.

## 13. Registration (family route; NOT run; the owner writes it on master)
```
register_family(path=<family_ledger.csv>, family_id="family_batch2",
                members=["72dbec2c3da600cfe6de049a64efd530171ef2f539075f53e57a05e972ef27dc"],                      # ONE spec, K = 1
                gate_params=<dataclasses.asdict(load_shared_config().validation_gates)>,                           # gates_sha256 e9b6407f908ff102dd25d9bc3b21a78a52b24c0ea082bba2cd3bb08f81188054
                git_sha="<COMMIT SHA OF THE APPROVED PRE-REGISTRATION>", reason="family_batch2 K=1")
```
(keyword form per `stockbot/validation/ledger/__init__.py`.) The registered run uses `STOCKBOT_VIEW=memory` (`docs/strategies/riskadj_momentum/RUN_COMMANDS.md`, output folder `docs/strategies/riskadj_momentum/results_run1/`). After the run and its B1 and B2: `py scripts/validate_family.py --member riskadj_momentum=docs/strategies/riskadj_momentum/results_run1 --expect-k 1 --lake <finsight.db> --out-json <FILE>`, then one `record_family_results` row.

## 14. Decisions still needed from the owner
None open in this text. The owner registers `family_batch2` (K = 1) on master at the commit that carries this text and then authorises the registered run.
