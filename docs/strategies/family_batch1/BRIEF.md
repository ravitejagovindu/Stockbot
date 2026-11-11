# family_batch1: shared preparation (task text, saved as given)

BRANCH: family-prep   REPORT: Claude_Docs/FAMILY_PREP_REPORT.md

Goal: shared changes on master so four strategy branches can run in parallel, each touching only its own folder. Four strategies will be registered as ONE family (K=4, Max-T correction).

1. tests/unit/test_no_strategy_in_the_tree.py: generalise to an allow-list. Put APPROVED_STRATEGY_IDS in tests/fixtures/boundaries.py = near_52w_high, short_term_reversal, trend_breakout_100d, low_volatility, pullback_uptrend. Folders may be absent. Every approved folder must still obey the import boundary (only stockbot.engine.exit_policy from the engine). Any unlisted strategy folder fails.
2. Guides: make test_guides_consistent / test_guide_html / test_data_guide_html pass when strategy folders exist that the guides don't list. The guides mention "strategies live in stockbot/strategies/<id>/" once, generically. Strategy branches must never need to edit guides.
3. Family validation: check scripts/validate_near_52w_high.py and the T1 code. Provide a generic scripts/validate_family.py that takes K member result dirs and computes T1 with Westfall-Young Max-T JOINTLY across the K monthly-sum series (B=10,000, blocks 2 and 3 months, both must be significant, seed fixed). It also reports T2 and the T3 placebo size check, and evaluates the shared gates per member. Test on synthetic data: under the null, family-wise rejection must be about 5% and at most 7.5%; with a planted edge in one member only, that member is found.
4. Ledger: confirm register_family accepts K=4 in ONE entry, record_family_results writes K rows, and verify_ledger passes. Do NOT write any registration row; the owner does that on master.
5. Add docs/strategies/family_batch1/FAMILY.md: members, K=4, shared rules (same eligibility, top_n 25, shared gates, B1 seed 20261111, B2 benchmark, T1 as above), and the sequence: stage 1, owner review, one registration, runs, joint validation.

Tests: full G1, then full G2 and G3. Confirm DB sha256 unchanged. Push, report, STOP.

Standing rules: plain commit messages, no trailers or attribution lines; finsight.db read-only, sha256 dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752; no edits to stockbot/engine, stockbot/validation, config/shared.yaml, ledgers, docs/guides, tests/fixtures without stopping to tell the owner; numbers fixed, no tuning.
