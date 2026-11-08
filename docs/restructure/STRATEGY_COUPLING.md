# Where the old strategy leaks into shared code (Phase 1, analysis only)

Read from the code at tag `pre-restructure`. "Generic" = stays (and moves to the package named); "old" = leaves the shared tree with the old strategy (recoverable from the tag). Anything I could not settle is marked **Q** and listed in `UNDECIDED.md`.

## 1. `engine_core/entry_filters.py` (163 lines) — entirely old strategy
`passes_trend_filter` (close > SMA50 > SMA200), `passes_breakout` (close >= prior 20-day high), `passes_pullback`, `rs_return`, `compute_universe_rs_cutoff`, `apply_rs_rank_percentile`, `apply_entry_filters` (ordered use of the config `entry_filters` section). Nothing generic. The whole file leaves; its two callers are `backtest/simulator.py` and `live_runner/pipeline.py`. (The pool definition in the F9 trade library re-implements the same trend filter on its own, so that script is unaffected.)

## 2. `engine_core/risk_sizing.py` (658 lines) — mixed
| part | class | goes to |
|---|---|---|
| `TradeSetup` dataclass (entry, stop, target, shares, risk, R:R, block reason) | generic shape, but carries R:R and a target | `risk` as the proposal/sizing record; target becomes optional (Q3) |
| Stop A = entry − 2 × ATR14; Stop B = 30-session Donchian low; live stop = min(A, B) (`compute_setup`, lines ~250-300) | **old** — the stop now comes from the strategy's proposal | old strategy |
| Target = 252-session high (`donchian_high(adj_high, resistance_lookback)`), projected R:R, `min_rr_ratio` reject, `max_rr_cap` reject (lines ~268-345) | **old** | old strategy (R:R gate: Q3) |
| Shares = floor(equity × 1% / (entry − stop)), minimum checks | generic | `risk.sizing` |
| Heat and sector caps `_check_heat_cap`, `_is_heat_cap_full`: open-position count, total portfolio risk %, sector exposure % of allocated capital, evaluated sequentially across candidates on projected post-trade values | generic | `risk.caps` (plus a multi-strategy arbitration function, Phase 5) |
| `_is_bull_regime` / `max_concurrent_positions_bull` | regime-dependent cap, same value as the normal cap today | **Q4** |
| Reads `candidate["adjusted_ohlcv"]`, `["raw_ohlcv"]`, ORM models | data access leak | disappears: sizing takes plain numbers |
Imports `data.db.models` (ORM) and `indicators` — both must go for `risk` to meet the boundary rule.

## 3. Lifecycle: `engine_core/lifecycle_rules.py` (254) and `position_lifecycle.py` (606)
`lifecycle_rules.py` is pure (no DB). Its parts:
| part | class |
|---|---|
| `LifecycleRules.from_config` reading `trade_management.time_decay_sessions`, `risk.trailing_*`, `parabolic_stop`, `partial_profit`, `profit_ratchet` | **old** |
| `PosState` (entry, initial/live stop, target, state, days_held, highest high, shares, partial counters) | generic skeleton, but the state names INITIAL_RISK / RISK_FREE_1_TO_1 / TRAILING_ATR / PARABOLIC_TRAILING / PENDING_MANUAL_EXIT are the old machine |
| `advance_one_bar`: gap-aware stop fill, time-decay exit at 20 sessions, breakeven at +1R, trail 2.5 × ATR after the target is passed, parabolic tightening, ratchet rungs (+1R→0, +2R→+1R, +3R→+2R), 12% partial at +1R | **old** — this is the exit policy that becomes a separate pluggable object |
| stop-hit fill rule `min(open, stop)` × (1 − slippage) | generic execution assumption, currently inside `advance_one_bar` |
| `rescale_for_action` (split/bonus rebasing of price state and share count, fractional remainder in cash) | generic — stays (engine) |
| `plan_entry_fill`: skip if open ≤ stop, skip if open > ticket entry × 1.03, fill at open × 1.001, R:R at fill ≥ 1.5, shares from risk % and cash | fill and sizing generic; **R:R-at-fill and gap-up cap are tied to a target and to values chosen for the old strategy (Q3)** |
`position_lifecycle.py` (DB-bound `PositionLifecycleManager`): reads ORM positions, applies `advance_one_bar`, writes updates, earnings alert (`earnings_alert_days`), kill-switch and bull lookups, corporate-action application via `corporate_action_events`. Generic: corporate-action application, earnings alert. Old: everything that calls the exit rules. Both are replaced by the engine's state object plus the exit policy.

## 4. `engine_core/indicators.py` (265) — generic
`sma`, `rma`, `atr` (Wilder), `donchian_low`, `donchian_high`, `_validate_period`. Checked: no strategy logic and no config reads (one docstring mentions `data.resistance_lookback_days`). Moves to `data` as shared functions unchanged.

## 5. `engine_core/universe_screener.py` (632)
`UniverseScreener` is a seven-gate screen reading the ORM and the config:
| gate | class | note |
|---|---|---|
| fund/ETF exclusion (`fund_etf_symbols.csv`) | generic | universe |
| 1 market cap > Rs 5,000 cr (raw close × `shares_outstanding` snapshot) | generic in form; **parked** | KI-001; value and code unchanged, no replacement designed |
| 2 raw ADTV20 ≥ Rs 25 cr | generic | universe |
| 3 listing age ≥ 252 sessions | generic | universe |
| 4 ASM/GSM | generic | live uses the table; backtest uses `backtest/exclusions.py` (fail-closed) |
| 5 binary event within 14 days (earnings/corporate action) | generic in form | Q10 (`binary_event_block_days` home) |
| 6 volume breakout ≥ N × average (disabled, multiplier 0) | **old** | |
| 7 relative-strength top percentile (disabled, 0) | **old** | |
Also `_compute_rs_threshold` (old). The screener imports `data.db.models` and `data.ingestion.securities_ingestor`.

## 6. Other leaks
- `candidate_builder.py` (92): builds candidate dicts (adjusted + raw OHLCV, sector, ATR, resistance lookback = 252 + 30 buffer) — the 252 is the old strategy's target lookback; the "bar context" for the lifecycle is old. Generic part is "adjusted bars as of date T", which becomes the as-of view.
- `regime_filter.py` (487) and `regime_gates.py` (43): Nifty/VIX kill switch with hysteresis (Nifty < SMA200 or VIX > 22 on; re-entry needs Nifty > SMA20, VIX < 20, 3 sessions), bull = Nifty > SMA50. Persists state in the DB. It is a market-wide rule not obviously tied to one strategy, but `profit_ratchet.active_in_bull`, the kill-switch trailing multiplier and the bull position cap read it. **Q4.**
- `backtest/simulator.py`: calls entry filters, screener, risk sizing, regime and lifecycle directly, so the backtest loop and the live loop currently share *pieces* but not a single decision function.
- `live_runner/pipeline.py` (394): the EOD orchestrator calls the same pieces in its own order and also performs ingestion (imports the ingestors) — live and backtest duplicate the orchestration.
- `strategy_config.yaml` mixes shared and old-strategy keys in one file; `config.load_config` validates `risk.min_rr_ratio` etc. (`config.py:43`).
- `scripts/redesigned_random_baseline.py`: the matched-random baseline hard-codes the old universe gates, the 3% gap cap, R:R ≥ 1.5 at fill and `advance_one_bar` exits — it is validation machinery with the old strategy inside it.
- `backtest/audit_generator.py`, `authorize_live.py`, `generate_confidence_report.py`: read `gates` (old pass criteria) and the audit JSON.

## 7. Config keys
All keys classified in `CONFIG_KEYS.csv` (81 keys): shared, old-strategy or undecided with the question number.

## 8. Dependencies that will break the boundary rules (from `ARCHITECTURE_CURRENT.md`)
- 10 `engine_core → data` edges, 9 of them `data.db.models` (ORM): `account_ledger`, `analytics_loop`, `candidate_builder`, `position_lifecycle`, `position_service`, `regime_filter`, `regime_gates`, `risk_sizing`, `universe_screener`. The engine and risk packages cannot touch a session, so each of these needs the ORM removed.
- `live_runner → engine_core`: 25 edges; `live_runner.pipeline` imports a network library (ingestion inside the EOD runner).
- `scripts → live_runner`: one (`paper_report → git_lock`), dies with the lock.
