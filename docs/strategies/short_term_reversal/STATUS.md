# short_term_reversal: status

Last updated: 2026-11-14 (stage 2 done; waiting for the owner's review).

## Done (stage 2; taken over from a stopped session)
- origin/master 8b07ece merged (ba007ab, kept); strategy and study tests pass.
- SPEC final: expected_trade_rate 23.0, smallest_edge_of_interest 0.15, prereg_ref set. Spec hash `57b86c47d0c5cbdc1325e19230c103b84bc08c6be6b495aadb99d1aa84ec6168` (recomputed).
- Counts study updated to the per-symbol UNMAPPED sector rule; re-count verified from the cached stage-1 lists (no database read): occupancy model 25.63 entries a month under the new rule against 23.02 before (sector figures recomputed, not carried from the old cache). expected_trade_rate NOT changed.
- PREREGISTRATION.md finalised (still DRAFT, not registered): K = 2, joint Max-T B = 10,000, blocks 2 and 3 (both), gates hash e9b6407f...8054, decision rule, limitations, registration snippet with two specs.
- Scripts: research, baseline, benchmark, evaluate_validation_gates (all `*_short_term_reversal.py`, proper copies; the benchmark and gates were thin wrappers of the near_52w_high versions and were replaced). Each output carries asof_view.
- Tests (fixture lakes only): two new files (14 tests) replace the half-finished `test_run_scripts_short_term_reversal.py`.
- RUN_COMMANDS.md written (not run).

## Next step
None until the owner replies. Nothing is registered; no real backtest has been run; status `research`.

## Blockers
None.

## Limitations
See PREREGISTRATION.md section 12 (913 of 1,385 ever-eligible symbols unmapped, no dividends, no historical ASM/GSM, unadjusted demerger/rights actions, memory view for the registered run).
