# Exit policies: status

Last updated: 2026-11-10 (STOP A).

## Done
- Branch `exit-policies` created from `origin/master` (ab6ae5b); local `master` is stale and was not used.
- ba284c8: task brief saved as `docs/exit_policies/BRIEF.md`.
- Design note: `Claude_Docs/STOCKBOT_EXIT_POLICIES_DESIGN.md` (no code written).

## Open items (need a reply before STOP B)
- `finsight.db` is absent in this environment: fingerprint and G2 cannot be done here. Where should Stage B run?
- Engine finding: `engine/corporate.py::_rescale` does not rescale `pending_exit` (fix needs approval).
- Boundary check treats `stockbot.strategies.spec` as a strategy (fix needs approval).
- `Claude_Docs/STOCKBOT_MOMENTUM_GROUNDWORK_REPORT.md` is missing from the repository.
- Confirm `highest_close` seed and the meaning of N sessions.

## Decisions (dated)
- 2026-11-10: owner branch name `exit-policies` used instead of the session default; no attribution trailers in commits (owner's rule).

## Next step
STOP B (tests first, then implementation) after the reviewer replies.

## Limitations (so far)
- Baseline here: G1 548 passed, 8 skipped, 4 failed (yfinance not installed, golden/ledger hash mismatch in this checkout); G3 2 passed; G2 not run (no database).
