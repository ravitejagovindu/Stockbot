# riskadj_momentum_daily: status

Last updated: 2026-11-16. **STOPPED, waiting for the owner.**

## Finding (step 3)
`propose(view, eligible, as_of, strategy_state, overlays)` (`stockbot/strategies/base.py:30`, called at `stockbot/engine/decide.py:267`) receives only the as-of view, the eligible list, its own previous `strategy_state` and overlay signals. It never receives positions, closed trades or exit dates. Closed trades are created in `decide` step 3 (`decide.py` lines about 190 to 230, `ClosedTrade`, reason STOP_HIT / SYMBOL_NO_BARS) and go into `Decisions.closed` only; `strategy_state_after` is whatever `propose` returned last time. An exit policy is not called on the bar where the stop is hit (`engine/stepping.py:60` returns before `policy.step`), so a strategy-owned policy cannot record it either. Operator-reported exits in live (`engine/reports.py:109` `exit_effect`, `apply_effect`) also bypass `decide`.
Inferring stop-outs from the lake would mean replaying fills, sizing and caps inside the strategy: not the actual STOP_HIT history.

## Smallest change (not made)
In `decide`, before step 4, for a strategy that opts in with a class attribute (`exit_history_sessions = 25`, NOT a spec field, so no spec hash changes): append this session's closed trades `(canon(symbol), as_of, exit_reason)` of that strategy to `strategy_state[sid]["_exits"]`, prune older than that many sessions, and hand the state to `propose` as today. Strategies without the attribute are untouched (journals and goldens byte-identical). Live adds the same append in `apply_effect` for reported exits. Same code path for backtest, paper and live; the state is journaled.

## Baseline
The matched-random cooldown is possible inside the strategy-side draw loop without a shared change (a symbol whose earlier draw ended STOP_HIT within 21 sessions before the new signal session is dropped from the pool before sampling); the semantics need the owner's confirmation.
