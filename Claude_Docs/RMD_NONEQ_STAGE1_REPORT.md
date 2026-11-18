# riskadj_momentum_daily BE/BZ re-run: stage 1 report (text and commands only)

Worktree `F:\Projects\Ravi\StockBot_wt_rmd_noneq`, branch `rmd-noneq-run`, from master 24e391a. **Pre-registration text status: FINAL TEXT, NOT REGISTERED.** Nothing was run on the real lake; no result of this trial exists; no strategy rule, parameter, exit policy, gate, shared config, spec, ledger row or old result folder was touched.

## Summary
- New trial, new family `family_batch5` (K = 1), same strategy and **same spec hash `5b06f092...446e19`**. The three differences from family_batch4 run 1 and nothing else: `STOCKBOT_NON_EQ=held`; the BE/BZ sell model (10% of bar volume, double exit slippage, no fill on a single-price low-volume bar; a fixed assumption); the current guarded `finsight.db` with the window unchanged (2016-01-01 to 2026-10-16).
- `PREREGISTRATION_NONEQ.md` contains: the three differences, why the window is kept, the honest note on K (another look at the same ten years; K counts only this family, budget 1, earlier trials stated), the extra reporting, and the pre-declared reading (verdict by the decision rule on this run alone; batch 4 stands as recorded; no second run unless a technical crash).
- G1: **1,508 passed, 9 skipped, 0 failed** (31 min), including 7 new dry-check tests.

## What differs from batch 4 (files)
| File | Change |
|---|---|
| `docs/strategies/riskadj_momentum_daily/PREREGISTRATION_NONEQ.md` | new (final text, not registered) |
| `docs/strategies/riskadj_momentum_daily/RUN_COMMANDS_NONEQ.md` | new: commands, env vars, locks, memory, db checks |
| `docs/strategies/riskadj_momentum_daily/STATUS.md` | dated note appended |
| `scripts/research_riskadj_momentum_daily.py` | **additive, switch-on only**: `manifest.non_eq_events` = count of `SELL_CAPPED_NON_EQ` flags, their symbols, `NOT_EQ_SERIES` blocks, `SYMBOL_NO_BARS` exits. The engine does not persist these flags anywhere else, so the pre-registered count was otherwise unobtainable. With the switch off the manifest is unchanged (tested). |
| `scripts/noneq_comparison_riskadj_momentum_daily.py` | new, read-only: the side-by-side table and the list of trades that held a stock through a BE/BZ spell; recomputes nothing |
| `tests/unit/test_riskadj_momentum_daily_noneq_dry.py` | new, 7 fixture tests |

## Ledger plan
- `register_family` takes `members` = spec objects and stores `{id, version, config_hash}`; a duplicate id is refused only **inside one family**, so `riskadj_momentum_daily` with the same hash in `family_batch5` is accepted. The family ledger has **no run-conditions column** and is hash-chained, so adding one would break verification of the existing rows. `validate_family` also checks that the member label equals the strategy id in the manifest (`not the strategy` error), so a new id such as `riskadj_momentum_daily_noneq` would need a new spec, which is forbidden.
- Minimal way, with **no change to ledger, spec, allow-list or tests**: `register_family(family_id="family_batch5", members=[SPEC], ..., reason="family_batch5 K=1: riskadj_momentum_daily re-run with STOCKBOT_NON_EQ=held and the BE/BZ sell model (PREREGISTRATION_NONEQ.md)")`. The run conditions live in the recorded `reason`, in the registration commit that carries the text, and in the run manifest (`non_eq_view`). The dry test registers exactly this into a temp ledger, checks budget 1, member list, hash chain, the gates hash `e9b6407f...8054`, and that a second registration without a reason is refused.

## Tests (fixtures only; G1)
- Dry check (7 tests, 186 s): switch on gives `non_eq_view` (switch, table, 10% cap, 2.0x slippage) and `non_eq_events` in the manifest; switch off gives neither; a stock that moved to BE is never bought after the move (engine) and never drawn after the move (baseline); gates output works in both modes; family_batch5 payload validates; comparison script lists only trades that touched BE bars. All passed.
- Pinned tests (allow-list of strategy ids, strategy and script tests, non-eq tests): passed within G1.
- G1 `pytest tests/unit tests/integration`: **1,508 passed, 9 skipped** (batch-4 build report: 1,372 passed, 9 skipped; the difference is tests added on master since, plus the 7 new). The worktree has no `finsight.db`; no real database was opened.

## What ran and what did not
Ran: git checks, worktree, code reading, the dry tests, G1. Did not run: the backtest, baseline, benchmark, gates script, `validate_family` or the comparison script on the real lake; no old result was read; nothing registered; no ledger write; no G2/G3. Open for the owner: register `family_batch5` on master at the commit carrying `PREREGISTRATION_NONEQ.md`, then a separate run block follows.
