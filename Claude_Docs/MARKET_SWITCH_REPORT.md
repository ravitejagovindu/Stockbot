# Market switch (`market_switch_v1`): report (facts only)

Branch `market-switch` (worktree `StockBot_wt_marketswitch`), from master b27431d. **Descriptive comparison only: these are not registered trials, they change no registered conclusion, nothing was written to any ledger, and no strategy folder, pre-registration, ledger row or stored result was touched. No recommendation is made.** finsight.db sha256 before and after: `dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752` (unchanged). Not merged; no default changed elsewhere.

# Part A: the build
## A1. Semantics (carried from the old code exactly; full text in `docs/shared/market-switch/BRIEF.md`)
Source: `scripts/provenance/regime/regime_filter.py` and the old `strategy_config.yaml` macro values (recorded in `docs/restructure/OLD_STRATEGY_REFERENCE.md`). **ACTIVE** = new entries blocked; **CLEAR** = entries allowed.
- Prices: `close_raw` of `NIFTY50_INDEX` and `INDIA_VIX`, read through `AsOfView.index_bars` only; the as-of session's close.
- CLEAR to ACTIVE: Nifty close **<** SMA200 OR VIX close **>** 22.0 (strict; a close equal to SMA200, or VIX exactly 22.0, does not trigger). The re-entry count is set to 0 on a trigger.
- While ACTIVE only the re-entry condition is looked at: Nifty close **>** SMA20 AND VIX close **<** 20.0 (strict), for 3 consecutive sessions; any miss resets the count to 0; the switch releases on the third qualifying session itself (entries from the next open). Nifty above SMA200 with VIX 21 stays ACTIVE.
- SMA windows: the old `sma` is NaN until the full window of closes exists (the old code fetched 210 closes; the overlay uses the same 210). Fewer than 200 closes: the Nifty trigger cannot fire (VIX still can). Fewer than 20 closes: re-entry fails. First session: CLEAR, count 0.
- Missing VIX or Nifty close on the as-of session: the old code raised `RuntimeError`; the overlay raises `MarketSwitchDataError` (a `RuntimeError`) in backtest, paper and live. Counted first: of 2,674 Nifty sessions 2016-01-01 to 2026-10-16, **0** have no VIX row or a null VIX close, so the zero-count branch applied (raise); nothing is carried forward, interpolated or failed closed.
- Discrepancy noted: the old module docstring and README say trigger VIX 20 and re-entry Nifty > SMA50 and VIX < 18; the code and config (what actually ran) say VIX 22, re-entry Nifty > SMA20 and VIX < 20. The config values are carried over.
- Timing: decided on the session close T; applies to proposals made at T (filled at the open of T+1). Tickets made earlier while CLEAR still fill. Open positions are never touched; exit policies run as before.
- Logged reasons: `NIFTY_BELOW_SMA200`, `VIX_ABOVE_22` (joined with `+` if both), then `REENTRY_COUNT n/3` on later ACTIVE sessions and on the releasing session (`3/3`, state CLEAR).

## A2. What was built and where
- `stockbot/overlays/market_switch.py` (rule, id `market_switch_v1`, version `1.0.0`) and `stockbot/overlays/__init__.py` (`resolve_default_overlays`, `describe_default_overlays`).
- `shared.yaml` section `overlays`: `default: [market_switch_v1]` and the five numbers `market_switch_v1_trigger_sma_period` 200, `_trigger_vix` 22.0, `_reentry_sma_period` 20, `_reentry_vix` 20.0, `_reentry_sessions` 3.
- `stockbot/engine/decide.py`: the ONE code path. It evaluates the shared default overlays once per session (not guarded, so a data error stops the session in every mode); while ACTIVE every proposal that passed the eligibility and duplicate checks is recorded in `Decisions.blocked` with reason `MARKET_SWITCH`, stage `overlay`, and is not sized or ticketed (`propose` still runs). The backtest runner and the live adapter both call `decide(..., default_overlays=...)`; `None` = the shared default, `[]` = the explicit opt-out.
- Opt-out: `run_backtest(..., default_overlays=[])` or `scripts/run_with_market_switch.py --overlays none`; the run prints `overlays: none (...)` and the manifest says `"overlays": []`.
- Logging: `stockbot/backtest/outputs.py` writes `daily.json` with `market_switch: {state, reason, reentry_count}` per session (only when the overlay ran) and `blocked.json` with `MARKET_SWITCH` rows. Shared runner `scripts/run_with_market_switch.py`, statistics `scripts/market_switch_stats.py`, tables `scripts/market_switch_tables.py`.

## A3. Shared files touched and why
| file | why |
|---|---|
| stockbot/config/shared.py, shared.yaml | new `overlays` section (default list and the five numbers), validated; part of the non-overridable sections |
| stockbot/strategies/spec.py | `overlays` added to NON_OVERRIDABLE (a test requires it to equal the shared list) |
| stockbot/engine/decide.py | evaluates the shared default overlays, blocks entries while ACTIVE |
| stockbot/backtest/runner.py, manifest.py | `default_overlays` argument; manifest key `overlays`; `shared_config_hash` now covers the effective overlays |
| stockbot/live/adapter.py | passes the same `default_overlays` argument (None = shared default) to the same `decide` call |
| tests/fixtures/boundaries.py | import rules for the new `overlays` package (imports data only; engine and backtest may import it) |
| docs/guides/CODEBASE_GUIDE.md, codebase_guide_data.json, codebase_guide.html | new package, modules and scripts named; HTML regenerated (guide-consistency tests require it) |
| tests/unit/test_engine_decide.py | an existing assertion on the full overlay state now also sees the default switch |
| tests/unit/test_shared_config.py | the new keys are declared as new (no legacy counterpart) |
| tests/unit/test_no_strategy_in_the_tree.py | the one allowed overlay class `stockbot/overlays/market_switch.py::MarketSwitch` |
New files: `stockbot/overlays/*`, `stockbot/backtest/outputs.py`, `scripts/run_with_market_switch.py`, `scripts/market_switch_stats.py`, `scripts/market_switch_tables.py`, `tests/unit/test_market_switch.py`, `docs/shared/market-switch/{BRIEF,STATUS}.md`, `docs/shared/market-switch/results/`. No strategy folder, strategy script, pre-registration, ledger file or stored result was edited.

## A4. Hash effects
- `StrategySpec.config_hash()` of every strategy: **unchanged** (the switch is a shared default, `spec.overlays` stays empty). near_52w_high `359c8331...` is identical in the WITH and WITHOUT manifests; the registered short_term_reversal `57b86c47...` and pullback_uptrend `81db6427...` do not move.
- `validation_gates` hash `e9b6407f...`: unchanged.
- `shared_config_hash` in a run manifest: **changes for every run made on this code**, with or without the switch, because the shared config has a new section and the hash also covers the effective overlay list (id, version, numbers; `[]` when off). near_52w_high: WITH `e7fb694d...`, WITHOUT (`overlays=[]`) `c14fca17...`. Stored manifests keep their old value and are not rewritten.
- Manifest: new key `overlays` (list of `{id, version, params}`; `[]` when off).
- Behaviour to know: because the default is shared, a registered research script (`scripts/research_*.py`) run on this branch applies the switch unless its `run_backtest` call passes `default_overlays=[]`; those scripts were not edited, so their `daily.json` has no `market_switch` column (their `blocked.json` does show `MARKET_SWITCH`).

## A5. Tests and gates
- New `tests/unit/test_market_switch.py` (24 tests): each trigger and its strictness, hysteresis counting and reset, release on the third session, warm-up, missing and null VIX and Nifty (raise); engine on a fixture lake (entries blocked with `MARKET_SWITCH`, state logged, exits and tickets made while CLEAR unaffected); SQL view = memory view (engine digest and per-session states); live adapter and backtest share the one `decide` call (source check plus a live-mode call); a missing VIX stops the session in backtest, paper and live modes; **a run with `default_overlays=[]` has the same sha256 digest as the same run on master b27431d** (decisions, final state, trades, equity, daily.json, blocked.json: `763ba4f2...`); daily.json carries the state only when the overlay ran.
- **Replay of the old code** (`scripts/provenance/regime/regime_filter.py`, imported read-only, `persist=False`, only its data fetch replaced): the daily ACTIVE/CLEAR state matches the overlay on **every session** of 8 random synthetic series (900 sessions each, both states exercised), of the hand series, and of the **real Nifty/VIX series, all 2,710 Nifty sessions in the lake (2015-11-09 to 2026-10-16), the overlay read through the real as-of view: 0 mismatches**. The engine run's own states also equal the statistics script's states on all 2,674 sessions of 2016-01-01 to 2026-10-16, and no trade of the WITH near_52w_high run entered at an open that followed an ACTIVE close.
- Gates on the final tree: **G1** (`tests/unit tests/integration`) 1,119 passed, 9 skipped; **full G2** (`STOCKBOT_DATA_TESTS=1 STOCKBOT_FINAL_CHECK=1 pytest tests`) 1,249 passed; **G3** 2 passed. (A first G1 run had 10 expected failures from the new package, section and class; fixed as listed in A3, then G1 re-run.)

# Part B: comparison (descriptive)
## B1. Switch statistics, 2016-01-01 to 2026-10-16 (evaluated from a fresh state at the window start, as an engine run starts)
- Sessions: 2674. **ACTIVE 881, CLEAR 1793; share of time ACTIVE 32.9%.**
- Flips (state changes): 117; ACTIVE periods (activations): 59. Reason at activation: VIX_ABOVE_22 8, NIFTY_BELOW_SMA200 50, NIFTY_BELOW_SMA200+VIX_ABOVE_22 1.
- Until about the 200th Nifty session of the lake (the lake starts 2015-11-09) the Nifty trigger cannot fire (warm-up); the VIX trigger can.

| # | ACTIVE from | to (last ACTIVE session) | sessions | calendar days | reason at activation |
|---|---|---|---|---|---|
| 1 | 2016-02-10 | 2016-03-02 | 16 | 22 | VIX_ABOVE_22 |
| 2 | 2016-11-15 | 2016-12-09 | 19 | 25 | NIFTY_BELOW_SMA200 |
| 3 | 2016-12-14 | 2017-01-02 | 14 | 20 | NIFTY_BELOW_SMA200 |
| 4 | 2017-01-04 | 2017-01-06 | 3 | 3 | NIFTY_BELOW_SMA200 |
| 5 | 2018-03-19 | 2018-04-06 | 13 | 19 | NIFTY_BELOW_SMA200 |
| 6 | 2018-10-04 | 2018-11-01 | 20 | 29 | NIFTY_BELOW_SMA200 |
| 7 | 2018-11-05 | 2018-11-07 | 3 | 3 | NIFTY_BELOW_SMA200 |
| 8 | 2018-11-12 | 2018-11-14 | 3 | 3 | NIFTY_BELOW_SMA200 |
| 9 | 2018-11-16 | 2018-11-20 | 3 | 5 | NIFTY_BELOW_SMA200 |
| 10 | 2018-11-22 | 2018-11-28 | 4 | 7 | NIFTY_BELOW_SMA200 |
| 11 | 2018-12-06 | 2018-12-13 | 6 | 8 | NIFTY_BELOW_SMA200 |
| 12 | 2018-12-21 | 2018-12-28 | 5 | 8 | NIFTY_BELOW_SMA200 |
| 13 | 2019-01-03 | 2019-01-09 | 5 | 7 | NIFTY_BELOW_SMA200 |
| 14 | 2019-01-11 | 2019-01-16 | 4 | 6 | NIFTY_BELOW_SMA200 |
| 15 | 2019-01-23 | 2019-02-01 | 8 | 10 | NIFTY_BELOW_SMA200 |
| 16 | 2019-02-12 | 2019-03-05 | 15 | 22 | NIFTY_BELOW_SMA200 |
| 17 | 2019-04-18 | 2019-05-24 | 24 | 37 | VIX_ABOVE_22 |
| 18 | 2019-07-30 | 2019-08-27 | 19 | 29 | NIFTY_BELOW_SMA200 |
| 19 | 2019-08-29 | 2019-09-11 | 8 | 14 | NIFTY_BELOW_SMA200 |
| 20 | 2019-09-13 | 2019-09-23 | 7 | 11 | NIFTY_BELOW_SMA200 |
| 21 | 2019-10-04 | 2019-10-10 | 4 | 7 | NIFTY_BELOW_SMA200 |
| 22 | 2020-02-26 | 2020-08-24 | 122 | 181 | NIFTY_BELOW_SMA200 |
| 23 | 2020-08-31 | 2020-10-05 | 25 | 36 | VIX_ABOVE_22 |
| 24 | 2020-10-15 | 2020-11-14 | 23 | 31 | VIX_ABOVE_22 |
| 25 | 2020-11-25 | 2020-12-03 | 6 | 9 | VIX_ABOVE_22 |
| 26 | 2020-12-21 | 2021-05-18 | 99 | 149 | VIX_ABOVE_22 |
| 27 | 2022-01-24 | 2022-04-04 | 48 | 71 | VIX_ABOVE_22 |
| 28 | 2022-04-19 | 2022-07-08 | 58 | 81 | NIFTY_BELOW_SMA200 |
| 29 | 2022-07-12 | 2022-07-14 | 3 | 3 | NIFTY_BELOW_SMA200 |
| 30 | 2022-07-18 | 2022-07-20 | 3 | 3 | NIFTY_BELOW_SMA200 |
| 31 | 2022-07-22 | 2022-07-26 | 3 | 5 | NIFTY_BELOW_SMA200 |
| 32 | 2022-07-28 | 2022-08-01 | 3 | 5 | NIFTY_BELOW_SMA200 |
| 33 | 2022-09-28 | 2022-10-18 | 14 | 21 | NIFTY_BELOW_SMA200+VIX_ABOVE_22 |
| 34 | 2023-02-28 | 2023-04-03 | 23 | 35 | NIFTY_BELOW_SMA200 |
| 35 | 2024-05-27 | 2024-06-06 | 9 | 11 | VIX_ABOVE_22 |
| 36 | 2024-11-14 | 2024-11-26 | 7 | 13 | NIFTY_BELOW_SMA200 |
| 37 | 2024-12-20 | 2025-02-01 | 31 | 44 | NIFTY_BELOW_SMA200 |
| 38 | 2025-02-04 | 2025-02-06 | 3 | 3 | NIFTY_BELOW_SMA200 |
| 39 | 2025-02-10 | 2025-03-19 | 26 | 38 | NIFTY_BELOW_SMA200 |
| 40 | 2025-03-21 | 2025-03-25 | 3 | 5 | NIFTY_BELOW_SMA200 |
| 41 | 2025-03-27 | 2025-04-01 | 3 | 6 | NIFTY_BELOW_SMA200 |
| 42 | 2025-04-03 | 2025-04-16 | 8 | 14 | NIFTY_BELOW_SMA200 |
| 43 | 2025-04-25 | 2025-04-29 | 3 | 5 | NIFTY_BELOW_SMA200 |
| 44 | 2025-05-09 | 2025-05-13 | 3 | 5 | NIFTY_BELOW_SMA200 |
| 45 | 2026-01-23 | 2026-02-04 | 9 | 13 | NIFTY_BELOW_SMA200 |
| 46 | 2026-02-27 | 2026-04-16 | 30 | 49 | NIFTY_BELOW_SMA200 |
| 47 | 2026-04-20 | 2026-04-22 | 3 | 3 | NIFTY_BELOW_SMA200 |
| 48 | 2026-04-24 | 2026-04-28 | 3 | 5 | NIFTY_BELOW_SMA200 |
| 49 | 2026-04-30 | 2026-05-05 | 3 | 6 | NIFTY_BELOW_SMA200 |
| 50 | 2026-05-07 | 2026-05-26 | 14 | 20 | NIFTY_BELOW_SMA200 |
| 51 | 2026-05-29 | 2026-06-15 | 12 | 18 | NIFTY_BELOW_SMA200 |
| 52 | 2026-06-17 | 2026-06-19 | 3 | 3 | NIFTY_BELOW_SMA200 |
| 53 | 2026-06-23 | 2026-06-25 | 3 | 3 | NIFTY_BELOW_SMA200 |
| 54 | 2026-06-30 | 2026-07-02 | 3 | 3 | NIFTY_BELOW_SMA200 |
| 55 | 2026-07-06 | 2026-07-20 | 11 | 15 | NIFTY_BELOW_SMA200 |
| 56 | 2026-07-22 | 2026-07-30 | 7 | 9 | NIFTY_BELOW_SMA200 |
| 57 | 2026-08-03 | 2026-08-05 | 3 | 3 | NIFTY_BELOW_SMA200 |
| 58 | 2026-08-07 | 2026-08-11 | 3 | 5 | NIFTY_BELOW_SMA200 |
| 59 | 2026-08-13 | 2026-10-16 (still ACTIVE at window end) | 45 | 65 | NIFTY_BELOW_SMA200 |

## B2. The switch on the index alone (no engine)
Nifty buy-and-hold against 'Nifty while CLEAR, cash at 6.5% a year while ACTIVE'. State decided on close T, executed at the open of T+1; each execution pays 0.22% (a full exit-and-re-entry cycle 0.44% round trip). Both lines start fully invested at the first open of the period with no entry cost; cash earns 6.5% a year (calendar-day compounding) for intervals fully in cash, the intra-day part of a switch day earns nothing. Max drawdown on closes. 'Worst year' is the worst calendar-year return in the period (2016 and 2026 are partial years: 2026 runs to 2026-10-16).

| period | line | CAGR % | max drawdown % | worst calendar year % (year) | total return % |
|---|---|---|---|---|---|
| full | buy-and-hold | 10.43 | 38.44 | -11.42 (2026) | 191.6 |
| full | switch, cash while ACTIVE | 3.48 | 24.07 | -13.64 (2026) | 44.6 |
| 2016-2019 | buy-and-hold | 11.28 | 14.55 | 3.12 (2016) | 53.3 |
| 2016-2019 | switch, cash while ACTIVE | 2.30 | 24.07 | -9.39 (2018) | 9.5 |
| 2020-2026 | buy-and-hold | 9.89 | 38.44 | -11.42 (2026) | 89.7 |
| 2020-2026 | switch, cash while ACTIVE | 4.13 | 18.90 | -13.64 (2026) | 31.6 |

## B3. Engine runs WITH the switch (`STOCKBOT_VIEW=memory`, engine only, no random baselines; same specs, window 2016-01-01 to 2026-10-16)
**Which WITHOUT side:** first check, a 12-month window (2016-01-01 to 2016-12-31) near_52w_high run with `overlays=[]` on this branch's code, compared with the stored 4B run (`F:\Projects\Ravi\StockBot_runs\near_52w_high_4B`) trades that closed in that window: stored 72 trades, fresh 71; **only 8 are identical on (symbol, entry date, exit date, entry price, shares, net P&L)**. **The stored 4B run does NOT reproduce on today's code.** The stored run was made on git 7176d90; between it and master the only change to decision logic is the shared sector rule (`b6f5c62`, every unmapped symbol is its own sector; the memory view, also added since, was proven identical to the SQL view). I did not re-run under the old sector rule, so the cause is the one candidate in the code diff, not a verified fact. **Therefore near_52w_high's WITHOUT side is a fresh full-window `overlays=[]` run on this code** (`F:\Projects\Ravi\StockBot_runs\market_switch\near_52w_high\without`), so both sides use the same code. For pullback_uptrend and short_term_reversal the WITHOUT side is the **stored registered run1** (made 2026-11-14 on master df7486b, which already contains the sector rule; engine code unchanged since apart from this branch); I did not re-run those WITHOUT sides and did not check their reproduction on this code.

Notes: 'proposals blocked' counts rows in `blocked.json` with reason `MARKET_SWITCH` (every proposal a strategy made on an ACTIVE session that passed eligibility); it is not the number of entries that would have been taken, because position, cash and sector caps would have refused many. Alpha is against the Nifty matched to each run's own invested share (re-matched to the new run), by the strategy's own gates script, point estimates; the 95% intervals are in the gates JSON and were not used. Each side is a single run; no statistical test was applied.

### near_52w_high

| measure | WITHOUT | WITH |
|---|---|---|
| closed trades (END_OF_WINDOW included) | 762 | 660 |
| usable trades | 739 | 649 |
| entries per month | 5.68 | 4.99 |
| proposals blocked MARKET_SWITCH (rows in blocked.json) | n/a (switch off) | 17635 |
|   of which distinct symbol-sessions | n/a | 17635 |
| sessions ACTIVE / sessions | n/a | 881 / 2674 |
| invested share (mean) | 0.732 | 0.651 |
| open positions (mean) | 11.57 | 10.05 |
| expectancy (net R per usable trade) | 0.1145 | 0.0593 |
| profit factor | 1.2975 | 1.1244 |
| strategy CAGR % (raw) | 6.53 | 2.09 |
| strategy CAGR % (cash credited 6.5%) | 8.37 | 4.39 |
| matched-Nifty CAGR % | 10.14 | 7.17 |
| alpha pp (raw) | -3.61 | -5.08 |
| alpha pp (cash credited, pre-tax: the gate quantity) | -1.77 | -2.78 |
| max drawdown % | 26.92 | 30.56 |

Sub-periods (descriptive; WITHOUT / WITH):

| period | trades | expectancy R | profit factor | max drawdown % | invested share | alpha pp (raw) |
|---|---|---|---|---|---|---|
| 2016-2019 | 298 / 280 | 0.015 / 0.020 | 1.016 / 1.018 | 21.51 / 21.46 | 0.765 / 0.739 | -10.53 / -7.44 |
| 2020-2026 | 441 / 369 | 0.182 / 0.089 | 1.405 / 1.184 | 19.68 / 23.13 | 0.714 / 0.600 | 3.78 / -0.01 |

### pullback_uptrend

| measure | WITHOUT | WITH |
|---|---|---|
| closed trades (END_OF_WINDOW included) | 4156 | 2945 |
| usable trades | 4144 | 2938 |
| entries per month | 31.88 | 22.60 |
| proposals blocked MARKET_SWITCH (rows in blocked.json) | n/a (switch off) | 9593 |
|   of which distinct symbol-sessions | n/a | 9593 |
| sessions ACTIVE / sessions | n/a | 881 / 2674 |
| invested share (mean) | 0.702 | 0.514 |
| open positions (mean) | 7.60 | 5.62 |
| expectancy (net R per usable trade) | -0.0951 | -0.1110 |
| profit factor | 0.8909 | 0.8396 |
| strategy CAGR % (raw) | -8.63 | -9.20 |
| strategy CAGR % (cash credited 6.5%) | -6.87 | -6.34 |
| matched-Nifty CAGR % | 7.38 | 5.65 |
| alpha pp (raw) | -16.01 | -14.85 |
| alpha pp (cash credited, pre-tax: the gate quantity) | -14.25 | -11.98 |
| max drawdown % | 69.38 | 68.06 |

Sub-periods (descriptive; WITHOUT / WITH):

| period | trades | expectancy R | profit factor | max drawdown % | invested share | alpha pp (raw) |
|---|---|---|---|---|---|---|
| 2016-2019 | 1276 / 1077 | -0.125 / -0.143 | 0.828 / 0.761 | 51.16 / 51.44 | 0.585 / 0.488 | -20.89 / -18.72 |
| 2020-2026 | 2868 / 1861 | -0.082 / -0.093 | 0.943 / 0.930 | 44.77 / 43.52 | 0.770 / 0.528 | -10.30 / -7.78 |

### short_term_reversal

| measure | WITHOUT | WITH |
|---|---|---|
| closed trades (END_OF_WINDOW included) | 4288 | 3247 |
| usable trades | 4275 | 3243 |
| entries per month | 32.88 | 24.95 |
| proposals blocked MARKET_SWITCH (rows in blocked.json) | n/a (switch off) | 13211 |
|   of which distinct symbol-sessions | n/a | 13211 |
| sessions ACTIVE / sessions | n/a | 881 / 2674 |
| invested share (mean) | 0.755 | 0.512 |
| open positions (mean) | 7.76 | 5.20 |
| expectancy (net R per usable trade) | -0.2590 | -0.2854 |
| profit factor | 0.7653 | 0.6953 |
| strategy CAGR % (raw) | -28.04 | -24.61 |
| strategy CAGR % (cash credited 6.5%) | -26.91 | -22.22 |
| matched-Nifty CAGR % | 8.74 | 6.01 |
| alpha pp (raw) | -36.78 | -30.62 |
| alpha pp (cash credited, pre-tax: the gate quantity) | -35.65 | -28.24 |
| max drawdown % | 97.17 | 95.29 |

Sub-periods (descriptive; WITHOUT / WITH):

| period | trades | expectancy R | profit factor | max drawdown % | invested share | alpha pp (raw) |
|---|---|---|---|---|---|---|
| 2016-2019 | 1640 / 1319 | -0.243 / -0.388 | 0.755 / 0.680 | 81.39 / 83.31 | 0.660 / 0.531 | -41.99 / -39.54 |
| 2020-2026 | 2635 / 1924 | -0.269 / -0.215 | 0.803 / 0.769 | 84.92 / 67.00 | 0.810 / 0.501 | -31.79 / -20.72 |

## Files
Run outputs (manifest, trades, equity_curve, daily, blocked; gates JSON and text; table.md) are under `F:\Projects\Ravi\StockBot_runs\market_switch\<id>\{with,without}`, plus `index_only\` and `repro\`. The small result files (statistics JSON, switch_states.csv, tables, gates JSON) are copied to `docs/shared/market-switch/results/`. The stored WITHOUT sides: `docs/strategies/pullback_uptrend/results_run1` on branch `pullback_uptrend` and `docs/strategies/short_term_reversal/results_run1` on branch `short_term_reversal`.

## Follow-up: the switch is optional, not a shared default (owner decision)
Changes on branch `market-switch` after the report above (the Part B numbers are unchanged; they were produced with the switch applied to every strategy, which is equivalent to a strategy declaring it):
1. `shared.yaml`: `overlays.default` is now `[]`. The five `market_switch_v1_*` numbers stay there as the single source of its parameters.
2. A strategy opts in with `StrategySpec.overlays = {"market_switch_v1": "1.0.0"}`; it enters that strategy's spec hash and its manifest entry. `engine.decide` resolves a declared library overlay (`stockbot.overlays.library_overlay`) through the one code path used by backtest, paper and live (no change was needed in the live adapter or runner). It blocks only the declaring strategy's new entries (reason `MARKET_SWITCH`), logs its state, and a missing Nifty or VIX close still raises in every mode. An unknown overlay id, or a declared version that differs from the code's, raises `EngineInputError` with a clear message ("... declared but unknown ..." / "... declared but registered as 1.0.0"). The explicit shared-default list (`default_overlays=[...]`) is kept as a mechanism and is empty.
3. Without a declaration nothing changes: the digest test (decisions, state, trades, equity, daily, blocked on the fixture lake) equals the digest taken on master b27431d with the plain default call, and `shared_config_hash` now equals master's value (816ee5cb...) when no overlay is in force (the `overlays.*` numbers are left out of the hash, and `overlays.effective` is added only when an overlay is in force). The three registered research strategies declare no overlay, so their scripts behave as on master without edits (a test asserts this). This corrects the earlier note that every run's `shared_config_hash` changes.
4. `scripts/run_with_market_switch.py`: `--overlays market_switch|none` (default none); the first makes the strategy declare the switch. `scripts/market_switch_stats.py` reads the overlay from the library.
5. `docs/shared/market-switch/DECISION.md`: criteria, the four numbers, the decision, caveats.
6. Tests: new ones for declared (entries blocked, state logged, all three modes), not declared (no block, no state, byte-identical to master), only the declaring strategy blocked, unknown id and wrong version, explicit default list; `test_engine_decide.py` is back to its master content. Guides: `CODEBASE_GUIDE.md`, `codebase_guide_data.json` and the regenerated HTML changed only where tests or accuracy required (the missing `market_switch_tables.py` entry, the wording of "shared default").

Gates: full G2 on this code gave 1,254 passed and 1 failed (a guide panel text over 45 words, fixed afterwards; the guide, G3 and fixture tests were re-run and pass; the full G2 was not repeated). G1 gave 1,124 passed, 1 failed (missing guide entry, fixed). G3 passes; finsight.db sha256 unchanged (dcade465...b752).

Shared files touched in this follow-up and why: `stockbot/engine/decide.py` (resolve and apply declared library overlays per strategy), `stockbot/overlays/__init__.py` (`library_overlay`, `describe_effective_overlays`), `stockbot/backtest/manifest.py` (hash and manifest list the overlays in force), `stockbot/backtest/runner.py` (overlays line), `stockbot/config/shared.yaml` and `shared.py` (default `[]`, wording), `tests/unit/test_market_switch.py`, `tests/unit/test_no_strategy_in_the_tree.py` (comment), `tests/unit/test_engine_decide.py` (reverted to master), the three guide files.
