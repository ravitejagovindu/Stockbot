# Proposal: the `stockbot/` namespace move and how imports change (Phase 1, proposal only)

## Layout
Code goes under a single top-level package `stockbot/` at the repo root. Non-code data stays where it is, so nothing in `data/` (reference CSVs, F9 results, the untracked lake files) moves:

```
StockBot/
├─ stockbot/            code only (config, data, universe, risk, engine, strategies, backtest, live, validation, data_checks)
├─ data/                NON-code: reference/, f9/ (results), plus untracked lake artefacts; no .py files
├─ tests/  scripts/  docs/  ui/  Claude_Docs/  finsight.db
```
So `stockbot.data` (code) and `data/` (files) coexist without an import clash. `finsight.db` stays where it is; the code reads it through a path from shared config, never a hard-coded string (two current files hard-code a path: `verify_db.py` — deleted — and `fix_blocker*`/`generate_confidence_report.py`).

## Import mapping (applied mechanically, one batch per source package)
| now | after |
|---|---|
| `engine_core.adjustments`, `engine_core.indicators` | `stockbot.data.adjustments`, `stockbot.data.indicators` |
| `engine_core.costs`, `engine_core.sector_map` | `stockbot.risk.costs`, `stockbot.risk.sector_map` |
| `engine_core.corporate_action_events` | `stockbot.engine.corporate_action_events` |
| `engine_core.max_t_bootstrap`, `prereg_lock`, `trade_metrics` | `stockbot.validation.*` |
| `engine_core.preflight`, `data.quality_checker` | `stockbot.data_checks.*` |
| `engine_core.mode`, `config`, `logging_config` | `stockbot.config.*` |
| `data.ingestion.*` | `stockbot.data.ingestion.*` |
| `data.db.*` | `stockbot.data.db.*` (Phase 3 splits lake vs state) |
| `backtest.no_network`, `backtest.simulator`, `backtest.run_backtest` | `stockbot.backtest.*` |
| `backtest.exclusions` | `stockbot.universe.exclusions` |
| `live_runner.*` | `stockbot.live.*` (routers → `stockbot.live.api`) |
| modules classified `rewrite` / `old-strategy` / `undecided` | **not moved in Phase 2**: they stay importable at their old path until the phase that replaces them, so Phase 2 is a pure move for the `move` rows only |

## How the move is done (Phase 2)
1. `git mv` the `move`-category files in small groups; each commit also rewrites the imports that point at the moved module (an AST-based rewriter driven by the table above, output reviewed as a diff). Commits are "move" commits only.
2. Tests move with their code (`tests/unit/test_adjustments.py` etc. keep their names; only imports change).
3. After each group: G1 (329 passed / 63 skipped), G3 and G4 identical to `BASELINE.md`; G2 after the last group.
4. Entry points: `python -m live_runner.main` becomes `python -m stockbot.live.main` (README, scheduler, and any scheduled task must be updated; the `ui/` is a separate JS app that talks to the API by URL, and the routers move unmodified, so the URL contract is unchanged). Scripts keep their file names and get a one-line `sys.path` bootstrap until `scripts/` becomes thin wrappers (Phase 8).
5. `tests/conftest.py` adds the repo root to `sys.path` (as the scripts do today); no installable-package step is required, but I can add a minimal `pyproject.toml` if you prefer `pip install -e .` (not assumed).

## Risks
- The old-strategy / rewrite modules import moved modules (for example `engine_core.risk_sizing` imports `engine_core.adjustments`): their imports are rewritten too, so they keep working at the old paths until deleted.
- `tests/data_integrity/test_corporate_actions_real_db.py` imports `scripts.f2_engine_scan.session_for`; that path stays valid until Phase 8.
- The ledger hash chain must not depend on file paths (Phase 7): to be checked before moving `backtest/outputs/trial_ledger*.csv`.
