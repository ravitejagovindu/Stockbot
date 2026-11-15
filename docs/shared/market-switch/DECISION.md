# Market switch: decision

**Decision (owner): the market switch is OPTIONAL, not a shared default.** `market_switch_v1` stays in the code as an overlay that a strategy declares (`StrategySpec.overlays = {"market_switch_v1": "1.0.0"}`); `shared.yaml` `overlays.default` is `[]`. Strategies that do not declare it behave exactly as on master.

## Criteria (set before the numbers were looked at)
The switch would have become a shared default only if, in BOTH the index-only study (B2) and near_52w_high (B3):
1. the maximum drawdown is cut by at least a quarter (at least 25% lower), AND
2. no more than 2 percentage points of yearly return (CAGR) are lost.

## The four observed numbers (window 2016-01-01 to 2026-10-16; full results in `Claude_Docs/MARKET_SWITCH_REPORT.md`)
| study | max drawdown without -> with the switch | change | CAGR without -> with | change | criteria met |
|---|---|---|---|---|---|
| index only (Nifty; cash at 6.5% while ACTIVE) | 38.44% -> 24.07% | 37.4% lower | 10.43% -> 3.48% | -6.95 pp | drawdown yes; return NO |
| near_52w_high (engine run, raw CAGR) | 26.92% -> 30.56% | 13.5% higher | 6.53% -> 2.09% | -4.44 pp | drawdown NO; return NO |

(near_52w_high CAGR with cash credited at 6.5%: 8.37% -> 4.39%, -3.98 pp; same verdict.)

Neither study meets both criteria, so the criteria for a shared default are not met. Hence: optional, not shared.

## Caveats
- Every number is from a single descriptive run on one window; none is a registered trial, none has a confidence interval, nothing was written to the ledger.
- Only the exact old rule was examined (Nifty close below its 200-day average or VIX above 22 to block entries; release after 3 consecutive sessions with Nifty above its 20-day average and VIX below 20). Other thresholds, other windows or other forms of the rule were not examined.
- The stored near_52w_high 4B run does not reproduce on the current code (8 of about 72 trades identical in a 2016 window with `overlays=[]`); the cause is not verified. The WITHOUT side used here is a fresh run on current code, not the stored result.
- The WITHOUT sides for pullback_uptrend and short_term_reversal are the stored run1 results; their reproduction on current code was not checked. Those two strategies are not part of the decision criteria.
- 2016 and 2026 are partial calendar years in the worst-year figures.

## How to opt in
Declare the overlay in the strategy's spec. It then enters that strategy's spec hash and run manifest, is evaluated once per session by `stockbot.engine.decide` in backtest, paper and live alike, blocks only that strategy's new entries while ACTIVE (reason `MARKET_SWITCH`), and logs its state in `overlay_state_after` and in `daily.json`. Its five numbers are the single source `overlays.market_switch_v1_*` in `shared.yaml`.
