# trend_breakout_100d: status

Last updated: 2026-11-12 (Stage 1 complete; G1 910 passed/8 skipped/1 failed, full G2 1039 passed/1 failed; failure is a near_52w_high test, see report).

## Done
- Branch `trend_breakout_100d` from origin/master 055c703, worked in its own worktree.
- abd7494: strategy package + SPEC (`stockbot/strategies/trend_breakout_100d/`), counts-only script `scripts/signal_count_trend_breakout_100d.py`, 24 strategy tests, 7 script tests, BRIEF.md.
- Counts study run on the real lake (2016-01-01 to 2026-10-16, 2,674 sessions, four date segments in parallel); `Claude_Docs/TREND_BREAKOUT_100D_SIGNAL_COUNTS.md/.json`, cached parts in `Claude_Docs/trend_breakout_100d_parts/`.
- PREREGISTRATION.md drafted (NOT registered). Report: `Claude_Docs/TREND_BREAKOUT_100D_STAGE1_REPORT.md`.

## Result of the counts
Stop condition (under 40 trades) NOT met: mechanical entries under assumed holds of 20 to 250 sessions are 1,503 down to 132. Signals on 96% of sessions. Overlap with near_52w_high candidates 83.9%. 71.8% of sessions have Nifty above its 200-day mean (83.7% of signals).

## Open items / decisions for the owner
- expected_trade_rate and smallest_edge_of_interest (left None); power is weak if holds are long (PREREGISTRATION section 9).
- The reversal block was not in my context; the counts follow the near_52w_high Stage 1 format.
- Whether T2's 20-session forward horizon is acceptable for a trailing-stop exit.
- Regime has no label for the first 163 sessions (the Nifty calendar starts 2015-11-09).

## Next step
None until the owner reviews. No backtest, no returns, no research wiring script yet; status stays `research`.

## Limitations
See PREREGISTRATION section 12.
