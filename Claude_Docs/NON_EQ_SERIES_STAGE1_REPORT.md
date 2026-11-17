# Non-EQ series, stage 1: report (archive, inventory, design)

Branch `non-eq-series` (from master c01386e). `finsight.db` was opened read-only (`open_lake`) and never written. No strategy folder, pre-registration, ledger row or stored result was touched; no registered run was re-run. Everything below DESCRIBES the data; it is not a re-evaluation and recomputes no result, metric or gate.

## Summary
- **Archive: done.** 3,416 original NSE files saved unmodified to `F:\Projects\Ravi\StockBotData\raw_bhavcopy\YYYY\` (300,621,901 bytes, about 287 MiB), one per trading day, 2013-01-01 to 2026-10-16. Trading days = every date in `market_data_lake` (3,416). **Dates missing: none** (all 3,416 fetched, 0 errors, no block by the site; paced at about 1 request per second, run time 57 minutes). Patterns used: legacy `cm...bhav.csv.zip` 2,844 days, UDiFF 571 days, `sec_bhavdata_full` 1 day (2020-07-13, where the other two patterns gave nothing). `MANIFEST.csv` (date, file name, url, bytes, sha256, pattern, status) is in the archive folder. The archive is outside the repo and is not committed.
- **Other sessions:** none found beyond the lake dates. The old loader's fetch log (which tried weekends too, 2013 to 2026-09-30) found no extra session.
- **One difference:** on 2020-07-13 the file has 1,384 EQ rows, the lake 1,392 (cause not investigated; the only day where the EQ row counts differ).
- **Lake names vs file names:** on 353,096 lake rows the symbol is the LATEST name of a renamed stock, while the raw file carries the name of the day (close prices are identical on all 5,275,451 same-name rows). Joins between the archive and the lake therefore go by ISIN.
- **Series found:** 175 codes. EQ 5,628,539 rows; BE 517,788 (2,274 symbols); SM 334,599; BZ 68,190 (306 symbols); ST 66,960; BL 3,194; many others (N*, Y*, Z*, GB, GS, TB ...). 2,617 ISINs traded in BE or BZ at some time (2,557 BE, 348 BZ).
- **Stored-results trades closed SYMBOL_NO_BARS: 20** (18 in riskadj_momentum_daily, 2 in lowvol_uptrend; none in the other four runs). In 17 of the 20 the stock traded in BE for the whole 20-session window (every such window has 20 BE rows). 3 have no row in any series after their last EQ date (GSKCONS twice, JBCHEPHARM).
- **The design is in `docs/shared/non-eq-series/DESIGN.md`.** Nothing is built. STOPPED for the owner's review.

## Part A: what the old loader is
- `scripts/ingest_raw_bhavcopy_range.py` is a 7-line wrapper that runs `stockbot/data/ingestion/ingest_raw_bhavcopy_range.py` (F2 staging loader).
- URL patterns: UDiFF `https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_YYYYMMDD_F_0000.csv.zip`, `https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_DDMMYYYY.csv`, legacy `https://archives.nseindia.com/content/historical/EQUITIES/YYYY/MON/cmDDMONYYYYbhav.csv.zip`; UDiFF first from 2024-07-01, legacy first before.
- It keeps EQ rows only (`parse_bhavcopy` filters `series == "EQ"`), writes them to `market_data_lake_staging`, and saves NO raw file (the zip is read from memory). The daily job `bhavcopy_ingestor.py` does the same.
- Leftover bhavcopy files on this machine: none. Under `F:\Projects\Ravi` the only matches for "bhav" are `.pyc` caches and two unrelated Yahoo CSVs (`SADBHAV`, `VAIBHAVGBL`).
- New script: `scripts/archive_raw_bhavcopy.py` (the old one is untouched): resumes (skips a valid existing file), never overwrites, accepts a file only if the date inside it equals the requested date, retries with backoff, stops with the exact error if 5 dates in a row fail for a reason other than 404. Tested on 3 days and re-run (second run skipped all 3) before the full run.

## Part B: restricted-series inventory (read-only, from the raw files)
Tables are in `Claude_Docs/non_eq_series/` (CSV, JSON); produced by `scripts/non_eq_series_inventory.py`.

### B1. Rows per series code
Total 7,233,694 rows in 3,416 files. Largest codes (all 175 in `b1_series_totals.csv`, per-day counts in `b1_rows_per_day_per_series.csv`):

| series | rows | days | symbols | first | last |
|---|---|---|---|---|---|
| EQ | 5628539 | 3416 | 3965 | 2013-01-01 | 2026-10-16 |
| BE | 517788 | 3416 | 2274 | 2013-01-01 | 2026-10-16 |
| SM | 334599 | 3339 | 781 | 2013-01-01 | 2026-10-16 |
| GB | 89213 | 2565 | 69 | 2016-06-13 | 2026-10-16 |
| BZ | 68190 | 3027 | 306 | 2014-07-09 | 2026-10-16 |
| ST | 66960 | 1669 | 723 | 2018-03-28 | 2026-10-16 |
| GS | 43542 | 1785 | 158 | 2018-12-26 | 2026-10-16 |
| N6 | 34299 | 3416 | 72 | 2013-01-01 | 2026-10-16 |
| N2 | 33128 | 3416 | 82 | 2013-01-01 | 2026-10-16 |
| N4 | 25503 | 3416 | 68 | 2013-01-01 | 2026-10-16 |
| N5 | 23553 | 3416 | 73 | 2013-01-01 | 2026-10-16 |
| N1 | 23548 | 3415 | 124 | 2013-01-01 | 2026-10-16 |

Mean rows per day by year:

| Unnamed: 0 | EQ | BE | BZ | BL | SM | ST |
|---|---|---|---|---|---|---|
| 2,013.00 | 1,325.30 | 83.20 | 0.00 | 0.30 | 1.30 | 0.00 |
| 2,014.00 | 1,332.30 | 167.30 | 1.90 | 0.30 | 1.40 | 0.00 |
| 2,015.00 | 1,438.30 | 47.10 | 5.40 | 0.60 | 3.30 | 0.00 |
| 2,016.00 | 1,500.70 | 46.00 | 4.30 | 0.30 | 7.60 | 0.00 |
| 2,017.00 | 1,486.00 | 105.10 | 7.10 | 0.60 | 37.70 | 0.00 |
| 2,018.00 | 1,495.40 | 137.80 | 18.70 | 0.30 | 82.60 | 2.20 |
| 2,019.00 | 1,504.40 | 135.60 | 27.50 | 0.50 | 75.40 | 0.50 |
| 2,020.00 | 1,507.00 | 152.70 | 40.00 | 0.30 | 60.30 | 0.40 |
| 2,021.00 | 1,571.70 | 186.10 | 38.10 | 0.90 | 60.60 | 0.80 |
| 2,022.00 | 1,769.70 | 145.80 | 27.40 | 3.70 | 75.60 | 3.50 |
| 2,023.00 | 1,817.00 | 213.50 | 25.90 | 0.60 | 135.30 | 8.10 |
| 2,024.00 | 1,877.10 | 297.80 | 23.10 | 1.30 | 240.70 | 59.00 |
| 2,025.00 | 2,135.60 | 221.80 | 30.90 | 2.20 | 283.90 | 121.70 |
| 2,026.00 | 2,475.50 | 190.10 | 31.00 | 1.10 | 358.10 | 92.50 |

### B2. Symbols that ever traded in BE or BZ (followed by ISIN)
2,617 ISINs (224 carry more than one symbol name). Full list with first/last date in each series, run path and direction: `b2_be_bz_symbols.csv`.

| direction (within 2013-01-01 .. 2026-10-16) | ISINs |
|---|---|
| EQ to BE/BZ and back (both) | 1,738 |
| BE/BZ only (never EQ in the window) | 565 |
| BE/BZ to EQ only | 185 |
| EQ to BE/BZ only | 129 |

Note: a stock already in BE on the first file date or still in BE on 2026-10-16 is cut off by the window, so the "only" rows can be a spell cut off by the archive edges.

### B3. The 20 SYMBOL_NO_BARS trades in the six stored results (DESCRIPTION ONLY, not a re-evaluation)
Runs read: near_52w_high results_4B (774 trades, 0 stale), pullback_uptrend run1 (4,156, 0), short_term_reversal run1 (4,288, 0), lowvol_uptrend run1 (413, 2), riskadj_momentum run1 (650, 0), riskadj_momentum_daily run1 (1,048, 18). Closes are raw closes from the archive file; the stock is followed by ISIN; sessions are counted on the archive calendar; "no row" = no row in any series that day. The last EQ close equals the `last_close` stored in each trade (checked for all 20). "Last BE/BZ close in window" is the last close up to the stale-exit date of the stored trade.

| run | symbol | last EQ date | last EQ close | s+1 | s+5 | s+10 | s+20 | BE/BZ rows in window | last BE/BZ close in window (to the stale exit date) | back in EQ on |
|---|---|---|---|---|---|---|---|---|---|---|
| lowvol_uptrend | GSKCONS | 2020-04-15 | 10,732.60 | no row | no row | no row | no row | 0 | none |  |
| lowvol_uptrend | JBCHEPHARM | 2026-07-16 | 2,408.90 | no row | no row | no row | no row | 0 | none |  |
| riskadj_momentum_daily | BOMDYEING | 2018-07-03 | 216.40 | 211.35 (BE) | 216.60 (BE) | 221.90 (BE) | 260.00 (BE) | 20 | 260.00 on 2018-07-31 | 2018-10-30 |
| riskadj_momentum_daily | GSKCONS | 2020-04-15 | 10,732.60 | no row | no row | no row | no row | 0 | none |  |
| riskadj_momentum_daily | MAGMA | 2021-06-08 | 154.90 | 155.25 (BE) | 156.75 (BE) | 155.55 (BE) | 157.50 (BE) | 20 | 157.50 on 2021-07-06 | 2021-09-13 |
| riskadj_momentum_daily | ADANIENSOL | 2021-06-08 | 1,592.60 | 1571.50 (BE) | 1446.40 (BE) | 1367.25 (BE) | 953.80 (BE) | 20 | 953.80 on 2021-07-06 | 2021-09-13 |
| riskadj_momentum_daily | CGPOWER | 2021-06-08 | 83.15 | 79.30 (BE) | 84.75 (BE) | 79.85 (BE) | 79.95 (BE) | 20 | 79.95 on 2021-07-06 | 2021-09-13 |
| riskadj_momentum_daily | ATGL | 2021-06-08 | 1,640.85 | 1588.20 (BE) | 1467.70 (BE) | 1387.40 (BE) | 918.20 (BE) | 20 | 918.20 on 2021-07-06 | 2021-09-13 |
| riskadj_momentum_daily | GPIL | 2021-06-17 | 1,395.45 | 1325.70 (BE) | 1340.70 (BE) | 1317.80 (BE) | 1402.05 (BE) | 20 | 1402.05 on 2021-07-15 | 2021-09-27 |
| riskadj_momentum_daily | CDSL | 2021-07-20 | 1,501.70 | 1426.65 (BE) | 1329.35 (BE) | 1333.35 (BE) | 1210.60 (BE) | 20 | 1210.60 on 2021-08-18 | 2021-10-25 |
| riskadj_momentum_daily | JSWENERGY | 2021-07-28 | 253.45 | 250.05 (BE) | 247.05 (BE) | 228.35 (BE) | 237.95 (BE) | 20 | 237.95 on 2021-08-26 | 2022-04-25 |
| riskadj_momentum_daily | TATASTLBSL | 2021-08-05 | 98.60 | 96.05 (BE) | 94.85 (BE) | 93.15 (BE) | 94.10 (BE) | 20 | 94.10 on 2021-09-03 |  |
| riskadj_momentum_daily | TRIDENT | 2022-01-20 | 64.45 | 64.35 (BE) | 60.40 (BE) | 62.30 (BE) | 53.00 (BE) | 20 | 53.00 on 2022-02-18 | 2022-04-25 |
| riskadj_momentum_daily | PCJEWELLER | 2022-09-12 | 74.05 | 70.50 (BE) | 73.90 (BE) | 86.70 (BE) | 96.50 (BE) | 20 | 96.50 on 2022-10-11 | 2022-12-06 |
| riskadj_momentum_daily | NEWGEN | 2023-11-01 | 1,144.00 | 1135.30 (BE) | 1183.75 (BE) | 1172.60 (BE) | 1455.65 (BE) | 20 | 1455.65 on 2023-11-30 | 2024-02-12 |
| riskadj_momentum_daily | TECHNOE | 2024-06-06 | 1,252.90 | 1230.60 (BE) | 1465.95 (BE) | 1441.80 (BE) | 1475.45 (BE) | 20 | 1475.45 on 2024-07-05 | 2024-09-09 |
| riskadj_momentum_daily | SHAILY | 2024-12-30 | 1,465.75 | 1439.60 (BE) | 1474.90 (BE) | 1486.65 (BE) | 1369.20 (BE) | 20 | 1369.20 on 2025-01-27 | 2025-03-25 |
| riskadj_momentum_daily | E2E | 2026-02-23 | 2,569.50 | 2441.10 (BE) | 2457.00 (BE) | 2422.10 (BE) | 2160.90 (BE) | 20 | 2160.90 on 2026-03-24 | 2026-05-19 |
| riskadj_momentum_daily | DIACABS | 2026-08-03 | 322.85 | 316.40 (BE) | 360.50 (BE) | 359.90 (BE) | 347.30 (BE) | 20 | 347.30 on 2026-08-31 |  |
| riskadj_momentum_daily | HFCL | 2026-09-02 | 226.27 | 220.42 (BE) | 245.43 (BE) | 209.45 (BE) | 238.36 (BE) | 20 | 238.36 on 2026-10-01 |  |

Reading: 17 of 20 stocks kept trading in BE through the whole window (20 BE rows each); the close 20 sessions after the last EQ day ranges from 53.00 to 2,160.90 rupees (different stocks, not comparable). Four stocks (MAGMA, ADANIENSOL, CGPOWER, ATGL) share the last EQ date 2021-06-08 and moved to BE together. GSKCONS and JBCHEPHARM have no row in any series after the last EQ date. TATASTLBSL, DIACABS and HFCL are still BE at the end of the archive; the others came back to EQ on the date in the last column.

### B4. Coverage: what BE/BZ rows would add to the EQ lake
The archive EQ rows are the lake rows (same prices on all matched rows, see Summary), so the EQ date set of an ISIN is its lake date set.

| measure | ISINs | sessions |
|---|---|---|
| ISINs with both EQ rows and BE/BZ rows | 2,052 | |
| BE/BZ sessions INSIDE a stock's EQ history (between its first and last EQ date, no EQ row that day): a gap in the lake | 1,713 | 426,645 |
| BE/BZ sessions AFTER a stock's last EQ date (trailing: where a held stock would go stale) | 605 | 112,828 |
| BE/BZ sessions BEFORE the first EQ date (leading: not a gap for a held stock) | 546 | 40,389 |
| internal + trailing | 1,867 | 539,473 |

Per-ISIN counts: `b4_coverage_by_isin.csv`. BZ is counted with BE; other restricted codes (BL, SM, ST ...) are not counted here.

### B5. Price band and volume of BE/BZ rows
**The files have no price-band column** (legacy file columns: SYMBOL, SERIES, OPEN, HIGH, LOW, CLOSE, LAST, PREVCLOSE, TOTTRDQTY, TOTTRDVAL, TIMESTAMP, TOTALTRADES, ISIN; UDiFF and `sec_bhavdata_full` carry the same fields, the latter adds delivery quantity). The band is unknown from the files; the table shows what prices and volumes did.

| | BE | BZ |
|---|---|---|
| rows (with a previous close) | 517,788 | 68,190 |
| median volume (shares) | 16,015 | 26,698 |
| p10 volume | 525 | 1,177 |
| p90 volume | 329,048 | 471,452 |
| median traded value (INR) | 441,896 | 89,996 |
| p10 traded value (INR) | 6,735 | 3,111 |
| p90 traded value (INR) | 10,610,037 | 1,628,312 |
| median number of trades | 78 | 49 |
| median abs close-to-previous-close move (%) | 2.15 | 2.99 |
| p90 abs move (%) | 4.98 | 5.02 |
| p99 abs move (%) | 14.29 | 20.00 |
| share of rows with abs move at least 4.9% | 0.142 | 0.164 |
| share at least 9.9% | 0.017 | 0.037 |
| share at least 19.9% | 0.007 | 0.015 |
| median high-low range (% of previous close) | 4.53 | 4.95 |

Largest absolute move seen per ISIN (a hint of the band that applied, not the band): BE {'<=5.2': 1580, '5.2-10.2': 186, '10.2-20.2': 151, '>20.2': 640}; BZ {'<=5.2': 221, '5.2-10.2': 60, '10.2-20.2': 31, '>20.2': 36}. Moves above 20% are likely corporate actions on an unadjusted previous close or newly listed names (not checked). Zero-volume rows: none (the file has a row only when a trade happened).

## Part C: design
See `docs/shared/non-eq-series/DESIGN.md` (tables first: new table `market_data_non_eq` and its guard class; how the engine reads it; where the never-buy rule lives in the shared engine and the test; EQ to BE/BZ and back and the stale rule; BE/BZ sell fill model; what a re-evaluation would be; risks and open questions). Proposal only.

## Shared files touched
None. New files only: `scripts/archive_raw_bhavcopy.py`, `scripts/non_eq_series_inventory.py`, `docs/shared/non-eq-series/BRIEF.md`, `STATUS.md`, `DESIGN.md`, `Claude_Docs/NON_EQ_SERIES_STAGE1_REPORT.md`, `Claude_Docs/non_eq_series/*`. The raw archive and the parsed cache (`F:\Projects\Ravi\StockBotData\derived\bhav_all.pkl`) are outside the repo.

## What ran, what did not
Ran: the archive (once, full); the inventory (several times while I fixed my own lookup: the stock-to-ISIN step first picked an old ISIN for TRIDENT and JBCHEPHARM; fixed and re-run, the final tables are from the last run). Did not run: any backtest or registered run, any write to `finsight.db`, any build of the table or engine change, any guard command.
