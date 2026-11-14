# shared-rules: sector, cash and gate fixes (shared infrastructure, no strategy)

Branch `shared-rules`, worktree `StockBot_wt_sharedrules`. Not pushed until the owner says so.

## Goal
Three fixes to shared rules before the family_batch1 registration. Every number is fixed by the owner; nothing is tuned.

- **C1 sector map.** Every unmapped symbol is its OWN sector (key `UNMAPPED:<SYMBOL>`) in backtest, paper and live, one shared implementation (`stockbot/data/sector_map.py`). The 15% sector cap then applies per mapped sector and never pools unmapped names. Total risk cap (15%) and the 12-position cap are unchanged. Report counts of unmapped symbols and whether any industry source exists; do not guess sectors.
- **B1 cash symmetry.** The B2 benchmark credits `risk_free_pct` on the un-invested share; strategy cash earned nothing. Fix on the strategy side in the analytics layer (not engine State): an adjusted equity series where each day's idle cash (previous close) earns `risk_free_pct/100/252`. Alpha reported raw and cash-credited; the gate uses cash-credited. One shared module in `stockbot/validation/`.
- **B2 tax and gate name.** `validation_gates.min_alpha_after_tax_pct` becomes `min_alpha_pct` (PRE-TAX cash-credited alpha). `ltcg_tax_pct` and `stcg_tax_pct` stay 0.0. New `reporting.after_tax_rates_pct: [0.0, 20.0]` (outside validation_gates, so outside the gate hash), used only for a non-gating "illustrative, not tax advice" line.
- **B3 gate arithmetic.** `min_alpha_pct` = 0.0 (was -2.0). Other gates unchanged (min_expectancy_r 0.15, min_profit_factor 1.3, min_trades 40, max_drawdown_pct 20.0). Reported, non-gating: implied annual return = trades per year x expectancy_r x max_loss_pct_per_trade, beside the matched Nifty CAGR.

## Constraints
- finsight.db is read-only (open_lake only), sha256 dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752 before and after.
- No strategy backtest, no strategy returns looked at. near_52w_high is NOT re-run; its ledger rows and `results_4B/` stay untouched.
- Strategy folders (`stockbot/strategies/<id>/`) and pre-registrations untouched.
- Commits: plain messages, no trailers. No push.
- Finish: full G1, full G2 (STOCKBOT_DATA_TESTS=1 STOCKBOT_FINAL_CHECK=1 pytest tests), G3, DB hash unchanged; report in `Claude_Docs/SHARED_RULES_REPORT.md`; then stop.
