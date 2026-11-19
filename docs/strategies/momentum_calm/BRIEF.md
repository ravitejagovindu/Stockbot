# momentum_calm: brief

Strategy id `momentum_calm`. Branch `momentum-calm` (from master 855a74c). Family `family_batch7`, K = 1. **Stage 1** (build, overlap check, pre-registration text, run commands). NO backtest, baseline, benchmark or validation has been run; no return of this strategy exists. Report: `Claude_Docs/MOMENTUM_CALM_STAGE1_REPORT.md`.

## Goal
The registered monthly risk-adjusted 12-1 momentum rule (riskadj_momentum), traded only among the calmest half of the eligible stocks. The strategy only proposes; sizing, caps, arbitration, fills, costs, corporate actions and the validation gates are shared code.

## Rule (owner decision, every number fixed)
Identical to riskadj_momentum (signal sessions, universe, eligibility, history guards, r12 = close[t-21]/close[t-252] - 1 > 0, vol of the log returns t-252..t-21, score r12/vol, top_n 25, initial stop = close - max(3 x ATR14, 8%), no re-entry rule beyond the engine's) plus ONE filter: sigma252 = sd of the 252 daily log returns ending at the signal date, for every eligible name that has one; median252 = their median (taken before the r12 > 0 filter); only names with sigma252 <= median252 (ties calm) may be proposed. Exit: own policy `mc_trailing_atr3_floor8` (a copy of riskadj_momentum's trailing policy). Standard risk 1.0%, 12 positions, shared caps and costs, no overlays. Exact text: `PREREGISTRATION.md` section 2.

## Constraints
- Shared files touched: only the allow-lists (`tests/fixtures/boundaries.py`, `tests/unit/test_no_strategy_in_the_tree.py`), a deliberate reviewed change as for the earlier strategies. A strategy may not import another strategy, so riskadj_momentum's functions are verbatim copies (a test proves equality with the filter off).
- `finsight.db` read-only; every short step takes the run lock and does the database check before and after. Plain commits, no trailers.
