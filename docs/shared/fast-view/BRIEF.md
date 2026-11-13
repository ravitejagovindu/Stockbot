# fast-view: in-memory as-of view (task text, condensed)

BRANCH: fast-view   REPORT: Claude_Docs/FAST-VIEW_REPORT.md

Goal: make the as-of data view fast without changing a single decision. A 2016-2026 run takes about 4 h and the matched-random baseline about 2 h more, because eligible_symbols issues several SQL queries per symbol per session and scoring reads adjusted_bars per symbol per session.

Design (fixed): `stockbot/data/asof_memory.py` holds `MemoryAsOfView`, a subclass of `AsOfView` that replaces ONLY the data-fetch primitives (SQL reads) with slices of tables loaded once from the lake. All adjustment, point-in-time and eligibility logic stays in the existing code. Returned objects identical to the SQL view's. Lake opened only through `open_lake` (read-only); no writes, no cache file in the lake.

Switch: env `STOCKBOT_VIEW=memory`, read in one place (`AsOfView.__new__`). Default stays the SQL view until the proof passes.

Constraints
- finsight.db read-only; sha256 dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752 checked before and after. No DB: STOP.
- No strategy folders, no pre-registrations, no strategy backtest "to see how it does", no looking at returns, no change to any strategy, gate or shared config value.
- No push until the owner says so. Commits: plain messages, no trailers or attribution lines (also none in PR text).
- Peak RSS reported for the full window; over 6 GB: say so and propose a smaller layout, do not silently degrade.
- docs/guides edited only at the end, minimum, if a guide test demands a row.

Proof (all must pass): (1) existing parity tests and the 120 golden as-of samples on both views, exact; (2) diff harness over at least 400 sessions (symbols_trading, symbol_info, adtv, per-symbol adjusted_bars hash, eligible_symbols), zero differences; (3) 12-month near_52w_high research run once per view, trades.json / daily.json / equity_curve.json byte-identical; (4) corporate-action edge cases (split, bonus, rights, demerger, a gap) in a fixture-lake test for both views.

Target: full 2016-2026 run of one strategy (engine only) in 45 min or less; matched-random baseline in 45 min or less. If missed, report where the time goes (profile) and STOP.

Finish: full G1, full G2 (STOCKBOT_DATA_TESTS=1 STOCKBOT_FINAL_CHECK=1 pytest tests), G3, DB hash unchanged; report; STOP.
