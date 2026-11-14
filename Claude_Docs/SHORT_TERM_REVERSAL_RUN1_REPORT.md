<!-- run 1 report, committed on branch short_term_reversal; the same facts text is committed in both branches -->
# family_batch1 registered runs: facts report (run 1)

Registered on master df7486b (ledger row_hash `ae3f43cf7ade3cd4733fee6f9acb638b78245f61b509f7180d2f8fd817cf41d4`, budget 2, gates sha256 `e9b6407f908ff102dd25d9bc3b21a78a52b24c0ea082bba2cd3bb08f81188054`). Each member ran ONCE; no parameter, code or config change, no re-run, no ledger row written. Environment: `STOCKBOT_DB=F:\Projects\Ravi\StockBot\finsight.db`, `STOCKBOT_VIEW=memory`. Facts only; no interpretation.

## Run log
- Both worktrees were clean and fast-forwarded to df7486b before the runs. Plans printed without `--execute` matched: spec hashes 57b86c47... (short_term_reversal) and 81db6427... (pullback_uptrend), window 2016-01-01 to 2026-10-16, asof_view memory.
- Restarts: **none** (every step exited 0).
- finsight.db sha256 before the runs (2026-11-14, before launch and again before the joint validation) and after (checked at the end): `dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752`. Each baseline's own before/after fingerprint: `unchanged: true` for both members.

## Timings and peak memory (wall clock; peak working set of the step's process)
| step | short_term_reversal | pullback_uptrend |
|---|---|---|
| research | 90.3 min (5416 s), 985 MB, 17:24 to 18:55 | 121.3 min (7281 s), 986 MB, 17:25 to 19:26 |
| baseline | 107.8 min (6471 s), 990 MB, 18:55 to 20:43 | 97.8 min (5866 s), 993 MB, 19:26 to 21:04 |
| benchmark | 0.5 min (30 s), 983 MB, 20:43 to 20:43 | 0.4 min (25 s), 985 MB, 21:04 to 21:04 |
| gates | 0.5 min (30 s), 986 MB, 20:43 to 20:44 | 0.4 min (25 s), 988 MB, 21:04 to 21:04 |
| joint validation (once, reversal worktree) | 2.6 min (155 s), 1012 MB | (same run) |

## short_term_reversal
### Manifest
- git sha `df7486be0f9ba5d01afdfa2cebe9a9f3b01cd29e`; spec hash `57b86c47d0c5cbdc1325e19230c103b84bc08c6be6b495aadb99d1aa84ec6168` (version 1.0.0, exit policy fixed_hold_5); shared-config hash `816ee5cb71b0618ed5c2065efc6de39f0f4a59ccf51862ceb3928d3665732bb3`; asof_view `memory`; window 2016-01-01 to 2026-10-16; initial equity 1,000,000; data snapshot finsight.db size 3,432,767,488, last session 2026-10-16.
### Trades
- closed 4288; usable 4275; END_OF_WINDOW 5; excluded (corporate action) 8; entries per month 32.88; invested share mean 0.755 (p5 0.304, p95 1.000); open positions mean 7.76, max 12.
- Baseline B1: draws per trade 20, seed 20261111, usable trades 4275, pairs kept 4247, dropped pairs 28 (0.65%), draws 83418, flag None; unfilled draws by reason {'GAP_THROUGH_STOP': 440, 'CORP_ACTION_ON_EXEC_DATE': 474, 'GAP_UP_TOO_LARGE': 1083, 'OPEN_AT_END': 25, 'NO_BAR_OR_ALREADY_HELD': 23, 'SIZE_ZERO': 37}.
### Gates (point estimates; shared `validation_gates`, read at run time)
| gate | registered value | observed | 95% interval | met |
|---|---|---|---|---|
| min_trades | >= 40 | 4275.0000 | - | met |
| min_expectancy_r | >= 0.15 | -0.2590 | -0.337 to -0.185 | NOT met |
| min_profit_factor | >= 1.3 | 0.7653 | 0.649 to 0.910 | NOT met |
| max_drawdown_pct | <= 20.0 | 97.1744 | - | NOT met |
| min_alpha_pct | >= 0.0 | -35.6472 | -43.414 to -27.372 | NOT met |
- all gates met: False
### Alpha, implied return, drawdown
- raw alpha -36.7846 pp (strategy CAGR -28.0447%, matched benchmark CAGR 8.7400%); cash-credited pre-tax alpha (the gate) -35.6472 pp (strategy CAGR -26.9072%); years 10.790; risk-free 6.5%.
- implied annual return (non-gating): 396.20 trades/year x -0.2590 R x 1.0% = -102.60% a year, beside the matched benchmark CAGR 8.7400%.
- max drawdown 97.1744%. Benchmark file: gate alpha -35.6472, mean invested share 0.7547.
- Descriptive sub-periods (no pass or fail): 2016-2019: trades 1640, expectancy -0.2431 R, profit factor 0.7554, max drawdown 81.39%, alpha -41.99 pp; 2020-2026: trades 2635, expectancy -0.2689 R, profit factor 0.8030, max drawdown 84.92%, alpha -31.79 pp

## pullback_uptrend
### Manifest
- git sha `df7486be0f9ba5d01afdfa2cebe9a9f3b01cd29e`; spec hash `81db6427ebc9e11980c2cbbfb86720c7e1e68eeb27073b05c95cc64ce4207044` (version 1.0.0, exit policy fixed_hold_5); shared-config hash `816ee5cb71b0618ed5c2065efc6de39f0f4a59ccf51862ceb3928d3665732bb3`; asof_view `memory`; window 2016-01-01 to 2026-10-16; initial equity 1,000,000; data snapshot finsight.db size 3,432,767,488, last session 2026-10-16.
### Trades
- closed 4156; usable 4144; END_OF_WINDOW 9; excluded (corporate action) 3; entries per month 31.88; invested share mean 0.702 (p5 0.000, p95 1.000); open positions mean 7.60, max 12.
- Baseline B1: draws per trade 20, seed 20261111, usable trades 4144, pairs kept 4135, dropped pairs 9 (0.22%), draws 81085, flag None; unfilled draws by reason {'CORP_ACTION_ON_EXEC_DATE': 515, 'GAP_UP_TOO_LARGE': 930, 'GAP_THROUGH_STOP': 256, 'NO_BAR_OR_ALREADY_HELD': 25, 'OPEN_AT_END': 21, 'SIZE_ZERO': 48}.
### Gates (point estimates; shared `validation_gates`, read at run time)
| gate | registered value | observed | 95% interval | met |
|---|---|---|---|---|
| min_trades | >= 40 | 4144.0000 | - | met |
| min_expectancy_r | >= 0.15 | -0.0951 | -0.142 to -0.050 | NOT met |
| min_profit_factor | >= 1.3 | 0.8909 | 0.765 to 1.044 | NOT met |
| max_drawdown_pct | <= 20.0 | 69.3771 | - | NOT met |
| min_alpha_pct | >= 0.0 | -14.2502 | -22.541 to -5.138 | NOT met |
- all gates met: False
### Alpha, implied return, drawdown
- raw alpha -16.0090 pp (strategy CAGR -8.6283%, matched benchmark CAGR 7.3807%); cash-credited pre-tax alpha (the gate) -14.2502 pp (strategy CAGR -6.8696%); years 10.790; risk-free 6.5%.
- implied annual return (non-gating): 384.06 trades/year x -0.0951 R x 1.0% = -36.53% a year, beside the matched benchmark CAGR 7.3807%.
- max drawdown 69.3771%. Benchmark file: gate alpha -14.2502, mean invested share 0.7018.
- Descriptive sub-periods (no pass or fail): 2016-2019: trades 1276, expectancy -0.1249 R, profit factor 0.8279, max drawdown 51.16%, alpha -20.89 pp; 2020-2026: trades 2868, expectancy -0.0818 R, profit factor 0.9429, max drawdown 44.77%, alpha -10.30 pp

## Joint validation (`scripts/validate_family.py --expect-k 2`, B = 10,000, seed 20261111, one run)
- K = 2; months 130; one-sided, family-wise alpha 0.05; Westfall-Young step-down Max-T, joint across members. Output: `F:\Projects\Ravi\StockBot_runs\family_batch1\validate_family.json` (copy in `docs/strategies/family_batch1/results_run1/`).
### T1: adjusted p-values (a member is found only if significant at BOTH block lengths)
| member | block (months) | observed mean D(m) | SE | t | unadjusted p | adjusted p | significant |
|---|---|---|---|---|---|---|---|
| short_term_reversal | 2 | -7.0944 | 1.0616 | -6.6830 | 1.0000 | 1.0000 | False |
| short_term_reversal | 3 | -7.0944 | 1.0616 | -6.6830 | 1.0000 | 1.0000 | False |
| pullback_uptrend | 2 | -1.8207 | 0.4404 | -4.1345 | 1.0000 | 1.0000 | False |
| pullback_uptrend | 3 | -1.8207 | 0.4404 | -4.1345 | 1.0000 | 1.0000 | False |
- found by T1: []; dual rule per member: {'pullback_uptrend': {'dual_significant': False}, 'short_term_reversal': {'dual_significant': False}}; family rejects: False.
### T2 (paired statistics; reported only), pooled window
- **short_term_reversal**: paired trades 4160; pooled n_trades 4160, entry dates 1979.

  | horizon (sessions) | actual mean | random mean | paired diff | clustered t | perm p | status |
  |---|---|---|---|---|---|---|
  | 1 | -0.2053 | -0.2030 | -0.0023 | -0.024 | 0.9802 | Not Sig |
  | 5 | -0.2703 | -0.0102 | -0.2601 | -1.695 | 0.0496 | Suggestive |
  | 10 | -0.2927 | 0.1754 | -0.4681 | -2.594 | 0.0094 | Significant |
  | 20 | -0.0501 | 0.8465 | -0.8965 | -3.575 | 0.0002 | Significant |

  net R expectancy: actual -0.2485; random (trade-averaged) -0.0392; paired diff mean -0.2094, clustered t -7.431, one-sided skill p 1.0000.
- **pullback_uptrend**: paired trades 4076; pooled n_trades 4076, entry dates 1871.

  | horizon (sessions) | actual mean | random mean | paired diff | clustered t | perm p | status |
  |---|---|---|---|---|---|---|
  | 1 | 0.0557 | -0.2014 | 0.2572 | 4.832 | 0.0000 | Significant |
  | 5 | 0.1657 | 0.0247 | 0.1410 | 1.595 | 0.1014 | Not Sig |
  | 10 | 0.2547 | 0.2055 | 0.0491 | 0.407 | 0.6802 | Not Sig |
  | 20 | 0.6060 | 0.7352 | -0.1292 | -0.742 | 0.4374 | Not Sig |

  net R expectancy: actual -0.0936; random (trade-averaged) -0.0355; paired diff mean -0.0581, clustered t -4.209, one-sided skill p 1.0000.
- (secondary, reported only; trades with a blanked forward return are left out of T2; the 2016-2019 and 2020-2026 windows are in the JSON.)
### T3 (placebo size check of the joint procedure)
- size 0.036 (SE 0.0059), 36 rejections in 1000 replications, B = 1000, seed 20261111; limits 0.025 to 0.075; verdict: **size ok**; per-member rejection rate {'pullback_uptrend': 0.022, 'short_term_reversal': 0.016}.
### The tool's stated conclusion per member
- **pullback_uptrend**: NOT DEMONSTRATED (registered rule not met; this is not evidence of no edge)
- **short_term_reversal**: NOT DEMONSTRATED (registered rule not met; this is not evidence of no edge)

## Files
Committed: manifest.json, gates.json, benchmark.json, baseline_meta.json, this report, and every other result file under 20 MB. Sizes and anything left untracked (with path) are listed in `docs/strategies/<id>/results_run1/FILES.md`. Step logs (`results_run1_*.log` next to the results folder) are untracked.
