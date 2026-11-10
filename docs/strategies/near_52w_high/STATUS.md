# near_52w_high: status

Last updated: 2026-11-10 (STOP 1, waiting for review).

## Done
- Branch `near-52w-high` from origin/master 4bfc188 (the exit-policies merge).
- aebad25 brief (BRIEF.md, task text verbatim); 689469b STOP 0 status and baseline.
- f8c81c2 counts-only study tool, wrapper, fixture lake and tests (`near_high_signal_count.py`, `signal_count_near_high.py`, `test_near_high_signal_count.py`, `near_high_lake.py`); 8055906 drop an unbounded probe; 470217f guide entries (md, json, html).
- Study run on the real lake, 2015-11-09 to 2026-10-16 (2710 sessions): `Claude_Docs/NEAR_52W_HIGH_SIGNAL_COUNTS.md` and `.json`.
- Report: `Claude_Docs/STOCKBOT_NEAR_52W_HIGH_STOP1_REPORT.md`.

## Tests and database
- STOP 0: G1 773 passed / 8 skipped; G2 121 passed; G3 2 passed.
- STOP 1: G1 790 passed / 8 skipped; G2 121 passed; G3 2 passed.
- finsight.db sha256 dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752, mtime 2026-11-08 12:38:02 +0530, 3,432,767,488 bytes: unchanged at every check.

## Open items (owner and reviewer)
1. Go or no-go for the rule given the alphabetical tie-break on exact new highs (82% of modelled entries at nearness 1.00; 36.9% of entries start with A).
2. Backtest window: A (2016-01-01 to 2026-10-16, pre-calendar bars) or B (from 2016-11-17).
3. Expected trade rate for the spec (model: 6.2 per month, cap-bound).
4. Sector map: 33% of selected symbols are UNKNOWN (one shared bucket, at most 2 positions at once).
5. smallest_edge_of_interest (needed at STOP 2).

## Decisions made
- 2026-11-10: branch based on origin/master (local master was stale).
- 2026-11-10: gap guard read as at least 250 of the last 252 calendar sessions; occupancy and sector-cap model as in the STOP 1 report section 3.

## Next step
STOP 2 (implementation) only after the owner and reviewer reply to the STOP 1 report.

## Limitations
- The study is a counts model; stops, risk cap, costs, gap-up cap, cash cap and fill blocks are ignored.
- Runtime: about 4.8 s per session (eligibility 3.7 s plus scoring 1.1 s median); a 2016 to 2026 backtest is projected at 3.5 hours or more before engine costs.
