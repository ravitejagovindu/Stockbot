# riskadj_momentum_daily: brief

Strategy id `riskadj_momentum_daily`. Branch `riskadj_momentum_daily` (from origin/master e2a6a82). Family `family_batch4`, K = 1. **Build + counts + scripts + final pre-registration text.** NO backtest on the real lake; no return, P&L or forward price of this strategy has been computed or looked at. Report: `Claude_Docs/RISKADJ_MOMENTUM_DAILY_BUILD_REPORT.md`. Positions and random draws still open on the last day of the window are closed at the last close and counted (PREREGISTRATION section 7a). Shared defaults as on master: symbol links on, stale exit after 20 sessions (`SYMBOL_NO_BARS`).

**This is a variant of riskadj_momentum chosen AFTER its registered result was seen** (run 1 was about 60% invested with a median hold of 20 sessions). riskadj_momentum's folder, scripts, results and pre-registration are untouched; nothing is imported from its folder.

## Goal
riskadj_momentum with ONE rule change: EVERY session is a signal session (signal on the close, entry the engine's next open), and a fixed re-entry cooldown that stops the rule from buying back, every day, a name it was just stopped out of. The strategy only proposes; every shared mechanism (eligibility, sizing, caps, fills, costs, corporate actions, validation gates) is shared code.

## Rule (numbers FIXED by the owner; no tuning)
- Signal sessions: EVERY session of the calendar (`params["signal"] == "every_session"`).
- Shared eligibility, no overrides. History: at least 240 adjusted closes among the last 252 calendar sessions, a bar on the signal session, and closes at t-21 and t-252 counted as OFFSETS ON THE SYMBOL'S OWN BARS (253 own bars needed), as riskadj_momentum.
- ret = close[t-21] / close[t-252] - 1 (adjusted), ret > 0. vol = sample std (ddof 1) of the daily log returns of the symbol's consecutive adjusted closes from t-252 to t-21, vol > 0. score = ret / vol.
- Rank: higher score, then higher 20-session ADTV, then symbol; ordinal rank 25..1; top_n 25.
- ATR14 = Wilder ATR on the adjusted high, low, close of the symbol's last 252 bars (a copy of riskadj_momentum's function, test-pinned equal). Initial stop = signal close - max(3 x ATR14, 0.08 x signal close).
- **Re-entry cooldown (new):** a symbol whose position of THIS strategy was closed by STOP_HIT is not proposed until 21 sessions have passed after the exit session (the exit session and the 21 sessions after it are blocked; the 22nd session after the exit is the first allowed signal session). Only STOP_HIT starts one; SYMBOL_NO_BARS, operator-reported reasons and END_OF_WINDOW do not. Linked (renamed) names are the same symbol.
- Exit: strategy-owned `rmd_trailing_atr3_floor8` (`exits.py`, the same rule as riskadj_momentum's `trailing_atr3_floor8`, test-pinned equal session by session on a fixture path with a corporate action).
- params `{"ret_long":252,"ret_skip":21,"min_closes":240,"top_n":25,"atr_period":14,"atr_mult":3.0,"stop_floor":0.08,"tie_adtv_sessions":20,"signal":"every_session","reentry_cooldown_sessions":21}`; status `research`; no overlay declared; `smallest_edge_of_interest` 0.15; `prereg_ref` docs/strategies/riskadj_momentum_daily/PREREGISTRATION.md.

## How the cooldown is supplied (shared engine change, approved 2026-11-16, own commit 433b1e1)
`propose()` never saw positions or exits. `stockbot/engine/exit_history.py` + `decide.py` + `reports.apply_effect` now record, for a strategy that sets the CLASS attribute `exit_history_sessions` (not a spec field: no spec, config or gates hash changed), each of ITS OWN closed positions as `[canonical symbol, exit session, exit reason]` under the engine-owned state key `_exits`, before proposals are requested, pruned to the last N sessions of the view's calendar; operator-reported exits in live are appended too. A strategy that does not opt in is byte-identical (proof in the report).

## Readings of ambiguous points (stated so the owner can overrule)
1. As riskadj_momentum: calendar-window reading of "240 of the last 252", own-bar offsets for t-21 and t-252, log returns across a gap between consecutive available closes, ATR over 252 bars, a stop at or below zero makes a name unusable.
2. A name in cooldown is skipped BEFORE the ranking, so the top 25 is refilled from the allowed names (reading B would rank first and drop, leaving fewer than 25).
3. "21 sessions have passed since the exit session": the exit session is day 0, so days 0 to 21 are blocked and day 22 is allowed.
4. The exit history keeps 25 sessions (the opt-in attribute); the cooldown needs 22.
5. Baseline pool (owner decision C): the random pool drops the symbols the strategy held or had in its cooldown on the signal session, from the stored run's trades; the trade's own symbol is dropped as in the shared helper; draws never block each other. NOTE: the shared helper itself drops only the trade's own symbol, not "held" symbols, so the held exclusion is new relative to the other registered baselines.

## Constraints
- Shared files: the approved engine change (commit 433b1e1: `stockbot/engine/decide.py`, `stockbot/engine/reports.py`, new `stockbot/engine/exit_history.py`, `stockbot/strategies/base.py` docstring, guide rows) and the approved allow-list edits (commit 125d44d).
- `finsight.db` read-only, sha256 `dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752`.
- Plain commits, no trailers. Keep this file and `STATUS.md` current.
