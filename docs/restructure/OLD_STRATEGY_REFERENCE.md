# Old strategy reference (recovery record)

Everything that is specific to the OLD strategy (or undecided) and therefore is not in the shared config (`stockbot/config/shared.yaml`). Values are copied unchanged from `strategy_config.yaml` at tag `pre-restructure`.
Until Phase 10 `strategy_config.yaml` itself stays in the tree (the old pipeline and the golden checks still read it through `stockbot/config/legacy_loader.py`); after Phase 10 recover it with `git show pre-restructure:strategy_config.yaml`.

Recovery: tag `pre-restructure`; path `strategy_config.yaml` (all keys); code paths are listed per item.

## Old-strategy keys (leave the shared config; become the old strategy's own parameters)

| key | value | note |
|---|---|---|
| `universe.volume_breakout_multiplier` | `0` | Gate 6 (disabled with 0) |
| `universe.relative_strength_lookback_days` | `63` | Gate 7 input |
| `universe.relative_strength_top_pct` | `0` | Gate 7 (disabled with 0) |
| `execution.min_rr_at_fill` | `1.5` | Q3 decided: per-strategy; value recorded in OLD_STRATEGY_REFERENCE |
| `risk.atr_period` | `14` | ATR for the stop and trailing; the indicator function itself is shared |
| `risk.atr_stop_multiplier` | `2.0` | Stop A |
| `risk.donchian_period` | `30` | Stop B |
| `risk.trailing_stop_atr_period` | `14` | exit policy |
| `risk.trailing_stop_atr_multiplier` | `2.5` | exit policy |
| `risk.trailing_stop_atr_multiplier_kill_switch` | `1.5` | exit policy (also depends on the macro kill switch: Q4) |
| `risk.min_rr_ratio` | `1.5` | Q3 decided: per-strategy; value recorded in OLD_STRATEGY_REFERENCE |
| `risk.max_rr_cap` | `6.0` | Q3 decided: per-strategy; value recorded in OLD_STRATEGY_REFERENCE |
| `entry_filters.trend_filter_enabled` | `True` |  |
| `entry_filters.trend_fast_sma` | `50` |  |
| `entry_filters.trend_slow_sma` | `200` |  |
| `entry_filters.breakout_required` | `True` |  |
| `entry_filters.breakout_lookback` | `20` |  |
| `entry_filters.rs_lookback_days` | `63` |  |
| `trade_management.time_decay_sessions` | `20` | exit policy |
| `trade_management.binary_event_block_days` | `14` | Q10 decided: mechanism (event within N days, known as of date) is shared in universe/data; whether to block entries is a per-strategy parameter; value 14 recorded in OLD_STRATEGY_REFERENCE |
| `data.resistance_lookback_days` | `252` | 52-week target |
| `parabolic_stop.enabled` | `True` | exit policy |
| `parabolic_stop.acceleration_threshold_atr` | `3.0` | exit policy |
| `parabolic_stop.acceleration_lookback_days` | `5` | exit policy |
| `parabolic_stop.parabolic_atr_multiplier` | `1.0` | exit policy |
| `partial_profit.enabled` | `True` | exit policy |
| `partial_profit.exit_ladder` | `[{'rr_trigger': 1.0, 'exit_pct': 12}]` | exit policy |
| `profit_ratchet.enabled` | `True` | exit policy |
| `profit_ratchet.active_in_bull` | `False` | exit policy (reads the macro bull flag: Q4) |
| `profit_ratchet.rungs` | `[{'trigger_rr': 1.0, 'lock_rr': 0.0}, {'trigger_rr': 2.0, 'lock_rr': 1.0}, {'trigger_rr': 3.0, 'lock_rr': 2.0}]` | exit policy |

## Undecided (macro regime, Q4): stay in strategy_config.yaml; decided in Phase 6 Part A

| key | value | note |
|---|---|---|
| `macro.nifty_kill_sma_period` | `200` | Q4: macro regime |
| `macro.bull_entry_sma_period` | `50` | Q4 |
| `macro.vix_kill_threshold` | `22.0` | Q4 |
| `macro.nifty_reentry_sma_period` | `20` | Q4 |
| `macro.vix_reentry_threshold` | `20.0` | Q4 |
| `macro.reentry_consecutive_sessions` | `3` | Q4 |
| `risk.max_concurrent_positions_bull` | `12` | DROPPED (STOP 3 ruling D2): equal to the normal cap, no behaviour change |

## Per-strategy values decided at the Stop-1 review (recorded unchanged)

- Q3 `risk.min_rr_ratio` = 1.5; `risk.max_rr_cap` = 6.0; `execution.min_rr_at_fill` = 1.5 (per-strategy parameters; a strategy may have no target).
- Q10 `trade_management.binary_event_block_days` = 14 (the mechanism - is an earnings/corporate-action event within N days, known as of the date - is shared; whether to block entries is a per-strategy parameter; a meeting date counts as known only after its intimation timestamp).
- Q11 `gates.*` and Q8 `paper_criteria.*` are shared validation / acceptance config, not per-strategy: see `shared.yaml` (`validation_gates`, `paper_criteria`) and `CONFIG_DIFF.md`.

## Removed code / files (path at tag `pre-restructure`)

| item | removed in | what it did | note |
|---|---|---|---|
| `authorize_live.py` | Phase 4.2 | validated `audit.json` (clean tree, config hash, `audit.sha256`, all pass gates) and wrote `authorized_deployment.json` with the HEAD SHA, then committed it | git-SHA authorization lock dropped for now; the live authorization design returns in the strategy phase |
| `authorized_deployment.json` | Phase 4.2 | the authorized SHA record | same |
| `live_runner/git_lock.py` | Phase 4.2 | `verify_git_lock()` at startup and before each scheduled run (exit if HEAD differs from the authorized SHA, allowing one auth-file-only commit); `read_authorized_info()` for the health endpoint and the paper start date | health keeps its keys with empty values; `scripts/paper_report.py` has a local stub returning no authorization date |
| `tests/unit/test_phase4_lock.py` (7 tests) | Phase 4.2 | tests of the two items above | see `REMOVED_TESTS.md` |

More rows are added at each phase that removes old-strategy code (Phase 5 stops, Phase 6 entry filters / lifecycle exits / screener gates 6-7, Phase 10 deletions).
