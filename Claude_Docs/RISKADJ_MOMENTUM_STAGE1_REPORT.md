# riskadj_momentum: stage 1 report (build, counts only, draft pre-registration)

Branch `riskadj_momentum` (from origin/master 1ba2a38). Nothing registered; no backtest on the real lake; no return, P&L or forward price of this strategy was computed or looked at. `finsight.db` sha256 `dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752` before and after (checked by the counts script itself, and again at the end: unchanged).

## 1. What ran
| step | result |
|---|---|
| Setup: worktree `../StockBot_wt_riskadj`, branch `riskadj_momentum` from origin/master | done; no branch switched elsewhere |
| 1. Allow-list line in `tests/fixtures/boundaries.py` | own commit 0da1b65, one line |
| 2. Strategy `stockbot/strategies/riskadj_momentum/` (strategy.py, indicators.py) | spec hash `72dbec2c3da600cfe6de049a64efd530171ef2f539075f53e57a05e972ef27dc`, `expected_trade_rate` 1.9 (proposed) |
| 3. Exit policy `trailing_atr3_floor8` (`exits.py`) | `ExitPolicy.step` receives `position` (symbol, entry, stop, state), the bar and the as-of `view`; ATR14 is read from `view.adjusted_bars(symbol)` as of the stepped session, so nothing was missing and no engine change was needed |
| 4. Counts study over the real lake (counts only) | 130 signal months, 332 s on the memory view; `docs/strategies/riskadj_momentum/counts/` |
| 5. Draft `PREREGISTRATION.md` (family_batch2, K = 1) | written, DRAFT |
| 6. Baseline and family tools | section 4 below |
| 7. Tests, G1, full G2, G3, DB hash | section 5 below |

## 2. The counts (facts; details and the slot arithmetic in PREREGISTRATION section 6)
- First signal 2016-12-01. The 11 signal months of 2016-01 to 2016-11 are empty (the Nifty calendar starts 2015-11-09; a 252-session window does not exist before late 2016). From 2016-12 every month has 34 to 534 qualifying names (median 188), so **fewer than 25 qualify only in the 11 empty months**.
- Funnel over 130 months (name-months): fewer than 253 own bars 1,640; fewer than 240 closes in the window 1,048; ret <= 0 12,580; vol <= 0, ATR missing, bad price, no bar: 0; qualifying 25,715. No score ties at all (the ADTV tie-break never fires). The symbol's own bar t-252 differs from the calendar's in 131 of 25,713 qualifying name-months.
- Top 25: 76.8% mapped to a sector, 23.2% UNMAPPED; median 7.5 distinct mapped sectors a month; 63.1% of top-25 names share a mapped sector with another top-25 name.
- Initial stop distance: median 11.9% of the close, p5 8.0% (floor), p95 19.4%, max 43.6%; 16.0% of names at the 8% floor. Implied position (1% risk / distance): median 8.4% of equity, mean 8.8%; so about 11.4 positions fit in capital, 12 in the position limit.
- Overlap of consecutive top 25s: mean 15.5 names (62%). 41.7% of top-25 names were also near_52w_high candidates that session.
- Trade rate under slot arithmetic: 2.85 a month at a 4-month average hold, 1.42 at 8 months; **proposed 1.9** (6 months). No rule was found unworkable: nothing to stop on.

## 3. Readings of ambiguous rules (also in BRIEF.md; overrule any)
1. "At least 240 closes among the last 252 sessions" is read on the Nifty calendar; "t-21 and t-252 on the symbol's own bars within the window" as own-bar positions 21 and 252 before the symbol's last bar, which needs 253 own bars (a 252-session calendar window alone cannot contain t-252, it holds t-251 at best). Without gaps the two readings coincide; with gaps the own-bar reading reaches further back (0.5% of qualifying name-months).
2. Log returns across a gap are between consecutive available closes. 3. ATR over a fixed 252 bars ending at the session (Wilder seeding decays, so the length matters slightly); signal and exit use the same function. 4. A stop at or below zero makes a name unusable (2 name-months). 5. First session of the calendar has no previous session, so no signal. 6. A fallback to the 8% floor if ATR is unavailable in the exit (flagged; cannot occur for this strategy's own positions).

## 4. Step 6: do the baseline and family tools accept a strategy-owned exit policy and varying stop distances?
- **Works without any shared change:** `draw_matched_random` takes any policy OBJECT (test `test_the_shared_matched_random_helper_accepts_the_strategy_owned_policy_object` runs draws with `TrailingAtr3Floor8` through the shared simulator on a fixture lake); per-trade stop distances that differ are supported (each draw uses its own actual trade's relative distance). The gates, benchmark and `validate_family` code contain no exit-policy lookup (grep), and `validate_family` refuses only K < 1, so K = 1 is accepted by reading; I did not run it (no fixture family of one).
- **Fails / needs care:**
  1. `scripts/baseline_matched_random_<id>.py` (the worked example) calls `stockbot.engine.exit_policies.registry.resolve(SPEC.exit_policy)`, which raises for `trailing_atr3_floor8` (not a library id). A riskadj script must pass `TrailingAtr3Floor8()` itself (a strategy-side script; no shared change).
  2. `run_backtest(..., policies=None)` builds the mapping with `policies_for(specs)`, which raises for the strategy-owned id (test `test_the_library_does_not_know_the_policy_so_it_is_passed_as_extra`). A research script must pass `policies_for(specs, extra=[TrailingAtr3Floor8()])` (the exit-policy guide describes it).
  3. **The pre-registered random stop cannot be produced by the shared helper.** `draw_matched_random` gives every draw the ACTUAL trade's relative distance `(entry - stop) / entry` applied to the draw's close; the pre-registration says the random entry's stop is `reference - max(3 x ATR14, 0.08 x reference)` of the RANDOM symbol. Only a strategy-side loop (copy of the helper's loop calling `simulate_ticket` with the strategy's own stop function) does it; no shared file needs to change, but it is a new baseline script whose loop duplicates about 25 lines of shared code. Decision needed (section 6).
  4. With a trailing stop and no time exit, a draw entered late in the window is often still open at the window end (`OPEN_AT_END`, unfilled); a pair needs 10 filled draws and more than 5% lost pairs flags the result. How many would be lost cannot be known without forward prices; the same holds for actual trades (excluded, as the limitations say).

## 5. Tests and gates
- New: `tests/unit/test_riskadj_momentum_strategy.py`, 44 tests on fixture lakes: spec numbers and hash coverage, month-start signal sessions, 12-1 return, volatility and score against an independent calculation, strict ret > 0 and vol > 0, the skipped month not in the return, 253-bar and 240-of-252 rules (12 missing passes, 13 fails, no bar on the signal date, calendar shorter than the window), own-bar offsets with gaps, ties by ADTV then symbol, the top-25 cut and ordinal rank, ATR against a hand-computed 64/27 and an independent recursion, stop floor and ATR branches, unusable stop, point-in-time safety (rows after the as-of date altered), split adjustment and no future-split leak, isolation, imports; the exit policy: id, seed from the entry price, floor, ATR, never down (random path), no requests or time exit, ATR fallback, corporate-action rescale, per-session stops against an independent formula through the real engine (applies from the next bar), a stop-out through the engine, identical under STOCKBOT_VIEW=sql and memory.
- **Shared tests that need an edit (NOT made, per the rule; two tests fail until the owner decides):** both are in `tests/unit/test_no_strategy_in_the_tree.py`: (a) `test_the_allow_list_holds_exactly_the_five_approved_ids` pins the list: it must now read `("near_52w_high", "short_term_reversal", "trend_breakout_100d", "low_volatility", "pullback_uptrend", "riskadj_momentum")` (and its name says "five"); (b) `test_no_class_outside_tests_implements_...` lists every allowed interface-implementing class outside the approved strategies: the strategy-owned policy needs `"stockbot/strategies/riskadj_momentum/exits.py::TrailingAtr3Floor8"` added to the expected list (the exit-policy guide says strategy-owned policies are allowed; the list is exact on purpose). Two small edits; with them G1 and G2 are expected to be green.
- G1 (`tests/unit tests/integration`): 1,168 passed, 9 skipped, 2 failed (the two shared tests above, nothing else). Full G2 (`STOCKBOT_DATA_TESTS=1 STOCKBOT_FINAL_CHECK=1 pytest tests`): 1,298 passed, 2 failed (the same two). G3 (`tests/unit/test_g3_fixture_baseline.py`): 2 passed. DB hash: unchanged. STOCKBOT_VIEW was unset for the tests.

## 6. Decisions needed
1. Confirm `expected_trade_rate` 1.9, or set another (the spec hash changes; slot arithmetic is in the pre-registration and depends on an assumed hold).
2. The window starts 2016-01-01 but the first signal is 2016-12-01 (11 empty months): keep as is or start the window later.
3. Baseline stop for random entries: a strategy-side baseline script with its own draw loop (no shared change) or a shared-code option on `draw_matched_random` (a shared change, your call).
4. The two shared test edits in section 5.
5. The own-bar reading of t-21 / t-252 (section 3, item 1) and the 252-bar ATR length.
6. Power (PREREGISTRATION section 9, assumptions only): at sigma 1.5 R and about 226 trades an edge of 0.15 R is detected with under 45% power; the gate `min_expectancy_r` 0.15 is a point estimate. Say if the edge of interest, the number of trades or the plan should change.

## 7. Files
Strategy: `stockbot/strategies/riskadj_momentum/`. Study: `scripts/signal_count_riskadj_momentum.py`; results `docs/strategies/riskadj_momentum/counts/` (full outputs also in `F:\Projects\Ravi\StockBot_runs\riskadj_momentum\counts_v1\`). Docs: `docs/strategies/riskadj_momentum/{BRIEF,STATUS,PREREGISTRATION}.md`. Tests: `tests/unit/test_riskadj_momentum_strategy.py`. The only shared file edited: `tests/fixtures/boundaries.py` (allow-list line).
