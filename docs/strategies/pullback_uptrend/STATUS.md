# pullback_uptrend: status

Last updated: 2026-11-12 (stage 1 in progress: strategy and tests done; real-data counts running).

## Done
- Branch `pullback_uptrend` from origin/master 055c703 (worktree `F:\Projects\Ravi\StockBot_wt_pullback`, because the shared checkout was switched to another branch by a parallel session; `STOCKBOT_DB` points at the one `finsight.db`).
- 00c09f8: strategy package `stockbot/strategies/pullback_uptrend/` (`SPEC`, `PullbackUptrendStrategy`, `rsi_wilder`, `order_signals`), study script `scripts/signal_count_pullback_uptrend.py`, `tests/unit/test_pullback_uptrend_strategy.py` (28 tests) and `tests/unit/test_signal_count_pullback_uptrend.py` (4 tests), `BRIEF.md`.
- `finsight.db` sha256 re-checked 2026-11-12 before any work: `dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752` (matches).

## Open items
- Real-data counts run in three date segments (2016-01-01..2018-12-31, 2019..2022, 2023-01-01..2026-10-16). The machine is shared with other sessions, so it is slow.
- Then: assemble the report, draft `PREREGISTRATION.md`, full G1, full G2, G3, push, write `Claude_Docs/PULLBACK_UPTREND_STAGE1_REPORT.md`.

## Decisions made (dated)
- 2026-11-12: RSI uses the existing `stockbot.data.indicators.rma` (Wilder, seeded with the simple mean of the first `period` values), applied to the symbol's last 250 adjusted closes. avg_loss = 0 gives RSI 100 (50 if avg_gain is also 0). No library RSI exists; `rsi_wilder` is tested against hand-computed values and an independent recursion.
- 2026-11-12: SMA200 = mean of the symbol's adjusted closes inside the last 200 Nifty-calendar sessions, at least 198 present. If the Nifty calendar has fewer than 200 sessions there is NO signal (the calendar starts 2015-11-09, so signals begin about 2016-08). The same 198-of-200 rule is used for the Nifty's own 200-day average in the regime split.
- 2026-11-12: `min_bars` 250 = the symbol's own last 250 adjusted bars must exist, with a bar on the signal date.
- 2026-11-12: RSI ties are exact float ties (no rounding); then ADTV, then symbol.
- 2026-11-12: `expected_trade_rate` and `smallest_edge_of_interest` left empty in the spec for the owner to set (not invented).
- 2026-11-12: strategy-owned study script lives in `scripts/` (name ends `_pullback_uptrend`, so the guide tests treat it as strategy-owned); no shared file or guide edited.

## Next step
Finish the counts run, assemble, write the pre-registration draft and the report.

## Limitations
- Sector map: unmapped symbols share one UNKNOWN sector which the shared 15% cap limits to one position at a time at this position size (12.5% of equity each).
- Actions the engine does not adjust (demerger, merger, rights, OTHER) inside the window can create or hide a pullback; counted in the study, no guard (as for near_52w_high).
- No historical ASM/GSM exclusion (KI-003); EQ-only lake.
- Occupancy numbers are a counts model (no stops, risk cap, costs, gap-up cap, fill blocks).
