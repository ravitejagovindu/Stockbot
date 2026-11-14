# short_term_reversal: stage 2 report

Branch `short_term_reversal` (master 8b07ece merged). 2026-11-14. Stage 2 was taken over from a stopped session. **No backtest on the real lake was run and no return, P&L or win rate was looked at.** Nothing is registered; the pre-registration is still DRAFT.

## Final spec hash
`57b86c47d0c5cbdc1325e19230c103b84bc08c6be6b495aadb99d1aa84ec6168` (recomputed in this session with `SPEC.config_hash()`; equal to the figure the previous session reported). SPEC: `expected_trade_rate` 23.0, `smallest_edge_of_interest` 0.15, `prereg_ref` `docs/strategies/short_term_reversal/PREREGISTRATION.md`; rule numbers unchanged.

## State found, and what I kept or redid
Verified first: branch `short_term_reversal`, no merge or rebase in progress, no conflict markers, `git merge-base --is-ancestor origin/master HEAD` true (master 8b07ece merged by `ba007ab`), and the only files differing from master are this strategy's own (strategy, study script and wrapper, its tests, its docs, its stage-1 report). DB sha256 matched.

| item | verdict |
|---|---|
| merge commit `ba007ab` | kept |
| SPEC edit (prereg_ref, comment) | kept; trade rate and edge confirmed set; hash recomputed |
| study script and its test change to the per-symbol UNMAPPED rule | kept, with one addition (below) |
| `results_stage2/` re-count | **re-run and verified**; its sector stats were stale (old cache), now recomputed |
| `scripts/research_short_term_reversal.py`, `scripts/baseline_matched_random_short_term_reversal.py` | kept (proper copies, `asof_view` included) |
| `scripts/benchmark_nifty_matched_short_term_reversal.py`, `scripts/evaluate_validation_gates_short_term_reversal.py` | **redone**: they were thin wrappers importing the near_52w_high versions; replaced by proper copies (as for pullback_uptrend), so each output carries `asof_view` and nothing of another strategy's script can change this one's gates |
| `tests/unit/test_run_scripts_short_term_reversal.py` | **deleted and rewritten**: a half-applied path edit (it looked for `root/"run"` where the run is under `root/"str"/"run"`), one test ever passed. Replaced by `tests/unit/test_research_short_term_reversal.py` and `tests/unit/test_short_term_reversal_validation_scripts.py` |
| PREREGISTRATION.md, RUN_COMMANDS.md, BRIEF/STATUS | written or updated (steps 3, 6, 7) |

## What ran
- **Step 0:** strategy and study tests 52 passed after the merge.
- **Step 2, re-count** (counts only; no database read: `signal_count_short_term_reversal.py --assemble` on the four cached stage-1 parts). The occupancy model's sector figures come from the shared `sector_for` (every unmapped symbol its own sector). The cached rows still carried the old pooled-UNKNOWN sector figures (distinct sectors, largest sector per session); `assemble` now re-derives them from each session's proposed list under the current rule, relabels the cached UNKNOWN candidates as UNMAPPED, and the "largest sector share" now means the largest MAPPED sector. Results in `results_stage2/counts_new_sector_rule.{md,json}`:

| model, 2016-2026 | stage 1 (pooled) entries | per month | new rule entries | per month |
|---|---|---|---|---|
| position cap only | 4,772 | 37.48 | 4,772 | 37.48 |
| + sector cap | 3,523 | 27.67 | 4,553 | 35.76 |
| + sector cap and cash, 8 slots (the registered basis) | 2,931 | **23.02** | 3,263 | **25.63** |

  Sector blocks fall from 9,665 to 1,350; shared slots full 15.1% to 19.5% of sessions. The previous session's 25.63 is confirmed. `expected_trade_rate` NOT changed (23.0).
- **Step 3:** PREREGISTRATION.md finalised, still DRAFT: family_batch1, K = 2, joint Westfall-Young Max-T, B = 10,000, blocks 2 and 3 (both significant), B1 20 draws per trade seed 20261111, B2 Nifty matched to the invested share, gates hash `e9b6407f908ff102dd25d9bc3b21a78a52b24c0ea082bba2cd3bb08f81188054`, decision rule, limitations (913 of 1,385 ever-eligible symbols unmapped, no dividends, no historical ASM/GSM, unadjusted demerger and rights actions, registered run on `STOCKBOT_VIEW=memory`), section 13 registration snippet with the TWO specs and `--expect-k 2`. The obsolete `min_alpha_after_tax_pct -2.0` of the draft is replaced by `min_alpha_pct 0.0` (pre-tax, cash-credited). Both the model figure 25.63 and the registered 23.0 are recorded (sections 0 and 11).
- **Step 4, scripts** (strategy-owned; shared modules imported, not copied): research (`--execute` required; plan prints spec hash, config hash, shared-config hash, `asof_view`), baseline, benchmark, gates. **Layout for `validate_family.py --member ID=DIR`:** `DIR/run/` (manifest.json with the strategy id and window, trades.json, equity_curve.json, daily.json, blocked.json) and `DIR/baseline/` (actual_trades.csv, baseline_draws.csv, baseline_meta.json); our member directory is `docs/strategies/short_term_reversal/results_run1/` (same layout as pullback_uptrend). Manifest, baseline meta, benchmark and gates JSON carry `asof_view`.
- **Step 5, tests** (fixture lakes only, 14 tests): plan without `--execute` runs nothing and creates nothing (both views); `--execute` without `--out` refused; a used output folder refused; the run through `run_backtest` (fixed_hold_5, only `short_term_reversal` ids); memory-view run byte-identical to SQL-view run (trades, daily, equity, blocked; manifest differs only in `asof_view`); baseline (own exit, 8% stop distance) and its memory-view run byte-identical; benchmark and gates on the real script output (both views); proof that no near_52w_high-specific name or exit policy reaches the scripts or outputs; the member directory loads in `validate_family.load_member`; a `validate_family.py` dry run on two fixture members with `--expect-k 2` (one member refused).
- **Step 6:** `docs/strategies/short_term_reversal/RUN_COMMANDS.md` (cmd and Git Bash; `STOCKBOT_DB`, `STOCKBOT_VIEW=memory`; output `results_run1/`; research, baseline, benchmark, gates, joint validation; times and memory). Not run.

## Final gates (default SQL view, `STOCKBOT_VIEW` unset)
- **G1** (`tests/unit tests/integration`): 1,052 passed, 8 skipped, 0 failed (10 min 57 s).
- **Full G2** (`STOCKBOT_DATA_TESTS=1 STOCKBOT_FINAL_CHECK=1 pytest tests`): 1,181 passed, 0 failed (18 min 22 s).
- **G3** (`test_g3_fixture_baseline.py`): 2 passed.
- **finsight.db sha256** before and after: `dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752` (unchanged).

## Shared files touched
None. Changed or added, all strategy-owned: `stockbot/strategies/short_term_reversal/strategy.py` (SPEC values), `scripts/strategies/short_term_reversal/signal_count.py` and `tests/unit/test_short_term_reversal_signal_count.py` (new sector rule; the assemble step recomputes sector figures), the four `scripts/*_short_term_reversal.py`, the two new test files (one old one deleted), and under `docs/strategies/short_term_reversal/`: `PREREGISTRATION.md`, `RUN_COMMANDS.md`, `BRIEF.md`, `STATUS.md`, `results_stage2/`; this report. No engine, validation, config, ledger, guide or other strategy's file was edited. I did not touch the other worktrees.

## What did not run
- No real-lake backtest, baseline, benchmark, gates or family validation (they wait for your registration).
- No fresh scoring of the lake for the re-count (it re-uses the cached stage-1 candidate lists, which do not depend on the sector rule; only the occupancy model and the sector statistics do).
- No SQL-view run of the whole pipeline on the real lake for this strategy (the memory view is relied on, per its proofs).

## Deviations
- The re-count's "largest sector share" now means the largest MAPPED sector (14.9% of signals), because an unmapped symbol is no longer a sector; the unmapped share is reported separately (36.0%).
- The gates script keeps the `--t1` option copied from near_52w_high (it reads the single-strategy T1 file, which the family tool does not write); `RUN_COMMANDS.md` says not to use it.
- `tests/unit/test_validate_family.py` (shared, not edited) still builds a K = 4 family; my dry run uses K = 2.
- Section numbering of the finalised pre-registration differs from the stage-1 draft (registration is section 13, as asked).

## Decisions needed
1. **Expected trade rate:** the registered 23.0 comes from the old pooled-UNKNOWN rule; the model under the rule the run will use gives 25.63 (11% higher). Kept at 23.0 as decided; changing it before registration would change the spec hash.
2. **Baseline time:** about 3,000 to 3,300 trades at 20 draws each will take longer than near_52w_high's 22 minutes (to be measured); confirm it may run detached.
3. **Registration:** register family_batch1 (K = 2) on master with both spec hashes. This branch's: `57b86c47d0c5cbdc1325e19230c103b84bc08c6be6b495aadb99d1aa84ec6168`.
