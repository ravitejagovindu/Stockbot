# StockBot — Status and open points for the reviewer (2026-11-07)

Against the reviewer's step list ("GO / STOP"). Evidence is in `STOCKBOT_STEP1_CONFIRMATIONS.md` and `STOCKBOT_STEP1_RESULTS.md` (same folder) and in `docs/data_audit/`. Commits up to `be278ba` are pushed to `origin/master`; the working tree is clean.

**Nothing in `market_data_lake`, `corporate_actions_log` or `shares_outstanding` has changed.** Only the staging tables (`market_data_lake_staging`, `bhavcopy_fetch_log`) were rewritten. The F3 migration is still not applied.

## 1. Status by step

| Step | State | Notes |
|---|---|---|
| Housekeeping | **done** | Tag `pre-prereq-fixes` pushed. Clean-clone test log in `docs/data_audit/clean_clone_test_log.txt`: 247 passed, 2 failed, 0 skipped; both failures are `test_baseline_reproducibility` (needs the real database; F10 item). Second backup: owner decided that the single local checksummed backup `F:\Projects\Ravi\Backups\finsight_pre_F2_2026-11-06.db` (1,005,137,920 bytes) is enough, no off-machine copy. |
| 1 Confirmations | **done; two unexpected results, both fixed** | (a) The "8,903 missing 2019 rows" were holiday copies caused by an ingester bug; fixed with an in-file date check, staging cleaned (81 copy dates removed, 0 left), 14 real special sessions added. (b) Renamed ISINs: map built (334 pure rename / 12 demerger-merger / 53 other). (c) ADTV uses Bhavcopy traded quantity: confirmed in code. The check that volume units are continuous across the legacy-to-UDiFF format change is **not done yet**. |
| 2 Prepare the swap | **not started** | Waits for the two answers in section 2. Backup integrity and checksum will be verified immediately before the swap. |
| 3 Swap and post-swap checks | **not started** | |
| 4 Corporate-action fixes | **partly done** | Done: parser patterns (TVSMOTOR, TVSHLTD, SIYSIL, RADIOCITY, SHARONBIO) with 5 regression tests; dispositions for DVL, VCL, MARINE. Not done: evidence tiers for the 1,116 split/bonus events; old-symbol queries through the ISIN map (row count added, cross-check rerun). |
| 5 Eligible symbols | **not started** | Needs the cleaned staging data (now available). |
| 6 Verification list | **not started** | Result columns, a split and a bonus in the same year on different dates, a relisted or suspended name. |
| STOP A | not reached | The corporate-action load is on hold. |
| 7 Load and integration tests | not started | |
| STOP B | not reached | |
| F2b, F9 study, AMD-002 | not started | After STOP B. |

## 2. Open points that need the reviewer

1. **Pre-2020 special sessions.** Staging 2013–2019 equals the lake plus 8,034 rows on six real special sessions that the lake lacks (2013-05-11, 2013-11-03, 2014-03-22, 2015-02-28, 2016-10-30, 2019-10-27). Insert them in the swap, append-only? **Recommended: yes.**
2. **Rewriting pre-2020 symbols.** Option A with "all years" rewrites `symbol` on existing pre-2020 lake rows for the 334 pure-rename ISINs (380 segments) and keeps the traded symbol in a new `source_symbol` column. The plan said not to touch existing pre-2020 rows. **Confirm.** I will protect it with before/after row counts and a checksum over (source_symbol, trade_date, OHLCV).
3. **Classification review.** Demerger/merger (12) and other (53) ISINs stay split. 52 of the 53 "other" ISINs are gap cases (suspension or relisting), one is a price step without a feed event (AMTEKINDIA → CASTEXTECH, ratio 1.71). Agreed approach: hand review only for symbols that become eligible (₹25 crore ADTV gate) once Step 5 has run. Confirm.
4. **Lake filler rows.** The lake has 6 near-empty dates (zero volume, flat close, no Nifty row) between 2025-03-18 and 2026-09-14. All lie inside the replaced range, so the swap removes them. Note: this differs from the earlier description of "5 lake holiday copies"; the detector finds no exact copies in the lake.
5. **Nifty gaps.** The lake's Nifty series lacks four ordinary sessions (2015-12-01, 2016-06-20, 2018-01-16, 2026-09-30). Recorded in `data/reference/special_sessions.csv` as `nifty_gap` so the calendar test passes. Does the reviewer want them filled from another source, or accepted?
6. **The 340 events with no price evidence** (actions before a rename, non-EQ series). The old-symbol queries should reduce this; the count on eligible symbols will be reported in Step 5.

## 3. Findings outside the plan

- **Cause of the earlier STOP-1 miss:** the calendar check counted Nifty dates without Bhavcopy but not the reverse. Now both directions are checked, and the check is a permanent test (`tests/data_integrity`, runs only with `STOCKBOT_DATA_TESTS=1` and the real database).
- **NSE's `PrevClose` field is not adjusted for corporate actions**, so the Bhavcopy previous-close factor cannot cross-check a split. The raw close-to-close ratio replaces it (764 of 776 ex-dates agree within 20%; Yahoo-implied factor 407 of 413).
- **Process slips to be aware of:** (a) the first F6 commit (reported earlier) carried failing tests and unrelated scripts; (b) three runs of the validation and detector scripts were killed by low machine memory, so the lake pass now runs year by year; (c) the staging ingester bug was mine and was in the data that went into STOP-1.
- **Carried forward for the strategy specification** (reviewer's point): a rule such as "no entries for 252 sessions after an unadjusted event (demerger, merger, large rights issue)" unless an adjustment factor can be derived. The 12 demerger/merger ISINs and the events marked for manual review are the input list.
- **F3 migration** (`data/db/migration_f3_corporate_actions.py`) will be applied together with the F2 migration in the swap transaction.

## 4. What I will do next (no decision needed)

1. Evidence tiers for all events (strong: Yahoo factor within 3%; weak: raw close ratio within 25%; unsupported → `OTHER`), including the ±2-session check around the ex-date.
2. Old-symbol queries through the ISIN map, then the cross-check on the new rows.
3. Eligibility by the ₹25 crore ADTV gate on raw data; triage of the 889 large moves; count of the 340 no-evidence events on eligible symbols.
4. Verification-list result columns and the two missing cases.
5. The volume-unit continuity check across the Bhavcopy format change.

The swap script (Step 2) needs answers 1 and 2 above before I can finish it.
