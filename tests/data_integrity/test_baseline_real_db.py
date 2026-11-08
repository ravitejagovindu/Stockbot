"""Real-database versions of the Simulator baseline tests (F10). Run only with STOCKBOT_DATA_TESTS=1 (fails loudly if the database is missing).

    set STOCKBOT_DATA_TESTS=1 && py -3 -m pytest tests/data_integrity/test_baseline_real_db.py -q
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pytest

DB = Path(os.environ.get("STOCKBOT_DB") or Path(__file__).resolve().parents[2] / "finsight.db")
RUN = os.environ.get("STOCKBOT_DATA_TESTS") == "1"
if RUN and not DB.exists():
    raise RuntimeError(f"STOCKBOT_DATA_TESTS=1 but the database {DB} does not exist")
pytestmark = pytest.mark.skipif(not RUN, reason="needs STOCKBOT_DATA_TESTS=1 and the real database")


from backtest.simulator import Simulator
from config import load_config
from data.db.connection import get_session
from engine_core.candidate_builder import build_candidate_dicts
from engine_core.entry_filters import apply_entry_filters


def test_real_db_simulator_and_funnel_agreement():
    """Verify that Simulator and candidate screening/filtering agree on candidate selection."""
    cfg = load_config()
    with get_session() as s:
        sim = Simulator(cfg, s, allow_live_db=True)
        d = date(2020, 1, 14)  # Signal date for ESCORTS entry on 2020-01-15

        # Screening through UniverseScreener
        all_syms = sim.screener._get_all_symbols(d)
        passed = [
            sym for sym in all_syms
            if sym not in ("NIFTY50_INDEX", "INDIA_VIX")
            and sim.screener.screen_single(sym, d, apply_event_gates=False).passed
        ]
        assert "ESCORTS" in passed, "ESCORTS must pass universe screening on 2020-01-14"

        # Candidate building & entry filter ranking
        cands = build_candidate_dicts(s, cfg, passed, d)
        filtered = apply_entry_filters(cands, cfg)
        filtered_syms = [c["symbol"] for c in filtered]
        assert "ESCORTS" in filtered_syms, "ESCORTS must qualify in entry filters on 2020-01-14"

        # Risk sizing & R:R qualification (DLF & BALKRISIND blocked by RR < 1.5; ESCORTS approved)
        setups = sim.sizer.compute_all(filtered, d, 1_000_000.0, [], s, is_bull_regime=True)
        approved = [st for st in setups if not st.blocked]
        assert len(approved) == 1, f"Expected exactly 1 approved trade ticket, got {len(approved)}"
        assert approved[0].symbol == "ESCORTS", "Approved trade ticket must be ESCORTS"
        assert approved[0].projected_rr >= 1.5, "ESCORTS projected R:R must clear >= 1.5"


@pytest.mark.slow
def test_real_db_active_simulator_mini_window_jan_feb_2020():
    """Actively execute Simulator over Jan-Feb 2020 and verify known trades reproduction.

    Re-baselined 2026-11-07 after the F2 lake swap (reviewer-approved after investigation): the old expected values
    (entry 2020-01-15 @ 643.40, 144 sh) came from a lake that spliced raw pre-2020 prices onto Yahoo dividend-adjusted
    2020+ prices (every 2020 close ~4.5% low against the raw 20-day high of 636.3).  On raw prices ESCORTS closes
    643.05 on 2020-01-09 (breakout, close > SMA50 633.6 > SMA200 606.6), so the fill is the 2020-01-10 open.
    """
    cfg = load_config()
    with get_session() as s:
        sim = Simulator(cfg, s, allow_live_db=True)
        res = sim.run(start=date(2020, 1, 1), end=date(2020, 2, 29), initial_equity=1_000_000.0)

    trades = res.trades
    assert len(trades) >= 1, f"Expected at least 1 trade in Jan-Feb 2020, got {len(trades)}"
    escorts_trades = trades[trades["symbol"] == "ESCORTS"]
    assert len(escorts_trades) == 1, "ESCORTS must be executed in Jan-Feb 2020"

    esc = escorts_trades.iloc[0]
    _as_date = lambda d: d.date() if hasattr(d, "date") and callable(getattr(d, "date")) else (date.fromisoformat(str(d)) if isinstance(d, str) else d)
    assert _as_date(esc["entry_date"]) == date(2020, 1, 10), f"ESCORTS entry date must be 2020-01-10, got {esc['entry_date']}"
    assert _as_date(esc["exit_date"]) == date(2020, 1, 31), f"ESCORTS exit date must be 2020-01-31, got {esc['exit_date']}"
    assert int(esc["shares"]) == 162, f"ESCORTS shares must be 162, got {esc['shares']}"
    assert round(float(esc["entry_price"]), 2) == 646.45, f"ESCORTS entry price mismatch: {esc['entry_price']}"
    assert esc["exit_reason"] == "STOP_HIT", f"ESCORTS exit reason must be STOP_HIT, got {esc['exit_reason']}"
    assert round(float(esc["pnl_net"])) == 22844, f"ESCORTS net PnL mismatch: {esc['pnl_net']}"
    assert round(float(esc["realized_r"]), 3) == 2.343, f"ESCORTS realized R mismatch: {esc['realized_r']}"

    print(f"\n[VERIFIED] Active Simulator Mini-Window Jan-Feb 2020:")
    print(f"  Executed Trades: {len(trades)}")
    print(f"  Trade 1: {esc['symbol']} | Entry: {_as_date(esc['entry_date'])} @ Rs. {float(esc['entry_price']):.2f} ({int(esc['shares'])} shares)")
    print(f"  Exit:    {_as_date(esc['exit_date'])} @ Rs. {float(esc['exit_price']):.2f} (reason: {esc['exit_reason']}, state: {esc['exit_state']})")
    print(f"  P&L:     Net Rs. {float(esc['pnl_net']):+,.0f} | Realized R: {float(esc['realized_r']):+.3f}R")
    print(f"  Result:  100% exact reproduction of known ESCORTS trade confirmed.")
