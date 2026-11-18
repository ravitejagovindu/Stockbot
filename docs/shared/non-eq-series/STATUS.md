# non-eq-series: status

- Stage 1 DONE (archive, inventory, DESIGN.md; merged to master 717f5cf). Stage 2 (build) IN PROGRESS on branch non-eq-series; it stops for the owner's review when finished.
- Stage 2 code is built and tested: table `market_data_non_eq` (DATED_APPEND_ONLY; key symbol, trade_date, series), backfill script, held-bar reads, never-buy gates (NOT_EQ_SERIES, NOT_EQ_SERIES_AT_FILL), BE/BZ sell model. Full test suite green (1474 passed).
- Switch `STOCKBOT_NON_EQ=held`: default OFF. With it off nothing in the engine reads the new table and every stored result reproduces byte-identically.
- Real `finsight.db`: NOT migrated yet. The backfill has run on a scratch copy only (589,172 rows BE/BZ/BL, sealed through 2026-10-16). The real file changes only after the scratch proofs and both backup integrity checks are green.
- Owner rule: buy only on EQ; held positions may be held or sold. The sell model is a fixed assumption, not evidence.
- No strategy folder, pre-registration, ledger row or stored result touched; no backtest run on the real lake.
- Reports: Claude_Docs/NON_EQ_SERIES_STAGE1_REPORT.md; stage 2 report to follow. Design: docs/shared/non-eq-series/DESIGN.md.
- UPDATE 2026-11-18: the real `finsight.db` holds the table (migrated) and the daily job (branch daily-data-update) now loads and seals BE/BZ/BL rows for each new session (2026-10-19 to 2026-11-18 loaded).
