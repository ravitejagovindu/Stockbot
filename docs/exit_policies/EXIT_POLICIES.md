# Exit policies

## What a policy is
An exit policy answers two questions about an open position, once per session: "should the stop move?" and "should we ask to exit?". It decides **what**. The engine (`stockbot/engine/stepping.py::step_position`) decides **how**, in one fixed order that is the same for every policy. A policy never sees a database; it gets the position, today's bar and the as-of view.

A strategy names its policy in its spec: `StrategySpec(exit_policy="fixed_hold_20", ...)`. The id is part of the spec, so it is part of the strategy's `config_hash`.

## The two shared policies (`stockbot/engine/exit_policies/`)
| id | meaning | state |
|---|---|---|
| `fixed_hold_<N>` | Exit the whole position at the open of the session after N sessions held. | none (`{}`) |
| `trailing_pct_<P>` | The stop trails P percent below the highest close since entry. It asks for no exit; the stop does the exiting. | `{"highest_close": float}` |

**Id formats.** `fixed_hold_<N>`: N a positive integer, written without leading zeros (`fixed_hold_20`; `fixed_hold_020`, `fixed_hold_0`, `fixed_hold_2.0`, ` fixed_hold_20` are all rejected). `trailing_pct_<P>`: P an integer from 1 to 99 without leading zeros. One behaviour has exactly one spelling. `resolve(policy_id)` returns the policy or raises `UnknownExitPolicyError`.

**How N is counted.** The entry session is session 1. `fixed_hold_N` asks for the exit on the bar where N sessions have been held, and the exit fills at the **open of the next session** (session N+1), less exit slippage. So the position is held through N closes. `fixed_hold_1` asks on the entry bar and exits at the next open. A session in which the symbol has no bar does not count as held (the engine does not step the position), and a queued exit waits for the next session that has a bar.

**How the trailing stop works.** `highest_close` starts at the position's **entry price** (the fill price, including entry slippage; this is a deliberate choice and it is not itself a close). Each stepped bar: `highest_close = max(highest_close, bar.close)`, `candidate = highest_close x (1 - P/100)`; the policy proposes the candidate only if it is above the live stop. Close-based on purpose: it avoids any question about the order of the bar's high and low. If the stop is hit, the engine fills it at `min(open, stop) x (1 - exit slippage)`, as for any stop.

## The timing rule (important)
A stop produced on bar T applies from bar T+1. In one session the engine does, in order: (1) execute a queued market exit at the open; (2) check the stop that was live at the previous close against this bar's low; (3) count the session, run the policy (it may move the stop and queue an exit); (4) fill limits, queue market requests. So the stop a policy sets on today's bar is never tested against today's bar. This holds on the entry bar too: the **initial stop** is tested on the entry bar; the trailing stop first applies on the bar after it. A policy reads only the bar it is given: no lookahead.

## What the engine always enforces, whatever the policy
- **Initial stop.** The ticket's stop is the position's stop from the fill; it is tested on every bar including the entry bar.
- **A stop never moves down.** A lower stop from a policy is ignored and flagged `STOP_LOWERING_IGNORED`. TrailingStop also never proposes one; it does not rely on the engine alone.
- **Corporate actions.** A split or bonus rescales entry price, stops, target, highest high, last close and the shares, and a queued exit scales with the shares (a full exit stays a full exit). The policy's own price-valued state is rescaled by `on_corporate_action(exit_state, factor)` with the same factor (1:5 split 0.2, 1:10 split 0.1, 1:1 bonus 0.5). An action the engine cannot rescale (rights, merger, unparsable ratio) puts the position on HOLD: flagged, the policy state untouched, excluded from trade statistics.
- **A queued exit executes before the stop check** on the next session that has a bar.
- Costs, slippage, the gap rules and the journal round trip are shared code.

## How a strategy picks a policy
Put the id in the spec. For a backtest, `run_backtest(..., policies=None, ...)` builds the mapping from the strategies' specs; for the live book use `Book.from_strategies(strategies)`. Both call `policies_for(specs, extra=None)` in `stockbot/engine/exit_policies/registry.py`. A caller may still pass its own mapping, as before.

## How to write a strategy-owned policy
1. Put a class in `stockbot/strategies/<name>/` (for example `exits.py`) with `id`, `initial_state(position, view)`, `step(position, bar, view, ctx) -> PolicyActions` and `on_corporate_action(exit_state, factor)`. Keep its state plain (JSON-serialisable) and rescale every price-valued field in `on_corporate_action`.
2. Import **only** the interface types from `stockbot.engine.exit_policy` (`ExitPolicy`, `PolicyActions`, `MarketAtNextOpen`, `Limit`, `StepContext`, `Bar`) and `stockbot.data` view types. Not `stockbot.engine.exit_policies` (the library), not any other engine module, not another strategy. `tests/unit/test_import_boundaries.py` (rules in `tests/fixtures/boundaries.py`) fails the build otherwise. Use `from stockbot.engine.exit_policy import ...`; `from stockbot.engine import exit_policy` is also rejected.
3. Give it an id of your own that does **not** start with `fixed_hold_` or `trailing_pct_`; reference it in the spec and pass the object as `extra`: `policies_for(specs, extra=[MyExit()])` or `Book.from_strategies(strategies, extra_policies=[MyExit()])`. An unknown id, two policies with one id, or a policy that is not a valid `ExitPolicy` fails loudly.
4. `tests/unit/test_no_strategy_in_the_tree.py` allows exit-policy classes only in `stockbot/engine/exit_policies/` and `stockbot/strategies/<name>/`, and still forbids strategies and overlays everywhere outside `tests/`. A test double of this kind is `tests/fixtures/own_policy.py`.

## Limits to know
- **Percent is an integer.** `trailing_pct_<P>` cannot express 7.5 percent; that keeps ids unique.
- **Prices are floats.** No tick-size rounding of the trailing stop.
- **Closed-out strategy with open positions.** `policies_for` covers the strategies it is given. If a strategy is removed from the book while it still has an open position, `decide` raises `EngineInputError` ("open position ... unknown exit policy") rather than guessing. Keep the strategy (or its policy) in the book until its positions are closed. There is no `also=` parameter on purpose.
- **Reference seeded from the entry price.** If the position closes below its fill price every session, the reference stays at the fill price.
- **Gap sessions.** A session without a bar is not seen by the policy; the first bar after the gap updates `highest_close` with its own close only.
- No performance claim is made for either policy; this library is mechanics only.
