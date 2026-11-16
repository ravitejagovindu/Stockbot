# lowvol_uptrend: pre-registration (FINAL TEXT, NOT YET REGISTERED)

Final text 2026-11-16. **Nothing in this file has been registered in any ledger; it takes effect only when the owner registers the family on master at the commit that carries this text.** No return, P&L, win rate or forward price of this strategy has been computed or looked at: the only measurements are the counts (`docs/strategies/lowvol_uptrend/counts/`) and test results on fixture lakes. The strategy is the single member of `family_batch3` (K = 1); its registration is the owner's `FAMILY_REGISTRATION` row on master, not a row written from this branch. **Final spec hash: `52e7ee3ccc2e150d7e4b6b54266bb2c73a8788612691ece475bfa7d1bb0e9e68`.**

## Owner decisions (fixed)
- Every rule number below, `smallest_edge_of_interest` 0.15, window **2016-01-01 to 2026-10-16** (kept, with its 11 empty months), K = 1, Max-T B = 10,000 with blocks 2 and 3 months (both significant), B1 20 draws per trade with seed 20261111, gates hash e9b6407f...8054.
- `expected_trade_rate` **1.3** a month (proposed from the slot arithmetic of section 6; the owner confirms or overrules it by registering).
- B1 is a strategy-side script with its own draw loop; every random entry gets the SAME stop rule and exit policy on its own symbol (section 7). The readings of the ambiguous rules in `BRIEF.md` (252 returns from 253 own closes; calendar-window SMA and presence counts) are the build's reading, stated for the owner.
- **End-of-window rule (fixed before any result): section 7a.** Shared defaults as on master: symbol links on, stale exit after 20 sessions (section 7b).

## 1. What would be registered
One strategy, one configuration, one backtest run, one decision, in a K = 1 family. No parameter sweep, no variants, no second run unless a bug is found (then it is a new trial and needs a new approval).

## 2. The rule and parameters (exactly the spec)
`stockbot/strategies/lowvol_uptrend/strategy.py`, `SPEC` at the registered commit:
- id `lowvol_uptrend`, version `1.0.0`, status `research`, exit_policy `lv_trailing_atr3_floor8` (strategy-owned, `exits.py`), universe_overrides `{}`, overlays `{}`, validation_ref empty; `expected_trade_rate` 1.3, `smallest_edge_of_interest` 0.15, `prereg_ref` this file.
- params `{"vol_window": 252, "min_closes": 240, "sma_window": 200, "sma_min_closes": 198, "top_n": 25, "atr_period": 14, "atr_mult": 3.0, "stop_floor": 0.08, "tie_adtv_sessions": 20}`.
- **Spec hash: `52e7ee3ccc2e150d7e4b6b54266bb2c73a8788612691ece475bfa7d1bb0e9e68`** (`SPEC.config_hash()`; covers every spec field, the trade rate included). The registration commit records it again; it changes if any spec field is changed first.
- Universe: shared `universe.eligibility`, no overrides.
- Signal sessions: the first trading session of each calendar month (its (year, month) differs from the previous session's); no other session proposes anything.
- Per symbol on a signal session: a bar on the signal session; at least 240 adjusted closes among the last 252 Nifty-calendar sessions ending at it; 253 adjusted bars of its own.
- **Uptrend:** signal close (adjusted) strictly greater than SMA200 = the mean of the symbol's adjusted closes that fall inside the last 200 calendar sessions, with at least 198 of those 200 closes present.
- **vol** = sample standard deviation (ddof 1) of the 252 daily log returns of the symbol's consecutive own adjusted closes (the last 253 own closes, ending at the signal session); required > 0.
- Order: **lowest vol first**; exact ties by higher raw 20-session ADTV; then symbol. The first 25 are proposed with an explicit ordinal rank 25 down to 1.
- ATR14: Wilder ATR on the adjusted high, low and close of the symbol's last 252 bars up to the session, the same function as riskadj_momentum's (a copy in this strategy's folder; a test shows equal values on a fixture).
- Entry: the engine's next-open fill. **Initial stop = signal close - max(3 x ATR14, 0.08 x signal close).** Long only; no regime filter; no target; no overlay.
- Exit `lv_trailing_atr3_floor8`: the same rule as riskadj_momentum's `trailing_atr3_floor8` (a test shows the same stops session by session): reference = highest close since entry (seeded with the entry fill price); each session `stop = max(previous stop, reference - max(3 x ATR14 of that session, 0.08 x reference))`; the stop set on bar T applies from bar T+1; it never moves down; no time exit; state rescaled on corporate actions. The engine's usual rules apply.

## 3. Window and sub-periods
- **2016-01-01 to 2026-10-16.** The calendar starts 2015-11-09, so a 252-session window first exists in late 2016: **the 11 signal months of 2016-01 to 2016-11 are empty by the rule's own definition** (counts). Effectively 119 signal months (2016-12 to 2026-10).
- Two DESCRIPTIVE sub-period reports: 2016 to 2019 and 2020 to 2026-10-16, by entry date; never used to select, change or stop anything.

## 4. Execution, cost and risk settings in force (shared, not overridable)
Read from `config/shared.yaml` at run time: entry_fill NEXT_OPEN; entry_slippage_pct 0.10; exit_slippage_pct 0.10; max_entry_gap_up_pct 3.0. Costs: stt_buy_pct 0.10, stt_sell_pct 0.10, brokerage 0, exchange_txn_pct 0.00297, sebi_fee_pct 0.0001, stamp_duty_buy_pct 0.015, gst_pct 18.0, dp_charge_per_sell_inr 15.34, stcg_tax_pct 0.0. Portfolio: max_loss_pct_per_trade 1.0, max_concurrent_positions 12, max_total_portfolio_risk_pct 15.0, max_sector_exposure_pct 15.0. Backtest initial_equity 1,000,000. Universe: min_adtv_cr 25, min_listing_age_trading_days 252, min_market_cap_cr 5000 (PARKED, KI-001). Data: `data.symbol_links_enabled` true; engine: `stale_exit_sessions` 20; reporting: `stale_exit_stress_factor` 0.5. Sector rule: a mapped symbol belongs to its sector in `data/reference/sector_map.csv`; every unmapped symbol is its own sector. **Consequence of the stop rule:** a position's value is 1% of equity divided by the stop distance, so an 8% stop is a 12.5% position; in the counts 74.4% of the top-25 names sit at the 8% floor (mean position 11.9% of equity); with a 15% sector cap at most one position per mapped sector fits whenever positions exceed 7.5% of equity, so the book holds about 8 positions in about 8 different sectors.

## 5. Data snapshot and view
`finsight.db`, sha256 `dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752`, last session 2026-10-16. The registered run uses `STOCKBOT_VIEW=memory` (byte-identical to the SQL view); each run manifest records `asof_view`. The counts below were produced on the memory view (511 s for 130 signal sessions, which also ran riskadj_momentum and near_52w_high for the overlap figures); the strategy's tests assert SQL = memory on a fixture.

## 6. Counts that inform the registration (counts only; no forward price read)
Study: `scripts/signal_count_lowvol_uptrend.py`; results `docs/strategies/lowvol_uptrend/counts/summary.json` and `monthly_counts.json`.
- **Signal months: 130** (2016-01-01 to 2026-10-01). Shared-eligible names per signal month: median 275 (min 125, max 635).
- **Funnel over all 130 months (name-months):** fewer than 253 own bars 1,642; fewer than 240 closes in the window 1,048; no bar on the signal date 0; non-positive or non-finite price 0; fewer than 198 of the last 200 closes 132; **close not above SMA200 13,337**; vol <= 0 0; ATR missing 0; qualifying 24,873 (none has a stop at or below zero). Median month: 86 names below the SMA200, 165 qualifying.
- **Candidates per month:** the 11 months 2016-01 to 2016-11 have none. The other 119 months: **118 months have at least 25 qualifying names (the top 25 is full); 2020-04 has 21.** Mean qualifying by year: 2016 9, 2017 155, 2018 107, 2019 88, 2020 103, 2021 268, 2022 160, 2023 278, 2024 424, 2025 239, 2026 290.
- **Ties:** none in 24,873 qualifying name-months (0 tie groups, none at the cut); the ADTV tie-break never fires on the real lake.
- **Sector spread of the top 25** (2,971 name-months): 96.4% mapped, 3.6% UNMAPPED; distinct mapped sectors per month median 8 (min 4); the largest same-sector group in a month has a median of 7 names (max 13). **Depth needed for 8 names in different sectors** (each UNMAPPED name its own sector), walking down the full ranked list: reached in all 119 non-empty months; median position 18, p95 25, max 30; so in some months the 8th distinct sector lies below rank 25, and in 5 months the top 25 itself holds fewer than 8 distinct sectors.
- **Initial stop distance (top 25):** median 8.0% of the close (the floor), p5 8.0%, p95 11.1%, max 36.9%; **74.4% of names sit at the 8% floor** (3 x ATR below 8%). **Implied position size** (1% risk / distance): median 12.5% of equity, mean 11.9%, p5 9.0%, p95 12.5%.
- **Overlap of each month's top 25 with the previous month's** (118 pairs): mean 17.8 names (71.2%), median 18, range 7 to 24.
- **Overlap with riskadj_momentum:** 10.8% of the top-25 name-months were riskadj_momentum top-25 names the same month (that strategy's own code). **Overlap with near_52w_high:** 48.3% were near_52w_high candidates that session (every candidate counted; its candidate count has a median of 60.5).
- **Market state:** the Nifty closed below its own 200-session average at 28 of the 122 signal sessions with that average available (23.0%). The rule has no regime filter and proposes in those months too.
- **Expected trade rate (slot arithmetic, no forward prices).** Concurrent positions are bounded by capital and the sector cap: mean position 11.9% of equity gives 100 / 11.9 = **8.4**, so **about 8 positions**. In steady state entries a month = slots / average hold in months (an entry replaces an exit; the first months fill the book):

| assumed average hold | entries a month (8 slots) | with slots freed mid-month idle until the next signal session (hold + 0.5 month) | entries over the 119 signal months |
|---|---|---|---|
| 3 months | 2.67 | 2.29 | about 317 (272) |
| 6 months | 1.33 | 1.23 | about 158 (146) |

**Proposed `expected_trade_rate` = 1.3** (the 6-month hold). Reason: the stop is an 8% trail from the highest close for three quarters of the names, and low-volatility names rarely fall 8% from a high within a few months, so the longer hold is the more plausible one; the 3-month figure (2.7 a month) is stated beside it. Both holds are assumptions: the real hold depends on prices after the signals, which were not looked at. The model ignores that the sector cap can lower entries (the top 25 has a median of 8 distinct sectors), the risk and cash caps beyond the capital bound, costs, gap-up blocks and fill blocks.

## 7. Baselines
- **B1:** matched-random entries at trade level: **20 draws per actual trade**, at least 10 filled, **seed 20261111**, drawn on the trade's signal session from the shared-eligible pool (never the trade's own symbol, no pool filter, no ASM ranges), same fill, slippage, gap rule, corporate-action rebasing, stepping, costs and exit policy `lv_trailing_atr3_floor8`. **Every random entry gets the same stop rule as the strategy, on its own symbol:** initial stop = signal close - max(3 x ATR14, 0.08 x signal close), with ATR14 the symbol's own Wilder ATR over its last 252 adjusted bars up to that session, and the trailing exit then runs on the random symbol's own prices. It is NOT the actual trade's relative distance (the shared helper does that, so it is not used). The draw loop is the strategy-side `draw_matched_random_own` in `scripts/baseline_matched_random_lowvol_uptrend.py`, a copy of the shared loop; a test proves that with the shared helper's stop rule it returns the shared helper's rows exactly (same seed, same draws). A draw whose ATR is unavailable or whose stop would be at or below zero is not filled (`NO_STOP`, counted). A pair needs 10 filled draws; more than 5% of trades losing their pair flags the result.
- **B2:** the Nifty matched to the strategy's own daily invested share, the rest at the shared risk-free rate (6.5%); the member's idle cash credited at the same rate; the annualised, pre-tax, cash-credited alpha feeds the alpha gate (`stockbot/validation/benchmark_alpha.py`).
- No full-engine random replicates.

## 7a. End-of-window rule (fixed now, before any result)
Positions still open after the last session of the window (2026-10-16) are **closed at that session's close**, with the normal exit slippage (0.10%) and the normal sell costs, exit reason `END_OF_WINDOW`, and they **count as usable trades** in the gates (min_trades, expectancy, profit factor), in T1 and in T2. The same holds for random draws: a draw still open at the window end is closed at the last close with the same slippage and costs and **counts as filled**. Implemented in the strategy-side scripts only, shared code untouched: in `trades.json` such a trade carries `exit_reason` `END_OF_WINDOW_COUNTED` because the shared gate code treats the exact string `END_OF_WINDOW` as "not usable"; the engine's own label is kept in `exit_reason_engine`, and `end_of_window` is true. `actual_trades.csv` and `baseline_draws.csv` carry an `end_of_window` column. **The numbers of such trades and of such draws are reported separately in every output** (`run/manifest.json` `end_of_window.trades`; `baseline/baseline_meta.json` `end_of_window_trades`, `end_of_window_draws`, `draws_closed_before_window_end`; the gates output `counts.end_of_window_counted_as_usable`, `counts.baseline_end_of_window_draws`). With holds of several months, many positions and draws will be open at the window end; the last months of the window contribute partly unfinished trades to every statistic, actual trades and random draws alike.

## 7b. Renamed symbols and symbols that stop having bars (shared defaults, in force)
- **Symbol links** (`data.symbol_links_enabled` true, `data/reference/symbol_links.csv`, 41 renamed pairs): a renamed stock is one symbol under its latest name in the as-of views; its history is continuous across the rename.
- **No bars for 20 sessions** (`engine.stale_exit_sessions` 20): a position whose symbol has had no bar for 20 consecutive sessions is closed at its last close with normal costs (exit reason `SYMBOL_NO_BARS`) and **counts as a usable trade**; random draws close the same way. The lake keeps EQ-series rows only, so a symbol that leaves the EQ series (a series change, a suspension, or a merger) simply stops having bars; the last EQ close may not be the price an investor would have realised. Reported with a stress line: the same trades with those exits at 0.5 x the last close (`reporting.stale_exit_stress_factor`), in the gates output and `run/manifest.json` (`stale_exit`). The registered conclusion uses the base values; the stress line is information only.

## 8. Tests (family procedure, K = 1: `scripts/validate_family.py --expect-k 1`)
- **T1 (decision test):** D(m) = sum over trades entered in month m of (actual net R minus the mean net R of that trade's random draws); the K = 1 monthly series tested with the Westfall-Young Max-T step-down (one-sided, family-wise 0.05, **B = 10,000**, studentized circular block bootstrap, seed 20261111), **block lengths 2 and 3 months; BOTH must be significant** (adjusted p at most 0.05 at both). With K = 1 the Max-T correction is the single test.
- **T2:** paired statistics, reported only. **T3:** placebo size check (limits 0.025 to 0.075; outside is "size unreliable", the owner decides, nothing is recalibrated).

## 9. Power (assumptions, labelled; not measured)
T1 tests the monthly mean of D(m). With about 119 signal months and about 1.3 entries a month (about 158 trades; about 317 at a 3-month hold), a one-sided test at 5% with 80% power detects a true mean excess of `(1.645 + 0.842) x sigma / sqrt(n_eff)` net R per trade, where sigma is the standard deviation of (actual net R minus the mean random-draw net R) of a trade and n_eff the effective number of trades. **ASSUMPTIONS (nothing here was measured):** sigma of 1.0, 1.5 or 2.0 R, and a design effect of 1.0 (independent trades) or 1.5 (trades entered on the same month start are correlated; low-volatility names cluster in a few sectors and in time).

| trades (hold) | sigma R | design effect | detectable edge at 80% power (R per trade) | power at the edge of interest 0.15 R |
|---|---|---|---|---|
| 158 (6 months) | 1.0 | 1.0 | 0.20 | 60% |
| 158 | 1.0 | 1.5 | 0.24 | 46% |
| 158 | 1.5 | 1.0 | 0.30 | 35% |
| 158 | 1.5 | 1.5 | 0.36 | 27% |
| 158 | 2.0 | 1.5 | 0.48 | 19% |
| 317 (3 months) | 1.0 | 1.0 | 0.14 | 85% |
| 317 | 1.5 | 1.0 | 0.21 | 55% |
| 317 | 1.5 | 1.5 | 0.26 | 42% |

Under these assumptions an edge of 0.15 R is detectable with good power only at the short hold and sigma about 1 R; at the 6-month hold and sigma 1.5 R the test has about a third power at 0.15 R, and T1 must hold at BOTH block lengths, which lowers the power further. The gate `min_expectancy_r` 0.15 is a point estimate with no such protection.

## 10. Validation gates (`validation_gates`, shared; read at run time)
Gates hash (`stockbot.validation.prereg_lock.gates_hash`): **`e9b6407f908ff102dd25d9bc3b21a78a52b24c0ea082bba2cd3bb08f81188054`** (unchanged by the stale-positions work; a test asserts it).
| gate | value | note |
|---|---|---|
| min_trades | 40 | well below the roughly 150 to 320 expected |
| min_expectancy_r | 0.15 | point estimate |
| min_profit_factor | 1.3 | point estimate |
| max_drawdown_pct | 20.0 | backtest 20.0 versus paper 12.0 |
| min_alpha_pct | 0.0 | annualised, pre-tax, idle cash credited at the risk-free rate, against the matched Nifty |
KI-002: point-estimate gates do not account for sampling error; the registered rule is T1 AND all gates on point estimates.

## 11. Decision rule
DEMONSTRATED only if T1 finds the member (adjusted p at most 0.05 at BOTH block lengths, 2 and 3 months) AND every shared gate is met on its point estimate; otherwise "NOT DEMONSTRATED (registered rule not met; this is not evidence of no edge)". Status stays `research` whatever the outcome.

## 12. Limitations
- No signals before the first full 252-session window (here 2016-12-01); sector map incomplete (each unmapped symbol its own sector, so the cap does not limit concentration among them); no dividends in the lake (price returns only for the strategy, the baselines and the Nifty); no historical ASM/GSM exclusion (KI-003); EQ-only lake; unadjusted demerger, merger, rights and OTHER actions inside the 252-session lookback can distort the volatility and the SMA (no guard; not counted at this stage); the registered run uses the memory view; occupancy numbers are a counts model, not a forecast.
- **Trades and draws open at the window end are closed at the last close and counted** (section 7a); their holding time is unfinished and their number is not known in advance.
- **Slots freed mid-month stay in cash until the next signal session**; the invested share is lower than a daily-rebalanced book would have.
- **Entry months cluster on month starts**: every entry of a month happens on the same one or two days, so the monthly D(m) series has few independent observations per month and trades are correlated; the effective sample is smaller than the nominal one.
- The hold is set by the stop, not by a time limit, so the number of trades depends on the (unobserved) price paths.
- **Sixth rule tested on this window** (near_52w_high, short_term_reversal, pullback_uptrend, riskadj_momentum run; this one), each its own family, so the chance that one passes by luck is not controlled across families.
- **The random baseline draws from all eligible stocks, not only those above their 200-session average, so a pass would not separate the uptrend filter from the low-volatility ranking.**
- **Symbols that leave the EQ series have no bars in the lake; such positions close after 20 sessions at the last EQ close (stress line reported).**
- Rank is by past volatility only inside an uptrend filter; no market-regime filter (the Nifty was below its 200-session average at 23% of the signal sessions), no overlay. Low volatility with an 8% trailing floor means positions of about 12.5% of equity and about 8 names, so the book is concentrated and a single name can matter.

## 13. Registration (family route; NOT run; the owner writes it on master)
```
register_family(path=<family_ledger.csv>, family_id="family_batch3",
                members=["52e7ee3ccc2e150d7e4b6b54266bb2c73a8788612691ece475bfa7d1bb0e9e68"],                      # ONE spec, K = 1
                gate_params=<dataclasses.asdict(load_shared_config().validation_gates)>,                           # gates_sha256 e9b6407f908ff102dd25d9bc3b21a78a52b24c0ea082bba2cd3bb08f81188054
                git_sha="<COMMIT SHA OF THE APPROVED PRE-REGISTRATION>", reason="family_batch3 K=1")
```
(keyword form per `stockbot/validation/ledger/__init__.py`.) The registered run uses `STOCKBOT_VIEW=memory` (`docs/strategies/lowvol_uptrend/RUN_COMMANDS.md`, output folder `docs/strategies/lowvol_uptrend/results_run1/`). After the run and its B1 and B2: `py scripts/validate_family.py --member lowvol_uptrend=docs/strategies/lowvol_uptrend/results_run1 --expect-k 1 --lake <finsight.db> --out-json <FILE>`, then one `record_family_results` row.

## 14. Decisions still needed from the owner
None open in this text beyond the readings in `BRIEF.md` and the proposed trade rate 1.3. The owner registers `family_batch3` (K = 1) on master at the commit that carries this text and then authorises the registered run.
