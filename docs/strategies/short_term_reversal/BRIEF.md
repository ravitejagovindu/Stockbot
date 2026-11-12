# short_term_reversal: brief

Task as given by the owner (kept as the working brief; numbers in the block are FIXED, do not tune).

## Session rules
You are a dev session for ONE task in the StockBot repo (rule-based NSE/BSE end-of-day engine, no order routing).
- Start: git fetch, branch from latest master using the branch name given below. Read docs/guides/CODEBASE_GUIDE.md, DATA_GUIDE.md, docs/exit_policies/EXIT_POLICIES.md, and the worked example docs/strategies/near_52w_high/{BRIEF,STATUS,PREREGISTRATION}.md plus stockbot/strategies/near_52w_high/.
- Keep docs/strategies/<id>/BRIEF.md (goal, rules, constraints) and STATUS.md (done, next, blockers) current at every commit.
- Commits: plain messages. NO Co-Authored-By, NO Claude-Session, NO "Generated with" lines, in commits or PR text. Branch name exactly as given.
- finsight.db is read-only; its sha256 must stay dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752. If the DB is not in your session, STOP and say so. Never invent data.
- Do not edit shared files (stockbot/engine, stockbot/validation, config/shared.yaml, ledgers, docs/guides, tests/fixtures). If one needs a change, STOP and tell the owner.
- Numbers in the block are FIXED. Do not tune. If counts show a rule is unworkable, STOP and report; the owner decides.
- Finish by pushing the branch and writing the report file named in the block. Say what ran, what did not run, and the full test results (G1, then full G2).

BRANCH: short_term_reversal   REPORT: Claude_Docs/SHORT_TERM_REVERSAL_STAGE1_REPORT.md

## Stage 1: implement, count signals (no returns), draft the pre-registration. Then STOP.
Rule (long-only, signals on session close, entry next open):
- Shared eligibility. min_bars 10.
- ret5 = close[t] / close[t-5 sessions] - 1. Signal if -0.30 <= ret5 <= -0.07 (the -0.30 floor guards against unadjusted corporate-action artifacts).
- Rank: lowest ret5 first, then higher 20-session ADTV, then symbol. Ordinal rank top_n..1, top_n = 25.
- Stop = 0.92 x signal close. Exit policy fixed_hold_5. status research.

Build: stockbot/strategies/short_term_reversal/{__init__,strategy}.py with SPEC, propose(), explicit register(registry); unit tests (rule, ranking, ties, edge cases, point-in-time safety). Copy the counts-study pattern from stockbot/data_checks/near_high_signal_count.py into a new module and script. Counts only: signals per year and per month, days with more than 25 signals, share of signals on the 10 worst market days (clustering), sector spread, tie rate, stop fit (stop distance must be >= ~6.7%), and an expected_trade_rate estimate after shared caps.

Draft docs/strategies/short_term_reversal/PREREGISTRATION.md in the near_52w_high format. Mark the family-level parts "filled at family registration". smallest_edge_of_interest 0.15R, shared gates.

## Constraints that shape the layout (found while implementing; see STATUS.md)
- `tests/fixtures/boundaries.py` already lists `short_term_reversal` in APPROVED_STRATEGY_IDS, so no shared file needs editing for the new strategy folder.
- The guide tests require every module and script outside a strategy-owned path to be named in `docs/guides/CODEBASE_GUIDE.md` (a shared file this task may not edit). The counts-study module therefore lives at `scripts/strategies/short_term_reversal/signal_count.py` and its wrapper is `scripts/signal_count_short_term_reversal.py`, both strategy-owned paths (`strategy_owned()` in `tests/fixtures/boundaries.py`). `stockbot/data_checks/` is not used.
- Interpretations of the brief that the owner should confirm are listed in STATUS.md under "Decisions needed".
