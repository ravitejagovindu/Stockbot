# momentum_calm_daily: stage 1 report

Branch `momentum-calm-daily` (worktree `F:\Projects\Ravi\StockBot_wt_mc_daily`, from master 1ea1f41). Date 2026-11-20. Nothing was run on the real lake except the overlap check (counts and symbol lists only). No backtest, baseline, benchmark, validation or registration. No return, P&L, win rate or equity of this strategy was computed or looked at.

## Summary
- **Overlap rule outcome: CONTINUE.** On 118 sampled sessions (the first session with a 252-session window, 2016-12-01, and every 21st session after it, up to 2026-10-15; sampled because every session is a signal day) the mean overlap of momentum_calm_daily's 25 picks with plain riskadj_momentum_daily's pure top 25 (no cooldown, slots or cash) is **0.3553** (median 0.32, min 0.04, max 0.84), against the pre-declared stop threshold of 0.85. Sampled sessions with fewer than 25 calm candidates (calm and r12 > 0): **0**; calm candidates per sampled session: min 33, median 94, max 247. The calm half is half of the eligible names (median share 0.50). The pre-registration and run commands were therefore written. (For comparison, the monthly momentum_calm check gave 0.358.)
- **Text status: "FINAL TEXT, NOT REGISTERED".** Spec hash **`814dce51b04fbfb7d2463822fd81176643e4a4e35bcc2b3861745270104bd152`**, status `research`, exit policy `mcd_trailing_atr3_floor8`, family `family_batch8`, K = 1, gates hash `e9b6407f908ff102dd25d9bc3b21a78a52b24c0ea082bba2cd3bb08f81188054` unchanged.
- **Baseline pool:** as decided by the owner, the random pool is NOT restricted to calm stocks, with the any-day pool rule C unchanged (the pool drops the symbols the strategy held or had in cooldown that session, and the trade's own symbol); the text says plainly that any benefit of holding calm stocks counts as the strategy's edge.
- **Cooldown order, as specified:** sigma252 and the median are computed over all eligible names with a sigma252 BEFORE the cooldown is applied; a name in cooldown still counts in the median and is then dropped. A test pins it.
- **Deviation from the brief, as in momentum_calm:** a strategy may not import another strategy, so riskadj_momentum_daily's functions (including `cooldown_symbols` and the exit-history hook) are verbatim copies, and a test proves that with the filter off the proposals equal riskadj_momentum_daily's, also with a name in cooldown.
- **Reading kept from momentum_calm:** sigma252 is the sd of the 252 daily log returns of the closes t-252..t (the 253 bars the rule already needs).

## Shared files touched
- `tests/fixtures/boundaries.py`: `momentum_calm_daily` appended to `APPROVED_STRATEGY_IDS` (ten ids).
- `tests/unit/test_no_strategy_in_the_tree.py`: the strategy-policy list gains `stockbot/strategies/momentum_calm_daily/exits.py::McdTrailingAtr3Floor8`; "exactly the nine ids" becomes "ten ids". Reason: the allow-list is pinned by that test and a strategy-owned exit policy must be listed.
- `docs/guides/CODEBASE_GUIDE.md`: two rows (`momentum_calm_daily_overlap.py`, `momentum_calm_daily_comparison.py`), required by `test_every_script_is_named_in_the_codebase_guide` (run before pushing: passes). No other docs/shared guide was needed (earlier strategy tasks touched only this one).
- Not touched: any existing strategy, spec, exit policy, gate, `shared.yaml`, ledger row, stored result, `build_results_page.py`.

## What was built
- `stockbot/strategies/momentum_calm_daily/` (strategy with `screen()` and `MomentumCalmDailyStrategy`, `mcd_trailing_atr3_floor8` exit policy, indicators). The class carries `exit_history_sessions = 25` like the daily rule.
- Scripts: `scripts/{research,baseline_matched_random,benchmark_nifty_matched,evaluate_validation_gates}_momentum_calm_daily.py` (minimal copies of the riskadj_momentum_daily ones: id, strategy import, policy class; the baseline keeps pool rule C; results folder `docs/strategies/momentum_calm_daily/results_run1/`, not created), `scripts/momentum_calm_daily_overlap.py`, `scripts/momentum_calm_daily_comparison.py` (any-day batch 4, 5, 6 and momentum_calm batch 7 columns, with fees and worst-fall dates).
- Documents: `docs/strategies/momentum_calm_daily/{BRIEF,STATUS,PREREGISTRATION,RUN_COMMANDS,OVERLAP}.md` and `OVERLAP.json`.

## Overlap check (step 2)
Run once, `STOCKBOT_VIEW=memory`, window 2016-01-01 to 2026-10-16, through `short_step` (run lock, database check before and after): **"database check ... unchanged"**, correction counter 0, exit 0. Output: per-date table, mean/median/min/max overlap, sampled sessions with fewer than 25 calm candidates, min/median/max calm-candidate count, in `OVERLAP.md` and `OVERLAP.json`. A test asserts no return/P&L/equity key appears in its output.

## Ledger plan (NOT run)
```
register_family(path=<family_ledger.csv>, family_id="family_batch8", members=[<momentum_calm_daily SPEC>],
                gate_params=asdict(validation_gates), git_sha=<approved commit>,
                reason="family_batch8 K=1: momentum_calm_daily, any-day momentum among the calmest half of stocks (PREREGISTRATION.md)")
```
`tests/unit/test_momentum_calm_daily_dry.py::test_the_family_batch8_payload_validates_with_k_1_on_a_copy_of_the_real_ledger` registers exactly this into a copy of the real ledger: budget 1, member hash as above, `verify_ledger` passes, registering twice without a reason is refused, gates hash `e9b6407f...8054`. The real ledger was not written.

## Tests
- `test_momentum_calm_daily_strategy.py`: **68 passed** (the calm filter: median over all eligible names including r12 <= 0 names, a tie at the median is calm, even count, a name without 252 sessions has no sigma and is not in the median nor proposed, ranking by score, at most 25, no look-ahead; the cooldown interplay: a stopped-out name is not proposed for 21 sessions and the 22nd is allowed with the filter on, a calm name in cooldown does not change the median; equality with riskadj_momentum_daily with the filter off including a name in cooldown; the exit policy and its equality with riskadj_momentum's, SQL = memory view; spec, hash covers the new params, status research).
- `test_momentum_calm_daily_scripts.py` and `test_momentum_calm_daily_dry.py`: 22 and 9 tests, all passed (research, baseline and gates run end to end on fixture lakes with `STOCKBOT_NON_EQ=held` and with it off; a restricted stock never bought or drawn; no `risk_override`; the overlap script with the 21-session sampling; the comparison script; the ledger plan).
- Boundary, allow-list and import tests, guide tests: pass.
- **G1 (all unit and integration tests): see the result line at the end of this report.**

## What ran and what did not
Ran: unit and fixture tests, the overlap check (counts only). Did NOT run: research, baseline, benchmark, gates, validate_family, the comparison on a real result, any ledger write, registration.

## For the owner
1. Register `family_batch8` (K = 1) on master at the commit carrying the pre-registration; a separate run block follows (`RUN_COMMANDS.md`; expected about 3 to 3.5 hours, an estimate; the run blocks the daily data job, which waits and catches up).

## G1 result
`py -m pytest tests/unit tests/integration`: **1718 passed, 9 skipped, 0 failed** in 52 minutes (the codebase-guide test that failed on master for the missing `relative_drawdown_table.py` row passes now that master carries that row).
