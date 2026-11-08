# Step 9 report — F2b decisions D1-D3 (spot-check FAILED the fixed bar; stopped, nothing loaded)

Date 2026-11-08. No config, gate or budget changed. No strategy work. `shares_outstanding_pit` was NOT created or loaded and the screener was NOT switched (D4 not started).

## D1 — implemented (`data/ingestion/pit_shares.py`, 10 unit tests pass)
- Demergers are share-neutral for the parent.
- Large rights are walked back by the feed ratio only where one distinct `n:d` parses from the text (102 of 105; the 3 that do not stay unreliable). Factor d/(n+d).
- Rights shares arrive weeks late: the count changes 45 days AFTER the ex-date and the whole band [ex-45d, ex+45d) is marked unreliable.
- Mergers, unsupported split/bonus, manual events and unparseable rights make every segment dated before the latest of them unreliable.
- Documented in the module docstring as NOT modelled: QIPs, preferential allotments, ESOPs, warrant conversions, buy-backs (and small or partly paid rights).

## D2 — coverage of ADTV-eligible traded value (symbol-years averaging >= Rs25 cr/day); final run `docs/data_audit/pit_shares_coverage_d2.csv`
Step 1, rename/successor through `isin_symbol_map` (same ISIN): resolves **9 of the 112** eligible "no current shares" groups (GUJGASLTD, HEG, JUBILANT, KPIT, LSIL, MAGMA, RUCHI, TATAMOTORS->TMPV, TRIL; about 28% of their traded value, mostly TATAMOTORS); 47 lake symbols resolved in total including non-eligible ones. The remaining 103 are delisted/merged or missing from the Yahoo snapshot.
Step 2, filings: 7 anchors read from shareholding filings, largest first (HDFC, DHFL, PEL, JETAIRWAYS, RELCAPITAL, RELINFRA, MINDTREE; `data/reference/pit_shares_anchors.csv`, with the source of each; four are exact filing totals, three are back-calculated from a stated holding and percentage, +-0.1-0.2%). **Stopped there because the target was met: excluded share <= 5% in every year 2019-2026** (after step 1 only 2019 was above, at 6.52%). Final excluded share (no source + unreliable) of ADTV-eligible traded value:

| year | 2013 | 2014 | 2015 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| excluded % | 14.5 | 14.8 | 9.7 | 7.4 | 8.1 | 4.0 | 1.2 | 0.9 | 1.2 | 0.8 | 1.3 | 1.0 | 0.6 | 1.8 |

2013-2018 is lower confidence and not to be tuned on (reviewer). Remaining top uncovered names 2019+: HFCL, MTARTECH, GSPL, JBCHEPHARM, STLTECH (still trading, missing from the Yahoo snapshot; NSE quote API returns 403 here), IDFC, TV18BRDCST, TATAMTRDVR. Every later backtest report must show what the excluded names did over the same windows (survivorship diagnostic) — carried as a requirement; list of excluded symbol-years: `pit_shares_excluded_symbol_years_d2.csv`.

## D3 — spot-check: FAILED the pre-registered bar
Bar fixed in advance: median |error| <= 5% and 90th percentile <= 15%. Result: **median 13.40%, p90 264.97%. Within 5%: 3/20; within 15%: 11/20.** Pairs were fixed before the filings were read (GMRINFRA had no snapshot and was replaced by JINDALSTEL before any actual was read). Groups: 4 large-rights names, 7 small/mid names with QIPs/preferential/warrants, 9 plain. Every symbol:

| symbol | date | group | actual | derived | error % | actual source |
|---|---|---|---|---|---|---|
| BHARTIARTL | 2018-12-31 | large rights | 3,997,400,107 | 4,859,843,644 | +21.58 | filing text |
| M&MFIN | 2020-03-31 | large rights | 617.7 M | 694.8 M | +12.48 | back-calc |
| IDEA | 2020-03-31 | large rights | 28.74 bn | 108.34 bn | +277.03 | back-calc |
| SUZLON | 2022-03-31 | large rights | 9.218 bn | 11.103 bn | +20.45 | back-calc |
| YESBANK | 2019-03-31 | QIP/pref | 2.315 bn | 31.389 bn | +1255.90 | back-calc |
| OLECTRA | 2021-03-31 | QIP/pref | 82.08 M | 82.08 M | 0.00 | back-calc |
| RPOWER | 2019-03-31 | QIP/pref | 2,805,126,466 | 4,135,770,966 | +47.44 | filing text |
| SOUTHBANK | 2020-03-31 | QIP/pref | 1.810 bn | 2.096 bn | +15.79 | back-calc |
| RBLBANK | 2019-03-31 | QIP/pref | 426,709,728 | 1,551,642,481 | +263.63 | filing text |
| JPPOWER | 2019-03-31 | QIP/pref | 5.995 bn | 6.853 bn | +14.32 | back-calc |
| JINDALSTEL | 2019-03-31 | QIP/pref | 967.5 M | 1,017.5 M | +5.17 | back-calc |
| RELIANCE | 2019-03-31 | plain | 6,338,693,823 | 6,766,236,317 | +6.74 | filing text |
| TCS | 2018-03-31 | plain | 1.914 bn | 1.809 bn | -5.50 | derived (buy-back %) |
| INFY | 2018-03-31 | plain | 2,184,114,257 | 2,025,171,780 | -7.28 | filing text |
| HDFCBANK | 2019-03-31 | plain | 2,723,306,610 | 3,854,619,253 | +41.54 | filing text |
| BAJFINANCE | 2018-03-31 | plain | 577.97 M | 622.09 M | +7.63 | back-calc (Jun-2018) |
| ASIANPAINT | 2019-03-31 | plain | 959.2 M | 958.6 M | -0.06 | back-calc |
| WIPRO | 2018-03-31 | plain | 4,523,784,491 | 3,710,039,008 | -17.99 | filing text |
| TITAN | 2019-03-31 | plain | 887,786,160 | 887,312,335 | -0.05 | filing text |
| ESCORTS | 2019-03-31 | plain | 122.59 M | 110.03 M | -10.25 | back-calc |

Full file: `docs/data_audit/pit_spotcheck_results.csv`; filings and sources: `data/reference/pit_shares_spotcheck_filings.csv`. Seven "actuals" are back-calculated from a stated holding and percentage (+-0.2%), TCS is derived; none of that explains errors of this size.

Why it fails (all are events the log cannot see):
- **Recapitalisations and preferential issues** (the three giant errors): YES Bank 2020 rescue issue, Vodafone Idea government/ATC conversions, RBL Bank 2026 preferential allotment (the current snapshot already contains it, so every earlier date is overstated by ~3.6x).
- **Acquirer-side mergers are not flagged**: HDFC Ltd's merger into HDFC Bank (2023) shows up on the delisted HDFC symbol only, so HDFC Bank's earlier counts are 41.5% too high.
- **Buy-backs** push the other way (WIPRO -18%, INFY -7%, TCS -5.5%); ESCORTS -10% is a capital reduction (cancelled trust shares); QIPs and warrants explain BHARTIARTL, RPOWER, SOUTHBANK, JPPOWER, JINDALSTEL.
- Large rights as modelled did not fail on the ratio itself (IDEA/SUZLON/BHARTI errors are dominated by other issuance after the rights).
Informational only (not the bar): at the spot-check dates the Rs5,000 cr market-cap gate decision would have been the same for all 20 names (they sit far from the line), so the failure says nothing yet about names near the line.

## Stopped per D3. Decisions needed (I will not change the bar or load anything)
1. Options to get a usable point-in-time series, in my order of preference:
   a) Add flags for what the data can detect: acquirer-side mergers (events on the delisted symbol -> mark the acquirer unreliable before the merger date), and unreliable-before-latest-large-issue using a jump test (derived market cap vs price-implied changes are not available, so this is a manual list for the ~60 largest names).
   b) Replace the current-size walk-back by direct quarterly shareholding totals for the eligible universe. Not feasible here (NSE API blocked, aggregator pages need per-company reading); would need a bulk source you can supply, or a time-boxed manual pass over the top names by traded value.
   c) Keep the walk-back but let the screener use it only as a coarse gate (accept shares within a band), i.e. a NEW pre-registered bar based on gate decisions near the Rs5,000 cr line. This changes the bar, so it is yours to decide, not mine.
2. Until one is chosen, `shares_outstanding_pit` stays unloaded and the screener keeps today's single-snapshot behaviour (which has the same errors, unflagged).

Commits: D1/D2 code and tests, anchors file, spot-check script, filings and results (this report is in the same push).
