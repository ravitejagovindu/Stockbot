import json
import sqlite3
import os
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "finsight.db"
AUDIT_PATH = BASE_DIR / "backtest" / "outputs" / "audit.json"
REPORT_PATH = BASE_DIR / "confidence_report.md"

def generate_report():
    print("Generating FInsight Confidence Report...")
    
    # 1. Load Baseline (Backtest Expectation)
    if not AUDIT_PATH.exists():
        print(f"[ERROR] Could not find backtest audit at {AUDIT_PATH}")
        return

    with open(AUDIT_PATH, "r", encoding="utf-8") as f:
        audit = json.load(f)

    regimes = audit.get("regimes", {})
    total_backtest_trades = 0
    weighted_win_rate_sum = 0.0

    for r_name, r_data in regimes.items():
        t = r_data.get("total_trades", 0)
        wr = r_data.get("win_rate", 0)
        total_backtest_trades += t
        weighted_win_rate_sum += (t * wr)

    backtest_win_rate = (weighted_win_rate_sum / total_backtest_trades) if total_backtest_trades > 0 else 0

    # 2. Load Reality (Live Paper Trades from DB)
    if not DB_PATH.exists():
        print(f"[ERROR] Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Get total trades and average Realized R:R
    cursor.execute("SELECT COUNT(*), AVG(realized_rr) FROM trade_analytics_log")
    row = cursor.fetchone()
    live_total_trades = row[0] if row[0] else 0
    live_avg_rr = row[1] if row[1] else 0.0

    # Get winning trades (where Realized R:R is positive)
    cursor.execute("SELECT COUNT(*) FROM trade_analytics_log WHERE realized_rr > 0")
    row = cursor.fetchone()
    live_winning_trades = row[0] if row[0] else 0

    live_win_rate = (live_winning_trades / live_total_trades) if live_total_trades > 0 else 0

    conn.close()

    # 3. Calculations & Variance
    win_rate_variance = live_win_rate - backtest_win_rate
    
    # Decay Ratio is based on Win Rate retention
    decay_ratio = (live_win_rate / backtest_win_rate) if backtest_win_rate > 0 else 0

    if live_total_trades < 30:
        status = "INSUFFICIENT DATA (Keep Paper Trading)"
        verdict = "WAIT: You need at least 30 closed trades to prove statistical significance."
        color = "⚪"
    else:
        status = "VALID SAMPLE SIZE"
        if decay_ratio >= 0.8:
            verdict = "GREEN (GO): Live performance is holding up beautifully against the backtest. Cleared for real capital."
            color = "🟢"
        elif decay_ratio >= 0.6:
            verdict = "AMBER (CAUTION): Strategy is slightly degrading in current conditions. Consider 50% capital or wait."
            color = "🟠"
        else:
            verdict = "RED (STOP): Live performance has severely decoupled from the backtest. Do not trade real capital."
            color = "🔴"

    # 4. Format Report as Markdown
    report = f"""# FInsight Walk-Forward Confidence Report
Generated on: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

## Section 1: Statistical Validity Check
* **Total Paper Trades Closed:** {live_total_trades}
* **Minimum Required:** 30
* **Status:** {status}

## Section 2: The Variance Matrix (Expectation vs. Reality)
| Metric | Backtest (Baseline) | Live (Paper Trading) | Variance |
|---|---|---|---|
| **Win Rate** | {backtest_win_rate*100:.1f}% | {live_win_rate*100:.1f}% | {win_rate_variance*100:+.1f}% |
| **Average R:R** | N/A (Aggregated) | {live_avg_rr:.2f}R | N/A |

## Section 3: The Verdict
**System Health (Decay Ratio):** {decay_ratio:.2f}
*(A ratio of 1.0 means live performance exactly matches the backtest. <0.60 is critical).*

### Final Recommendation
**{color} {verdict}**
"""

    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"[SUCCESS] Confidence Report generated successfully at: {REPORT_PATH}")

if __name__ == "__main__":
    generate_report()
