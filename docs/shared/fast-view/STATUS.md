# fast-view status

Done
- stockbot/data/asof_memory.py (MemoryAsOfView) and the STOCKBOT_VIEW=memory switch in AsOfView.__new__; asof.py got two small fetch primitives (_symbols_on_as_of, _first_and_count) so the SQL view's logic is shared, not copied.
- tests/unit/test_asof_memory.py (fixture lake, 64 tests, exact comparison, both views).
- Proof 2 (444 real sessions, ~788,000 symbol-sessions): 0 differences. Proof 1 (golden 120 + parity/engine/baseline tests under memory): 143 passed. Proof 3 (12-month near_52w_high run): trades/daily/equity_curve/blocked byte-identical, manifest identical.
- Peak RSS ~1 GB. Full engine-only run 3312 s (target 45 min: MISSED). Matched-random baseline 1340 s (target met).
- G1: 943 passed, 8 skipped, 1 guide test (module row) - fixed with one row in CODEBASE_GUIDE.md.

Next
- Full G2 (STOCKBOT_DATA_TESTS=1 STOCKBOT_FINAL_CHECK=1), G3, DB hash, report Claude_Docs/FAST-VIEW_REPORT.md, then STOP.

Blockers
- Engine target missed: remaining time is pandas overhead in adtv and adjusted_bars (logic that must stay unchanged). Owner decision needed.
