# Exit policies: status

Last updated: 2026-11-10 (STOP B).

## Done (branch exit-policies, not merged)
- ba284c8 brief; aac4f4b design note (STOP A)
- 2c7eac9 engine fix: pending_exit scales with shares on a split/bonus (own commit and tests)
- a4071c9 boundaries: strategies may import stockbot.engine.exit_policy only; `spec` is not a strategy name
- 701a1dc tests first (failing at import); a6be7e0 library, `resolve`, `policies_for`, wiring (`run_backtest(policies=None)`, `Book.from_strategies`)
- 1328855 docs: EXIT_POLICIES.md, ARCHITECTURE row, codebase guide (md, json, rebuilt html)
- Report: Claude_Docs/STOCKBOT_EXIT_POLICIES_REPORT.md

## Open items
- G2 and the finsight.db sha256/mtime check were NOT run (no database in the cloud container): owner or a local session before merge.
- 2 G1 failures (golden file hashes, exploratory ledger hash) are pre-existing in this checkout; suspected CRLF/LF, not verified.
- `Claude_Docs/` copies of the codebase guide are stale.

## Decisions (dated)
- 2026-11-10: branch name exit-policies; no attribution trailers (owner).
- 2026-11-10 (STOP A reply): build and test here, G2/fingerprint deferred; `_rescale` pending_exit fix approved; `spec` exclusion approved; highest_close seeded from entry price; N counts the entry session as 1, exit at open of session N+1; extra ids starting with fixed_hold_/trailing_pct_ rejected; no `also=`; no upper bound on N; integer percent.

## Next step
Reviewer reads the report; owner runs G2 and the fingerprint, then merges. No further stage started.

## Limitations
See section 7 of the report: integer percent, float prices, closed-out strategy with open positions fails loudly, seed from the fill price, no-bar sessions invisible to policies.
