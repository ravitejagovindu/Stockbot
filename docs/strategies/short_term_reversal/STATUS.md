# short_term_reversal: status

Last updated: 2026-11-12 (Stage 1 in progress: strategy and study tool implemented and tested; real-data counts not run yet).

## Done
- Branch `short_term_reversal` from origin/master 055c703. finsight.db sha256 checked: dcade465...b752 (matches).
- `stockbot/strategies/short_term_reversal/` (`__init__.py`, `strategy.py`): SPEC, `ShortTermReversalStrategy.propose`, explicit `register(registry)`; `scan` and `order_candidates` are public so the counts study uses the very same rule.
- Counts study: `scripts/strategies/short_term_reversal/signal_count.py` (module) and `scripts/signal_count_short_term_reversal.py` (wrapper).
- Tests: `tests/unit/test_short_term_reversal_strategy.py` (36) and `tests/unit/test_short_term_reversal_signal_count.py` (16), fixture lakes only.

## Next
1. Run the real-data counts study (read-only, parts in parallel), assemble, record results.
2. Set `SPEC.expected_trade_rate` from the counts (owner confirms), draft `PREREGISTRATION.md`.
3. G1 and full G2, report `Claude_Docs/SHORT_TERM_REVERSAL_STAGE1_REPORT.md`, push, STOP.

## Blockers
None.

## Decisions needed (owner)
- "min_bars 10" is implemented as: at least 10 own bars in `view.adjusted_bars`, a bar on the as-of date, and a bar on the exact session 5 calendar sessions back (Nifty calendar). A name missing the anchor bar is not a signal (no silent skipping to an earlier bar).
- ret5 is computed on split/bonus-adjusted closes in the as-of basis and rounded to 12 decimals, so an exact -7.00% or -30.00% is inside the band (without the rounding, 93/100 - 1 is -0.06999999999999995 and would be lost at the -0.07 edge).
- Unadjusted corporate actions (demerger, merger, rights, OTHER): only the -0.30 floor guards them, as in the brief; no extra guard.

## Limitations
- Entry gaps below the stop (stop at or above the next open) and the 3% gap-up cap need a price after the signal and cannot be counted in a counts-only study.
