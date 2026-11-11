TASK: Implement the "near 52-week high" strategy, with staged STOPs. Strategy id: near_52w_high. Branch: near-52w-high.

READ FIRST
1. docs/guides/CODEBASE_GUIDE.md (sections G and H), docs/guides/DATA_GUIDE.md, docs/ARCHITECTURE.md, docs/restructure/ENGINE_CONTRACT.md
2. docs/exit_policies/EXIT_POLICIES.md (the exit-policy library, now merged to master)
3. docs/PRE_LIVE_LIST.md

GIT RULES (the owner's instructions, they override any default)
- Create the branch from current master and name it exactly: near-52w-high. No "claude/" prefix, nothing else in the name.
- Do NOT add any trailer, signature or attribution to any commit message or PR text: no "Co-Authored-By", no "Claude-Session", no "Generated with". Plain commit messages: a short imperative subject and an optional plain body.
- Small commits. Push the branch at every STOP. Do NOT merge to master; the owner merges after review.
- Strategy documentation lives in docs/strategies/near_52w_high/ (BRIEF.md and STATUS.md). First action: save this task text, exactly as given, as BRIEF.md. Keep STATUS.md current at each STOP: done (with commit SHAs), open items, decisions made (dated), next step, limitations.

STANDING RULES
- Strategies only PROPOSE (symbol, stop, optional target, rank). Sizing, caps, arbitration, fills, costs, corporate actions and exit stepping are shared. A strategy must not import another strategy and must not override shared config.
- finsight.db is read-only, opened only through open_lake. This task MUST run on the owner's machine with the real database. If finsight.db is not present in your environment, STOP immediately and say so; do not substitute other data and do not continue with a design-only version. Record sha256 and mtime of finsight.db before and after every STOP; they must be identical. The last recorded values are sha256 dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752, modified 2026-11-08 12:38:02 +0530, 3,432,767,488 bytes; if they differ at STOP 0, report that before anything else.
- No return, P&L, win rate or forward price change may be computed or looked at until STOP 4, and only after the pre-registration is locked.
- Run G1, G2 and G3 at every STOP and quote counts before and after. G2 has not been run since the guides task; STOP 0 establishes the baseline. If G2 is killed for memory or time, say so plainly and do not report it as passed. Close other programs and, if needed, run G2 on its own.
- Shared code (config, data, universe, risk, engine, backtest, live, validation) is not edited to suit this strategy. If you find a shared change is needed, STOP and report it.
- State every limitation and deviation plainly. If something cannot be done as written, say so; do not work around it.

THE RULE (fixed numbers; no tuning, no variants)
- Universe: shared universe.eligibility with no strategy overrides.
- Nearness: adjusted close today divided by the highest adjusted close of the last 252 symbol bars, using AsOfView.adjusted_bars (point-in-time).
- Candidate: nearness >= 0.95.
- Gap guard: the symbol needs at least 250 bars within those 252 sessions (its own bars, as returned by the view), otherwise it is not a candidate.
- Rank: highest nearness first, ties by symbol. The strategy proposes its top 25 each session (rank = nearness).
- Entry: the engine's next-open fill; nothing strategy-specific.
- Stop: 0.85 x the signal-day adjusted close (15% below), as a price in the as-of basis.
- Exit: the library policy fixed_hold_40 (entry session is session 1; market exit at the open of session 41, so 40 closes held), or the stop, whichever comes first.
- Long-only. No regime filter, no target.

STOP 0: SETUP AND BASELINE
- Create the branch from current master, save BRIEF.md, create STATUS.md.
- Record the baseline on the owner's machine: G1, G2 and G3 counts, and the finsight.db sha256 and mtime (compare with the values above).
- Push and report in a few lines. Continue to STOP 1.

STOP 1: COUNTS-ONLY STUDY (no returns). Review gate.
- A counts-only study tool already exists, but NOT on master. It is on the set-aside branch claude/momentum-prereg-groundwork-z93w6m (a different strategy that was shelved). Do NOT merge or cherry-pick that branch. Read the files with git show and copy them under new names, adapted to this rule: stockbot/data_checks/momentum_signal_count.py -> stockbot/data_checks/near_high_signal_count.py; scripts/signal_count_momentum.py -> scripts/signal_count_near_high.py; tests/unit/test_momentum_signal_count.py and tests/fixtures/momentum_lake.py -> near_high equivalents. Nothing named momentum may appear on master. Keep the design: the lake only through open_lake and AsOfView with every query bounded by as-of; the data_checks package may import only config and data, so the eligibility function and shared settings are injected by the wrapper, as in the original. Add the new module and script to docs/guides/CODEBASE_GUIDE.md and the guide data JSON (rebuild codebase_guide.html), because the guide tests require it.
Report, per year 2016 to 2026 and in total, each measured with its date:
 a. The first date the rule can produce a valid nearness (252 bars), by both definitions: using bars before 2015-11-09, and counting only calendar sessions (the Nifty calendar starts 2015-11-09).
 b. Eligible names per session; names passing the gap guard; names with nearness >= 0.95; names proposed (top 25): median, p5, p95.
 c. Occupancy model: signal at the close of session j, entry at the open of j+1 (session 1 of the hold), market exit requested at the close of session 40 and executed at the open of session 41, 12 slots, a symbol already held is skipped. State that it ignores stops, the risk cap, costs and fill blocks. Report entries per year and total.
 d. Capital use under the shared sizing and caps: at 1% risk and a 15% stop, a position is about 6.7% of equity. Report how many slots are typically full, the invested share of equity, and how often the shared sector cap (15%) would block a candidate, using data/reference/sector_map.csv with the same SectorLookup behaviour live uses (unmapped symbols share one UNKNOWN sector). State how many selected symbols have no sector.
 e. Concentration: largest share of any one symbol, top-10 share, sector split.
 f. Data-quality counts: names dropped by the gap guard; names with a split/bonus inside the 252-bar window; names with a corporate action the engine does not adjust (demerger, merger, rights, OTHER) inside the window.
 g. Distribution of nearness among candidates (how many sit at exactly 1.00 versus 0.95 to 0.99).
 h. Measured runtime for scoring one session across the whole eligible universe, and the projected runtime for a 2016 to 2026 backtest.
Include a fixture-lake unit test showing no price after the as-of date is read, and show finsight.db unchanged.
Deliver Claude_Docs/NEAR_52W_HIGH_SIGNAL_COUNTS.md (and .json) and Claude_Docs/STOCKBOT_NEAR_52W_HIGH_STOP1_REPORT.md. STOP. The owner and reviewer decide whether the rule goes ahead, and fix the backtest window and the expected trade rate from this report. Do not start STOP 2 before they reply.

STOP 2: IMPLEMENTATION (only after STOP 1 is approved)
2.1 Strategy: add stockbot/strategies/near_52w_high/ (a folder). It implements the Strategy protocol. It imports only what stockbot/strategies may import (data view types, the shared interface and spec modules). All numbers (252, 250, 0.95, 25, 0.85) live in the StrategySpec params, are read by the strategy from there, and are covered by config_hash.
2.2 StrategySpec: id near_52w_high, version 1, status research, params as above, exit_policy "fixed_hold_40" (a library id resolved by stockbot.engine.exit_policies; do NOT build a new policy and do NOT touch the library), universe_overrides empty, expected_trade_rate from STOP 1 (trades per month), smallest_edge_of_interest left for the owner to supply (ask at STOP 2; do not invent), prereg_ref and validation_ref empty. Register it in the registry.
2.3 Update tests/unit/test_no_strategy_in_the_tree.py deliberately: it currently asserts that no strategy exists. Replace that assertion so that exactly one strategy folder (near_52w_high) is allowed and nothing else, keeping every other rule in that file strict. Explain why in the commit body and in STATUS.md.
2.4 Backtest wiring: a research script that runs the strategy through stockbot.backtest.runner.run_backtest with the shared config, the library's policies (run_backtest builds them from the spec when policies is None), the shared SectorLookup behaviour (same sector map as live), and the window agreed at STOP 1. No parameter sweep and no loops over variants.
2.5 Tests (written first and shown failing before the code exists):
 - nearness equals an independent computation on a synthetic series, including a split inside the window (adjusted series, no lookahead from a future split)
 - the gap guard, the 0.95 threshold edges (0.9499 vs 0.9500), tie order, the top-25 cut, rank = nearness
 - stop = 0.85 x signal-day adjusted close, as a price in the as-of basis
 - through the engine: exit at the open of session 41 via fixed_hold_40, the stop firing earlier, a no-bar session not counted
 - the spec hash changes when a parameter changes; status research cannot run in LIVE
 - isolation: registering a dummy second strategy does not change this strategy's proposals; strategies cannot import each other
 - lookahead: changing every row after the as-of date does not change proposals
 - determinism and idempotency through the engine on the fixture lake
 Run G1, G2 and G3 and quote the counts.
Deliver Claude_Docs/STOCKBOT_NEAR_52W_HIGH_STOP2_REPORT.md: files and lines added, tests and counts, the measured scoring time, and every deviation. STOP. Run no backtest that outputs returns.

STOP 3: PRE-REGISTRATION PACKAGE (draft; owner and reviewer set the bar)
- Prepare, but do NOT register: the exact rule and parameters (as the spec), the backtest window, the shared cost and slippage settings in force (quoted from shared.yaml), the data snapshot id, the baselines (matched-random entries through the same stops and exits; Nifty buy-and-hold; the paired comparison), the tests to be used (Max-T block bootstrap with the block length stated, paired stats, the F9 power numbers for this strategy's expected trade count), and the validation_gates and paper_criteria values that exist today. For each gate state the current value and whether it is testable at this trade count (KI-002). Mark pass/fail numbers PROPOSED; do not decide them.
- Use the family route (register_family) with one member, or explain why not. Show the exact call, with a placeholder for the commit SHA. Do not run it.
- Deliver Claude_Docs/STOCKBOT_NEAR_52W_HIGH_STOP3_REPORT.md. STOP. The owner and reviewer set the success bar and approve.

STOP 4: REGISTER, RUN ONCE, VALIDATE (only after STOP 3 is approved in writing)
- Commit the approved pre-registration, then execute the register call so the ledger row carries that commit SHA. Verify the ledger chain with verify_ledger.
- Run the backtest ONCE with the registered config and window. Save the run manifest. Do not change any parameter after seeing a result. If a bug is found, STOP and report it: any fix and rerun is a new trial in the ledger and needs a new approval.
- Run the validation steps exactly as registered: matched-random baseline, paired stats, Max-T, the power statement, and the gates evaluation (no code evaluates validation_gates today; if so, compute the registered gates in a clearly named new script and say so).
- Report all results as measured, with confidence intervals, the trade count, the occupancy and capital use actually seen, the largest drawdown, and what the test can and cannot detect. Do not interpret beyond the registered decision rule.
- Deliver Claude_Docs/STOCKBOT_NEAR_52W_HIGH_STOP4_REPORT.md. STOP. Do not change the strategy's status from research. Do not merge.

REPORT RULES (every STOP)
Write for a reviewer who has not seen the session. Include: what was done, commit SHAs, test counts before and after (G1, G2, G3), the finsight.db sha256 and mtime before and after, every deviation, every limitation, and an explicit list of decisions needed from the owner and reviewer. Do not begin the next STOP until told.
