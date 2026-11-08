# F8 prerequisites — feasibility (historical ASM/GSM lists and earnings history)

Date 2026-11-08. Nothing was loaded and nothing was scraped. Evidence: the repo as it stands, four read-only probes of NSE pages from this machine (one request each, no loop), two static circular PDFs downloaded to a scratch folder, and web searches. Probe results are marked **tested**; anything else is **not tested** and is stated as such.

## What exists in the repo today
- `backtest/bifurcated_scraper/asm_gsm_pdf_scraper.py`: a stub. `fetch_circular_index` returns `[]`, `extract_symbols_from_pdf` returns `[]`; `build_surveillance_timeline` writes a template with `status = PENDING` for every candidate symbol.
- `backtest/bifurcated_scraper/earnings_scraper.py`: calls the NSE **corporate-actions** API and keeps rows whose purpose mentions results/financial/**dividend**, using the **ex-date**. An ex-date is not a results date, so this does not produce earnings history.
- Outputs on disk: `backtest/outputs/pending_asm_gsm_matches_{bull_run,sideways_inflation}.csv` (PENDING templates, no VERIFIED rows); no `historical_earnings_*.csv` at all.
- `backtest/exclusions.py` `Exclusions.load` is fail-closed: Pass 2 (compliant) refuses to run without verified ASM/GSM rows and a non-empty earnings file (unless `--allow-unverified`). So today no compliant (Pass 2) backtest can run, and any Pass 1 result ignores both exclusions.
- Scraping was moved out of the backtest runner in this step (`scripts/run_surveillance_scrapers.py`), and a backtest now raises on any network call.

## 1. Historical ASM / GSM lists
| question | answer |
|---|---|
| Official source | NSE surveillance circulars (static PDFs at `nsearchives.nseindia.com/content/circulars/SURV<number>.pdf`). GSM: framework circular NSE/SURV/34262 of 23-Feb-2017, in force 14-Mar-2017; further circulars list securities moving to or out of each stage with an effective date (e.g. NSE/SURV/74577, 5-Jun-2026). ASM: published as lists/circulars on the same surveillance page. BSE publishes its own ASM/GSM notices (**not tested**). |
| Date range that can be covered | GSM from March 2017; ASM from its introduction (the exact first date was **not confirmed**). Both to today. |
| Format | PDF, text-extractable. **Tested:** `SURV34262.pdf` (4 pages) and `SURV74577.pdf` (2 pages) both download (HTTP 200) and parse with `pdfplumber`; the list is a table `Sr. No | Symbol | Security Name | ISIN` plus an effective date and stage in the text. Stage tables are in the PDF too. |
| Live endpoint | **Tested:** `api/reportASM` (130 long-term + 49 short-term rows today, with stage and `asmTime`) and `api/reportGSM` (76 rows, with `gsmStage`, `gsmTime`, ISIN) answer HTTP 200 from here. **They are current snapshots only:** a request with `date=01-01-2020` returned the identical response. So history cannot come from these endpoints. |
| Blocker for history | The circular numbers are not sequential and the circular **index** is a dynamic page (not fetched). The GSM FAQ (April 2025) contains a table of list-update circular numbers up to March 2025 and each new circular cites its predecessors, so a chain can be followed, but ASM has no such table that I found. Enumerating numbers blindly would be scraping and was not done. |
| What we can get from here | (a) A **forward** archive starting today: snapshot `reportASM` and `reportGSM` daily from now on (legitimate, small, gives clean point-in-time data from the day it starts). (b) GSM history by following the circular chain from the FAQ table (PDF parsing, manual verification of each effective date, because the entries have effective dates and removals are separate circulars). (c) Any file you supply. |
| What a user-supplied file should look like | `symbol, isin, framework (ASM_LT / ASM_ST / GSM), stage, start_date, end_date` (end blank if still on). Sources that could produce it: NSE/BSE data subscription, a broker back-office report, a data vendor. |
| Risk | Reconstructing from circulars gives start dates but removals/stage moves are in separate notices; an error silently leaves a name flagged or unflagged. This is why `Exclusions.load` insists on VERIFIED rows. |
| What it blocks | Pass 2 (compliant) backtests of any strategy; the live ASM/GSM entry block is the only place the screener is allowed to depend on it. Not needed for the data gate itself. |

## 2. Earnings (results announcement) history
| question | answer |
|---|---|
| Needed | For each symbol and quarter: the date results were announced, and the date the board meeting was announced (what live could have known 7 days ahead, `earnings.known_ahead_days`). |
| Source 1: NSE financial results API | **Tested** (one request, INFY): `api/corporates-financial-results?index=equities&symbol=INFY&period=Quarterly` answers 200 with 144 rows reaching back to 2005. Fields include `filingDate`, `broadCastDate` (exchange dissemination timestamp to the second), `fromDate`/`toDate` of the period, `audited`, `consolidated`, ISIN. Broadcast timestamps are point-in-time results dates. |
| Source 2: NSE board meetings API | **Tested** (INFY): `api/corporate-board-meetings?index=equities&symbol=INFY` returns 20 rows (recent and upcoming, with `bm_date`, `bm_purpose`, `bm_desc`, intimation timestamp `bm_timestamp`); with `from_date=01-01-2018&to_date=31-12-2019` it returned 9 rows, so a date range works. The intimation timestamp gives the "known ahead" date. |
| Access | Same cookie-session method already used for the corporate-actions dump (this machine could fetch both; `api/quote-equity` returned 403 in F2b, so not every endpoint is open). One symbol per request. About 2 requests per symbol; at the 0.6 s politeness delay about 40 minutes for ~2,000 symbols. **Not run.** |
| Date range | Results API: back to 2005 for INFY (older entries may be sparse in format); lake starts 2013. Board-meeting history depth was only spot-checked for 2018-2019. |
| Gaps | Delisted/renamed symbols: the query is by current symbol, so names that left before the API's symbol master may return nothing (**not tested**); the lake's canonical symbols need mapping to the API's symbol. Meeting purposes must be filtered to results meetings (text match on `bm_purpose`/`bm_desc`). Board meetings that were postponed show up as separate rows. Format changed in 2019-2020 ("New" vs old). |
| Alternatives | BSE corporate announcements API (**not tested**); company pages on aggregators list board meetings and announcement dates (terms-of-use and anti-bot limits; **not used**); vendor datasets. A user-supplied CSV `symbol, quarter_end, board_meeting_intimation_ts, results_broadcast_ts` would do. |
| What the current scraper does wrong | Uses dividend/ex-dates as a proxy, so `historical_earnings_*.csv` can never be a valid earnings calendar. |
| What it blocks | Pass 2 backtests (earnings exclusion window), and any event-risk analysis that needs earnings proximity. Not needed for the data gate itself. |

## 3. Summary: what is missing and what each gap blocks
| gap | status | blocks |
|---|---|---|
| Historical ASM/GSM start/end dates | not available from any endpoint tested; circulars exist as PDFs but the index is not reachable without enumeration; live lists are snapshots only | Pass 2 compliant backtests; ASM/GSM exclusion in any historical test |
| Earnings announcement history | **obtainable** from NSE results + board-meeting APIs (tested on one symbol) but not collected; current scraper is invalid | Pass 2 compliant backtests; earnings-window exclusion |
| Forward ASM/GSM archive | not started; free to start today | future point-in-time compliance only |

Decisions needed from you: (1) approve a time-boxed earnings collection through the two NSE APIs (about 40 minutes of requests, no scraping of blocked pages), (2) say whether you can supply an ASM/GSM history file, otherwise whether to start the forward daily snapshot and to attempt GSM history from the circular chain.
