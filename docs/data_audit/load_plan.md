# Load plan, unadjusted events and post-adjustment scan

## 1. Events vs rows (SPLIT/BONUS only)

An event = one (symbol, ex-date); a same-day split+bonus is one event and two rows.

```
                  events  BONUS  SPLIT  rows
tier                                        
STRONG               477    250    253   503
UNSUPPORTED          259    142    137   279
WEAK                 335    168    182   350
WEAK_DIRECTIONAL      58     45     17    62
TOTAL               1129    605    589  1194
```

Rows by stored type, and what survives the table's UNIQUE(symbol, ex_date, action_type) with INSERT OR IGNORE (two OTHER rows on one date collapse into one):

```
             parsed_rows  after_UNIQUE  collapsed
stored_type                                      
BONUS                463           463          0
DEMERGER             108           108          0
DIVIDEND           20913         20913          0
MERGER                91            91          0
OTHER                650           630         20
RIGHTS               341           341          0
SPLIT                452           452          0
TOTAL              23018         22998         20
```

Price-moving feed rows by tier and stored type:

```
stored_type       BONUS  OTHER  SPLIT
tier                                 
STRONG              250      0    253
UNSUPPORTED           0    279      0
WEAK                168      0    182
WEAK_DIRECTIONAL     45      0     17
```

## 2. Unadjusted-event list (eligible equity names; `data/reference/unadjusted_events.csv`)

```
kind
demerger                    83
large_rights               105
manual_unadjusted_event      2
merger                      57
unsupported_bonus           15
unsupported_split            6
```

## 3. Post-adjustment scan (eligible equity names, price >= Rs5, |move| > 40%, lake 2013-01-01..2026-09-30)

Eligible names scanned: 1607. Events applied: 870 (tiers STRONG, WEAK, WEAK_DIRECTIONAL), applied on the first session on/after the ex-date.

```
large moves before adjustment : 764
large moves after adjustment  : 267
  removed by adjusting        : 499
  created by adjusting        : 2
```

Remaining moves by category:

```
category
after_gap_in_EQ_series     209
near_unadjusted_event       40
residual_no_explanation     18
```
