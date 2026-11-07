# STOP B follow-up: DOLPHIN, ESCORTS investigation, F2b (STOP-3 hit)

Date 2026-11-08. No config, gate or budget changed. No strategy work.

## 1. DOLPHIN 2024-01-25 SPLIT — loaded (one run, one row)
Log row: `symbol=DOLPHIN, ex_date=2024-01-25, SPLIT 1:10 (ratio_numerator=1, ratio_denominator=10), evidence_tier=STRONG`, source "NSE corporates-corporateActions API (F2 Step 7)",
notes `feed_symbol=DOLPHIN; Face Value Split (Sub-Division) - From Rs 10/- Per Share To Re 1/- Per Share`,
evidence `yahoo factor 0.1000 vs logged 0.1000 (within 3%); across the gap: last close 2023-09-06 vs first close 2024-04-15 (222 calendar days)`.
Second sources used: company BSE filing (record/ex-date 25 Jan 2024), Trendlyne split page, press (BSE 1,826.85 on 24 Jan -> ~182.7 on 25 Jan).
Confirmed: total rows **22,997** (not 22,998: 22,996 + 1), SPLIT 452, price-moving 915, engine scan **267 remaining / 2 created** (499 removed), 58/58 verification rows still pass, equivalence 0 mismatches.

## 2. ESCORTS test — understood, legitimate, re-baselined (commit 8a19b40)
(a) Bars 2019-12-01..2020-01-20: Dec 2019 rows are the untouched pre-2020 raw rows (source NULL, identical to staging). From 2020-01-01 the OLD lake held Yahoo rows
(archive) with the same dates and identical volumes but close = 0.95514 x raw on every day (constant factor, e.g. 579.01 vs raw 606.20 on 2020-01-01). No rows added or removed
for ESCORTS in the window; no special session in the window.
(b) The old series therefore spliced raw pre-2020 prices onto dividend-adjusted 2020 prices (a fake -4.5% step on 2020-01-01). Breakout rule: close >= prior 20-day high. Prior high = 636.3 (raw, Dec 2019) in both.
Old: first close >= 636.3 is 642.81 on 2020-01-14 (signal) -> fill 2020-01-15. New (raw): close 643.05 on 2020-01-09 (SMA50 633.6, SMA200 606.6, trend true) -> fill 2020-01-10 open 645.8 x 1.001 = 646.45.
(c) The new date is correct on raw prices and the current rules; hand-checked against raw bars (entry price, lowest low 639.15, highest high 835.5; exit price is the average across partial exits).
(d) Yes: the old expected values came from Yahoo dividend-adjusted 2020+ prices spliced onto raw history.
All expected values re-baselined in one commit: entry 2020-01-10 @ 646.45, 162 shares, exit 2020-01-31 STOP_HIT, pnl_net 22,844, R 2.343 (old: 2020-01-15 @ 643.40, 144, 2020-02-20, 22,569, 2.295). The window now has 3 trades (ADANIPOWER, ESCORTS, BRITANNIA).
Added to F10: make this test independent of the real DB (fixture data) and remove the on-demand NSE fetch inside backtests.

## 3. F2b point-in-time shares — STOPPED at STOP-3, nothing loaded
Built (committed, tested, **not run against the database**): `data/ingestion/pit_shares.py` (current issued size walked back through the SPLIT/BONUS factors in the log), `scripts/f2b_build_pit_shares.py` (dry-run only so far), `SharesOutstandingPIT` model, 6 unit tests incl. the two-share-count test (market cap equal on both sides of a split/bonus ex-date for factors 0.1, 0.5, 0.25).
Current state of the data: `shares_outstanding` is ONE Yahoo "current" snapshot per symbol (2,217 symbols, fetched 2026-10-02) labelled effective 2020-01-01. For any date before a split/bonus it overstates shares by the full factor; it is not point-in-time.

Coverage by year (symbols / % of traded value, all non-fund lake equities; right-hand block = symbol-years averaging >= Rs25 cr/day, the ADTV-gate level):

| year | reliable | no current shares | excluded: unadjusted event | ADTV>=25cr: reliable % | no current shares % | unadjusted event % |
|---|---|---|---|---|---|---|
| 2013 | 813 | 629 | 109 | 65.5 | 21.4 | 13.1 |
| 2015 | 891 | 556 | 103 | 70.5 | 14.7 | 14.7 |
| 2017 | 1024 | 493 | 99 | 70.4 | 14.4 | 15.3 |
| 2019 | 1155 | 374 | 80 | 79.2 | 8.4 | 12.4 |
| 2020 | 1226 | 344 | 67 | 82.3 | 5.4 | 12.2 |
| 2021 | 1374 | 326 | 63 | 84.9 | 6.9 | 8.2 |
| 2022 | 1499 | 302 | 52 | 87.2 | 5.6 | 7.2 |
| 2024 | 1771 | 235 | 32 | 94.7 | 2.6 | 2.8 |
| 2026 | 2216 | 342 | 1 | 98.1 | 1.9 | 0.0 |

Full table: `docs/data_audit/pit_shares_coverage.csv`; excluded symbol-years: `pit_shares_excluded_symbol_years.csv`.
**Excluded share of traded value on ADTV-eligible names is large (about 35% in 2013, 25% in 2019, 18% in 2020, 13% in 2022). STOP-3: reported before continuing.** The spot-check against shareholding filings (~20 symbols) has not been started either.

Two separate causes:
1. **No current shares (112 eligible symbol groups; e.g. TATAMOTORS (old line), HDFC (merged), PEL, RELCAPITAL, RELINFRA, MINDTREE, DHFL, JETAIRWAYS, TATAMTRDVR).** Delisted, merged or renamed names have no current issued size, so a walk-back from today cannot reach them. This needs a different source (filings / NSE shareholding patterns by quarter) or an explicit rule to exclude them.
2. **Unadjustable events (56 eligible symbols; RELIANCE, ITC, VEDL, HINDUNILVR, BHARTIARTL, MOTHERSON, SIEMENS...).** My first rule flags every unadjusted event. A demerger does not change the parent's share count, so counting demergers as unreliable is over-cautious. What-if (not loaded): treating demergers as share-neutral cuts the eligible-share excluded for this cause from ~12% to ~1.4% in 2020 (reliable 93.1%); also walking large rights back by their ratio (known from the feed text) takes it to ~0 (reliable 94.6% in 2020; 77.9% in 2013). Mergers (57) and unsupported bonus/split (21) would remain excluded.

## Decisions needed
1. Treat demergers as share-neutral for the parent, and walk large rights back by their feed ratio? (Both are inside the "and so on" of the F2b instruction but change what is marked reliable.)
2. For delisted/merged/renamed names with no current issued size (5-21% of eligible traded value, falling by year): exclude them from the universe (state the share per year), or source quarterly shareholding filings for the largest ones (candidate list in `pit_shares_excluded_symbol_years.csv`)?
3. Then I load `shares_outstanding_pit`, switch the screener to it (missing/unreliable = no market-cap data, as today), and run the 20-symbol filing spot-check, reporting every miss.
