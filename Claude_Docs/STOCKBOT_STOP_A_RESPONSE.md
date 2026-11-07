# StockBot — response to the reviewer's STOP A verdict (2026-11-07)

Produced as asked: revised tiers, the events-vs-rows table, the post-adjustment scan, the nine dispositions. **Nothing is loaded into `corporate_actions_log`.** Commits: `41cf8a2` (tiers), `b1bcc1c` (rename-with-split rule), `45530b9` (refreshed analysis, dispositions, load plan, unadjusted-event list). Pure suite: 286 passed, 3 skipped. Detail files: `docs/data_audit/load_plan.md`, `manual_move_dispositions.csv`, `post_adjustment_large_moves.csv`, `data/reference/unadjusted_events.csv`, `data/reference/corporate_actions_evidence.csv`.

## Status at a glance
| Item | State |
|---|---|
| Swap, symbol mapping, post-swap checks (Step 3) | accepted by the reviewer |
| Step 4 tiers, Step 5 eligibility, Step 6 verification list | done; tiers revised under the reviewer's rule (this file); verification list 58/58 PASS |
| Revised tiers, events vs rows, post-adjustment scan, nine dispositions | done (sections 1-5) |
| ETF exclusion (INF ISINs), listing-date rule | approved, not yet implemented (section 6); neither changes the load |
| STOP A: load into `corporate_actions_log` | **waiting for the reviewer's approval; table still empty** |
| Step 7, STOP B, F2b, F9 study, AMD-002 | not started |

## 0. Two corrections to my previous report (found while doing this work)
1. **The large-move list was stale.** `unexplained_moves.csv` had been generated before the holiday-copy clean-up, so it still contained moves on 2024-01-22 and 2024-05-20 (dates that no longer exist in staging; the real data sits on the Saturday sessions 2024-01-20 and 2024-05-18). I regenerated it from the current staging and redid the triage. The reviewer's suspicion about PGIL, JYOTISTRUC and SCHNEIDER was right in spirit (section 5). Corrected numbers: 873 large moves (was 889), **119 relevant** (was 122). I also restored the STOP-1 comparison files (`staging_vs_lake_by_year.csv`, `factor_crosscheck.csv`, validation report), which the rerun would otherwise have overwritten with post-swap values.
2. **Events were keyed to the wrong symbol in some cases.** The feed gives the company's *current* symbol; the prices before the ex-date can sit under another lake symbol when two names are separated by a gap and are not linked in the ISIN map (example: the 2016 split of SECURKLOUD; the prices on that date are under `8KMILES`, which is a gap-separated earlier name of the same company). An event stored under `SECURKLOUD` would never adjust the `8KMILES` history. The evidence file now carries `lake_symbol` = the lake symbol that holds the pre-ex-date prices; **the Step 7 load must write that as `symbol`** (feed symbol kept in `notes`). This removed 3 of the 21 residual unexplained moves after adjustment. **Please confirm this keying.**

## 1. Revised tiers (reviewer's rule)
`WEAK_DIRECTIONAL` = the feed subject states the ratio, Yahoo (where it exists) does not contradict (its factor within 25% of the logged one), logged factor ≤ 0.8, and adjusting improves the fit: ex-date return after adjustment within ±25% of 1 and at most half the unadjusted move in log terms. Tested: AJANTPHARM (0.667 vs 0.728) passes; BBOX (no step), MINDACORP, factors above 0.8 and a Yahoo factor of 1.0 do not. Events with factor above 0.8 stay `OTHER` unless Yahoo confirms them (STRONG) and are on the unadjusted-event list.

| Tier | All events | ADTV-eligible equity names |
|---|---|---|
| STRONG | 477 | 353 |
| WEAK | 335 | 248 |
| WEAK_DIRECTIONAL | 58 | 31 |
| UNSUPPORTED (stored `OTHER`) | 259 | 158 |
| **Total** | **1,129** | 790 |

Supported (price-moving) events: **870 = 77%** (was 754). The 259 unsupported: 196 are before staging starts (2013-01-01), 10 after 2026-09-30, 7 have no usable rows even across a gap, and **46 have price data that does not fit** (13 with factor above 0.8, 33 with a lower factor and no matching step, e.g. DVL, BBOX, MINDACORP, RAJRATAN, SUMEETINDS).

**Events with no EQ rows around the ex-date (95 before, 7 now).** Evidence now uses the ratio across the gap (last close before the ex-date vs first close after, up to 800 days, Yahoo factor on the same two dates where available): 76 events use this basis: **50 STRONG, 8 WEAK, 3 WEAK_DIRECTIONAL, 15 UNSUPPORTED**. An unadjusted split at a re-entry would otherwise create a false step, as the reviewer said.

## 2. Events vs rows (the reconciliation the reviewer asked for)
An event is one (symbol, ex-date). A same-day split + bonus is one event and two rows, so rows exceed events by 45 for the supported events.

| Tier | Events | BONUS rows | SPLIT rows | Rows |
|---|---|---|---|---|
| STRONG | 477 | 250 | 253 | 503 |
| WEAK | 335 | 168 | 182 | 350 |
| WEAK_DIRECTIONAL | 58 | 45 | 17 | 62 |
| UNSUPPORTED | 259 | 142 | 137 | 279 |
| **Total** | **1,129** | 605 | 589 | **1,194** |

Supported: 870 events = **915 rows (SPLIT 452 + BONUS 463)**. The earlier "754 events vs SPLIT 403 + BONUS 384 = 787 rows" was the old rule (and the old parser); the same-day pairs account for the events-to-rows difference both times.

Rows by stored type (parsed from the feed → surviving `UNIQUE(symbol, ex_date, action_type)` with `INSERT OR IGNORE`): SPLIT 452 → 452, BONUS 463 → 463, RIGHTS 341 → 341, DEMERGER 108 → 108, MERGER 91 → 91, DIVIDEND 20,913 → 20,913, **OTHER 650 → 630 (20 collapse: two OTHER rows on one symbol and date, e.g. an unsupported split and an unsupported bonus on the same day)**; total 23,018 → 22,998. The collapsed notes would be lost; I propose to concatenate the notes of colliding OTHER rows before the load. Tier and evidence travel in `evidence_tier` / `evidence`.

## 3. Rename with ISIN change at a split
Rule implemented as approved (`scripts/f2_split_rename_links.py`, 3 tests): link only when a split on the new symbol falls within 3 days of the boundary **and** its factor reproduces the price step (tier WEAK/WEAK_DIRECTIONAL), ISINs differ, candidate unique, price continuity alone never links. **Result: 0 qualifying pairs.** Only 5 events in the whole feed have a symbol that begins trading within 10 days of its own ex-date, and all are new listings with no predecessor. So no lake relabelling was needed. (The keying issue in section 0.2 is a different case: same company, gap between the names, no split at the boundary.)

## 4. Post-adjustment scan of large moves (eligible equity names, price ≥ ₹5, |move| > 40%, lake 2013-01-01..2026-09-30)
Events applied: 870 (STRONG + WEAK + WEAK_DIRECTIONAL), on the first session on or after the ex-date, 1,607 names scanned.

| | Moves |
|---|---|
| Before adjustment | 764 |
| After adjustment | **267** |
| Removed by adjusting | 499 |
| Created by adjusting | 2 |

Remaining 267: **209 after a gap in the EQ series** (the previous close is weeks to years old), **40 within 30 days of an unadjusted event** (demerger, merger, rights, unsupported), **18 with no explanation in the data**. The 18: YESBANK ×3, INDUSINDBK, SIGMAADV (all in section 5), AURUM = the lake name of MAJESCO (reviewer's unadjusted event), plus 63MOONS 2013-08-01, AMTEKAUTO 2015, CCAVENUE 2018-09-28, COREEDUTEC ×2 2013, DHFL 2018, EMBDL 2017, JETAIRWAYS ×2 2019, PCJEWELLER 2018, PNB 2017, RCOM 2018: no corporate action in the feed, large volume surges in the triage (13 REAL_MOVE dispositions), distressed or news-driven names.
**The 2 created:** DOLPHIN 2024-04-15 (adjusted +1,240%, raw +34%) and MBAPL 2023-02-06 (adjusted +81%, raw −9%). Both are first rows after 222- and 255-day gaps with a Yahoo-confirmed split/bonus inside the gap (factors 0.1000 and 0.4997 against the logged 0.1 and 0.5), so the adjusted move is the real price change over the gap, not an adjustment error; DOLPHIN's size is worth a manual look.
List: `docs/data_audit/post_adjustment_large_moves.csv`.

## 5. The nine dispositions (evidence in `docs/data_audit/manual_move_dispositions.csv`)
| Move | Disposition | Evidence |
|---|---|---|
| STAR 2013-12-19 (−57.6%) | UNADJUSTED_EVENT (reviewer) | On the unadjusted-event list. Nifty −0.3% that day; no feed row. |
| YESBANK 2020-03-16 (+45.2%) | REAL, stock-specific | Nifty −7.6%, universe median −5.3%, sector peers −6.2%: the stock moved against the market. Part of a cluster with 2020-03-06 (−56%) and 2020-03-17 (+58%) in the same stock, volume surge, price level persists; no corporate action in the feed. |
| YESBANK 2020-03-17 (+58.1%) | REAL, stock-specific | Same cluster; Nifty −2.5%, universe median −2.0%. |
| INDUSINDBK 2020-03-26 (+44.7%) | REAL market stress (provisional) | Same direction as the market: Nifty +3.9%, eligible-universe median +4.0%, 64 sector peers +4.5%. The stock's move is about 11× the market's; it fell from 804 to 301 in the preceding 8 sessions, and the new level persists (411–413 over the next days). Left provisional. |
| MAJESCO 2020-12-23 (−98.8%) | UNADJUSTED_EVENT (reviewer) | On the list. Volume ×0.1 and the price falls to 1.2% of the previous close; lake name AURUM. |
| SIGMAADV 2026-05-25 (+47.7%) | REAL, across a gap | The previous EQ-series row is 2026-04-27 (28 days earlier); Nifty +1.3%, universe median +1.0%; no sector peers in `sector_map.csv`. |
| PGIL 2024-01-20 (−56.9%) | Artefact of re-entry | First EQ row after 92 days and it is the Saturday special session: volume 9,534 vs 40,243 on the last pre-gap row (2023-10-20, close 1,404.20). The 2024-01-05 split sits inside the gap; the "move" is the gap. The reviewer's 2024-01-22 date was the stale stamp. |
| JYOTISTRUC 2024-01-20 (+232%) | Artefact of re-entry | First EQ row after 2,124 days (previous row 2018-03-28), re-entry on the special session. |
| SCHNEIDER 2024-05-18 (+59%) | Artefact of re-entry | First EQ row after 93 days (previous 2024-02-15), re-entry on the special session; 2024-05-20 was the stale stamp. |

Your hypothesis about a thin special-session print as the *previous close* did not apply to these three (the previous row is months old). But all three re-enter the EQ series on a thin special-session print, which matters for the strategy specification: **a special session (Saturday/Muhurat) should not be the first bar of a name's history in the engine's calendar.**

## 6. Approved items to implement (not yet done, none changes the load)
- **ETFs/funds:** exclude INF-prefixed ISINs from the equity universe (63 eligible symbols). To do in the universe step.
- **Listing date:** derive from the first raw trading day; `securities_master` stays untouched; symbols present on 2013-01-01 are treated as already seasoned. To do with the universe/listing-age change; will be implemented with a test, not by editing the table.

## 7. What I need from the reviewer before Step 7
1. Approval of the load with the revised tiers: **915 price-moving rows (870 events), 630 OTHER, 341 RIGHTS, 108 DEMERGER, 91 MERGER, 20,913 DIVIDEND** (22,998 after the unique key, with the OTHER-notes merge).
2. Confirmation of the keying decision: `symbol` in `corporate_actions_log` = `lake_symbol` (symbol holding the pre-ex-date prices); feed symbol in the notes.
3. The 46 unsupported events that have price data (33 with factor ≤ 0.8 and no matching step, 13 with factor above 0.8) stay `OTHER`. Those on ADTV-eligible names go on the unadjusted-event list (268 entries in total: 105 large rights, 83 demergers, 57 mergers, 21 unsupported price rows, 2 manual): OK?
4. INDUSINDBK left provisional: accept or ask for more evidence?
5. **Merge the notes of colliding `OTHER` rows** (20 rows would otherwise lose their note under `INSERT OR IGNORE`): OK to concatenate them before the load?
6. **DOLPHIN 2024-04-15** (adjusted +1,240% over a 222-day gap, split confirmed by Yahoo at 0.1000): I will look at it manually before the load unless you say the Yahoo confirmation is enough.
7. **Special sessions in the engine calendar (strategy specification, not the load):** three names re-enter the EQ series on a Saturday special-session print, and special sessions are thin. Whether the engine's calendar counts them as trading days is still open from your earlier note; I will raise it again in the specification.
