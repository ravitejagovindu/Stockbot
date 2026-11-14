# short_term_reversal: Stage 1 report (2026-11-12)

Branch `short_term_reversal` (from origin/master 055c703). Stage 1 only: implement, count signals (no returns), draft the pre-registration. STOPPED here.

## What ran
- Strategy `stockbot/strategies/short_term_reversal/` (SPEC, `propose`, explicit `register`), exactly the fixed numbers: 5-session ret5, band -0.30..-0.07 inclusive, min_bars 10, top 25, stop 0.92 x signal close, `fixed_hold_5`, status research, smallest_edge_of_interest 0.15.
- Counts study on the real `finsight.db` (read-only, 2,710 sessions, 2015-11-09 to 2026-10-16, four parallel date segments, then assembled): `docs/strategies/short_term_reversal/results_stage1/counts.md` and `counts.json`.
- Draft `docs/strategies/short_term_reversal/PREREGISTRATION.md` (family-level parts marked "filled at family registration"); BRIEF.md and STATUS.md kept current.
- Tests: 36 strategy tests (rule, band edges, ranking, ties, edge cases, point-in-time, engine path) and 16 study tests, fixture lakes only.

## What did NOT run
No backtest, no return, no B1/B2/T1 (later stages). The strategy-specific research, B1 and B2 scripts do not exist yet. Entry-gap-below-stop and the 3% gap-up cap are not counted (they need a price after the signal).

## Counts (2016-2026 unless stated, measured 2026-11-12)
- Signals: 59,055 (median 10 a session; 2016: 2,638; 2020: 4,982; 2024: 9,618). Sessions with more than 25 signals: 658 of 2,674 (24%). Max in one day 292. Per-month table in counts.md.
- Clustering: the 10 worst Nifty days carry 1.8% of all signals (0.37% if spread evenly); 8 of the 659 over-25 days are among them.
- Sector spread: 36.0% of signals have no sector (UNKNOWN); largest named sector FINANCIALS 14.9%; proposed names per session span a median of 5 sectors.
- Ties: 10 of 33,108 proposed names in a tie group; 5 sessions; no tie ever straddled the cut; none needed the symbol rule.
- Stop fit: 8.00% against a 6.67% minimum (1% risk / 15% sector cap): fits. But it gives 12.5%-of-equity positions: ONE per sector, at most 8 by cash (the 12-position cap never binds).
- expected_trade_rate (mechanical occupancy model, ignores stops/gaps/costs): 37.5 a month with the position cap only, 27.7 with the sector cap, **23.0 with the shared caps** (2,931 entries; slots full 15% of sessions; mean 5.5 open). SPEC set to 23.0, provisional.
- Data quality: 1,139 no-anchor name-sessions; 574 below the floor, 72 of them with a corporate action in the window; 204 signal-sessions with an unadjusted action (demerger/merger/rights/OTHER) in the window, 108 with a split/bonus.
- The rule is workable; nothing to stop on.

## Tests
- **G1** (`tests/unit tests/integration`): **955 passed, 8 skipped, 1 failed** (15 m 45 s).
- **Full G2** (`STOCKBOT_DATA_TESTS=1 STOCKBOT_FINAL_CHECK=1 pytest tests`): **1084 passed, 1 failed** (30 m 22 s).
- The one failure in both is `tests/unit/test_near_52w_high_strategy.py::test_the_strategy_package_imports_only_what_a_strategy_may_import`: its last lines assert that no other folder exists under `stockbot/strategies/`. It will fail as soon as ANY second approved strategy folder exists; it is not specific to this branch. It needs a one-line change (allow the approved ids), which I did not make: it is another strategy's test and the rules say to stop and tell you.
- G3 files (`test_g3_fixture_baseline.py`) are inside G1/G2 and passed.
- On a clean tree (055c703 + my two commits only), 130 passed, 2 skipped for: my two test files, guides consistency, import boundaries, no-strategy-in-the-tree, wrapper `--help`.

## finsight.db
sha256 before (start) and after (end): `dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752`, size 3,432,767,488, mtime 2026-11-08 12:38:02.892612 +0530, unchanged; also size and mtime unchanged across all four study parts.

## Deviations and problems
1. **Shared checkout.** Another session (low_volatility) works in the same working tree and committed onto my branch: 7f9efb0 and 72ab050 are interleaved with mine locally, and the G1/G2 runs above were on that mixed tree. I did not rewrite the local branch or touch their files. For the push I built a clean chain on a temporary worktree (055c703 + my two commits, SHAs 1dcc678 and 0776bc3) and pushed that as `short_term_reversal`, so the remote branch holds only this task. Your local `short_term_reversal` still contains the low_volatility commits and now diverges from the remote; reconcile it (for example `git branch low_volatility 72ab050` to save theirs, then reset this branch to origin) once the other session is idle.
2. Study module location: `scripts/strategies/short_term_reversal/signal_count.py` (wrapper `scripts/signal_count_short_term_reversal.py`), not `stockbot/data_checks/`, so that no edit of `docs/guides` (shared) is needed; both are strategy-owned paths.
3. The first G1 run was killed by a 10-minute limit I set myself; it was rerun in full (result above).

## Decisions needed from the owner
1. "min_bars 10" = at least 10 own bars, a bar on the as-of date, and a bar on the exact session 5 calendar sessions back; a name with no anchor bar is not a signal. Confirm.
2. ret5 on adjusted closes, rounded to 12 decimals (so exactly -7% and -30% are inside the band). Confirm.
3. expected_trade_rate 23.0 (shared model). Confirm or set another.
4. The 12.5% position size means one position per sector and one at a time in the UNKNOWN bucket (36% of signals). Shared rules, unchanged; flagged for the family review.
5. Fix the near_52w_high test (above) and say who owns it.
6. How to reconcile the shared checkout (above).
