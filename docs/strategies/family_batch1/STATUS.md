# family_batch1: status

Last updated: 2026-11-11 (branch `family-prep`, from origin/master a7aff12).

## Done
- Allow-list `APPROVED_STRATEGY_IDS` (5 ids) in `tests/fixtures/boundaries.py`; `test_no_strategy_in_the_tree.py` generalised (unlisted folder fails, listed may be absent, import boundary tested per id, one strategy class per folder, no overlay). Commit fcd88b3.
- Guide tests (`test_guides_consistent`, `test_guide_html`) skip files owned by an approved strategy (`strategy_owned`); one generic sentence added to CODEBASE_GUIDE C.6. Verified with a temporary `low_volatility` folder plus script: all guide tests pass.
- `scripts/validate_family.py` (joint Max-T over K series, T2, joint T3, gates per member) and `tests/unit/test_validate_family.py` (12 tests). Row added to CODEBASE_GUIDE (required by the guide test). Commit 0f4d58b.
- K = 4 ledger tests (temporary files only). No ledger row written.
- `FAMILY.md`, `BRIEF.md` here.
- G1 880 passed / 8 skipped. Full G2 1009 passed (whole folder); G3 2 passed; DB sha unchanged. Report: Claude_Docs/FAMILY_PREP_REPORT.md.

## Open / blockers
- Owner to confirm the four members (allow-list has five; this plan assumes near_52w_high is out because it is already registered and run).
- `record_family_results` writes ONE row carrying K results, not K rows (shared ledger code, not changed).

## Next
Owner reviews; strategy branches start stage 1. Nothing is registered or run.

- 2026-11-12 owner decision: family_batch1 has THREE members (short_term_reversal, trend_breakout_100d, pullback_uptrend), K = 3. low_volatility is set aside (its branch stays unmerged). Register with `--expect-k 3`; the registration snippet in each PREREGISTRATION section 13 lists three specs.
