# low_volatility: brief (task text as given, plus the working interpretation)

BRANCH: low_volatility   REPORT: Claude_Docs/LOW_VOLATILITY_STAGE1_REPORT.md

## Standing instructions (the owner's header)
- ONE task in the StockBot repo (rule-based NSE/BSE end-of-day engine, no order routing). Branch from latest master with the branch name given. Read the guides, `docs/exit_policies/EXIT_POLICIES.md` and the worked example `docs/strategies/near_52w_high/` and `stockbot/strategies/near_52w_high/`.
- Keep this BRIEF.md (goal, rules, constraints) and STATUS.md (done, next, blockers) current at every commit.
- Commits: plain messages. No Co-Authored-By, no Claude-Session, no "Generated with" lines, in commits or PR text. Branch name exactly as given.
- `finsight.db` is read-only; its sha256 must stay `dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752`. If the DB is not in the session, STOP and say so. Never invent data.
- Do not edit shared files (`stockbot/engine`, `stockbot/validation`, `config/shared.yaml`, ledgers, `docs/guides`, `tests/fixtures`). If one needs a change, STOP and tell the owner.
- Numbers in the block are FIXED. Do not tune. If counts show a rule is unworkable, STOP and report; the owner decides.
- Finish by pushing the branch and writing the report file named in the block. Say what ran, what did not run, and the full test results (G1, then full G2).

## The block (Stage 1 only)
Rule (long-only, monthly rebalance signal, entry next open):
- Signals only on the first trading session of each calendar month (month differs from the previous session's).
- Shared eligibility. min_bars 252.
- vol60 = standard deviation of the last 60 daily log returns. Rank lowest vol60 first, then higher 20-session ADTV, then symbol. top_n 25.
- Stop = 0.90 x signal close (10%). Exit policy fixed_hold_21. status research.

Counts only: signals per month, sector concentration of the top 25 (low-vol names cluster in FMCG, pharma and utilities), how many would be blocked by the 15% sector cap given 10% stop sizing (1% risk / 10% stop = 10% positions, so about one per sector), the typical number of positions that actually fit, and the expected_trade_rate. Report the sector-cap effect plainly. Do not change the rule to work around it.

Draft PREREGISTRATION.md as in Block 1.

## Working interpretation (choices the text leaves open; each is listed in STATUS.md for the owner)
1. "Block 1" is not in this session; the draft follows the structure of `docs/strategies/near_52w_high/PREREGISTRATION.md` and the family plan `docs/strategies/family_batch1/FAMILY.md`.
2. Stage 1 here = the strategy module, its SPEC and tests, a counts-only study, the draft pre-registration and the report. No backtest, no return, no P&L, no forward price was computed or looked at.
3. vol60 uses the sample standard deviation (ddof = 1) of 60 log returns of the point-in-time adjusted close (61 closes). The ranking does not depend on ddof.
4. `min_bars` 252 is read as: 252 own adjusted bars in the view and a bar on the signal date (the near_52w_high gap guard of 250-of-252 is NOT applied; the rule does not state one). Missing sessions inside the 61-close window and zero volatilities are counted, not filtered.
5. Shared sector cap and sizing are those of the engine (`max_sector_exposure_pct` 15, `max_loss_pct_per_trade` 1, `max_concurrent_positions` 12); unmapped symbols share one UNKNOWN sector, as live.
6. The study tool lives in `scripts/signal_count_low_volatility.py` (a strategy-owned path), not in `stockbot/data_checks/`, so that no guide has to change.
