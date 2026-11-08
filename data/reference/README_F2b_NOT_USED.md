# F2b files kept but NOT USED

`pit_shares_anchors.csv`, `pit_shares_spotcheck_filings.csv` (and `scripts/f2b_*`, `data/ingestion/pit_shares.py`, `docs/data_audit/pit_shares_*`, `pit_spotcheck_*`)
belong to the point-in-time shares work that was closed on 2026-11-08 because its derivation failed the pre-registered spot-check bar
(median |error| 13.40% vs <= 5%; p90 264.97% vs <= 15%).  `shares_outstanding_pit` was never created in `finsight.db`; the screener reads the old
single-snapshot `shares_outstanding`.  See `docs/data_audit/DATA_KNOWN_ISSUES.md` KI-001.
