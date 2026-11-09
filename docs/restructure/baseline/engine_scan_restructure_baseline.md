# Engine-path scan (restructure_baseline)

Database: `F:\Projects\Ravi\StockBot\finsight.db`.  Adjusted with `engine_core.adjustments.get_adjusted_series` from `corporate_actions_log` rows keyed by lake symbol.

Names scanned: 1607.

```
large moves before adjustment : 764
large moves after adjustment  : 267
  removed by adjusting        : 499
  created by adjusting        : 2
```

Remaining by category:

```
category
after_gap_in_EQ_series     209
near_unadjusted_event       40
residual_no_explanation     18
```

Equivalence with `build_candidate_dicts` (the candidate path itself): 120 (symbol, eval_date) samples, 0 mismatches.
