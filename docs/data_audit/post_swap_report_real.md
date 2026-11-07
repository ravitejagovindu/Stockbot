# Post-swap report (real)

Database: `F:\Projects\Ravi\StockBot\finsight.db`.  Failures: none

## Rows and trading days per year (equities; lake after swap vs staging vs Yahoo archive)

```
  yr  lake_rows  lake_days  lake_symbols  staging_rows  yahoo_archive_rows
2013     331315        250          1587        331315                 NaN
2014     325090        244          1569        325090                 NaN
2015     356689        248          1604        356689                 NaN
2016     370662        247          1632        370662                 NaN
2017     368537        248          1678        368537                 NaN
2018     367880        246          1663        367880                 NaN
2019     368578        245          1686        368578                 NaN
2020     379782        252          1731        379782            352207.0
2021     389770        248          1889        389770            366212.0
2022     438894        248          2009        438894            393243.0
2023     446991        246          2118        446991            410302.0
2024     467396        249          2265        467396            437714.0
2025     531765        249          2511        531765            476866.0
2026     485198        196          2931        455691            393361.0
```

## Continuity at the 2019-12-31 -> 2020-01-01 base change

```
   symbol  last_2019   close first_2020  close_2020  ratio
 RELIANCE 2019-12-31 1514.05 2020-01-01     1509.60 0.9971
 HDFCBANK 2019-12-31 1272.10 2020-01-01     1278.60 1.0051
KOTAKBANK 2019-12-31 1684.35 2020-01-01     1674.05 0.9939
```

## All symbols present on both sides of 2019-12-31 | 2020-01-01: close ratio beyond +-25% (splits/bonuses on that day aside)

```
 n_symbols  over_25pct
      1499           0
```

## NIFTY50_INDEX: equity session dates (to 2026-09-30) without an index row

```
 missing dates
       0  None
```

## INDIA_VIX: equity session dates (to 2026-09-30) without an index row

```
 missing dates
       0  None
```

## Lake rows by source label

```
                                                                  source    rows      first       last
                                                    (unlabelled, pre-F2) 2515960 2013-01-01 2026-10-16
https://archives.nseindia.com/content/indices/ind_close_all_01012021.csv       1 2021-01-01 2021-01-01
https://archives.nseindia.com/content/indices/ind_close_all_01012024.csv       1 2024-01-01 2024-01-01
https://archives.nseindia.com/content/indices/ind_close_all_01012025.csv       1 2025-01-01 2025-01-01
https://archives.nseindia.com/content/indices/ind_close_all_01012026.csv       1 2026-01-01 2026-01-01
https://archives.nseindia.com/content/indices/ind_close_all_01022020.csv       2 2020-02-01 2020-02-01
https://archives.nseindia.com/content/indices/ind_close_all_01022025.csv       1 2025-02-01 2025-02-01
https://archives.nseindia.com/content/indices/ind_close_all_01022026.csv       2 2026-02-01 2026-02-01
https://archives.nseindia.com/content/indices/ind_close_all_02032024.csv       2 2024-03-02 2024-03-02
https://archives.nseindia.com/content/indices/ind_close_all_05052021.csv       1 2021-05-05 2021-05-05
https://archives.nseindia.com/content/indices/ind_close_all_05072021.csv       1 2021-07-05 2021-07-05
https://archives.nseindia.com/content/indices/ind_close_all_11052021.csv       1 2021-05-11 2021-05-11
https://archives.nseindia.com/content/indices/ind_close_all_12112023.csv       2 2023-11-12 2023-11-12
https://archives.nseindia.com/content/indices/ind_close_all_14112020.csv       2 2020-11-14 2020-11-14
https://archives.nseindia.com/content/indices/ind_close_all_15022021.csv       1 2021-02-15 2021-02-15
https://archives.nseindia.com/content/indices/ind_close_all_16012018.csv       2 2018-01-16 2018-01-16
https://archives.nseindia.com/content/indices/ind_close_all_17022021.csv       1 2021-02-17 2021-02-17
https://archives.nseindia.com/content/indices/ind_close_all_18052024.csv       2 2024-05-18 2024-05-18
https://archives.nseindia.com/content/indices/ind_close_all_19022024.csv       1 2024-02-19 2024-02-19
https://archives.nseindia.com/content/indices/ind_close_all_20012024.csv       2 2024-01-20 2024-01-20
https://archives.nseindia.com/content/indices/ind_close_all_20052021.csv       1 2021-05-20 2021-05-20
https://archives.nseindia.com/content/indices/ind_close_all_22012021.csv       1 2021-01-22 2021-01-22
https://archives.nseindia.com/content/indices/ind_close_all_25052021.csv       1 2021-05-25 2021-05-25
https://archives.nseindia.com/content/indices/ind_close_all_26122022.csv       1 2022-12-26 2022-12-26
https://archives.nseindia.com/content/indices/ind_close_all_27102019.csv       2 2019-10-27 2019-10-27
https://archives.nseindia.com/content/indices/ind_close_all_28022015.csv       1 2015-02-28 2015-02-28
https://archives.nseindia.com/content/indices/ind_close_all_30092026.csv       2 2026-09-30 2026-09-30
https://archives.nseindia.com/content/indices/ind_close_all_30102016.csv       2 2016-10-30 2016-10-30
https://archives.nseindia.com/content/indices/ind_close_all_31052021.csv       1 2021-05-31 2021-05-31
                                                        nse_bhavcopy_raw 3118323 2013-05-11 2026-09-30
                                                         yahoo:^INDIAVIX      10 2014-12-15 2016-06-20
                                                             yahoo:^NSEI       2 2015-12-01 2016-06-20
```

## Rows still under a renamed traded symbol (should be 0)

```
 rows_left_under_renamed_symbol
                              0
```

## Listing-age gate input for the renamed names (securities_master listing date vs first lake date)

```
 renamed_names  with_listing_date  no_listing_date_uses_first_lake_date  lake_history_starts_before_listing_date
           334                296                                    38                                      153
```

## Examples: lake history starts before the master's listing date

```
    symbol first_lake_date listing_date  lake_start_before_listing  no_listing_date
   ACLGATI      2013-01-01          NaN                       True             True
     ALPHA      2021-12-29   2026-10-01                       True            False
ALPL30IETF      2020-08-18   2026-10-01                       True            False
  AURIGROW      2022-06-21          NaN                       True             True
  AUTOBEES      2022-01-25   2026-10-01                       True            False
  AUTOIETF      2022-01-18   2026-10-01                       True            False
   BANKADD      2023-01-06   2026-10-01                       True            False
  BANKBETA      2021-02-19   2026-10-01                       True            False
  BANKIETF      2022-09-02   2026-10-01                       True            False
BANKNIFTY1      2014-12-11   2026-10-01                       True            False
      BFSI      2021-08-05   2026-10-01                       True            False
 BHARATFIN      2013-01-01          NaN                       True             True
  BKMINDST      2015-04-16          NaN                       True             True
BNKETFAXIS      2020-11-09   2026-10-01                       True            False
BSE500IETF      2021-10-29   2026-10-01                       True            False
```

## Duplicate (symbol, date) pairs

```
 dup_pairs
         0
```