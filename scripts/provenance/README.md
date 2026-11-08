# scripts/provenance - one-off and superseded scripts, kept as provenance (restructure Phase 8)

These scripts produced results that reports under `docs/` cite (the F2 raw-price swap and its checks, F2b point-in-time shares which was NOT USED, the rejected CFG-01..06
selection pipeline, the F1 net-R recompute, the F9 trade library). They are not part of any run path. They moved here from `scripts/` and `data/`; the code is unchanged apart
from the repo-root depth of `Path(__file__).parents[n]` and the dotted module names.

Reports written before the move cite the OLD paths; use the table. Tag `pre-restructure` holds every script at its old path.

| old path | new path | why it is kept |
|---|---|---|
| `scripts/f2_swap.py` | `scripts/provenance/f2_swap.py` | the reviewed raw-price swap (F2 STOP-2) |
| `scripts/f2_validate_staging.py` | `scripts/provenance/f2_validate_staging.py` | staging validation report |
| `scripts/f2_eligibility_triage.py`, `f2_load_plan.py`, `f2_move_dispositions.py`, `f2_post_swap_checks.py`, `f2_pre2020_compare.py`, `f2_volume_continuity.py` | same names under `scripts/provenance/` | F2 swap and audit steps cited by `docs/data_audit` reports |
| `scripts/ingest_historical_2018_2019.py` | `scripts/provenance/ingest_historical_2018_2019.py` | the original 2018-2019 backfill |
| `scripts/f2b_build_pit_shares.py`, `f2b_spotcheck.py`, `f2b_spotcheck_model.py`, `data/ingestion/pit_shares.py` | `scripts/provenance/` (the module is `scripts/provenance/pit_shares.py`) | F2b point-in-time shares (NOT USED, KI-001) |
| `scripts/recompute_step3_net_r.py` | `scripts/provenance/recompute_step3_net_r.py` | F1 net-R recompute of the old outputs |
| `scripts/select_candidate.py` | `scripts/provenance/select_candidate.py` | the six-config selection pipeline that wrote the trial ledger; its ledger writers now live in `stockbot.validation.ledger` (decision Q7) |
| `scripts/f9_trade_library.py` | `scripts/provenance/f9_trade_library.py` | builds `data/f9/trade_library.npz` with the old exit rules; regenerate through `engine.path` once a strategy's exit policy exists |
| `data/db/migration_f3_corporate_actions.py`, `migration_phase2.py`, `migration_phase3_paper.py`, `migration_securities_master.py` | `scripts/provenance/migrations/` | schema migrations already applied to `finsight.db` |
| `fix_blocker1_index_data.py`, `fix_blocker2_shares_outstanding.py` (repository root) | `scripts/provenance/` | one-off set-up of the index/VIX series and of the `shares_outstanding` snapshot behind KI-001 (moved in Phase 10) |
| `engine_core/regime_filter.py`, `engine_core/regime_gates.py` | `scripts/provenance/regime/` | the old macro kill switch (Nifty below its 200-day SMA or VIX above 22, 3-session re-entry hysteresis) and the bull-regime helpers. NOT part of any run path and not an overlay yet (decision D1: the overlay interface exists with a dummy under tests/, the kill switch is not implemented). Kept with their tests (`tests/unit/test_regime_filter.py`, `test_phase1_components.py`) so the rule stays executable and specified until a strategy needs it (moved in Phase 10) |

Scripts here that import `engine_core`, `data.db` or `live_runner` leave the tree in Phase 10 together with those modules; the reports that cite them then name the tag and commit.

Removed in Phase 10 (tag `pre-restructure` holds them): `verify_db.py` (hard-coded-path row counter, superseded by `stockbot.data_checks`), `generate_confidence_report.py` and `confidence_report.md` (report of the old paper-trading strategy).
Also removed in Phase 10 with the legacy backtest modules they import (tag `pre-restructure` holds them): `redesigned_random_baseline.py` (replaced by `stockbot.validation.random_baseline`), `count_candidate_signals.py`, `count_executable_entries.py`, `diagnose_trades.py`, `diagnose_trades_amended.py`, `evaluate_selection_hypotheses.py`, `generate_stage_by_stage_funnel.py` (analyses of the old strategy), `run_surveillance_scrapers.py` and `backtest/bifurcated_scraper` (the two invalid scrapers, F8).
