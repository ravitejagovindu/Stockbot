# StockBot (FInsight) — Backend Codebase Understanding

Repo: `F:\Projects\Ravi\StockBot`, HEAD `be4295a` (Step 3 candidate simulations; "NO CANDIDATE SELECTED").
Scope: backend only (UI ignored). Everything below was read from the code; items marked **[RUN]** were also reproduced by running tests, scratch repros, or read-only queries. Where this differs from `STOCKBOT_ONBOARDING.md`, the code wins and the difference is listed in section 11.

---

## 1. What the system is

A personal, rule-based EOD screening and trade-management engine for NSE. It never sends orders. It produces `daily_watchlist` rows (Trade Tickets), the owner fills them manually, and the engine tracks the positions. One rule set (`engine_core`) is used three ways: backtest (`backtest/simulator.py`), paper (`live_runner/paper_trader.py` + pipeline) and live (pipeline + operator-reported fills).

Status: the breakout strategy (CFG-00) and six pre-registered variants (CFG-01..06) were tested; all six died at Gate 2 (`trial_ledger.csv`: `2,2,2,2,2,2`). No strategy is authorized.

## 2. Dependency map

```
strategy_config.yaml ─► config.load_config (lru_cache, _validate_config)
                          │
data/db (models, schema.sql, connection) ◄── data/ingestion/*  (raw OHLCV, shares, corp-action LOG, ASM/GSM, earnings)
                          │
engine_core.candidate_builder ─► adjustments (in-memory, PIT)
engine_core: indicators → adjustments → lifecycle_rules → universe_screener → entry_filters → risk_sizing
             regime_filter / regime_gates · position_lifecycle · costs · trade_metrics · equity/mode/ledger · max_t_bootstrap
                          │                                     │
backtest/simulator.py ◄───┘             live_runner/pipeline.py ◄┘
   │  run_backtest.py / run_candidate_simulations.py                 │ scheduler.py (APScheduler), main.py (FastAPI), routers
   ▼                                                                │ paper_trader.py, idempotency.py, git_lock.py
scripts/redesigned_random_baseline.py ─► scripts/select_candidate.py ─► selection_decision.json + trial_ledger.csv
audit.json + config hash ─► authorize_live.py ─► authorized_deployment.json ─► git_lock.verify_git_lock
```

The two halves (validation vs operations) meet only in `engine_core`.

## 3. Configuration (`strategy_config.yaml`, `config.py`)

`load_config()` loads once (lru_cache) and validates: required sections, `min_rr_ratio >= 1`, `vix_reentry < vix_kill`, `reentry SMA < kill SMA`. The effective values (these are what the code runs, not what README says):

| Area | Value |
|---|---|
| Universe | mcap > ₹5,000 cr, 20-day ADTV > ₹25 cr, listing age ≥ 252 trading days; volume-breakout gate 0 (off); RS gate 0 (off) |
| Mode | `runtime.mode: PAPER` (only switch), `paper_start_equity` 1,000,000 |
| Execution | NEXT_OPEN; entry/exit slippage 0.10%; max gap-up 3%; min R:R at fill 1.5 |
| Costs | STT 0.10% buy+sell; exchange 0.00297%; SEBI 0.0001%; stamp 0.015% buy; GST 18% on fees; DP ₹15.34/sell; brokerage 0; **tax 0** |
| Macro | kill if Nifty < SMA200 or VIX > 22; re-entry needs Nifty > SMA20 and VIX < 20 for 3 sessions; `bull_entry_sma_period` 50 (pauses *new* entries in bull when Nifty < SMA50) |
| Risk | ATR14, stop A = entry − 2.0×ATR, stop B = Donchian-30 low, live stop = min(A,B); 1% risk/trade; min R:R 1.5, max cap 6; max positions 12 (bull 12); total heat 15%; sector cap 15% of equity; trail 2.5×ATR (1.5× in kill switch) |
| Entry filters | close > SMA50 > SMA200; close ≥ prior 20-day high (breakout); RS 63d only for ranking |
| Lifecycle | time decay 20 sessions; parabolic (3 ATR in 5 days → 1×ATR trail); partial 12% at +1R; ratchet rungs (+1R→0R, +2R→+1R, +3R→+2R) *off in bull* |
| Gates | DD < 15%, alpha ≥ −2%, expectancy ≥ 0.15R, PF ≥ 1.3, trades ≥ 40 |
| Windows | TUNE 2020–21, 2022-01..2026-09-30; TEST 2015–19 (untouched) |

No `live_guardrails` section exists in the YAML; the pipeline's LIVE drawdown guard reads `config.get("live_guardrails", {})` and is therefore inert unless added.

## 4. Data layer

Tables (ORM in `data/db/models.py`, DDL in `data/db/schema.sql`): `market_data_lake` (raw OHLCV, UNIQUE symbol+date; includes `NIFTY50_INDEX`, `INDIA_VIX`), `shares_outstanding`, `corporate_actions_log`, `asm_gsm_list`, `earnings_calendar`, `regime_state`, `active_positions`, `trade_analytics_log` (append-only triggers), `pipeline_run_log` (UNIQUE run_date), `daily_watchlist` (UNIQUE run_date+symbol), `account_ledger`, `securities_master` (official listing dates).

**Invariants**: raw prices are stored as-is; adjustments exist only in memory (`adjustments.get_adjusted_series`). ADTV and market cap use raw only (`compute_adtv`, `compute_market_cap`). The lake is append-only in spirit, but `BhavcopyIngestor.ingest` deletes the day's equity rows before re-inserting and the pipeline's yfinance index path deletes then appends index rows.

**What the real DB actually contains [RUN, read-only on `finsight.db`, ~1 GB]**:
- `market_data_lake`: Nifty 2015-11-09..2026-10-16, VIX 2014-05-14..2026-10-16, RELIANCE 2013-01-01..2026-10-16.
- `corporate_actions_log`: **0 rows**. `asm_gsm_list`: **0**. `earnings_calendar`: **0**.
- `shares_outstanding`: 2,217 rows, **all with effective_date 2020-01-01** (one snapshot per symbol) — so "point-in-time" market cap uses a 2020 share count on every date, and any pre-2020 `eval_date` finds no shares row (`_get_latest_price_and_shares` returns `None` → `NO_PRICE_DATA`).
- `securities_master`: 2,965. `regime_state`: 1,747 rows (2019-10-01..2026-10-16, 685 kill-switch days). `pipeline_run_log`: 11 COMPLETE. `active_positions`, `trade_analytics_log`, `daily_watchlist`, `account_ledger`: empty.
- The real `active_positions` has `CHECK(position_state IN ('INITIAL_RISK','RISK_FREE_1_TO_1','TRAILING_ATR','PENDING_MANUAL_EXIT'))` and `trade_analytics_log` has `CHECK(exit_reason IN ('MANUAL','STOP_HIT','TIME_DECAY','EARNINGS_EXIT','OTHER'))` (from `schema.sql`; `init_db()` runs that file, not the ORM). The code writes state `PARABOLIC_TRAILING` and exit reason `PARTIAL_PROFIT`, neither of which these allow (the transient `CLOSED` value is set on a row that is then deleted, so SQLAlchemy emits only the DELETE). Code-read plus schema-confirmed; I did not run PAPER processing against the real DB. Failures inside `process_all` are caught and only logged, so they would be silent. See section 11.

Consequence for backtests: with an empty `corporate_actions_log`, the backtests ran on **unadjusted** prices (splits/bonuses in 2020–26 appear as price crashes), and with empty ASM/earnings tables, Pass 2 inputs come only from CSV files in `backtest/outputs`.

## 5. `engine_core` module by module

- **indicators.py** — pure `sma`, `rma` (Wilder, SMA-seeded), `atr` (TR from prev close; first bar = H−L), `donchian_low/high`.
- **adjustments.py** — `compute_row_factors(index, actions, as_of_date)`: for each SPLIT/BONUS with `ex_date <= as_of_date`, bars strictly before ex-date are scaled (split factor num/den; bonus den/(den+num)). Actions after `as_of_date` are ignored (PIT-safe). Dividends ignored. Output has no volume.
- **lifecycle_rules.py** — pure state machine. `advance_one_bar(pos, bar, ctx, rules, exit_slip)` order: (0) `PENDING_MANUAL_EXIT` → exit at today's open ×slip; (1) `bar.low <= live_stop` → `STOP_HIT` at `min(open, stop)`×slip (gap-aware), flag `GAP_THROUGH_STOP` if open < stop; (2) `days_held++`, `highest_high`; (3) INITIAL_RISK → RISK_FREE_1_TO_1 if high ≥ entry+1R (stop = max(stop, entry)), **else** if `days_held ≥ 20` → PENDING_MANUAL_EXIT (graduation wins on the same day); RISK_FREE → TRAILING_ATR when high > target; TRAILING: parabolic test (close − close_n_ago ≥ 3×ATR) → PARABOLIC_TRAILING, else stop = max(stop, HH − 2.5×ATR); (4) ratchet rungs (skipped in bull); (5) partial: first rung at +1R sells 12% of remaining shares at `max(open, limit)`. `plan_entry_fill(...)` decides a next-open fill: gap-through-stop, gap-up cap, slippage, R:R at fill, re-size `floor(equity×1%/risk_ps)` capped by cash.
- **candidate_builder.py** — `build_candidate_dicts`: last `resistance_lookback_days+30` raw bars ≤ eval_date, all corp actions, adjusted series as of eval_date, sector (`sector_map.sector_for`, default `UNKNOWN`).
- **universe_screener.py** — `screen_single`: G1 market cap (raw close × PIT shares), G2 ADTV, G3 listing age (securities_master → on-demand NSE fetch → first lake date; ≥550 calendar days is auto-seasoned), G4 ASM/GSM *snapshot* lookup, G5 earnings within 14 calendar days, G6 volume breakout (off), G7 RS percentile (off). G4/G5 only when `apply_event_gates=True`.
- **entry_filters.py** — `apply_entry_filters`: trend (close>SMA50>SMA200), breakout (close ≥ max high of prior 20), optional pullback, optional universe RS cutoff (`rs_rank_percentile`), then deterministic sort by `rs_3m` desc, symbol asc.
- **risk_sizing.py** — `RiskAndSizingEngine.compute_setup` / `compute_all` (details in answer Q10).
- **regime_filter.py** — stateful kill switch with persisted hysteresis (`regime_state`). **regime_gates.py** — stateless `is_bull`, `bull_correction_active`, `nifty_sma`.
- **position_lifecycle.py** — DB-backed daily processing of `active_positions`; builds a `PosState`, calls `advance_one_bar`, writes back. PAPER: logs exits to `trade_analytics_log` and deletes the position on close. LIVE: advisory only (`pending_close_reason`, `ACTION_REQUIRED_*`, `BOOK_PARTIAL_*` flags).
- **costs.py / trade_metrics.py** — `CostModel.buy_cost/sell_cost/tax_on_gain`; `metrics_from_trades` (true net R = `pnl_net/((entry−stop)×shares)`, PF/DD on after-tax P&L), `sharpe_from_equity`.
- **equity.py / mode.py / position_service.py / account_ledger.py** — PAPER equity = start + Σ(pnl_net − tax) (realized only); `current_mode`; `open_position` (shared creator; sets entry_costs, marks ticket OPENED); LIVE equity = ledger deposits/withdrawals + Σ **pnl_gross** of LIVE trades.
- **max_t_bootstrap.py** — weekly series builders, circular block resampling, Westfall-Young step-down Max-T.
- **analytics_loop.py** — LIVE close recording and decay report. **preflight.py** — synthetic split spot-check run before each pipeline. **sector_map.py** — CSV lookup (raises if file missing).

## 6. The simulator (`backtest/simulator.py::Simulator.run`)

Per trading day (days = distinct lake dates in window): (0) `RegimeFilter.evaluate(d)` (this *writes* `regime_state`) → `ks`, `bull`; (1) fill yesterday's tickets in rank order via `plan_entry_fill` using MTM equity and cash, skipping if no bar / already held / corporate action on the date; (2) advance every open position with `advance_one_bar` (including those filled this morning), book exit costs, close → trade row; (3) mark to market → `curve[d]`; (4) if kill switch or bull-correction, no tickets; else screen all symbols with `screen_single(apply_event_gates=False)`, apply Pass-2 `Exclusions` if given, `build_candidate_dicts` → `apply_entry_filters` → `sizer.compute_all(..., is_bull_regime=bull)` → non-blocked setups become tomorrow's `pending`. Leftover positions are force-closed at the last close with reason `END_OF_WINDOW`.

## 7. The live pipeline (`live_runner/pipeline.py::EODPipeline.run`)

`IdempotencyGuard.acquire` → ingestion (bhavcopy + yfinance indices, or Kite) → `_assert_data_freshness` (Nifty latest ≥ eval_date) → `assert_preflight_spot_check` → `RegimeFilter.evaluate` → (PAPER) `expire_stale_tickets` + `open_pending_tickets` → `PositionLifecycleManager.process_all` (always) → (LIVE) drawdown guard (inert, see §3) → if not kill switch and not bull-correction: `UniverseScreener.screen_all` (event gates ON) → `build_candidate_dicts` → `apply_entry_filters` → `compute_all` → `_persist_watchlist` (approved **and** blocked rows) → `guard.complete`.

### Parity table (sim vs live)

| Step | Simulator | Live/Paper | Shared? |
|---|---|---|---|
| Regime | `RegimeFilter.evaluate` | same | yes |
| Screening gates 1–3 | `screen_single(apply_event_gates=False)` | `screen_all(apply_event_gates=True)` | same class, different flag |
| Event exclusions | `Exclusions` (historical ASM intervals, earnings window `min(14, 7)=7` days) | live ASM snapshot + earnings within 14 days | **no** |
| Candidate build / filters / sizing | `build_candidate_dicts`, `apply_entry_filters`, `compute_all` | same | yes |
| Equity for sizing | cash + MTM of open positions | PAPER: start + realized net−tax; LIVE: ledger + gross realized | **no** |
| Fill | `plan_entry_fill` | `paper_trader.open_pending_tickets` → `plan_entry_fill` (LIVE: operator fill via `/positions/open`) | yes (PAPER) |
| Daily lifecycle | `advance_one_bar` inline | `PositionLifecycleManager` → `advance_one_bar` | yes |
| Costs | `CostModel` | `CostModel` (+ `entry_costs` pro-rated per exit) | yes |
| Bull flag to sizer | passed explicitly | DB lookup inside sizer | equivalent |

## 8. Validation machinery

- **Pass 1 / Pass 2**: same `Simulator`; Pass 2 passes an `Exclusions` loaded fail-closed from `backtest/outputs/pending_asm_gsm_matches_<regime>.csv` (only `status == VERIFIED` rows count) and `historical_earnings_<regime>.csv`; any missing/unverified input raises unless `--allow-unverified`, and `applied=False` makes `compliance_applied` false, which the audit gate requires.
- **Audit / authorize**: `audit_generator.summarize` computes after-tax CAGR vs Nifty, DD, Sharpe, trade metrics; `generate` evaluates gates and writes `audit.json` + `audit.sha256`; `authorize_live.py` re-verifies hash, config SHA, clean tree, recomputes gates, requires `docs/PAPER_RESULT.json passed` for LIVE, then writes and commits `authorized_deployment.json`.
- **Pre-registration**: `backtest/pre_registered_configs.yaml` (CFG-00 baseline + CFG-01..06 factorial: trend-continuation vs SMA20 pullback × RS top 50/40/30, gap cap 1.5%); `run_candidate_simulations.py` applies only `entry_filters` and `execution` overrides and runs W1/W2.
- **Random baseline** (`scripts/redesigned_random_baseline.py`): for each actual trade, draws symbols from the pool on the signal date (gates 1–3 + trend filter), fills at the same entry date's open with the same `plan_entry_fill`, runs the same `advance_one_bar` lifecycle with true regime flags, and records true net R (`pnl_net / (shares×one_r)`).
- **Selection** (`scripts/select_candidate.py`): G1 volume (pooled ≥ 80, each window ≥ 20) → G2 99% circular-block-bootstrap CI (block 4, B=2000) of own weekly R-sum > 0 → G3 Max-T FWER ≤ 0.05 at block 4 **and** 8 (B=10,000) → G4 plateau on the single best finalist (neighbours ≥ 75% of its expectancy and > 0) → G5 DD ≤ 15%, PF ≥ 1.3, expectancy ≥ 0.15. Writes `selection_decision.json` and appends to `trial_ledger.csv`.

## 9. Safety and operations

- `git_lock.verify_git_lock`: authorization file exists → clean tree → HEAD equals `authorized_sha` (or parent equals it and the diff is only `authorized_deployment.json`) → `git hash-object strategy_config.yaml` equals stored hash. Run at FastAPI startup and before each scheduled run; not enforced when calling `EODPipeline` directly.
- **Current state [RUN]**: authorized SHA `002f579…`, config hash `6e71f2c…`; HEAD is `be4295a…`, current config hash `c7887a3…`. The engine would exit with `SYSTEM_LOCKED_CODE_MODIFIED`. The file also has no `mode` key.
- `IdempotencyGuard`: row per `run_date` (UNIQUE); COMPLETE → skip, RUNNING → `CurrentlyRunningError`, FAILED → retry. The scheduler's catch-up path *deletes* `pipeline_run_log` rows after the last equity date before re-running.
- Scheduler: cron 19:00 IST for `eod_source: bhavcopy` (17:00 otherwise); catch-up loops over trading days from yfinance's `^NSEI` calendar.
- Regulatory barrier: `tests/unit/test_regulatory_barrier.py` scans FastAPI routes for order-like names (allowing `/positions/open|close`) and `live_runner`/`engine_core` source for broker/automation tokens. **[RUN] passes.**

## 10. Test status [RUN]

`pytest` on lifecycle rules, indicators, adjustments, Max-T, regulatory barrier and both sim-vs-live integration tests: **82 passed, 1 failed**. The failure is `test_max_t_bootstrap.py::test_empirical_fwer_with_ar1_autocorrelation`: empirical FWER 12.5% (25/200) at ρ=0.4 vs the test's own ≤ 12% bound (and nominal 5%) — the 4-week block bootstrap does not fully control FWER under that autocorrelation, which is why the pre-registration demands significance at block 8 too. I deliberately did not run `test_baseline_reproducibility.py` or any Simulator run against the real DB (the simulator writes `regime_state`).

Scratch reproductions (in-memory SQLite, no repo changes):
- Held position + 1:2 split on a later bar → `PositionLifecycleManager` returns `STOP_HIT, GAP_THROUGH_STOP, POSITION_CLOSED` (a false stop-out).
- Kill switch: triggered 03-11, released 03-18 after three qualifying sessions, re-triggered 03-21 when Nifty fell back under its kill SMA.

## 11. Verified differences between the map/README and the code

1. `net_r` in candidate CSVs is gross (see answers Q17); no code in the repo writes that column.
2. `engine_core/regime_filter.py` docstring and `README.md` describe VIX>20 / SMA50 / VIX<18; code uses config (22 / SMA20 / 20). `RegimeState.nifty_sma50` holds the *20*-day SMA.
3. README: stop = 1.5×ATR or Donchian-20, 10 positions, 10% heat, 15-session decay, 2× trail → config is 2.0×/Donchian-30, 12, 15%, 20, 2.5×. `position_lifecycle.py` docstring says 15 sessions/2×ATR; `/positions/states` says 15 sessions/2× ATR.
4. Map says "fires 5 PM IST"; scheduler uses 19:00 when `eod_source=bhavcopy`.
5. Map says corporate actions/shares/ASM/earnings are "known gaps"; in the real DB they are *empty* (corp actions, ASM, earnings) or a single 2020 snapshot (shares).
6. `schema.sql` CHECK constraints (present in the real DB) disagree with the state machine (`PARABOLIC_TRAILING` position state; `PARTIAL_PROFIT` exit reason).
7. `pre_registered_configs.yaml` `definitions.random_baseline` claims 1000 draws "matched to all 198 actual entry dates"; the generator uses `max(500, n_trades×5)` draws for candidates, and hardcodes dates (`2019-10-01`, `2026-10-16`, window ends) in the baseline script.
