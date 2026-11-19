# Relative drawdown table (DESCRIPTIVE, NOT A GATE, NO VERDICT CHANGES)

Strategy max drawdown (stored gate value) against the matched Nifty account (rebuilt with the stored B2 functions, idle cash at 6.5% a year) and against the full Nifty 50 over the run window. A: strategy DD <= matched DD; B: <= 1.25 x matched DD; C: <= full Nifty DD. **Not a gate; no verdict changes.**

| run | family | invested share (mean) | strategy DD % (peak, trough, recovery) | matched DD % (peak, trough, recovery) | full Nifty DD % (peak, trough, recovery) | strategy / matched | strategy / full Nifty | A | B | C | alpha check |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 52-week high | near_52w_high (K=1) | 0.738 | 30.05 (2018-08-28, 2020-05-18, 2021-06-02) | 18.12 (2020-01-14, 2020-04-03, 2020-08-18) | 38.44 (2020-01-14, 2020-03-23, 2020-11-09) | 1.66 | 0.78 | no | no | yes | equal to 4 decimals |
| Short-term reversal | family_batch1 (K=2) | 0.755 | 97.17 (2016-01-01, 2026-10-08, not recovered) | 26.65 (2020-01-24, 2020-03-23, 2020-10-08) | 38.44 (2020-01-14, 2020-03-23, 2020-11-09) | 3.65 | 2.53 | no | no | no | equal to 4 decimals |
| Pullback in uptrend | family_batch1 (K=2) | 0.702 | 69.38 (2017-10-30, 2026-03-09, not recovered) | 32.71 (2020-01-24, 2020-03-23, 2021-05-31) | 38.44 (2020-01-14, 2020-03-23, 2020-11-09) | 2.12 | 1.80 | no | no | no | equal to 4 decimals |
| Momentum (monthly) | family_batch2 (K=1) | 0.604 | 34.32 (2024-02-08, 2025-10-14, not recovered) | 16.98 (2020-02-12, 2020-03-23, 2020-08-18) | 38.44 (2020-01-14, 2020-03-23, 2020-11-09) | 2.02 | 0.89 | no | no | yes | equal to 4 decimals |
| Low volatility | family_batch3 (K=1) | 0.734 | 25.97 (2021-10-18, 2022-06-20, 2023-11-30) | 21.04 (2021-10-18, 2022-06-17, 2023-09-13) | 38.44 (2020-01-14, 2020-03-23, 2020-11-09) | 1.23 | 0.68 | no | yes | yes | equal to 4 decimals |
| Momentum (any day) | family_batch4 (K=1) | 0.803 | 36.15 (2018-01-09, 2020-03-23, 2020-09-15) | 31.41 (2020-01-14, 2020-03-23, 2020-11-11) | 38.44 (2020-01-14, 2020-03-23, 2020-11-09) | 1.15 | 0.94 | no | yes | yes | equal to 4 decimals |
| Momentum (any day), with restricted-series prices | family_batch5 (K=1) | 0.798 | 45.61 (2018-01-09, 2020-03-23, 2021-03-23) | 30.70 (2020-01-14, 2020-03-23, 2020-11-10) | 38.44 (2020-01-14, 2020-03-23, 2020-11-09) | 1.49 | 1.19 | no | no | no | equal to 4 decimals |
| Momentum (monthly), half risk | family_batch6 (K=2) | 0.319 | 23.68 (2024-02-08, 2025-11-06, not recovered) | 7.47 (2020-02-12, 2020-03-12, 2020-07-07) | 38.44 (2020-01-14, 2020-03-23, 2020-11-09) | 3.17 | 0.62 | no | no | yes | equal to 4 decimals |
| Momentum (any day), half risk | family_batch6 (K=2) | 0.446 | 24.87 (2018-01-09, 2020-03-23, 2021-05-06) | 21.96 (2020-01-14, 2020-03-23, 2021-01-04) | 38.44 (2020-01-14, 2020-03-23, 2020-11-09) | 1.13 | 0.65 | no | yes | yes | equal to 4 decimals |

## Monthly momentum runs: does the strategy's worst fall overlap the matched account's worst fall?

| run | strategy worst fall (peak to trough) | matched worst fall (peak to trough) | overlap (days) | share of strategy fall | trough inside the other fall | matched account change during strategy fall % | strategy change during matched fall % |
|---|---|---|---|---|---|---|---|
| Momentum (monthly) (family_batch2 (K=1)) | 2024-02-08 to 2025-10-14 | 2020-02-12 to 2020-03-23 | 0 | 0% | strategy trough in matched fall: no; matched trough in strategy fall: no | 3.50 | -12.06 |
| Momentum (monthly), half risk (family_batch6 (K=2)) | 2024-02-08 to 2025-11-06 | 2020-02-12 to 2020-03-12 | 0 | 0% | strategy trough in matched fall: no; matched trough in strategy fall: no | 7.16 | -7.27 |
