# StockBot (FInsight trading engine)

A local, end-of-day research and decision-support system for Indian equities. It generates **trade tickets for a human to act on**; it never sends an order to any broker and contains no order-routing code (`tests/unit/test_regulatory_barrier.py` scans the whole code base for it). SEBI's algorithmic-trading rules are the reason: there is no buy button anywhere.

**State of the project after the restructure:** the machinery is finished and strategy-independent; **no strategy exists in the tree.** The previous strategy was tested, rejected (six pre-registered configurations, none passed the gates) and removed; it lives in git tag `pre-restructure`. Everything a new strategy needs is shared: one data view, one decision function, one risk layer, one validation package. Read `docs/ARCHITECTURE.md` first, then `docs/restructure/ENGINE_CONTRACT.md`.

## Layout
```
stockbot/            all code (config, data, universe, risk, engine, strategies, backtest, live, validation, data_checks)
  config/shared.yaml   the only configuration: runtime mode, execution assumptions, costs, portfolio risk limits, universe rules, validation gates, paper criteria
scripts/             thin command-line wrappers (python -m style) + scripts/provenance (one-off tools kept because reports cite them)
tests/               unit, integration, data_integrity (needs the real database, read-only), fixtures, golden (results frozen from the old code)
docs/                architecture, data and validation docs, data_audit reports, archive (old specs), restructure (the restructure record)
data/                reference and F9 data files
backtest/            kept result files only (no code); see backtest/README.md
ui/                  React dashboard (not touched by the restructure)
```

## Setup
```bash
python -m pip install -r requirements.txt
copy .env.template .env        # fill in what you use (data keys); nothing here can place an order
```
`finsight.db` (the price lake, about 3.4 GB) is not in git. Engine, backtest, validation and live decision code open it **read-only** (`stockbot.data.lake.open_lake`: SQLite `mode=ro` + `query_only`). Only the ingestion tools write to it. The live state is a separate database (`state/live_state.db`).

## Everyday commands
| what | command |
|---|---|
| all fast checks (unit suite, fixture baseline, import boundaries, engine parity/lookahead/idempotency/determinism/isolation) | `py scripts/check_all.py` |
| plus the real-database golden checks (long; read-only) | `py scripts/check_all.py --data` |
| final acceptance (also requires the import-boundary allowlists to be empty) | `py scripts/check_all.py --data --final` |
| ingest prices for a date range (its own step, BEFORE the EOD run) | `py scripts/ingest_raw_bhavcopy_range.py --start 2026-10-01 --end 2026-10-31` (see `--help`) |
| run the EOD decision step for one date (mode gate, freshness check, decide, state store, ticket file) | `py scripts/run_eod.py [--date YYYY-MM-DD] [--mode PAPER]` |
| daily health check (stale data, state store vs journal, state behind the lake) | `py scripts/daily_health_check.py` |
| daily ASM/GSM snapshot (forward history; none exists before 2026-11-08) | `py scripts/snapshot_asm_gsm.py` |
| start the API for the dashboard and the 17:00 / 19:00 IST scheduler | `python -m stockbot.live.main` then `cd ui && npm run dev` |

`runtime.mode` in `stockbot/config/shared.yaml` is **PAPER** by default. LIVE refuses to run unless a registered strategy has status `live` and a `validation_ref`, and fails closed without an ASM/GSM snapshot for the date.

## The rules this code base enforces (each one is a test)
* Layers: `tests/unit/test_import_boundaries.py` (a violation fails the build; seeded violations prove it fails). No strategy imports another, no engine/strategy code gets a database connection, no network library in backtest/engine/risk/strategies.
* Point-in-time: market data reaches decision code only through `AsOfView(conn, as_of)`; asking for a later bar raises; changing every later row changes no earlier decision.
* One decision function for backtest and live; parity over 71 sessions; the same live date twice changes nothing.
* Shared gates and costs: a strategy cannot override them. Parameters of one strategy live in its `StrategySpec` only.
* Trials are counted: the hash-chained trial ledger (`stockbot/validation/ledger/records`) records every pre-registration; a family of strategies is registered and its results recorded together, so multiplicity corrections cannot lose a member.
* Data limits are written down: `docs/data_audit/DATA_KNOWN_ISSUES.md` (KI-001 shares outstanding is not point-in-time and the market-cap gate is parked; KI-002 trade rate vs the gates; KI-003 no ASM/GSM history; KI-004 and others).

## Before any strategy goes live
`docs/restructure/PRE_LIVE_LIST.md` lists what was deliberately left undone (correction replay for late operator reports, the mandate's 10 positions / 10% total risk versus the 12 / 15% in `shared.yaml`, an earnings alert, a drawdown guard, an operator reconciliation command line, and the legacy dashboard tables that are not connected to the new state store).

## History
The restructure was done in reviewed stops (`Claude_Docs/STOCKBOT_RESTRUCTURE_STOP1..5_REPORT.md`); `docs/restructure/` keeps the plan decisions, the engine contract, the file inventory, the list of every removed test with its reason, and the fail-before evidence for each new test.
