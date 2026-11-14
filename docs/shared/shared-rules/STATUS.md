# STATUS: shared-rules

## Done
- Branch created; DB present and hash verified (dcade465...b752) before work.
- BRIEF written.
- C1 sector rule: `sector_for` returns `UNMAPPED:<SYMBOL>` for every unmapped symbol; `SectorLookup` moved to `stockbot/data/sector_map.py` (re-exported by `stockbot/live/runner.py`); data check and research wrapper updated; tests in `tests/unit/test_sector_map.py`. C1(b) counts done: 1,385 ever eligible, 472 mapped, 913 unmapped.
- B1: `stockbot/validation/benchmark_alpha.py` (cash-credited equity, alpha raw / cash-credited / illustrative after-tax, implied annual return); the benchmark and evaluate scripts are wrappers over it.
- B2/B3: `min_alpha_after_tax_pct` -> `min_alpha_pct` = 0.0 (pre-tax, cash-credited); new `reporting.after_tax_rates_pct: [0.0, 20.0]` outside the gate hash; evaluate prints raw and credited alpha, illustrative after-tax lines and the implied annual return. All readers of the old key updated (config, evaluate script, validate_family test, docs, guides).
- Guides updated (md, json) and HTML rebuilt; family FAMILY.md and near_52w_high STATUS note updated.

## Next
Nothing. G1 914 passed / 8 skipped; full G2 1043 passed; G3 2 passed; DB hash unchanged. Report: `Claude_Docs/SHARED_RULES_REPORT.md`. Waiting for the owner (not pushed).

## Blockers
None. Decisions needed are listed in the report.
