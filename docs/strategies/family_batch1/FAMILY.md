# family_batch1: four strategies, one family (K = 4)

Status: **plan, nothing registered, nothing run.** This file fixes the shared rules and the sequence so that four strategy branches can run in parallel and be judged together. It is not a pre-registration; each member keeps its own `PREREGISTRATION.md` in `docs/strategies/<id>/` and the single family registration is written by the owner on master.

## Members (K = 4)

| id | folder | allowed by |
|---|---|---|
| `short_term_reversal` | `stockbot/strategies/short_term_reversal/` | `APPROVED_STRATEGY_IDS` in `tests/fixtures/boundaries.py` |
| `trend_breakout_100d` | `stockbot/strategies/trend_breakout_100d/` | same |
| `low_volatility` | `stockbot/strategies/low_volatility/` | same |
| `pullback_uptrend` | `stockbot/strategies/pullback_uptrend/` | same |

**To confirm (owner):** the allow-list holds five ids and the family has four. This file assumes the four above, because `near_52w_high` was already registered (as its own K = 1 family, `family_ledger.csv`) and run once, with the registered conclusion NOT DEMONSTRATED. If a different four are meant, only this table changes. A strategy not in the family needs its own registration and is not corrected with these four.

## Shared rules (identical for every member; none is a strategy parameter)

- **Eligibility:** the shared `universe.eligibility`, no `universe_overrides`.
- **Proposals:** `top_n` = 25 per session, long only. Entry at the engine's next-open fill; sizing, caps, arbitration, costs, corporate actions and exit stepping are the shared engine's. A strategy only proposes (symbol, stop, rank).
- **Window:** one registered run each over the same window (the near_52w_high window, 2016-01-01 to 2026-10-16, unless the owner fixes another before registration). `validate_family.py` refuses members with different windows.
- **Shared gates:** `validation_gates` in `config/shared.yaml`, read at run time (min_trades, min_expectancy_r, min_profit_factor, max_drawdown_pct, min_alpha_after_tax_pct), evaluated per member and printed beside the registered values.
- **B1 baseline:** matched-random entries at trade level through the shared simulator, seed **20261111**, the same draws-per-trade and minimum-filled rule for every member (as for near_52w_high: 20 draws, at least 10 filled).
- **B2 benchmark:** the Nifty matched to the member's own daily invested share, the rest at the shared risk-free rate; annualised alpha after the shared tax rate feeds the alpha gate.
- **T1 (the decision test):** per member, the paired monthly series D(m) = sum over trades entered in month m of (actual net R minus mean net R of the trade's random draws), one value per month of the window. The **four series are tested together with one Westfall-Young step-down Max-T** (one-sided, alpha 0.05 family-wise, **B = 10,000**, studentized circular block bootstrap, the same block draw applied to all four series, seed **20261111**) at block lengths **2 and 3 months**. A member is "found" only if its adjusted p-value is at most 0.05 at **both** block lengths.
- **T2:** paired statistics per member; reported only, never a decision input.
- **T3:** placebo size check of the joint procedure (the T1 pipeline on the B1 draws alone, all four members at once, 1,000 replications); family-wise rejection rate outside 0.025 to 0.075 is labelled "size unreliable" and the owner decides. Nothing is recalibrated.
- **Conclusion per member:** DEMONSTRATED only if found by T1 **and** every shared gate is met; otherwise "NOT DEMONSTRATED (registered rule not met; this is not evidence of no edge)".
- **Ledger:** one `FAMILY_REGISTRATION` row for all four (budget 4); one `FAMILY_RESULTS` row that carries a result for each of the four members (a missing or extra member is refused). Re-running anything is a new trial and needs a recorded reason and the owner's approval.

The tool for T1 to T3 and the gates is `scripts/validate_family.py` (tests: `tests/unit/test_validate_family.py`). On synthetic data, under the null (four cross-correlated, heavy-tailed series, 130 months, dual rule) the family-wise rejection rate measured 4.1% to 5.2% (1,000 replications each, B = 1,000), and with an edge planted in one member only that member is found. A stress case with stronger autocorrelation (lag-1 0.2) measured 7.5%; the real series show about 0.08.

## Sequence

1. **Stage 1** (each strategy branch, in its own folder only): the strategy, its `SPEC`, tests, its `PREREGISTRATION.md` draft, counts-only study if asked. No return or P&L looked at. No shared file is edited; if one must change, the branch STOPs and tells the owner.
2. **Owner review** of the four stage-1 reports.
3. **One registration**: the owner writes a single `FAMILY_REGISTRATION` row (K = 4, spec hashes, shared gate hash) on master. Nothing runs before it.
4. **Runs**: one registered backtest per member, then its B1 and B2 (same seeds and rules for all four).
5. **Joint validation**: `py scripts/validate_family.py --member ID=DIR` (four times, `--expect-k 4`, `--lake` for the alpha gate), then one `FAMILY_RESULTS` row with the four results. Report. STOP; the owner and reviewer decide.
