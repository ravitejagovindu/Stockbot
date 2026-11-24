"""HTTP layer: every endpoint for every scenario equals the SHAPE of its example, every reconciliation rule holds, and the error and security behaviour is as the contract says."""
from __future__ import annotations

import logging
import sqlite3
from datetime import date, datetime

import pytest
from conftest import AUTH, TOKEN, example, make_client
from world import SCENARIOS, append_session

from bff import models as M
from bff import sources as S
from stockbot.engine.types import Decisions

ENDPOINTS = ("today", "account", "positions", "trades")
MODEL = {"today": M.Today, "account": M.Account, "positions": M.Positions, "trades": M.Trades}


def kind(v):
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return "number"
    if isinstance(v, str):
        return "str"
    return type(v).__name__


def shape(a, b, path="$"):
    """Same keys and the same JSON types; a null on either side matches (nullable fields); lists compare their first element when both are non-empty."""
    if isinstance(a, dict) and isinstance(b, dict):
        assert set(a) == set(b), f"{path}: keys differ: {sorted(set(a) ^ set(b))}"
        for k in a:
            shape(a[k], b[k], f"{path}.{k}")
    elif isinstance(a, list) and isinstance(b, list):
        if a and b:
            shape(a[0], b[0], f"{path}[0]")
    elif a is None or b is None:
        return
    else:
        assert kind(a) == kind(b), f"{path}: {kind(a)} != {kind(b)}"


def get(client, ep):
    r = client.get(f"/v1/{ep}", headers=AUTH)
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------------------------------------------------------------------------ shape
@pytest.mark.parametrize("scenario", SCENARIOS)
@pytest.mark.parametrize("ep", ENDPOINTS)
def test_response_has_the_shape_of_its_example_and_validates(client_for, scenario, ep):
    body = get(client_for(scenario), ep)
    shape(body, example(f"{ep}_{scenario}.json"))
    MODEL[ep].model_validate(body)                                    # enums valid, no extra keys, +05:30 timestamp
    assert body["apiVersion"] == "1"


def test_health_has_the_shape_of_its_example(client_for):
    body = get(client_for("empty"), "health")
    shape(body, example("health_ok.json"))
    assert body["status"] == "ok" and body["latestSealedDate"] == "2026-11-23" and body["dataAsOf"] == body["latestSealedDate"]
    assert body["generatedAt"] == body["serverTime"]


def test_response_values_match_the_example_scenarios(client_for):
    """Not only the shape: the figures the fixtures were built to produce are the ones in the example files."""
    t = get(client_for("trades"), "trades")["stats"]
    e = example("trades_trades.json")["stats"]
    assert t == e
    a, ea = get(client_for("deep_drawdown"), "account"), example("account_deep_drawdown.json")
    assert a["summary"]["drawdownNowPct"] == ea["summary"]["drawdownNowPct"] == 31.0
    assert a["summary"]["drawdownWorstPct"] == ea["summary"]["drawdownWorstPct"] == 32.5
    assert a["summary"]["equityPaise"] == ea["summary"]["equityPaise"] == 17_940_000
    assert get(client_for("deep_drawdown"), "trades")["stats"] == example("trades_deep_drawdown.json")["stats"]
    p = get(client_for("positions"), "positions")
    assert p["cashPaise"] == example("positions_positions.json")["cashPaise"] == 3_898_000


# ------------------------------------------------------------------------------------------------------------------------------ reconciliation
@pytest.mark.parametrize("scenario", SCENARIOS)
def test_reconciliation_rules(client_for, scenario):
    c = client_for(scenario)
    acc, pos, tr = get(c, "account"), get(c, "positions"), get(c, "trades")
    s, curve = acc["summary"], acc["curve"]
    # equity = cash + positions (exact, integer paise), on both screens
    assert s["equityPaise"] == s["cashPaise"] + sum(p["shares"] * p["lastClosePaise"] for p in pos["positions"])
    assert s["cashPaise"] == pos["cashPaise"]
    for p in pos["positions"]:
        assert p["unrealisedPnlPaise"] == p["shares"] * (p["lastClosePaise"] - p["entryPricePaise"])
    # returns from equity and start; Nifty return from the rebased curve
    assert s["startingCapitalPaise"] == 20_000_000
    assert s["returnPct"] == pytest.approx((s["equityPaise"] / s["startingCapitalPaise"] - 1) * 100, abs=0.006)
    assert s["niftyReturnPct"] == pytest.approx((curve[-1]["niftyPaise"] / s["startingCapitalPaise"] - 1) * 100, abs=0.006)
    # curve: starts at the starting capital, ends at equity, one point per day, ascending, same dates for both lines
    assert curve[0]["date"] == s["startDate"] and curve[-1]["date"] == acc["dataAsOf"]
    assert curve[0]["accountPaise"] == curve[0]["niftyPaise"] == s["startingCapitalPaise"]
    assert curve[-1]["accountPaise"] == s["equityPaise"]
    assert [p["date"] for p in curve] == sorted({p["date"] for p in curve})
    # drawdowns from the daily curve
    peak, worst = 0, 0.0
    for p in curve:
        peak = max(peak, p["accountPaise"])
        worst = max(worst, (peak - p["accountPaise"]) / peak * 100)
    now = (peak - curve[-1]["accountPaise"]) / peak * 100
    assert s["drawdownNowPct"] == pytest.approx(now, abs=0.006)
    assert s["drawdownWorstPct"] == pytest.approx(max(worst, now), abs=0.006)
    # trades: stats from the unflagged trades; flagged ones are listed and counted
    trades, st = tr["trades"], tr["stats"]
    used = [t for t in trades if not t["corporateActionFlag"]]
    assert st["tradeCount"] == len(trades) == s["closedTrades"]
    assert st["excludedFromStats"] == len(trades) - len(used)
    assert st["wins"] == sum(t["netPnlPaise"] > 0 for t in used) and st["losses"] == sum(t["netPnlPaise"] < 0 for t in used)
    if used:
        assert st["winRatePct"] == pytest.approx(st["wins"] * 100 / len(used), abs=0.006)
    else:
        assert st["winRatePct"] is None
    gl = -sum(t["netPnlPaise"] for t in used if t["netPnlPaise"] < 0)
    if gl:
        assert st["profitFactor"] == pytest.approx(sum(t["netPnlPaise"] for t in used if t["netPnlPaise"] > 0) / gl, abs=0.006)
    else:
        assert st["profitFactor"] is None
    assert [t["exitDate"] for t in trades] == sorted((t["exitDate"] for t in trades), reverse=True)
    # without open positions equity is the starting capital plus every realised P&L, flagged trades included
    if not pos["positions"]:
        assert s["equityPaise"] == s["startingCapitalPaise"] + sum(t["netPnlPaise"] for t in trades)


def test_flagged_trade_is_listed_counted_and_left_out_of_the_stats(client_for):
    tr = get(client_for("trades"), "trades")
    assert [t["symbol"] for t in tr["trades"] if t["corporateActionFlag"]] == ["ASIANPAINT"]
    assert tr["stats"]["excludedFromStats"] == 1 and tr["stats"]["tradeCount"] == 12 and tr["stats"]["wins"] == 5 and tr["stats"]["losses"] == 6
    assert get(client_for("trades"), "account")["summary"]["closedTrades"] == 12


def test_position_held_by_hand_is_flagged(client_for):
    pos = get(client_for("positions"), "positions")["positions"]
    assert [p["symbol"] for p in pos if p["corporateActionFlag"]] == ["SBIN"]


def test_gap_through_stop_comes_from_the_exit_session_flag(client_for):
    by = {t["symbol"]: t["exitReason"] for t in get(client_for("trades"), "trades")["trades"]}
    assert by["HCLTECH"] == "GAP_THROUGH_STOP" and by["ONGC"] == "STOP_HIT" and by["WIPRO"] == "OTHER"


def test_today_signal_day_and_blocked_reasons(client_for):
    t = get(client_for("signal_day"), "today")
    assert t["isSignalDay"] is True and len(t["tickets"]) == 3 and len(t["blocked"]) == 12
    assert {b["reason"] for b in t["blocked"]} == {"SECTOR_CAP"}
    for k in t["tickets"]:
        assert k["riskPaise"] == k["shares"] * (k["entryReferencePaise"] - k["stopPaise"])
    assert {k["symbol"]: k["sector"] for k in t["tickets"]} == {"TCS": "IT", "HDFCBANK": "Financials", "ITC": "FMCG"}


def test_today_pending_sell_in_plain_words(client_for):
    t = get(client_for("positions"), "today")
    assert t["isSignalDay"] is False and t["tickets"] == []
    assert t["pendingFills"] == [{"symbol": "MARUTI", "side": "SELL", "shares": 3, "note": "Time exit queued at the close"}]
    assert t["nextSignalRule"] == "first trading day of next month"
    assert t["riskPerTradePct"] == 1.0


def test_marks_come_from_the_marks_file(client_for):
    m = get(client_for("empty"), "account")["marks"]
    assert m == {"drawdownReviewPct": 35.0, "closedTradesTarget": 30, "verdict": "not demonstrated"}


def test_empty_is_the_real_state_shape(client_for):
    c = client_for("empty")
    a = get(c, "account")
    assert a["summary"]["equityPaise"] == a["summary"]["cashPaise"] == a["summary"]["startingCapitalPaise"] == 20_000_000
    assert get(c, "positions")["positions"] == [] and get(c, "trades")["trades"] == [] and get(c, "today")["tickets"] == []


# ------------------------------------------------------------------------------------------------------------------------------ freshness
def test_fresh_data_is_not_behind_and_stale_data_is(client_for):
    fresh = get(client_for("positions"), "account")
    assert fresh["dataAsOf"] == fresh["expectedAsOf"] == "2026-12-22"
    stale = get(client_for("stale"), "account")
    assert stale["dataAsOf"] == "2026-12-18" and stale["expectedAsOf"] == "2026-12-22"
    assert datetime.fromisoformat(stale["generatedAt"]).utcoffset().total_seconds() == 5.5 * 3600


# ------------------------------------------------------------------------------------------------------------------------------ errors and security
@pytest.mark.parametrize("ep", ("health",) + ENDPOINTS)
@pytest.mark.parametrize("headers", ({}, {"X-Paper-Token": "wrong"}, {"X-Paper-Token": ""}, {"X-Paper-Token": TOKEN + "x"}))
def test_wrong_or_missing_token_is_401_with_the_error_body(client_for, ep, headers):
    r = client_for("empty").get(f"/v1/{ep}", headers=headers)
    assert r.status_code == 401
    M.ErrorResponse.model_validate(r.json())
    assert r.json()["error"]["code"] == "UNAUTHORIZED" and r.json()["apiVersion"] == "1"


def test_unknown_routes_are_404_with_the_error_body(client_for):
    c = client_for("empty")
    for path in ("/", "/v1", "/v1/orders", "/v2/today", "/docs", "/openapi.json"):
        r = c.get(path, headers=AUTH)
        assert r.status_code == 404, path
        M.ErrorResponse.model_validate(r.json())


@pytest.mark.parametrize("method", ("post", "put", "delete", "patch"))
def test_no_endpoint_accepts_a_write(client_for, method):
    c = client_for("empty")
    for ep in ("health",) + ENDPOINTS:
        r = getattr(c, method)(f"/v1/{ep}", headers=AUTH)
        assert r.status_code == 405
        M.ErrorResponse.model_validate(r.json())


def test_state_missing_is_503_not_ready(tmp_path, worlds):
    from world import build_world
    w = build_world(tmp_path, "empty")
    w.settings.state_db.unlink()
    c = make_client(w)
    for ep in ENDPOINTS:
        r = c.get(f"/v1/{ep}", headers=AUTH)
        assert r.status_code == 503 and r.json() == {"apiVersion": "1", "error": {"code": "NOT_READY", "message": "Today's data is not ready yet."}}
    h = c.get("/v1/health", headers=AUTH)
    assert h.status_code == 200 and h.json()["status"] == "not_ready"


def test_state_without_a_processed_session_is_503(tmp_path):
    from world import build_world, write_state
    w = build_world(tmp_path, "empty")
    w.settings.state_db.unlink()
    write_state(w.settings.state_db, [])
    assert make_client(w).get("/v1/account", headers=AUTH).status_code == 503


def test_locked_lake_is_503_not_a_partial_result(tmp_path):
    from world import build_world
    w = build_world(tmp_path, "positions")
    holder = sqlite3.connect(w.settings.lake, timeout=0.1)
    holder.execute("BEGIN EXCLUSIVE")
    try:
        c = make_client(w)
        for ep in ENDPOINTS:
            r = c.get(f"/v1/{ep}", headers=AUTH)
            assert r.status_code == 503 and r.json()["error"]["code"] == "NOT_READY", ep
    finally:
        holder.rollback()
        holder.close()
    assert make_client(w).get("/v1/account", headers=AUTH).status_code == 200        # and it recovers when the lock is gone


def test_lake_missing_a_nifty_day_is_503(tmp_path):
    from world import build_world
    w = build_world(tmp_path, "empty")
    con = sqlite3.connect(w.settings.lake)
    con.execute("delete from market_data_lake where symbol='NIFTY50_INDEX' and trade_date='2026-11-16'")
    con.commit()
    con.close()
    assert make_client(w).get("/v1/account", headers=AUTH).status_code == 503


def test_unexpected_error_is_500_with_the_error_body(tmp_path, monkeypatch):
    from world import build_world
    w = build_world(tmp_path, "empty")
    c = make_client(w)
    monkeypatch.setattr(S, "read_state", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom with secret " + TOKEN)))
    r = c.get("/v1/account", headers=AUTH)
    assert r.status_code == 500 and r.json()["error"]["code"] == "SERVER_ERROR"
    assert "boom" not in r.text and TOKEN not in r.text


def test_wrong_host_header_is_refused(client_for):
    r = client_for("empty").get("/v1/health", headers={**AUTH, "Host": "evil.example"})
    assert r.status_code == 400


def test_no_cors_headers_by_default(client_for):
    r = client_for("empty").get("/v1/health", headers={**AUTH, "Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in {k.lower() for k in r.headers}


def test_cors_only_for_listed_origins(worlds):
    from dataclasses import replace
    w = worlds["empty"]
    c = make_client(type(w)(**{**w.__dict__, "settings": replace(w.settings, cors_origins=("http://ok.example",))}))
    ok = c.get("/v1/health", headers={**AUTH, "Origin": "http://ok.example"})
    bad = c.get("/v1/health", headers={**AUTH, "Origin": "http://evil.example"})
    assert ok.headers.get("access-control-allow-origin") == "http://ok.example"
    assert "access-control-allow-origin" not in bad.headers


# ------------------------------------------------------------------------------------------------------------------------------ read-only proof and the log
def test_connections_are_read_only(worlds):
    w = worlds["positions"]
    for path in (w.settings.state_db, w.settings.lake):
        con = S.ro_connect(path)
        for sql in ("create table x (a)", "insert into meta values ('k','v')" if path == w.settings.state_db else "delete from market_data_lake",
                    "drop table " + ("journal" if path == w.settings.state_db else "market_data_lake")):
            with pytest.raises(sqlite3.OperationalError):
                con.execute(sql)
        assert con.execute("pragma query_only").fetchone()[0] == 1
        con.close()


def test_serving_requests_changes_no_file(tmp_path):
    from world import build_world
    w = build_world(tmp_path, "positions")
    watched = [w.settings.state_db, w.settings.lake, w.settings.tickets_dir, w.settings.state_db.parent, w.settings.lake.parent]

    def snap():
        out = {}
        for p in watched:
            if p.is_dir():
                out[str(p)] = sorted((q.name, q.stat().st_mtime_ns, q.stat().st_size) for q in p.iterdir())
            else:
                out[str(p)] = (p.stat().st_mtime_ns, p.stat().st_size)
        return out

    before = snap()
    c = make_client(w)
    for ep in ("health",) + ENDPOINTS:
        c.get(f"/v1/{ep}", headers=AUTH)
    assert snap() == before


def test_the_token_is_never_in_the_log_or_a_repr(tmp_path, worlds):
    from bff.app import setup_access_log
    from bff.app import log as access
    logfile = tmp_path / "logs" / "bff.log"
    setup_access_log(logfile)
    try:
        c = make_client(worlds["empty"])
        for headers in (AUTH, {"X-Paper-Token": "a-wrong-token-value"}, {}):
            for ep in ("health", "account"):
                c.get(f"/v1/{ep}?x={TOKEN}", headers=headers)
        for h in access.handlers:
            h.flush()
        text = logfile.read_text(encoding="utf-8")
    finally:
        for h in list(access.handlers):
            h.close()
            access.removeHandler(h)
    assert "GET /v1/account 200" in text and "401" in text
    assert TOKEN not in text and "a-wrong-token-value" not in text and "?" not in text
    assert TOKEN not in repr(worlds["empty"].settings)
    logging.getLogger("bff.access").handlers.clear()


# ------------------------------------------------------------------------------------------------------------------------------ caching
def test_responses_are_cached_until_the_state_file_changes(tmp_path, monkeypatch):
    from world import build_world
    from stockbot.engine.types import Decisions as D
    w = build_world(tmp_path, "empty")
    calls = {"n": 0}
    real = S.read_state

    def counting(*a, **k):
        calls["n"] += 1
        return real(*a, **k)

    monkeypatch.setattr(S, "read_state", counting)
    c = make_client(w)
    first = get(c, "account")
    get(c, "account"); get(c, "account")
    assert calls["n"] == 1                                                        # cached
    append_session(w.settings.state_db, D(as_of=date(2026, 11, 24), cash_after=200000.0))
    con = sqlite3.connect(w.settings.lake)
    con.execute("insert into market_data_lake (symbol, trade_date, close_raw) values ('NIFTY50_INDEX','2026-11-24',25100.0)")
    con.execute("update _guard_seal set sealed_through='2026-11-24'")
    con.commit(); con.close()
    second = get(c, "account")
    assert calls["n"] == 2                                                        # the changed key rebuilt it
    assert first["dataAsOf"] == "2026-11-23" and second["dataAsOf"] == "2026-11-24"


def test_envelope_times_are_fresh_on_a_cache_hit(tmp_path):
    from world import build_world
    w = build_world(tmp_path, "empty")
    clock = {"now": w.now}
    from bff.app import create_app
    from fastapi.testclient import TestClient
    from world import sector_stub, signal_stub
    c = TestClient(create_app(w.settings, now_fn=lambda: clock["now"], signal_fn=signal_stub, sector_for=sector_stub), base_url="http://testserver")
    a = get(c, "today")
    clock["now"] = w.now.replace(hour=22, minute=5)
    b = get(c, "today")
    assert a["generatedAt"] != b["generatedAt"] and b["generatedAt"].startswith("2026-11-23T22:05")
