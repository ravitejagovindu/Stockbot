# family_batch1: two strategies, one family (K = 2)

Status: **plan, nothing registered, nothing run.** This file fixes the shared rules and the sequence so that two strategy branches can run in parallel and be judged together. It is not a pre-registration; each member keeps its own `PREREGISTRATION.md` in `docs/strategies/<id>/` and the single family registration is written by the owner on master.

## Members (K = 2)

| id | folder | allowed by |
|---|---|---|
| `short_term_reversal` | `stockbot/strategies/short_term_reversal/` | `APPROVED_STRATEGY_IDS` in `tests/fixtures/boundaries.py` |
| `pullback_uptrend` | `stockbot/strategies/pullback_uptrend/` | same |

**Decided (2026-11-14):** `trend_breakout_100d` is NOT a member either: stage 1 showed 84% of its signals were also near_52w_high candidates the same day, and that rule was NOT DEMONSTRATED. Its branch stays unmerged and unregistered.

**Decided (owner, 2026-11-12):** `low_volatility` is NOT a member. It stays on its own branch, unmerged and unregistered (stage 1 showed the 15% sector cap holds a 10% stop to one position per sector, and the 21-session hold overlaps the next monthly signal in 74% of months; its expected edge is also far below the shared 0.15R gate). Its id stays on the allow-list only so that a later, separate family could register it. `near_52w_high` is out too (already registered as its own K = 1 family and run). A strategy not in this family is not corrected with these three.

## Shared rules (identical for every member; none is a strategy parameter)

- **Eligibility:** the shared `universe.eligibility`, no `universe_overrides`.
- **Proposals:** `top_n` = 25 per session, long only. Entry at the engine's next-open fill; sizing, caps, arbitration, costs, corporate actions and exit stepping are the shared engine's. A strategy only proposes (symbol, stop, rank).
- **Window:** one registered run each over the same window (the near_52w_high window, 2016-01-01 to 2026-10-16, unless the owner fixes another before registration). `validate_family.py` refuses members with different windows.
- **Shared gates:** `validation_gates` in `config/shared.yaml`, read at run time (min_trades 40, min_expectancy_r 0.15, min_profit_factor 1.3, max_drawdown_pct 20.0, min_alpha_pct 0.0), evaluated per member and printed beside the registered values. `min_alpha_pct` is PRE-TAX alpha with the member's idle cash credited at the risk-free rate (renamed from `min_alpha_after_tax_pct`, shared-rules). Reported, never gating: the raw alpha, illustrative after-tax alpha at `reporting.after_tax_rates_pct` (0% and 20%), and the implied annual return (trades per year x expectancy_r x max loss per trade) beside the matched Nifty CAGR.
- **B1 baseline:** matched-random entries at trade level through the shared simulator, seed **20261111**, the same draws-per-trade and minimum-filled rule for every member (as for near_52w_high: 20 draws, at least 10 filled).
- **B2 benchmark:** the Nifty matched to the member's own daily invested share, the rest at the shared risk-free rate. The member's own idle cash is credited at the same rate, after the fact (no feedback into sizing); the annualised, pre-tax, cash-credited alpha feeds the alpha gate (`stockbot/validation/benchmark_alpha.py`).
- **Sector rule:** a mapped symbol belongs to its sector in `data/reference/sector_map.csv`; every unmapped symbol is its own sector (`UNMAPPED:<SYMBOL>`), so the 15% sector cap never pools unmapped names. The 15% total-risk cap and the 12-position cap are unchanged.
- **T1 (the decision test):** per member, the paired monthly series D(m) = sum over trades entered in month m of (actual net R minus mean net R of the trade's random draws), one value per month of the window. The **three series are tested together with one Westfall-Young step-down Max-T** (one-sided, alpha 0.05 family-wise, **B = 10,000**, studentized circular block bootstrap, the same block draw applied to all three series, seed **20261111**) at block lengths **2 and 3 months**. A member is "found" only if its adjusted p-value is at most 0.05 at **both** block lengths.
- **T2:** paired statistics per member; reported only, never a decision input.
- **T3:** placebo size check of the joint procedure (the T1 pipeline on the B1 draws alone, both members at once, 1,000 replications); family-wise rejection rate outside 0.025 to 0.075 is labelled "size unreliable" and the owner decides. Nothing is recalibrated.
- **Conclusion per member:** DEMONSTRATED only if found by T1 **and** every shared gate is met; otherwise "NOT DEMONSTRATED (registered rule not met; this is not evidence of no edge)".
- **Ledger:** one `FAMILY_REGISTRATION` row for both (budget 2); one `FAMILY_RESULTS` row that carries a result for each of the two members (a missing or extra member is refused). Re-running anything is a new trial and needs a recorded reason and the owner's approval.

The tool for T1 to T3 and the gates is `scripts/validate_family.py` (tests: `tests/unit/test_validate_family.py`). On synthetic data, under the null (two, three or four cross-correlated, heavy-tailed series, 130 months, dual rule) the family-wise rejection rate measured 4.1% to 5.2% (1,000 replications each, B = 1,000), and with an edge planted in one member only that member is found. A stress case with stronger autocorrelation (lag-1 0.2) measured 7.5%; the real series show about 0.08.

## Sequence

1. **Stage 1** (each strategy branch, in its own folder only): the strategy, its `SPEC`, tests, its `PREREGISTRATION.md` draft, counts-only study if asked. No return or P&L looked at. No shared file is edited; if one must change, the branch STOPs and tells the owner.
2. **Owner review** of the stage-1 reports.
3. **One registration**: the owner writes a single `FAMILY_REGISTRATION` row (K = 2, spec hashes, shared gate hash) on master. Nothing runs before it.
4. **Runs**: one registered backtest per member, then its B1 and B2 (same seeds and rules for both).
5. **Joint validation**: `py scripts/validate_family.py --member ID=DIR` (twice, `--expect-k 2`, `--lake` for the alpha gate), then one `FAMILY_RESULTS` row with the two results. Report. STOP; the owner and reviewer decide.
