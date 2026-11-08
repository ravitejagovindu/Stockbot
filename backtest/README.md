# backtest/ - data only (restructure Phase 10)

No code lives here any more (the backtest runner is `stockbot/backtest`). What remains is kept on purpose:

* `outputs/selection_decision.json` - the official decision of the rejected CFG-01..06 search ("NONE": no candidate passed all gates). The LEGACY row of the trial ledger records the same outcome.
* `outputs_recomputed_net/` - the 27 files of the F1 net-R recomputation of the six configurations (pooled trade CSVs, equity curves, `recompute_comparison.csv`, `selection_decision.json`). Kept whole by the reviewer's decision at STOP 2; the exploratory ledger (`stockbot/validation/ledger/records/trial_ledger_exploratory.csv`) names this folder, and `tests/data_integrity/test_entry_bar_real_lake.py` reads its pooled trade files.

Everything else that used to be here (the other 49 files of `outputs/`, `outputs_v1_stale/`, the legacy simulator and the six-config runner) is in git tag `pre-restructure`. No trial-ledger entry references a deleted file (`docs/restructure/LEDGER_MANIFEST.md`; tested).
