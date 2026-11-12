# trend_breakout_100d: Stage 1 report

Date 2026-11-12. Branch `trend_breakout_100d` (from origin/master 055c703), worked in a separate git worktree (`F:\Projects\Ravi\StockBot_wt_trend100`) because other sessions switch branches in the main checkout. Report for a reviewer who has not seen the session.

## Headline
- **The stop condition (under 40 trades) is NOT met.** The rule signals on 2,568 of 2,674 sessions (96%); mechanical entries under 12 slots are 1,503 / 781 / 528 / 324 / 216 / 132 for assumed holds of 20 / 40 / 60 / 100 / 150 / 250 sessions. The real exit (15% trailing stop) depends on later prices that Stage 1 does not read, so this is a bracket, not a forecast of the trade count.
- **Overlap with near_52w_high: 83.9%** of signal name-sessions (53,500 of 63,740) were also near_52w_high candidates the same day (84.2% of this strategy's top-25 name-sessions). Overlap is with that rule's candidate set (nearness >= 0.95 plus its gap guard), not its top 25. Range by year 68% to 95%.
- **Regime:** Nifty above its 200-day mean on 71.8% of sessions, carrying 83.7% of signals (median 22 a session); below: 22.1% of sessions, 13.3% of signals (median 5); no label for the first 163 sessions (the Nifty calendar starts 2015-11-09). In 2026, 159 of 196 sessions are "below" and carry 6,297 signals.
- Tables: `Claude_Docs/TREND_BREAKOUT_100D_SIGNAL_COUNTS.md` (and `.json`); per-session cached parts in `Claude_Docs/trend_breakout_100d_parts/`.

## What ran
- Strategy package `stockbot/strategies/trend_breakout_100d/` with the owner's fixed numbers (spec hash at this draft `07963c2a...b22d80`; `expected_trade_rate`, `smallest_edge_of_interest`, `prereg_ref` left None).
- Counts-only study `scripts/signal_count_trend_breakout_100d.py` on the real lake, window 2016-01-01 to 2026-10-16, four date segments in parallel (about 4.7 hours of wall time; the machine was shared with other sessions' studies, so timings are not a speed benchmark). It uses the strategy itself for the signals (top_n lifted), shared eligibility, and `near_high_signal_count.snapshot` for the overlap. It computes no return and reads nothing after the as-of date.
- 31 new tests (24 strategy, 7 script), all passing.
- Docs: BRIEF.md, STATUS.md, PREREGISTRATION.md (DRAFT, not registered), this report.

## What did not run
No backtest, no returns, no research wiring script, no matched-random baseline, no registration, no power calculation with `power_calc.py` (the power figure in PREREGISTRATION section 9 is my scaling of the near_52w_high arithmetic). The reversal block was not in my context, so "counts as in the reversal block" was taken as the near_52w_high Stage 1 count format (eligible, signals, proposed, occupancy bracket, concentration-free); say if it should differ. Not reported: sector concentration and data-quality counts (split / unadjusted-action names) of the near_52w_high study.

## Tests
- **G1** (`tests/unit tests/integration`): **910 passed, 8 skipped, 1 failed** (878 s).
- **Full G2** (`STOCKBOT_DATA_TESTS=1 STOCKBOT_FINAL_CHECK=1`, whole `tests` folder): **1,039 passed, 1 failed** (1,761 s).
- The one failure in both: `tests/unit/test_near_52w_high_strategy.py::test_the_strategy_package_imports_only_what_a_strategy_may_import` (line 252). It asserts that no strategy folder other than `near_52w_high` exists under `stockbot/strategies/`, so it fails as soon as ANY other approved strategy folder (mine) exists. It is not caused by a defect in this strategy; it will fail on every family branch and on master after the first merge. I did not edit it (another strategy's test; the owner asked me to STOP if shared files need a change). **Decision needed:** relax that assertion to the approved-ids list (suggest one change on master, or in `family-prep`).
- An earlier partial run saw `test_each_module_imports_in_a_fresh_interpreter` time out at 120 s while the machine was overloaded; in the final G1 and G2 runs it passed.
- G3 is inside both runs (`test_g3_fixture_baseline.py`); not run separately.

## finsight.db
sha256 `dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752` checked before the study and again after G2: unchanged. The study parts compared size and mtime before/after (unchanged; hashing 3.4 GB per segment was skipped with `--no-hash`).

## Deviations and limitations
- Worktree instead of the main checkout (see top). The study's `--lake` pointed at the main checkout's `finsight.db`.
- Occupancy model: assumed fixed holds; stops, risk cap, costs, gap-up cap, cash cap, missing-bar blocks ignored; slots fill together on day one, so entries cluster (per-year counts at long holds are multiples of 12). The "sector cap" variant's block counts are sector-cap skips counted each session, not distinct candidates.
- The prior-100 maximum uses the symbol's own previous 100 bars (equals the calendar's 100 sessions unless it has 1 to 2 missing).
- Unadjusted corporate actions, no historical ASM/GSM exclusion, UNKNOWN sector bucket, EQ-only lake gaps: as for near_52w_high.
- 2016 has a small universe (median 144 eligible names against 585 in 2026).

## Decisions needed from the owner
1. The near_52w_high strategy test above (relax to the approved list).
2. `expected_trade_rate` and `smallest_edge_of_interest`; power looks weak at 0.15 R if holds are long.
3. Whether to proceed given the 84% overlap with near_52w_high (which was NOT DEMONSTRATED).
4. Whether T2's 20-session forward horizon is acceptable for a trailing-stop exit.
5. Whether the counts format matches the reversal block.
