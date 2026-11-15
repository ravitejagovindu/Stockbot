# riskadj_momentum: stage 2 report (scripts, final pre-registration text, run commands)

Branch `riskadj_momentum`. Nothing registered; **no backtest on the real lake was run; no return, P&L or forward price of this strategy was computed or looked at** (all new tests use fixture lakes). `finsight.db` sha256 `dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752` before and after: unchanged (checked before and after the gates).

**Final spec hash: `72dbec2c3da600cfe6de049a64efd530171ef2f539075f53e57a05e972ef27dc`** (unchanged from stage 1: `expected_trade_rate` 1.9 was already in the spec). Gates hash `e9b6407f908ff102dd25d9bc3b21a78a52b24c0ea082bba2cd3bb08f81188054` (recomputed from the shared config: equal).

## 1. What was done
| item | result |
|---|---|
| Decisions 1, 2, 5, 6 (rate 1.9, window kept, readings accepted, power kept) | written into `PREREGISTRATION.md` ("Owner decisions") |
| Decision 4: the two shared-test edits | own commit cff497e: allow-list of six (test renamed `..._six_approved_ids`), one extra allowed class `stockbot/strategies/riskadj_momentum/exits.py::TrailingAtr3Floor8` (constant `STRATEGY_POLICIES`); nothing else shared touched |
| Decision 3: baseline | `scripts/baseline_matched_random_riskadj_momentum.py` with its own draw loop; every random entry: stop = close - max(3 x ATR14, 0.08 x close) on its own symbol, exit policy `TrailingAtr3Floor8`, seed 20261111, 20 draws per trade |
| New end-of-window rule | implemented in strategy-side scripts only; no shared code changed (section 2) |
| Scripts | `research_riskadj_momentum.py` (`--execute` required; `policies_for(specs, extra=[TrailingAtr3Floor8()])`; manifest carries `asof_view`), `baseline_matched_random_riskadj_momentum.py`, `benchmark_nifty_matched_riskadj_momentum.py`, `evaluate_validation_gates_riskadj_momentum.py` |
| Tests | `tests/unit/test_riskadj_momentum_scripts.py`, 18 tests on fixture lakes |
| `PREREGISTRATION.md` | final text, section 7a (end-of-window rule) added, the old limitation "trades open at the window end are excluded" replaced, section 13 snippet with `--expect-k 1`, memory view for the registered run |
| `RUN_COMMANDS.md` | output folder `docs/strategies/riskadj_momentum/results_run1/`, steps 0 to 6, expected times (estimates) |

## 2. The end-of-window rule: how it is done, and one thing to know
Rule: positions and random draws still open at 2026-10-16 are closed at the last close with the normal exit slippage and costs, reason END_OF_WINDOW, and COUNT as usable (gates, T1, T2) / filled (draws).
- **Strategy's own positions:** the shared runner already closes them that way (reason END_OF_WINDOW). Only the exclusion has to go.
- **Gates:** the shared gate code (`evaluate_validation_gates_near_52w_high.evaluate`, which `validate_family.py` calls) treats the exact string `END_OF_WINDOW` as "not usable". It could not be edited, so the research script writes `trades.json` with `exit_reason` **`END_OF_WINDOW_COUNTED`** for those trades, keeps the engine's label in `exit_reason_engine` and sets `end_of_window: true`. A test shows that with the engine's label the shared evaluator would drop them (usable count falls by exactly the number of such trades) and with the relabel it counts all of them. Same trades, same P&L as the engine's own run (a test compares position ids and net P&L with a direct `run_backtest`; another recomputes the exit-price arithmetic: last close x (1 - exit slippage), sell cost paid).
- **T1 and T2:** read `actual_trades.csv` and `baseline_draws.csv`, which carry every trade including these (column `end_of_window`).
- **Random draws:** the shared `simulate_ticket` returns nothing for a path still open at the end. The strategy-side loop (`simulate_ticket_own`) is a copy that, instead, closes the position at the last close with the same arithmetic as the runner. Draws closed this way have exit reason END_OF_WINDOW and count as filled.
- **Counts, reported separately:** research log line and `run/manifest.json` (`end_of_window.trades`); `baseline/baseline_meta.json` (`end_of_window_trades`, `end_of_window_draws`, `draws_closed_before_window_end`); gates output (`counts.end_of_window_counted_as_usable`; with `--baseline-dir` also `baseline_end_of_window_draws`). **Limit:** `validate_family.py` is shared and does not print these numbers (its member counts include the trades); they must be read from the three files above. Nothing blocked the rule, so I did not stop.
- The relabel is the only place where the file says something other than the engine's exact reason; it is stated in `PREREGISTRATION.md` 7a, the script docstring and `RUN_COMMANDS.md`.

## 3. The baseline loop cannot drift
`draw_matched_random_own` is a copy of the shared `draw_matched_random` loop (same random stream: `random.Random(seed)`, `sample`, sorted picks) with two parameters: `stop_rule` and `close_at_end`. Tests (fixture lake, library policy `fixed_hold_5` and the strategy policy): with `stop_rule=shared_relative_stop` and `close_at_end=False` the output equals the shared helper's frame **exactly** (`assert_frame_equal(check_exact=True)`, same seed, same unfilled counts), for a policy that closes inside the lake and for `TrailingAtr3Floor8` where the shared helper loses draws to OPEN_AT_END; with `close_at_end=True` the extra rows are exactly those lost draws and every other row is unchanged. A further test recomputes the registered stop of 60 real draws of the fixture run from the lake with the strategy's own ATR function (`initial_stop`) and checks that both branches occur (8% floor and 3 x ATR) and that the relative distance varies from draw to draw.

## 4. Family of one
- `validate_family.load_member("riskadj_momentum", member_dir)` loads the real script outputs of the fixture run (the label is checked against the manifest).
- A dry run `validate_family.py --member riskadj_momentum=<dir> --expect-k 1` runs on a synthetic member (same files and columns; with END_OF_WINDOW trades among the trades): K = 1, T1 with blocks 2 and 3, seed 20261111, `--expect-k 2` and `--expect-k 0` refused. **Why synthetic:** the fixture lake spans about 14 months and the Max-T bootstrap needs at least 10 monthly observations of the window to run its block lengths; the real window has 130. The real-script outputs are tested through `load_member`, the shared evaluator (counts) and the sql = memory comparison.
- The gates of a member are evaluated by the shared code from `run/`; tested on the script outputs (usable = all closed trades).

## 5. Tests and gates
- New: 18 tests in `tests/unit/test_riskadj_momentum_scripts.py`: plan-only without `--execute` (no output directory, under sql and memory), `--out` required, a used directory refused, default window, layout, the end-of-window rule (closure at the last close, relabel, P&L equal to the engine run, shared gates count them, draws closed and counted), the baseline stop rule (own ATR stop, both branches), equivalence with the shared helper, sql = memory byte-identical (trades, equity, daily, blocked, both CSVs; manifests differ only in `asof_view`), benchmark and gates, load_member, K = 1 dry run, layout against the synthetic members, no write into a used directory.
- G1 (`tests/unit tests/integration`): 1,188 passed, 9 skipped, 0 failed. Full G2 (`STOCKBOT_DATA_TESTS=1 STOCKBOT_FINAL_CHECK=1 pytest tests`): 1,318 passed, 0 failed. G3 (`tests/unit/test_g3_fixture_baseline.py`): 2 passed. `STOCKBOT_VIEW` unset for the tests.

## 6. Expected times (estimates, not measured; nothing was run on the real lake)
Engine run, memory view: 15 to 45 minutes. Baseline: 2 to 4 hours (about 4,500 draws, each running until its trailing stop fires or the window ends, against 5-session paths for the pullback baseline). Steps 4 to 6: minutes to tens of minutes. About 1 GB of memory per process; at most two processes at once. `RUN_COMMANDS.md` has the details.

## 7. Notes for the owner
1. The registered run's trade count is unknown until it runs; the end-of-window rule lifts it slightly (the last months' open positions now count). Power (section 9 of the pre-registration) was accepted as stated.
2. The `END_OF_WINDOW_COUNTED` label is the price of not touching shared gate code (section 2). If you prefer the exact string `END_OF_WINDOW` in `trades.json`, the shared gate code needs a one-line change (`usable` must not test that string); say so and I will list it.
3. Nothing is registered. `PREREGISTRATION.md` section 13 has the `register_family` call (K = 1, gates hash above, spec hash above); `git_sha` must be the commit carrying the approved text.
4. Section 14 of the pre-registration now lists no open decisions.

## 8. Files
Scripts: `scripts/{research,baseline_matched_random,benchmark_nifty_matched,evaluate_validation_gates}_riskadj_momentum.py`. Tests: `tests/unit/test_riskadj_momentum_scripts.py`. Docs: `docs/strategies/riskadj_momentum/{BRIEF,STATUS,PREREGISTRATION,RUN_COMMANDS}.md`. The only shared file edited at stage 2: `tests/unit/test_no_strategy_in_the_tree.py` (approved).
