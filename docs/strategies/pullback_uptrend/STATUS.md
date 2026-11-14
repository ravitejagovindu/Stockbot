# pullback_uptrend: status

Last updated: 2026-11-14 (stage 2 done; waiting for the owner's review).

## Done (stage 2)
- Merged origin/master (8b07ece) into the branch (cded0bf); strategy tests pass.
- SPEC finalised: expected_trade_rate 31.7, smallest_edge_of_interest 0.15, prereg_ref set. Spec hash `81db6427ebc9e11980c2cbbfb86720c7e1e68eeb27073b05c95cc64ce4207044`.
- Re-count under the new sector rule (counts only, from the cached stage-1 candidate lists, no database read): capped entries 4,338 (36.3 a month) against 3,786 (31.7) before; uncapped unchanged 4,659 (39.0). `counts_new_sector_rule/`. expected_trade_rate NOT changed.
- PREREGISTRATION.md finalised (still DRAFT, not registered): K = 2, joint Max-T B = 10,000, blocks 2 and 3 (both), gates hash e9b6407f...8054 (checked against the shared config), decision rule, limitations, registration snippet with two specs.
- Scripts: research, baseline, benchmark, evaluate_validation_gates, all `*_pullback_uptrend.py`; each output carries asof_view. Layout for validate_family: member dir with run/ and baseline/.
- Tests (fixture lakes only): research wiring and refusal, baseline, benchmark, gates, layout, validate_family dry run on two fixture members.
- RUN_COMMANDS.md written (not run).
- finsight.db sha256 checked before and after: dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752.

## Open items
- See `Claude_Docs/PULLBACK_UPTREND_STAGE2_REPORT.md` (decisions needed).

## Next step
None until the owner replies. Nothing is registered; no real backtest has been run; status `research`.

## Limitations
See PREREGISTRATION.md section 12 (unmapped symbols each their own sector, no dividends, no historical ASM/GSM, unadjusted demerger/rights actions, memory view for the registered run).
