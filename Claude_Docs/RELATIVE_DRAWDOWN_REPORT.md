# Relative drawdown table: report (DESCRIPTIVE, NOT A GATE, NO VERDICT CHANGES)

Run 2026-11-19 16:30 to 16:33 IST (finished well before 19:30), worktree `F:\Projects\Ravi\StockBot_wt_reldd`, branch `relative-drawdown` (from master 9341542). Script `scripts/relative_drawdown_table.py` (read-only; run lock and db check as any short step); outputs `docs/shared/relative-drawdown/TABLE.json` and `TABLE.md`. No stored result file, gate, gates hash, `shared.yaml`, ledger row, spec or old results folder was changed; no backtest, baseline or `validate_family` was run; `finsight.db` was opened read-only (the NIFTY50_INDEX closes only).

## Summary: the table (all 9 runs; every alpha cross-check passed)
Strategy max drawdown is the STORED gate value; matched account = the Nifty matched to the run's daily invested share with idle cash at 6.5% a year (the stored B2 functions); full Nifty = the 100% invested index over the same window. Test A: strategy DD <= matched DD; B: <= 1.25 x matched DD; C: <= full Nifty DD. **Not a gate; nothing here changes any verdict.**

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


Reading (descriptive only): test A is met by none of the nine runs; B by Low volatility, Momentum (any day) and Momentum (any day) half risk; C by six runs and missed by Short-term reversal, Pullback in uptrend and Momentum (any day) with restricted-series prices. The strategies' worst falls mostly sit in 2018 to 2020 or 2024 to 2025, while the matched account's worst fall is mostly the COVID crash (2020-02/03), so the two do not compare like for like: the matched account holds only the share the strategy was invested in at each close, and at the COVID date the half-risk runs were lightly invested (matched DD of the monthly half-risk run only 7.47%, which is why its ratio is 3.17 although its own drawdown fell from 34.3% to 23.7%). The ratio therefore rises when exposure is thin at the time of the market's fall, independent of how the strategy itself behaves. Short-term reversal (97.2%) and Pullback (69.4%) never recovered their equity peaks.

## Monthly momentum runs: overlap of the worst falls
Neither monthly run (family_batch2 and family_batch6) has any overlap: the strategy's worst fall is 2024-02-08 to 2025-10-14 (batch 2) and 2024-02-08 to 2025-11-06 (batch 6), the matched account's worst fall is the COVID crash (2020-02-12 to 2020-03-23 and to 2020-03-12). During the strategy's worst fall the matched account moved +3.50% (batch 2) and +7.16% (batch 6); during the matched account's worst fall the strategy moved -12.06% (batch 2) and -7.27% (batch 6). So the two worst falls are in different periods: in 2024 to 2025 the strategy fell while the matched Nifty account rose.

## Alpha cross-check per run (recomputed vs stored, 4 decimals)
Recomputed with `stockbot.validation.benchmark_alpha` from each run's `daily.json`, `equity_curve.json` and the Nifty closes. New-format runs are checked against both `gates.json` (`alpha.cash_credited.alpha_pct`) and `benchmark.json` (`gate_alpha_pct`); the first run (earlier rules, cash not credited) against the raw alpha stored in `b2_benchmark.json`. The strategy depth recomputed from the stored equity curve also equals the stored `max_drawdown_pct` for every run. Risk-free rate 6.5% in every run.
| run | stored alpha | recomputed | equal to 4 decimals |
|---|---|---|---|
| 52-week high (raw alpha, b2_benchmark.json) | -4.7913 | -4.7913 | yes |
| Short-term reversal | -35.6472 | -35.6472 | yes (both files) |
| Pullback in uptrend | -14.2502 | -14.2502 | yes (both files) |
| Momentum (monthly), batch 2 | 5.4538 | 5.4538 | yes (both files) |
| Low volatility | -2.4336 | -2.4336 | yes (both files) |
| Momentum (any day), batch 4 | 7.0611 | 7.0611 | yes (both files) |
| Momentum (any day), batch 5 | 3.0158 | 3.0158 | yes (both files) |
| Momentum (monthly), half risk | 2.7115 | 2.7115 | yes (both files) |
| Momentum (any day), half risk | 3.3119 | 3.3119 | yes (both files) |
No run failed, so every run's numbers are used.

## db check
| | |
|---|---|
| `finsight.db` sha256 before / after | `81e90beff580f962628596031978c918b06e8876cd9ac5bfeb39b3b2377e50d0` / identical (`docs/shared/relative-drawdown/sha_before.txt`, `sha_after.txt`) |
| `guard status --json` before vs after | byte-identical; correction counter 0 |
| Short-step check printed by the script | "unchanged; verified size, mtime_ns, -wal size, correction counter, sealed dates and table digests; correction counter 0"; the run lock was taken like any short step |

## What ran and what did not
Ran: the script once over all nine stored runs, the cross-checks, the overlap block for the two monthly runs, hash and guard status before and after. Did not run: any backtest, baseline, benchmark script, gates script or `validate_family`; no stored file was rewritten; no verdict, gate or ledger row was touched. Limits: the matched account is a price-return account with the risk-free credit on the idle share (no dividends in the lake); drawdown dates are calendar dates of the stored daily series; "recovery" is the first later date at or above the previous peak value.
