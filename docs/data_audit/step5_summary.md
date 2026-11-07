# Step 5 summary

Traded symbols in staging with a full 20-session ADTV: 3883; eligible (ADTV >= Rs25 crore on at least one session): **1743**, of which 63 have an INF ISIN (ETFs / funds, to be excluded from the equity universe).

Distinct ISINs among eligible symbols: 197; canonical names: 208; in classes demerger_merger: 9, other: 14.


## Large moves (>40%, no logged action within 3 days, price >= Rs5): 873

```
relevant_equity                                       False  True 
category                                                          
after_gap_in_EQ_series_or_suspension                    574     57
explained_by_logged_split_bonus_under_another_symbol     62     27
large_move_no_pattern                                    27     18
logged_split_bonus_on_a_different_date                    4      0
near_demerger_merger_rights_or_other                     35     16
probable_unlogged_split_or_consolidation                 52      1
```

Dispositions of the relevant equity moves (the stock passed the gate within 20 sessions before to 252 after):

```
disposition
REAL_MOVE_ACROSS_GAP    57
EXPLAINED               27
UNADJUSTED_EVENT        16
REAL_MOVE               13
MANUAL                   6
```


## Split/bonus events (grouped by symbol and ex-date) by tier and eligibility

```
elig              False  True 
tier                          
STRONG              124    353
UNSUPPORTED         101    158
WEAK                 87    248
WEAK_DIRECTIONAL     27     31
```

No-price-data events on eligible symbols:

```
reason
after the data window (2026-09-30)                   5
before staging starts (2013-01-01)                 135
symbol had no EQ-series rows around the ex-date      1
```


## Listing-age input for eligible names

Eligible canonical/traded names: 1758; placeholder `securities_master.listing_date` (>= 2026-04-01): 110; no master row: 211.
