# momentum_calm: status

Last updated: 2026-11-19 (stage 1 done; waiting for the owner to register family_batch7 and authorise the run block).

## Done
- Allow-list: `momentum_calm` added to `APPROVED_STRATEGY_IDS` and its exit policy to the strategy-policy list of `tests/unit/test_no_strategy_in_the_tree.py` (nine ids).
- Strategy (`stockbot/strategies/momentum_calm/`), spec hash `d215b84c5b2c340929a7bf4bef3d01e3da4f8e613d35fd0a9bc62edc96cbad55`, status `research`; unit tests `tests/unit/test_momentum_calm_strategy.py` (calm filter on a hand-made lake, exit policy, spec hash, boundaries).
- Overlap check (counts only, no return): `OVERLAP.md` and `OVERLAP.json`, 119 signal months, **mean overlap 0.358** against the pre-declared stop threshold 0.85, so the work continued.
- Scripts: `scripts/{research,baseline_matched_random,benchmark_nifty_matched,evaluate_validation_gates}_momentum_calm.py`, `scripts/momentum_calm_overlap.py`, `scripts/momentum_calm_comparison.py`; tests `test_momentum_calm_scripts.py` and `test_momentum_calm_dry.py` (fixture lakes only, switch on and off, ledger plan validated on a copy of the ledger).
- `PREREGISTRATION.md` (FINAL TEXT, NOT REGISTERED) and `RUN_COMMANDS.md`.

## Open items (owner)
1. Register `family_batch7` (K = 1) on master at the commit that carries the pre-registration.
2. Decide the baseline pool question (PREREGISTRATION section 5): the text registers riskadj_momentum's pool unchanged (not restricted to calm stocks).
3. Authorise the run block (`RUN_COMMANDS.md`): morning start, one heavy job at a time.

## Next step
None until the owner replies. No backtest on the real lake has been run.
