# Tests removed during the restructure (reviewer rule Q9)

Each removed test is listed with the old rule it covered. A test of generic behaviour is never dropped without a ported replacement existing first; none of the tests below covers generic behaviour (sizing, heat caps, idempotency, corporate-action holds, regulatory barrier, network guard all stay).
G1 arithmetic is restated at every STOP as: previous baseline − removed + added.

| phase / commit | file | tests | rule covered | recoverable from |
|---|---|---|---|---|
| Phase 4.2 (git lock dropped) | `tests/unit/test_phase4_lock.py` | `test_validate_audit_rejects_dirty_tree`, `test_validate_audit_rejects_config_hash_mismatch`, `test_validate_audit_rejects_tampered_audit_file`, `test_validate_audit_recomputes_and_rejects_gate_failure` (4) | `authorize_live.py`: refuse to authorize live trading unless `audit.json` has a clean working tree, matches the `strategy_config.yaml` hash and `audit.sha256`, and every pass-gate is met (the old strategy's `gates.*`) | tag `pre-restructure`, same path |
| Phase 4.2 (git lock dropped) | same file | `test_git_lock_detects_modified_code`, `test_git_lock_detects_modified_config`, `test_git_lock_allows_auth_file_commit_on_top` (3) | `live_runner/git_lock.py`: refuse to start live if HEAD differs from the authorized SHA (code or config changed), allowing one commit that only adds `authorized_deployment.json` | tag `pre-restructure`, same path |

Running total: 7 removed (G1 352 → 345 at Phase 4.2).
