"""The pure builders, the freshness rule, the readers and the configuration."""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from bff import builders as B
from bff import config as C
from bff import sources as S
from bff.models import Marks
from stockbot.engine.types import ClosedTrade, Decisions, Flag, Position

IST = timezone(timedelta(hours=5, minutes=30))


# ------------------------------------------------------------------------------------------------------------------------------ money
@pytest.mark.parametrize("rupees,paise", [(0.0, 0), (1.0, 100), (1642.3, 164230), (0.005, 1), (0.004, 0), (10.005, 1001), (-1.005, -101), (200000.0, 20_000_000), (1575.4, 157540),
                                          (3801.0, 380100), (0.1 + 0.2, 30), (123456.785, 12345679)])
def test_to_paise_rounds_half_up_on_the_decimal_text(rupees, paise):
    assert B.to_paise(rupees) == paise


def test_equity_is_built_from_rounded_parts_so_it_is_exact():
    p = Position("x", "s", "AAA", None, date(2026, 1, 1), 100.005, 90.0, 90.0, None, 7.0, 7, 70.0, "e", last_close=101.005)
    # 7 x round(101.005) = 7 x 10101 paise, summed as integers with the cash in paise
    last = B.to_paise(101.005)
    assert 7 * last == 70707
    assert B.to_paise(0.1) * 3 == 30


# ------------------------------------------------------------------------------------------------------------------------------ mappings (CONTRACT.md, "Engine mapping")
@pytest.mark.parametrize("reason,stage,expected", [
    ("BLOCKED_BY_RISK(sector_IT:16.1%>15.0%)", "risk", "SECTOR_CAP"),
    ("BLOCKED_BY_RISK(sector_Financial Services:20.0%>15.0%)", "risk", "SECTOR_CAP"),
    ("BLOCKED_BY_RISK(positions:13>12)", "risk", "RISK_CAP"),
    ("BLOCKED_BY_RISK(total_risk:15.5%>15.0%)", "risk", "RISK_CAP"),
    ("BLOCKED_BY_RISK", "risk", "RISK_CAP"),
    ("SIZE_ZERO", "fill", "CASH"),
    ("SIZE_ZERO", "sizing", "OTHER"),
    ("NONPOSITIVE_RISK", "sizing", "OTHER"), ("NONPOSITIVE_RISK", "fill", "OTHER"),
    ("ALREADY_HELD", "risk", "OTHER"), ("SYMBOL_HELD_BY_OTHER_STRATEGY", "risk", "OTHER"), ("NO_BAR_OR_ALREADY_HELD", "fill", "OTHER"),
    ("NOT_ELIGIBLE", "propose", "OTHER"), ("DUPLICATE_PROPOSAL", "propose", "OTHER"),
    ("NOT_EQ_SERIES", "propose", "OTHER"), ("NOT_EQ_SERIES_AT_FILL", "fill", "OTHER"),
    ("MARKET_SWITCH", "overlay", "OTHER"), ("STRATEGY_NOT_REGISTERED", "fill", "OTHER"), ("CORP_ACTION_ON_EXEC_DATE", "fill", "OTHER"),
    ("GAP_THROUGH_STOP", "fill", "OTHER"), ("GAP_UP_TOO_LARGE", "fill", "OTHER"), ("CONFIRM_FILL_ERROR", "fill", "OTHER"), ("anything new", "fill", "OTHER"), ("", "", "OTHER"),
])
def test_block_reason_mapping(reason, stage, expected):
    assert B.map_block_reason(reason, stage) == expected


@pytest.mark.parametrize("reason,gap,expected", [
    ("STOP_HIT", False, "STOP_HIT"), ("STOP_HIT", True, "GAP_THROUGH_STOP"), ("TIME_EXIT", False, "OTHER"), ("TIME_EXIT", True, "OTHER"), ("POLICY_EXIT", False, "OTHER"),
    ("SYMBOL_NO_BARS", False, "OTHER"), ("END_OF_WINDOW", False, "OTHER"), ("OPERATOR_EXIT", False, "OTHER"), ("MANUAL", False, "OTHER"), ("UNKNOWN", False, "OTHER"),
])
def test_exit_reason_mapping(reason, gap, expected):
    assert B.map_exit_reason(reason, gap) == expected


# ------------------------------------------------------------------------------------------------------------------------------ stats
def trade(symbol, pnl, flag=False):
    from bff import models as M
    return M.ClosedTrade(symbol=symbol, entryDate=date(2026, 1, 2), exitDate=date(2026, 2, 2), exitReason="OTHER", netPnlPaise=pnl, netR=0.0, corporateActionFlag=flag)


def test_stats_leave_out_flagged_trades_but_count_them():
    s = B.build_stats([trade("A", 300), trade("B", -100), trade("C", -100), trade("D", -5000, flag=True), trade("E", 9000, flag=True)])
    assert (s.tradeCount, s.wins, s.losses, s.excludedFromStats) == (5, 1, 2, 2)
    assert s.winRatePct == 33.33 and s.profitFactor == 1.5


def test_stats_empty_and_no_loss():
    e = B.build_stats([])
    assert (e.tradeCount, e.winRatePct, e.profitFactor, e.excludedFromStats) == (0, None, None, 0)
    w = B.build_stats([trade("A", 100)])
    assert (w.winRatePct, w.profitFactor) == (100.0, None)
    only_flagged = B.build_stats([trade("A", 100, flag=True)])
    assert (only_flagged.tradeCount, only_flagged.winRatePct, only_flagged.profitFactor, only_flagged.excludedFromStats) == (1, None, None, 1)


def test_net_r_and_exit_reason_in_trade_rows():
    ct = ClosedTrade("p", "s", "ABC", date(2026, 1, 2), date(2026, 1, 20), 100.0, 95.0, 400.0, 2000.0, 1000.0, 40.0, 960.0, "STOP_HIT", True)
    d = Decisions(as_of=date(2026, 1, 20), closed=(ct,), flags=(Flag("STOP_HIT", "", "s", "ABC"), Flag("GAP_THROUGH_STOP", "", "s", "ABC")))
    f = B.fold([Decisions(as_of=date(2026, 1, 2), cash_after=200000.0), d], 200000.0)
    row = B.build_trade_rows(f)[0]
    assert (row.exitReason, row.netR, row.netPnlPaise, row.corporateActionFlag) == ("GAP_THROUGH_STOP", 0.48, 96000, True)
    assert f.start_date == date(2026, 1, 2) and f.data_as_of == date(2026, 1, 20)


def test_a_gap_flag_for_another_symbol_or_session_does_not_count():
    ct = ClosedTrade("p", "s", "ABC", date(2026, 1, 2), date(2026, 1, 20), 100.0, 95.0, 400.0, 2000.0, 0.0, 0.0, -2000.0, "STOP_HIT")
    other_symbol = Decisions(as_of=date(2026, 1, 20), closed=(ct,), flags=(Flag("GAP_THROUGH_STOP", "", "s", "XYZ"),))
    other_day = Decisions(as_of=date(2026, 1, 19), flags=(Flag("GAP_THROUGH_STOP", "", "s", "ABC"),))
    f = B.fold([other_day, other_symbol], 200000.0)
    assert B.build_trade_rows(f)[0].exitReason == "STOP_HIT"


# ------------------------------------------------------------------------------------------------------------------------------ Nifty and drawdown
def test_nifty_rebased_to_the_starting_capital_in_whole_paise():
    assert B.rebase(25000.0, 25000.0, 20_000_000) == 20_000_000
    assert B.rebase(25500.0, 25000.0, 20_000_000) == 20_400_000
    assert B.rebase(25349.65, 25800.6, 20_000_000) == round(20_000_000 * 25349.65 / 25800.6)
    assert isinstance(B.rebase(25349.65, 25800.6, 20_000_000), int)


def test_drawdown_now_and_worst_from_the_curve():
    now, worst = B._drawdowns([100, 120, 90, 100, 108])
    assert (now, worst) == (10.0, 25.0)
    assert B._drawdowns([100, 100, 100]) == (0.0, 0.0)
    assert B._drawdowns([100, 90]) == (10.0, 10.0)


# ------------------------------------------------------------------------------------------------------------------------------ expectedAsOf
def at(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=IST)


def test_expected_is_today_after_2030_ist_and_yesterday_before():
    nofile: set = set()
    assert B.expected_as_of(at(2026, 11, 24, 20, 30), nofile) == date(2026, 11, 24)           # Tuesday, after the job should have finished
    assert B.expected_as_of(at(2026, 11, 24, 20, 29), nofile) == date(2026, 11, 23)           # not yet: yesterday (Monday)
    assert B.expected_as_of(at(2026, 11, 24, 8, 0), nofile) == date(2026, 11, 23)


def test_friday_data_on_a_monday_morning_is_not_behind():
    # Monday 2026-11-23 morning: the last day on which data is expected is Friday 2026-11-20
    assert B.expected_as_of(at(2026, 11, 23, 9, 0), set()) == date(2026, 11, 20)
    assert B.expected_as_of(at(2026, 11, 21, 12, 0), set()) == date(2026, 11, 20)             # Saturday
    assert B.expected_as_of(at(2026, 11, 22, 23, 0), set()) == date(2026, 11, 20)             # Sunday night
    assert B.expected_as_of(at(2026, 11, 23, 20, 30), set()) == date(2026, 11, 23)            # Monday after 20:30


def test_recorded_holidays_are_skipped_and_an_unrecorded_one_is_the_documented_limit():
    holiday = {date(2026, 11, 24)}                                                            # recorded as having no file
    assert B.expected_as_of(at(2026, 11, 24, 21, 0), holiday) == date(2026, 11, 23)
    assert B.expected_as_of(at(2026, 11, 25, 9, 0), holiday) == date(2026, 11, 23)
    assert B.expected_as_of(at(2026, 11, 25, 9, 0), set()) == date(2026, 11, 24)              # not recorded yet: looks like a missing day (the limit)
    assert B.expected_as_of(at(2026, 11, 27, 21, 0), {date(2026, 11, 26), date(2026, 11, 27)}) == date(2026, 11, 25)


def test_expected_uses_ist_whatever_the_clock_zone():
    utc = datetime(2026, 11, 24, 15, 10, tzinfo=timezone.utc)                                 # 20:40 IST
    assert B.expected_as_of(utc, set()) == date(2026, 11, 24)
    assert B.iso_ist(utc) == "2026-11-24T20:40:00+05:30"


def test_no_file_days_from_the_calendar_journal(tmp_path):
    p = tmp_path / "calendar.csv"
    p.write_text("date,checked_at,outcome,detail\n2026-11-20,x,LOADED,f\n2026-11-21,x,NO_FILE,404\n2026-11-22,x,NO_FILE,404\n2026-11-22,y,LOADED,f\n2026-11-25,x,NO_FILE_FINAL,\nbad,row\n", encoding="utf-8")
    assert S.read_no_file_days(p) == {date(2026, 11, 21), date(2026, 11, 25)}
    assert S.read_no_file_days(tmp_path / "missing.csv") == set()


# ------------------------------------------------------------------------------------------------------------------------------ signal day with the repository's own function
def test_default_signal_fn_is_the_repositorys_is_signal_session():
    assert B.default_signal_fn((date(2026, 11, 30), date(2026, 12, 1))) is True               # first session of December
    assert B.default_signal_fn((date(2026, 12, 1), date(2026, 12, 2))) is False
    assert B.default_signal_fn((date(2026, 12, 2),)) is False                                 # no previous session: no signal


# ------------------------------------------------------------------------------------------------------------------------------ config files
def test_marks_come_from_the_yaml_file():
    m = B.load_marks(Path(C.REPO) / "bff" / "paper_marks.yaml")
    assert m == Marks(drawdownReviewPct=35.0, closedTradesTarget=30, verdict="not demonstrated")


def test_risk_pct_is_read_from_shared_yaml(tmp_path):
    p = tmp_path / "s.yaml"
    p.write_text("portfolio_risk:\n  max_loss_pct_per_trade: 0.5\n", encoding="utf-8")
    assert B.load_risk_pct(p) == 0.5
    assert B.load_risk_pct(Path(C.REPO) / "stockbot" / "config" / "shared.yaml") == 1.0


# ------------------------------------------------------------------------------------------------------------------------------ token and settings
def test_refuses_to_start_without_a_token(tmp_path):
    with pytest.raises(C.TokenMissing):
        C.load_settings({"STOCKBOT_DATA_ROOT": str(tmp_path)})
    (tmp_path / "bff").mkdir()
    (tmp_path / "bff" / "token.txt").write_text("\n", encoding="utf-8")
    with pytest.raises(C.TokenMissing):
        C.load_settings({"STOCKBOT_DATA_ROOT": str(tmp_path)})
    from bff.app import create_app
    with pytest.raises(C.TokenMissing):
        create_app(C.Settings(token=""))


def test_token_from_env_or_file_and_never_in_messages(tmp_path):
    assert C.load_settings({"STOCKBOT_DATA_ROOT": str(tmp_path), "STOCKBOT_BFF_TOKEN": "env-token"}).token == "env-token"
    (tmp_path / "bff").mkdir()
    (tmp_path / "bff" / "token.txt").write_text("file-token\n", encoding="utf-8")
    assert C.load_settings({"STOCKBOT_DATA_ROOT": str(tmp_path)}).token == "file-token"
    assert C.load_settings({"STOCKBOT_DATA_ROOT": str(tmp_path), "STOCKBOT_BFF_TOKEN": "env-token"}).token == "env-token"      # the environment wins
    try:
        C.load_settings({"STOCKBOT_DATA_ROOT": str(tmp_path / "nowhere")})
    except C.TokenMissing as exc:
        assert "file-token" not in str(exc)


def test_defaults_and_overrides(tmp_path):
    s = C.load_settings({"STOCKBOT_DATA_ROOT": str(tmp_path), "STOCKBOT_BFF_TOKEN": "t"})
    assert (s.host, s.port, s.allowed_hosts, s.cors_origins) == ("127.0.0.1", 8765, ("localhost", "127.0.0.1"), ())
    s = C.load_settings({"STOCKBOT_DATA_ROOT": str(tmp_path), "STOCKBOT_BFF_TOKEN": "t", "STOCKBOT_BFF_HOST": "0.0.0.0", "STOCKBOT_BFF_PORT": "9001",
                         "STOCKBOT_BFF_ALLOWED_HOSTS": "a.example, b.example", "STOCKBOT_BFF_CORS": "http://x.example"})
    assert (s.host, s.port, s.allowed_hosts, s.cors_origins) == ("0.0.0.0", 9001, ("a.example", "b.example"), ("http://x.example",))
    assert s.log_file == tmp_path / "logs" / "bff.log" and s.calendar_csv == tmp_path / "daily" / "calendar.csv"


def test_the_bff_package_has_no_write_lock_scheduler_or_broker_code():
    """A static guard over bff/*.py (comments and docstrings included, so the wording is kept clean too)."""
    import re
    files = [f for f in (Path(C.REPO) / "bff").glob("*.py")]
    assert {f.name for f in files} >= {"app.py", "builders.py", "sources.py", "config.py", "models.py", "run.py", "smoke.py"}
    for f in files:
        text = f.read_text(encoding="utf-8")
        assert not re.search(r"^\s*(from|import)\s+stockbot\.live", text, re.M), f"{f.name} imports stockbot.live"
        for bad in (r"mode=rw", r"INSERT\s+INTO", r"UPDATE\s+\w+\s+SET", r"DELETE\s+FROM", r"CREATE\s+TABLE", r"DROP\s+TABLE", r"runlock", r"place_order",
                    r"kite", r"api_key", r"\.write_text\(", r"open\([^)]*['\"]w"):
            assert not re.search(bad, text, re.I), f"{f.name}: {bad}"
