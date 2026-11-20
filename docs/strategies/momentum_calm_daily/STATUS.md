# momentum_calm_daily: status

Last updated: 2026-11-20 (stage 1 done; waiting for the owner to register family_batch8 and authorise the run block).

## Done
- Allow-list: `momentum_calm_daily` added to `APPROVED_STRATEGY_IDS` (ten ids) and its exit policy to the strategy-policy list of `tests/unit/test_no_strategy_in_the_tree.py`.
- Strategy (`stockbot/strategies/momentum_calm_daily/`), spec hash `814dce51b04fbfb7d2463822fd81176643e4a4e35bcc2b3861745270104bd152`, status `research`; unit tests `tests/unit/test_momentum_calm_daily_strategy.py` (calm filter on a hand-made lake, cooldown interplay, equality with riskadj_momentum_daily with the filter off, exit policy, spec hash, boundaries).
- Overlap check (counts only, no return): `OVERLAP.md` and `OVERLAP.json`, 118 sampled sessions (one in 21), **mean overlap 0.355** against the pre-declared stop threshold 0.85, so the work continued.
- Scripts: `scripts/{research,baseline_matched_random,benchmark_nifty_matched,evaluate_validation_gates}_momentum_calm_daily.py`, `scripts/momentum_calm_daily_overlap.py`, `scripts/momentum_calm_daily_comparison.py`; tests `test_momentum_calm_daily_scripts.py` and `test_momentum_calm_daily_dry.py` (fixture lakes only, switch on and off, ledger plan validated on a copy of the ledger).
- `PREREGISTRATION.md` (FINAL TEXT, NOT REGISTERED) and `RUN_COMMANDS.md`.

## Open items (owner)
1. Register `family_batch8` (K = 1) on master at the commit that carries the pre-registration.
2. Authorise the run block (`RUN_COMMANDS.md`): one heavy job at a time; the run blocks the daily data job, which waits and catches up.

## Next step
None until the owner replies. No backtest on the real lake has been run.

## 2026-11-20: family_batch8 run done
Ran once, every registered step once, `STOCKBOT_VIEW=memory`, `STOCKBOT_NON_EQ=held`, standard 1.0 percent risk: T1 not significant at either block (adjusted p 0.1391 and 0.1216), four of the five gates met, the 20 percent drawdown gate missed (35.8); verdict NOT DEMONSTRATED by the decision rule. db_check clean (file hash and guard counter unchanged). Results in `results_run1/`, report `Claude_Docs/MOMENTUM_CALM_DAILY_RUN_REPORT.md`. Open for the owner: the `record_family_results` row on master (command in the report).
