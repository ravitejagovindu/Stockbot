"""tests/unit/test_phase5_paper_tools.py — Unit tests for Phase 5 paper trading tools."""
from __future__ import annotations

import json
from datetime import date, timedelta
from unittest.mock import MagicMock, patch
import pandas as pd
import pytest

from stockbot.data_checks.preflight import assert_preflight_spot_check
from stockbot.live.paper_report import evaluate_paper_performance, load_backtest_baseline


def test_preflight_spot_check_passes():
    assert assert_preflight_spot_check() is True


def test_preflight_spot_check_fails_on_tampered_adjustment(monkeypatch):
    import stockbot.data_checks.preflight as pf
    # Mock get_adjusted_series to return wrong close
    def bad_adjusted_series(raw_df, actions, as_of_date):
        df = raw_df.copy()
        df["close_adj"] = [999.0] * len(df)
        return df

    monkeypatch.setattr(pf, "get_adjusted_series", bad_adjusted_series)
    with pytest.raises(RuntimeError, match="PREFLIGHT_SPOT_CHECK_FAILED"):
        assert_preflight_spot_check()


def test_load_backtest_baseline(tmp_path):
    audit_file = tmp_path / "audit.json"
    audit_data = {
        "metrics": {
            "window_1": {"expectancy_r": 0.40, "win_rate_pct": 55.0},
            "window_2": {"expectancy_r": 0.60, "win_rate_pct": 65.0},
        }
    }
    audit_file.write_text(json.dumps(audit_data))
    baseline = load_backtest_baseline(audit_file)
    assert abs(baseline["expectancy_r"] - 0.50) < 1e-6
    assert abs(baseline["win_rate_pct"] - 60.0) < 1e-6


def test_paper_report_d4_or_condition(tmp_path, monkeypatch):
    audit_file = tmp_path / "audit.json"
    audit_file.write_text(json.dumps({
        "metrics": {
            "window_1": {"expectancy_r": 0.50, "win_rate_pct": 60.0}
        }
    }))
    out_file = tmp_path / "PAPER_RESULT.json"

    cfg = {
        "runtime": {"paper_start_equity": 1000000.0},
        "paper_criteria": {
            "min_days": 90,
            "min_closed_trades": 60,
            "max_expectancy_gap_r": 0.25,
            "max_win_rate_gap_pts": 12.0,
            "min_profit_factor": 1.2,
            "max_drawdown_pct": 12.0,
            "max_skipped_ticket_rate": 0.40,
        },
    }

    # Case A: 100 days active, but only 10 trades -> D4 OR condition met for duration
    monkeypatch.setattr("stockbot.live.paper_report.read_authorized_info", lambda: {
        "authorized_at": (date.today() - timedelta(days=100)).isoformat()
    })

    # Mock trades to return 10 winning trades
    sample_trades = pd.DataFrame([
        {
            "position_id": i,
            "symbol": f"SYM{i}",
            "entry_date": date.today() - timedelta(days=90 - i),
            "exit_date": date.today() - timedelta(days=80 - i),
            "entry_price": 100.0,
            "stop": 95.0,
            "shares": 100,
            "pnl_gross": 1000.0,
            "costs": 50.0,
            "pnl_net": 950.0,
            "tax_est": 190.0,
            "days_held": 10,
        }
        for i in range(10)
    ])

    monkeypatch.setattr("stockbot.live.paper_report.trades_from_log", lambda s, mode: sample_trades)

    mock_s = MagicMock()
    # opened_cnt, skipped_cnt
    mock_s.execute.side_effect = [
        MagicMock(scalar=lambda: 10),
        MagicMock(scalar=lambda: 1),
    ]

    with patch("stockbot.live.paper_report.get_session") as mock_gs:
        mock_gs.return_value.__enter__.return_value = mock_s
        res = evaluate_paper_performance(cfg, audit_file=audit_file, output_file=out_file)

    assert res["checks"]["duration_or_trades"] is True
    assert res["metrics"]["days_count"] >= 90
    assert res["metrics"]["n_closed_trades"] == 10
    assert out_file.exists()

    # Case B: 30 days active, but 65 trades -> D4 OR condition met for trades
    monkeypatch.setattr("stockbot.live.paper_report.read_authorized_info", lambda: {
        "authorized_at": (date.today() - timedelta(days=30)).isoformat()
    })
    sample_65_trades = pd.DataFrame([
        {
            "position_id": i,
            "symbol": f"SYM{i}",
            "entry_date": date.today() - timedelta(days=20),
            "exit_date": date.today() - timedelta(days=10),
            "entry_price": 100.0,
            "stop": 95.0,
            "shares": 100,
            "pnl_gross": 500.0,
            "costs": 50.0,
            "pnl_net": 450.0,
            "tax_est": 90.0,
            "days_held": 10,
        }
        for i in range(65)
    ])
    monkeypatch.setattr("stockbot.live.paper_report.trades_from_log", lambda s, mode: sample_65_trades)

    mock_s2 = MagicMock()
    mock_s2.execute.side_effect = [
        MagicMock(scalar=lambda: 65),
        MagicMock(scalar=lambda: 5),
    ]
    with patch("stockbot.live.paper_report.get_session") as mock_gs2:
        mock_gs2.return_value.__enter__.return_value = mock_s2
        res2 = evaluate_paper_performance(cfg, audit_file=audit_file, output_file=out_file)

    assert res2["checks"]["duration_or_trades"] is True
    assert res2["metrics"]["n_closed_trades"] == 65
    assert res2["metrics"]["days_count"] < 90
