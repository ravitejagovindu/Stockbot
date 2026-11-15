# riskadj_momentum: status

Last updated: 2026-11-15 (stage 2 done; waiting for the owner to register family_batch2 and authorise the run).

## Done
- Allow-list: `riskadj_momentum` added to APPROVED_STRATEGY_IDS (own commit 0da1b65); the two shared tests in `tests/unit/test_no_strategy_in_the_tree.py` updated as approved (own commit: allow-list of six, one strategy-owned policy allowed).
- Strategy (`stockbot/strategies/riskadj_momentum/`), final spec hash `72dbec2c3da600cfe6de049a64efd530171ef2f539075f53e57a05e972ef27dc`; `expected_trade_rate` 1.9 confirmed; 44 unit tests.
- Counts study over the real lake (counts only): `counts/`.
- Stage 2 scripts: `scripts/research_riskadj_momentum.py`, `baseline_matched_random_riskadj_momentum.py` (own draw loop, every random entry with the strategy's own ATR stop rule and exit policy), `benchmark_nifty_matched_riskadj_momentum.py`, `evaluate_validation_gates_riskadj_momentum.py`; tests in `tests/unit/test_riskadj_momentum_scripts.py` (fixture lakes only), including the proof that the draw loop equals the shared helper when given the shared stop rule, and a `validate_family --expect-k 1` dry run.
- End-of-window rule (positions and random draws open at 2026-10-16 are closed at the last close and COUNT) written into `PREREGISTRATION.md` section 7a; implemented in the strategy-side scripts only.
- `PREREGISTRATION.md` final text (family_batch2, K = 1, gates hash e9b6407f...8054); `RUN_COMMANDS.md` (output folder `results_run1/`, expected times are estimates).
- Gates and the DB hash: see `Claude_Docs/RISKADJ_MOMENTUM_STAGE2_REPORT.md`.

## Open items (owner)
Register `family_batch2` (K = 1) on master at the commit carrying the pre-registration; then authorise the registered run (`RUN_COMMANDS.md`).

## Next step
None until the owner replies. No backtest on the real lake has been run; no return of this strategy has been looked at.
