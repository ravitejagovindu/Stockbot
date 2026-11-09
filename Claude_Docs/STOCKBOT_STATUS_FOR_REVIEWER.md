# StockBot — Status and open points for the reviewer (updated 2026-11-07, after all GO steps)

**Latest (after the reviewer's STOP A verdict): see `STOCKBOT_STOP_A_RESPONSE.md`** (revised tiers, events vs rows, post-adjustment scan, nine dispositions, two corrections). The open-points list below is superseded by section 7 of that file.

Where to read the detail: `STOCKBOT_STEP1_RESULTS.md` (holiday copies, ISIN map), `STOCKBOT_STEP3_SWAP_REPORT.md` (swap, mapping, post-swap checks), `STOCKBOT_STEP4_6_REPORT.md` (evidence tiers, eligibility, verification list, open points), `STOCKBOT_PREREQUISITE_FIXES_REPORT.md` (all commits). Evidence files are in `docs/data_audit/`. Everything is pushed to `origin/master`; the working tree is clean.

**State of the database:** the swap and the symbol mapping have run on the real `finsight.db`. `corporate_actions_log` is still empty (STOP A) and `shares_outstanding` is unchanged (F2b).

## 1. Status by step
| Step | State |
|---|---|
| Housekeeping, backup | done; one local checksummed backup accepted by the owner (verified again immediately before the swap) |
| 1 Confirmations | done; volume-unit continuity check done (median ratio 0.96 vs 0.83–1.03 controls) |
| 2 Prepare the swap | done; rehearsed on a scratch copy (deleted afterwards), three transactions in the reviewer's order |
| 3 Swap and post-swap checks | **done, all checks pass** (2,829,905 Yahoo rows archived, 3,110,289 raw rows inserted, 8,034 special-session rows and 51 index rows added, 353,088 rows relabelled by the ISIN map, untouched rows checksum-identical, 0 duplicates, Nifty/VIX gap-free, calendar data tests pass) |
| 4 Corporate-action fixes | **done**: parser fixes (two rounds, 16 tests failed before), evidence tiers (STRONG 427 / WEAK 327 / UNSUPPORTED 375 of 1,129 events), old-symbol queries already covered by the original dump, DVL window checked |
| 5 Eligible symbols | **done**: 1,743 symbols pass the ₹25 crore gate (63 are ETFs/funds), 889 large moves triaged, 122 relevant, 9 for manual judgement |
| 6 Verification list | **done**: 57/57 PASS, split+bonus-different-dates and relisted cases added |
| STOP A | **reached; reviewer asked for revised tiers, reconciliation, scan and dispositions: delivered in `STOCKBOT_STOP_A_RESPONSE.md`, waiting for approval of the load** |
| 7 Load and integration tests | not started (after STOP A) |
| STOP B, F2b, F9 study, AMD-002 | not started |

## 2. Open points that need the reviewer (also in `STOCKBOT_STEP4_6_REPORT.md`, section 5)
1. **Evidence rule rejects genuine-looking events:** 40 of 44 conflicting eligible events are within 25% of the logged factor, mostly with a price rise on the ex-date. Recommended: accept as `WEAK_DIRECTIONAL`; alternative: keep strict and put them on the no-entry list. Decides the SPLIT/BONUS counts for the load.
2. **A symbol rename combined with an ISIN change** can hide a rename from the symbol map (not measured).
3. **Nine large moves** for judgement (STAR, YESBANK ×2, INDUSINDBK, MAJESCO, PGIL, JYOTISTRUC, SCHNEIDER, SIGMAADV).
4. **ETFs/funds** (63 eligible symbols with INF ISINs) to be excluded from the equity universe.
5. **Placeholder listing dates** in `securities_master` (110 eligible names; 211 without a master row): proposal to derive the listing date from the first raw trading day; `securities_master` stays untouched. Needs approval.
6. **Events with no usable price data** (135 before 2013, 28 without EQ rows) are not adjustable from our data.
7. **Index fill:** 12 of the 51 gap-fill rows are Yahoo (NSE has no file for those dates), verified on 2 overlapping dates; the owner accepted this.
8. **Process notes:** the earlier F6 commit slip and the ingester bug are disclosed in the prerequisite report. In this stretch two of my own edits (a regex patch and a CSV-writer line) broke and were caught by the tests or by running the script before commit; MARINE and VCL were wrongly called WEAK in my earlier report and are now UNSUPPORTED under the stricter rule.

## 3. Next (after the reviewer's answers)
Step 7: append-only load into `corporate_actions_log` with counts by type and tier, a real-database integration test for every row of the verification list, and a test that ADTV and market cap use raw prices only. Then STOP B, F2b (point-in-time shares), the F9 weekly-vs-monthly study, AMD-002, and the strategy specification (carrying the "no entries for 252 sessions after an unadjusted event" rule).
