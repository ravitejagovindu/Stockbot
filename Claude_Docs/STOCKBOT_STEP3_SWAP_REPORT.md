# StockBot — Step 3: swap and post-swap checks (2026-11-07)

**The swap has run on the real `finsight.db`.** Rehearsed first on a scratch copy (deleted afterwards; not a backup). Three separate transactions, in the reviewer's order: schema, swap, symbol mapping. Logs: `docs/data_audit/real_swap_run_log.txt`, `post_swap_report_real.md` (rehearsal report alongside). Backup `finsight_pre_F2_2026-11-06.db` verified (sha256 `d531af5d…016e`, quick_check ok) immediately before the swap.

## 1. Schema (transaction 1)
Lake gets `source`, `loaded_at`, `source_symbol`; table `market_data_lake_yahoo_archive`; F3 columns on `active_positions` and `trade_analytics_log`; `corporate_actions_log` rebuilt (it was empty) with CHECK allowing DEMERGER and OTHER plus `source`, `loaded_at`, `evidence_tier`, `evidence`. NULL `source` = row from before F2; NULL `source_symbol` = symbol is the traded symbol.

## 2. Swap (transaction 2)
| Item | Rows |
|---|---|
| Yahoo rows 2020-01-01..2026-09-30 archived, then removed (equities) | 2,829,905 |
| Raw Bhavcopy rows inserted for that window (= staging, per year equal) | 3,110,289 |
| Pre-2020 special-session rows inserted (append-only, six dates) | 8,034 |
| Nifty / VIX session gaps filled, labelled | 51 (39 NSE index file, 12 Yahoo fallback: 2 Nifty, 10 VIX, NSE had no file for those dates; cross-checked on 2 overlapping dates, owner accepted) |

Untouched, checksum identical before and after (count + sha256 of symbol/date/OHLCV): pre-2020 existing rows 2,483,109; rows after 2026-09-30 29,529; existing Nifty/VIX rows 5,736. Rows from 2026-10-01 onward and the index series were not modified.

## 3. Symbol mapping (transaction 3)
380 segments of 334 pure-rename ISINs relabelled, **353,088 rows**, `source_symbol` keeps the traded symbol. Whole-lake row count 5,634,334 before and after; checksum over (source_symbol-or-symbol, date, OHLCV) identical; 0 duplicate (symbol, date) pairs; 0 rows left under a renamed traded symbol. Map stored in table `isin_symbol_map`.

## 4. Post-swap checks
- Rows / trading days per year equal staging for 2013..2026-09-30 (e.g. 2020: 379,782 / 252; 2025: 531,765 / 249). Symbols per year 1,587 (2013) to 2,931 (2026), delisted names included.
- Continuity 2019-12-31 -> 2020-01-01: RELIANCE 0.997, HDFCBANK 1.005, KOTAKBANK 0.994; of 1,499 symbols present on both sides none moved more than 25%.
- Nifty and VIX: no equity session date lacks an index row.
- Calendar / copy data tests on the real database: 3 passed. Pure suite: 263 passed, 3 skipped (the data tests without the env var).
- Volume units across the Bhavcopy format change: median after/before ratio 0.96 (controls 0.83-1.03).

## 5. Finding for the reviewer (existing data problem, not changed)
`securities_master.listing_date` holds placeholder dates (2026-04-20 .. 2026-10-01) for many symbols (351 are exactly 2026-10-01); 115 of the 334 renamed names are affected, 38 have no master row (the gate then uses the first lake date, now longer), 3 have a real listing date later than the lake start. The listing-age gate would call the placeholder names too young at every historical date. Mostly ETFs and odd symbols; I will count how many are ADTV-eligible in Step 5 and propose a fix (derive listing date from first raw trading date) for approval. `securities_master` is untouched.

Next: Step 4 remainder (tiers, tightened by the reviewer's closer-than-any-standard-ratio rule, DVL window check, old-symbol queries), Step 5, Step 6. STOP A still applies.
