"""The JSON export of the data catalogue (docs/guides/data_catalogue.json, written by ``py scripts/gen_data_catalogue.py --json``).

It is what the data picture guide takes its numbers from, so it must be machine-made, dated, and read-only on the database. Tested on a tiny throw-away SQLite file.
"""
import json
import sqlite3

from stockbot.data_checks import data_catalogue as dc


def make_db(path):
    c = sqlite3.connect(path)
    c.executescript("""
    create table market_data_lake (id integer primary key, symbol text not null, trade_date date not null, close_raw real not null, volume_raw bigint not null, source text, unique(symbol, trade_date));
    create index idx_mdl_trade_date on market_data_lake(trade_date);
    create table corporate_actions_log (id integer primary key, symbol text not null, ex_date date not null, action_type text not null, evidence_tier text, source text);
    create table bhavcopy_fetch_log (trade_date date primary key, status text not null, n_rows integer);
    create table earnings_board_meeting (id integer primary key, query_symbol text, symbol text, bm_date text, is_results_meeting integer);
    create table earnings_symbol_map (lake_symbol text, query_symbol text, how text);
    create table earnings_api_raw (endpoint text, query_symbol text, row_count integer);
    create table asm_gsm_daily_snapshot (snapshot_date text, framework text, symbol text);
    create table asm_gsm_snapshot_log (run_at text, snapshot_date text, endpoint text, outcome text, detail text);
    """)
    rows = [("AAA", "2020-01-01", 10.0, 5, None), ("AAA", "2020-01-02", 11.0, 6, None), ("NIFTY50_INDEX", "2020-01-01", 12000.0, 0, "x"), ("NIFTY50_INDEX", "2020-01-02", 12100.0, 0, "x"), ("BBB", "2021-03-01", 5.0, 9, None)]
    c.executemany("insert into market_data_lake(symbol,trade_date,close_raw,volume_raw,source) values (?,?,?,?,?)", rows)
    c.executemany("insert into corporate_actions_log(symbol,ex_date,action_type,evidence_tier) values (?,?,?,?)",
                  [("AAA", "2020-02-01", "SPLIT", "STRONG"), ("AAA", "2020-03-01", "DIVIDEND", "NOT_PRICE_MOVING"), ("BBB", "2099-01-01", "BONUS", "WEAK")])
    c.execute("insert into bhavcopy_fetch_log values ('2020-01-01','OK',3)")
    c.commit()
    c.close()


def export(tmp_path):
    db = tmp_path / "t.db"
    make_db(db)
    from stockbot.data.lake import open_lake
    con = open_lake(db)
    try:
        return dc.export_json(con, db), db
    finally:
        con.close()


def test_the_export_has_tables_columns_indexes_sample_and_a_measurement_date(tmp_path):
    d, db = export(tmp_path)
    assert d["meta"]["measured_at"][:4].isdigit() and d["meta"]["db_size_bytes"] == db.stat().st_size
    t = d["tables"]["market_data_lake"]
    assert t["rows"] == 5 and t["first"] == "2020-01-01" and t["last"] == "2021-03-01" and t["symbols"] == 3
    assert [c["name"] for c in t["columns"]][:3] == ["id", "symbol", "trade_date"]
    assert t["columns"][1]["notnull"] is True and t["columns"][1]["type"] == "TEXT"
    assert any(i["name"] == "idx_mdl_trade_date" for i in t["indexes"]) and t["sample"]
    assert {o["name"] for o in d["objects"] if o["type"] == "table"} >= set(d["tables"])


def test_the_export_has_the_coverage_numbers_the_guide_charts_use(tmp_path):
    d, _ = export(tmp_path)
    cov = d["coverage"]
    by_year = {r["year"]: r for r in cov["lake_by_year"]}
    assert by_year["2020"] == {"year": "2020", "rows": 4, "sessions": 2, "equity_symbols": 1}
    assert cov["lake_last_date"] == "2021-03-01" and cov["nifty_first_date"] == "2020-01-01"
    assert {r["action_type"]: r["rows"] for r in cov["actions_by_type"]} == {"SPLIT": 1, "DIVIDEND": 1, "BONUS": 1}
    assert cov["actions_after_last_session"] == 1
    assert {(r["action_type"], r["evidence_tier"]) for r in cov["actions_by_type_tier"]} >= {("SPLIT", "STRONG")}


def test_the_export_is_json_and_does_not_write_the_database(tmp_path):
    db = tmp_path / "t.db"
    make_db(db)
    before = db.read_bytes()
    from stockbot.data.lake import open_lake
    con = open_lake(db)
    try:
        json.dumps(dc.export_json(con, db))
        with __import__("pytest").raises(sqlite3.OperationalError):
            con.execute("create table x (a)")
    finally:
        con.close()
    assert db.read_bytes() == before


def test_reference_file_counts_skip_comments_and_the_header(tmp_path):
    (tmp_path / "a.csv").write_text("# note\nsymbol,sector\nAAA,X\nBBB,Y\n", encoding="utf-8")
    r = dc.reference_files(tmp_path)
    assert r == [{"file": "a.csv", "columns": ["symbol", "sector"], "rows": 2}]
