"""AsOfView earnings reads (decision D5): intimation <= as_of enforced inside the view, dedupe on (symbol, bm_date), per-symbol coverage; and the shared
event-proximity mechanism in stockbot.universe.eligibility."""
import sqlite3
import sys
from datetime import date
from pathlib import Path

import pytest

from stockbot.data.ingestion.collect_earnings_history import DDL
from stockbot.data.asof import AsOfView
from stockbot.data.lake import open_lake
from stockbot.universe.eligibility import results_within
from tests.fixtures import mini_lake
from tests.fixtures.lakefile import _make

DS = mini_lake.sessions()
T = DS[250]


def add_meeting(con, qs, bm_date, intimation, results=1, purpose="Financial Results"):
    con.execute("insert into earnings_board_meeting (query_symbol, symbol, bm_date, purpose, intimation_ts, is_results_meeting, results_rule, row_hash) values (?,?,?,?,?,?,?,?)",
                (qs, qs, bm_date, purpose, intimation, results, "purpose", f"{qs}|{bm_date}|{intimation}|{results}"))


@pytest.fixture()
def lake(tmp_path):
    p = tmp_path / "lake.db"
    _make(p)
    con = sqlite3.connect(p)
    con.executescript(DDL)
    con.execute("insert into earnings_symbol_map values ('FIXCO','FIXCO','exact')")
    con.execute("insert into earnings_symbol_map values ('FIXCO','FIXCO-OLD','former')")
    con.execute("insert into earnings_api_raw values ('corporate-board-meetings','FIXCO','2026-11-01',200,5,x'00')")
    con.commit()
    yield p, con
    con.close()


def view(path, day):
    return AsOfView(open_lake(path), day)


def test_a_meeting_is_visible_only_from_its_intimation_date(lake):
    p, con = lake
    bm = (T + __import__("datetime").timedelta(days=20)).isoformat()                       # the meeting is in the future
    add_meeting(con, "FIXCO", bm, DS[247].isoformat() + " 18:30:00")                        # intimated 3 sessions before T
    add_meeting(con, "FIXCO", "2019-12-30", DS[252].isoformat() + " 09:00:00")              # intimated AFTER T
    con.commit()
    got = view(p, T).results_meetings("FIXCO")
    assert [m["bm_date"].isoformat() for m in got] == [bm]                                  # the upcoming meeting is known; the later-intimated one is not
    assert [m["bm_date"].isoformat() for m in view(p, DS[251]).results_meetings("FIXCO")] == [bm]
    assert len(view(p, DS[252]).results_meetings("FIXCO")) == 2                              # visible on its intimation day
    assert view(p, DS[246]).results_meetings("FIXCO") == []                                  # before any intimation: unknown


def test_changing_rows_intimated_after_the_as_of_date_changes_nothing(lake):
    p, con = lake
    add_meeting(con, "FIXCO", "2019-12-02", DS[240].isoformat() + " 10:00:00")
    con.commit()
    before = view(p, T).results_meetings("FIXCO")
    add_meeting(con, "FIXCO", "2019-12-09", DS[255].isoformat() + " 10:00:00")
    con.execute("update earnings_board_meeting set purpose='x' where intimation_ts > ?", (T.isoformat(),))
    con.commit()
    assert view(p, T).results_meetings("FIXCO") == before


def test_duplicate_meeting_dates_collapse_to_the_earliest_intimation(lake):
    p, con = lake
    add_meeting(con, "FIXCO", "2019-12-02", DS[240].isoformat() + " 10:00:00")
    add_meeting(con, "FIXCO-OLD", "2019-12-02", DS[238].isoformat() + " 10:00:00")          # the same meeting through the former symbol, announced earlier
    add_meeting(con, "FIXCO", "2019-12-02", DS[244].isoformat() + " 10:00:00")              # a re-intimation
    con.commit()
    (m,) = view(p, T).results_meetings("FIXCO")
    assert m["intimation_ts"] == DS[238].isoformat() + " 10:00:00"


def test_only_results_meetings_with_a_known_intimation_count(lake):
    p, con = lake
    add_meeting(con, "FIXCO", "2019-12-02", DS[240].isoformat() + " 10:00:00", results=0, purpose="Fund raising")
    add_meeting(con, "FIXCO", "2019-12-03", None)                                           # no intimation timestamp: not known
    con.commit()
    assert view(p, T).results_meetings("FIXCO") == []


def test_coverage_says_no_data_instead_of_no_event(lake):
    p, con = lake
    v = view(p, T)
    assert v.earnings_coverage("FIXCO") is True and v.results_meetings("FIXCO") == []        # has data, no meeting known
    assert v.earnings_coverage("NOSUCH") is False                                            # unmapped symbol
    con.execute("insert into earnings_symbol_map values ('EMPTYCO','EMPTYCO','exact')")
    con.execute("insert into earnings_api_raw values ('corporate-board-meetings','EMPTYCO','2026-11-01',200,0,x'00')")
    con.commit()
    assert view(p, T).earnings_coverage("EMPTYCO") is False                                  # mapped, but the API returned nothing


def test_a_lake_without_earnings_tables_has_no_coverage_and_no_meetings(tmp_path):
    p = tmp_path / "plain.db"
    _make(p)
    v = view(p, T)
    assert v.earnings_coverage("FIXCO") is False and v.results_meetings("FIXCO") == []


def test_results_within_is_none_without_coverage_and_respects_the_window(lake):
    p, con = lake
    assert results_within(view(p, T), "NOSUCH", 14) is None                                  # no data is not "no event"
    assert results_within(view(p, T), "FIXCO", 14) is False                                  # data, no meeting
    d14 = date.fromordinal(T.toordinal() + 14).isoformat()
    d15 = date.fromordinal(T.toordinal() + 15).isoformat()
    add_meeting(con, "FIXCO", d14, DS[240].isoformat() + " 10:00:00")
    add_meeting(con, "FIXCO", d15, DS[240].isoformat() + " 10:00:00")
    con.commit()
    assert results_within(view(p, T), "FIXCO", 14) is True
    assert results_within(view(p, T), "FIXCO", 13) is False                                  # window is inclusive of day 14, exclusive of 15
    add_meeting(con, "FIXCO", T.isoformat(), DS[200].isoformat() + " 10:00:00")
    con.commit()
    assert results_within(view(p, T), "FIXCO", 0) is True                                    # a meeting on the as-of day itself
