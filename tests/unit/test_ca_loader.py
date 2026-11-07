"""Step 7: append-only load of corporate actions (synthetic database)."""
from __future__ import annotations

import sqlite3

import pandas as pd
import pytest

from scripts import f2_load_corporate_actions as ld

DDL = """
create table market_data_lake(id integer primary key autoincrement, symbol text not null, trade_date date not null,
  open_raw real, high_raw real, low_raw real, close_raw real, volume_raw bigint, unique(symbol, trade_date));
create table isin_symbol_map(isin text, symbol text, first_date text, last_date text, isin_class text, canonical_symbol text, applied_at text);
create table corporate_actions_log(id integer primary key autoincrement, symbol text not null, ex_date date not null,
  action_type text not null check(action_type in ('SPLIT','BONUS','DIVIDEND','RIGHTS','MERGER','DEMERGER','OTHER')),
  ratio_numerator real, ratio_denominator real, notes text, created_at timestamp default current_timestamp,
  source text, loaded_at text, evidence_tier text, evidence text, unique(symbol, ex_date, action_type));
"""
COLS = ["symbol", "isin", "ex_date", "action_type", "num", "den", "factor", "note", "subject", "factor_logged", "raw_ratio", "tier",
        "evidence", "evidence_basis", "lake_symbol", "no_data_reason"]


def _ev(rows):
    df = pd.DataFrame(rows, columns=COLS)
    df["stored_action_type"] = None
    return df


def _row(sym, ex, typ, num=None, den=None, tier="NOT_PRICE_MOVING", lake=None, subj="x", f=None):
    return (sym, None, ex, typ, num, den, f, subj, subj, f, None, tier, "ev", None, lake, None)


@pytest.fixture
def db(tmp_path):
    p = str(tmp_path / "t.db")
    c = sqlite3.connect(p)
    c.executescript(DDL)
    for sym in ("OLDNAME", "AAA", "BBB"):
        for d in ("2020-01-01", "2020-01-02", "2020-01-03"):
            c.execute("insert into market_data_lake(symbol,trade_date,close_raw) values (?,?,1)", (sym, d))
    c.commit()
    c.close()
    return p


def _build(db, rows, hold=()):
    con = sqlite3.connect(db)
    try:
        return ld.build_rows(con, _ev(rows), hold=set(hold))
    finally:
        con.close()


def test_symbol_is_the_lake_symbol_and_feed_symbol_goes_to_notes(db):
    rows = [_row("NEWNAME", "2020-01-03", "SPLIT", 1, 2, "STRONG", lake="OLDNAME", f=0.5)]
    out = _build(db, rows).rows
    assert list(out.symbol) == ["OLDNAME"] and "feed_symbol=NEWNAME" in out.notes.iloc[0]
    assert out.action_type.iloc[0] == "SPLIT" and out.ratio_numerator.iloc[0] == 1 and out.evidence_tier.iloc[0] == "STRONG"


def test_unsupported_price_event_is_stored_as_other_without_ratio(db):
    out = _build(db, [_row("AAA", "2020-01-03", "BONUS", 1, 2, "UNSUPPORTED", lake="AAA", f=0.667)]).rows
    r = out.iloc[0]
    assert r.action_type == "OTHER" and pd.isna(r.ratio_numerator) and r.evidence_tier == "UNSUPPORTED"
    assert "BONUS" in r.notes and "1" in r.notes


def test_colliding_other_rows_are_merged_and_logged_but_other_types_are_not(db):
    rows = [_row("AAA", "2020-01-03", "SPLIT", 1, 5, "UNSUPPORTED", lake="AAA", subj="split text", f=0.2),
            _row("AAA", "2020-01-03", "BONUS", 1, 1, "UNSUPPORTED", lake="AAA", subj="bonus text", f=0.5),
            _row("AAA", "2020-01-03", "OTHER", subj="unparsed text"),
            _row("BBB", "2020-01-03", "DIVIDEND", subj="div 1"),
            _row("BBB", "2020-01-03", "DIVIDEND", subj="div 2")]
    res = _build(db, rows)
    other = res.rows[res.rows.action_type == "OTHER"]
    assert len(other) == 1 and all(t in other.notes.iloc[0] for t in ("split text", "bonus text", "unparsed text"))
    assert other.evidence_tier.iloc[0] == "UNSUPPORTED"
    assert list(res.merged_log.symbol) == ["AAA"] and int(res.merged_log.n_rows.iloc[0]) == 3
    assert len(res.rows[res.rows.action_type == "DIVIDEND"]) == 1          # not merged: first kept
    assert len(res.dropped_duplicates) == 1 and res.dropped_duplicates.action_type.iloc[0] == "DIVIDEND"


def test_held_event_is_excluded_and_recorded(db):
    rows = [_row("AAA", "2020-01-03", "SPLIT", 1, 10, "STRONG", lake="AAA", f=0.1), _row("BBB", "2020-01-03", "SPLIT", 1, 2, "STRONG", lake="BBB", f=0.5)]
    res = _build(db, rows, hold=[("AAA", "2020-01-03")])
    assert list(res.rows.symbol) == ["BBB"] and list(res.held.symbol) == ["AAA"]


def test_events_without_rows_before_the_ex_date_are_listed(db):
    rows = [_row("AAA", "2020-01-01", "SPLIT", 1, 2, "STRONG", lake="AAA", f=0.5),      # no row before 2020-01-01
            _row("AAA", "2020-01-03", "SPLIT", 1, 2, "STRONG", lake="AAA", f=0.5),      # ok
            _row("GHOST", "2020-01-03", "DIVIDEND", lake=None)]                           # symbol not in the lake at all
    res = _build(db, rows)
    assert set(zip(res.no_prior_rows.symbol, res.no_prior_rows.ex_date)) == {("AAA", "2020-01-01"), ("GHOST", "2020-01-03")}


def test_load_is_append_only_and_rolls_back_on_a_count_mismatch(db):
    rows = [_row("AAA", "2020-01-03", "SPLIT", 1, 2, "STRONG", lake="AAA", f=0.5), _row("BBB", "2020-01-03", "DIVIDEND")]
    res = _build(db, rows)
    with pytest.raises(AssertionError):
        ld.load(db, res.rows, expect={"SPLIT": 5})
    c = sqlite3.connect(db)
    assert c.execute("select count(*) from corporate_actions_log").fetchone()[0] == 0
    c.close()
    rep = ld.load(db, res.rows, expect={"SPLIT": 1, "DIVIDEND": 1})
    assert rep["inserted"] == 2
    with pytest.raises(AssertionError):                         # second load of the same rows must not silently double or skip
        ld.load(db, res.rows)


def test_verified_list_stores_per_row_factors_so_same_date_pairs_multiply_to_the_combined_factor():
    import numpy as np, pandas as pd
    v = pd.read_csv("data/reference/verified_corporate_actions.csv")
    e = v[(v.symbol == "EASEMYTRIP") & (v.ex_date == "2022-11-21")]
    assert sorted(e.expected_factor) == [0.25, 0.5] and np.isclose(np.prod(e.expected_factor), 0.125)
