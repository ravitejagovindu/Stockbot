# lowvol_uptrend: build report

Branch `lowvol_uptrend` (from origin/master 1d87146). Nothing registered, nothing run on the real lake except the counts study. **No return, P&L or forward price of this strategy was computed or looked at.**

## Summary
| Item | Result |
|---|---|
| Final spec hash | **`52e7ee3ccc2e150d7e4b6b54266bb2c73a8788612691ece475bfa7d1bb0e9e68`** (`SPEC.config_hash()`, `expected_trade_rate` 1.3 included) |
| Gates hash | `e9b6407f908ff102dd25d9bc3b21a78a52b24c0ea082bba2cd3bb08f81188054`, unchanged |
| Shared files touched | only the two approved edits, own commit 3998fd9 (below) |
| Rule workable? | Yes: 118 of 119 non-empty months fill the top 25; 2020-04 has 21. The 11 months of 2016 are empty by definition |
| Proposed `expected_trade_rate` | **1.3** a month (about 8 slots, 6-month hold); 2.7 at a 3-month hold |
| Real-lake runs | the counts study only (memory view, 511 s); DB hash unchanged |

## Shared files touched (approved, one commit)
- `tests/fixtures/boundaries.py`: `lowvol_uptrend` appended to `APPROVED_STRATEGY_IDS`.
- `tests/unit/test_no_strategy_in_the_tree.py`: the test is renamed `test_the_allow_list_holds_exactly_the_seven_approved_ids` and pins seven ids; `STRATEGY_POLICIES` gains `stockbot/strategies/lowvol_uptrend/exits.py::LvTrailingAtr3Floor8`.
Nothing else shared was edited: no config, no engine, no guide (the guide tests need no rows for strategy folders; riskadj_momentum has none either).

## The counts (130 signal months, 2016-01 to 2026-10; `docs/strategies/lowvol_uptrend/counts/`)
- **Funnel (name-months):** eligible median 275 a month; fewer than 253 own bars 1,642; fewer than 240 closes 1,048; fewer than 198 of 200 closes 132; **below or at SMA200 13,337**; vol <= 0 0; ATR missing 0; **qualifying 24,873**. Median month: 86 below SMA200, 165 qualifying.
- **Months:** 11 empty (2016-01 to 2016-11); 2020-04 has 21; the other 118 have 25 or more.
- **Ties:** 0 exact vol ties in 24,873 qualifying name-months; the ADTV tie-break never fires.
- **Sector spread of the top 25** (2,971 name-months): 96.4% mapped, 3.6% UNMAPPED. Distinct mapped sectors per month: median 8, min 4. Largest same-sector group: median 7, max 13. **Depth to find 8 different sectors** in the full ranked list: reached in all 119 months, median rank 18, p95 25, max 30; the top 25 holds fewer than 8 sectors in 5 months.
- **Initial stop:** median 8.0% (the floor); p5 8.0%, p95 11.1%, max 36.9%; **74.4% of names at the floor**. **Implied position size** (1% risk / distance): median 12.5%, mean 11.9%, p5 9.0%, p95 12.5% of equity.
- **Overlap of consecutive months' top 25:** mean 17.8 names (71.2%), median 18, range 7 to 24 (118 pairs).
- **Same-month overlap:** 10.8% of the top-25 name-months were riskadj_momentum top-25 names; 48.3% were near_52w_high candidates that session.
- **Nifty below its own SMA200** at 28 of 122 signal sessions with the average available (23.0%).

### expected_trade_rate (slot arithmetic, no forward prices)
Mean position 11.9% of equity gives 100 / 11.9 = 8.4 slots (the 15% sector cap points the same way: at most one position per mapped sector), so "about 8 positions". Entries a month = 8 / hold:
| hold assumption | entries a month | with mid-month slots idle (hold + 0.5 month) | over 119 months |
|---|---|---|---|
| 3 months | 2.67 | 2.29 | about 317 (272) |
| 6 months | 1.33 | 1.23 | about 158 (146) |
**Proposed 1.3** (6 months): three quarters of the names sit on an 8% trailing floor and low-volatility names rarely fall 8% from a high within a few months. This is an assumption, not a measurement; the owner can overrule it, which changes the spec hash.

## The rule as built (`stockbot/strategies/lowvol_uptrend/`)
`strategy.py` (rule, spec, `assess`, `order_signals`), `exits.py` (`LvTrailingAtr3Floor8`, id `lv_trailing_atr3_floor8`; imports only `stockbot.engine.exit_policy`; nothing imported from the riskadj folder), `indicators.py` (the ATR function copied from riskadj_momentum). Params as fixed: `{"vol_window":252,"min_closes":240,"sma_window":200,"sma_min_closes":198,"top_n":25,"atr_period":14,"atr_mult":3.0,"stop_floor":0.08,"tie_adtv_sessions":20}`, `smallest_edge_of_interest` 0.15, `prereg_ref` the pre-registration, no overlay, status `research`.

## My reading of the ambiguous rules (for you to overrule)
1. **"vol over the last 252 own bars"**: 253 own closes give 252 daily log returns (this matches "needs 253 own bars"). Reading B would be 252 closes and 251 returns; a test pins reading A and shows it differs from 251 and 253 returns and from ddof 0.
2. **SMA200 and "at least 198 of the last 200 closes present"**: both read on the Nifty calendar (the last 200 sessions ending at the signal session); the SMA is the mean of the symbol's closes inside it. Strictly greater than; equal is not an uptrend (tested at equality).
3. **"At least 240 of the last 252"**: Nifty calendar, as riskadj_momentum.
4. **Window edge:** the three numbers in the funnel that follow from these readings (132 name-months fail the 198-of-200 rule, 1,048 the 240-of-252 rule) show that they bind only rarely.

## Scripts
`research_`, `baseline_matched_random_`, `benchmark_nifty_matched_`, `evaluate_validation_gates_` `lowvol_uptrend.py`: copies of the riskadj_momentum scripts, renamed, on top of the shared stale-positions code. `research_`: `--execute` required; the manifest carries `asof_view`, `symbol_links`, `stale_exit` and `end_of_window`. `baseline_`: own draw loop `draw_matched_random_own`, 20 draws per trade, seed 20261111; every random entry gets close - max(3 x ATR14, 0.08 x close) on its own symbol and the same exit policy; a draw open at the window end is closed at the last close and counted (`END_OF_WINDOW`); draws that stop having bars close as `SYMBOL_NO_BARS` and are counted in `stale_exit_draws`. `evaluate_`: the gate table, the end-of-window counts and the shared stale-exit report with the 0.5 x last close stress line. `signal_count_lowvol_uptrend.py`: the counts study (counts only).

## Tests (fixture lakes only; `finsight.db` is never opened by a test)
- `tests/unit/test_lowvol_uptrend_strategy.py` (49): spec and hash coverage, signal sessions, vol against an independent calculation, 253 closes and 252 returns, the strict uptrend filter and its equality edge, SMA window presence (198 passes, 197 fails), 240-of-252 and 253-own-bar edges, the SMA over present closes, ties by ADTV then symbol, the ordinal rank and the top-25 cut, point-in-time safety (changing every future price changes nothing), a split inside the window, isolation, import boundaries, **the ATR equal to riskadj_momentum's on a fixture (including `None` for short histories)**, the exit policy (floor, ATR, timing, never down, no time exit, corporate-action rescale), through the engine, SQL = memory, and **the policy giving the same `PolicyActions` and stops as riskadj_momentum's session by session on a random path with a corporate action in the middle**.
- `tests/unit/test_lowvol_uptrend_scripts.py` (19): the plan without `--execute` (SQL and memory view), refusal without `--out` or into a used folder, the registered window, the end-of-window rule (closed at the last close and counted; the shared gates count them), baseline equivalence with the shared helper (exact), the baseline stop rule on each draw's own symbol, SQL = memory byte for byte, B2 and gates from the run folder, `validate_family` loading the member and a dry run with `--expect-k 1` on a fixture family of one, the manifest `symbol_links` and `stale_exit` blocks.

## Gates and the database
| gate | result |
|---|---|
| G1 (`pytest tests/unit tests/integration`) | **1,278 passed, 9 skipped, 0 failed** (19 min) |
| full G2 (`STOCKBOT_DATA_TESTS=1 STOCKBOT_FINAL_CHECK=1 pytest tests`) | **1,408 passed, 0 failed** (22 min) |
| G3 (`tests/unit/test_g3_fixture_baseline.py`) | 2 passed |
| `finsight.db` sha256 | `dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752` before and after (checked after the counts study and after the gates) |

## Decisions needed
1. **`expected_trade_rate` 1.3** (6-month hold) versus 2.7 (3-month hold). It only feeds the spec hash and the power section; the choice is yours.
2. **The three readings** above (253 closes, calendar-window SMA presence, strict inequality).
3. **Concentration:** with about 12.5% positions and the 15% sector cap the book holds about 8 names, one per mapped sector, while the top 25 holds a median of 8 mapped sectors and in 5 months fewer than 8. Some signals will be blocked by the sector cap; the engine decides, nothing here changes it.
4. **Overlap with near_52w_high is 48%** (and 11% with riskadj_momentum), so a result for this rule is partly a result for the near-high names; the random baseline (all eligible stocks) cannot separate the uptrend filter from the low-volatility ranking (stated in the pre-registration).
5. Registration of `family_batch3` (K = 1) on master at the commit carrying the pre-registration, and authorisation of the registered run.

## What ran and what did not
- Ran: the unit and fixture tests; the counts study on the real lake (memory view, read-only, DB hash unchanged).
- Did not run: the registered backtest, the baseline, the benchmark, the gates script and `validate_family` on the real lake. Nothing is registered.
