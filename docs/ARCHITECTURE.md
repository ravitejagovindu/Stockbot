# StockBot architecture (DRAFT — restructure Phase 2; updated at each phase)

Goal: about five strategies, each developed, tested and retired without touching the others or the shared machinery; backtest and live run the same decision code; strategy-independent validation is identical for every strategy. This file is enforced, not aspirational: `tests/unit/test_import_boundaries.py` fails the build on a violation.

## Packages (all code under `stockbot/`; the top-level `data/` folder holds files only)
| package | purpose | may import |
|---|---|---|
| `config` | shared typed config, runtime mode, logging, file locations (`paths.py`) | nothing from stockbot |
| `data` | ingestion, **read-only lake access** (`lake.py`), corporate-action adjustment, **point-in-time as-of view** (`asof.py`), shared indicators | config |
| `universe` | eligibility rules and exclusions (ASM/GSM, earnings) | config, data |
| `risk` | costs, sector map; later sizing, heat/sector caps, arbitration, R definitions | config, data |
| `engine` | one `decide()` for backtest and live; strategy interface (Phase 6) | config, data, universe, risk, strategies (interface only) |
| `strategies` | interface and registry only; **no strategy files** (a dummy lives under `tests/`) | data (view types) |
| `backtest` | runner, simulated fills, network guard, run manifest | config, data, universe, risk, engine, strategies (registry) |
| `live` | EOD runner, tickets, state DB, idempotency, scheduler, read-only API | same as backtest plus its own state store; **never backtest** |
| `validation` | Max-T, prereg lock, trade-R reporting, power study, matched-random baseline, trial ledger | config, data (types), backtest results; **never live** |
| `data_checks` | quality, calendar, corporate-action verification, pre-flight | config, data |

Also forbidden: a strategy or the engine receiving a database session/connection or importing sqlalchemy/sqlite3; any network library inside `backtest`, `engine`, `strategies`, `risk` (the network guard module is the one exception, it patches `socket`); `sys.path` edits inside `stockbot/`; one strategy importing another; any `stockbot` module importing an old top-level path (`data`, `engine_core`, `live_runner`, `backtest`, `config`, ...) unless it is an explicit entry of the temporary allowlist.

## Data rules
- `finsight.db` is never written by backtest, live decision code or validation. `stockbot.data.lake.open_lake` opens it with SQLite `mode=ro` plus `PRAGMA query_only`; a write raises. Live state goes in a separate state database (Phase 9).
- Everything above `data` reads market data only through `AsOfView(conn, as_of)`: every query is bounded by `trade_date <= as_of`, a request for a later bar raises `FutureDataError`, adjustments use only actions with `ex_date <= as_of`, raw close/volume/traded value are exposed separately from adjusted prices, and the connection is not reachable from the view.
- The market-cap gate and `shares_outstanding` are parked (KI-001); the view does not expose share counts.

## Where things are now (end of Phase 3)
- Moved into `stockbot/`: adjustments, indicators (data); costs, sector map (risk); mode, logging (config); Max-T bootstrap, prereg lock, trade metrics (validation; the R-definition split is Phase 5); corporate-action events (engine); pre-flight, quality checker (data_checks); the ingestion modules (data.ingestion); exclusions (universe); the network guard (backtest); idempotency, scheduler, `main` and the API routers (live, unmodified).
- Still at old paths (replaced in later phases): `engine_core/` (screener, risk sizing, lifecycle, entry filters, candidate builder, regime filter, ledger/equity helpers), `backtest/` (simulator, runner), `live_runner/` (pipeline, paper trader, git lock), `data/db/` (ORM + session helper), `config.py`, `strategy_config.yaml`. Each stockbot → legacy import is an entry in `tests/fixtures/boundaries.py` `LEGACY_ALLOWLIST` with the phase that removes it; the list must be empty at STOP 5 (`STOCKBOT_FINAL_CHECK=1`).
- Entry point: `python -m stockbot.live.main`.

## Tests
`tests/unit` (fixture lake, no real database), `tests/integration`, `tests/data_integrity` (env-gated, `STOCKBOT_DATA_TESTS=1`), `tests/fixtures` (mini lake, file-backed lake, boundary-violation fixtures). Golden checks G1–G6 are defined in the restructure plan; baseline numbers in `docs/restructure/BASELINE.md`.
