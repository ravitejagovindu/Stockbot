# momentum_calm_daily: brief

Strategy id `momentum_calm_daily`. Branch `momentum-calm-daily` (from master 1ea1f41). Family `family_batch8`, K = 1. **Stage 1** (build, overlap check, pre-registration text, run commands). NO backtest, baseline, benchmark or validation has been run; no return of this strategy exists. Report: `Claude_Docs/MOMENTUM_CALM_DAILY_STAGE1_REPORT.md`.

## Goal
The registered any-day risk-adjusted 12-1 momentum rule (riskadj_momentum_daily, 21-session re-entry cooldown) traded only among the calmest half of the eligible stocks, with the same calm filter as momentum_calm. The strategy only proposes; sizing, caps, arbitration, fills, costs, corporate actions and the validation gates are shared code.

## Rule (owner decision, every number fixed)
Identical to riskadj_momentum_daily (every session a signal session, universe, eligibility, history guards, r12 = close[t-21]/close[t-252] - 1 > 0, vol of the log returns t-252..t-21, score r12/vol, top_n 25, initial stop = close - max(3 x ATR14, 8%), 21-session cooldown after a STOP_HIT with the 22nd session allowed, the opt-in exit-history hook) plus ONE filter: sigma252 = sd of the 252 daily log returns of the closes t-252..t, for every eligible name that has one; median252 = their median, taken before the r12 > 0 filter and before the cooldown; only names with sigma252 <= median252 (ties calm) may be proposed. Exit: own policy `mcd_trailing_atr3_floor8` (a copy of `rmd_trailing_atr3_floor8`). Standard risk 1.0%, 12 positions, shared caps and costs, no overlays. Exact text: `PREREGISTRATION.md` section 2.

## Constraints
- Shared files touched: only the allow-lists (`tests/fixtures/boundaries.py`, `tests/unit/test_no_strategy_in_the_tree.py`), a deliberate reviewed change as for the earlier strategies. A strategy may not import another strategy, so riskadj_momentum_daily's functions are verbatim copies (a test proves equality with the filter off).
- `finsight.db` read-only; every short step takes the run lock and does the database check before and after. Plain commits, no trailers.
