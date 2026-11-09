# Paper Trade Criteria

**Written:** 2026-10-20 (before seeing any new results — per plan ground rule)  
**Status:** ACTIVE — do not modify after the paper run starts (Gate G3)

---

## Backtest Pass Criteria (Gate G2)

Must be met on **all** windows (TUNE and TEST), net of costs and tax, using the corrected engine.

| Criterion | Threshold | Notes |
|-----------|-----------|-------|
| Max Drawdown | < 15% | Strict less-than on equity curve |
| Alpha (after-tax CAGR − after-tax Nifty CAGR) | ≥ −2.0% | Owner decision D3. No grace below −2%. |
| Expectancy | ≥ +0.15 R per trade | Net of all costs and tax |
| Profit Factor | ≥ 1.3 | Gross wins / gross losses |
| Minimum Trades | ≥ 40 | Per window — fewer invalidates the window |
| Compliance Applied | = true | ASM/GSM + earnings exclusions must be VERIFIED |

> **Important:** if any single window fails any single criterion, the backtest does NOT pass. Do not loosen gates. Go back to strategy design.

---

## Paper Run Pass Criteria (Gate G4)

### Duration Requirement
**OR condition (owner decision D4):** paper run is eligible for evaluation when:
- ≥ 90 calendar days of paper trading, **OR**
- ≥ 60 closed trades

Whichever comes first. Every manual DB edit must be logged in `paper_log.md`.

### Performance Criteria (evaluated at eligibility)

| Criterion | Threshold | Definition |
|-----------|-----------|------------|
| Expectancy gap | within 0.25 R of backtest | \|paper expectancy − backtest avg expectancy\| ≤ 0.25 R |
| Win rate gap | within 12 percentage points | \|paper win rate − backtest win rate\| ≤ 12 pts |
| Profit Factor | ≥ 1.2 | Paper gross wins / gross losses |
| Max Drawdown | < 12% | Paper equity curve (tighter than backtest gate) |
| Skipped ticket rate | < 40% | SKIPPED / (OPENED + SKIPPED) from daily_watchlist |

> **Partial exits are NOT counted as separate trades.** One position = one trade (merged by position_id).

### What "paper" means
- `runtime.mode: PAPER` in `strategy_config.yaml`
- Fills are simulated at next-open + slippage; no real broker interaction
- Results stored in `trade_analytics_log WHERE mode='PAPER'`
- Equity tracked via `engine_core/equity.py::paper_equity()`

---

## Change Control During the Paper Run

- **No strategy-affecting commits** once Gate G3 is set. Any commit that touches `engine_core/` or `strategy_config.yaml` fires the git lock and **restarts the paper count from zero**.
- Allowed in parallel: tests, docs, UI polish, verifying historical ASM/GSM data, `scripts/` tools (health check, report).
- Every manual DB edit must be logged in `paper_log.md` with date and reason.

---

## Path to Live (Gate G5)

1. `scripts/paper_report.py` shows `passed: true` in `docs/PAPER_RESULT.json`
2. Manual review of worst 5 trades and all skipped tickets
3. Set `runtime.mode: LIVE`, re-run corrected backtest, re-authorize (requires `PAPER_RESULT.json`)
4. Start at 25% of intended size (`max_loss_pct_per_trade: 0.25`) for first 20 live trades
5. Scale to full only after ≥ 30 more live trades within paper-derived bands
