# Engine-path scan (restructure_stop5)

Database: `F:\Projects\Ravi\StockBot\finsight.db`.  Read through the as-of view; adjusted with `stockbot.data.adjustments.get_adjusted_series` from `corporate_actions_log` rows keyed by lake symbol.

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

Comparison with the FROZEN result of the old path (tests/golden): identical.
