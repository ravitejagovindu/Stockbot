# lowvol_uptrend: brief

Strategy id `lowvol_uptrend`. Branch `lowvol_uptrend` (from origin/master 1d87146). Family `family_batch3`, K = 1. **Build + counts + scripts + final pre-registration text.** NO backtest on the real lake; no return, P&L or forward price of this strategy has been computed or looked at. Report: `Claude_Docs/LOWVOL_UPTREND_BUILD_REPORT.md`. Positions and random draws still open on the last day of the window are closed at the last close and counted (PREREGISTRATION section 7a). Shared defaults as on master: symbol links on, stale exit after 20 sessions (`SYMBOL_NO_BARS`).

## Goal
A long-only, monthly-rebalanced "low volatility inside an uptrend" rule on NSE equities: among stocks whose close is above their 200-session average, take the 25 with the lowest volatility of daily log returns over the last 252 bars; hold with an ATR-based trailing stop. Signals are taken on the close of the first trading session of each calendar month; entry is the engine's next open. The strategy only proposes; every shared mechanism (eligibility, sizing, caps, fills, costs, corporate actions, validation gates) is shared code.

## Rule (numbers FIXED by the owner; no tuning)
- Signal sessions: the first trading session of each calendar month only (its (year, month) differs from the previous session's).
- Shared eligibility, no overrides. History: a bar on the signal session, at least 240 adjusted closes among the last 252 calendar sessions, and 253 own bars (the 252 returns of the volatility are counted on the symbol's own bars).
- Uptrend: signal close > SMA200 (strict), SMA200 = mean of the adjusted closes inside the last 200 calendar sessions, at least 198 of those 200 closes present.
- vol = sample standard deviation (ddof 1) of the 252 daily log returns of the symbol's own consecutive adjusted closes, ending at the signal session; vol > 0.
- Rank: LOWEST vol first, then higher 20-session ADTV, then symbol; ordinal rank 25..1; top_n 25.
- ATR14 = Wilder ATR (a copy of riskadj_momentum's function, test-pinned equal) on the adjusted high, low, close of the symbol's last 252 bars. Initial stop = signal close - max(3 x ATR14, 0.08 x signal close).
- Exit: strategy-owned `lv_trailing_atr3_floor8` (`exits.py`, same rule as riskadj_momentum's `trailing_atr3_floor8`, test-pinned equal session by session): reference = highest close since entry; stop = max(previous stop, reference - max(3 x ATR14 of the session, 0.08 x reference)); applies from the next bar; no time exit; rescaled on corporate actions.
- params `{"vol_window":252,"min_closes":240,"sma_window":200,"sma_min_closes":198,"top_n":25,"atr_period":14,"atr_mult":3.0,"stop_floor":0.08,"tie_adtv_sessions":20}`; status `research`; no overlay declared; `smallest_edge_of_interest` 0.15; `prereg_ref` docs/strategies/lowvol_uptrend/PREREGISTRATION.md.

## Readings of ambiguous points (stated so the owner can overrule)
1. "The last 252 own bars" for the volatility is read as 253 own closes giving 252 daily log returns (consistent with "needs 253 own bars"). Reading B would be 252 closes and 251 returns.
2. "At least 198 of the last 200 closes present" is read on the Nifty calendar (the last 200 sessions ending at the signal session); the SMA is the mean of the closes of the symbol that fall in that window (present ones). With no gaps this is the plain 200-bar mean.
3. "At least 240 of the last 252" is read on the Nifty calendar as for riskadj_momentum; log returns across a gap are between consecutive AVAILABLE closes.
4. A stop at or below zero makes a name unusable (cannot happen in practice at a 3 x ATR distance below 8%+; counted).

## Constraints
- Shared files: only the two approved edits (own commit 3998fd9): the allow-list in `tests/fixtures/boundaries.py` and the pinned allow-list and policy list in `tests/unit/test_no_strategy_in_the_tree.py`.
- `finsight.db` read-only, sha256 `dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752`.
- Plain commits, no trailers. Keep this file and `STATUS.md` current.
