# pullback_uptrend: stage 1 report

Branch `pullback_uptrend` (from origin/master 055c703). 2026-11-12. Counts only: no return, P&L, win rate or forward price change was computed or looked at. Nothing is registered.

## What ran
- Strategy `stockbot/strategies/pullback_uptrend/` (SPEC, `PullbackUptrendStrategy`, `rsi_wilder`, `order_signals`) with the owner's fixed numbers: close > SMA200 (198 of 200 closes), RSI(2) < 10 (Wilder, via the existing `rma`), rank lowest RSI, then higher 20-session ADTV, then symbol, top 25, stop 0.92 x signal close, `fixed_hold_5`, status `research`. No RSI exists in the library, so `rsi_wilder` wraps `rma` and is tested against hand-computed values and an independent recursion.
- Study `scripts/signal_count_pullback_uptrend.py` on the real lake, 2016-01-01 to 2026-10-16 (2,674 sessions), in three date segments, using the strategy's own code. Results: `docs/strategies/pullback_uptrend/counts/` (`counts.md`, `summary.json`, three part files).
- Draft `docs/strategies/pullback_uptrend/PREREGISTRATION.md` (not registered), `BRIEF.md`, `STATUS.md`.
- Commits: 00c09f8 (strategy, script, tests, brief), c369b3d (counts, pre-registration draft, status).

## What did not run
- No backtest, no returns, no baselines, no validation (later stages). No power figure was computed. No registration or ledger row.

## Counts (measured 2026-11-12; full tables in `counts.md`)
- First session with a 200-session Nifty calendar, so the first possible signal: **2016-08-30**. The 163 earlier sessions in the window cannot signal.
- Signals per session (from that date): median 11, p5 1, p95 72, max 287; 51,441 signal name-sessions; the top-25 cut binds on 628 of 2,511 sessions. Median by year: 5 to 9 in 2017-2020, 16 to 30 in 2021-2026.
- Occupancy model (12 slots, 5-session hold): 4,659 entries (39.0 a month) without the sector cap, 3,786 (**31.7 a month**) with the shared 15% cap (position 12.5% of equity, so one per sector). Ignores stops (would raise), risk cap, costs, gap-up cap and fill blocks (would lower).
- Concentration: 828 distinct symbols, largest 0.6%, top-10 5.3%; unmapped (UNKNOWN sector) names are 23% of uncapped entries, 10% of capped.
- Nifty regime (above or below its 200-session average): 81.5% of signal name-sessions with the Nifty above (3,672 uncapped entries), 18.5% below (987); Nifty above on 71.8% of sessions, below on 22.1%.
- Clustering: busiest 10% of sessions hold 41% of signals. Nifty days down 1% or more (10% of sessions): 21% of signals, median 29 a session vs 11 other days. Days down 2% or more (2.3% of sessions): 4.8% of signals, median 30.
- Data quality: 3,161 signal name-sessions with a split or bonus in the window (adjusted); 2,220 with a demerger, merger, rights or OTHER action (not adjusted by the engine).
- Runtime: shared eligibility median 9.0 s and scoring median 5.5 s per session on a machine shared with other jobs (total 46,600 s across three processes). A full backtest is likely several hours.
- Counts show no sign that a rule is unworkable.

## Tests
- Strategy tests `tests/unit/test_pullback_uptrend_strategy.py` 28 passed; study tests `tests/unit/test_signal_count_pullback_uptrend.py` 4 passed.
- **G1** (`tests/unit tests/integration`): 911 passed, 8 skipped, **1 failed**.
- **G2 full** (`STOCKBOT_DATA_TESTS=1 STOCKBOT_FINAL_CHECK=1`, whole `tests` folder): 1040 passed, **1 failed**, 0 skipped (44 min 47 s).
- **G3** (`test_g3_fixture_baseline.py`): 2 passed.
- The one failure, in both runs: `tests/unit/test_near_52w_high_strategy.py::test_the_strategy_package_imports_only_what_a_strategy_may_import`. Its last lines assert no strategy folder other than `near_52w_high` exists, so any family member's folder fails it. It is not a defect of this strategy. I did NOT edit it (another strategy's test). Fix on master (use `APPROVED_STRATEGY_IDS`) or tell me to edit it here.
- `finsight.db`: sha256 `dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752`, 3,432,767,488 bytes, mtime 2026-11-08 12:38:02.892612 +0530, identical before and after (hashed at the start and again after the counts and G1; size and mtime also checked after G2 and G3).

## Deviations and limitations
- Worked in a separate git worktree because a parallel session switched the shared checkout to another branch; `STOCKBOT_DB` pointed at the one database.
- SMA200 uses the Nifty calendar; fewer than 200 sessions means no signal. Same 198-of-200 rule for the Nifty regime.
- RSI is computed on the last 250 adjusted closes; exact RSI ties only (no rounding).
- Study script reuses `Occupancy` and `fingerprint` from `stockbot.data_checks.near_high_signal_count`.
- Sector map UNKNOWN bucket, unadjusted corporate actions, no historical ASM/GSM, EQ-only lake, counts-model occupancy.
- I did not see the "reversal block" text; the counts follow the near_52w_high STOP 1 items plus the requested regime split, sell-off clustering and trade rate.
- No shared file, guide or fixture was edited.

## Decisions needed from the owner
1. The failing near_52w_high test (above): edit it on this branch or fix on master.
2. Window: common 2016-01-01 start (first 163 sessions empty for this member) or 2016-09-01 for the family.
3. `expected_trade_rate` (31.7 proposed, capped model; 39.0 uncapped) and `smallest_edge_of_interest` (left empty).
4. Whether to compute a power figure before registration.
5. Confirm the decision rule and T1/T2/T3 and B1/B2 settings for this member.
