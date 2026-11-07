# FInsight Trading Engine — Orientation Map & Comprehension Questions

Based on the repo snapshot at zip commit `be4295a717b4…` (Step 3 candidate-simulation delivery). Verify everything against the actual code; this map is a guide, not the source of truth. If the code and this document disagree, the code wins and you should report the difference.

---

## 1. What this project is

A personal, rule-based **end-of-day (EOD) stock screening and trade-management engine for NSE/BSE**. The owner trades manually. The engine never routes orders. It produces **Trade Tickets**, and the owner clicks them in his broker terminal. There is no "Buy" button by design (regulatory barrier, tested in `tests/unit/test_regulatory_barrier.py`).

Three jobs, one shared rule set:
1. **Backtest**: prove (or disprove) that the rules have an edge, with multiple-testing control.
2. **Paper mode**: run the same rules forward, fills simulated at next open.
3. **Live mode**: generate tickets nightly, track positions the owner reports.

**Current status:** the breakout strategy was tested through Step 3 (six pre-registered configs, 2020–2026 tuning windows). All six failed the pre-registered gates, so no strategy is selected. The infrastructure is sound and reusable; the strategy is what failed. A new strategy family is planned (52-week-high / momentum rotation, 1–3 month holds). Do not assume the old strategy parameters are good.

## 2. Repo map

| Path | Purpose |
|---|---|
| `strategy_config.yaml`, `config.py` | Every numeric parameter. `config.py` loads it once. No magic numbers elsewhere. Config hash is part of the deployment lock. |
| `data/` | SQLite DB layer (`data/db/`), ingestors (`data/ingestion/`), data-quality checks. |
| `engine_core/` | Shared, stateless quant logic used by backtest **and** live. The heart of the project. |
| `backtest/` | Simulator, exclusions, audit/gate generator, candidate-simulation runner, pre-registered configs. |
| `live_runner/` | FastAPI app, 5 PM IST scheduler, EOD pipeline, paper trader, Git-SHA lock, idempotency guard, REST routers. |
| `scripts/` | Analysis and diagnostics: candidate selection, random baseline, funnel counts, paper report, health check. |
| `ui/` | React dashboard (Tickets, Portfolio, Analytics, Regime). Out of scope for the current phase. |
| `tests/` | Unit and integration tests, including sim-vs-live consistency tests. |
| `authorize_live.py`, `authorized_deployment.json` | One-time authorization after a passing backtest; pins commit + config hash. |
| `BRD.docx`, `Architecture_Spec.docx`, `docs/`, `enhancements/` | Original requirements, architecture, and phase plans. Read the BRD and Architecture first for intent. |
| `backtest/outputs/` | Generated results: trades, equity curves, `selection_decision.json`, `trial_ledger.csv`. `outputs_v1_stale/` is old, ignore. |
| Root `fix_blocker*.py`, `verify_db.py`, `confidence_report.md` | One-off historical fixes and reports. Not part of the runtime. |

## 3. Data layer

SQLite DB with these tables: `market_data_lake` (raw OHLCV, plus synthetic symbols `NIFTY50_INDEX` and `INDIA_VIX`), `shares_outstanding`, `corporate_actions_log`, `asm_gsm_list`, `earnings_calendar`, `regime_state`, `active_positions`, `trade_analytics_log`, `pipeline_run_log`, `daily_watchlist`.

Key invariants (from module docstrings):
- **Raw OHLCV is never mutated.** Ingested with `continuous=False`. Splits and bonuses are applied in memory by `engine_core/adjustments.py`.
- **ADTV and market cap use raw prices only**, never adjusted. Market cap = raw close × raw shares outstanding (point-in-time).
- The data lake is append-only. Corporate actions are only *logged* at ingestion; adjustment happens at read time.
- ASM/GSM list is a **snapshot** (replaced on refresh), which is a known limit for historical backtests.

Known data gaps (from the project's own open items): historical corporate actions, point-in-time shares, VIX history, 2018–19 ASM/GSM, earnings data for 2015–19, and survivorship of delisted names.

## 4. `engine_core/`: the shared logic

Dependency order (imports flow downward):

1. `indicators.py`: pure functions (ATR, SMA, Donchian). No DB.
2. `adjustments.py`: split/bonus adjustment, in memory. Produces adjusted series; raw series is kept for ADTV/market cap.
3. `lifecycle_rules.py`: **pure** functions for the position state machine, gap-aware stops, next-open fill planning. No DB, no pandas. Used by both simulator and live code.
4. `candidate_builder.py`: the single place that turns symbols into candidate dicts (raw + adjusted OHLCV, sector, corporate actions). Live and backtest both call it.
5. `universe_screener.py`: multi-gate filter (market cap, ADTV, listing age, surveillance, earnings block, etc.).
6. `entry_filters.py`: trend and breakout filters and deterministic ranking. Shared by live and sim.
7. `risk_sizing.py`: stops (wider of ATR-based and Donchian low), 1% risk sizing, R:R, sector and heat caps.
8. `regime_filter.py` / `regime_gates.py`: macro kill switch (Nifty vs 200 SMA OR VIX high; hysteresis for re-entry). `regime_gates.py` is the stateless gate form.
9. `position_lifecycle.py`: daily state machine for open positions (INITIAL_RISK → RISK_FREE_1_TO_1 → TRAILING_ATR, plus time-decay flag).
10. `costs.py`: STT, stamp duty, DP, GST, SEBI/exchange fees, slippage, tax. `trade_metrics.py`: unified R, expectancy, profit factor, drawdown.
11. `equity.py`, `mode.py`, `position_service.py`, `account_ledger.py`: PAPER vs LIVE equity tracking and position opening (paper auto-fills at next open; live uses operator-entered fill).
12. `max_t_bootstrap.py`: Westfall-Young step-down Max-T studentized block bootstrap, the multiple-testing control.
13. `analytics_loop.py`, `preflight.py`, `sector_map.py`: trade analytics, nightly data spot-checks, sector lookup.

**Design principle:** the rules live once in `engine_core` and both the simulator and the live pipeline call them. If you ever copy a rule into a second place, you have recreated the backtest-vs-live drift the previous reviews found.

## 5. `backtest/`

- `simulator.py`: **one** Simulator for Pass 1 (no exclusions) and Pass 2 (with ASM/GSM + earnings exclusions). Uses `engine_core` for all rules.
- `exclusions.py`: fail-closed loader. Missing surveillance/earnings data should block, not allow.
- `bifurcated_scraper/`: scrapers for historical ASM/GSM PDFs and earnings dates (Pass 2 inputs).
- `audit_generator.py`: evaluates gates, writes `audit.json`; `run_backtest.py` is the CLI (`--pass1`, `--pass2`, `--freeze`, `--test`, `--audit`).
- `run_candidate_simulations.py` + `pre_registered_configs.yaml`: runs the six pre-registered configs over W1 (2020–21) and W2 (2022–26).
- `scripts/select_candidate.py`: the pre-registered selection gates (G1 volume, G2 own-series CI > 0, G3 Max-T at block 4 and 8, G4 plateau, G5 DD/PF/expectancy), then writes `selection_decision.json` and appends the trial ledger.
- Statistical baseline: `scripts/redesigned_random_baseline.py` (matched-random entries under identical exits).

## 6. `live_runner/`

- `main.py`: FastAPI app. On startup checks the Git-SHA lock, inits DB, starts the scheduler.
- `scheduler.py`: fires `pipeline.py` at 5 PM IST.
- `pipeline.py` (`EODPipeline`): freshness check → regime evaluation → manage open positions (always) → screen and size new setups (only if kill switch is OFF) → write tickets.
- `idempotency.py`: DB-level UNIQUE on run date, so the pipeline cannot run twice a day.
- `git_lock.py` + `authorize_live.py`: the system refuses to run unless current commit and config hash match `authorized_deployment.json`.
- `paper_trader.py`: auto-executes approved tickets at next open in PAPER mode.
- `routers/`: REST endpoints for the UI.

## 7. Dependencies at a glance

```
strategy_config.yaml ──> config.py ──> everything
data/ (DB + ingestors) ──> engine_core.candidate_builder
engine_core (pure rules) ──> backtest/simulator  AND  live_runner/pipeline
backtest/simulator ──> scripts/select_candidate ──> selection_decision.json
audit.json + config hash ──> authorize_live.py ──> authorized_deployment.json ──> git_lock ──> live_runner startup
ui ──> live_runner/routers (HTTP only)
```

The two big independent halves are (a) **validation** (simulator, baseline, bootstrap, ledger) and (b) **operations** (live runner, lock, paper trader). They meet only through `engine_core`.

## 8. Things to know before touching anything

- `net_r` in the trade CSVs is currently **gross R** (it equals `realized_r`). True net R is `pnl_net` divided by the amount risked. Selection stats are computed on the gross column. Fix pending.
- Tax is set to `stcg_tax_pct: 0.0` as a placeholder until the owner confirms with his CA.
- Config values in the repo deviate from the original spec in several places (e.g. 12 max positions, 15% total risk, VIX threshold 22, 20-session time decay). Do not "fix" these without asking.
- Windows git: ignore CRLF/newline-hash issues.
- **Never run the 2015–2019 TEST window** for the rejected breakout configs. It is reserved for a single-shot test of a future pre-registered strategy.
- Never add configs or loosen gates to rescue the old strategy.

---

## Comprehension questions

Answer **from the code**, with file and function references. Where relevant, say what you would test to confirm.

**A. Purpose and flow**
1. Trace one trade end to end in the live pipeline: from the 5 PM run to a ticket, to the owner reporting a fill, to exit. Name every module and function touched.
2. Do the same for one trade in the simulator. Which functions are shared with the live path, and which are not?
3. What exactly differs between Pass 1 and Pass 2, and which code decides it?
4. What does PAPER mode do differently from LIVE, and where is the single switch?

**B. Data integrity**
5. Why are raw and adjusted prices both kept? Which calculations must use raw, and which adjusted? Find the code that enforces it.
6. How does the engine avoid lookahead bias? Give three specific places (indicators, fills, exclusions, corporate actions).
7. What happens if the earnings calendar or ASM/GSM data is missing for a date?
8. Which data is point-in-time, and which is a snapshot that cannot be backtested faithfully?

**C. Rules and risk**
9. Explain the position state machine, including exactly when the stop moves and when time decay applies. What does a gap-down through the stop do?
10. How is position size computed? How do the 1% risk, sector cap, heat cap, and max positions interact, and in what order are they checked?
11. How does the kill switch trigger and release? Could it re-trigger the day after release?
12. Where are costs applied, and which costs are on buy, sell, or both? What is excluded from "net"?

**D. Validation machinery**
13. Explain the matched-random baseline: what is matched, and why does it matter?
14. What does Max-T control that a simple per-config p-value does not? Why block bootstrap and why two block lengths?
15. List the pre-registered selection gates in order. What happens when no config passes? What stops someone from adding a seventh config?
16. What is the trial ledger for, and what makes it append-only?
17. Find where `net_r` is defined and computed. Is it net of costs? Show evidence.

**E. Safety and operations**
18. How does the Git-SHA lock work? What would it block, and how would it be bypassed by mistake?
19. How does the idempotency guard work, and what is its failure mode?
20. What proves the engine cannot place orders?

**F. Honest assessment**
21. Name the three weakest parts of the codebase in your opinion, with evidence.
22. Name two places where the specification and the code disagree.
23. What would you need to add to test a new strategy (for example, ranking stocks by proximity to the 52-week high and rotating monthly) using the existing harness? Which modules would change and which must not?
24. What did you not understand, and what would you ask the owner?

### Rating guide (for the reviewer)

Each answer is graded 0–3: 0 = wrong or missing, 1 = surface description only, 2 = correct with code references, 3 = correct, referenced, and verified by a test or run. Sections B, C and D are the critical ones; the team should score at least 2 on average there before touching the engine. Anyone who cannot answer Q17 and Q23 is not ready to write strategy code.
