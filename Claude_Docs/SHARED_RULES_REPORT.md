# SHARED_RULES_REPORT (branch shared-rules, from family-prep de36639)

Three commits on top, plus this report. Nothing pushed. No strategy backtest was run and no strategy return was looked at. near_52w_high was not re-run.

## What was done
**C1 sector map.** `sector_for(symbol)` now returns `UNMAPPED:<SYMBOL>` for a symbol that is not in `data/reference/sector_map.csv` (or has a blank / "UNKNOWN" sector). `SectorLookup` moved to `stockbot/data/sector_map.py`; the live runner re-exports it, the research wrapper imports it from there. The 15% sector cap therefore applies per mapped sector and never pools unmapped names. The 15% total-risk cap and the 12-position cap are unchanged (tested). Tests: `tests/unit/test_sector_map.py` (10), plus updated occupancy tests in `test_near_high_signal_count.py` and `test_phase1_components.py`.

**B1 cash symmetry.** New `stockbot/validation/benchmark_alpha.py`: `cash_credited_equity` (each day's idle cash at the previous close earns `risk_free_pct/100/252`, applied after the fact, no feedback into sizing; stated in the docstring), `benchmark_returns`, `alpha_pct`, `alpha_report` (raw, cash-credited = gate value, illustrative after-tax), `implied_annual_return_pct`. The benchmark and evaluate scripts are thin wrappers over it. Engine State is untouched.

**B2/B3.** `validation_gates.min_alpha_after_tax_pct` is now `min_alpha_pct` = 0.0 (pre-tax, cash-credited). `ltcg_tax_pct` and `stcg_tax_pct` stay 0.0. min_expectancy_r 0.15, min_profit_factor 1.3, min_trades 40, max_drawdown_pct 20.0 unchanged. New section `reporting.after_tax_rates_pct: [0.0, 20.0]`, outside `validation_gates`. The evaluate output now also prints, non-gating: raw alpha, cash-credited alpha, after-tax alpha per rate (labelled "illustrative, not tax advice"), and implied annual return (trades/year x expectancy_r x max_loss_pct_per_trade) beside the matched Nifty CAGR.

**Gate hash.** New `validation_gates` sha256: `e9b6407f908ff102dd25d9bc3b21a78a52b24c0ea082bba2cd3bb08f81188054`. Old: `805efac844810c62d6f5d74b706d7cfb0b042c5fbc3cf217add54116d783cd2f`; a test rebuilds it from the old key name and value.

## C1(b) counts (counts only; read-only; shared eligibility, no ASM ranges, 2016-01-01 to 2026-10-16, 2,674 sessions)
- Symbols ever eligible: **1,385**. Mapped: **472**. Unmapped: **913** (66%). (The map has 501 symbols in all.)
- Method: exact `eligible_symbols` per session, restricted to symbols whose single-session turnover ever exceeds the ADTV bar in that year (a 20-session mean cannot exceed its maximum, so this drops no eligible symbol). List of the 913: scratch file `ever_eligible.json` (not committed); many look like delisted or renamed names.
- Industry source in repo or lake: **none**. `securities_master` has symbol, name, series, listing date, ISIN only; the `sector` columns exist only in empty legacy tables (`active_positions`, `daily_watchlist`, `trade_analytics_log`, 0 rows).
- If a public classification is wanted (not fetched, not checked by me): the NSE index constituent lists published by NSE Indices, e.g. `ind_nifty500list.csv` (columns include Company Name, Industry, Symbol, ISIN Code), from niftyindices.com under Indices > Broad Based Indices; or BSE's "List of scrips" download, which has an Industry column. Both cover current listings, so delisted names among the 913 would still be unmapped. The owner should confirm the exact file and licence before use.

## Shared files touched, and why
- `stockbot/data/sector_map.py` (the one sector rule), `stockbot/live/runner.py` (SectorLookup moved out, re-exported)
- `stockbot/data_checks/near_high_signal_count.py` (unmapped counted via `is_mapped`; report groups unmapped in one row)
- `stockbot/config/shared.py`, `stockbot/config/shared.yaml` (rename, `reporting` section, validation of rates), `stockbot/strategies/spec.py` (`reporting` added to NON_OVERRIDABLE; a test requires it to equal the config list)
- `stockbot/validation/benchmark_alpha.py` (new)
- `scripts/benchmark_nifty_matched_near_52w_high.py`, `scripts/evaluate_validation_gates_near_52w_high.py` (wrappers; `validate_family.py` needed no code change, only its test)
- `scripts/research_near_52w_high.py` (docstring and import only)
- Tests: `test_sector_map.py`, `test_benchmark_alpha.py` (new); `test_shared_config.py`, `test_near_52w_high_validation_scripts.py`, `test_near_high_signal_count.py`, `test_phase1_components.py`, `test_validate_family.py` (updated)
- Docs: `docs/guides/CODEBASE_GUIDE.md`, `DATA_GUIDE.md`, `codebase_guide_data.json`, `codebase_guide.html` (rebuilt; data_guide.html rebuilt with no content change); `docs/strategies/family_batch1/FAMILY.md`; `docs/strategies/near_52w_high/STATUS.md` (note only, as asked); `docs/shared/shared-rules/{BRIEF,STATUS}.md`.
- Not touched: strategy folders, pre-registrations, ledgers, `results_4B/`, the DB.

## Tests
- G1 (`tests/unit tests/integration`): **914 passed, 8 skipped**.
- Full G2 (`STOCKBOT_DATA_TESTS=1 STOCKBOT_FINAL_CHECK=1 pytest tests`): **1043 passed**, 0 failed, 0 skipped (20 min).
- G3 (`tests/unit/test_g3_fixture_baseline.py`): 2 passed.
- finsight.db sha256 unchanged: dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752 (checked before and after).

## Not run
- No backtest, no near_52w_high re-run, no real-data validation. The new alpha code and the implied-return line were exercised on synthetic run directories only, never on the real lake.
- The first attempts at G1 and the count were killed by a low-memory reaper and re-run one at a time; the results above are from the re-runs.
- HTML guides rebuilt without `--stamp` (date and commit in the footer unchanged).

## Deviations and choices
- Cash credit is multiplicative: each day's return gets `idle share(t-1) x rf/252` added, then compounds, mirroring the benchmark's form. A simple additive-interest variant would differ slightly.
- The alpha gate's bootstrap interval and the descriptive sub-period alphas now use the cash-credited, pre-tax series.
- `evaluate()` result: key `tax_pct` removed; `alpha`, `implied_annual_return`, `gate_alpha_is_pre_tax` added.
- `ltcg_tax_pct` (0.0) is kept in `validation_gates` as instructed, but no gate code reads it now; it only stays in the hash.

## Decisions needed
1. **Shared-config hash changes for every run** (`manifest.py` hashes `flat()`, which gained `reporting` and the renamed key). Anything pinned to the old config hash will differ; near_52w_high's registered records are untouched.
2. **Portfolio API** (`stockbot/live/api/portfolio.py`) will list each unmapped name as its own sector row. Left as is; say if you want them grouped for display only.
3. **Classification file** for the 913 unmapped names (see above), or accept them as single-name sectors.
4. The 15% cap with 913 of 1,385 names unmapped now rarely binds for most signals; that is the intended effect, but it makes concentration in unmapped names a total-risk-cap question only.
