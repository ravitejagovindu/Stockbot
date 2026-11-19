# momentum_calm: stage 1 report

Branch `momentum-calm` (worktree `F:\Projects\Ravi\StockBot_wt_momentum_calm`, from master 855a74c). Date 2026-11-19. Nothing was run on the real lake except the overlap check (counts and symbol lists only). No backtest, baseline, benchmark, validation or registration. No return, P&L, win rate or equity of this strategy was computed or looked at.

## Summary
- **Overlap rule outcome: CONTINUE.** Over the 119 monthly signal dates (2016-12-01 to 2026-10-01) the mean overlap of momentum_calm's 25 picks with plain riskadj_momentum's 25 is **0.358** (median 0.32, min 0.04, max 0.84), against the pre-declared stop threshold of 0.85. Months with fewer than 25 calm candidates (calm and r12 > 0): **1**; calm candidates per month: min 23, median 96, max 255. The calm half is about half of the eligible names every month (median share 0.50). The pre-registration and run commands were therefore written.
- **Text status: "FINAL TEXT, NOT REGISTERED".** Spec hash **`d215b84c5b2c340929a7bf4bef3d01e3da4f8e613d35fd0a9bc62edc96cbad55`**, status `research`, exit policy `mc_trailing_atr3_floor8`, family `family_batch7`, K = 1, gates hash `e9b6407f908ff102dd25d9bc3b21a78a52b24c0ea082bba2cd3bb08f81188054` unchanged.
- **Baseline pool question (open, for the owner):** the text registers riskadj_momentum's pool rule unchanged (20 random draws per trade from the shared-eligible pool of that date, not restricted to calm stocks), so any benefit of simply holding calm stocks counts as the strategy's edge in T1. **My view: I think a pool restricted to calm stocks would be the cleaner test of the momentum part**, because with the unrestricted pool a T1 pass could come from the calm half alone; the cost is that it needs a change to the baseline script (the pool filter) and answers a narrower question. Not decided; the unchanged pool is what is written. Changing it after registration is a new trial, so it should be settled before registering.
- **Deviation from the brief, stated:** "REUSE its functions, do not re-implement" could not be done by import, because the boundary rules forbid a strategy importing another strategy (`tests/unit/test_import_boundaries.py`). `is_signal_session`, `assess`, `initial_stop`, `order_signals` and the ATR indicator are verbatim copies (the same way riskadj_momentum_daily was built), and a test proves that with the filter off the picks equal riskadj_momentum's.
- **One reading to confirm:** sigma252 is the sd of the 252 daily log returns of the closes t-252..t (the 253 bars the rule already needs, same as lowvol_uptrend). "Sessions t-251..t" can be read as 251 returns; I used 252 and wrote it into the text.

## Shared files touched
- `tests/fixtures/boundaries.py`: `momentum_calm` appended to `APPROVED_STRATEGY_IDS` (nine ids). A deliberate reviewed change, as for the earlier strategies.
- `tests/unit/test_no_strategy_in_the_tree.py`: the strategy-policy list gains `stockbot/strategies/momentum_calm/exits.py::McTrailingAtr3Floor8`; the "exactly the eight ids" test becomes "nine ids" with the new id. Reason: the allow-list is pinned by that test and a strategy-owned exit policy must be listed.
- `docs/guides/CODEBASE_GUIDE.md`: two rows (`momentum_calm_overlap.py`, `momentum_calm_comparison.py`), required by `test_every_script_is_named_in_the_codebase_guide`.
- Not touched: any existing strategy, spec, exit policy, gate, `shared.yaml`, ledger row, stored result, `build_results_page.py`.

## What was built
- `stockbot/strategies/momentum_calm/` (strategy, `mc_trailing_atr3_floor8` exit policy, indicators). The strategy exposes `screen()` (counts and the ranked list, filter switchable for the overlap check and the equality test) and `MomentumCalmStrategy.propose`.
- Scripts: `scripts/{research,baseline_matched_random,benchmark_nifty_matched,evaluate_validation_gates}_momentum_calm.py` (copies of the riskadj_momentum ones: id, strategy import, policy class; results folder `docs/strategies/momentum_calm/results_run1/`, not created), `scripts/momentum_calm_overlap.py`, `scripts/momentum_calm_comparison.py`.
- Documents: `docs/strategies/momentum_calm/{BRIEF,STATUS,PREREGISTRATION,RUN_COMMANDS,OVERLAP}.md` and `OVERLAP.json`.

## Overlap check (step 2)
Run once, `STOCKBOT_VIEW=memory`, window 2016-01-01 to 2026-10-16, through `short_step` (run lock, database check before and after): **"database check ... unchanged"**, correction counter 0, exit 0. It took about 40 minutes (the first output appeared after about 12 minutes: building a memory view for every session to find the signal dates is the slow part; not an error). Output: per-date table, mean/median/min/max overlap, months with fewer than 25 calm candidates and min/median/max calm-candidate counts, in `OVERLAP.md` and `OVERLAP.json`. A test asserts no return/P&L/equity key appears in its output.

## Ledger plan (NOT run)
```
register_family(path=<family_ledger.csv>, family_id="family_batch7", members=[<momentum_calm SPEC>],
                gate_params=asdict(validation_gates), git_sha=<approved commit>,
                reason="family_batch7 K=1: momentum_calm, monthly momentum among the calmest half of stocks (PREREGISTRATION.md)")
```
`tests/unit/test_momentum_calm_dry.py::test_the_family_batch7_payload_validates_with_k_1_on_a_copy_of_the_real_ledger` registers exactly this into a copy of the real ledger: budget 1, member hash as above, `verify_ledger` passes, registering twice without a reason is refused, gates hash `e9b6407f...8054`. The real ledger was not written.

## Tests
- `test_momentum_calm_strategy.py`: **54 passed** (calm filter: median over all eligible names including r12 <= 0 names, a tie at the median is calm, an even count takes the mean of the middle two, a name without 252 sessions has no sigma and is not in the median nor proposed, ranking by score among calm names, at most 25, no look-ahead, equality with riskadj_momentum with the filter off; the exit policy: never moves down, floor, ATR, timing, corporate-action rescale, SQL = memory view; spec, hash covers the new params, status research).
- `test_momentum_calm_scripts.py`: 18 passed. `test_momentum_calm_dry.py`: 9 passed: research, baseline and gates run end to end on fixture lakes with `STOCKBOT_NON_EQ=held` and with it off (manifest `non_eq_view` and `non_eq_events`, a restricted stock never bought or drawn, no `risk_override`), the overlap script and the comparison script on fixture files, the ledger plan.
- Boundary, allow-list and import tests: pass.
- **G1 (all unit and integration tests): see the result line at the end of this report.**

## What ran and what did not
Ran: unit and fixture tests, the overlap check (counts only), the comparison script against the already stored runs of family_batch2, family_batch6 and family_batch3 as a smoke check only (no result of momentum_calm exists to compare). Did NOT run: research, baseline, benchmark, gates, validate_family, any ledger write, registration.

## For the owner
1. Decide the baseline pool question (above) before registering.
2. Register `family_batch7` (K = 1) on master at the commit carrying the pre-registration, then a separate run block follows (`RUN_COMMANDS.md`: morning start before about 14:00 IST, never spanning 19:30, about 2.4 hours).
3. **Pre-existing on master, not mine:** `scripts/relative_drawdown_table.py` has no row in `CODEBASE_GUIDE.md`, so `test_every_script_is_named_in_the_codebase_guide` fails on master (it was merged without one). I did not touch it.

## G1 result
`py -m pytest tests/unit tests/integration`: **1617 passed, 9 skipped, 1 failed** in 44 minutes. The one failure is the pre-existing `test_every_script_is_named_in_the_codebase_guide`, which names only `scripts/relative_drawdown_table.py` (merged to master without a guide row; the two momentum_calm scripts are in the guide). Every other test passes.
