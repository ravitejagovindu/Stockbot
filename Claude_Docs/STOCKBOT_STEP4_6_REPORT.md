# StockBot — Steps 4, 5, 6 and the Step 1 leftovers (2026-11-07)

Everything the reviewer marked GO is done: volume-unit check, Nifty/VIX gap fill, rehearsal, swap and post-swap checks (see `STOCKBOT_STEP3_SWAP_REPORT.md`), the rest of Step 4, Step 5, Step 6. **Nothing has been loaded into `corporate_actions_log` (it is empty); STOP A applies.** No config, gate or strategy file was touched. Pure suite: 280 passed, 3 skipped (the data tests without the env var). One task per commit; no commit with a failing test.

## 1. Commits (this stretch)
| Commit | Content |
|---|---|
| `2b03a6e` | Volume-unit continuity across the legacy→UDiFF Bhavcopy change: median after/before ratio 0.96 at 2024-07-01 against 0.83–1.03 at four control boundaries. Pass. |
| `4f8f2a1` | Nifty/VIX gap fill into `index_gap_fill` (39 rows from NSE's daily index file, 12 Yahoo fallback rows where NSE has no file; cross-checked on 2 overlapping dates, owner accepted). |
| `a0c6fc7`, `ef46661` | Swap script (three transactions), post-swap checks, rehearsal and real run (Step 3 report). The calendar data test now fails loudly if the env var is set and the database is missing. |
| `750015c` | Parser: abbreviated NSE subjects were dropped silently ("Fv Splt Frm Rs 10 To Rs 2", "Bon 1:1", "Fv Spl Rs.5tors.2", "Right Issue 1:15"). 11 new tests failed before; 16 feed subjects change, all intended (old vs new parser compared over the whole feed). Capital reduction / consolidation are now flagged UNPARSED instead of vanishing. |
| `a050132` | Step 4 evidence tiers (`data/ingestion/ca_evidence.py`, `scripts/f2_event_evidence.py`, `data/reference/corporate_actions_evidence.csv`). 6 tests failed before. |
| `63c2882` | Step 5 eligibility, triage and dispositions of the large moves. |
| `bebd08f` | Step 6 verification list with result columns, two added cases, 57/57 PASS. |

## 2. Step 4 — evidence tiers
Rule as the reviewer specified: STRONG = Yahoo-implied factor within 3%; WEAK = raw close ratio (best day pair within ±2 sessions of the ex-date) within 25% **and** the logged factor is the nearest standard ratio; otherwise UNSUPPORTED, stored as `OTHER`. Standard ratios = the 17 factors that occur at least 3 times in the feed (a dense set would make every 10% price move ambiguous). Tier and evidence text are stored per event.

Results, 1,129 split/bonus events (symbol, ex-date): **STRONG 427, WEAK 327, UNSUPPORTED 375**. Of the 375: 305 have no price data (210 rows are before staging starts on 2013-01-01 or after 2026-09-30, 95 had no EQ-series rows around the ex-date) and **86 have price data that does not fit** (44 on ADTV-eligible names).

**Old-symbol queries.** Already done: the original dump queried all 3,945 staging symbols, including all 454 retired traded symbols. Only 10 of the 454 returned rows (47 rows, none new): NSE keys its history to the current symbol. There is nothing to add by querying again.

**New finding that explains the 340 "no evidence" events:** NSE issues a **new ISIN at a face-value split** (360ONE: INE466L01020 → INE466L01038 on the ex-date). Matching events to prices by ISIN alone loses the ex-date. The evidence step matches on the ISIN **or any traded symbol of that ISIN** (from the map) **or** the event symbol; with that the "no price data" count fell from 629 rows to 315.

**DVL:** window checked: the best day pair within ±2 sessions is 0.915 (at −2 sessions, 2021-08-03), no step anywhere in the window, and Yahoo shows factor 1.0. UNSUPPORTED stands (stays `OTHER`).

**Correction to my earlier report:** MARINE (2021-02-18, split 0.2, observed 0.224) and VCL (2023-02-15, 0.5, observed 0.605) were called WEAK/genuine. Under the tightened rule they are UNSUPPORTED (0.224 is as near 0.25 as 0.2; 0.605 is nearer 0.6). Both are genuine splits per the feed subject; they are part of open point 1. SHARONBIO (0.1 vs 0.12) is WEAK.

## 3. Step 5 — eligibility and large moves
- ADTV gate (₹25 crore, SMA(raw close × raw volume, 20), engine definition) on staged raw data: **1,743 symbols pass at least once**, 63 of them with INF ISINs (ETFs/funds, to be excluded from the equity universe). Symbols passing per year: 166 (2013), 246, 260, 300, 407, 395, 294 (2019), 385 (2020), 686, 642, 818, 1,076, 1,096, 1,209 (2026). Market cap (F2b) is not applied.
- 889 large moves (>40%, no logged action within 3 days, price ≥ ₹5) triaged automatically; **122 are relevant** (equity, passes the gate within 20 sessions before to 252 after). Dispositions of the 122: 55 real moves across a gap in the EQ series (stock was in another series or suspended for >30 days, so the previous price is simply months old), 29 explained by a logged split/bonus once matched through the ISIN/rename history, 16 near a demerger/merger/rights (the unadjusted-event list for the strategy spec), 13 real moves (volume surge ≥ 3×, no action in the feed), **9 left for manual judgement**: STAR 2013-12-19 (−58%, no feed row), YESBANK 2020-03-16 and 2020-03-17, INDUSINDBK 2020-03-26, MAJESCO 2020-12-23 (−99%, volume ×0.1: looks like an unadjusted corporate event), PGIL 2024-01-22 (logged ex-date 17 days earlier), JYOTISTRUC 2024-01-22, SCHNEIDER 2024-05-20, SIGMAADV 2026-05-25. The other 767 moves (not relevant, or funds) are not reviewed individually (`docs/data_audit/large_moves_triage.csv`).
- Events on ADTV-eligible equity names, by tier: STRONG 332, WEAK 246, UNSUPPORTED 212 (`docs/data_audit/step5_summary.md`). Of the 212: 168 have no price data and **44 have conflicting price data** (open point 1).
- Placeholder listing dates: 110 eligible names have a `securities_master.listing_date` ≥ 2026-04-01 and 211 have no master row.

## 4. Step 6 — verification list
`data/reference/verified_corporate_actions.csv` now has `logged_factor`, `observed_raw_ratio`, `yahoo_factor`, `tier`, `result`, `result_note`. **57 rows, 57 PASS.** Added: EASEMYTRIP (bonus 2022-02-28, split+bonus 2022-11-21) and KPIGREEN (bonus 2024-02-15, split 2024-07-18), each a split and a bonus in the same year on different dates; AQYLON 2026-03-05 and AVANTIFEED 2015-11-26, names whose ISIN class is `other` (gap in the EQ series). The three demergers (RELIANCE 2023-07-20, ITC 2025-01-06, SIEMENS 2025-04-07) are in the feed and stored as DEMERGER (not price-moving); TATAMOTORS/TMPV stay split in the ISIN map (class demerger_merger). The real-database integration test for every row is Step 7 (after STOP A).

## 5. Open points for the reviewer (decisions needed before STOP A)
1. **The tightened rule rejects genuine-looking events.** 40 of the 44 conflicting eligible events are within 25% of the logged factor, and 39 of the 44 show a raw ratio **above** the logged factor (e.g. AJANTPHARM bonus 1:2: 0.667 logged, 0.728 observed; also GODREJCP, UPL, VBL, MOTHERSON, ASTRAL, BERGEPAINT, MARINE). An ordinary +5–10% price rise on the ex-date moves the ratio nearer the next standard ratio, so the rule calls them unsupported. Stored as `OTHER` they would **not be adjusted**, producing a false overnight drop in the price history. Options: (A) keep the rule: the events become `OTHER` and go on the "no entries for 252 sessions after an unadjusted event" list; (B) accept them as WEAK when the feed subject states the ratio, the raw ratio is within 25% **and** lies between the logged factor and the next standard ratio, and Yahoo (where it exists) does not contradict; they would carry a separate label `WEAK_DIRECTIONAL` so they can be filtered. I recommend B with the label. The other 4 (BBOX, MINDACORP, RAJRATAN, SUMEETINDS: no price step at the logged date) stay UNSUPPORTED either way. The list is in `data/reference/corporate_actions_evidence.csv` (tier UNSUPPORTED, `no_data_reason` empty).
2. **An ISIN change can hide a rename.** The ISIN map follows one ISIN; if a company changes symbol and ISIN together (a face-value split plus a rename), the two segments are not linked. Not measured. Proposal: report such pairs by price/volume continuity at the boundary, for eligible names only.
3. **Nine large moves** need your judgement (section 3). MAJESCO and STAR look like unadjusted corporate events; the rest are real moves or lack data.
4. **ETFs/funds:** 63 eligible symbols have INF ISINs; the universe must exclude them. Their unit splits (e.g. NIFTYBEES 2019-12-19) are not in the corporate-action feed.
5. **Placeholder listing dates** (110 eligible names with a date ≥ 2026-04-01, 211 with no master row): the listing-age gate would call them too young at every historical date, or fall back to the first lake date. Proposal: derive the listing date from the first raw trading day for the backtest and leave `securities_master` untouched. Needs your approval.
6. **Events before staging starts** (135 on eligible names) and events with no EQ rows around the ex-date (28): not adjustable from our data; they affect only prices before 2013 or periods when the stock was outside the EQ series.
7. **STOP A:** tiers, conflict dispositions and verification results are above; `corporate_actions_log` stays empty until you approve. Planned load, by stored type, before your decision on point 1: SPLIT 403, BONUS 384, RIGHTS 341, DEMERGER 108, MERGER 91, OTHER 778, DIVIDEND 20,913.

## 6. Next
Wait for your answers on STOP A (point 1 changes the SPLIT/BONUS counts), then Step 7 (append-only load, counts by type and tier, real-database integration test per verification row, test that ADTV and market cap use raw prices only), STOP B, F2b.
