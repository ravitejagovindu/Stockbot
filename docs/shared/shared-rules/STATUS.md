# STATUS: shared-rules

## Done
- Branch created; DB present and hash verified (dcade465...b752) before work.
- BRIEF written.
- C1 sector rule: `sector_for` returns `UNMAPPED:<SYMBOL>` for every unmapped symbol; `SectorLookup` moved to `stockbot/data/sector_map.py` (re-exported by `stockbot/live/runner.py`); data check and research wrapper updated; tests in `tests/unit/test_sector_map.py`. C1(b) counts running (read-only).

## Next
1. B1 shared module, then B2/B3 config rename and evaluate output.
2. Docs, guides (regenerate HTML), G1, G2, G3, report.

## Blockers
None.
