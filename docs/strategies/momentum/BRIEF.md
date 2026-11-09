You are working on StockBot (personal rule-based NSE/BSE trading engine, end-of-day, long-only, no order routing) at F:\Projects\Ravi\StockBot. This session covers ONE strategy only: the momentum / relative-strength strategy. Do not work on any other strategy.

READ FIRST, in this order, before doing anything:
1. docs/guides/CODEBASE_GUIDE.md (package map, engine flow, how a strategy plugs in)
2. docs/guides/DATA_GUIDE.md (database, tables, known issues KI-001 to KI-004)
3. docs/ARCHITECTURE.md and docs/restructure/ENGINE_CONTRACT.md
4. docs/PRE_LIVE_LIST.md (known open items, not part of this task)

STANDING RULES (always apply)
- The architecture is fixed: strategies only PROPOSE (symbol, stop, optional target, rank). Sizing, caps, arbitration, fills, costs, corporate actions and exits stepping are shared. Do not edit shared code (config, data, universe, risk, engine, backtest, live, validation) to suit a strategy. If you think a shared change is needed, STOP and say so in the report instead of making it.
- finsight.db is read-only. Open it only through stockbot.data.lake.open_lake. Record its sha256 and mtime before and after your work; they must be identical.
- Never compute or look at forward returns, P&L or win rates unless the task explicitly says so. Pre-registration comes before any backtest.
- Run G1 (tests/unit + tests/integration) and G2 (STOCKBOT_DATA_TESTS=1 STOCKBOT_FINAL_CHECK=1 pytest tests) before reporting. Quote counts before and after. The import-boundary test must pass.
- Write your report to Claude_Docs/ under the file name the task gives, commit, push, and STOP. Do not start anything not in the task. State every limitation and every deviation plainly. If something in the task cannot be done as written, say so rather than working around it.
- The owner reads the report and passes it to a separate reviewer, so write for a reader who has not seen this session.

STRATEGY BRIEF AND STATUS (one folder per strategy)
- This session's strategy folder is docs/strategies/momentum/. Create it if it does not exist.
- First action: save the task text you were given, exactly as written, to docs/strategies/momentum/BRIEF.md. Do not edit it afterwards. If the owner changes the task later, add BRIEF_v2.md and keep the old one.
- Keep docs/strategies/momentum/STATUS.md up to date. At each stop, record: what has been done (with commit SHAs), what the current open items are, which decisions the owner or reviewer made (with dates), what must happen next, and any limitation found.
- These files hold documentation only. Do not put code, strategy parameters used in a run, or any results in them. The strategy code itself will live in its own package later, as the guides describe.
- A new session picking this strategy up must read BRIEF.md and STATUS.md first.
- Commit both files with your report.

THE TASK FOLLOWS.

TASK: Pre-registration groundwork for the first strategy (relative-strength ranking). Read-only study plus a design check. Do NOT write a strategy file, do NOT register anything in the ledger, do NOT compute any return, P&L, win rate or forward price change. STOP when done.

CONTEXT
The owner wants the first strategy to be a relative-strength (momentum) ranking rule, long-only, end-of-day. Before anything is registered, we must know whether the rule produces enough trades, and whether the engine can express its exit. Looking at outcomes before pre-registration would contaminate the test. This task is counts and design only.

THE RULE (draft, fixed numbers, not to be tuned or varied)
- Universe: shared universe.eligibility with no strategy overrides.
- Score: adjusted-close return over the last 126 sessions, skipping the most recent 5 sessions. In words: close[t-5] / close[t-5-126] - 1, using split/bonus-adjusted closes as of the as-of date through AsOfView.adjusted_bars.
- Trend condition: adjusted close[t] > 200-session simple average of adjusted close.
- Proposal: each session, candidates are eligible names meeting the trend condition. Rank by score descending, ties by symbol. The strategy proposes the best-ranked names. Shared caps and arbitration limit this to 12 positions and 15% total risk (shared.yaml).
- Stop: entry minus 3 x ATR(14).
- Exit: a fixed 20-session hold (market exit at the next open after the 20th session), or the stop, whichever comes first.

PART 1: COUNTS-ONLY SIGNAL STUDY (read-only)
Build it as a script in stockbot/data_checks/ (logic) plus a thin wrapper in scripts/, for example signal_count_momentum.py. Open the lake only through open_lake and AsOfView, and bound every query by as-of. finsight.db sha256 and mtime must be unchanged afterwards.
Do not import anything from, or add anything to, stockbot/strategies/. This is a study tool, not the strategy.
Report, per year 2016 to 2026 and in total:
 a. The first date on which the rule can produce a valid score (needs 200 sessions for the average and 131 for the score, plus the calendar starting 2015-11-09). State the date.
 b. Eligible names per session: median, p5, p95.
 c. Names meeting the trend condition per session: median, p5, p95.
 d. Names meeting the trend condition and having a valid score, per session.
 e. An approximate trade count under the caps, using only a mechanical simulation of occupancy: each session, fill free slots (up to 12) from the ranked list at the next open, hold exactly 20 sessions, ignore stops, ignore the 15% risk cap, ignore costs. State clearly that this is an upper-bound occupancy model and that stops would shorten holds and raise the count.
 f. Concentration of the occupancy model: the largest share of any single symbol, and the share in the top 10 symbols (use data/reference/sector_map.csv for a sector split and say how many symbols have no sector).
 g. Distinct symbols ever selected; median and maximum holding overlap between selected names (count of positions at once).
 h. Data-quality counts that would affect the rule: names dropped for fewer than 200 sessions; names where the split/bonus adjustment affects the 126 or 200-session window; names with a trading gap longer than 5 sessions inside the window (EQ-only lake effect, PRE_LIVE_LIST item 11).
Mark every figure "measured <date>". Do not use any figure from price changes after the signal date.

PART 2: ENGINE DESIGN CHECK (read-only, no code changes)
Answer from the code, with file and function names:
 1. Which ExitPolicy implementations exist today in stockbot/engine/exit_policy.py?
 2. Can they express a fixed N-session time exit plus the initial stop? If not, what exact small addition is needed? Describe the plug-in (class name, state it needs, how it counts sessions held, how it requests MarketAtNextOpen). Do not implement it.
 3. Does ctx or position state expose sessions held and entry date? Does the exit state survive the journal and rebuild() round trip?
 4. Is ATR(14) available in stockbot/data/indicators.py, computed on adjusted prices as of the as-of date? Show the signature. Is there a lookahead risk on the 126-session score or 200-session average with corporate actions that fall inside the window?
 5. Can a strategy ask for the ranking across all eligible symbols efficiently, or does each symbol call AsOfView separately? Give the measured time for scoring one session across the full eligible universe, and the projected runtime for a 2016 to 2026 backtest.
 6. How does StrategySpec.expected_trade_rate get used, and what units?
 7. Which fields of the pre-registration (stockbot/validation/prereg_lock, ledger/pre_registered_configs.yaml) must be filled for a new strategy? List them with their meaning. Do NOT fill them. The owner and reviewer will set the success bar.
 8. Anything in the shared engine that this rule would need changed. If the answer is "yes", say so clearly and stop short of changing it.

DELIVERABLE
Claude_Docs/STOCKBOT_MOMENTUM_GROUNDWORK_REPORT.md with Part 1 tables and Part 2 answers. Commit the study script, its wrapper and a unit test on the fixture lake showing the counts are produced without touching returns (assert that no price after the as-of date is read). Run G1 and G2, quote counts, and re-hash finsight.db.

GROUND RULES
- Do not change the rule's numbers or add variants. If you think a number is a bad choice, say so in the report, but report on the rule as written.
- Do not look at, compute, or mention any forward returns, P&L or win rates, even informally.
- No new strategy file, no registration in the trial ledger, no edits to shared engine/validation code.
- State every limitation plainly.

STOP when the report is pushed. Do not begin implementing the strategy.
