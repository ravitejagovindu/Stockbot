# riskadj_momentum: status

Last updated: 2026-11-15 (stage 1 done; waiting for the owner's review).

## Done
- Allow-list: `riskadj_momentum` added to APPROVED_STRATEGY_IDS (own commit 0da1b65).
- Strategy (`stockbot/strategies/riskadj_momentum/`: strategy.py, indicators.py, exits.py), spec hash `72dbec2c3da600cfe6de049a64efd530171ef2f539075f53e57a05e972ef27dc`; 44 unit tests on fixture lakes.
- Counts study over the real lake (counts only; `scripts/signal_count_riskadj_momentum.py`, results in `counts/`): 130 signal months, first signal 2016-12-01 (the first 11 months of the window are empty by the rule's definition), 25 or more qualifying in every later month, no score ties, median initial stop distance 11.9% (16% of names at the 8% floor), implied position 8.8% of equity on average.
- `expected_trade_rate` proposed and set at 1.9 a month (slot arithmetic, 6-month hold; 2.85 at 4 months, 1.42 at 8 months).
- Draft `PREREGISTRATION.md` (family_batch2, K = 1). Nothing registered.
- Baseline and family tools checked (section 8 of the report): what works and what does not.
- G1, G2, G3 and the DB hash: see the report.

## Open items (owner)
See `Claude_Docs/RISKADJ_MOMENTUM_STAGE1_REPORT.md`, "Decisions needed".

## Next step
None until the owner replies. No backtest on the real lake has been run; no return of this strategy has been looked at.
