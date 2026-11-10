# Exit policies library: design note (STOP A)

Branch `exit-policies` (from `origin/master` ab6ae5b). No code has been written. Written for a reviewer who has not seen the session.

## 0. Read this first: four things that block or change the plan

1. **`finsight.db` is not present in this environment** (this session runs in a cloud container, not the owner's machine). The standing rule says: run on the owner's machine, and if the database is absent, STOP and say so. So no sha256/mtime fingerprint and no G2 run exist for this stage. This note needs neither (it is design only), but **STOP B cannot satisfy the standing rules from this container**. Decision needed: run Stage B on the owner's machine, or accept a stated exception (G1/G3 here, G2 and the fingerprint by the owner).
2. **Engine finding (shared code, not mine to change): a split on the day a pending exit executes sells only a fraction of the position.** `engine/corporate.py::_rescale` rescales `shares_remaining` but not `pending_exit`. Checked: a position with 100 shares and `pending_exit=100`, after a 1:5 split, has `shares_remaining=500, pending_exit=100`. Stepping then sells `min(100, 500)=100` shares at the open and leaves 400 with `pending_exit=0`; the time exit becomes a silent partial exit. This hits FixedHold directly whenever the ex-date is the session after `days_held` reached N, and it would break the required test "same trade with and without a split mid-hold is economically identical". Proposed fix (one line, `pending_exit = floor(pending_exit / factor + 1e-9)`, capped at the new `shares_remaining`) needs your approval because the brief forbids other shared changes. Without the fix I will pin the current behaviour in a test marked as a known limitation and say so in the report.
3. **`Claude_Docs/STOCKBOT_MOMENTUM_GROUNDWORK_REPORT.md` does not exist in the repository** (not on `origin/master`, not on any branch). I could not read Part 2 (Q1 to Q3, Q8). This design rests on the code and `ENGINE_CONTRACT.md` only. Please supply the file or confirm nothing in it changes this plan.
4. **Local `master` is stale** (22b5372); `origin/master` is ab6ae5b and contains the guide commits and `scripts/build_guide_html.py` that section 6 needs. I branched from `origin/master`. The session's default branch name (`ccr-...`) is not used; the owner's branch name `exit-policies` is.

Baseline observed here (G1 = `pytest tests/unit tests/integration`): **548 passed, 8 skipped, 4 failed**, 51 s. The 4 failures are environmental and exist before any change: `test_every_module_imports_alone` (no `yfinance` installed), `test_golden_files` and `test_ledger_yaml_hash` (file hashes differ in this checkout, probably line endings), `test_script_wrappers_help[f2_index_gap_fill_yahoo.py]` (same `yfinance`). G3 (`test_g3_fixture_baseline.py`): 2 passed. G2: not run (no database). I expect the owner's machine to show these 4 passing; the report will quote counts from wherever Stage B is run.

## 1. Location and ids

Files (all new): `stockbot/engine/exit_policies/__init__.py` (docstring only), `fixed_hold.py`, `trailing_stop.py`, `registry.py`. `stockbot/engine/exit_policy.py` is not touched.

`registry.py`:
- `resolve(policy_id) -> ExitPolicy`. Grammar (anchored, `re.fullmatch`, no `strip`, no `int()` on text): `fixed_hold_([1-9][0-9]*)` and `trailing_pct_([1-9][0-9]?)`. The first digit is 1-9, so `040`, `0`, `-5`, `+5`, `4.0`, ` 40`, `40 `, `40\n` (note: `$` would accept a trailing newline, `fullmatch` does not), `FIXED_HOLD_5`, full-width/other Unicode digits (`[0-9]` is ASCII only, unlike `\d`), and empty string are all rejected. Percent also bounded to 1..99 after the match (so `trailing_pct_100` and `trailing_pct_0` are rejected; `trailing_pct_9` and `_99` accepted).
- Each id has exactly one spelling, so the canonical id is `f"fixed_hold_{n}"` / `f"trailing_pct_{p}"`; `resolve(pid).id == pid` is asserted in tests. Upper bound on N: none in the brief; I propose `fixed_hold_N` with `N <= 10000` to avoid absurd ids (decision requested, default: no bound beyond positive integer, as written).
- Errors: `class UnknownExitPolicyError(ValueError)` with a message naming the id, the two accepted formats, and for a near miss why (e.g. "leading zero"). A single exception type for unknown and malformed.
- `LIBRARY_FORMATS` (tuple of the two format strings) for the error text and docs.

Policy objects are immutable (frozen dataclass-style, `id` set in `__post_init__` or as a property computed from the parameter), so the id cannot drift from the parameter. `ExitPolicy` is a `runtime_checkable` Protocol with attribute `id`; a read-only property satisfies `isinstance` (checked at implementation).

## 2. FixedHold(hold_sessions)

`fixed_hold.py::FixedHold`. Validation: `hold_sessions` must be a real `int` (not bool) `>= 1`, else `ValueError`.
- `id` = `fixed_hold_<N>`.
- `initial_state(position, view)` -> `{}`.
- `step(position, bar, view, ctx)`: `if ctx.days_held >= self.hold_sessions: return PolicyActions(requests=(MarketAtNextOpen(position.shares_remaining, "TIME_EXIT"),))` else `PolicyActions()`. `new_live_stop` is always `None` (never touches the stop), `new_exit_state` is `None` (state stays `{}`).
- `on_corporate_action(exit_state, factor)` -> `dict(exit_state)`.

Timing (from `engine/stepping.py`): `days_held` is incremented in step 3 on every stepped bar **including the entry bar** (the entry-bar is day 1). So `fixed_hold_1` requests the exit on the entry bar and it executes at the **next session's open**; `fixed_hold_N` executes at the open of session N+1 after entry, i.e. the position is held through N closes. This must be stated in `EXIT_POLICIES.md`. If the stop is hit on session k <= N the position closes first (step 2 runs before the policy). On session N+1 the pending exit runs in step 1, before the stop check, so a low below the stop on that day does not matter: the exit is at the open x (1 - slippage), not at the stop.

No-bar sessions (confirmed in `decide.py` section 3): when `bar_of` returns `None` the position is appended unchanged, a `NO_BAR_POSITION_NOT_STEPPED` flag is raised, and `step_position` is not called. So `days_held` does not increase and the policy is not called. A pending exit stays pending and executes at the first later session that has a bar. Corporate actions are also deferred to the next session with a bar (they are applied from inside the same loop, and `due_actions` selects by `entry_date < ex_date <= as_of`, so nothing is lost). Test: a symbol with a gap in the fixture lake.

## 3. TrailingStop(percent)

`trailing_stop.py::TrailingStop`, `percent` a real `int` 1..99. `id` = `trailing_pct_<P>`.

State schema (exact): `{"highest_close": float}` in the **price basis of the position** (rescaled by corporate actions). Nothing else, no keys that are None. Values are plain Python floats (JSON round trip is exact for floats via `repr`).

- `initial_state(position, view)` -> `{"highest_close": float(position.entry_price)}`.
- `step(position, bar, view, ctx)`:
  1. `hc = max(float(position.exit_state.get("highest_close", position.entry_price)), bar.close)`. (Missing key falls back to entry price rather than raising, so a state written by an older run cannot crash a live session; a test pins it.)
  2. `cand = hc * (1 - percent / 100)`.
  3. `new_stop = cand if cand > position.live_stop else None`.
  4. Return `PolicyActions(new_live_stop=new_stop, new_exit_state={"highest_close": hc})`. No requests, no flags.
  Equal-to-current stop: `cand > live_stop` is strict, so `None` is returned (no change); engine behaviour is identical either way (engine only rejects `<`). A lower candidate returns `None`, so the engine's `STOP_LOWERING_IGNORED` flag never appears for this policy (a test asserts that flag is absent).
- No lookahead: reads only `bar` and `position`; never touches `view`.
- `on_corporate_action(exit_state, factor)` -> `{**exit_state, "highest_close": exit_state["highest_close"] * factor}` (key by key copy, other keys untouched).

**How the engine passes the factor (from the code).** `engine/decide.py` section 3: for each open position with a bar, `due = due_actions(view.corporate_actions(sym), entry_date, as_of, pos.ca_done)`; then `apply_actions(pos, due, bar.open, policy)`. In `engine/corporate.py::apply_actions`, per action `factor = action_factor(a)` (`data/adjustments.py`): SPLIT `num/den` (1:5 gives 0.2, 1:10 gives 0.1), BONUS `den/(den+num)` (1:1 gives 0.5). `factor == 1.0` is skipped. `_rescale` then multiplies entry price, initial stop, live stop, target, highest high, last close by `factor`, divides shares by `factor` (floor, remainder paid in cash), and sets `exit_state = policy.on_corporate_action(pos.exit_state, factor)` with the **pre-action** state and the same `factor`. Several actions on one day are applied in `(ex_date, type)` order, one call each. Actions with an unsupported type or an unparsable ratio never reach the policy: they go to `review`, `ca_done` records them, and `hold=True` (flag `CORPORATE_ACTION_HOLD`). Dividends are ignored. So `highest_close * factor` is exactly consistent with `live_stop * factor`. After the action the bar given to `step` is in the new basis (the as-of view adjusts for actions with `ex_date <= as_of`), so `max(rescaled highest_close, bar.close)` compares like with like.

**Timing, precise.**
- *Entry bar.* Order inside `step_position` on the entry day: (1) no pending exit; (2) the **initial stop** is checked against the entry bar's low; if it hits, the position closes and the policy never runs; (3) otherwise `days_held=1`, then `step` runs: `highest_close = max(entry_price, entry-bar close)`, candidate computed, and a raised stop (if above the initial stop) becomes `live_stop` **for the next bar**. Stops are only tested in step 2 of a later call, so a stop produced by bar T is never tested against bar T.
- *Subtle point (ambiguity A1 below):* `entry_price` is the fill price (open x (1 + entry slippage)), not a close. If the entry bar closes below the fill price, `highest_close` stays at the fill price. That is what the brief says (`initial_state` starts from the entry price) and what I will build, but it means the reference can be a price that never was a close.
- *Bar with no data.* `step` is not called; `highest_close` is unchanged; the live stop stays what it was; no close is filled forward. The first bar after the gap updates `highest_close` with that bar's close only (the unseen closes in the gap are not used). Same as the engine's treatment of `days_held`.
- *Stop higher than the close.* If the close falls more than P% below `highest_close`, the candidate can be above that close. If it is above the live stop it is set; on the next bar `low <= stop` is almost certain and the fill is `min(open, stop) x (1 - slippage)`; if the next bar opens above the stop and never trades down to it, it survives. Same code path as any stop. A new highest close afterwards can only raise it.

## 4. Strategy-owned policies and the rules

**`tests/fixtures/boundaries.py`** (edit in `check()`; the `ALLOWED` table is unchanged so `strategies: {"data"}` stays, and a narrow exception is carved out):
```python
STRATEGY_ENGINE_ALLOWED = ("stockbot.engine.exit_policy",)      # the interface file only
...
if pkg in ALLOWED and tgt in PACKAGES and tgt != pkg and tgt not in ALLOWED[pkg]:
    if not (pkg == "strategies" and tgt == "engine" and any(name == a or name.startswith(a + ".") for a in STRATEGY_ENGINE_ALLOWED)):
        out.add(...)
```
Effects: `from stockbot.engine.exit_policy import Bar` (reported by the scanner as `stockbot.engine.exit_policy` and `stockbot.engine.exit_policy.Bar`) passes. `stockbot.engine.exit_policies...` fails (prefix match requires the `.`, so `exit_policy` does not match `exit_policies`). `stockbot.engine.decide`, `.types`, `.stepping`, and the bare `from stockbot.engine import exit_policy` (scanner reports `stockbot.engine`) all fail; the last is stricter than needed and I will document that the dotted form must be used. The other direction (engine imports strategies base/registry only) is unchanged. `ARCHITECTURE.md` gets one edited row/sentence (docs only).

**Latent bug found in the same function, relevant here:** `_strategy_name()` treats `stockbot.strategies.spec` as a strategy called "spec", and the rule "a strategy may not import another strategy" excludes only `base` and `registry`. So a real strategy module `stockbot/strategies/x/rules.py` that does `from stockbot.strategies.spec import StrategySpec` (as the guide's example stub does) would be reported as importing another strategy. Proposed fix: add `"spec"` to both exclusion tuples. This does not weaken the rule (spec is shared interface code, not a strategy). Decision requested; I will not do it silently.

Also noted: the existing rule keys on `p[2]`, so `stockbot.strategies.<name>.<anything>` all map to strategy `<name>`; a second strategy folder importing the first is caught (existing fixture `strategy_imports_strategy`).

A narrower per-file rule (a file that defines an exit-policy class may import only stdlib, `stockbot.engine.exit_policy`, `stockbot.data*`) is possible with the AST; the brief's package-level wording does not need it. Proposed as an extra test, not a boundary rule: for files in `stockbot/strategies/<name>/` defining an exit-policy class, `stockbot.strategies.base/registry/spec` imports are tolerated only if you say so. Default: not added.

**New fixtures** under `tests/fixtures/boundary_violations/`: `strategy_policy_imports_library` (a policy in `stockbot/strategies/foo/` importing `stockbot.engine.exit_policies`), `strategy_policy_imports_engine_module` (imports `stockbot.engine.stepping`), and `strategy_policy_clean` (imports only `stockbot.engine.exit_policy` and `stockbot.data...`; must produce no violations). Parametrised into the existing seeded-violation test.

**`tests/unit/test_no_strategy_in_the_tree.py`** (deliberate edit, nothing else relaxed):
- Test 1 (names in `stockbot/strategies/*.py` equal the four files) stays, and a new test asserts the folder has **no sub-folders** other than `__pycache__` (that is what "no strategy in the tree today" means once folders are allowed), plus no `Strategy`/`Overlay`-shaped class anywhere under `stockbot/strategies/`.
- Test 3 (AST scan) becomes: a hit is allowed only if (a) it is one of the three interface Protocols as today, or (b) it is an **exit-policy-shaped** class (has `initial_state` and `on_corporate_action`) located under `stockbot/engine/exit_policies/` or `stockbot/strategies/<name>/`. A `propose` class or an overlay-shaped class is allowed nowhere outside tests. The expected hit list becomes the three Protocols plus exactly `FixedHold` and `TrailingStop`. The scan stays on `ast.walk` over `stockbot/` and `scripts/` with the same detection; I add a function `classify(path, class)` so the path rule is unit-testable on seeded snippets (a policy class in `stockbot/risk/x.py` must be a hit; one in `stockbot/strategies/foo/pol.py` must not).
- New test: a policy inside a strategy folder that imports a forbidden module is caught (uses the boundary fixtures above through `B.check`).

## 5. `policies_for` and wiring

New in `stockbot/engine/exit_policies/registry.py`:
```python
def policies_for(specs, extra=None) -> dict[str, ExitPolicy]
```
- `specs`: iterable of `StrategySpec`. `extra`: optional iterable of policy objects (each with `.id`) supplied by strategy-owned registration, e.g. a strategy module exposes `EXIT_POLICIES = (MyPolicy(),)` and the caller passes them.
- Builds `{policy_id: policy}` for each distinct `spec.exit_policy`: if an `extra` policy has that id use it, else `resolve()`. Failures (all `UnknownExitPolicyError` or `ValueError` subclasses, message names the id and the strategy): id neither in `extra` nor resolvable; two `extra` objects with the same id; an `extra` object whose id is a **valid library id** (it would shadow `fixed_hold_5` with other behaviour; two sources claiming one id); an `extra` policy whose `.id` is empty or not a string; an extra object that is not an `ExitPolicy`. Extras not referenced by any spec are allowed but still checked for duplicates (so a typo in `spec.exit_policy` fails loudly as "unknown", not silently).
- Optional keyword `also=()`: policy ids of already open positions (live), so a book that no longer has the strategy can still step its old positions. `decide` raises `EngineInputError` for an open position whose policy is missing, which is loud but late; `also` lets the live book include them from the journal. Default empty; unrequested complexity, so I propose to leave `also` out unless you want it. I flag it as a risk (section 8).
- Mapping keys always equal `policy.id` (needed because `decide` looks up by `spec.exit_policy` and by `pos.exit_policy_id`, and `fill_ticket` writes `policy.id` into the position).

Wiring, smallest possible edits (no change when a mapping is passed):
- `stockbot/backtest/runner.py::run_backtest`: `policies` keeps its position and meaning; if `policies is None` it becomes `policies_for([s.spec for s in strategies])`. One line plus the import (backtest may import engine). Type hint `Optional[Mapping]`. Existing tests pass dicts, so nothing changes for them.
- `stockbot/live/runner.py`: add a classmethod `Book.from_strategies(strategies, overlays=None, extra_policies=None)` that fills `policies` via `policies_for`. `default_book()` and the dataclass fields are unchanged. `run_eod` already passes `book.policies`.
- `stockbot/engine/exit_policies` is imported by backtest and live only; engine itself never imports the library, so the engine -> strategies dependency stays interface-only and there is no import cycle (`strategies` -> `engine.exit_policy` has no further imports: `exit_policy.py` is standard-library only; `engine/__init__.py` is docstring only).

Files outside the new package I expect to touch: `stockbot/backtest/runner.py`, `stockbot/live/runner.py`, `tests/fixtures/boundaries.py`, `tests/unit/test_no_strategy_in_the_tree.py`, new fixtures under `tests/fixtures/boundary_violations/`, `tests/unit/test_import_boundaries.py` (new parametrised cases only), `docs/ARCHITECTURE.md` (permission row), `docs/guides/CODEBASE_GUIDE.md`, `docs/guides/codebase_guide_data.json`, rebuilt `docs/guides/codebase_guide.html`, and `docs/exit_policies/*`. Not touched without approval: `engine/corporate.py` (finding 2 in section 0).

## 6. Documentation

`docs/exit_policies/EXIT_POLICIES.md` as specified. Guide: add to `codebase_guide_data.json` the new modules in the `packages`/engine entries and the permission in `strategy_rule`/`extra_rules`, and two lines in `add_items`; matching text in `CODEBASE_GUIDE.md` sections C.0, C.5, C.6 and G; rebuild HTML with `scripts/build_guide_html.py`. Existing guide tests (`test_guide_html.py`, `test_guides_consistent.py`) run unchanged.

## 7. Stage B test plan (tests first, shown failing)

Each required test in the brief maps to a file: `tests/unit/test_exit_policy_registry.py` (resolve, id determinism, policies_for), `test_exit_policy_fixed_hold.py`, `test_exit_policy_trailing_stop.py`, `test_exit_policy_corporate.py`, `test_exit_policy_journal.py`, `test_exit_policy_isolation.py`, plus the boundary/tree tests above. Hand-derived expectations on the fixture lake (`tests/fixtures/synth_lake.py`), the `engine_run.run_days` helper, with a small helper to build lakes having a gap session and a split. Failing-before evidence: run the new files before the package exists (ImportError / collection errors) and, for boundary and tree tests, before editing `boundaries.py` (clean-fixture and allow-case failing). Lookahead test: rewrite every bar after the as-of date in a copy of the lake and require byte-identical Decisions JSON up to the as-of date.

## 8. Risks and ambiguities in the brief

- **A1 (ambiguous)** "highest adjusted close seen since entry, including the entry bar's close" versus "initial_state starts from the entry price". The fill price is not a close and includes slippage. Options: (a) as written (default); (b) start at the entry bar close only, i.e. `initial_state` returns the entry price but treat as a floor of `0` for the max... that contradicts the brief. Decision: confirm (a).
- **A2 (finding)** pending exit not rescaled on a split (section 0, item 2). Needs approval for the shared fix; affects FixedHold only on the exit day's ex-date, and TrailingStop not at all (no pending exits).
- **A3 (finding)** `spec` treated as a strategy name in the boundary check (section 4). Needs approval.
- **A4** "N sessions" counts the entry bar as session 1 and the exit fills at the next open, so a position is held N closes. State this plainly in docs; confirm that is the intended meaning (alternative would be N sessions after entry).
- **A5** Percent as integer only: a 7.5% trail cannot be expressed; by design, to keep ids unique. Noted limitation.
- **A6** A strategy-owned policy can have any id; `policies_for` rejects ids equal to a valid library id. A strategy-owned id that merely looks like a library id with different spelling (e.g. `fixed_hold_040`) is not a library id, so it is allowed; I will additionally reject extra ids matching `^(fixed_hold|trailing_pct)_` to avoid confusion (small deviation, flagged).
- **A7** `ExitPolicy` Protocol is `runtime_checkable`, which only checks attribute presence; `policies_for` will therefore also check the three methods exist.
- **A8** Backtest `policies=None` default and `Book.from_strategies` are the only behavioural additions outside the package; existing paths unchanged.
- **A9** The live `LiveAdapter` reads `self.policies[strat.spec.exit_policy]` in `_apply_reports`; with `policies_for` the mapping has the same shape, so no adapter change.
- **A10** The strict AST scan counts any class with both `initial_state` and `on_corporate_action`; a helper class that happens to have both inside a strategy folder is allowed by the new rule even if it is not a real policy. Acceptable; noted.
- Limitations that will stand: no tick-size rounding of the trailing stop (float prices); close-based reference means a trail lags intraday highs by design; trailing stop on a very low-priced symbol can produce stops with many decimals; library ids cannot carry non-integer parameters.

## 9. Decisions needed

1. Run Stage B on the owner's machine with the real database, or accept G1/G3 here and G2 plus fingerprint by the owner? (Section 0, item 1.)
2. Approve the one-line fix to `engine/corporate.py::_rescale` for `pending_exit`, or keep it as a documented limitation with a pinned test? (A2.)
3. Approve adding `"spec"` to the strategy-name exclusions in `boundaries.py`? (A3.)
4. Confirm the `highest_close` seed (A1) and the meaning of N (A4).
5. Provide the missing `STOCKBOT_MOMENTUM_GROUNDWORK_REPORT.md`, or confirm it adds nothing. (Section 0, item 3.)
6. Confirm `extra` ids that look like library ids are rejected (A6), and that `also=` is omitted (section 5).
