# riskadj_momentum_daily: status

Last updated: 2026-11-16 (build, counts, scripts and final pre-registration text done; waiting for the owner's review).

## Done
- Shared engine change (approved, own commit 433b1e1): opt-in exit history (`stockbot/engine/exit_history.py`, `decide.py`, `reports.apply_effect`, `strategies/base.py` docstring, two guide rows); proof in the report (fixture byte-identity of riskadj_momentum and lowvol_uptrend, full G2 1,422 passed, 14 new tests).
- Allow-list edits (own commit 125d44d): eight ids, the strategy-owned policy class `RmdTrailingAtr3Floor8`.
- Strategy (`stockbot/strategies/riskadj_momentum_daily/`), final spec hash `5b06f092df061bff1532093d21ea21c88c3f2db64ddd66e0cbe81bd5c0446e19`; `expected_trade_rate` 8.1 (proposed).
- Counts study over the real lake (counts only): `counts/`.
- Scripts: `research_`, `baseline_matched_random_` (own draw loop, pool of option C), `benchmark_nifty_matched_`, `evaluate_validation_gates_` `riskadj_momentum_daily.py`, `signal_count_riskadj_momentum_daily.py`; tests in `tests/unit/test_riskadj_momentum_daily_strategy.py` and `test_riskadj_momentum_daily_scripts.py` (fixture lakes only).
- `PREREGISTRATION.md` final text (family_batch4, K = 1, gates hash e9b6407f...8054); `RUN_COMMANDS.md` (output folder `results_run1/`).

## Open items (owner)
Review; register `family_batch4` (K = 1) on master at the commit carrying the pre-registration; authorise the registered run.

## Next step
None until the owner replies. No backtest on the real lake has been run; no return of this strategy has been looked at.
