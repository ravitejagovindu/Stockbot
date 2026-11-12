# trend_breakout_100d: brief

Strategy id `trend_breakout_100d`. Branch `trend_breakout_100d`. Member of `family_batch1` (K = 4; see `docs/strategies/family_batch1/FAMILY.md`). Stage 1 only.

## Task as given (owner, 2026-11-12)
Stage 1 only. Rule (long-only, signals on session close, entry next open):
- Shared eligibility. min_bars 200.
- Signal if close > max(close of the PRIOR 100 sessions, excluding today) AND close > SMA200 (require 198 of 200 closes present).
- Rank: higher 20-session ADTV first, then symbol (liquidity-neutral on purpose). top_n 25.
- Stop = 0.85 x signal close. Exit policy trailing_pct_15. status research.

Counts only: as in the reversal block, PLUS the share of these signals that would also have been near_52w_high eligible on the same day (it failed its test, so I need the overlap), and signals per market regime, split by whether Nifty is above or below its own 200-day average. Expect fewer signals; report the trade-rate estimate honestly. If it is under 40 trades over the sample, STOP and say so.
Draft PREREGISTRATION.md as in Block 1.

## Session rules (owner)
- Branch from latest master, name exactly `trend_breakout_100d`. Keep this BRIEF and STATUS.md current at every commit.
- Commits: plain messages, no trailers or attribution lines of any kind, in commits or PR text.
- `finsight.db` is read-only; sha256 must stay `dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752`. If the DB is not in the session, stop and say so. Never invent data.
- Do not edit shared files (`stockbot/engine`, `stockbot/validation`, `config/shared.yaml`, ledgers, `docs/guides`, `tests/fixtures`). If one needs a change, stop and tell the owner.
- The numbers in the block are FIXED. No tuning. If the counts show a rule is unworkable, stop and report; the owner decides.
- Finish by pushing the branch and writing `Claude_Docs/TREND_BREAKOUT_100D_STAGE1_REPORT.md`: what ran, what did not run, full test results (G1, then full G2).

## The rule, as implemented (`stockbot/strategies/trend_breakout_100d/strategy.py`)
| item | value |
|---|---|
| universe | shared `universe.eligibility`, no overrides |
| data rule | 200 own bars (`min_bars`), a bar on the signal date, at least 198 of the last 200 Nifty sessions present (`min_present`) |
| breakout | adjusted close today > max adjusted close of the symbol's previous 100 bars (today excluded; strict) |
| trend | adjusted close today > mean of the last 200 adjusted closes (today included) |
| rank | raw 20-session ADTV descending, then symbol ascending; explicit ordinal rank 25 down to 1 |
| top_n | 25 |
| stop | 0.85 x signal-day adjusted close (as-of basis), reference price = that close, no target |
| exit | library policy `trailing_pct_15` (stop trails 15% under the highest close since entry), or the stop |
| status | research; registration explicit (`register(registry)`), default registry stays empty |

## Constraints that bind this work
Strategies only propose; sizing, caps, arbitration, fills, costs, corporate actions and exit stepping are shared. No return, P&L, win rate or forward price change is computed or looked at in Stage 1.
