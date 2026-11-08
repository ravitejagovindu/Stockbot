# Data known issues

## KI-001 — `shares_outstanding` is a single current snapshot, NOT point-in-time (recorded 2026-11-08, F2b closed)
- **What it is:** 2,217 rows, one per symbol, all labelled `effective_date = 2020-01-01`, source `yahoo_finance_current`, fetched 2026-10-02 (`fix_blocker2_shares_outstanding.py`). It holds today's issued size, not the count in force on any past date.
- **Consequence:** anything that multiplies a historical raw price by this count (the market-cap gate, Rs5,000 cr) is **unreliable before 2024** and carries **unflagged errors** wherever the share count changed after the date through events other than splits/bonus: recapitalisations and preferential allotments, QIPs, mergers (acquirer side), buy-backs, capital reductions. Names with no row (delisted, merged, renamed without a successor) get no market cap at all and are rejected as `NO_PRICE_DATA`.
- **Evidence (F2b spot-check, 20 name-dates against shareholding filings; `docs/data_audit/pit_spotcheck_results.csv`):** median |error| of a walk-back from the snapshot = 13.40%, 90th percentile = 264.97%; only 3 of 20 within 5%. Examples: YESBANK 2019-03 +1,256% (2020 rescue issue), RBLBANK 2019-03 +264% (2026 preferential allotment already in the snapshot), IDEA 2020-03 +277%, HDFCBANK 2019-03 +41.5% (HDFC Ltd merger, acquirer side), RPOWER +47%, WIPRO -18% (buy-backs). The raw snapshot used directly (no walk-back) is worse for any name that split or issued bonus shares after the date.
- **Status:** open. F2b (point-in-time derivation) was closed as "failed its pre-registered bar"; `shares_outstanding_pit` is not loaded and the screener was not switched. The code, anchors and spot-check files are in the repo, marked not used (`data/reference/README_F2b_NOT_USED.md`). No replacement rule has been decided.
- **Call sites that read it:** see `Claude_Docs/STOCKBOT_STEP10_REPORT.md`.

## KI-002 — the pre-registered Max-T test has low power at the achievable trade count; size is mildly liberal (recorded 2026-11-08, F9)
- **What it is:** at about 2.6 trades a month over 81 months (~210 trades), the Westfall-Young step-down Max-T studentized circular block bootstrap with the dual-block rule cannot detect edges below roughly **+0.25 R per trade**. Power at +0.10 R per trade is 3-16% across the four designs tested (weekly/monthly x 60/81 periods); the best (monthly, 81 periods) reaches 79% only at +0.25 R. Detecting +0.10 R would need roughly 800-1,400 trades (reviewer estimate; not measured by the study).
- **Size:** mildly liberal. Measured false-positive rate 0.0555-0.0630 against nominal 0.05 (SE 0.0049; the pre-registered window was 0.0451-0.0549). Every design misses it.
- **Evidence:** `docs/F9_PREREGISTRATION.md` (rule fixed before any result), `docs/F9_POWER_RESULTS.md`, `data/f9/power_results.json`. Caveat recorded there: dependence comes from random-entry portfolios, not a real strategy; the pool omits the market-cap gate (KI-001).
- **Status:** recorded as a finding; the study is not extended or redesigned. No gate, alpha or budget was changed. A "not significant" result from this test at this sample size is NOT evidence of no edge.

## KI-003 — no historical ASM/GSM data; Pass 2 (compliant) backtests cannot run (recorded 2026-11-08, F8)
- **What it is:** NSE's `api/reportASM` and `api/reportGSM` return current snapshots only (a request dated 2020 returned the identical response). History exists only as circular PDFs; no index is reachable without enumeration, which is not to be done. `backtest/outputs/pending_asm_gsm_matches_*.csv` are PENDING templates with no VERIFIED rows.
- **Consequence:** `Exclusions.load` is fail-closed, so no Pass 2 backtest runs; any Pass 1 result ignores the ASM/GSM exclusion.
- **Status:** open. A forward daily snapshot (table `asm_gsm_daily_snapshot`, `scripts/snapshot_asm_gsm.py`) gives point-in-time data from its start date only; it does not fill the past. See `docs/F8_FEASIBILITY.md`.

## KI-004 — earnings history not collected (recorded 2026-11-08, F8)
- **What it is:** no historical earnings calendar exists in the repo; the old scraper used dividend ex-dates and cannot produce a valid one.
- **Consequence:** Pass 2 backtests and any earnings-window exclusion cannot run.
- **Status:** collection authorised and run in Step 12 (tables `earnings_api_raw`, `earnings_results_filing`, `earnings_board_meeting`; not wired into any backtest). This entry stays open until the collection report is accepted and its coverage gaps are decided; see `Claude_Docs/STOCKBOT_STEP12_REPORT.md`.
