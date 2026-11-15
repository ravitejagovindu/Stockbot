# riskadj_momentum: brief

Strategy id `riskadj_momentum`. Branch `riskadj_momentum` (from origin/master 1ba2a38). Family `family_batch2`, K = 1. **Stage 2** (scripts, final pre-registration text, run commands; stage 1 was the build and the counts). NO backtest on the real lake; no return of this strategy has been computed or looked at. Reports: `Claude_Docs/RISKADJ_MOMENTUM_STAGE1_REPORT.md`, `Claude_Docs/RISKADJ_MOMENTUM_STAGE2_REPORT.md`. Positions and random draws still open on the last day of the window are closed at the last close and counted (PREREGISTRATION section 7a).

## Goal
A long-only, monthly-rebalanced "risk-adjusted 12-1 momentum" rule on NSE equities: rank by trailing 12-month-minus-1-month return divided by the volatility of daily log returns over the same stretch; hold with an ATR-based trailing stop. Signals are taken on the close of the first trading session of each calendar month; entry is the engine's next open. The strategy only proposes; every shared mechanism (eligibility, sizing, caps, fills, costs, corporate actions, validation gates) is shared code.

## Rule (numbers FIXED by the owner; no tuning)
- Signal sessions: the first trading session of each calendar month only (its (year, month) differs from the previous session's).
- Shared eligibility, no overrides. History: at least 240 adjusted closes among the last 252 calendar sessions, a bar on the signal session, and closes at t-21 and t-252 counted as OFFSETS ON THE SYMBOL'S OWN BARS (253 own bars needed).
- ret = close[t-21] / close[t-252] - 1 (adjusted), ret > 0. vol = sample std (ddof 1) of the daily log returns of the symbol's consecutive adjusted closes from t-252 to t-21, vol > 0. score = ret / vol.
- Rank: higher score, then higher 20-session ADTV, then symbol; ordinal rank 25..1; top_n 25.
- ATR14 = Wilder ATR (existing `stockbot.data.indicators.atr`) on the adjusted high, low, close of the symbol's last 252 bars. Initial stop = signal close - max(3 x ATR14, 0.08 x signal close).
- Exit: strategy-owned `trailing_atr3_floor8` (`exits.py`): reference = highest close since entry (seeded from the entry price); each session stop = max(previous stop, reference - max(3 x ATR14 of that session, 0.08 x reference)); applies from the next bar; no time exit; rescaled on corporate actions.
- params `{"ret_long":252,"ret_skip":21,"min_closes":240,"top_n":25,"atr_period":14,"atr_mult":3.0,"stop_floor":0.08,"tie_adtv_sessions":20}`; status `research`; no overlay declared; `smallest_edge_of_interest` 0.15; `prereg_ref` docs/strategies/riskadj_momentum/PREREGISTRATION.md.

## Readings of ambiguous points (stated so the owner can overrule)
1. "At least 240 closes among the last 252 sessions" is read on the Nifty calendar (the last 252 sessions ending at the signal session); "t-21 and t-252 on the symbol's own bars" is read as own-bar positions 21 and 252 before the symbol's last bar, which needs 253 own bars. With no gaps these are the calendar's sessions; with gaps they reach further back (131 of 25,713 qualifying name-months).
2. Daily log returns across a gap are the log of consecutive AVAILABLE closes.
3. ATR over the last 252 bars (a fixed length, because the Wilder seed decays); the exit policy uses the same function every session. If ATR cannot be computed the exit falls back to the 8% floor and is flagged (cannot happen for a position this strategy opened).
4. A stop at or below zero (ATR above a third of the price) makes a name unusable (2 name-months in the counts).

## Constraints
- Shared files: only the allow-list line in `tests/fixtures/boundaries.py` was edited (own commit). Two shared tests need an edit that was NOT made: see the report.
- `finsight.db` read-only, sha256 `dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752`.
- Plain commits, no trailers. Keep this file and `STATUS.md` current.
