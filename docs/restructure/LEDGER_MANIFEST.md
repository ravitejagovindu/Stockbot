# Ledger and pre-registration files: old and new locations (Phase 7.2)

Pure move with `git mv` (history follows); no byte changed; no ledger row edited. The chain verified before and after (`baseline/ledger_chain_before.txt`, `baseline/ledger_chain_after.txt`).

| file | old location | new location | sha256 (raw bytes) |
|---|---|---|---|
| hash-chained trial ledger (2 rows: LEGACY, REGISTRATION) | `backtest/outputs/trial_ledger.csv` | `stockbot/validation/ledger/records/trial_ledger.csv` | `bc6927bf4de1e14924d06d42cc19a4a4fa18a5721c61775e67545dfd685d25e6` |
| exploratory ledger (no chain, a sha256 pin only) | `backtest/outputs/trial_ledger_exploratory.csv` | `stockbot/validation/ledger/records/trial_ledger_exploratory.csv` | `090c1c178bc434a1fa0778a97aa94b5f0abe320f03513090cab0891f8dbe2049` |
| pre-registration of CFG-01..06 (the rejected records) | `backtest/pre_registered_configs.yaml` | `stockbot/validation/ledger/records/pre_registered_configs.yaml` | `18931c4f9640c0cc7bde31310f3ce4e44e0409c7af93de51b19acf9b30cba4f4` |

* The chain's last `row_hash` is `869d1bd13d592ce635bed70c10081d6b2037a79272f64dabe21819a9152125d1` before and after. The chain covers the content fields of each row (timestamp, commit, selected config, reason, gate-reached values, row type, yaml/gates hashes, budget); none of them is a file path, so the move cannot break it.
* The `yaml_sha256` in the REGISTRATION row equals the (line-ending-normalised) sha256 of `pre_registered_configs.yaml`; a test pins this. The yaml's own first comment line still reads `backtest/pre_registered_configs.yaml`: the file is byte-identical on purpose.
* The exploratory ledger names `backtest\outputs_recomputed_net` in its `outputs_dir` column. That folder is kept in place (decision at the STOP 2 review) and is not touched before Phase 10.
* Code that wrote or read these paths (`scripts/select_candidate.py`, `backtest/run_candidate_simulations.py`, three tests) points at the new location.
* Tests: `tests/unit/test_ledger_yaml_hash.py` (yaml hash, chain verification at the new location, no path in any row, exploratory pin and no chain). Each has a fail-before row in `PARTB_FAIL_BEFORE.md`.
