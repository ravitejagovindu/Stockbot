# pullback_uptrend: brief

Strategy id `pullback_uptrend`. Branch `pullback_uptrend` (from origin/master 055c703). Member of family_batch1 (K = 4, see `docs/strategies/family_batch1/FAMILY.md`). Stage 1 only: strategy, spec, tests, counts-only study, draft pre-registration. Report: `Claude_Docs/PULLBACK_UPTREND_STAGE1_REPORT.md`.

## Goal
A long-only, end-of-day "buy a short, sharp pullback inside a long uptrend" rule on NSE equities. Signals are taken on the session close, entry is the engine's next open, the hold is five sessions. The strategy only proposes; every shared mechanism (eligibility, sizing, caps, fills, costs, corporate actions, exits, validation gates) is the shared code's.

## Rule (numbers FIXED by the owner; no tuning)
- Long only. Signals on the session close, entry next open.
- Shared eligibility, no overrides. `min_bars` 250 (the symbol's own adjusted bars, including a bar on the signal date).
- Signal: close > SMA200 (198 of the last 200 sessions must have a close) AND RSI(2) < 10. RSI is Wilder-smoothed with period 2 (the existing `stockbot.data.indicators.rma` is the Wilder smoothing and matches; there is no RSI function in the library, so `rsi_wilder` in the strategy folder wraps it and is tested against hand-computed values).
- Rank: lowest RSI(2) first, then higher 20-session ADTV, then symbol. `top_n` 25 (explicit ordinal rank, 25 down to 1).
- Stop = 0.92 x the signal close. Exit policy `fixed_hold_5` (shared library). Status `research`.

## Constraints
- Do not edit shared files (`stockbot/engine`, `stockbot/validation`, `config/shared.yaml`, ledgers, `docs/guides`, `tests/fixtures`). If one must change, STOP and tell the owner.
- `finsight.db` is read-only; sha256 must stay `dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752`. Never invent data.
- Counts only at this stage: no return, P&L, win rate or forward price change is computed or looked at.
- Plain commit messages, no trailers or attribution lines. The branch name is exactly `pullback_uptrend`.
- Keep this file and `STATUS.md` current at every commit.

## Stage-1 deliverables
1. `stockbot/strategies/pullback_uptrend/` (strategy, `SPEC`), `tests/unit/test_pullback_uptrend_strategy.py`, `tests/unit/test_signal_count_pullback_uptrend.py`.
2. Counts-only study `scripts/signal_count_pullback_uptrend.py` and its results (`docs/strategies/pullback_uptrend/counts/`): eligible, signal and proposed counts per session and year, the occupancy model, capital use and the sector cap, concentration, data-quality counts, runtime, PLUS signals split by Nifty above or below its 200-day average, clustering in sell-off days, and the expected trade rate.
3. Draft `PREREGISTRATION.md` (not registered).
4. Report file named above.
