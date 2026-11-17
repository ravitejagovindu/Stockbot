# non-eq-series: brief

Owner rule (fixed): buy only on EQ series. NEVER buy a stock in BE, BZ or any other restricted series. A held position in such a stock may be held or sold. Eligibility, ADTV, liquidity filters and ranking use EQ rows only.

Why: the lake stores EQ rows only. A held stock that moves from EQ to BE/BZ simply stops having bars; the engine then closes it with the stale rule (SYMBOL_NO_BARS, 20 sessions) at its last EQ close, a price the position could not necessarily be sold at. Stage 1 archives the original NSE files, describes what is in them, and proposes a design. Nothing is built.

Stage 1 (this branch): archive, inventory, design. No write to finsight.db. Stage 2 (only after the owner approves the design): build. Stage 3 (separate, registered): any re-evaluation.

Files: scripts/archive_raw_bhavcopy.py (downloads, never edits), scripts/non_eq_series_inventory.py (read-only inventory), docs/shared/non-eq-series/DESIGN.md, Claude_Docs/NON_EQ_SERIES_STAGE1_REPORT.md, Claude_Docs/non_eq_series/ (inventory tables).
