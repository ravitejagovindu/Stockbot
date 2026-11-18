# Corporate actions: the 85 "differs, not applied" events (analysis only)

Run date 2026-11-18, branch `ca-differences`, base 6afd0ad. Nothing in `finsight.db` or any strategy/ledger/result was touched (read-only `open_lake` only).

## Summary
| Class | Count |
|---|---|
| HARMLESS (wording/formatting only) | **85** |
| RATIO | 0 |
| DATE | 0 |
| OTHER | 0 |
| **Total differing** | **85** (equals the daily job's 85) |

- **How many matter: none.** In all 85 events ratio numerator/denominator and ex-date are identical. The only difference is the stored `notes` text: every stored row has the prefix `feed_symbol=<SYM>; ` in front of the fetched text (checked mechanically for all 85: `stored_notes == "feed_symbol=" + symbol + "; " + fetched_notes`).
- Cause: the 85 stored rows were loaded earlier by `f2_load_corporate_actions.py` (source `NSE corporates-corporateActions API (F2 Step 7)`, evidence tier `NOT_PRICE_MOVING`), which writes that prefix. The daily job's parser writes the bare subject. The job compares `notes` exactly (`split_new(..., ("ratio_numerator","ratio_denominator","notes"))`), so these show as "different" on every run. Types: 81 DIVIDEND, 3 OTHER (Buy Back), 1 RIGHTS (SUVIDHAA 3:8, ex 2026-11-04, ratio equal).
- **Could any registered run be affected: NO.** Evidence: (a) earliest differing ex-date is 2026-10-21, after the 2026-10-16 end of the registered-run window, so the step-5 table is empty; (b) no ratio or date differs; (c) the adjustment code only uses SPLIT/BONUS (see step 6), and the one RIGHTS row has equal ratios in both versions. No result was recomputed.

## Method (what the job does, reproduced exactly)
- Fetch: `daily_update.default_ca_fetch(date(2026,10,17), today+45d)` = `https://www.nseindia.com/api/corporates-corporateActions?index=equities&from_date=17-10-2026&to_date=02-01-2027`. 219 raw rows, saved UNMODIFIED to `F:\Projects\Ravi\StockBotData\raw_corporate_actions\ca_2026-11-18.json`. No block from NSE.
- Parse: `nse_corporate_actions_history._parse_ex` + `parse_subject` (205 action records; 14 raw rows give no action; 0 unresolved).
- Compare: `guard.writers.split_new`, key `(symbol, ex_date, action_type)`, values `(ratio_numerator, ratio_denominator, notes)`, the same function and columns as `load_corporate_actions`.
- Result now: 205 records = 119 identical + 85 differ + **1 new** (ALUFLUOR, DIVIDEND, ex 2026-11-20, "Interim Dividend - Rs 2.50 Per Share": announced since the job ran; not inserted by this analysis). The 119 identical are the 119 the job inserted.
- Stored `corporate_actions_log` has no ISIN or record-date column; ISIN and record date in the CSV come from the fetched row (`recDate` equals ex-date in the sample checked). So a DATE difference cannot show up through this key.

Full list: `docs/data_audit/ca_differences_2026-11-18.csv` (symbol, ISIN, ex-date, type, all stored columns, fetched columns, differing columns, class, reason). Scripts: `docs/data_audit/ca_differences_fetch.py`, `ca_differences_compare.py`.

## Step 4: RATIO/DATE rows with ex-date on or before today
None (0 RATIO, 0 DATE). No price check was needed; bhavcopy and lake were not consulted.

## Step 5: differing events with ex-date on or before 2026-10-16 (registered-run window)
| Stock | Stored | Fetched | Registered runs could trade it? |
|---|---|---|---|
| (none) | | | Earliest differing ex-date is 2026-10-21, latest 2026-11-06. No `results_run1` trades.json lookup was required. |

## Step 6: differing events with ex-date after today (2026-11-18)
None of the 85 (latest 2026-11-06). For information, the log already holds 16 future-dated rows (ex 2026-11-19 to 2026-11-27, all inserted by the daily job, none differing; one is a SPLIT, VGL 2:5 on 2026-11-27, and one a RIGHTS, SMLMAH 2:7 on 2026-11-20), plus the not-yet-inserted ALUFLUOR.

What the engine does with a future ex-date (exact behaviour, from code):
- `stockbot/data/asof.py` `corporate_actions` / `_corporate_actions_physical` / `_feed_actions_physical`: SQL `where ex_date<=?` with the as-of date. Future rows are not returned. The in-memory twin `asof_memory.py` filters `ex <= lim` the same way.
- `stockbot/data/adjustments.py`: `get_adjusted_series` / the factor code skips `ex > as_of_date` ("future event, not known yet"); and `DIVIDEND`/other types get factor 1.0 (only SPLIT and BONUS scale prices). Rights are not applied as a factor either.
- Unfiltered readers (`data_catalogue.py` counts `actions_after_last_session`; nothing trading-related) only count them. Nothing reads future rows for trading decisions.
- `notes` is read only for the `feed_symbol=<NAME>;` prefix (`asof.py` `_feed_actions_physical`, `asof_memory.feed_actions`), which attaches an action filed under another symbol to a linked stock. The prefix is therefore functional for such stocks; the 85 stored rows keep it, which is another reason not to overwrite notes.

## Step 7: Recommendation (not done)
- **No event needs `guard correct` or a new insert.** All 85 are formatting differences in an informational column; the stored versions are the better ones (prefix needed for the linked-stock lookup; all tier NOT_PRICE_MOVING).
- A `guard correct` would be wrong here: it needs a reason, a SQL file, one transaction, bumps the correction counter and makes every open run INVALID (R3). A new insert is impossible for these keys: INSERT_ONLY refuses an insert that would replace a row with different values (R2).
- The real issue is the recurring false report: each daily run will report these 85 again. A code change (not done, needs an owner decision) would be to compare `notes` after stripping a leading `feed_symbol=<SYM>; ` (or drop `notes` from the compared value columns), so only ratio changes are flagged. That is a change to `daily_update.py`, not to data.
- ALUFLUOR (ex 2026-11-20) will be inserted by the next daily run; no action needed.

## What ran and what did not
Ran: git checks, branch creation, NSE fetch (success, 219 rows), comparison with the job's own `split_new`, read-only queries of the stored rows and of future-dated rows, code reading of the engine. Did not run: the bhavcopy/lake price-move check (no RATIO/DATE rows), the `results_run1 trades.json` lookup (no pre-2026-10-17 rows), any recomputation, backtest, guard command or database write.
