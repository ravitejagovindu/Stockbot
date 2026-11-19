# riskadj_momentum_daily: status

Last updated: 2026-11-16 (build, counts, scripts and final pre-registration text done; waiting for the owner's review).

## Done
- Shared engine change (approved, own commit 433b1e1): opt-in exit history (`stockbot/engine/exit_history.py`, `decide.py`, `reports.apply_effect`, `strategies/base.py` docstring, two guide rows); proof in the report (fixture byte-identity of riskadj_momentum and lowvol_uptrend, full G2 1,422 passed, 14 new tests).
- Allow-list edits (own commit 125d44d): eight ids, the strategy-owned policy class `RmdTrailingAtr3Floor8`.
- Gates: G1 1,372 passed 9 skipped; full G2 1,502 passed; G3 2 passed; DB hash unchanged (`Claude_Docs/RISKADJ_MOMENTUM_DAILY_BUILD_REPORT.md`).
- Strategy (`stockbot/strategies/riskadj_momentum_daily/`), final spec hash `5b06f092df061bff1532093d21ea21c88c3f2db64ddd66e0cbe81bd5c0446e19`; `expected_trade_rate` 8.1 (proposed).
- Counts study over the real lake (counts only): `counts/`.
- Scripts: `research_`, `baseline_matched_random_` (own draw loop, pool of option C), `benchmark_nifty_matched_`, `evaluate_validation_gates_` `riskadj_momentum_daily.py`, `signal_count_riskadj_momentum_daily.py`; tests in `tests/unit/test_riskadj_momentum_daily_strategy.py` and `test_riskadj_momentum_daily_scripts.py` (fixture lakes only).
- `PREREGISTRATION.md` final text (family_batch4, K = 1, gates hash e9b6407f...8054); `RUN_COMMANDS.md` (output folder `results_run1/`).

## Open items (owner)
Review; register `family_batch4` (K = 1) on master at the commit carrying the pre-registration; authorise the registered run.

## Next step
None until the owner replies. No backtest on the real lake has been run; no return of this strategy has been looked at.

## 2026-11-18: re-run with BE/BZ data pre-registered as family_batch5, not yet registered
A NEW trial of the same strategy (same spec hash, K = 1, family `family_batch5`) with `STOCKBOT_NON_EQ=held` and the BE/BZ sell model; window and everything else as batch 4. Final text `PREREGISTRATION_NONEQ.md` (FINAL TEXT, NOT REGISTERED), commands `RUN_COMMANDS_NONEQ.md`, output folder `results_run2_noneq/` (not created). Branch `rmd-noneq-run`. The family_batch4 run 1 result stands as recorded. Waiting for the owner to register the family on master; nothing has been run.

## 2026-11-19: family_batch5 run done
The BE/BZ re-run (registered as family_batch5, K = 1) ran once on the real lake: T1 adjusted p 0.4236 (2-month blocks) and 0.4270 (3-month blocks), max drawdown gate missed (45.6
## 2026-11-19: family_batch5 run done
The BE/BZ re-run (registered as family_batch5, K = 1) ran once on the real lake: T1 adjusted p 0.4236 (2-month blocks) and 0.4270 (3-month blocks), max drawdown gate missed (45.6 percent), verdict NOT DEMONSTRATED by the decision rule, db_check clean (file hash and guard counter unchanged). The family_batch4 run 1 result stands as recorded. Results in `results_run2_noneq/`; report `Claude_Docs/RMD_NONEQ_RUN_REPORT.md`. Open for the owner: write the `record_family_results` row on master (command in the report).

## 2026-11-19: pre-registered in family_batch6, not yet registered
This strategy is a member of family_batch6 (K = 2, with its sibling riskadj_momentum or riskadj_momentum_daily): a re-run of its own separate backtest at 0.5 percent risk per trade (per-run override STOCKBOT_RISK_PCT, shared.yaml unchanged) with STOCKBOT_NON_EQ=held. Final text `docs/strategies/family_batch6/PREREGISTRATION.md` (FINAL TEXT, NOT REGISTERED), commands `docs/strategies/family_batch6/RUN_COMMANDS.md`, branch `half-risk-run`. Earlier results of this strategy stand as recorded. Waiting for the owner to register the family on master; nothing has been run.

## 2026-11-19: family_batch6 run done
Ran once at 0.5 percent risk per trade with STOCKBOT_NON_EQ=held (family_batch6, K = 2): T1 not significant at either block for either member and the 20 percent drawdown gate missed (monthly 23.7, any-day 24.9); verdict NOT DEMONSTRATED for both by the decision rule; db_check clean (file hash and guard counter unchanged). Earlier results of this strategy stand as recorded. Results in `docs/strategies/family_batch6/results/`, report `Claude_Docs/FAMILY_BATCH6_RUN_REPORT.md`. Open for the owner: the `record_family_results` row on master (command in the report).
