# STATUS: shared-rules

## Done
- Branch created; DB present and hash verified (dcade465...b752) before work.
- BRIEF written.
- C1 sector rule: `sector_for` returns `UNMAPPED:<SYMBOL>` for every unmapped symbol; `SectorLookup` moved to `stockbot/data/sector_map.py` (re-exported by `stockbot/live/runner.py`); data check and research wrapper updated; tests in `tests/unit/test_sector_map.py`. C1(b) counts running (read-only).
- B1: `stockbot/validation/benchmark_alpha.py` (cash-credited equity, alpha raw / cash-credited / illustrative after-tax, implied annual return); the benchmark and evaluate scripts are wrappers over it.
- B2/B3: `min_alpha_after_tax_pct` -> `min_alpha_pct` = 0.0 (pre-tax, cash-credited); new `reporting.after_tax_rates_pct: [0.0, 20.0]` outside the gate hash; evaluate prints raw and credited alpha, illustrative after-tax lines and the implied annual return. All readers of the old key updated (config, evaluate script, validate_family test, docs, guides).
- Guides updated (md, json) and HTML rebuilt; family FAMILY.md and near_52w_high STATUS note updated.

## Next
1. Full G1, full G2, G3, DB hash; report `Claude_Docs/SHARED_RULES_REPORT.md`; stop.

## Blockers
None.
