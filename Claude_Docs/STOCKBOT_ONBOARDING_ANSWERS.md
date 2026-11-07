# StockBot — Answers to the Onboarding Comprehension Questions

Repo HEAD `be4295a`. Tags: **[CODE]** = read from source only; **[RUN]** = also confirmed by a test, scratch repro, or read-only DB/CSV query. Companion: `STOCKBOT_CODEBASE_UNDERSTANDING.md`. Paths are relative to `F:\Projects\Ravi\StockBot`.

---

## A. Purpose and flow

### Q1. One live trade, end to end [CODE]

1. `live_runner/scheduler.py::start_scheduler` registers `run_eod_pipeline` (19:00 IST for bhavcopy, else 17:00). `run_eod_pipeline` calls `git_lock.verify_git_lock()`, finds missing trading days (yfinance `^NSEI`), and for each calls `EODPipeline(session).run(t_date)`.
2. `pipeline.py::EODPipeline.run`: `IdempotencyGuard.acquire` → `_run_ingestion` (`BhavcopyIngestor.ingest` + `_ingest_indices_yahoo`) → `_assert_data_freshness` → `preflight.assert_preflight_spot_check` → `RegimeFilter.evaluate` (persists `regime_state`).
3. (PAPER only) `paper_trader.expire_stale_tickets` / `open_pending_tickets` — not relevant in LIVE.
4. `PositionLifecycleManager.process_all` → `process_single` per `ActivePosition(mode=LIVE)` → `advance_one_bar`. In LIVE it only sets flags/`pending_close_reason` (`ACTION_REQUIRED_*`, `BOOK_PARTIAL_*`) and never closes rows.
5. If kill switch is off and not `bull_correction_active`: `_run_screening` → `UniverseScreener.screen_all(eval_date)` (event gates on) → `_build_candidate_dicts` → `candidate_builder.build_candidate_dicts` (→ `adjustments.get_adjusted_series`, `sector_map.sector_for`) → `entry_filters.apply_entry_filters` → `RiskAndSizingEngine.compute_all` (→ `compute_setup`, `_check_heat_cap`, `_is_heat_cap_full`; equity from `equity.get_equity` → `account_ledger.get_live_equity`) → `_persist_watchlist` writes `daily_watchlist` rows (ticket) with `execution_status=PENDING`.
6. `IdempotencyGuard.complete`. The owner sees the ticket via `routers/watchlist.py`, places the order in his broker terminal.
7. Reporting the fill: `POST /positions/open` (`routers/positions.py::open_position_endpoint`) requires LIVE mode and a PENDING, non-blocked ticket, then `position_service.open_position` creates `ActivePosition` (INITIAL_RISK, `fill_source=BROKER_ENTERED`, `entry_costs=CostModel.buy_cost`) and marks the ticket OPENED. Note it back-derives equity from the ticket (`risk_amount / risk_pct`).
8. Subsequent nights: step 4 advances the state machine, moving `live_stop_loss`, flagging partials/time decay/stop hits for the owner to act on at the broker.
9. Exit: owner exits at broker, then `POST /positions/close` → `AnalyticsLoop.record_closed_trade` (computes realized R, `pnl_gross`, costs, `pnl_net`, regime labels, writes `trade_analytics_log`), then the route deletes the `ActivePosition`.

**Confirm by**: an in-memory integration test that seeds a ticket, calls `/positions/open` with LIVE config, advances bars, then `/positions/close`; none exists today (`test_live_vs_rules.py` covers only the state machine in PAPER).

### Q2. One trade in the simulator [CODE; parity of exits RUN via `test_sim_vs_live_rules.py::test_golden_master_simulator_vs_plm_exits`]

`backtest/simulator.py::Simulator.run` day `d`: `RegimeFilter.evaluate(d)` → (day T) `UniverseScreener.screen_single(apply_event_gates=False)` per symbol → `Exclusions.asm_blocked/earnings_within` (Pass 2) → `build_candidate_dicts` → `apply_entry_filters` → `RiskAndSizingEngine.compute_all(is_bull_regime=bull)` → non-blocked setups to `pending` → (day T+1) `_bar` → `lifecycle_rules.plan_entry_fill` → `CostModel.buy_cost`, cash debit, `PosState` created → `advance_one_bar` each day (`BarCtx` from `atr`, `parabolic_ref_close`) → exits booked with `CostModel.sell_cost` → trade row on close (or `END_OF_WINDOW`).

**Shared with live**: `RegimeFilter`, `UniverseScreener` class, `build_candidate_dicts`, `apply_entry_filters`, `RiskAndSizingEngine`, `plan_entry_fill`, `advance_one_bar`, `LifecycleRules`, `CostModel`, `get_adjusted_series`.
**Not shared**: the orchestration loop itself; event exclusions (`Exclusions` vs ASM snapshot/earnings table, 7-day vs 14-day window); equity definition (MTM vs realized-only); persistence (in-memory dict vs `ActivePosition`/`trade_analytics_log`); `_bar` reads a *single-symbol adjusted bar as-of the bar date* while PLM uses `lookback=220` raw bars as-of eval date; the simulator ignores `has_ca` for open positions (see Q21).

### Q3. Pass 1 vs Pass 2 [CODE]

Only the `exclusions` argument of `Simulator.run`. Pass 1: `exclusions=None`. Pass 2: `Exclusions` object, applied in step 4 after the gate-1–3 screen: `if exclusions and (exclusions.asm_blocked(sym, d) or exclusions.earnings_within(sym, d)): continue`. `earnings_within` uses `min(block_days, known_ahead_days)` so the backtest only blocks on events the live system could have known (7 days). Loading is `Exclusions.load` (fail-closed; `run_backtest.py --pass2`). `SimResult.compliance_applied` tells the audit gate whether Pass 2 was truly compliant. A unit-level check exists: `test_simulator_exclusions_none_vs_empty` [RUN] and `test_asm_exclusion_frees_slot_for_next_ranked` [RUN].
Caveat: `run_candidate_simulations.py` runs **Pass 1 only** (`sim.run(...)` with no exclusions), so Step 3 results have no compliance filtering.

### Q4. PAPER vs LIVE [CODE]

Single switch: `strategy_config.yaml → runtime.mode`, read only by `engine_core/mode.py::current_mode` (raises on anything else). Differences:
- Fills: PAPER auto-fills tickets at next open (`paper_trader.open_pending_tickets` → `plan_entry_fill`, `fill_source=SIMULATED`); LIVE waits for `/positions/open`.
- Lifecycle: PAPER `process_single` logs exits to `trade_analytics_log`, updates `shares_remaining`, deletes closed rows; LIVE is advisory (`pending_close_reason`, flags), the owner closes via `/positions/close`.
- Equity: `equity.get_equity` → `paper_equity` (start + Σ(net−tax) of PAPER trades) vs `account_ledger.get_live_equity` (ledger + Σ gross PnL of LIVE trades, falling back to `ACCOUNT_EQUITY` env).
- Endpoints: `/positions/open` is LIVE-only, `/positions/close` is blocked in PAPER.
- Pipeline: LIVE-only drawdown guard (`live_guardrails`, inert without that config key); `authorize_live.py` requires `docs/PAPER_RESULT.json passed` for LIVE.
Every `ActivePosition`, `TradeAnalyticsLog` row carries `mode`; queries filter by it.

---

## B. Data integrity

### Q5. Raw vs adjusted [CODE; enforcement tests RUN: `test_adjustments.py`]

Raw is stored (`ohlcv_ingestor` `continuous=False`; `market_data_lake.close_raw`). Adjusted is computed on demand because corporate actions after any given date change history *retroactively*; storing adjusted data would bake in knowledge unavailable then and corrupt liquidity.
- **Must use raw**: ADTV (`adjustments.compute_adtv(raw_close, raw_volume)` called from `universe_screener.screen_single`), market cap (`compute_market_cap(raw_close, shares)`), RS gate 7 (`close_raw`), index regime (`RegimeFilter._fetch_closes` uses `close_raw`), `paper_trader` open price check.
- **Must use adjusted**: ATR, Donchian stops/targets, SMA trend, breakout, RS rank, `Bar` values in `advance_one_bar`.
Enforcement is by structure: `get_adjusted_series` returns *only* OHLC (no volume), so ADTV cannot accidentally take adjusted volume; `compute_adtv/compute_market_cap` are the only canonical implementations; `lifecycle_rules.Bar` docstring says "split-ADJUSTED". There is no runtime assertion; correctness depends on callers. **Confirm**: grep that no `*_adj` appears in `universe_screener.py`.
Real-DB caveat: `corporate_actions_log` is empty so adjusted == raw today [RUN].

### Q6. Lookahead avoidance — five concrete places [CODE]

1. Indicators/data windows: every fetch is `trade_date <= eval_date` (`candidate_builder`, `_fetch_ohlcv`, `RegimeFilter._fetch_closes`, `nifty_sma`); `donchian_*`/`sma` are trailing.
2. Fills: signal at close T, fill `plan_entry_fill(next_open=bar.open)` on T+1; the stop check in `advance_one_bar` uses the stop in force at yesterday's close, trail/ratchet updates apply from today's high *after* the stop test.
3. Corporate actions: `compute_row_factors` ignores actions with `ex_date > as_of_date`; ticket fills on an ex-date are skipped (`CORP_ACTION_ON_EXEC_DATE`).
4. Exclusions: `earnings_within` caps the horizon at `known_ahead_days=7`; ASM uses time intervals containing `d`.
5. Fundamentals: market cap uses `SharesOutstanding.effective_date <= eval_date`; listing age from official listing date.
Leaks I found: live ASM table is a current snapshot (not PIT); shares data is a single 2020-01-01 snapshot [RUN]; `UniverseScreener.screen_all` RS cutoff is off. **Confirm**: shift the price series by one day in a fixture and assert tickets change.

### Q7. Missing earnings or ASM/GSM data [CODE; RUN for DB state]

- Backtest Pass 2: `Exclusions.load` raises `RuntimeError("Pass 2 refused (fail-closed)…")` if either CSV is missing, empty, or has non-VERIFIED ASM rows; `--allow-unverified` downgrades to `applied=False` → `compliance_applied=False` → `audit_generator.generate` check `compliance_applied` fails, so the run can't authorize.
- Pass 1 / candidate runs: no exclusions at all.
- Live: **fail-open**. `_is_under_surveillance` returns False when the table is empty; `_days_to_next_event` returns `None` when no rows. The real DB has 0 rows in both tables [RUN], so today the live screener blocks nothing on those gates. The onboarding claim "missing data should block" applies to `exclusions.py` only.

### Q8. Point-in-time vs snapshot [CODE + RUN]

- Point-in-time by design: OHLCV (append-only by date), `regime_state` (per date), corp-action adjustment as-of, `SecuritiesMaster.listing_date`, `shares_outstanding` (schema supports `effective_date`, but the data is one 2020-01-01 snapshot, so effectively **not** PIT), sector map (static CSV, today's mapping).
- Snapshot, cannot be backtested faithfully: `asm_gsm_list` (replaced on refresh; backtests use manually verified CSVs), `earnings_calendar` (forward calendar refreshed, 0 rows), sector map, shares outstanding as loaded, `EQUITY_L.csv` universe (survivorship: delisted names absent unless in the lake), `securities_master`.

---

## C. Rules and risk

### Q9. Position state machine [CODE; RUN via `test_lifecycle_rules.py`, `test_position_lifecycle.py`, `test_live_vs_rules.py`]

States: `INITIAL_RISK` → `RISK_FREE_1_TO_1` → `TRAILING_ATR` → (`PARABOLIC_TRAILING`), plus `PENDING_MANUAL_EXIT`, closed.
Per bar (`lifecycle_rules.advance_one_bar`):
1. State `PENDING_MANUAL_EXIT` → exit today's open × (1−slip), reason `TIME_DECAY`.
2. `low <= live_stop` → `STOP_HIT` at `min(open, live_stop)×slip`.
3. `days_held += 1`; `highest_high = max(...)`.
4. INITIAL_RISK: high ≥ entry+1R → RISK_FREE, stop = max(stop, entry). Otherwise `days_held >= 20` → PENDING_MANUAL_EXIT (flag `TIME_DECAY_FLAGGED`; exit executes at the *next* open). Graduation beats decay on the same day.
5. RISK_FREE: high > target → TRAILING_ATR with stop = max(stop, HH − 2.5×ATR) (1.5× during kill switch).
6. TRAILING: if parabolic (close − close 5 sessions ago ≥ 3×ATR) → PARABOLIC (stop = max(stop, HH − 1×ATR)); else ratchet-trail.
7. Ratchet rungs (if not bull): HH ≥ +1R → stop ≥ entry; +2R → entry+1R; +3R → entry+2R.
8. Partial: first rung when `bar.high ≥ entry+1R`: sell `floor(12% of remaining)` at `max(open, limit)`.
The stop only moves up (`max`). Time decay applies only in INITIAL_RISK. **Gap down through stop**: the open is below the stop → filled at the open (`min(open, stop)`), flag `GAP_THROUGH_STOP`, whole remaining position exits that bar. [RUN] `test_golden_master_simulator_vs_plm_exits` asserts the fill at the gap open (94 vs stop 95) and identical exit date in simulator and PLM.
Note (from docstrings/README) "15 sessions" is stale; config is 20.

### Q10. Position sizing and cap order [CODE; RUN partially via `test_phase1_components.py`]

`risk_sizing.RiskAndSizingEngine.compute_setup`:
1. entry = last adjusted close; ATR14; stop A = entry − 2.0×ATR; stop B = Donchian-30 low; **live stop = min(A,B)** (wider). Blocks: `ATR_NAN`, `DONCHIAN_LOW_NAN`, `STOP_ABOVE_ENTRY`.
2. Target = Donchian-252 high; if entry ≥ target use entry + 3×ATR (hardcoded `atr_projection_mult = 3.0` — a magic number outside config).
3. R:R = (target−entry)/(entry−stop); block `RR_TOO_LOW` (<1.5) or `RR_ABOVE_CAP` (>6).
4. Shares = `floor(equity×1% / risk_per_share)`; `ZERO_SHARES` if < 1.
5. `_check_heat_cap` in order: A positions (`len(current)+1 > max`), B total risk (Σ risk_amount + new > 15% equity), C sector (Σ position_value in sector + new > 15% equity — note: against **equity**, not "allocated capital").
`compute_all` evaluates candidates in rank order, appends each approved setup to `virtual_positions`, and after each approval `_is_heat_cap_full` (count ≥ max or total risk ≥ 15%) blocks all remaining with `BLOCKED_BY_RISK`. A sector-blocked candidate does *not* stop later candidates in other sectors. At fill time `plan_entry_fill` re-sizes with the actual fill and `min(shares, cash/fill)`. With 1% risk and a 15% heat cap, at most ~15 full-size positions could ever fit, so the 12-position count is usually the binding cap.

### Q11. Kill switch [CODE; RUN scratch repro]

`regime_filter.RegimeFilter._apply_logic`: inactive → trigger if `nifty_close < SMA200` OR `VIX > 22` (counter reset). Active → each session if `nifty_close > SMA20` AND `VIX < 20` counter +1, else reset to 0; at 3 the switch deactivates **that day** (new tickets allowed on the release day). State persists in `regime_state` (restart-safe). Effects: no new tickets; trailing multiplier drops to 1.5×; positions still managed.
**Can it re-trigger the day after release? Yes.** Release requires only Nifty > SMA20, not > SMA200; if Nifty is still below SMA200 (or VIX jumps > 22) the next session's trigger check fires immediately. [RUN] Repro: released 03-18, re-armed 03-21 in a toy series; with Nifty still under SMA200 on the next day it re-arms on day +1. There is no cooldown.

### Q12. Costs [CODE; RUN: `test_phase1_components.py`]

`costs.CostModel`: **buy** = value×(STT 0.10% + stamp 0.015%) + (brokerage + value×(exchange 0.00297% + SEBI 0.0001%))×1.18. **Sell** = value×STT 0.10% + DP ₹15.34 + (brokerage + exchange/SEBI fees)×1.18. Tax = `max(0, gain)×stcg_pct` (0 now). Applied: simulator at fill (`buy_cost` out of cash) and at each exit (`sell_cost`); PAPER `position_service.open_position` stores `entry_costs`, `PositionLifecycleManager._log_exit` pro-rates it per exit and adds `sell_cost`; LIVE `AnalyticsLoop.record_closed_trade`. **Slippage** (0.10% each side) is baked into fill/exit prices, not into `costs`. **Excluded from "net"**: tax (`pnl_net` is pre-tax; `net_after_tax` in `trade_metrics` subtracts `tax_est`), brokerage (0), impact beyond the 0.10% slippage, STT on corporate actions, interest on cash, and cash drag. `trade_metrics.metrics_from_trades` computes `r_net = pnl_net / ((entry−stop)×shares)`.

---

## D. Validation machinery

### Q13. Matched-random baseline [CODE]

`scripts/redesigned_random_baseline.py::run_apples_to_apples_random_baseline`. For every actual trade it draws ~`n_draws_target/len(trades)` (≥5) random symbols from the screened pool *on the actual trade's signal date* (gates 1–3 + trend filter `close>SMA50>SMA200`, cached in `screened_trend_pools.json`). Matched: entry date (so market regime/seasonality), liquidity/trend universe, execution rules (`plan_entry_fill`: gap cap, slippage, R:R at fill), sizing (1% on 1M, same stops/target formulas), exits (identical `advance_one_bar` with real kill-switch/bull flags and exit slippage), costs. **Not matched**: breakout/RS/pullback signal (that's the thing being tested), portfolio constraints (no position/heat cap, no cash competition), actual equity, sector mix. Why it matters: a long-only strategy in a rising market earns money from drift; only the excess over equally-exposed random entries is attributable to the signal. The paired unit is the trade, then weekly (`max_t_bootstrap.build_weekly_paired_series`: mean of each trade's random draws, summed by entry week, minus actual).
Caveat: the random simulator reads **raw** prices for the forward path (`open_raw/high_raw...`), unlike the adjusted path in the main simulator (splits distort it), and its `net_r` is true net while the candidate column is gross (Q17).

### Q14. What Max-T adds; block bootstrap; two block lengths [CODE; RUN unit tests]

A per-config p-value tests one hypothesis; testing six configs, the best of six looks significant ~26% of the time at α=0.05 by luck. Westfall-Young step-down Max-T (`WestfallYoungMaxTBootstrap._run_with_block_size`): null-center each config's weekly paired series, resample weeks jointly across all K configs (preserves cross-correlation), studentize, take the **maximum** t across configs per replication, compare each observed t to the distribution of the maximum (step-down: successive maxima over the remaining configs, monotonicity enforced). That controls family-wise error. Block bootstrap because weekly R sums are autocorrelated (lag-1 ≈ 0.22–0.24) and i.i.d. resampling understates variance (the docstring cites FWER 18.7% at ρ=0.4). Two lengths (4 and 8, plus 2 for sensitivity) because the true dependence horizon is unknown; requiring significance at both is a robustness check. [RUN] `test_max_t_bootstrap.py::test_empirical_fwer_with_ar1_autocorrelation` **fails** (12.5% > 12%), so even block-4 over-rejects at ρ=0.4; the dual-block rule exists partly for this. Also: p-values are one-sided (`T_boot >= obs_t`) and the CI in `compute_block_bootstrap_ci` is a plain percentile bootstrap of the mean.

### Q15. Selection gates, "no pass", and the seventh config [CODE; RUN: ledger/decision file read]

Order (`scripts/select_candidate.py::run_selection`): G1 volume (pooled ≥ 80, W1 ≥ 20, W2 ≥ 20) → G2 99% block-bootstrap CI lower bound of own weekly net-R > 0 → G3 FWER-adjusted p ≤ 0.05 at block 4 and 8 → pick the best pooled expectancy finalist → G4 plateau (all adjacency-graph neighbours ≥ 75% of its expectancy and > 0) → G5 max DD ≤ 15%, PF ≥ 1.30, expectancy ≥ 0.15. No pass → `selected_config = None`, reason "No candidate passed all gates", ledger row `NONE`. Current outcome [RUN]: all six eliminated at Gate 2.
What stops a seventh config: `candidate_ids` is read from `pre_registered_configs.yaml` `role: CANDIDATE`; the YAML says `PRE_REGISTERED_LOCKED` and "trials budget exactly 6", and the hard-coded `ADJACENCY_GRAPH` only knows CFG-01..06. But **nothing technical enforces it**: someone can edit the YAML, add a config and re-run; the only barrier is git history/review (the file is not hash-pinned, and `run_selection` doesn't compare against a locked hash or ledger count). Suggested fix: store the YAML SHA in the first ledger row and refuse to run on mismatch.

### Q16. Trial ledger [CODE; RUN: file read]

`backtest/outputs/trial_ledger.csv`: one row per selection run (timestamp, commit SHA, selected config, reason, gate reached for each CFG). Purpose: count every analysis performed so multiplicity can be audited. "Append-only" is by convention only: `run_selection` opens it with mode `"a"` and writes a header only when the file is new; nothing prevents editing/deleting it (git history is the only protection). Contrast `trade_analytics_log`, which is truly append-only via SQLite triggers `trg_tal_no_update/delete` [RUN: triggers present in the real DB]. Also `--dry-run` skips the ledger, so exploratory runs are not recorded. Currently one row.

### Q17. `net_r` — definition, computation, is it net of costs? [CODE + RUN]

- **Where it is consumed**: `scripts/select_candidate.py::_compute_trade_stats` requires a `net_r` column and uses it for expectancy, PF, `max_drawdown_r`; `max_t_bootstrap.build_weekly_*_series` sums it by week.
- **Where it is *produced***: not by `backtest/run_candidate_simulations.py` or `Simulator` (trade columns include `realized_r`, `pnl_gross`, `costs`, `pnl_net`, no `net_r`). The only code that defines it is `scripts/redesigned_random_baseline.py:89` (`df["net_r"] = df["pnl_net"] / (df["shares"] * df["one_r"])`, true net) and `:393` (random draws, true net), plus `diagnose_trades_amended.py`. The committed candidate CSVs nevertheless contain a trailing `net_r` column, which no checked-in code writes.
- **Evidence it is gross [RUN]**: in `trades_candidate_CFG-01.csv` (508 trades) `max|net_r − realized_r| = 0.0`. `realized_r = (avg_exit_price − entry)/one_r` in `simulator.py`, which includes slippage but **no fees**. Recomputing true net R `pnl_net/(shares×(entry−stop))` gives mean **0.0293** vs the stored **0.0519**; total costs ₹119,341 on gross P&L ₹271,690.
- **Consequences**: Gates 2, 4 and 5 and the Max-T actual side use the gross column; the random baseline uses true net, so the paired difference is biased in the strategy's favour by roughly the cost per trade. Conclusion of "no candidate" is therefore not caused by this bias (it would only make passing easier), but any future positive result would be overstated. Fix before reuse: derive `net_r = pnl_net/(shares×(entry−stop))` in the simulator output and regenerate.

---

## E. Safety and operations

### Q18. Git-SHA lock [CODE; RUN: file/hash comparison]

`live_runner/git_lock.verify_git_lock`: (1) `authorized_deployment.json` must exist with `authorized_sha`; (2) working tree clean (`git status --porcelain`, so ignored files like `.env`, `*.db` don't count); (3) HEAD == authorized SHA, or HEAD~1 == authorized SHA and HEAD's diff is only the auth file (the pattern `authorize_live.py` produces by committing the file); (4) `git hash-object strategy_config.yaml` == stored hash. Called in `main.lifespan` and `scheduler.run_eod_pipeline`. `authorize_live.py` is the only writer and re-verifies the audit.
**Current state [RUN]**: authorized SHA `002f579…`, config hash `6e71f2c…` vs HEAD `be4295a…`, config `c7887a3…` → the engine would refuse to start (`SYSTEM_LOCKED_CODE_MODIFIED`).
**What it blocks**: any commit to any tracked file after authorization, and any config edit.
**Mistaken bypasses**: running `EODPipeline.run` or scripts directly (no lock); anyone committing a hand-edited `authorized_deployment.json` as a lone commit on top of the authorized SHA; re-authorizing without regenerating audits (it only checks audit hash, config hash, gates); `.gitignore`d inputs changing behaviour (`.env` `ACCOUNT_EQUITY`, the DB, `backtest/outputs/audit.json` ignored in `.gitignore`); lock only checked at startup/scheduled fire, not when routers run; `mode` in the auth file isn't compared to `runtime.mode` (the committed file has no mode key).

### Q19. Idempotency guard [CODE only; `tests/integration/test_idempotency.py` was not in my test subset]

`IdempotencyGuard.acquire`: `pipeline_run_log.run_date` is UNIQUE. COMPLETE → returns False (pipeline raises `AlreadyRunError`); RUNNING → `CurrentlyRunningError`; FAILED → set to RUNNING and retry; new → insert RUNNING, `IntegrityError` → rollback/False.
**Failure modes**: (a) crash mid-run leaves RUNNING, blocking all retries until someone edits the row; (b) the guard only protects the *log row* — pipeline side effects (ingestion deletes/reinserts, `regime_state` upsert, PAPER fills, watchlist writes) are not transactional across the run, so a FAILED retry replays partially-applied effects (e.g. paper fills already opened; `open_pending_tickets` filters on PENDING so it's safe; `expire_stale_tickets` fine); (c) `scheduler.run_eod_pipeline` runs `DELETE FROM pipeline_run_log WHERE run_date > last_date` before catch-up, deliberately defeating the guard for any date after the last equity bar; (d) it takes `run_date` as given — passing the wrong date creates a different lock.

### Q20. What proves the engine cannot place orders [CODE; RUN]

- `tests/unit/test_regulatory_barrier.py` [RUN, passes]: no FastAPI route path outside `/positions/open|close` matches `order|place|execute|trade|buy|sell|broker|kite`; no `live_runner`/`engine_core` source contains `place_order|modify_order|kiteconnect|selenium|playwright|pyautogui|pywinauto`.
- Code facts: `/positions/open` and `/close` only write DB rows; there is no broker client in the runtime path (Kite is used only in optional ingestors under `data/`, which the test does not scan).
- Limits: it is a static grep, not proof — `data/` and `scripts/` are outside the scan, and an HTTP call via `requests` would not match. A stronger guard: allow-list outbound hosts in tests, and scan the whole repo.

---

## F. Honest assessment

### Q21. Three weakest parts

1. **R-metric integrity and the selection statistics** [RUN] — `net_r` is gross in the candidate CSVs and unproduced by checked-in code, while the baseline's `net_r` is net; all gates are computed on it (Q17). Also `redesigned_random_baseline` ignores portfolio constraints, hardcodes dates (`2019-10-01`, `2026-10-16`, window ends), and reads raw (not adjusted) forward prices; pre-registered text claims 198-trade/1000-draw matching that the code does not do.
2. **Corporate actions and shared state in the engine** [RUN for split repro; CODE for rest]:
   - A split during a hold produces a false stop-out: both `Simulator._bar` and `PositionLifecycleManager.process_single` re-adjust history with `as_of=today` while `PosState.entry_price/stops` stay in the old price basis. [RUN] scratch repro: `STOP_HIT, GAP_THROUGH_STOP` on the ex-date for a 1:2 split. The simulator even computes `has_ca` for the bar and discards it for open positions.
   - Because the real `corporate_actions_log` is empty [RUN], backtests also ran unadjusted (crashes look like gaps).
   - The simulator writes `regime_state` into the shared DB, so hysteresis state at the start of a window depends on whichever run last wrote the preceding date, and a backtest mutates the table live trading reads.
   - `shares_outstanding` is a single 2020 snapshot [RUN], so market cap isn't PIT and pre-2020 test windows are unusable as is.
3. **Operational/data-model drift** [CODE + RUN for DB checks]:
   - Real-DB CHECK constraints reject `PARABOLIC_TRAILING` and `PARTIAL_PROFIT` rows; `process_all` catches and logs exceptions, so PAPER positions can silently fail to update.
   - `get_live_equity` sums `pnl_gross` (not net); pipeline guard uses `pnl_net`; PAPER equity uses net−tax.
   - Event gates: live 14 days vs sim 7 days; live ASM/earnings fail-open with empty tables; the scheduler wipes idempotency rows.
   - Authorization file stale and unlinked from the current config; `live_guardrails` missing; hard-coded `atr_projection_mult=3.0`, `"/3"` in log text.
   - Test gaps: the sim-vs-live tests only compare exits on synthetic data (no entry/ticket parity, no split, no fill), `test_baseline_reproducibility` depends on the real DB/CSV hashes, and one Max-T test currently fails.

### Q22. Two (really several) spec-vs-code disagreements [CODE; docs quoted]

1. **Kill-switch thresholds**: `regime_filter.py` docstring and README: trigger VIX > 20, re-entry Nifty > 50-SMA and VIX < 18. Code/config: VIX > 22, Nifty > **20**-SMA (`nifty_reentry_sma_period: 20`), VIX < 20, and the dataclass field `nifty_sma50` holds the 20-day SMA (`regime_filter.evaluate`).
2. **Stop/size/lifecycle parameters**: README: stop = max(entry − 1.5×ATR, Donchian-20), 10 positions, 10% heat, 15-session decay, 2× trail. Code: min-price (wider) of 2.0×ATR and Donchian-30, 12 positions, 15% heat, 20-session decay, 2.5× trail. (The map says to leave the config alone; the README/docstrings are what's stale.)
3. Bonus: sector cap is "% of allocated capital" in spec/config comment but computed against total equity (`_check_heat_cap`); README says the scheduler fires at 5 PM, code uses 19:00 for bhavcopy; `schema.sql` allows a four-state `position_state`.

### Q23. Testing a 52-week-high momentum rotation (1–3 month holds, monthly rotation)

Reuse unchanged: data layer, `adjustments`, `candidate_builder`, `UniverseScreener` gates 1–3, `RegimeFilter`/`regime_gates`, `CostModel`, `trade_metrics`, `plan_entry_fill`, `max_t_bootstrap`, the random-baseline pattern, `select_candidate` gate framework (as a template), git lock/authorization.
Must change/add:
- `engine_core/entry_filters.py`: a ranking function by `close/high252` (adjusted) with deterministic ties; no breakout/trend-gate dependency.
- Exit logic: monthly rotation (rank-drop/time-based exit) replaces the stop/R:R-target machinery; add a new pure function beside `advance_one_bar` (do not branch inside it) with a protective stop only if pre-registered.
- Sizing: equal-weight or risk-parity target portfolio; today's `risk_sizing` R:R/target gates (`RR_TOO_LOW`) are meaningless for a rotation and must be bypassed via a separate sizing path (not config hacks).
- `backtest/simulator.py` (or a sibling): rebalance-date scheduling and diff-to-target ticket generation; same for `pipeline._run_screening`.
- A new pre-registered YAML (configs, adjacency, gates, trials budget), a fresh selection script using the same machinery, and a baseline matched on rebalance dates/universe.
Must NOT change: raw-vs-adjusted rules, costs, Max-T/bootstrap code (reuse), TEST-window protocol (2015–2019 single shot, config frozen via `--freeze`/`FROZEN.sha`), and no retroactive gate loosening. First fix: correct `net_r` (Q17), fix the split-mid-hold handling and fill the corporate-action and PIT shares tables (needed for 1–3 month holds), then re-baseline. Because holding periods are far longer, the weekly-sum test statistic in `build_weekly_paired_series` (keyed on *entry* week) needs rethinking (overlapping trades inflate autocorrelation; use portfolio-level periodic returns).
Anyone who cannot answer Q17 and Q23 isn't ready to write strategy code — this answer plus the Q17 evidence above are my self-check.

### Q24. What I didn't understand / questions for the owner

1. Which code produced the `net_r` column in the committed candidate CSVs, and were Step 3 results meant to be gross? Which R definition is authoritative for the gates?
2. Why is `corporate_actions_log` empty, and were all backtests (including the 198-trade baseline) run on unadjusted prices? Same for the single-date `shares_outstanding` snapshot — is a PIT source planned?
3. Was Step 3 intentionally run with Pass 1 (no ASM/earnings exclusions)? The pre-registered text speaks of "screened liquid universe excluding ASM/GSM".
4. Is the 19:00 scheduler time (vs 17:00 in the docs) intentional? Is the stale `authorized_deployment.json` expected given no strategy is selected?
5. Should the real DB's `schema.sql` CHECK constraints be migrated to match the ORM? Are PAPER positions currently being opened/advanced (the DB shows none)?
6. What rule decides the tax rate (`stcg_tax_pct`) and whether net R should be after-tax?
7. For the new strategy: portfolio-level vs per-trade evaluation, expected number of names, rebalance day, and whether the kill switch still applies.
8. Was the Max-T test's own FWER failure (12.5% vs 12% bound) known, and should it block reuse of `max_t_bootstrap` as pre-registered?
9. What is the intended behaviour when a corporate action hits an open position in LIVE (owner adjusts manually?) since the engine will flag a false stop.

---

### Self-rating (per the guide's 0–3 scale)
Section B ≈ 2 (code refs, data state checked by query, no PIT test run). Section C ≈ 2–3 (state machine and kill switch reproduced; sizing/costs code-read with existing unit tests passing). Section D ≈ 2–3 (Q17 verified by recomputation; Max-T by unit tests, one failing). Q17 and Q23: answered with evidence above.
