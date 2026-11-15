# Symbols that stop having bars: inventory (counts and lists only)

Branch `stale-positions` (from origin/master 67b6724). **No engine change, no rule built, no mapping adopted, no stored result touched.** Read-only on `finsight.db` (sqlite `mode=ro&immutable=1`; sha256 before and after `dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752`, see the end). No returns are computed or shown. Scripts: `scripts/stale_symbols_inventory.py` (about 19 minutes) and `scripts/stale_symbols_tables.py` (seconds). Data files: `docs/data_audit/stale_symbols/`.

## Summary counts
| item | count |
|---|---|
| symbols in the lake (index series NIFTY50_INDEX, INDIA_VIX excluded) | 3,625 (5,634,334 rows, 3,416 calendar sessions, 2013-01-01 to 2026-10-16) |
| **stale symbols: last bar more than 20 sessions before 2026-10-16** | **870** |
| of which in the fund/ETF list (`data/reference/fund_etf_symbols.csv`) | 36 |
| of which ever eligible (shared rules, any date in the lake) | 159 (132 on a date in 2016-01-01 to 2026-10-16) |
| with at least one corporate_actions_log row within 30 days of the last bar | 53 (in 24 of them a note names a feed_symbol different from the symbol itself) |
| stale symbols in the repo's copy of `EQUITY_L.csv` (committed 2026-10-21) | 193 (series BE 158, BZ 28, EQ 7); 34 of them ever eligible |
| stale symbols with a row in `isin_symbol_map` | 180; with a same-ISIN successor row: 114 (boundary types: {'other': 54, 'pure_rename': 48, 'demerger_merger': 12}) |
| rename candidates by the price rule (first bar within 5 sessions after the last bar, first close within 2% of the old last close after any logged split/bonus) | 65 candidate rows for 52 stale symbols (all rows examined: 5,950) |
| pairs named by a feed_symbol note (a different symbol named in a corporate_actions_log note, one side stale) | 64 distinct pairs (201 log rows); first bar of the named symbol 1 session after the old last bar: 24; 6 to 20 sessions: 4; more than 20: 35; overlapping history: 1 |
| **rename candidates exist (so "none" cannot be confirmed)** | stale symbols with at least one lead: 120 (definition A); with a strict lead: 67 (definition B) |
| gaps: runs of more than 20 missing sessions between two bars | 6,433 runs in 1,613 symbols; in 204 symbols (333 runs) the symbol was eligible both before and after the gap |
| terminal symbols with no rename lead (definition A) | 750: ever eligible 126; held in at least one stored run 84 |

## Definitions and limits (stated once)
- **Calendar and sessions.** Every distinct `trade_date` in `market_data_lake` (3,416; each has at least 1,142 symbols). The engine's own session list is the NIFTY50_INDEX dates; the lake's NIFTY series has 706 fewer dates, so the counts here use the lake's full calendar. A symbol is stale when more than 20 calendar sessions lie after its last bar (minimum observed: 21). The lake keeps NSE EQ-series bars only (`Claude_Docs/DATA_GUIDE.md` section D.2), so "no bar" means "no EQ-series bar"; this inventory cannot tell not traded from traded in another series.
- **Last 20-session ADTV** = mean of raw close x raw volume over the symbol's last 20 bars, in crore (blank where the symbol has fewer than 20 bars: 21 symbols).
- **Ever eligible** = on at least one bar date the shared eligibility rules (`stockbot/universe/eligibility.py`, thresholds read from the shared config: ADTV above 25 crore, listing age at least 252 by the F2 rule of `AsOfView.symbol_info`, not a fund/ETF) all held. ASM/GSM exclusion is not applied (no historical ASM/GSM data exists, KI-003). Computed vectorised from the raw table, not by calling the view per session.
- **Price rule for renames** as given in the task; the logged factor is the product of `action_factor` over SPLIT/BONUS rows of either symbol with ex-date after the old last bar and up to the new first bar. A split whose ex-date equals the old last bar is already in that bar and is not applied again (PHILIPCARB, 2018-04-19).
- The price rule alone is a weak test: 65 candidate rows match, among them batches of new listings that start on the same day (2026-08-17) and several ETF launches. It is listed, not judged.

## 1. Stale symbols
Count by last-bar year:

| last-bar year | 2013 | 2014 | 2015 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| symbols | 50 | 58 | 73 | 43 | 68 | 67 | 58 | 50 | 53 | 52 | 51 | 35 | 36 | 176 |

Of the 176 symbols whose last bar is in 2026, 155 appear in the repo's copy of `EQUITY_L.csv`.

All 870 stale symbols, with last bar, number of bars, last 20-session ADTV, ever-eligible flag, eligibility span, number of corporate_actions_log rows within 30 days of the last bar, the raw notes and the fund/ETF flag, are in **`docs/data_audit/stale_symbols/stale_symbols.csv`** (columns: symbol, first_bar, last_bar, bars, sessions_after_last_bar, last_close, adtv20_last_cr, is_fund_etf, ever_eligible, eligible_sessions, first_eligible, last_eligible, eligible_in_window_2016, n_ca_within_30d, ca_within_30d, feed_symbol_in_notes, in_isin_symbol_map). The 159 ever-eligible stale symbols are listed here (none is a fund/ETF):

| symbol | last bar | bars | ADTV20 (cr) | eligible first to last | eligible sessions | corporate_actions_log rows within 30 days of the last bar (ex-date, type, ratio, notes) |
|---|---|---|---|---|---|---|
| 3IINFOLTD | 2026-08-13 | 1183 | 4.18 | 2024-01-23 to 2024-01-25 | 3 |  |
| 3IINFOTECH | 2021-06-08 | 1910 | 35.35 | 2021-05-19 to 2021-06-08 | 15 |  |
| 8KMILES | 2020-09-23 | 1364 | 0.48 | 2017-10-31 to 2018-08-01 | 77 |  |
| ABAN | 2025-09-04 | 2641 | 0.57 | 2013-11-20 to 2018-05-07 | 793 |  |
| ABGSHIP | 2017-01-23 | 1005 | 1.12 | 2015-02-27 to 2015-03-24 | 18 |  |
| ABIRLANUVO | 2017-07-04 | 1114 | 97.84 | 2013-01-28 to 2017-07-04 | 635 |  |
| ACLGATI | 2025-11-11 | 3159 | 3.98 | 2014-05-28 to 2022-02-15 | 343 |  |
| AGSTRA | 2025-01-29 | 690 | 3.47 | 2023-12-06 to 2023-12-08 | 3 |  |
| AHL | 2025-01-29 | 522 | 4.33 | 2024-08-22 to 2024-10-08 | 33 |  |
| ALBK | 2020-03-19 | 1784 | 2.53 | 2013-01-28 to 2019-07-23 | 714 |  |
| ALOKTEXT | 2019-12-09 | 1511 | 0.97 | 2014-06-05 to 2014-09-23 | 42 |  |
| AMIORG | 2025-04-24 | 896 | 61.37 | 2022-09-20 to 2025-04-24 | 244 | 2025-04-25 SPLIT 5:10 [feed_symbol=ACUTAAS; Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 5/- Pe] |
| AMTEKAUTO | 2018-03-28 | 1238 | 1.91 | 2014-04-07 to 2016-08-22 | 296 |  |
| AMTEKINDIA | 2015-06-08 | 575 | 41.88 | 2014-06-10 to 2015-06-08 | 43 |  |
| ANDHRABANK | 2020-03-19 | 1784 | 1.07 | 2014-05-16 to 2018-05-02 | 289 |  |
| ARIES | 2026-09-07 | 3265 | 8.37 | 2023-01-05 to 2023-01-24 | 14 | 2026-09-22 DIVIDEND [feed_symbol=ARIES; Dividend - Rs 1.50 Per Share/Special Dividend - Re 1 Per Share] |
| BGRENERGY | 2026-02-23 | 2788 | 4.21 | 2014-05-23 to 2024-11-11 | 32 |  |
| BHARATFIN | 2019-07-02 | 1607 | 156 | 2014-04-17 to 2019-07-02 | 1266 |  |
| BLISSGVS | 2026-07-02 | 3342 | 54.45 | 2019-02-05 to 2026-07-02 | 242 | 2026-07-08 DIVIDEND [feed_symbol=BLISSGVS; Dividend - Re 1 Per Share] |
| BRFL | 2022-04-01 | 1814 | 0.25 | 2017-12-12 to 2018-01-10 | 21 |  |
| CADILAHC | 2015-10-06 | 684 | 33.05 | 2014-02-28 to 2015-10-06 | 96 | 2015-10-06 SPLIT 1:5 [feed_symbol=ZYDUSLIFE; Face Value Split (Sub-Division) - From Rs 5/- Per Share To Re 1/- P] |
| CAIRN | 2017-04-25 | 1066 | 186.4 | 2013-01-28 to 2017-04-25 | 1046 |  |
| CAPF | 2018-12-27 | 1481 | 76.04 | 2016-08-04 to 2018-12-27 | 417 |  |
| CIGNITITEC | 2026-05-14 | 2751 | 18.9 | 2021-07-05 to 2025-06-02 | 192 |  |
| COREEDUTEC | 2015-09-24 | 632 | 0.07 | 2013-02-28 to 2013-03-28 | 20 |  |
| COX&KINGS | 2019-12-24 | 1714 | 0.48 | 2014-10-07 to 2016-09-23 | 12 |  |
| DALMIABHA | 2018-11-28 | 1435 | 37.44 | 2016-10-06 to 2018-11-28 | 308 |  |
| DENABANK | 2019-03-07 | 1530 | 2.46 | 2013-01-28 to 2014-06-19 | 83 |  |
| DHANI | 2025-10-27 | 3028 | 23.06 | 2017-04-11 to 2025-10-15 | 1171 |  |
| DHFL | 2021-06-11 | 2089 | 6.24 | 2014-07-08 to 2019-10-25 | 1147 |  |
| DIACABS | 2026-08-03 | 346 | 265 | 2025-06-06 to 2026-08-03 | 169 |  |
| DISHMAN | 2017-05-29 | 1089 | 25.55 | 2014-09-19 to 2017-05-29 | 266 |  |
| E2E | 2026-08-10 | 568 | 123.3 | 2025-05-02 to 2026-08-10 | 177 |  |
| EQUITAS | 2023-02-02 | 1685 | 11.01 | 2017-04-25 to 2023-01-10 | 735 |  |
| EROSMEDIA | 2024-10-24 | 2749 | 5.74 | 2015-07-09 to 2018-02-02 | 148 |  |
| ESSAROIL | 2016-02-09 | 758 | 5.24 | 2013-02-01 to 2016-01-15 | 139 |  |
| FCONSUMER | 2024-05-15 | 2376 | 0.93 | 2017-07-21 to 2021-07-09 | 231 |  |
| FEL | 2023-01-20 | 1592 | 0.55 | 2017-09-19 to 2017-10-05 | 12 |  |
| FLFL | 2023-03-31 | 2194 | 0.11 | 2017-04-05 to 2017-05-02 | 18 |  |
| FRETAIL | 2022-07-22 | 1443 | 3.54 | 2017-09-18 to 2022-04-08 | 583 |  |
| FRL | 2016-05-10 | 758 | 11.52 | 2013-05-11 to 2014-07-03 | 170 |  |
| GANESHBE | 2026-07-30 | 1208 | 18.3 | 2024-02-09 to 2024-02-23 | 11 |  |
| GDL | 2022-01-04 | 2166 | 7.52 | 2021-05-20 to 2021-05-31 | 8 |  |
| GENSOL | 2025-03-18 | 369 | 26.55 | 2025-03-07 to 2025-03-18 | 6 |  |
| GEOMETRIC | 2017-03-10 | 1037 | 4.84 | 2015-03-24 to 2016-05-04 | 41 |  |
| GITANJALI | 2018-04-26 | 1316 | 0.22 | 2013-01-28 to 2018-02-02 | 157 |  |
| GRUH | 2019-10-15 | 1676 | 99.05 | 2018-01-19 to 2019-10-15 | 178 |  |
| GSKCONS | 2020-04-15 | 1799 | 58.24 | 2013-01-28 to 2020-04-15 | 90 |  |
| GSPL | 2026-05-11 | 3306 | 75.51 | 2015-01-14 to 2026-05-11 | 786 |  |
| GUJGASLTD | 2026-06-30 | 2659 | 36.33 | 2020-01-02 to 2026-06-30 | 1297 |  |
| GUJRATGAS | 2015-05-26 | 592 | 79.69 | 2014-07-04 to 2015-05-26 | 82 |  |
| GVKPIL | 2024-07-19 | 2130 | 3.98 | 2014-05-28 to 2017-08-22 | 28 |  |
| HDFC | 2023-07-12 | 2606 | 2087 | 2013-01-28 to 2023-07-12 | 2587 |  |
| HDIL | 2019-11-21 | 1701 | 0.38 | 2013-01-28 to 2018-10-03 | 1346 |  |
| HEG | 2026-09-04 | 3388 | 127 | 2017-08-28 to 2026-09-04 | 1902 |  |
| HERCULES | 2026-01-01 | 3080 | 0.27 | 2024-11-08 to 2024-11-12 | 3 |  |
| HEXAWARE | 2020-10-30 | 1938 | 13.91 | 2013-01-28 to 2020-10-14 | 1199 |  |
| HFCL | 2026-09-02 | 3312 | 414 | 2014-09-17 to 2026-09-02 | 1459 | 2026-09-22 DIVIDEND [feed_symbol=HFCL; Dividend - Re 0.20 Per Share] |
| HINDMOTORS | 2025-10-01 | 2642 | 10.97 | 2024-05-06 to 2024-06-05 | 23 |  |
| IDFC | 2024-10-09 | 2915 | 132.7 | 2013-01-28 to 2024-10-09 | 2144 |  |
| INDIABULLS | 2013-03-18 | 55 | 47.63 | 2013-01-28 to 2013-03-18 | 36 |  |
| INFIBEAM | 2017-08-31 | 350 | 125.5 | 2017-04-10 to 2017-08-31 | 99 | 2017-08-31 SPLIT 1:10 [feed_symbol=CCAVENUE; Annual General Meeting/Face Value Split (Sub-Division) - From Rs 10/] |
| INGVYSYABK | 2015-04-15 | 564 | 24.53 | 2014-11-20 to 2015-03-24 | 86 |  |
| INOXLEISUR | 2023-02-16 | 2509 | 11.72 | 2020-03-04 to 2022-10-12 | 303 |  |
| ISEC | 2025-03-21 | 1729 | 66.07 | 2019-12-30 to 2025-03-21 | 644 |  |
| ISMTLTD | 2024-08-05 | 2407 | 22.4 | 2024-07-18 to 2024-07-30 | 9 |  |
| IVRCLINFRA | 2019-06-06 | 1500 | 0.27 | 2013-01-28 to 2014-07-02 | 51 |  |
| IWEL | 2025-06-19 | 658 | 32.33 | 2024-08-16 to 2025-06-19 | 28 |  |
| JBCHEPHARM | 2026-07-16 | 3352 | 152.3 | 2020-08-11 to 2026-07-16 | 689 |  |
| JBFIND | 2023-01-20 | 1988 | 0.09 | 2014-12-08 to 2015-01-02 | 19 |  |
| JETAIRWAYS | 2019-06-27 | 1604 | 207.2 | 2013-01-28 to 2019-06-27 | 1508 |  |
| JPASSOCIAT | 2024-06-05 | 2764 | 42.53 | 2013-01-28 to 2024-06-05 | 1546 |  |
| JSLHISAR | 2023-03-08 | 1752 | 11.94 | 2021-05-17 to 2021-09-01 | 38 |  |
| JSWISPL | 2023-08-09 | 1089 | 15.81 | 2021-06-07 to 2022-02-02 | 10 |  |
| JUBILANT | 2021-02-03 | 2003 | 58.93 | 2015-07-29 to 2021-02-03 | 789 |  |
| KALINDEE | 2017-02-08 | 990 | 3.65 | 2015-02-26 to 2015-03-20 | 17 |  |
| KAYA | 2026-08-24 | 2422 | 2.06 | 2024-07-10 to 2024-07-11 | 2 |  |
| KPIT | 2019-02-25 | 1523 | 42.36 | 2014-12-12 to 2019-02-25 | 421 |  |
| KRONOX | 2026-08-25 | 539 | 38.65 | 2026-08-21 to 2026-08-25 | 3 | 2026-09-09 DIVIDEND [feed_symbol=KRONOX; Dividend - Re 0.50 Per Share] |
| KWALITY | 2021-02-23 | 1861 | 0.19 | 2015-12-18 to 2018-05-16 | 107 |  |
| LAKSHVILAS | 2020-11-25 | 1956 | 3.22 | 2019-04-02 to 2019-05-10 | 25 |  |
| LEEL | 2019-05-21 | 1552 | 0.36 | 2017-02-23 to 2017-03-21 | 17 |  |
| LITL | 2018-09-12 | 1221 | 0.43 | 2013-01-28 to 2014-07-03 | 18 |  |
| LSIL | 2023-08-09 | 1341 | 76.91 | 2023-01-20 to 2023-08-09 | 41 | 2023-07-17 DIVIDEND [feed_symbol=LLOYDSENGG; Annual General Meeting/Dividend - Re 0.10 Per Share] |
| MAGMA | 2021-06-08 | 2086 | 31.16 | 2021-02-24 to 2021-06-08 | 45 |  |
| MAKE | 2015-05-25 | 208 | 19.78 | 2014-08-26 to 2015-05-13 | 53 |  |
| MANGCHEFER | 2025-10-30 | 3178 | 13.38 | 2022-04-21 to 2025-08-26 | 40 |  |
| MANPASAND | 2019-09-23 | 1039 | 0.99 | 2018-06-11 to 2018-07-24 | 32 |  |
| MAX | 2016-02-25 | 771 | 19.51 | 2014-07-16 to 2016-01-22 | 59 | 2016-01-27 MERGER [feed_symbol=MFSL; Scheme Of Arrangement] |
| MCDOWELL-N | 2018-06-15 | 1351 | 146.5 | 2013-01-28 to 2018-06-15 | 1332 | 2018-06-15 SPLIT 2:10 [feed_symbol=UNITDSPR; Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/- P] |
| MEGH | 2021-05-17 | 1995 | 66.35 | 2017-08-18 to 2021-05-17 | 155 | 2021-05-18 DEMERGER [feed_symbol=MEGH; Merger/Demerger] |
| MEP | 2024-03-19 | 2003 | 4.96 | 2017-06-19 to 2017-10-03 | 73 |  |
| MERCATOR | 2022-05-24 | 1906 | 0.11 | 2016-10-07 to 2016-11-04 | 19 |  |
| METALFORGE | 2021-02-24 | 1671 | 0.01 | 2014-09-09 to 2014-09-19 | 9 |  |
| MICEL | 2026-07-02 | 657 | 3.87 | 2025-09-05 to 2025-10-27 | 35 |  |
| MINDTREE | 2022-11-22 | 2448 | 230 | 2014-04-17 to 2022-11-22 | 1679 |  |
| MIRCELECTR | 2026-05-18 | 2732 | 21.88 | 2017-11-30 to 2017-12-26 | 18 |  |
| MONSANTO | 2019-09-26 | 1665 | 0.73 | 2014-09-19 to 2016-07-13 | 52 |  |
| MTARTECH | 2026-06-24 | 1308 | 1635 | 2022-03-25 to 2026-06-24 | 767 |  |
| MYSOREBANK | 2017-03-15 | 1039 | 2.25 | 2016-06-28 to 2016-07-14 | 12 |  |
| NURECA | 2026-08-10 | 1149 | 2.69 | 2022-12-23 to 2023-02-20 | 33 |  |
| OPTOCIRCUI | 2021-02-19 | 1776 | 0.36 | 2013-02-06 to 2013-06-27 | 43 |  |
| ORIENTBANK | 2020-03-20 | 1785 | 9.84 | 2013-01-28 to 2019-07-16 | 1353 |  |
| OSIAHYPER | 2026-05-05 | 382 | 0.83 | 2025-02-24 to 2025-03-17 | 14 |  |
| PANTALOONR | 2013-04-10 | 70 | 69.88 | 2013-01-28 to 2013-04-10 | 51 |  |
| PEL | 2025-09-22 | 3152 | 59.55 | 2016-05-20 to 2025-09-22 | 2172 |  |
| PHILIPCARB | 2018-04-19 | 1311 | 29.19 | 2017-06-19 to 2018-04-19 | 184 | 2018-04-19 SPLIT 2:10 [feed_symbol=PCBL; Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/- Per S] |
| POLARIS | 2018-07-24 | 1368 | 0.96 | 2014-03-03 to 2015-08-19 | 99 |  |
| PRICOL | 2016-12-02 | 969 | 8.35 | 2016-08-04 to 2016-08-12 | 7 |  |
| PUNJLLOYD | 2019-09-23 | 1569 | 0.05 | 2013-03-28 to 2014-08-25 | 51 |  |
| RADHIKAJWE | 2026-09-15 | 971 | 33.63 | 2024-08-19 to 2026-09-15 | 61 |  |
| RAJESHEXPO | 2025-12-24 | 3216 | 60 | 2015-07-10 to 2025-12-24 | 954 |  |
| RAMASTEEL | 2026-06-25 | 2429 | 4.51 | 2023-01-18 to 2025-10-14 | 208 |  |
| RANBAXY | 2015-04-01 | 557 | 121.9 | 2013-01-28 to 2015-04-01 | 538 |  |
| RBZJEWEL | 2026-09-07 | 451 | 34.22 | 2026-09-03 to 2026-09-07 | 3 |  |
| RCOM | 2022-05-24 | 2076 | 1.73 | 2013-01-28 to 2022-03-30 | 1552 |  |
| RELCAPITAL | 2022-05-24 | 2164 | 1.99 | 2013-01-28 to 2021-07-15 | 1671 |  |
| RELINFRA | 2025-06-04 | 2752 | 336.5 | 2013-01-28 to 2025-06-04 | 2278 |  |
| RNAVAL | 2021-01-22 | 1795 | 0.88 | 2015-01-16 to 2018-06-14 | 175 |  |
| ROLTA | 2022-08-22 | 1953 | 0.24 | 2014-06-13 to 2018-02-01 | 95 |  |
| RUCHI | 2022-05-24 | 382 | 885.7 | 2022-03-29 to 2022-05-24 | 38 |  |
| RUCHISOYA | 2019-11-13 | 1605 | 0.71 | 2017-11-24 to 2017-11-29 | 4 |  |
| SANGHIIND | 2026-04-02 | 2986 | 4.52 | 2017-10-17 to 2024-02-15 | 38 |  |
| SATYAMCOMP | 2013-07-03 | 128 | 95.73 | 2013-01-28 to 2013-07-03 | 105 |  |
| SBBJ | 2017-03-15 | 1039 | 4.72 | 2016-06-16 to 2016-07-21 | 25 |  |
| SBT | 2017-03-15 | 1039 | 10.54 | 2016-06-17 to 2016-07-15 | 20 |  |
| SHALPAINTS | 2026-08-05 | 3243 | 9.76 | 2023-12-08 to 2023-12-29 | 15 |  |
| SHASUNPHAR | 2015-11-17 | 712 | 7.23 | 2014-05-09 to 2014-09-18 | 22 |  |
| SHRIRAMCIT | 2022-11-28 | 2452 | 26.91 | 2016-07-22 to 2022-11-28 | 64 |  |
| SINTEX | 2022-03-21 | 1960 | 5.48 | 2013-01-28 to 2017-09-25 | 630 |  |
| SORILINFRA | 2022-08-17 | 2242 | 0.37 | 2017-12-08 to 2018-08-02 | 12 |  |
| SPICEJET | 2023-04-28 | 917 | 6.01 | 2020-08-24 to 2022-09-02 | 296 |  |
| SREINFRA | 2022-05-24 | 2235 | 0.27 | 2016-01-05 to 2018-10-22 | 140 |  |
| STALLION | 2026-08-10 | 248 | 104.7 | 2026-08-10 to 2026-08-10 | 1 |  |
| STER | 2013-08-26 | 164 | 97.84 | 2013-01-28 to 2013-08-26 | 145 |  |
| STLTECH | 2026-05-13 | 3262 | 228.6 | 2015-07-10 to 2026-05-13 | 1167 |  |
| SUBEX | 2020-10-21 | 1788 | 8.77 | 2015-12-09 to 2015-12-22 | 10 |  |
| SUNILHITEC | 2018-08-16 | 1383 | 0.25 | 2016-10-13 to 2016-12-07 | 39 |  |
| SUPPETRO | 2022-04-06 | 2228 | 27.7 | 2022-03-29 to 2022-04-06 | 7 |  |
| SYNDIBANK | 2020-03-19 | 1784 | 5.29 | 2013-01-28 to 2019-07-04 | 524 |  |
| TATACOFFEE | 2024-01-12 | 2732 | 38.29 | 2013-01-28 to 2024-01-12 | 402 |  |
| TATAMETALI | 2024-02-05 | 2686 | 10.51 | 2014-10-30 to 2021-10-14 | 276 |  |
| TATAMOTORS | 2025-10-23 | 3173 | 1131 | 2013-01-28 to 2025-10-23 | 3154 | 2025-10-14 DEMERGER [feed_symbol=TMPV; Demerger] |
| TATAMTRDVR | 2024-08-29 | 2887 | 428.4 | 2013-01-28 to 2024-08-29 | 2673 |  |
| TATASTLBSL | 2021-08-05 | 2069 | 88.03 | 2017-06-23 to 2021-08-05 | 184 |  |
| TATASTLLP | 2023-11-16 | 2628 | 6.04 | 2014-03-04 to 2022-10-14 | 576 |  |
| TCNSBRANDS | 2024-09-02 | 1508 | 53.19 | 2024-06-18 to 2024-09-02 | 32 |  |
| TIDEWATER | 2021-07-14 | 2112 | 15.22 | 2016-01-05 to 2021-06-29 | 40 | 2021-07-26 SPLIT 2:5 [feed_symbol=VEEDOL; Face Value Split (Sub-Division) - From Rs 5/- Per Share To Re 2/- Per ] / 2021-07-26 BONUS 1:1 [feed_symbol=VEEDOL; Bonus 1:1] |
| TIL | 2026-08-10 | 2727 | 72.42 | 2026-07-29 to 2026-08-10 | 9 |  |
| TINPLATE | 2024-01-18 | 2672 | 21.72 | 2017-07-12 to 2022-05-12 | 359 |  |
| TRIL | 2024-05-13 | 2603 | 39.15 | 2023-07-21 to 2024-05-13 | 67 | 2024-05-10 DIVIDEND [feed_symbol=TARIL; Annual General Meeting/Dividend - Re 0.20 Per Share] |
| TV18BRDCST | 2024-10-15 | 2853 | 41.67 | 2014-05-30 to 2024-10-15 | 1110 |  |
| TWL | 2015-04-23 | 519 | 32.96 | 2015-02-10 to 2015-04-23 | 49 | 2015-04-23 SPLIT 2:10 [feed_symbol=TITAGARH; Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/- P] |
| UFBL | 2026-08-11 | 1326 | 12.39 | 2022-04-11 to 2026-06-18 | 50 |  |
| UJJIVAN | 2024-05-02 | 1978 | 65.03 | 2017-05-15 to 2024-05-02 | 1150 |  |
| UPERGANGES | 2017-03-22 | 916 | 8.32 | 2016-06-17 to 2016-09-29 | 71 |  |
| VIJAYABANK | 2019-03-07 | 1530 | 11.14 | 2017-05-15 to 2017-12-04 | 39 |  |
| VIVIMEDLAB | 2026-04-16 | 2412 | 0.09 | 2016-10-07 to 2017-10-19 | 30 |  |
| WELSPUNIND | 2016-03-21 | 771 | 16.91 | 2015-07-24 to 2015-08-28 | 26 | 2016-03-21 SPLIT 1:10 [feed_symbol=WELSPUNLIV; Interim Div - Rs 6/- Per Share + Face Value Split (Sub-Division) -] |

## 2. Rename candidates (listed with evidence; none adopted)
**Price rule** (65 rows, 52 stale symbols; `rename_candidates_price_within_2pct.csv`):

| old symbol | old last bar | other symbol | its first bar | sessions between | first close / old last close | also named by a feed_symbol note | old ever eligible | other ever eligible |
|---|---|---|---|---|---|---|---|---|
| 3IINFOLTD | 2026-08-13 | APOORVA | 2026-08-20 | 5 | 0.9844 | no | True | False |
| 3IINFOLTD | 2026-08-13 | GSEC10ADD | 2026-08-20 | 5 | 1.01 | no | True | False |
| AARTISURF | 2026-08-14 | ISTLTD | 2026-08-17 | 1 | 1.013 | no | False | False |
| ALSTOMT&D | 2016-09-12 | GET&D | 2016-09-14 | 1 | 1.009 | no | False | False |
| ANMOL | 2026-09-16 | SECLEDBETA | 2026-09-18 | 2 | 0.9903 | no | False | False |
| ASHIKAG | 2026-08-10 | ALUFLUOR | 2026-08-17 | 5 | 1.015 | no | False | False |
| BNALTD | 2026-07-21 | CMLL | 2026-07-24 | 3 | 1.017 | no | False | False |
| CADILAHC | 2015-10-06 | ZYDUSLIFE | 2015-10-07 | 1 | 0.9942 | yes | True | True |
| DHABRIYA | 2026-08-21 | TEMPSENS | 2026-08-28 | 5 | 1.017 | no | False | False |
| E2E | 2026-08-10 | ARYAMAN | 2026-08-17 | 5 | 0.9952 | no | True | False |
| GAL | 2016-10-13 | SHAH | 2016-10-14 | 1 | 1.019 | yes | False | False |
| GOLDSHARE | 2021-03-25 | GOLDBETA | 2021-03-26 | 1 | 0.9951 | no | False | False |
| GUJFLUORO | 2019-07-24 | GFLLIMITED | 2019-07-25 | 1 | 1.008 | yes | False | False |
| HDFCMFGETF | 2021-02-18 | HDFCGOLD | 2021-02-19 | 1 | 0.9892 | no | False | False |
| HDFCMFGETF | 2021-02-18 | SNXT50BETA | 2021-02-19 | 1 | 1.014 | no | False | False |
| HDFCNIFETF | 2021-02-18 | HDFCNIFTY | 2021-02-19 | 1 | 0.9936 | no | False | False |
| HDFCSENETF | 2021-02-18 | HDFCSENSEX | 2021-02-19 | 1 | 0.9963 | no | False | False |
| ICICI500 | 2021-10-28 | BSE500IETF | 2021-10-29 | 1 | 0.9819 | no | False | False |
| ICICIBANKN | 2022-09-01 | BANKIETF | 2022-09-02 | 1 | 1.001 | no | False | False |
| ICICIGOLD | 2018-11-15 | GOLDIETF | 2018-11-16 | 1 | 0.9912 | no | False | False |
| ICICITECH | 2022-09-01 | ITIETF | 2022-09-02 | 1 | 0.9955 | no | False | False |
| IDFC | 2024-10-09 | GARUDA | 2024-10-15 | 4 | 0.9851 | no | True | True |
| IGOLD | 2016-06-09 | ICICIGOLD | 2016-06-10 | 1 | 0.9875 | no | False | False |
| KAYA | 2026-08-24 | SUNSHINE | 2026-08-25 | 1 | 1.005 | no | True | False |
| KCPSUGIND | 2026-08-10 | CFEL | 2026-08-17 | 5 | 1.008 | no | False | False |
| KEERTI | 2023-06-21 | GHCLTEXTIL | 2023-06-26 | 3 | 1.012 | no | False | True |
| KOTAKGOLD | 2021-07-22 | GOLD1 | 2021-07-23 | 1 | 1.002 | no | False | False |
| KOTAKNIFTY | 2017-07-27 | NIFTY1 | 2017-07-28 | 1 | 0.9953 | no | False | False |
| KPIT | 2019-02-25 | BSOFT | 2019-02-26 | 1 | 0.9972 | yes | True | True |
| LANCORHOL | 2026-09-08 | DOLLEX | 2026-09-11 | 3 | 1.011 | no | False | False |
| MAHASTEEL | 2026-08-10 | MOLBIO | 2026-08-17 | 5 | 1.02 | no | False | False |
| MANJUSHREE | 2015-03-16 | GREENLAM | 2015-03-17 | 1 | 1.007 | no | False | False |
| MCDOWELL-N | 2018-06-15 | UNITDSPR | 2018-06-18 | 1 | 0.983 | yes | True | True |
| MEP | 2024-03-19 | GVPTECH | 2024-03-26 | 4 | 1.014 | no | True | False |
| NETFNV20 | 2019-12-19 | NV20BEES | 2019-12-20 | 1 | 0.9929 | no | False | False |
| NURECA | 2026-08-10 | HINDADH | 2026-08-17 | 5 | 1.004 | no | True | False |
| NURECA | 2026-08-10 | VIRAT | 2026-08-17 | 5 | 1.002 | no | True | False |
| PRETAILDVR | 2013-04-10 | FRLDVR | 2013-04-11 | 1 | 1.019 | no | False | False |
| RADHIKAJWE | 2026-09-15 | HTEL | 2026-09-16 | 1 | 0.9833 | no | True | False |
| RBZJEWEL | 2026-09-07 | DEEPA | 2026-09-08 | 1 | 1.019 | no | True | False |
| SHAHALLOYS | 2026-09-02 | LUMINO | 2026-09-03 | 1 | 0.981 | no | False | False |
| SHEKHAWATI | 2026-08-14 | VEDAVAAG | 2026-08-17 | 1 | 0.9907 | no | False | False |
| SHEKHAWATI | 2026-08-14 | VIVOBIOT | 2026-08-17 | 1 | 1.018 | no | False | False |
| SHEKHAWATI | 2026-08-14 | STLSTRINF | 2026-08-18 | 2 | 0.9881 | no | False | False |
| SHRENUJ | 2017-01-23 | BHANDARI | 2017-01-30 | 4 | 1.018 | no | False | False |
| SPECIALITY | 2026-08-13 | LEAPIND | 2026-08-14 | 1 | 0.9901 | no | False | False |
| SPECIALITY | 2026-08-13 | MUKESHB | 2026-08-17 | 2 | 1.004 | no | False | False |
| SPECIALITY | 2026-08-13 | NTCIND | 2026-08-17 | 2 | 0.9868 | no | False | False |
| SPECIALITY | 2026-08-13 | POEL | 2026-08-17 | 2 | 1.014 | no | False | False |
| SPECIALITY | 2026-08-13 | RRECL | 2026-08-17 | 2 | 0.9906 | no | False | False |
| SPECIALITY | 2026-08-13 | SVGLOBAL | 2026-08-17 | 2 | 0.9811 | no | False | False |
| SPECIALITY | 2026-08-13 | UDAYJEW | 2026-08-17 | 2 | 0.993 | no | False | False |
| SUNCLAYLTD | 2023-08-09 | TVSHLTD | 2023-08-10 | 1 | 1.001 | yes | False | False |
| SWANENERGY | 2014-02-03 | SWANCORP | 2014-02-04 | 1 | 1.002 | yes | False | True |
| TATAMOTORS | 2025-10-23 | TMPV | 2025-10-24 | 1 | 0.9937 | yes | True | False |
| TIL | 2026-08-10 | ARCL | 2026-08-17 | 5 | 1.017 | no | True | False |
| TIL | 2026-08-10 | BRIGHTBR | 2026-08-17 | 5 | 0.9961 | no | True | False |
| TOTAL | 2026-09-09 | HTEL | 2026-09-16 | 4 | 0.9862 | no | False | False |
| TRANSPEK | 2026-08-10 | SUNSHIEL | 2026-08-17 | 5 | 0.9963 | no | False | False |
| UFBL | 2026-08-11 | PERMAGN | 2026-08-17 | 4 | 1.003 | no | True | False |
| VIMALOIL | 2017-04-10 | SORILHOLD | 2017-04-18 | 5 | 0.9912 | no | False | False |
| VIVIMEDLAB | 2026-04-16 | COMFINTE | 2026-04-20 | 2 | 1.008 | no | True | False |
| WELSPUNIND | 2016-03-21 | WELSPUNLIV | 2016-03-22 | 1 | 0.9995 | yes | True | True |
| YAARII | 2021-12-14 | YAARI | 2021-12-15 | 1 | 1.006 | no | False | False |
| YAARII | 2021-12-14 | SHRIRAMPPS | 2021-12-20 | 4 | 0.9886 | no | False | True |

**Pairs named by a feed_symbol note** (64 distinct pairs; one side is stale; "old" is the member with the earlier last bar; `rename_pairs_feed_symbol_directed.csv`; sessions are first bar of the other symbol minus last bar of the old one; the ratio is blank where the histories overlap):

| old (earlier last bar) | old last bar | named other symbol | its first bar | sessions old last to new first | logged split/bonus factor | first close / (last close x factor) | within 2% | same ISIN in isin_symbol_map | map boundary | old ever eligible | log note (first 80 chars) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| DTIL | 2026-09-02 | DVL | 2013-01-01 | -3385 | 1 |  | n/a | no |  | False | feed_symbol=DTIL; Dividend - Re 1 Per Share |
| AEGISCHEM | 2015-09-16 | AEGISLOG | 2015-09-18 | 1 | 1 | 1.158 | no | yes | continuous / pure_rename | False | feed_symbol=AEGISLOG; Face Value Split From Rs 10 To Rs 1 |
| AMIORG | 2025-04-24 | ACUTAAS | 2025-04-25 | 1 | 0.5 | 0.9714 | no | yes | continuous / pure_rename | True | feed_symbol=ACUTAAS; Face Value Split (Sub-Division) - From Rs 10/- Per Share To |
| BOROSIL | 2020-02-19 | BORORENEW | 2020-02-20 | 1 | 1 | 0.9459 | no | yes | feed ['DEMERGER'] within 45d / demerger_merger | False | feed_symbol=BORORENEW; Dividend- Rs 2.50 Per Share |
| CADILAHC | 2015-10-06 | ZYDUSLIFE | 2015-10-07 | 1 | 1 | 0.9942 | yes | yes | continuous / pure_rename | True | feed_symbol=ZYDUSLIFE; Face Value Split (Sub-Division) - From Rs 5/- Per Share T |
| DAAWAT | 2017-02-07 | LTFOODS | 2017-02-08 | 1 | 1 | 1.199 | no | yes | continuous / pure_rename | False | feed_symbol=LTFOODS; Fv Splt Frm Rs 10 To Re 1 |
| DEEPIND | 2020-09-29 | DEEPENR | 2020-09-30 | 1 | 1 | 0.9797 | no | yes | feed ['DEMERGER'] within 45d / demerger_merger | False | feed_symbol=DEEPENR; Annual General Meeting And Dividend Re.0.60 Per Share |
| EXCEL | 2022-09-27 | LANDSMILL | 2022-09-28 | 1 | 0.0667 | 1.108 | no | yes | continuous / pure_rename;nan / nan | False | feed_symbol=LANDSMILL; Bonus 2:1 |
| GAL | 2016-10-13 | SHAH | 2016-10-14 | 1 | 1 | 1.019 | yes | yes | continuous / pure_rename | False | feed_symbol=SHAH; Face Value Split From Rs 10 To Re 1 |
| GUJFLUORO | 2019-07-24 | GFLLIMITED | 2019-07-25 | 1 | 1 | 1.008 | yes | yes | feed ['DEMERGER'] within 45d / demerger_merger | False | feed_symbol=GFLLIMITED; Interim Dividend Rs 1.50 Per Share |
| GUJGASLTD | 2026-06-30 | GUJENERGY | 2026-07-01 | 1 | 1 | 1.04 | no | yes | feed ['DEMERGER'] within 45d / demerger_merger | True | feed_symbol=GUJENERGY; Face Value Split (Sub-Division) - From Rs 10/- Per Share  |
| INFIBEAM | 2017-08-31 | CCAVENUE | 2017-09-01 | 1 | 1 | 0.9582 | no | yes | continuous / pure_rename | True | feed_symbol=CCAVENUE; Annual General Meeting/Face Value Split (Sub-Division) - F |
| ITDCEM | 2015-08-21 | CEMPRO | 2015-08-24 | 1 | 1 | 0.909 | no | yes | continuous / pure_rename | False | feed_symbol=CEMPRO; Face Value Split (Sub-Division) - From Rs 10/- Per Share To  |
| KPIT | 2019-02-25 | BSOFT | 2019-02-26 | 1 | 1 | 0.9972 | yes | yes | feed ['MERGER'] within 45d / demerger_merger | True | feed_symbol=BSOFT; Annual General Meeting/Dividend Re 0.90/- Per Share |
| MAX | 2016-02-25 | MFSL | 2016-02-26 | 1 | 1 | 1.049 | no | yes | feed ['MERGER'] within 45d / demerger_merger | True | feed_symbol=MFSL; Annual General Meeting And Dividend Rs.2.20 Per Share |
| MCDOWELL-N | 2018-06-15 | UNITDSPR | 2018-06-18 | 1 | 1 | 0.983 | yes | yes | continuous / pure_rename | True | feed_symbol=UNITDSPR; Face Value Split (Sub-Division) - From Rs 10/- Per Share T |
| MINDAIND | 2016-09-12 | UNOMINDA | 2016-09-14 | 1 | 1 | 1.085 | no | yes | continuous / pure_rename | False | feed_symbol=UNOMINDA; Face Value Split From Rs 10 To Rs 2 |
| PHILIPCARB | 2018-04-19 | PCBL | 2018-04-20 | 1 | 1 | 1.05 | no | yes | continuous / pure_rename | True | feed_symbol=PCBL; Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs |
| PITTILAM | 2015-04-16 | PITTIENG | 2015-04-17 | 1 | 1 | 1.063 | no | yes | continuous / pure_rename | False | feed_symbol=PITTIENG; Face Value Split (Sub-Division) - From Rs 10/- Per Share T |
| SUNCLAYLTD | 2023-08-09 | TVSHLTD | 2023-08-10 | 1 | 1 | 1.001 | yes | yes | feed ['DEMERGER'] within 45d / demerger_merger | False | feed_symbol=TVSHLTD; Interim Dividend Rs 9 Per Share (Purpose Revised) |
| SWANENERGY | 2014-02-03 | SWANCORP | 2014-02-04 | 1 | 1 | 1.002 | yes | yes | continuous / pure_rename | False | feed_symbol=SWANCORP; Face Value Split From Rs 2/- To Re 1/- |
| TATAMOTORS | 2025-10-23 | TMPV | 2025-10-24 | 1 | 1 | 0.9937 | yes | yes | feed ['DEMERGER'] within 45d / demerger_merger | True | feed_symbol=TMPV; Annual General Meeting And Dividend Rs.2/- Per Share |
| TIPSINDLTD | 2023-04-20 | TIPSMUSIC | 2023-04-21 | 1 | 0.1 | 0.9597 | no | yes | continuous / pure_rename | False | feed_symbol=TIPSMUSIC; Face Value Split (Sub-Division) - From Rs 10/- Per Share  |
| TWL | 2015-04-23 | TITAGARH | 2015-04-24 | 1 | 1 | 0.9056 | no | yes | continuous / pure_rename | True | feed_symbol=TITAGARH; Face Value Split (Sub-Division) - From Rs 10/- Per Share T |
| WELSPUNIND | 2016-03-21 | WELSPUNLIV | 2016-03-22 | 1 | 1 | 0.9995 | yes | yes | continuous / pure_rename | True | feed_symbol=WELSPUNLIV; Interim Div - Rs 6/- Per Share + Face Value Split (Sub-D |
| FRL | 2016-05-10 | FEL | 2016-05-25 | 11 | 1 | 0.1827 | no | yes | feed ['MERGER'] within 45d / demerger_merger | True | feed_symbol=FEL; Scheme Of Arrangement |
| FRLDVR | 2016-05-10 | FELDVR | 2016-05-25 | 11 | 1 | 0.1303 | no | yes | feed ['MERGER'] within 45d / demerger_merger | False | feed_symbol=FELDVR; Scheme Of Arrangement |
| HEG | 2026-09-04 | HEGAM | 2026-09-22 | 11 | 1 | 0.3198 | no | yes | feed ['DEMERGER'] within 45d / demerger_merger | True | feed_symbol=HEGAM; Face Value Split (Sub-Division) - From Rs 10/- Per Share To R |
| JUBILANT | 2021-02-03 | JUBLPHARMA | 2021-02-18 | 11 | 1 | 0.7678 | no | yes | feed ['DEMERGER'] within 45d / demerger_merger | True | feed_symbol=JUBLPHARMA; Annual General Meeting And Dividend Rs.3/- Per Share |
| AMTEKINDIA | 2015-06-08 | CASTEXTECH | 2015-07-07 | 21 | 1 | 1.711 | no | yes | price step 1.711 without a feed event / other | True | feed_symbol=CASTEXTECH; Annual General Meeting/Dividend - Re 0.10/- Per Share (P |
| SHARRESLTD | 2014-10-01 | CREST | 2014-11-17 | 26 | 1 | 0.8589 | no | yes | gap of 25 sessions / other | False | feed_symbol=CREST; Annual General Meeting / Dividend - Re 0.50/- Per Share |
| SIGNETIND | 2015-01-29 | SIGNET | 2015-03-13 | 30 | 1 | 1.077 | no | yes | gap of 29 sessions / other | False | feed_symbol=SIGNETIND; Annual General Meeting / Dividend Re.0.50 Per Share |
| AVANTI | 2015-01-29 | AVANTIFEED | 2015-04-15 | 50 | 1 | 0.986 | yes | yes | gap of 49 sessions / other | False | feed_symbol=AVANTI; Annual General Meeting/Dividend Of Re.1/- Per Share |
| THEBYKE | 2015-01-29 | BYKE | 2015-04-15 | 50 | 1 | 1.025 | no | yes | gap of 49 sessions / other | False | feed_symbol=THEBYKE; Annual General Meeting / Div Of Re.1/- Per Equity Share |
| GAMMNINFRA | 2021-07-19 | AJRINFRA | 2021-10-12 | 58 | 1 | 0.625 | no | yes | gap of 57 sessions / other | False | feed_symbol=AJRINFRA; Bonus 1:34 |
| MIRCELECTR | 2026-05-18 | ONIDA | 2026-08-11 | 59 | 1 | 0.9531 | no | yes | gap of 58 sessions / other | True | feed_symbol=ONIDA; Rights 5:13 @Premium Rs.5 |
| LSIL | 2023-08-09 | LLOYDSENGG | 2023-11-12 | 64 | 1 | 0.8856 | no | yes | gap of 63 sessions / other | True | feed_symbol=LLOYDSENGG; Annual General Meeting/Dividend - Rs 0.05 Per Share |
| TIDEWATER | 2021-07-14 | VEEDOL | 2021-10-18 | 64 | 0.2 | 0.5617 | no | yes | continuous / pure_rename | True | feed_symbol=VEEDOL; Bonus 1:1/Face Value Split (Sub-Division) - From Rs 10/- Per |
| MEGASOFT | 2025-11-06 | SIGMAADV | 2026-02-09 | 65 | 1 | 0.8908 | no | yes | gap of 64 sessions / other | False | feed_symbol=SIGMAADV; Rights 2:3 |
| ORIENTABRA | 2023-07-12 | ORIENTCER | 2023-10-16 | 65 | 1 | 1.102 | no | yes | gap of 64 sessions / other | False | feed_symbol=ORIENTCER; Annual General Meeting And Final Dividend Re.0.35 Per Sha |
| SONAMCLOCK | 2023-10-25 | SONAMLTD | 2024-01-29 | 65 | 1 | 1.104 | no | yes | gap of 64 sessions / other | False | feed_symbol=SONAMLTD; Bonus 1:1 |
| ATLANTA | 2023-12-13 | ATLANTAA | 2024-03-18 | 66 | 1 | 0.8951 | no | yes | gap of 65 sessions / other | False | feed_symbol=ATLANTAA; Annual General Meeting / Dividend - Re 0.24/- Per Share |
| MAGMA | 2021-06-08 | POONAWALLA | 2021-09-13 | 66 | 1 | 1.2 | no | yes | gap of 65 sessions / other | True | feed_symbol=POONAWALLA; Annual General Meeting /Dividend Re 0.80 Per Equity Shar |
| SAH | 2025-06-02 | AERONEU | 2025-09-08 | 68 | 1 | 1.018 | yes | yes | gap of 67 sessions / other | False | feed_symbol=AERONEU; Dividend - Rs 0.50 Per Share |
| VIKASGLOB | 2014-02-28 | VIKASECO | 2014-06-13 | 70 | 0.1 | 1.199 | no | yes | continuous / pure_rename | False | feed_symbol=VIKASECO; Face Value Split From Rs 10/- To Re 1/- |
| 8KMILES | 2020-09-23 | SECURKLOUD | 2021-02-02 | 90 | 1 | 2.443 | no | yes | gap of 89 sessions / other | True | feed_symbol=SECURKLOUD; Bonus 1:3/Face Value Split (Sub-Division) - From Rs 10/- |
| GODHA | 2022-01-27 | AURIGROW | 2022-06-21 | 98 | 0.1 | 1.119 | no | yes | continuous / pure_rename | False | feed_symbol=AURIGROW; Bonus 1:1 |
| BINANIIND | 2025-04-17 | BILVYAPAR | 2025-09-15 | 103 | 1 | 0.5491 | no | yes | gap of 102 sessions / other | False | feed_symbol=BILVYAPAR; Annual General Meeting And Dividend Rs.3/- Per Share |
| YAARI | 2025-05-28 | IBULLSLTD | 2025-12-09 | 134 | 1 | 1.138 | no | yes | gap of 133 sessions / other | False | feed_symbol=IBULLSLTD; Demerger |
| TRIL | 2024-05-13 | TARIL | 2025-02-01 | 183 | 1 | 1.396 | no | yes | gap of 182 sessions / other | True | UNSUPPORTED BONUS 1:9 (factor 0.9000); feed_symbol=TARIL; Bonus 1:9; evidence: r |
| TTKHEALTH | 2014-12-23 | TTKHLTCARE | 2015-12-02 | 233 | 1 | 1.257 | no | yes | gap of 232 sessions / other | False | feed_symbol=TTKHEALTH; Annual General Meeting And Dividend Rs.3.50 Per Share |
| GISOLUTION | 2023-04-06 | TPHQ | 2024-06-10 | 291 | 1 | 0.1264 | no | no |  | False | UNSUPPORTED SPLIT 1:10 (factor 0.1000); feed_symbol=TPHQ; Face Value Split (Sub- |
| GET&D | 2023-09-29 | GVT&D | 2025-01-06 | 314 | 1 | 4.538 | no | yes | gap of 313 sessions / other | False | feed_symbol=GVT&D; Annual General Meeting/Dividend - Rs 1.80 Per Share |
| SALONACOT | 2015-01-29 | SALONA | 2016-06-16 | 341 | 1 | 1.093 | no | yes | gap of 340 sessions / other | False | feed_symbol=SALONACOT; Annual General Meeting And Dividend Re.1/- Per Share |
| COMPUAGE | 2015-01-29 | COMPINFO | 2016-07-07 | 355 | 1 | 1.026 | no | yes | gap of 354 sessions / other | False | feed_symbol=COMPUAGE; Agm And Final Dividend Rs. 2/- Per Share ( 20%) |
| WEIZFOREX | 2020-02-26 | DELPHIFX | 2021-09-01 | 376 | 1 | 1.383 | no | yes | gap of 57 sessions / other | False | feed_symbol=DELPHIFX; Annual General Meeting/Final Dividend Rs.2.50 Per Share An |
| SPYL | 2023-11-20 | SHEKHAWATI | 2025-08-11 | 429 | 1 | 25.35 | no | no |  | False | UNSUPPORTED SPLIT 1:10 (factor 0.1000); feed_symbol=SHEKHAWATI; Face Value Split |
| PERIATEA | 2014-01-10 | PKTEA | 2015-10-20 | 436 | 1 | 1.29 | no | yes | gap of 435 sessions / other | False | feed_symbol=PERIATEA; Annual Geneeral Meeting/Div.Rs.3/- Per Share |
| HYDROS&S | 2015-01-29 | KINGFA | 2016-11-15 | 442 | 1 | 3.32 | no | yes | gap of 441 sessions / other | False | feed_symbol=HYDROS&S; Annual General Meeting / Div.Re.0.60 Per Share |
| STAMPEDE | 2020-06-18 | GATECH | 2023-12-12 | 867 | 1 | 1.833 | no | yes | gap of 866 sessions / other | False | UNSUPPORTED BONUS 1:4 (factor 0.8000); feed_symbol=GATECH; Bonus 1:4; evidence:  |
| SMOBILITY | 2014-08-18 | DIGISPICE | 2019-09-17 | 1252 | 1 | 0.2495 | no | yes | continuous / pure_rename | False | feed_symbol=DIGISPICE; Interim Dividend - Re 0.15/- Per Share (Purposed Revised) |
| KRITIIND | 2015-01-29 | KRITI | 2021-11-01 | 1672 | 1 | 14.58 | no | yes | gap of 1671 sessions / other | False | feed_symbol=KRITIIND; Annual General Meeting/Dividend Re 0.15 Per Share |
| ALSTOMT&D | 2016-09-12 | GVT&D | 2025-01-06 | 2061 | 1 | 6.227 | no | yes | continuous / pure_rename | False | feed_symbol=GVT&D; Annual General Meeting/ Dividend Rs 1.80/- Per Share |
| IBWSL | 2017-04-17 | IBULLSLTD | 2025-12-09 | 2145 | 1 | 0.3643 | no | yes | continuous / pure_rename | False | feed_symbol=IBULLSLTD; Interim Dividend Re.1/- Per Equity Share |

Counts: 24 pairs have the named symbol's first bar within 5 sessions after the old last bar (all 24 exactly 1 session); of those, 9 also pass the 2% price test after the logged action, and 24 are the same ISIN in `data/reference/isin_symbol_map.csv`. 9 pairs satisfy both the price rule and the note within 5 sessions; 43 stale symbols match the price rule only. **Not confirmed none:** candidates exist under both rules; no mapping was written or used.

## 3. Gaps of more than 20 missing sessions between bars
6,433 runs in 1,613 symbols (`gaps_over_20_sessions.csv`: symbol, gap start, gap end, missing sessions, close before, first close after, ratio, fund/ETF flag, ever eligible, eligible before the gap, eligible after the gap).

Runs by length (sessions):

| 21-40 | 41-60 | 61-120 | 121-250 | >250 |
|---|---|---|---|---|
| 1712 | 1769 | 2354 | 405 | 193 |

Runs by ratio (first close after / close before):

| <0.5 | 0.5-0.9 | 0.9-1.1 | 1.1-2.0 | >2.0 |
|---|---|---|---|---|
| 237 | 2972 | 1899 | 1124 | 201 |

Runs where the symbol was eligible on a bar before and on a bar after the gap: 333 runs in 204 symbols (`gaps_symbol_eligible_before_and_after.csv`). By length: {'21-40': 47, '41-60': 140, '61-120': 127, '121-250': 14, '>250': 5}. By ratio: {'<0.5': 11, '0.5-0.9': 156, '0.9-1.1': 98, '1.1-2.0': 59, '>2.0': 9}. The 25 longest:

| symbol | gap start | gap end | missing sessions | close before | first close after | ratio |
|---|---|---|---|---|---|---|
| ATLASCYCLE | 2017-01-19 | 2025-01-02 | 1971 | 665.3 | 84.39 | 0.127 |
| COFFEEDAY | 2019-12-10 | 2021-04-30 | 347 | 43.85 | 36 | 0.821 |
| INDRAMEDCO | 2022-12-06 | 2024-03-07 | 314 | 85.1 | 175.4 | 2.061 |
| BCG | 2024-04-26 | 2025-07-18 | 307 | 14.7 | 16 | 1.088 |
| SDBL | 2019-05-28 | 2020-06-15 | 258 | 143.3 | 68.7 | 0.479 |
| CUPID | 2023-12-13 | 2024-10-25 | 217 | 933.1 | 74.06 | 0.079 |
| KAMOPAINTS | 2024-10-08 | 2025-08-01 | 205 | 25.84 | 9.22 | 0.357 |
| ALOKINDS | 2022-05-25 | 2023-02-28 | 193 | 22.25 | 14.15 | 0.636 |
| JSWENERGY | 2021-07-29 | 2022-04-22 | 182 | 253.4 | 329.6 | 1.301 |
| BESTAGRO | 2023-07-27 | 2024-04-09 | 175 | 1164 | 675 | 0.58 |
| AXISCADES | 2024-12-31 | 2025-09-08 | 172 | 639.9 | 1475 | 2.305 |
| BGRENERGY | 2024-03-02 | 2024-10-25 | 161 | 51.55 | 36.13 | 0.701 |
| NACLIND | 2025-04-28 | 2025-11-21 | 144 | 179.4 | 180.2 | 1.005 |
| COFFEEDAY | 2024-08-14 | 2025-02-28 | 138 | 35 | 25.53 | 0.729 |
| WALCHANNAG | 2023-06-08 | 2023-12-22 | 136 | 90.5 | 196.9 | 2.176 |
| RCOM | 2020-05-07 | 2020-11-09 | 131 | 0.85 | 1.5 | 1.765 |
| WEBELSOLAR | 2024-04-10 | 2024-10-07 | 122 | 556.4 | 1013 | 1.821 |
| OLECTRA | 2021-07-08 | 2022-01-03 | 122 | 248.8 | 831.5 | 3.343 |
| SAREGAMA | 2021-09-16 | 2022-03-11 | 122 | 4194 | 4856 | 1.158 |
| PURVA | 2024-04-19 | 2024-10-04 | 116 | 354.2 | 364.9 | 1.03 |
| INDSWFTLAB | 2024-08-19 | 2025-01-31 | 116 | 137 | 109.4 | 0.799 |
| ATGL | 2021-09-16 | 2022-02-25 | 113 | 1407 | 1588 | 1.129 |
| HGS | 2021-06-17 | 2021-11-18 | 106 | 2540 | 2963 | 1.167 |
| ADANIENSOL | 2021-09-16 | 2022-02-11 | 103 | 1944 | 1915 | 0.985 |
| DBREALTY | 2021-12-15 | 2022-05-13 | 102 | 43.35 | 63.25 | 1.459 |

Runs by start year: {'2013': 580, '2014': 549, '2015': 104, '2016': 122, '2017': 428, '2018': 297, '2019': 360, '2020': 681, '2021': 631, '2022': 445, '2023': 628, '2024': 750, '2025': 513, '2026': 345}.

## 4. Terminal symbols with no rename lead: eligible and held
| definition of 'no rename lead' | symbols | ever eligible | eligible 2016-2026 | fund/ETF | held in any stored run | near_52w_high 4B: symbols (trades) | pullback_uptrend | short_term_reversal | riskadj_momentum |
|---|---|---|---|---|---|---|---|---|---|
| A: no price-rule match and not named by any feed_symbol note (the task's definition) | 750 | 126 | 104 | 24 | 84 | 16 (29) | 60 (288) | 76 (648) | 18 (40) |
| B: strict, no price-rule match and no note-named successor starting within 5 sessions | 803 | 137 | 113 | 24 | 91 | 18 (32) | 64 (321) | 82 (687) | 20 (53) |
| C: A and no same-ISIN successor row in isin_symbol_map | 712 | 123 | 102 | 16 | 82 | 16 (29) | 60 (288) | 74 (645) | 18 (40) |

Trades held counts are all trades of those symbols in the stored runs (near_52w_high 4B, family_batch1 run1 = pullback_uptrend and short_term_reversal, riskadj_momentum run1). Of those trades, the number with an exit date after the symbol's last bar (definition A): near_52w_high 4B 3, pullback_uptrend 1, short_term_reversal 1, riskadj_momentum 3. For all 870 stale symbols (leads included): 103 distinct symbols were held in at least one stored run. Symbol lists: `tables_summary.json` and `summary.json` (key `q4.held`).

## 5. Official NSE files that would confirm renames, mergers, suspensions and delistings (nothing downloaded; no mapping guessed)
Verification status: **in repo** = the repo's code or data already names/holds it; **seen** = appeared in this session's web search results (nseindia.com pages); **unverified** = named from memory, not confirmed by anything in this session or the repo.

| purpose | official NSE source | status | held by the repo or lake now |
|---|---|---|---|
| listed securities with ISIN, series, date of listing | `EQUITY_L.csv` (archives.nseindia.com/content/equities/EQUITY_L.csv) | in repo, seen | yes: `data/reference/EQUITY_L.csv` (2,608 rows, committed 2026-10-21, a snapshot of currently listed names only); table `securities_master` (2,965 rows, created 2026-10-21). 193 stale symbols appear in the EQUITY_L copy; the other 677 do not. It carries no delisted or suspended history. |
| symbol changes (old symbol, new symbol, date) | the equities symbol-change list on nseindia.com, which I recall as `symbolchange.csv` in the same `content/equities` folder | **unverified** (a search did not find it) | no |
| company name changes | the name-change list on nseindia.com (file name unknown to me) | **unverified** | no |
| mergers, demergers, amalgamations, other corporate actions, with ISIN and subject text | `api/corporates-corporateActions` (nseindia.com) | in repo | yes: `data/reference/nse_corporate_actions_raw.csv` (3.9 MB) and `corporate_actions_evidence.csv`; table `corporate_actions_log`. Per-symbol queries, so a symbol that no longer exists under its old name returned nothing for later actions (`verified_corporate_actions.csv` notes this for TATAMOTORS). |
| delistings, companies removed from listing, dissemination-board and exit-option lists | NSE "Security Information" page (`invest/content/diss_secinfo.htm`) and the delisting circulars; the listing-compliance page | seen (mostly xlsx/pdf there, not a csv); exact downloadable file **unverified** | no |
| suspensions | NSE trading-suspension / delisting circulars (PDF) | **unverified** as a machine-readable file | no |
| series changes (EQ to BE/BZ, trade-for-trade) | daily bhavcopy files carry the `SERIES` column: `sec_bhavdata_full_DDMMYYYY.csv` (nsearchives.nseindia.com/products/content/) and `cmDDMMMYYYYbhav.csv.zip` | in repo (URLs in the downloader), seen | the lake keeps EQ only; 3,405 fetched days are logged in `bhavcopy_fetch_log`; non-EQ rows were not kept (`DATA_GUIDE.md` D.2) |
| surveillance lists | `asm_securities.csv`, `gsm_securities.csv`, `api/reportASM`, `api/reportGSM` | in repo | table `asm_gsm_daily_snapshot` (253 days, forward only; KI-003) |
| ISIN per symbol per day (the basis for same-ISIN renames) | the `ISIN` column of the bhavcopy files | in repo | yes: `data/reference/isin_symbol_map.csv` (853 rows, derived, not an NSE file) and table `isin_symbol_map`; an earlier inventory of symbols that stop trading is `docs/data_audit/historical_universe.csv` (`Claude_Docs/STOCKBOT_PREREQUISITE_FIXES_REPORT.md` section A4: 1,198 stop trading) |

The repo holds none of the symbol-change, name-change, delisting or suspension lists.

## Reproduction and checks
`finsight.db` sha256 after both scripts and this report: `dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752`. Both scripts are read-only on the database; no shared file, strategy, ledger or stored result was edited. Files in `docs/data_audit/stale_symbols/`: `stale_symbols.csv`, `rename_candidates_price.csv` (all 5,950 examined rows), `rename_candidates_price_within_2pct.csv`, `rename_pairs_feed_symbol.csv`, `rename_pairs_feed_symbol_directed.csv`, `stale_symbols_in_isin_symbol_map.csv`, `stale_with_isin_map_successor.csv`, `gaps_over_20_sessions.csv`, `gaps_symbol_eligible_before_and_after.csv`, `summary.json`, `tables_summary.json`.
