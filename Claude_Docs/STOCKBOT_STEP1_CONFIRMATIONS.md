# StockBot — Step 1 confirmations (written 2026-11-07) — STOPPED: two unexpected results

Per the reviewer's rule ("if any answer is unexpected, stop and ask"), I have **not** started Step 2 (swap script) or anything after it. Nothing in `market_data_lake` or `corporate_actions_log` has changed. Only read-only queries were run.

## Result 1 — The "8,903 missing 2019 rows" are exchange-holiday copies, not real data (UNEXPECTED)

**Which dates and symbols.** 8,903 rows on 6 dates, covering 1,470–1,505 symbols per date:

| Date | Rows | Symbols | What the date was |
|---|---|---|---|
| 2019-10-02 | 1,484 | 1,484 | Gandhi Jayanti (NSE closed) |
| 2019-10-08 | 1,488 | 1,488 | Dussehra (NSE closed) |
| 2019-10-21 | 1,486 | 1,486 | Maharashtra election (NSE closed) |
| 2019-10-28 | 1,470 | 1,470 | Diwali Balipratipada (NSE closed) |
| 2019-11-12 | 1,470 | 1,470 | Guru Nanak Jayanti (NSE closed) |
| 2019-12-25 | 1,505 | 1,505 | Christmas (NSE closed) |

The lake correctly has no rows on these dates. **Staging has them because my ingester wrongly accepted a file on a holiday.** For 2019-10-02, 2019-10-08 and 2019-12-25 I compared row by row with the previous session: **every symbol has exactly the same close and the same volume as the day before.** These are not new trading days.

**Root cause.** `scripts/ingest_raw_bhavcopy_range.py::fetch_day` stamps the *requested* date on whatever file the NSE archive returns. It never checks the date inside the file. On some holidays the archive returns the previous session's file instead of a 404.

**Extent (staging dates that are absent from the lake, 2013-01-01 … 2026-09-30): 80.**
- 76 are exact row-for-row copies of the previous session (all closes and volumes equal, 100%).
- 4 are not copies of the previous or next session (2019-10-28, 2020-11-16, 2024-01-22, 2024-05-20). All four were exchange holidays; the file returned for them seems to be some other day's file. I have not yet identified which.
- 5 more dates **that are also in the lake** are exact copies of the previous session and are also exchange holidays: 2026-01-15, 2026-05-01, 2026-05-28, 2026-06-26, 2026-09-14. So the current lake also carries some holiday rows (from the earlier Yahoo/raw load).
- The 80 dates run from 2019-10-02 to 2026-04-14 (the first 6 are the table above; the rest are holidays in 2020–2026 such as 2020-04-02, 2022-01-26, 2023-12-25, 2024-01-26, 2026-03-31). I will save the full list as a CSV with the fix.

**Consequence if not fixed.** The swap would insert about 80 phantom sessions × ~1,500–2,600 symbols. They would add zero-return days, distort ATR, moving averages, ADTV and gaps, and count as trading days in every window.

**Proposed fix (needs your approval because it changes staging):**
1. Ingester: read the date inside each file (legacy `TIMESTAMP`, UDiFF `TradDt`) and reject the file if it differs from the requested date; log such days as `HOLIDAY_OR_MISSING`. Add a unit test that fails on the current code (a holiday served with the previous day's file).
2. Staging: delete the rows of every date where the in-file date disagrees with the requested date (the 80 above, confirmed by re-fetching their files). Staging is my own table; this does not touch the lake.
3. Re-run the staging validation, then report the corrected counts.
4. Separately, decide what to do with the 5 holiday copies already in the lake (2026-01-15, 05-01, 05-28, 06-26, 09-14): replace them as part of the swap by removing them (they sit inside 2020-01-01 … 2026-09-30, so the archive step would remove them anyway; the raw load would then simply not insert them).
5. Real sessions the lake has but staging lacks: **2020-11-14** (Muhurat, Saturday) and **2025-02-01** (Budget Saturday). My range loop skipped weekends. I propose to fetch these two dates (and the other special weekend/holiday sessions I find) explicitly.

## Result 2 — The 399 renamed ISINs: the swap, as I would have written it, would break histories (UNEXPECTED)

**How the lake is built today.** For 2013–2019 the lake stores the symbol *as traded on the day* (identical to staging). For 2020 onwards the Yahoo-sourced rows sit under the **current** symbol for the full 2020+ history. Examples (lake / staging):

| Name | Lake | Staging (raw) |
|---|---|---|
| ZYDUSLIFE (was CADILAHC until 2022-03-04) | 2020-01-01 … 2026-10-16, 1,687 rows | 2022-03-07 … 2026-09-30, 1,181 rows |
| CADILAHC | 2013-01-01 … 2019-12-31 | 2013-01-01 … 2022-03-04 |
| TMPV (was TATAMOTORS until 2025-10-23) | 2020-01-01 … 2026-10-16, 1,687 rows | 2025-10-24 … 2026-09-30, 244 rows |
| TATAMOTORS | 2013-01-01 … 2019-12-31 | 2013-01-01 … 2025-10-23 |
| HEALTHX (was SASTASUNDR until 2026-04-29) | 2020-01-01 … 2026-10-16 | 2026-04-30 … 2026-09-30, 110 rows |

Of the 399 ISINs with more than one symbol: in 279 both symbols are in the lake, in 110 only one is, in 10 neither. In 28 of the 110 the lake history is already stitched backward by Yahoo.

**What a straight swap does.** Archive the lake's 2020+ rows and insert staged rows under the symbol traded on the day. ZYDUSLIFE would lose 2020-01 … 2022-03-06 (it moves to CADILAHC), TMPV would lose everything before 2025-10-24, and so on. The affected names then appear to have very short histories and fall out of the universe screens (listing age, 252-day features) *because of a rename*. That would be a new survivorship distortion, in the opposite direction.

**Options (your decision):**
- **A. Canonical symbol via ISIN, applied to staged rows at the swap.** Keep the traded symbol in a new column (`source_symbol`) and write the latest symbol of the same ISIN into `symbol` for pure renames (same ISIN, no demerger/merger flag). Histories stay continuous, like today's 2020+ lake. Raw prices are untouched. Exclusions: pairs that are a demerger or merger (TATAMOTORS → TMPV is a demerger and the price steps), which stay split until their corporate action is loaded and reviewed (STOP A).
- **B. Keep traded-day symbols and add an alias table** (`symbol_aliases`: old → new, valid-from/to) that the engine reads. More code in `engine_core`; histories remain split in the table.
- **C. Keep split histories** and list them. Simple, but it silently shortens histories of renamed names.

**Recommendation: A**, with an explicit exclusion list (demergers, mergers, ISIN changes without a shared ISIN) and a report of exactly which histories remain split and why (that is the reviewer's own condition 2). It needs one new column and one deterministic mapping that I can verify against the 110 + 279 + 10 groups.

## Result 3 — ADTV uses Bhavcopy traded quantity (CONFIRMED, as expected)

- `scripts/ingest_raw_bhavcopy_range.py::parse_bhavcopy` maps `volume_raw` from `TtlTradgVol` (UDiFF) / `TTL_TRD_QNTY` (legacy) = total traded quantity of the EQ series.
- `engine_core/universe_screener.py` computes ADTV as `compute_adtv(raw_ohlcv["close_raw"], raw_ohlcv["volume_raw"], period=adtv_sma_period)` from `market_data_lake` (`_fetch_ohlcv`); `engine_core/adjustments.py::compute_adtv` documents "raw prices only" and "must always use raw volume". After the swap, `volume_raw` is the Bhavcopy quantity.
- Not yet done: the grep-style test (reviewer's 4.8) that ADTV and market cap never read adjusted columns. It comes with Step 7.

## What I need from you before continuing
1. Approve the ingester fix and staging clean-up (Result 1, items 1–3 and 5), and the handling of the 5 holiday copies already in the lake (item 4).
2. Choose A, B or C for renamed ISINs (Result 2). I recommend A.

Steps 4–6 (corporate-action parser fixes, evidence tiers, eligible symbols, verification list) do not depend on these two answers, except that eligibility counts need the cleaned staging data. I will start with the parser fixes (Step 4, first bullet) and the tier definitions while you review, unless you say otherwise.
