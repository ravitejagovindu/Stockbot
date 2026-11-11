# FAMILY_PREP_REPORT (branch family-prep, from origin/master a7aff12)

## What was done
1. **Allow-list.** `APPROVED_STRATEGY_IDS` (near_52w_high, short_term_reversal, trend_breakout_100d, low_volatility, pullback_uptrend) in `tests/fixtures/boundaries.py`. `test_no_strategy_in_the_tree.py` now: unlisted folder fails; listed folders may be absent; at most one strategy class per approved folder, no overlay; every approved id obeys the import boundary (seeded-tree test per id: allowed imports pass; engine.decide, engine.exit_policies, another strategy, risk, network all caught; engine.exit_policy allowed). Other rules unchanged.
2. **Guides.** New `strategy_owned()` helper; `test_guides_consistent` and `test_guide_html` skip packages/modules/scripts owned by an approved strategy (`stockbot/strategies/<id>/`, `scripts/strategies/<id>/`, `scripts/*_<id>.py`). Checked by temporarily creating `stockbot/strategies/low_volatility/` plus `scripts/research_low_volatility.py`: guide, guide-html, data-guide-html, no-strategy, wrapper and import-alone tests all passed (then removed). One generic sentence added to CODEBASE_GUIDE C.6. `test_data_guide_html` needed no change.
3. **`scripts/validate_family.py`** (+ `tests/unit/test_validate_family.py`, 12 tests). Reuses the T1/pairing/placebo helpers of `validate_near_52w_high.py` and the gates code. Joint Max-T across K monthly-sum series, B 10,000, blocks 2 and 3, seed 20261111, both blocks must be significant; T2 per member; T3 placebo of the JOINT procedure (family-wise rate); gates per member when `--lake` is given (only NIFTY closes read, read-only), otherwise "not evaluated". Refuses mixed windows, label/manifest mismatch, duplicate ids, wrong `--expect-k`.
   - Null (K=4, 130 months, cross-correlation 0.5, t6 tails, B=1,000, 1,000 reps): family-wise rejection **4.7%** (no autocorrelation), **5.2%** (lag-1 0.08, like the real series), 4.1% (independent). The test uses 600 reps and asserts 2% to 7.5%.
   - Stress, reported not hidden: lag-1 autocorrelation 0.2 gave **7.5%** (600 reps, exploratory, not in the tests). Blocks of 2 to 3 months are short for that much autocorrelation; the existing F9 work found the same liberal tendency.
   - Planted edge in one member: found alone in the end-to-end 4-member run and in 20/20 seeds, wrong member found at most once in 20 runs.
4. **Ledger (tmp files only, no row written).** `register_family` accepts K=4 in ONE entry (budget 4); `verify_ledger` passes. **Correction to the brief:** `record_family_results` writes ONE `FAMILY_RESULTS` row whose `results_json` holds all four members' results (missing or extra member refused), not four rows. Chain verifies. If you want four rows that is a change to shared ledger code; I did not make it.
5. **`docs/strategies/family_batch1/{FAMILY,BRIEF,STATUS}.md`.**

## Needs your decision
- **Members:** the allow-list has five ids, the family has four. FAMILY.md assumes the four other than near_52w_high (already registered as its own family and run). Please confirm.
- **Shared-file edits made as part of the task:** `tests/fixtures/boundaries.py` and `docs/guides/CODEBASE_GUIDE.md` (generic sentence, and one script row for validate_family.py, which the guide test requires). Nothing in stockbot/engine, stockbot/validation, config/shared.yaml, ledgers or the DB changed.
- A new script `*_<id>.py` or a folder under `scripts/strategies/<id>/` is exempt from the guide; any other new script still needs a guide row.

## Tests
- **G1** (`tests/unit tests/integration`): 880 passed, 8 skipped (before: 856 at the last near_52w_high STOP on its branch; master baseline not separately run).
- **Full G2** (`STOCKBOT_DATA_TESTS=1 STOCKBOT_FINAL_CHECK=1 pytest tests`, whole folder, 50 min 55 s): **1009 passed**, 0 failed, 0 skipped.
- **G3**: 2 passed (also inside the full run).
- finsight.db sha256 unchanged: dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752.

## Not run
Nothing on real data: no registration, no backtest, no real validation. The `--lake` path of validate_family.py is exercised only through the gates function with a synthetic Nifty series, not against the real database.
