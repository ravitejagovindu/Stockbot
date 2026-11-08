# Earnings history collection (Step 12, KI-004)

Collected 2026-11-08 from `api/corporates-financial-results` and `api/corporate-board-meetings` only, by `scripts/collect_earnings_history.py` (0.6 s delay, one retry, stop after 8 consecutive failures; no 403 or 429: 6,476 stored responses, all HTTP 200; one request failed with a network error and succeeded on the re-run). Raw responses (zlib-compressed JSON, lossless) and parsed rows are in NEW tables; no existing table changed; not wired into any backtest. Pre-step backup `Backups\finsight_pre_step12_2026-11-08.db` (sha256 verified, integrity_check ok).

| table | rows |
|---|---|
| earnings_results_filing | 173,410 (period Quarterly; to_date 2005-02-28..2024-12-31) |
| earnings_board_meeting | 164,819 (145,035 classified as results meetings: 123,261 by purpose text, 21,774 by description text; meeting dates 2012-01..2026-11) |
| earnings_symbol_map | 3,258 (3,238 distinct query symbols: lake symbol, plus the canonical symbol where `isin_symbol_map` has a pure rename) |

## Findings that change how it may be used
1. **The financial-results API ends in January 2025.** No filing with period end after 2024-12-31 exists for any symbol (INFY with a 2025+ date range returns only the Dec-2024 quarter). For 2025 and 2026 only board-meeting rows exist (99.5% and 96.3% of symbol-years).
2. **`broadcast_ts` is not the announcement date.** It is when the filing (often the XBRL) was disseminated. Comparing it with the results board-meeting date (nearest meeting, same symbol), share within 3 days, by broadcast year: 2013 36%, 2014 31%, 2015 65%, 2016 46%, 2017 30%, 2018 6%, 2019 61%, 2020 81%, 2021-2025 94-97%. Example: INFY Q4 FY18 — meeting 13-Apr-2018, filing timestamp 8-Jun-2018. Banks lag by a day even now (HDFCBANK Q3 FY25: meeting 22-Jan-2025, timestamp 23-Jan 12:25). **Use the results board-meeting date as the announcement date; keep broadcast_ts only as a secondary field.**
3. **Intimation lead time (the "known ahead" date).** Results meetings: median 9 days between `bm_timestamp` (intimation) and the meeting, 5th percentile 4 days; 84% have >= 7 days. By year the share with >= 7 days is 91-96% for 2012-2019, 78% in 2020, 87-90% in 2021-2023, 83% in 2024, 71% in 2025, 67% in 2026. 0.09% of intimations are timestamped after the meeting date. A strict "known 7 days ahead" rule therefore excludes a growing minority in recent years.
4. Multiple rows per event: standalone and consolidated filings, and several board-meeting rows for the same meeting (intimation, outcome, different purpose texts). Dedupe on (symbol, bm_date) before use. Postponed meetings appear as separate rows.

## Coverage by year (lake symbol-years with >= 100 sessions, non-fund; `docs/data_audit/earnings_coverage_by_year.csv`)
| year | symbol-years | results filing | results meeting | with intimation ts | either |
|---|---|---|---|---|---|
| 2013 | 1,397 | 96.4% | 96.7% | 96.7% | 96.8% |
| 2015 | 1,425 | 96.4% | 96.7% | 96.7% | 96.7% |
| 2017 | 1,497 | 96.9% | 97.3% | 97.3% | 97.3% |
| 2019 | 1,491 | 97.1% | 97.5% | 97.5% | 97.6% |
| 2020 | 1,513 | 96.4% | 96.8% | 96.8% | 96.9% |
| 2022 | 1,721 | 96.4% | 96.9% | 96.9% | 97.0% |
| 2023 | 1,759 | 97.3% | 97.7% | 97.7% | 97.7% |
| 2024 | 1,783 | 98.7% | 99.2% | 99.2% | 99.2% |
| 2025 | 1,999 | 0.0% | 99.5% | 99.5% | 99.5% |
| 2026 | 2,217 | 0.0% | 96.3% | 96.3% | 96.3% |
(all years in the CSV.) "Has a row" is not "has every quarter": per-quarter completeness was not measured.

## Names with no data
145 of 2,900 lake symbols (5.0%) returned empty (HTTP 200, 0 rows) from both APIs (`docs/data_audit/earnings_no_data_symbols.csv`, with first/last active year). By last active year: 2013-2022 3-8 each, 2023 15, 2024 6, 2025 4, **2026 72**. The 2026 group includes liquid names that are certainly listed (MCX, HEG, GUJGASLTD, ICICIPRULI, GOODYEAR, ELANTAS); a re-query of MCX, HEG, GUJGASLTD, ICICIPRULI returned 0 rows again, so the empties are stable, not transient. The cause is not known (the API's own symbol coverage). TATAMOTORS (renamed after the 2025 demerger) is in the list because `isin_symbol_map` does not link it to its successor.

## Validation against filings (10 symbols)
Board-meeting date in the table vs an outside source. Web-confirmed in this session (public news and company filings found by search): ETERNAL (ex-ZOMATO) Q1 FY25 results 1-Aug-2024 = table 2024-08-01; HDFCBANK Q3 FY25 22-Jan-2025 = table 2025-01-22 (timestamp 23-Jan); **HDFC Ltd (delisted 2023)** Q4 FY23 4-May-2023 = table 2023-05-04; **MINDTREE (merged into LTIMindtree 2022)** Q4 FY22 18-Apr-2022 = table 2022-04-18; BAJFINANCE Q4 FY24 25-Apr-2024 = table 2024-04-25; ITC Q4 FY24 23-May-2024 = table 2024-05-23; SUZLON Q4 FY24 24-May-2024 = table 2024-05-24. All 7 match. Three more matched against widely published dates from memory, NOT re-fetched: INFY (13-Apr-2018, 11-Jan-2019, 16-Jan-2025), TCS (19-Apr-2018, 9-Jan-2025), RELIANCE (16-Jan-2025). Limit: 10 symbols, mostly large; no small-cap was checked externally. The check covers the meeting date; broadcast_ts correctness is shown by finding 2 above.
Renamed-name handling: HDFC and MINDTREE return history under their old symbols; ZOMATO under its old symbol returns nothing (history is under ETERNAL since the rename), which is why the join relies on the lake's own symbol set plus ISIN.

Reproduce: `py scripts/earnings_coverage.py`, `py scripts/earnings_validate.py INFY TCS ...`.
