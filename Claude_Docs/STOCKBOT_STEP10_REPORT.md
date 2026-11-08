# Step 10 report — F2b closed; known issue recorded; call sites listed (no code changed)

Date 2026-11-08. No config, gate or budget changed. No replacement rule proposed.

## 1. F2b closed as "failed its pre-registered bar"
`shares_outstanding_pit` is not created or loaded in `finsight.db`; the screener still reads the old table. The code, anchors and spot-check files stay in the repo and are marked NOT USED:
`data/ingestion/pit_shares.py`, `scripts/f2b_build_pit_shares.py`, `scripts/f2b_spotcheck.py`, `scripts/f2b_spotcheck_model.py` (note added to each docstring), the unused `SharesOutstandingPIT` model (note added), and `data/reference/README_F2b_NOT_USED.md` covering `pit_shares_anchors.csv` and `pit_shares_spotcheck_filings.csv`. Their 10 unit tests still pass.

## 2. Known-issues list
There was no such list in the repo, so it is started: `docs/data_audit/DATA_KNOWN_ISSUES.md`, **KI-001**: `shares_outstanding` is a single current snapshot (2,217 rows, all dated 2020-01-01, Yahoo "current" fetched 2026-10-02), NOT point-in-time. The market-cap gate is unreliable before 2024 and has unflagged errors (spot-check: YESBANK +1,256%, RBLBANK +264%, HDFCBANK +41.5%; median 13.40%, p90 264.97% over 20 name-dates). Names with no row are rejected as `NO_PRICE_DATA`.

## 3. Every reader of `shares_outstanding` / market cap (nothing changed)
**The only code that reads the table to decide anything:**
| where | what |
|---|---|
| `engine_core/universe_screener.py:477-514` `_get_latest_price_and_shares` | `SELECT shares_count FROM shares_outstanding WHERE symbol=? AND effective_date <= eval_date ORDER BY effective_date DESC LIMIT 1` |
| `engine_core/universe_screener.py:234-255` `screen_single`, Gate 1 | market cap = raw close x shares (`compute_market_cap`), rejects `MARKET_CAP_TOO_LOW` if <= `min_market_cap_cr`; rejects `NO_PRICE_DATA` if no row; result carries `market_cap_cr` |
| `engine_core/adjustments.py:286` `compute_market_cap` (exported in `engine_core/__init__.py`) | pure function raw_close x shares; no database access |
| `strategy_config.yaml:6` `universe.min_market_cap_cr: 5000` | the threshold (not changed) |

**Everything that runs the screener, so inherits the defect:**
- `backtest/simulator.py:90, 344, 351` (every backtest and the Jan-Feb 2020 baseline test)
- `live_runner/pipeline.py:255-261` (`screen_all`, live/paper pipeline)
- scripts: `count_executable_entries.py:70,203`, `count_candidate_signals.py:32,88`, `redesigned_random_baseline.py:128,147`, `generate_stage_by_stage_funnel.py:171,295,299`; `diagnose_trades_amended.py:46` imports the class. `generate_stage_by_stage_funnel.py:6` and `redesigned_random_baseline.py:3` describe "Mcap > 5000cr" in their text.
- Every previously produced backtest, funnel and baseline output (e.g. `backtest/outputs_*`, the pre-registered config results) used this gate.

**Writers / other mentions:** `fix_blocker2_shares_outstanding.py` (one-off that filled the table), `data/ingestion/shares_outstanding_ingestor.py` (`get_latest_shares`, upsert; no caller found outside itself), `data/db/models.py:38` and `data/db/schema.sql:28` (definitions), docstring mentions in `data/ingestion/ohlcv_ingestor.py:15` and `engine_core/adjustments.py`.

**Not users of it:** position sizing and risk (`risk_sizing`/sizer files contain no market-cap or shares reference), the UI and API code (no hits), reports (no script computes market cap other than through the screener). Tests that insert `SharesOutstanding` fixtures: `tests/conftest.py`, `tests/integration/test_sim_vs_live_rules.py`, `tests/integration/test_idempotency.py`, plus unit tests of the screener.

Stopped here as instructed. Not started: F9 study and pre-registration, AMD-002, F8 prerequisites, deferred F5/F7/F10 items.
