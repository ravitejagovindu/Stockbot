# StockBot — Step 1 results after the reviewer's approval (2026-11-07)

Status: holiday-copy clean-up and the ISIN map are done and tested. **The swap has not run.** `market_data_lake` and `corporate_actions_log` are unchanged. Only the staging tables changed.

## 1. Commits

| Commit (see `git log`) | Content |
|---|---|
| ingester fix | `scripts/ingest_raw_bhavcopy_range.py`: a file is accepted only if its own date (`DATE1` / `TIMESTAMP` / `TradDt`) equals the requested date; `--all-days` (weekends), `--redo`; a holiday re-fetch deletes stale staging rows. 2 of the 3 new tests failed on the old code. |
| parser fix | `data/ingestion/nse_corporate_actions_history.py`: bonus of NCRPS / preference shares under a scheme is `NON_PRICE` (TVSMOTOR, TVSHLTD, SIYSIL, RADIOCITY); "Split From 10/- To Face Value 2/-" is read (SHARONBIO). 5 new tests failed before. |
| ISIN map + detector | `scripts/f2_build_isin_symbol_map.py` (+ 4 tests), `scripts/f2_copy_detector.py` (+ 2 tests). |
| data + permanent test | `data/reference/isin_symbol_map.csv`, `data/reference/special_sessions.csv`, `tests/data_integrity/test_calendar_integrity.py` (runs only with `STOCKBOT_DATA_TESTS=1`), audit CSVs. |

Pure suite after these commits: **249 passed**.

## 2. Root cause and clean-up (Result 1)

- **Root cause confirmed.** The third candidate URL, `sec_bhavdata_full_DDMMYYYY.csv`, answers HTTP 200 on a holiday with the previous session's file. The file's own `DATE1` says so (for example 2019-10-02 → `01-Oct-2019`; 2022-01-26 → `25-Jan-2022`). The old ingester stamped the requested date on it.
- **The 4 files that were not copies** were real special sessions stamped one or two days late: 2019-10-28 held Sunday 2019-10-27 (Diwali Muhurat), 2020-11-16 held Saturday 2020-11-14, 2024-01-22 held Saturday 2024-01-20, 2024-05-20 held Saturday 2024-05-18. They are now stored under their true dates.
- **Copy detector over all dates** (a date is a copy when ≥ 90% of symbols have identical close and volume to the previous session):
  - Staging before the clean-up: **81 copy dates** (all 100% identical), 2019-10-02 … 2026-09-14.
  - Staging after the clean-up: **0**.
  - Whole lake, 14 yearly passes 2012-12-15 … 2026-12-31: **0 exact copies**. But the lake holds **6 near-empty filler dates** (more than half the symbols with volume 0, flat close, no Nifty row): 2025-03-18, 2026-01-15, 2026-05-01, 2026-05-28, 2026-06-26, 2026-09-14. All six lie inside 2020-01-01 … 2026-09-30, so the swap removes them. (The reviewer's "5 lake holiday copies" were really these zero-volume Yahoo fillers; 2025-03-18 is a real session in staging with true data, so the swap replaces the filler with real rows.)
- **Special sessions found (14, all with the file's own date verified)**: 2013-05-11, 2013-11-03, 2014-03-22, 2015-02-28, 2016-10-30, 2019-10-27, 2020-02-01, 2020-11-14, 2023-11-12, 2024-01-20, 2024-03-02, 2024-05-18, 2025-02-01, 2026-02-01. Recorded in `data/reference/special_sessions.csv`, together with four ordinary sessions that the lake's Nifty series lacks (2015-12-01, 2016-06-20, 2018-01-16, 2026-09-30).
- **Calendar test** (permanent, `tests/data_integrity`): staging and lake have no copy dates; every staging date from the Nifty start is a Nifty date or listed in `special_sessions.csv`; no Nifty date lacks Bhavcopy rows. 3 passed. The copy test itself is verified by 2 synthetic unit tests, because the data test is skipped without the database.

**Cleaned staging counts** (rows / trading days): 2013 331,315 / 250 · 2014 325,090 / 244 · 2015 356,689 / 248 · 2016 370,662 / 247 · 2017 368,537 / 248 · 2018 367,880 / 246 · 2019 368,578 / 245 · 2020 379,782 / 252 · 2021 389,770 / 248 · 2022 438,894 / 248 · 2023 446,991 / 246 · 2024 467,396 / 249 · 2025 531,765 / 249 · 2026 (to 09-30) 455,691 / 185. Fetch log: 3,405 OK, 1,616 holiday/missing, 0 errors.

**Pre-2020 comparison, updated.** Staging 2013–2019 is now the lake's 2,480,717 rows plus exactly **8,034 rows on five special sessions** that the lake lacks: 2013-05-11 and 2013-11-03 (2,357 rows), 2014-03-22 (1,278), 2015-02-28 (1,410), 2016-10-30 (1,516), 2019-10-27 (1,473). The 2019 gap of 8,903 rows therefore disappears completely: those six dates were holidays. **Decision for the reviewer: insert the 8,034 pre-2020 special-session rows (append-only) in the swap?** I propose yes; they are real sessions.

## 3. ISIN → canonical symbol map (Result 2, Option A)

`data/reference/isin_symbol_map.csv` (deterministic; one row per ISIN × symbol segment; columns include `isin_class`, `canonical_symbol`, `boundary_reason`, `gap_sessions`, `close_ratio_next_over_this`). Rules are in `scripts/f2_build_isin_symbol_map.py` and tested.

| Class | ISINs | Treatment |
|---|---|---|
| pure_rename | **334** | `canonical_symbol` = the ISIN's latest symbol, applied to **all years**; `source_symbol` keeps the traded symbol. 380 segments are remapped. Every boundary has no overlap, a gap of at most 20 sessions, a raw close ratio between 0.8 and 1.25 and no demerger/merger in the NSE feed within 45 days. |
| demerger_merger | **12** | Stay split: SUNCLAYLTD→TVSHLTD, **TATAMOTORS→TMPV**, MAX→MFSL, GUJFLUORO→GFLLIMITED, HEG→HEGAM, BOROSIL→BORORENEW, DEEPIND→DEEPENR, JUBILANT→JUBLPHARMA, KPIT→BSOFT, GUJGASLTD→GUJENERGY, plus the two Future-group ISINs (FRL, FRLDVR). Their price is mostly continuous, but the reviewer asked to keep demerger/merger pairs split. |
| other | **53** | Stay split. Across these 53 ISINs there are 54 boundaries: 53 with a gap of more than 20 sessions (suspension or relisting, for example SONAMCLOCK→SONAMLTD 64 sessions, AHL→AFSL 61) and 1 with a price step without a feed event (AMTEKINDIA→CASTEXTECH, ratio 1.71). Hand review for eligible symbols follows once eligibility is computed (Step 5). |

Examples after the map: CADILAHC → ZYDUSLIFE and MICROSEC → SASTASUNDR → HEALTHX become one continuous history each.

The map will drive the swap and also the corporate-action old-symbol queries, the future shares table, the sector map and ASM/earnings history (one mapping, no per-table copies).

## 4. Corporate-action conflicts (Step 4, first part)

| Symbol, ex-date | Disposition |
|---|---|
| TVSMOTOR 2025-08-25, TVSHLTD 2026-09-08, SIYSIL 2026-08-21, RADIOCITY 2023-01-13 | The subject was "Scheme Of Arrangement - Bonus **NCRPS** a:b" (bonus of non-convertible redeemable preference shares). Not price-moving. Parser fixed; now stored as `OTHER` / `NON_PRICE`. |
| SHARONBIO 2014-02-20 | "Bonus 1:1 / Face Value Split From 10/- To Face Value 2/-": the split was missed; parser fixed, combined factor 0.1 matches the raw price ratio 0.12. |
| DVL 2021-08-05 | Feed says "Bonus 1:2". The raw close moved only 300.75 → 281.05 (−6.5%) and Yahoo shows no step. Not supported by prices → tier UNSUPPORTED, stored as `OTHER` for manual review. |
| VCL 2023-02-15 | Genuine Rs2 → Re1 split. Price 5.95 → 3.60 (ratio 0.605 against 0.5) because of a 21% same-day rise on 4.1 million shares; next day 2.90. Tier WEAK, accepted as genuine. |
| MARINE 2021-02-18 | Genuine Rs10 → Rs2 split. Price 258.10 → 57.85 (ratio 0.224 against 0.2). Tier WEAK, accepted. (Yahoo shows 0.224 as well; its adjustment included the day's move.) |

Still to do in Step 4: evidence tiers for all 1,116 events, old-symbol queries through the map (row count added), then Steps 5 and 6.

## 5. Questions for the reviewer

1. Insert the 8,034 pre-2020 special-session rows in the swap (append-only)? Recommended: yes.
2. The map rewrites `symbol` on existing pre-2020 lake rows for the 334 pure-rename ISINs (adding `source_symbol` for reversibility). That touches existing pre-2020 rows, which the plan said to leave alone. Confirm it is wanted. I will protect it with before/after row counts and a checksum over (source_symbol, trade_date, OHLCV).
3. Hand-review of the 12 demerger/merger and 53 other ISINs: only for symbols that become eligible (₹25 crore ADTV gate), as agreed.

## 6. Carried forward for the strategy specification

The reviewer's new point: unadjusted events (demergers, mergers, large rights issues) distort price-history features such as 52-week highs for about a year. A likely rule is "no entries for 252 sessions after an unadjusted event" unless an adjustment factor can be derived from prices. The 12 demerger/merger ISINs and the events marked `manual_review` are the input list for it.
