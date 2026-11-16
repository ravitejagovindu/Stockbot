# riskadj_momentum: owner decision to paper-trade (2026-11-16)

This file records an owner decision. It changes no registered result.

## The registered result stands
family_batch2 (K = 1), run once, recorded in the family ledger (results row be7bee6e...): **NOT DEMONSTRATED**.
T1 significant at both blocks (adjusted p 0.0082 and 0.0096). Gates met: trades 647, expectancy 0.211 R, profit factor 1.45, cash-credited alpha +5.45 pp. Gate NOT met: max drawdown 34.32% against 20.0.

## Decision (owner exception)
riskadj_momentum goes to PAPER trading despite the failed drawdown gate. Reasons given:
- its worst drawdown (34.3%) was no deeper than the Nifty's worst in the same window (about 38%), and in the 2020 fall it lost 12.6% peak to trough;
- every other gate and the test against random picks were met.
The validation gate `max_drawdown_pct` stays 20.0 in the shared config. The strategy is NOT validated; `validation_ref` stays empty; status `live` remains impossible without a validation record.

## Known weaknesses accepted for the paper phase
- The 10 best of 647 trades carry 60% of net R and 94% of the paired difference against random picks.
- The deepest drawdown (2024-02 to 2025-10) had not recovered by the end of the data.
- Win rate 40.5%; long runs of stop-outs are normal for this rule.
- Rules, parameters and the exit policy are frozen as registered (spec params unchanged). Only `status` changes to `paper`, which changes the spec hash.

## Paper pass marks (owner, fixed before the paper phase starts)
- maximum drawdown: below 35%
- minimum closed trades: 30
- all other paper criteria: as in the shared config at the start of the paper phase, unless changed by a recorded decision before the start.
Reviewer note: a 35% limit will rarely bind within a paper phase of a few months, so this mark gives little information on its own; the comparison with the backtest (expectancy, win rate, profit factor) carries the weight.

## Operations
- Daily job at 19:30 IST (data update, then the paper run).
- A daily report or dashboard is deliberately NOT planned for now (last item, owner instruction).
- Open: risk per trade for the paper phase (shared rule is 1.0%); the daily data update is not built yet.
