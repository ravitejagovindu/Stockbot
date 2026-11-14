# pullback_uptrend: stage 2 report

Branch `pullback_uptrend` (master 8b07ece merged in). 2026-11-14. **No backtest on the real lake was run and no return, P&L or win rate was looked at.** Nothing is registered; the pre-registration is still DRAFT.

## Final spec hash
`81db6427ebc9e11980c2cbbfb86720c7e1e68eeb27073b05c95cc64ce4207044` (`SPEC.config_hash()`; also printed by `py -3 scripts/research_pullback_uptrend.py --out ...` without `--execute`, with `asof_view`, window 2016-01-01 to 2026-10-16 and shared-config hash `816ee5cb71b0618ed5c2065efc6de39f0f4a59ccf51862ceb3928d3665732bb3`). SPEC now carries `expected_trade_rate` 31.7, `smallest_edge_of_interest` 0.15, `prereg_ref` `docs/strategies/pullback_uptrend/PREREGISTRATION.md`; rule numbers unchanged.

## What ran
0. Pre-checks: tree clean, branch `pullback_uptrend`, HEAD = `origin/pullback_uptrend` = f5300aa; DB sha256 matched. `git merge origin/master` (8b07ece): clean, no conflicts (merge commit cded0bf). Strategy and study tests: 32 passed.
1. SPEC fields set; the one test that asserted them empty was updated (28 passed).
2. **Re-count under the new sector rule** (counts only, no database read: `signal_count_pullback_uptrend.py --assemble` on the three cached stage-1 candidate lists, whose occupancy model uses the shared `sector_for`, now `UNMAPPED:<SYMBOL>` per unmapped symbol). Results in `docs/strategies/pullback_uptrend/counts_new_sector_rule/` (stage-1 `counts/` kept):

| | entries | per month |
|---|---|---|
| no sector cap | 4,659 | 39.0 (unchanged) |
| sector cap, stage 1 (unmapped pooled in one sector) | 3,786 | **31.7** (registered `expected_trade_rate`) |
| sector cap, new rule (each unmapped symbol its own sector) | 4,338 | **36.3** |

   Sector blocks fall from 19,628 to 5,658; sessions at the 12-position limit rise from 99 to 225. `expected_trade_rate` NOT changed; the difference (36.3 against 31.7, 4.6 a month, about 15%) is for your decision.
3. `PREREGISTRATION.md` finalised (still DRAFT): K = 2 (short_term_reversal, pullback_uptrend), joint Westfall-Young Max-T, B = 10,000, blocks 2 and 3 months, both must be significant; B1 20 draws per trade, seed 20261111; B2 Nifty matched to the invested share, cash credited, pre-tax; gates (min_trades 40, min_expectancy_r 0.15, min_profit_factor 1.3, max_drawdown_pct 20.0, min_alpha_pct 0.0 pre-tax cash-credited) with hash `e9b6407f908ff102dd25d9bc3b21a78a52b24c0ea082bba2cd3bb08f81188054` (recomputed from the shared config with `prereg_lock.gates_hash`: equal); decision rule; limitations (913 of 1,385 ever-eligible symbols unmapped, no dividends, no historical ASM/GSM, unadjusted demerger/rights actions, registered run on `STOCKBOT_VIEW=memory`); section 13 registration snippet with the TWO specs and `--expect-k 2`.
4. Scripts (strategy-owned, copied from the near_52w_high pattern and renamed; the shared modules `SectorLookup`, `benchmark_alpha`, `random_baseline`, the runner are imported, not copied): `scripts/research_pullback_uptrend.py` (`--execute` required; without it prints plan, spec hash, config hash, `asof_view`), `baseline_matched_random_pullback_uptrend.py`, `benchmark_nifty_matched_pullback_uptrend.py`, `evaluate_validation_gates_pullback_uptrend.py`. The run manifest and `baseline_meta.json` carry `asof_view`; so do the benchmark and gates JSON.
   **Layout contract of `validate_family.py --member ID=DIR`:** `DIR/run/` (manifest.json with the strategy id under `strategies` and `window`, trades.json, equity_curve.json, daily.json; blocked.json is also written) and `DIR/baseline/` (actual_trades.csv, baseline_draws.csv). It opens the lake only with `--lake` (alpha gate). Our member dir is `docs/strategies/pullback_uptrend/results_run1/`; benchmark.json and gates.json sit beside `run/` and `baseline/`.
5. Tests on fixture lakes only (`tests/unit/test_research_pullback_uptrend.py`, `tests/unit/test_pullback_uptrend_validation_scripts.py`, 12 tests): plan without `--execute` runs nothing and creates nothing (both views), `--execute` without `--out` refused, a used output folder refused, the run through `run_backtest` (fixed_hold_5 exit at session 6, stop fires), memory-view run byte-identical to the SQL-view run (trades, daily, equity, blocked) with only `asof_view` differing in the manifest, baseline (own exit and 8% stop distance, memory view byte-identical to SQL), benchmark and gates on the real script output, the member directory loads in `validate_family.load_member`, and a `validate_family.py` dry run on two fixture members (`--expect-k 2`, one member refused).
6. `docs/strategies/pullback_uptrend/RUN_COMMANDS.md` (cmd and Git Bash; `STOCKBOT_DB`, `STOCKBOT_VIEW=memory`; output `results_run1/`; research, baseline, benchmark, gates, joint validation; times and memory). Not run.
7. `BRIEF.md` and `STATUS.md` updated at the commits.

## Final gates (default SQL view, `STOCKBOT_VIEW` unset)
- **G1** (`tests/unit tests/integration`): 1,029 passed, 8 skipped, 0 failed (9 min 55 s).
- **Full G2** (`STOCKBOT_DATA_TESTS=1 STOCKBOT_FINAL_CHECK=1 pytest tests`): 1,158 passed, 0 failed (15 min 1 s).
- **G3** (`test_g3_fixture_baseline.py`): 2 passed.
- **finsight.db sha256** before and after: `dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752` (unchanged). The tests ran with the other strategy's session active; nothing was killed for memory.

## Shared files touched
None. Changed or added, all strategy-owned or under this strategy's docs: `stockbot/strategies/pullback_uptrend/strategy.py` (SPEC values), `tests/unit/test_pullback_uptrend_strategy.py` (SPEC assertion), the four scripts, the two test files, and under `docs/strategies/pullback_uptrend/`: `PREREGISTRATION.md`, `RUN_COMMANDS.md`, `BRIEF.md`, `STATUS.md`, `counts_new_sector_rule/`. This report. No engine, validation, config, ledger, guide or other strategy's file was edited (the guide tests exempt `*_pullback_uptrend.py` scripts; G1/G2 pass).

## What did not run
- No real-lake backtest, baseline, benchmark, gates or family validation (they wait for your registration).
- No power figure; no `power_calc.py`-style arithmetic for this member.
- No SQL-view run of the whole pipeline on the real lake for this strategy (the memory view is relied on, per its two proofs).
- The plan-only step was run once on the real configuration (prints the hashes; opens nothing in the lake for data).

## Deviations
- The re-count reused the cached stage-1 candidate lists (signals do not depend on the sector rule; only the occupancy model does) instead of re-scoring the lake.
- The gates script keeps the `--t1` option copied from near_52w_high; it reads the single-strategy T1 file, which the family tool does not write, so `RUN_COMMANDS.md` tells you not to use it (the family conclusion comes from `validate_family.py`).
- `tests/unit/test_validate_family.py` (shared, not edited) still builds a K = 4 family; my dry run uses K = 2.
- The window is the common 2016-01-01 to 2026-10-16 as decided; the first 163 sessions are empty for this member.

## Decisions needed
1. **Expected trade rate:** the registered 31.7 comes from the old pooled-UNKNOWN sector rule; under the rule the run will use the model gives 36.3 a month. Keep 31.7 as decided, or change it before registration (it would change the spec hash).
2. **Baseline time:** this member expects about 4,000+ trades against near_52w_high's 774, so the matched-random baseline will take longer than the quoted 22 minutes (to be measured); confirm you accept that, or whether to run it detached.
3. **Registration:** register family_batch1 (K = 2) on master with the two spec hashes; this branch's hash is above.
