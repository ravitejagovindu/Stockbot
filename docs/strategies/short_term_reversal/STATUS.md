# short_term_reversal: status

Last updated: 2026-11-12 (Stage 1 complete except test runs and report; STOP after that).

## Done
- Branch `short_term_reversal` from origin/master 055c703. finsight.db sha256 checked at the start: dcade465...b752 (matches). Size and mtime unchanged after all four study parts.
- `stockbot/strategies/short_term_reversal/` (`__init__.py`, `strategy.py`): SPEC, `ShortTermReversalStrategy.propose`, explicit `register(registry)`; `scan` and `order_candidates` are public so the counts study uses the very same rule. `expected_trade_rate` 23.0 (provisional, owner confirms).
- Counts study: `scripts/strategies/short_term_reversal/signal_count.py` (module) and `scripts/signal_count_short_term_reversal.py` (wrapper). Real-data run done: `results_stage1/counts.md`, `counts.json`, four part caches, logs.
- Tests: `tests/unit/test_short_term_reversal_strategy.py` (36) and `tests/unit/test_short_term_reversal_signal_count.py` (16), fixture lakes only.
- Draft `PREREGISTRATION.md` (family-level parts marked "filled at family registration").

## Counts headline (2016-2026, measured 2026-11-12)
59,055 signals (median 10 a session; 658 sessions with more than 25); 1.8% of signals on the 10 worst market days (0.37% if even); 36% of signals have no sector; 10 of 33,108 proposed names in a tie group, none straddling the cut; stop 8.00% fits (minimum 6.67%) but gives 12.5% positions: one per sector, 8 slots by cash. Occupancy model: 37.5 (plain), 27.7 (sector cap), **23.0 (shared) entries a month**. The rule is workable; nothing to stop on.

## Next
Owner review of the Stage 1 report. Then (not before): the strategy-owned research, B1 and B2 scripts, and the family registration.

## Blockers
None.

## Decisions needed (owner)
- "min_bars 10" is implemented as: at least 10 own bars, a bar on the as-of date, and a bar on the exact session 5 calendar sessions back. A name missing the anchor bar is not a signal.
- ret5 is computed on split/bonus-adjusted closes in the as-of basis and rounded to 12 decimals, so an exact -7.00% or -30.00% is inside the band.
- Unadjusted corporate actions (demerger, merger, rights, OTHER): only the -0.30 floor guards them, as in the brief; no extra guard.
- `expected_trade_rate` 23.0 is the `shared` occupancy model; confirm or set another.
- The study module is under `scripts/strategies/short_term_reversal/` (not `stockbot/data_checks/`) so that no edit of `docs/guides` is needed.
- The 12.5% position and one-per-sector cap mean the 12-position cap never binds; the 36% UNKNOWN-sector signals share one slot. Not changed (shared rules); flagged for the family review.

## Limitations
- Entry gaps below the stop and the 3% gap-up cap need a price after the signal and cannot be counted in a counts-only study.
