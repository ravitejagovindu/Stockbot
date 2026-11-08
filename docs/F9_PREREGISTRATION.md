# F9 power study — pre-registration (written and committed BEFORE any study result exists)

Date: 2026-11-08. Status: no strategy result, no study output exists at the time of writing. Measurement only; no real signals; no gate, alpha or budget is changed.

## Question
For the Westfall-Young step-down Max-T studentized circular-block bootstrap (`engine_core/max_t_bootstrap.py`, unchanged: FWER alpha = 0.05, one-sided, null-centred, joint draw across K configs, B = 2,000 draws per test), applied to portfolio-level periodic returns: what are its **size** and **power**, for **weekly vs monthly** periods and **60 vs 81 periods**?

## Data-generating process (all from the lake, no model of returns)
1. **Trade library.** Over 2020-01-01..2026-09-30 (the last 81 calendar months; lake `market_data_lake`, split/bonus adjusted through `corporate_actions_log` with the engine's `get_adjusted_series`), for every session t and a random sample of up to 15 names from that session's random-entry pool, simulate one trade with the engine's own rules: signal at close t, fill at open t+1 plus 0.10% slippage, stop = min(entry - 2 x ATR14, 30-session low) as in `risk_sizing`, then `engine_core.lifecycle_rules.advance_one_bar` with `LifecycleRules.from_config(strategy_config.yaml)` (time-decay 20 sessions, trailing, parabolic, ratchet, partial ladder) and the 0.10% exit slippage; round-trip costs from `CostModel`. Each trade is stored as its daily mark-to-market path in R (multiples of initial risk).
2. **Random-entry pool at session t:** raw 20-day ADTV >= Rs25 crore, raw price >= Rs5, >= 252 sessions of history, not a fund/ETF, and the trend filter close > SMA50 > SMA200 (adjusted) — the same pool definition as `scripts/redesigned_random_baseline.py`. The market-cap gate is NOT applied (KI-001: the share-count table is not point-in-time). Trades whose path contains an adjusted close-to-close move over 40% are dropped (unadjusted-event artefacts).
3. **Portfolio.** Entries arrive as a Bernoulli draw per session with probability 0.13 (about 0.65 a week, 2.8 a month = the baseline's observed trade rate: 159 trades in 2022-2026), one library trade drawn uniformly from that session's library entries; at most 12 open positions, no duplicate symbol, 1% of equity risked per trade. Portfolio daily return = 0.01 x sum of open trades' daily R changes. Returns are compounded within the period (weekly = ISO week, monthly = calendar month).
4. **Paired series.** Per replication: one baseline random portfolio and K = 6 "strategy" random portfolios, all independent random draws from the same library (so the nulls are true). D_k(period) = P_k - P_baseline. Window: weekly = a random contiguous block of n weeks from the 2020-2026 history; monthly 81 = the whole history, monthly 60 = a random 60-month block.
5. **Injected edge.** An edge e (R per trade) is added to config 1 only, spread evenly over each trade's holding days, so the portfolio-return shift per period is e x 1% x (trades in the period). Edges: **0, 0.05, 0.10, 0.15, 0.25, 0.50 R per trade**. In period terms 0.10 R/trade is roughly +0.28% a month, +0.065% a week at the baseline trade rate (stated here, measured in the output).

## Tests compared (cells)
{weekly, monthly} x {60, 81} periods. Circular blocks and the pre-registered dual rule (significant at BOTH blocks): **weekly blocks 4 and 8 weeks** (the existing rule, unchanged); **monthly blocks 2 and 3 months** (about one and a half to two hold lengths; fixed here before results). Single-block results are also reported for diagnosis but are not decision inputs.

## Replications and uncertainty
Size cell (edge 0, all six configs true nulls): **R = 2,000** replications; size = P(any of the 6 is declared significant by the dual rule); SE at nominal = sqrt(0.05 x 0.95 / 2000) = 0.0049. Power cells (edge > 0, config 1 non-null): **R = 1,000** each; power = P(config 1 significant by the dual rule), SE <= 0.016. Seed 20261108. Block length, periods, B and R are reported with every number.

## Decision rule (fixed now)
A design (frequency, periods) is **acceptable** only if BOTH:
1. **size within nominal +/- its standard error:** 0.0451 <= size <= 0.0549 (the nominal 0.05 +/- 0.0049); and
2. **power >= 80% at the smallest edge we have agreed to care about: +0.10 R per trade** (net of costs, over the matched random baseline).
No gate or alpha is loosened to reach either condition. If more than one design is acceptable, take the one with the highest power at +0.10 R; if none is acceptable, the report says so plainly and says which condition failed. The smallest edge that does reach 80% power in each design is reported for information (minimum detectable edge from the grid above) but does not change the rule.

## Pre-registered caveats
Random-entry portfolios from the lake are a stand-in for a strategy's return process (no real signals are used); dependence in them comes from overlapping holds, market-wide moves in the shared window and the 12-position cap. The pool omits the market-cap gate (KI-001). The result bounds the test's size and power under that dependence, not under any particular strategy's.

## Amendment 1 (2026-11-08, before any study result; only the trade-library summary existed)
The library has trades on 1,134 of 1,676 sessions (the rest have an empty pool: regime or trend filter off). A Bernoulli probability of 0.13 applied only to sessions that have a pool would give about 0.44 trades a week, not the stated ~0.65 a week (the baseline's rate: 159 trades in 4.75 years). The intent is the baseline's trade rate, so the entry probability per pool session is set to **0.188** (= 0.127 per calendar session x 1,676 / 1,134), giving about 0.64 trades a week. Nothing else changes. The realised trades per week and per month are reported with the results.
