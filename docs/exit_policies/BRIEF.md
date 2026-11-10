TASK: Build a small library of reusable exit policies. Separate task from any strategy. Branch: exit-policies. STOP at the points below.

WHY
The owner wants exit policies to be reusable building blocks that any strategy can name in its StrategySpec (exit_policy field). A strategy that needs something special defines its own policy inside its own strategy folder. This task builds the shared library and the rules that make both options safe. No strategy is implemented in this task.

READ FIRST
1. docs/guides/CODEBASE_GUIDE.md (sections G and H) and docs/ARCHITECTURE.md
2. docs/restructure/ENGINE_CONTRACT.md
3. stockbot/engine/exit_policy.py, engine/stepping.py, engine/fills.py, engine/corporate.py, engine/decide.py, strategies/spec.py, tests/fixtures/dummies.py, tests/fixtures/boundaries.py, tests/unit/test_no_strategy_in_the_tree.py
4. Claude_Docs/STOCKBOT_MOMENTUM_GROUNDWORK_REPORT.md, Part 2 (Q1 to Q3 and Q8): it describes what exists and what is blocked.

GIT RULES (owner's instructions, they override any default)
- Create branch exit-policies from current master. Nothing else in the name.
- No trailer, signature or attribution in any commit message or PR text: no "Co-Authored-By", no "Claude-Session", no "Generated with". Plain messages: a short imperative subject and an optional plain body.
- Small commits. Push at each STOP. Do NOT merge to master; the owner merges after review.
- Save this task text, unedited, as docs/exit_policies/BRIEF.md. Keep docs/exit_policies/STATUS.md current at each STOP (done with SHAs, open items, decisions with dates, next step, limitations).

STANDING RULES
- finsight.db is read-only (open_lake only). Record sha256 and mtime before and after every STOP; they must be identical. Run on the owner's machine with the real database; if it is absent, STOP and say so.
- Run G1 and G2 at every STOP and quote counts before and after. If G2 is killed for memory or time, say so plainly and do not report it as passed. The G3 fixture baseline test must stay identical.
- No strategy file is added to stockbot/strategies/. Test strategies and test policies exist only under tests/.
- Do not change any shared package except what this task names. If another shared change looks necessary, STOP and report it.
- No backtest on real data, no returns, no P&L. This task is about mechanics, not performance.
- State every limitation and deviation plainly.

THE DESIGN TO BUILD

1. Location and ids
- New package stockbot/engine/exit_policies/: one file per policy, plus a registry module. The interface file stockbot/engine/exit_policy.py is unchanged.
- A policy id encodes its parameters, so the strategy's config_hash covers them. Formats: fixed_hold_<N> (N a positive integer number of sessions) and trailing_pct_<P> (P a positive integer percent below the reference price, 1 to 99). A function resolve(policy_id) returns the policy object, or raises a clear error for an unknown or malformed id (including zero, negative, non-integer, and leading/trailing junk). No two ids may resolve to the same behaviour with different spellings (for example fixed_hold_040 is rejected).

2. FixedHold(hold_sessions)
- initial_state returns {} (no state). step reads ctx.days_held; when days_held >= hold_sessions it returns PolicyActions with MarketAtNextOpen(position.shares_remaining, "TIME_EXIT"); otherwise PolicyActions() (it never touches the stop). on_corporate_action returns a copy of the state unchanged. A session in which the symbol has no bar does not count as held (as the engine already behaves); confirm and test that.

3. TrailingStop(percent)
- Reference price: the highest adjusted close seen since entry, including the entry bar's close. (A close-based reference is chosen on purpose: it avoids intrabar ordering ambiguity.)
- State: {"highest_close": float}. initial_state starts from the position's entry price. step updates highest_close with the current bar's close, computes candidate_stop = highest_close * (1 - percent/100), and returns new_live_stop = candidate_stop ONLY if it is above the current live stop (the engine's rule "a stop never moves down" must hold and must not be relied on alone). The new stop applies from the NEXT bar; it is never applied to the bar that produced it. No lookahead: the policy reads only the bar it is given.
- on_corporate_action must rescale highest_close by the same factor the engine applies to the stop and the position; test with a 1:5 split, a 1:10 split, a 1:1 bonus and an unsupported action (HOLD behaviour as in engine/corporate.py). Check how the engine passes the factor and state; do not guess.
- It does not request exits itself. The stop does the exiting, filled by the engine at min(open, stop) x (1 - slippage), as for any stop.
- Fixed behaviours to pin in tests: gap down through the raised stop; a raised stop that equals the current stop; a close below the previous high (no change); the entry day.

4. Strategy-owned policies (the permission)
- A strategy may define its own exit policy inside its own folder (stockbot/strategies/<name>/...). Such a policy imports only the interface types from stockbot.engine.exit_policy (ExitPolicy, PolicyActions, MarketAtNextOpen, Limit, StepContext, Bar) and stockbot.data view types. It may not import stockbot.engine.exit_policies (the library), any other engine module, or another strategy.
- Update tests/fixtures/boundaries.py to allow exactly that: stockbot.strategies may import stockbot.engine.exit_policy and nothing else from stockbot.engine. Update tests/unit/test_no_strategy_in_the_tree.py deliberately: classes implementing the exit-policy interface are allowed in stockbot/engine/exit_policies/ and in stockbot/strategies/<name>/ only, and still forbidden elsewhere; the rule that no strategy file exists in the tree today must stay true (add a test that currently the strategies folder holds no strategy). Document why in the commit body and in STATUS.md. Do not weaken any other rule; keep the AST scan strict and add a test showing a policy inside a strategy folder that imports a forbidden module is caught.

5. How a policy gets found at run time
- The backtest runner and live runner currently take a mapping of policy id to policy object supplied by the caller. Provide ONE helper, for example policies_for(specs, extra=None), that builds the mapping from the registered specs: library ids through resolve(), strategy-owned ids through a small explicit registration (a strategy's own registry entry may carry its exit policies), failing loudly if an id is unknown or if two sources claim the same id. Wire it so run_backtest and the live book use it without any behaviour change for existing tests. If this needs an edit to backtest/ or live/ code, make it the smallest possible change and list it.

6. Documentation
- docs/exit_policies/EXIT_POLICIES.md: short, plain English: what a policy is, the two policies, the id formats, how a strategy picks one, how to write a strategy-owned one, the timing rule, and what the engine always enforces whatever the policy (initial stop, stop never down, corporate action rescale, pending exit executes before the stop check).
- Update docs/guides/CODEBASE_GUIDE.md and docs/guides/codebase_guide_data.json (and rebuild docs/guides/codebase_guide.html with scripts/build_guide_html.py) minimally: name the new modules and the new import permission, and mention the two policies in the "Add a strategy" view. Do not redesign the guide. The existing guide tests must pass unchanged.

STAGES

STOP A: DESIGN NOTE (no code yet)
- Deliver Claude_Docs/STOCKBOT_EXIT_POLICIES_DESIGN.md: for each numbered section above, how you will implement it with file and function names; the exact state schema of each policy; how the engine passes the corporate-action factor to a policy (from the code); the precise timing of the trailing stop update on the entry bar and on a bar with no data; the exact boundaries.py and test_no_strategy_in_the_tree changes; the policies_for design and every file outside the new package you expect to touch; risks; and any point where the brief is ambiguous or wrong. STOP. Do not write code until the reviewer replies.

STOP B: IMPLEMENTATION (after A is approved)
Write tests FIRST and show them failing before the code exists. Required tests:
 - resolve(): valid ids; every malformed id rejected; determinism of the id string
 - FixedHold: exit requested exactly when days_held reaches N, executed at the next open; the stop firing earlier; a session without a bar not counted; pending exit executes before the stop check; the stop is untouched
 - TrailingStop: stop rises with new closes, never lowers when the close falls; applies from the next bar only; a gap down through the stop fills at the open less slippage; entry-bar behaviour; equals-current-stop case; a stop higher than the close handled as the engine does
 - corporate actions: rescale of highest_close for 1:5 and 1:10 splits and a 1:1 bonus; an unsupported action leaves the engine's HOLD behaviour; the same trade with and without a split mid-hold gives economically identical results
 - journal round trip: state, position and pending exit survive Decisions JSON, apply_decisions and StateStore.rebuild() (live state equals rebuilt state), with each policy
 - determinism and idempotency: the same inputs twice give byte-identical decisions
 - isolation: two test strategies on different policies and symbols do not affect each other; a position keeps its own policy id; a strategy cannot import another strategy
 - a test strategy defined only under tests/ with its own policy in the way section 4 allows, and a negative test: one that imports a forbidden module fails the boundary scan
 - the spec hash changes when the policy id changes
 - lookahead: changing every bar after the as-of date does not change decisions
 - policies_for: unknown id fails loudly; duplicate id from two sources fails; library and strategy-owned both resolve
Then implement. Then docs and guide updates. Run G1, G2 and G3 and quote counts.
Deliver Claude_Docs/STOCKBOT_EXIT_POLICIES_REPORT.md: what was added (files, lines), every test and the before/after counts, the failing-before evidence, every file touched outside the new package, the fingerprint of finsight.db, and every deviation and limitation. STOP. Do not merge.

REPORT RULES
Write for a reviewer who has not seen the session. List the decisions needed from the owner and reviewer. Do not begin the next stage until told.
