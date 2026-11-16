# riskadj_momentum_daily: pre-registration (FINAL TEXT, NOT YET REGISTERED)

Final text 2026-11-16. **Nothing in this file has been registered in any ledger; it takes effect only when the owner registers the family on master at the commit that carries this text.** No return, P&L, win rate or forward price of this strategy has been computed or looked at: the only measurements are the counts (`docs/strategies/riskadj_momentum_daily/counts/`) and test results on fixture lakes. The strategy is the single member of `family_batch4` (K = 1); its registration is the owner's `FAMILY_REGISTRATION` row on master, not a row written from this branch. **Final spec hash: `5b06f092df061bff1532093d21ea21c88c3f2db64ddd66e0cbe81bd5c0446e19`.**

## Owner decisions (fixed)
- Every rule number below, `smallest_edge_of_interest` 0.15, window **2016-01-01 to 2026-10-16** (kept, with its empty sessions), K = 1, Max-T B = 10,000 with blocks 2 and 3 months (both significant), B1 20 draws per trade with seed 20261111, gates hash e9b6407f...8054.
- The one rule change against riskadj_momentum (every session is a signal session) and the fixed re-entry cooldown (21 sessions; option A). The engine change that supplies the exit history (own commit 433b1e1) was approved on 2026-11-16.
- Baseline pool (decision C): the random pool for each actual entry excludes the symbols the STRATEGY itself could not have bought that day (held, or in its own cooldown, taken from the stored run's trades); random draws never block each other.
- `expected_trade_rate` **8.1** a month (proposed from the slot arithmetic of section 6; the owner confirms or overrules it by registering).
- **End-of-window rule (fixed before any result): section 7a.** Shared defaults as on master: symbol links on, stale exit after 20 sessions (section 7b).

## 1. What would be registered
One strategy, one configuration, one backtest run, one decision, in a K = 1 family. No parameter sweep, no variants, no second run unless a bug is found (then it is a new trial and needs a new approval).

## 2. The rule and parameters (exactly the spec)
`stockbot/strategies/riskadj_momentum_daily/strategy.py`, `SPEC` at the registered commit:
- id `riskadj_momentum_daily`, version `1.0.0`, status `research`, exit_policy `rmd_trailing_atr3_floor8` (strategy-owned, `exits.py`), universe_overrides `{}`, overlays `{}`, validation_ref empty; `expected_trade_rate` 8.1, `smallest_edge_of_interest` 0.15, `prereg_ref` this file.
- params `{"ret_long": 252, "ret_skip": 21, "min_closes": 240, "top_n": 25, "atr_period": 14, "atr_mult": 3.0, "stop_floor": 0.08, "tie_adtv_sessions": 20, "signal": "every_session", "reentry_cooldown_sessions": 21}`.
- **Spec hash: `5b06f092df061bff1532093d21ea21c88c3f2db64ddd66e0cbe81bd5c0446e19`** (`SPEC.config_hash()`; covers every spec field, the trade rate included). The counts below were produced before `expected_trade_rate` was set (spec hash then `5eee3136...`); the rule code did not change. The registration commit records the hash again.
- Universe: shared `universe.eligibility`, no overrides.
- **Signal sessions: every session of the calendar.** A session proposes when the 252-session calendar window exists (first possible: late 2016); nothing else is required.
- Per symbol on a signal session, as riskadj_momentum: a bar on the signal session; at least 240 adjusted closes among the last 252 Nifty-calendar sessions ending at it; 253 adjusted bars of its own (t-21 and t-252 are positions 21 and 252 before its last own bar).
- ret = adjusted close[t-21] / adjusted close[t-252] - 1, required > 0 (strict). vol = sample standard deviation (ddof 1) of the daily log returns of the symbol's consecutive adjusted closes from t-252 through t-21, required > 0. score = ret / vol.
- **Re-entry cooldown:** a symbol whose position of this strategy was closed by STOP_HIT is not proposed until 21 sessions have passed after the exit session: the exit session and the 21 sessions after it are blocked, the 22nd session after the exit is the first allowed signal session. Only STOP_HIT starts a cooldown; exits by SYMBOL_NO_BARS, by an operator-reported reason, or by END_OF_WINDOW (which never reaches the strategy) do not. Linked (renamed) names are the same symbol. A name in cooldown is removed BEFORE the ranking: the top 25 is filled from the allowed names. The exits come only from the engine-owned history (`strategy_state["_exits"]`, the strategy opts in with the class attribute `exit_history_sessions` = 25, which is not a spec field) and the sessions from `view.sessions`; it is the same in backtest, paper and live.
- Order: score descending; exact ties by higher raw 20-session ADTV; then symbol. The first 25 are proposed with an explicit ordinal rank 25 down to 1.
- ATR14: Wilder ATR on the adjusted high, low and close of the symbol's last 252 bars up to the session (a copy of riskadj_momentum's function; a test shows equal values on a fixture).
- Entry: the engine's next-open fill. **Initial stop = signal close - max(3 x ATR14, 0.08 x signal close).** Long only; no regime filter; no target; no overlay.
- Exit `rmd_trailing_atr3_floor8`: the same rule as riskadj_momentum's `trailing_atr3_floor8` (a test shows the same stops session by session on a fixture path with a corporate action): reference = highest close since entry (seeded with the entry fill price); each session `stop = max(previous stop, reference - max(3 x ATR14 of that session, 0.08 x reference))`; the stop set on bar T applies from bar T+1; it never moves down; no time exit; state rescaled on corporate actions.
- **Shared engine change (approved, own commit 433b1e1):** `stockbot/engine/exit_history.py`, `decide.py`, `reports.apply_effect`, a docstring in `strategies/base.py`. Opt-in by class attribute; no spec, config or gates hash changed (the gates hash `e9b6407f...8054` and `shared_config_hash` `da459624...` are unchanged; a strategy that does not opt in has byte-identical states, journals and outputs; proof in `Claude_Docs/RISKADJ_MOMENTUM_DAILY_BUILD_REPORT.md`).

## 3. Window and sub-periods
- **2016-01-01 to 2026-10-16.** The calendar starts 2015-11-09, so a 252-session window first exists in late 2016: **the first 215 sessions of the window (2016-01 to 2016-11) have no signals by the rule's own definition** (counts). Signals exist on 2,459 sessions.
- Two DESCRIPTIVE sub-period reports: 2016 to 2019 and 2020 to 2026-10-16, by entry date; never used to select, change or stop anything.

## 4. Execution, cost and risk settings in force (shared, not overridable)
Read from `config/shared.yaml` at run time: entry_fill NEXT_OPEN; entry_slippage_pct 0.10; exit_slippage_pct 0.10; max_entry_gap_up_pct 3.0. Costs: stt_buy_pct 0.10, stt_sell_pct 0.10, brokerage 0, exchange_txn_pct 0.00297, sebi_fee_pct 0.0001, stamp_duty_buy_pct 0.015, gst_pct 18.0, dp_charge_per_sell_inr 15.34, stcg_tax_pct 0.0. Portfolio: max_loss_pct_per_trade 1.0, max_concurrent_positions 12, max_total_portfolio_risk_pct 15.0, max_sector_exposure_pct 15.0. Backtest initial_equity 1,000,000. Universe: min_adtv_cr 25, min_listing_age_trading_days 252, min_market_cap_cr 5000 (PARKED, KI-001). Data: `data.symbol_links_enabled` true; engine: `stale_exit_sessions` 20; reporting: `stale_exit_stress_factor` 0.5. Sector rule: a mapped symbol belongs to its sector in `data/reference/sector_map.csv`; every unmapped symbol is its own sector. **Consequence of the stop rule:** a position's value is 1% of equity divided by the stop distance, so an 8% stop is a 12.5% position and a 12% stop an 8.3% position (counts: mean 8.8% of equity, as for riskadj_momentum), so capital allows about 11 positions although the limit is 12; with a 15% sector cap at most one position per mapped sector fits whenever positions exceed 7.5% of equity.

## 5. Data snapshot and view
`finsight.db`, sha256 `dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752`, last session 2026-10-16. The registered run uses `STOCKBOT_VIEW=memory` (byte-identical to the SQL view; the strategy's tests assert SQL = memory through the engine on a fixture); each run manifest records `asof_view`. The counts were produced on the memory view (5,875 s for 2,674 sessions).

## 6. Counts that inform the registration (counts only; no forward price read; the cooldown is NOT applied in the counts because it needs the strategy's own exits, which exist only in an engine run; it can only remove names)
Study: `scripts/signal_count_riskadj_momentum_daily.py`; results `counts/summary.json` and `session_counts.json`.
- **Sessions: 2,674** (2016-01-01 to 2026-10-16). Shared-eligible names per session: median 275 (min 123, max 635).
- **Funnel over all sessions (name-sessions):** fewer than 253 own bars 32,363; fewer than 240 closes in the window 21,677; no bar on the signal date 0; non-positive or non-finite price 0; ret <= 0 261,852; vol <= 0 0; ATR missing 0; qualifying 532,372 (44 have a stop at or below zero and are unusable).
- **Candidates per session:** 215 sessions (2016-01 to 2016-11) have none. The other 2,459 sessions have a median of 171 qualifying names overall (all sessions: p95 457, max 539). **Fewer than 25 qualify in 216 sessions: the 215 empty ones and one session with 23; every other session (2,458) has a full top 25.**
- **Score ties:** none in 532,328 qualifying name-sessions (the ADTV tie-break never fires).
- **Day-to-day overlap of the top 25** (2,458 pairs): mean 23.0 names (92.1%), median 23, range 18 to 25. **The top-ranked 12 change on 81.3% of sessions** (1,998 of 2,458); the mean number of new names in the top 12 is 1.15 a session, median 1, maximum 6.
- **Initial stop distance (top 25, 61,473 name-sessions):** median 11.8% of the close, p5 8.0%, p95 19.6%, max 99.0%; **15.9% sit at the 8% floor**. **Implied position size** (1% risk / distance): median 8.5% of equity, mean 8.8%, p5 5.1%, p95 12.5%.
- **Sector spread of the top 25:** 76.8% mapped, 23.2% UNMAPPED; distinct mapped sectors per session median 8 (min 4); the largest same-sector group has a median of 6 names (max 13). **Depth needed to find 12 names that pass the 15% sector cap** (greedy walk down the ranked list, each unmapped name its own sector; cash not applied): reached in all 2,459 sessions; median rank 17, p95 41, max 55; **in 447 sessions (18%) more than 25 names are needed, so the engine, which sees only the top 25, cannot fill 12 slots from that list on those sessions.**
- **Expected trade rate (slot arithmetic, no forward prices).** 12 slots (the limit; capital allows about 11 at a mean position of 8.8%). A slot that frees on a session is refilled by a signal at that session's close and an entry at the next open, one session later, so entries per session = 12 / (hold + 1) in sessions, 21 sessions to the month. The holds are assumptions: 20 sessions (riskadj_momentum run 1's observed median hold, a result already seen and cited as such) and 40 sessions; the median understates the mean hold of a trailing-stop rule with a long right tail, so the midpoint, 30 sessions, is also shown.

| assumed average hold | entries a session | entries a month | entries over the 2,459 signal sessions |
|---|---|---|---|
| 20 sessions | 0.571 | 12.0 | about 1,405 |
| 30 sessions (proposed) | 0.387 | 8.1 | about 952 |
| 40 sessions | 0.293 | 6.1 | about 720 |

**Proposed `expected_trade_rate` = 8.1** a month (the 30-session midpoint). Ignored: the cooldown (it lowers entries), the sector cap and cash limits (they lower entries, and the 447 sessions above say that is not rare), costs, gap-up blocks, fill blocks. The holds are assumptions, not measurements.

## 7. Baselines
- **B1:** matched-random entries at trade level: **20 draws per actual trade**, at least 10 filled, **seed 20261111**, drawn on the trade's signal session from the shared-eligible pool, with **the pool of option C**: minus the trade's own symbol (as the shared helper), minus the symbols the strategy held on that signal session (entry date <= the signal session < exit date) and minus the symbols in the strategy's own cooldown on that session (STOP_HIT exit, exit session up to 21 sessions before the signal session, the exit session included; linked names compared by their latest name), all taken from the stored run's trades; random draws never block each other; no ASM ranges. Note: the shared helper drops only the trade's own symbol, so the held exclusion is new relative to the earlier registered baselines. Each draw gets the same fill, slippage, gap rule, corporate-action rebasing, stepping, costs and exit policy `rmd_trailing_atr3_floor8`, and **the same stop rule as the strategy on its own symbol**: initial stop = signal close - max(3 x ATR14, 0.08 x signal close). The draw loop is the strategy-side `draw_matched_random_own` in `scripts/baseline_matched_random_riskadj_momentum_daily.py`, a copy of the shared loop; a test proves that with the shared helper's stop rule and no pool filter it returns the shared helper's rows exactly (same seed). The numbers of pool exclusions (held, cooldown, kept) are written to `baseline_meta.json` (`pool_exclusions`) and reported. A draw whose ATR is unavailable or whose stop would be at or below zero is not filled (`NO_STOP`, counted). A pair needs 10 filled draws; more than 5% of trades losing their pair flags the result.
- **B2:** the Nifty matched to the strategy's own daily invested share, the rest at the shared risk-free rate (6.5%); the member's idle cash credited at the same rate; the annualised, pre-tax, cash-credited alpha feeds the alpha gate (`stockbot/validation/benchmark_alpha.py`).
- No full-engine random replicates.

## 7a. End-of-window rule (fixed now, before any result)
Positions still open after the last session of the window (2026-10-16) are **closed at that session's close**, with the normal exit slippage (0.10%) and the normal sell costs, exit reason `END_OF_WINDOW`, and they **count as usable trades** in the gates (min_trades, expectancy, profit factor), in T1 and in T2; random draws still open at the window end are closed the same way and **count as filled**. Implemented in the strategy-side scripts only: in `trades.json` such a trade carries `exit_reason` `END_OF_WINDOW_COUNTED` (the shared gate code treats the exact string `END_OF_WINDOW` as "not usable"), the engine's label is kept in `exit_reason_engine`, `end_of_window` is true. Their numbers are reported separately in every output (`run/manifest.json` `end_of_window.trades`; `baseline_meta.json` `end_of_window_trades`, `end_of_window_draws`; the gates output `counts.end_of_window_counted_as_usable`, `counts.baseline_end_of_window_draws`). A position closed at the window end does not start a cooldown (it is closed after the last session, and the strategy never sees it).

## 7b. Renamed symbols and symbols that stop having bars (shared defaults, in force)
- **Symbol links** (`data.symbol_links_enabled` true, 41 renamed pairs): a renamed stock is one symbol under its latest name; the cooldown treats both names as one symbol.
- **No bars for 20 sessions** (`engine.stale_exit_sessions` 20): such a position is closed at its last close with normal costs (exit reason `SYMBOL_NO_BARS`), **counts as a usable trade**, and does NOT start a cooldown; random draws close the same way. Reported with the stress line (same trades with those exits at 0.5 x the last close) in the gates output and `run/manifest.json` (`stale_exit`); the registered conclusion uses the base values.

## 8. Tests (family procedure, K = 1: `scripts/validate_family.py --expect-k 1`)
- **T1 (decision test):** D(m) = sum over trades entered in month m of (actual net R minus the mean net R of that trade's random draws); the K = 1 monthly series tested with the Westfall-Young Max-T step-down (one-sided, family-wise 0.05, **B = 10,000**, studentized circular block bootstrap, seed 20261111), **block lengths 2 and 3 months; BOTH must be significant** (adjusted p at most 0.05 at both).
- **T2:** paired statistics, reported only. **T3:** placebo size check (limits 0.025 to 0.075; outside is "size unreliable", the owner decides, nothing is recalibrated).

## 9. Power (assumptions, labelled; not measured)
T1 tests the monthly mean of D(m). With about 117 months of signals and about 8.1 entries a month (about 950 trades; about 1,400 and 720 at 20 and 40 session holds), a one-sided test at 5% with 80% power detects a true mean excess of `(1.645 + 0.842) x sigma / sqrt(n_eff)` net R per trade, where sigma is the standard deviation of (actual net R minus the mean random-draw net R) of a trade and n_eff = trades / design effect. **ASSUMPTIONS (nothing here was measured):** sigma of 1.0, 1.5 or 2.0 R, and a design effect of 1, 2 or 4: entries on neighbouring sessions come from a top 25 that overlaps 92% from day to day, trade windows overlap, and market-wide moves are shared, so the 950 trades are far fewer than 950 independent observations.

| trades (hold) | sigma R | design effect | detectable edge at 80% power (R per trade) | power at the edge of interest 0.15 R |
|---|---|---|---|---|
| 952 (30 sessions) | 1.0 | 1 | 0.08 | above 99% |
| 952 | 1.5 | 1 | 0.12 | 93% |
| 952 | 1.5 | 2 | 0.17 | 70% |
| 952 | 1.5 | 4 | 0.24 | 46% |
| 952 | 2.0 | 4 | 0.32 | 31% |
| 1,405 (20 sessions) | 1.5 | 2 | 0.14 | 84% |
| 1,405 | 1.5 | 4 | 0.20 | 59% |
| 720 (40 sessions) | 1.5 | 2 | 0.20 | 60% |
| 720 | 1.5 | 4 | 0.28 | 38% |

The power depends mostly on the design effect, which is the least known number here; with sigma 1.5 R and a design effect of 4 the test has under half power at 0.15 R, and T1 must hold at BOTH block lengths, which lowers it further. The gate `min_expectancy_r` 0.15 is a point estimate with no such protection.

## 10. Validation gates (`validation_gates`, shared; read at run time)
Gates hash (`stockbot.validation.prereg_lock.gates_hash`): **`e9b6407f908ff102dd25d9bc3b21a78a52b24c0ea082bba2cd3bb08f81188054`** (unchanged by the exit-history engine change; a test asserts it).
| gate | value | note |
|---|---|---|
| min_trades | 40 | far below the roughly 700 to 1,400 expected |
| min_expectancy_r | 0.15 | point estimate |
| min_profit_factor | 1.3 | point estimate |
| max_drawdown_pct | 20.0 | backtest 20.0 versus paper 12.0 |
| min_alpha_pct | 0.0 | annualised, pre-tax, idle cash credited at the risk-free rate, against the matched Nifty |
KI-002: point-estimate gates do not account for sampling error; the registered rule is T1 AND all gates on point estimates.

## 11. Decision rule
DEMONSTRATED only if T1 finds the member (adjusted p at most 0.05 at BOTH block lengths, 2 and 3 months) AND every shared gate is met on its point estimate; otherwise "NOT DEMONSTRATED (registered rule not met; this is not evidence of no edge)". Status stays `research` whatever the outcome.

## 12. Limitations
- **This is a variant of riskadj_momentum chosen AFTER its registered result was seen (run 1 was about 60% invested with a median hold of 20 sessions); seventh rule on this window (near_52w_high, short_term_reversal, pullback_uptrend, riskadj_momentum, lowvol_uptrend; this one), each its own family, so the chance that one passes by luck is not controlled across families; a pass is weaker evidence than a first registered pass.** The window, the data and the rule's family are the same as the result that motivated the change.
- No signals before the first full 252-session window (here from late 2016); sector map incomplete (each unmapped symbol its own sector, so the cap does not limit concentration among them); no dividends in the lake (price returns only for the strategy, the baselines and the Nifty); no historical ASM/GSM exclusion (KI-003); EQ-only lake; unadjusted demerger, merger, rights and OTHER actions inside the 252-session lookback can distort the 12-1 return and the volatility (no guard); the registered run uses the memory view.
- **Trades and draws open at the window end are closed at the last close and counted** (section 7a); their number is not known in advance.
- **Daily signals overlap heavily** (92% of the top 25 is the same from one session to the next, 81% of sessions change at least one of the top 12), so trades entered on neighbouring sessions are strongly correlated and the effective sample is much smaller than the trade count; the monthly D(m) of T1 sums many correlated trades.
- **The cooldown is a fixed 21 sessions chosen once, before any result, to stop immediate re-buying; it was not tuned.** It acts only through the engine-supplied exit history of this strategy's own STOP_HIT exits. It does not stop a name that was exited for another reason, or re-entry after 22 sessions.
- **The random baseline's pool also drops the strategy's held and cooldown symbols** (option C), which the earlier registered baselines did not do for held symbols; the random draws themselves can hold a symbol while another draw buys it again (draws never block each other), so the baseline is not a portfolio.
- The sector cap and cash leave room for fewer positions than the 12-position limit; on 18% of sessions the ranked top 25 holds fewer than 12 names that pass the cap, so fewer entries occur than the slot arithmetic says.
- **Costs:** daily rebalancing with a trailing stop produces many more trades than the monthly rule; costs are those of the shared config and are included in the net R.
- The hold is set by the stop, not by a time limit, so the trade count depends on the (unobserved) price paths; section 6 is an assumption-driven model.
- **Symbols that leave the EQ series have no bars in the lake; such positions close after 20 sessions at the last EQ close (stress line reported).**
- Rank is by past risk-adjusted return only; no market-regime filter, no overlay.

## 13. Registration (family route; NOT run; the owner writes it on master)
```
register_family(path=<family_ledger.csv>, family_id="family_batch4",
                members=["5b06f092df061bff1532093d21ea21c88c3f2db64ddd66e0cbe81bd5c0446e19"],                      # ONE spec, K = 1
                gate_params=<dataclasses.asdict(load_shared_config().validation_gates)>,                           # gates_sha256 e9b6407f908ff102dd25d9bc3b21a78a52b24c0ea082bba2cd3bb08f81188054
                git_sha="<COMMIT SHA OF THE APPROVED PRE-REGISTRATION>", reason="family_batch4 K=1")
```
(keyword form per `stockbot/validation/ledger/__init__.py`.) The registered run uses `STOCKBOT_VIEW=memory` (`docs/strategies/riskadj_momentum_daily/RUN_COMMANDS.md`, output folder `docs/strategies/riskadj_momentum_daily/results_run1/`). After the run and its B1 and B2: `py scripts/validate_family.py --member riskadj_momentum_daily=docs/strategies/riskadj_momentum_daily/results_run1 --expect-k 1 --lake <finsight.db> --out-json <FILE>`, then one `record_family_results` row.

## 14. Decisions still needed from the owner
None open in this text beyond the readings in `BRIEF.md` (cooldown applied before the ranking; day 0 to 21 blocked) and the proposed trade rate 8.1. The owner registers `family_batch4` (K = 1) on master at the commit that carries this text and then authorises the registered run.
