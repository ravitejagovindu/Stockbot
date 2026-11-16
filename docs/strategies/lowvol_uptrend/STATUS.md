# lowvol_uptrend: status

Last updated: 2026-11-16 (registered run 1 done; report Claude_Docs/LOWVOL_UPTREND_RUN1_REPORT.md; waiting for the owner).

## Done
- Approved shared edits (own commit 3998fd9): `lowvol_uptrend` in APPROVED_STRATEGY_IDS; allow-list of seven ids and the strategy-owned policy `LvTrailingAtr3Floor8` in `tests/unit/test_no_strategy_in_the_tree.py`.
- Strategy (`stockbot/strategies/lowvol_uptrend/`), final spec hash `52e7ee3ccc2e150d7e4b6b54266bb2c73a8788612691ece475bfa7d1bb0e9e68`; `expected_trade_rate` 1.3 (proposed).
- Counts study over the real lake (counts only): `counts/`.
- Scripts: `research_`, `baseline_matched_random_`, `benchmark_nifty_matched_`, `evaluate_validation_gates_` `lowvol_uptrend.py`, and `signal_count_lowvol_uptrend.py`; tests in `tests/unit/test_lowvol_uptrend_strategy.py` and `test_lowvol_uptrend_scripts.py` (fixture lakes only).
- `PREREGISTRATION.md` final text (family_batch3, K = 1, gates hash e9b6407f...8054); `RUN_COMMANDS.md` (output folder `results_run1/`).
- Gates: G1 1,278 passed, full G2 1,408 passed, G3 2 passed; DB hash unchanged (`Claude_Docs/LOWVOL_UPTREND_BUILD_REPORT.md`).

## Open items (owner)
Review; register `family_batch3` (K = 1) on master at the commit carrying the pre-registration; authorise the registered run.

## Next step
None until the owner replies. No backtest on the real lake has been run; no return of this strategy has been looked at.
