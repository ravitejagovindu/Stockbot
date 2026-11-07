# F2 — Bhavcopy staging validation report

Generated 2026-11-07 09:30.

## 1. Download log (by year and status)

| year | status | n | rows_total |
|---|---|---|---|
| 2013 | HOLIDAY_OR_MISSING | 13 | 0 |
| 2013 | OK | 248 | 328958 |
| 2014 | HOLIDAY_OR_MISSING | 18 | 0 |
| 2014 | OK | 243 | 323812 |
| 2015 | HOLIDAY_OR_MISSING | 14 | 0 |
| 2015 | OK | 247 | 355279 |
| 2016 | HOLIDAY_OR_MISSING | 15 | 0 |
| 2016 | OK | 246 | 369146 |
| 2017 | HOLIDAY_OR_MISSING | 12 | 0 |
| 2017 | OK | 248 | 368537 |
| 2018 | HOLIDAY_OR_MISSING | 15 | 0 |
| 2018 | OK | 246 | 367880 |
| 2019 | HOLIDAY_OR_MISSING | 11 | 0 |
| 2019 | OK | 250 | 376008 |
| 2020 | HOLIDAY_OR_MISSING | 1 | 0 |
| 2020 | OK | 261 | 393432 |
| 2021 | OK | 261 | 410124 |
| 2022 | HOLIDAY_OR_MISSING | 1 | 0 |
| 2022 | OK | 259 | 458217 |
| 2023 | OK | 260 | 472632 |
| 2024 | HOLIDAY_OR_MISSING | 1 | 0 |
| 2024 | OK | 261 | 489930 |
| 2025 | HOLIDAY_OR_MISSING | 10 | 0 |
| 2025 | OK | 251 | 536710 |
| 2026 | OK | 195 | 480242 |

## 2. Trading-calendar cross-check against the lake's Nifty dates

| nifty_dates_without_bhavcopy | bhavcopy_dates_without_nifty | example_missing |
|---|---|---|
| 12 | 791 | 2025-02-01,2026-10-01,2026-10-05,2026-10-06,2026-10-07,2026-10-08,2026-10-09,2026-10-12,2026-10-13,2026-10-14,2026-10-15,2026-10-16 |

## 3. Staging (true raw) vs current lake (Yahoo-adjusted) for 2020-01-01..2026-09-30

| year | staging_rows | lake_rows | n_matched | vol_equal_rate | close_within_0_2pct | mean_old_over_new | min_old_over_new |
|---|---|---|---|---|---|---|---|
| 2020 | 393432 | 352207 | 275372 | 0.6279 | 0.1901 | 0.8209 | 0.0093 |
| 2021 | 410124 | 366212 | 292141 | 0.7722 | 0.2006 | 0.8304 | 0.0095 |
| 2022 | 458217 | 393243 | 334167 | 0.8077 | 0.2330 | 0.8596 | 0.0097 |
| 2023 | 472632 | 410302 | 347882 | 0.8464 | 0.2652 | 0.8849 | 0.0099 |
| 2024 | 489930 | 437714 | 366580 | 0.8955 | 0.3019 | 0.9234 | 0.0486 |
| 2025 | 536710 | 476866 | 424899 | 0.9461 | 0.4131 | 0.9635 | 0.0470 |
| 2026 | 480242 | 393361 | 371772 | 0.9683 | 0.6400 | 0.9897 | 0.0663 |

Symbols: staging 3404, lake 2317, in both 2317, only in lake 0 (e.g. ).

Reading: `mean_old_over_new` < 1 and `close_within_0_2pct` far below 1 in early years shows the old lake rows are adjusted (split/bonus/dividend); `vol_equal_rate` shows whether Yahoo volumes equal NSE volumes.

## 4. Symbol continuity (A3) — ISINs traded under more than one symbol

399 ISINs / 853 symbol segments (see symbol_map.csv). First 25:

| isin | symbol | first_date | last_date | n_days |
|---|---|---|---|---|
| IN9623B01058 | PRETAILDVR | 2013-01-01 | 2013-04-10 | 70 |
| IN9623B01058 | FRLDVR | 2013-04-11 | 2016-05-10 | 754 |
| IN9623B01058 | FELDVR | 2016-05-25 | 2023-02-21 | 1540 |
| INE007B01023 | GEOJITBNPP | 2013-01-01 | 2017-03-01 | 999 |
| INE007B01023 | GEOJITFSL | 2017-03-02 | 2026-09-30 | 2366 |
| INE00FF01025 | AMIORG | 2025-04-25 | 2025-05-30 | 25 |
| INE00FF01025 | ACUTAAS | 2025-06-02 | 2026-09-30 | 331 |
| INE00LM01011 | SONAMCLOCK | 2022-04-07 | 2023-10-25 | 384 |
| INE00LM01011 | SONAMLTD | 2024-01-29 | 2024-05-09 | 68 |
| INE00ZE01026 | AHL | 2022-12-23 | 2025-01-29 | 518 |
| INE00ZE01026 | AFSL | 2025-05-05 | 2026-09-30 | 351 |
| INE010A01011 | PRISMCEM | 2013-01-01 | 2018-05-03 | 1289 |
| INE010A01011 | PRSMJOHNSN | 2018-05-04 | 2026-09-30 | 2076 |
| INE010B01027 | CADILAHC | 2015-10-07 | 2022-03-04 | 1583 |
| INE010B01027 | ZYDUSLIFE | 2022-03-07 | 2026-09-30 | 1128 |
| INE019C01026 | HCIL | 2013-01-01 | 2016-08-12 | 891 |
| INE019C01026 | HSCL | 2016-08-16 | 2026-09-30 | 2433 |
| INE019J01013 | MICROSEC | 2013-01-01 | 2016-11-21 | 862 |
| INE019J01013 | SASTASUNDR | 2016-11-22 | 2026-04-29 | 2106 |
| INE019J01013 | HEALTHX | 2026-04-30 | 2026-09-30 | 106 |
| INE020G01017 | AFL | 2013-01-01 | 2018-10-11 | 1187 |
| INE020G01017 | INSPIRISYS | 2018-10-12 | 2026-09-30 | 1224 |
| INE023M01027 | PRAKASHCON | 2013-01-01 | 2019-07-29 | 1448 |
| INE023M01027 | SETUINFRA | 2019-07-30 | 2022-11-16 | 377 |
| INE02WG01016 | WFL | 2022-01-17 | 2023-01-03 | 151 |

## 5. Historical universe from the daily files (A4)

3946 distinct EQ symbols; 2207 have raw data before 2020; 1198 stop trading (delisted or renamed) before the end.

| year | symbols |
|---|---|
| 2013 | 1608 |
| 2014 | 1587 |
| 2015 | 1618 |
| 2016 | 1654 |
| 2017 | 1691 |
| 2018 | 1682 |
| 2019 | 1703 |
| 2020 | 1743 |
| 2021 | 1897 |
| 2022 | 2041 |
| 2023 | 2178 |
| 2024 | 2304 |
| 2025 | 2552 |
| 2026 | 2935 |

## 6. Corporate-action factor cross-check (A1)

1116 split/bonus ex-dates in the NSE feed. Agreement: raw close-to-close ratio across the ex-date (within 20%) 764/776; NSE PrevClose field (within 3%) 2/1116 (the field is not adjusted by NSE, so it carries no information); Yahoo/raw ratio factor 407/413 (2020-2026 only). Disagreements: see factor_crosscheck.csv.

## 7. Large close-to-close moves (>40%) in staging

2472 moves; 1823 OPEN (no logged action within 3 days), of which 889 have a price of at least Rs5 on both days. See unexplained_moves.csv (disposition column to be completed by hand).
