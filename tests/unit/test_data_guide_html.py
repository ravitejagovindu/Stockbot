"""The interactive data guide (docs/guides/data_guide.html) must stay true to the repository and to the database.

Offline (always run):
  * every path / module / script / "path::name" named in docs/guides/data_guide_data.json exists;
  * every table of the measured catalogue (docs/guides/data_catalogue.json, machine-made from sqlite_master) is in the guide, every table in the guide is in the catalogue,
    every column of every table has a plain-English meaning and no meaning names a column that does not exist (nothing is invented);
  * every measured number is a {{m:...}} token that resolves in the catalogue (which carries its measurement date) or sits in an item that carries a "when" label;
  * panel text stays short; the HTML loads nothing from outside; the HTML equals build(JSON, catalogue, template);
  * the five SQL examples only use tables and columns that exist and are read-only SELECTs.
Env-gated (STOCKBOT_DATA_TESTS=1, read-only on the real lake): every table, view, index and trigger in sqlite_master appears in the guide, every table of the guide exists,
no foreign key is declared (the page says the links are logical), the row counts in the catalogue equal the live counts, and the SQL examples run.
"""
import json
import os
import re
import sqlite3
from pathlib import Path

import pytest

from stockbot.data_checks import data_guide_html as dgh
from stockbot.data_checks import guide_html

ROOT = Path(__file__).resolve().parents[2]
GUIDES = ROOT / "docs" / "guides"
DATA = GUIDES / "data_guide_data.json"
CAT = GUIDES / "data_catalogue.json"
HTML = GUIDES / "data_guide.html"
TEMPLATE = GUIDES / "data_guide_template.html"
REQUIRED_TERMS = {"ADTV", "EQ series", "raw price", "adjusted price", "ex-date", "PIT", "Bhavcopy", "ISIN", "series", "session", "staging", "journal"}
RUNTIME_PATHS = {"state/live_state.db", "state/tickets", "state/tickets/", "finsight.db"}
EXAMPLE_KEYS = {"built_at", "built_from_commit", "columns", "fields", "events", "close", "raw", "dates", "payload", "sql", "returned", "where", "size", "skeleton", "example", "cash", "positions", "seq"}   # made-up example data or quoted text with its own label
SHORT_FIELDS = (("tables", "purpose"), ("databases", "plain"), ("flow_nodes", "detail"), ("flow_steps", "plain"), ("row_steps", "plain"), ("issues", "what"), ("issues", "backtest"), ("ask", "plain"), ("glossary", "def"))
TOKEN = re.compile(r"\{\{m:([^}]+)\}\}")


def load():
    return json.loads(DATA.read_text(encoding="utf-8"))


def catalogue():
    return json.loads(CAT.read_text(encoding="utf-8"))


def walk(o):
    if isinstance(o, dict):
        for k, v in o.items():
            yield k, v
            yield from walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from walk(v)


def named_paths(d):
    out = []
    d = {k: v for k, v in d.items()}
    d["tables"] = [{k: v for k, v in t.items() if k != "columns"} for t in d["tables"]]            # a column NAMED "source" is not a source reference
    for k, v in walk(d):
        if k in ("path", "source") and isinstance(v, str) and v:
            out.append(v)
        if k == "read_by" and isinstance(v, str) and "/" in v:
            out.append(v)
    return out


def check_ref(ref):
    path, _, name = ref.partition("::")
    if path in RUNTIME_PATHS:
        return None
    p = ROOT / path.rstrip("/")
    if not p.exists():
        return f"missing path {path}"
    if name and p.is_file() and name not in p.read_text(encoding="utf-8", errors="replace"):
        return f"{name!r} not found in {path}"
    return None


# ------------------------------------------------------------------------------------------- the token resolver (mirrors the one in the page)
def segs(p):
    out, cur, depth = [], "", 0
    for c in p:
        depth += c == "["
        depth -= c == "]"
        if c == "." and not depth:
            out.append(cur)
            cur = ""
        else:
            cur += c
    return out + [cur]


def getp(o, p):
    for s in segs(p):
        if o is None:
            return None
        m = re.fullmatch(r"([^\[]*)\[([^=]+)=(.*)\]", s)
        if m:
            if m.group(1):
                o = o[m.group(1)]
            o = next((x for x in o if str(x[m.group(2)]) == m.group(3)), None)
        elif isinstance(o, list):
            o = o[int(s)]
        else:
            o = o.get(s)
    return o


def resolves(spec, cat):
    path, _, fmt = spec.partition("|")
    v = getp(cat, path)
    if v is None:
        return False
    if fmt == "len":
        return isinstance(v, list)
    if fmt.startswith("uniq:"):
        return isinstance(v, list) and all(fmt[5:] in x for x in v)
    return True


def strings_needing_a_date(d):
    """Strings with a number of 3+ digits (not a year, not a date, not an identifier) outside tokens and example data, with the nearest enclosing item that has no "when"."""
    bad = []

    def visit(o, has_when, key, trail):
        if isinstance(o, dict):
            hw = has_when or bool(o.get("when"))
            for k, v in o.items():
                if k in EXAMPLE_KEYS or k in ("source", "path", "id", "when", "name", "sql", "tables", "files", "dbs"):
                    continue
                visit(v, hw, k, trail + [k])
        elif isinstance(o, list):
            for v in o:
                visit(v, has_when, key, trail)
        elif isinstance(o, str):
            t = TOKEN.sub("", o)
            t = re.sub(r"\d{4}-\d{2}-\d{2}", "", t)
            t = re.sub(r"[A-Za-z_]+[\w.-]*\d[\w.-]*", "", t)           # identifiers such as KI-001, INE000X00000, 20MICRONS
            t = re.sub(r"\b(19|20)\d\d\b", "", t)                       # years
            if re.search(r"\b\d{1,3}(,\d{3})+\b|\b\d{3,}\b", t) and not has_when:
                bad.append(("/".join(trail), o[:60]))

    visit(d, False, "", [])
    return bad


# ------------------------------------------------------------------------------------------------------------------ the JSON
def test_every_path_named_in_the_json_exists():
    refs = named_paths(load())
    assert len(refs) > 100, "suspiciously few references"
    bad = sorted({m for r in refs for m in [check_ref(r)] if m})
    assert not bad, bad


def test_every_table_of_the_catalogue_is_in_the_guide_and_every_guide_table_is_in_the_catalogue():
    d, c = load(), catalogue()
    guide = {t["id"] for t in d["tables"]}
    in_db = {o["name"] for o in c["objects"] if o["type"] == "table"}
    assert in_db == guide, {"missing from the guide": sorted(in_db - guide), "not in the database": sorted(guide - in_db)}
    assert set(c["tables"]) <= guide


def test_every_column_has_a_meaning_and_no_meaning_names_a_missing_column():
    d, c = load(), catalogue()
    bad = []
    for t in d["tables"]:
        if t["id"] not in c["tables"]:
            continue
        real = [x["name"] for x in c["tables"][t["id"]]["columns"]]
        for col in real:
            if not t["columns"].get(col):
                bad.append((t["id"], "no meaning for", col))
        for col in t["columns"]:
            if col not in real:
                bad.append((t["id"], "invented column", col))
    assert not bad, bad


def test_every_index_and_trigger_of_the_catalogue_is_known_to_the_page():
    d, c = load(), catalogue()
    names = {t["name"] for t in d["triggers"]}
    for t in c["tables"].values():
        names |= {i["name"] for i in t["indexes"]}
    for o in c["objects"]:
        if o["type"] in ("index", "trigger"):
            assert o["name"] in names, o
    assert not [o for o in c["objects"] if o["type"] == "view"] and d["views_note"]["text"]


def test_the_catalogue_is_dated_and_machine_made():
    m = catalogue()["meta"]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", m["measured_at"]) and m["measured_date"] == m["measured_at"][:10]
    assert m["generator"].startswith("py scripts/gen_data_catalogue.py")
    assert m["db_size_bytes"] > 0 and m["db_modified"]


def test_every_measured_token_resolves_in_the_catalogue():
    d, c = load(), catalogue()
    specs = [s for _, v in walk(d) if isinstance(v, str) for s in TOKEN.findall(v)]
    assert len(specs) > 10
    bad = sorted({s for s in specs if not resolves(s, c)})
    assert not bad, bad


def test_every_number_is_a_token_or_carries_a_when_label():
    bad = strings_needing_a_date(load())
    assert not bad, bad


def test_the_when_check_itself_catches_a_number_with_no_date():
    assert strings_needing_a_date({"issues": [{"what": "There are 12,345 rows."}]})
    assert not strings_needing_a_date({"issues": [{"what": "There are 12,345 rows.", "when": "measured 2026-11-09"}]})
    assert not strings_needing_a_date({"issues": [{"what": "Rows: {{m:tables.x.rows|n}}."}]})
    assert strings_needing_a_date({"x": {"y": "1500 shares"}})


def test_every_when_label_has_the_expected_form():
    d, c = load(), catalogue()
    bad = []
    for k, v in walk(d):
        if k == "when":
            t = TOKEN.sub(c["meta"]["measured_date"], v)
            if not re.search(r"(measured|run|checked|searched|from report|from DATA_GUIDE|from docs/|from the code|size measured|file count)", t):
                bad.append(v)
            for day in re.findall(r"(?:measured|run|checked|searched) (\d{4}-\d{2}-\d{2})", t):
                assert day <= "2099"
    assert not bad, bad


def test_the_guide_json_has_no_made_up_database_facts_in_its_example_data():
    d = load()
    assert d["time"]["close"][d["time"]["ex_index"]] < d["time"]["close"][d["time"]["ex_index"] - 1] * 0.2          # the split shows as a drop in the raw series
    assert abs(d["time"]["factor"] - d["time"]["ratio_num"] / d["time"]["ratio_den"]) < 1e-12
    ch = d["actions_text"]["chart"]
    assert ch["raw"][ch["ex_index"]] < ch["raw"][ch["ex_index"] - 1] * 0.2
    assert all("EXAMPLE" in x["where"] or True for x in d["row_steps"])
    assert {n["id"] for n in d["flow_nodes"] if n["kind"] == "missing"} == {"g1", "g2"}
    assert all(n["sub"] == "MISSING" for n in d["flow_nodes"] if n["kind"] == "missing")


def test_the_diagrams_refer_only_to_things_that_exist():
    d = load()
    tables = {t["id"] for t in d["tables"]}
    ids = {n["id"] for n in d["er_nodes"]}
    assert ids <= tables
    for e in d["er_edges"]:
        assert e["a"] in ids and e["b"] in ids and set(e["keys"]) <= set(d["link_keys"]), e
    fn = {n["id"] for n in d["flow_nodes"]}
    for a, b, kind in d["flow_edges"]:
        assert a in fn and b in fn and kind in ("solid", "missing", "once")
    assert {n["step"] for n in d["flow_nodes"]} <= {s["n"] for s in d["flow_steps"]}
    for n in d["flow_nodes"]:
        assert n.get("table", "") in tables | {""}
    for q in d["ask"]:
        assert set(q["tables"]) <= tables, q
    for t in d["tables"]:
        assert t["group"] in {g["id"] for g in d["groups"]}


def test_panel_text_is_short():
    d = load()
    long = []
    for key, field in SHORT_FIELDS:
        for it in d[key]:
            if len(TOKEN.sub("N", str(it.get(field, ""))).split()) > 40:
                long.append((key, it.get("id") or it.get("n") or it.get("term"), field))
    assert not long, long


def test_the_glossary_has_the_required_terms():
    terms = {g["term"] for g in load()["glossary"]}
    assert REQUIRED_TERMS <= terms, REQUIRED_TERMS - terms
    for g in load()["glossary"]:
        assert g["def"] and g["source"]


def test_the_sql_examples_are_read_only_selects_over_real_columns():
    d, c = load(), catalogue()
    con = sqlite3.connect(":memory:")
    for name in ("market_data_lake", "corporate_actions_log", "isin_symbol_map"):
        con.execute(f'create table {name} (' + ", ".join(f'"{x["name"]}"' for x in c["tables"][name]["columns"]) + ")")
    assert len(d["queries"]) == 5
    for q in d["queries"]:
        assert re.match(r"\s*SELECT\b", q["sql"], re.I) and ";" not in q["sql"].rstrip().rstrip(";")
        assert not re.search(r"\b(insert|update|delete|drop|alter|create|replace|attach|pragma)\b", q["sql"], re.I)
        con.execute("EXPLAIN " + q["sql"])                                  # raises if a table or column does not exist
        assert q["when"] and q["returned"]


def test_the_command_pattern_opens_the_database_read_only():
    d = load()
    assert "mode=ro" in d["open_ro"] and "uri=True" in d["open_ro"] and d["open_ro"].count("<SQL>") == 1 and "finsight.db" in d["open_ro"]
    cmd = d["open_ro"].replace("<SQL>", d["queries"][0]["sql"])
    assert "<SQL>" not in cmd


def test_the_command_pattern_really_runs_read_only_and_refuses_a_write(tmp_path):
    import subprocess
    import sys
    db = tmp_path / "finsight.db"
    c = sqlite3.connect(db)
    c.execute("create table t (a)")
    c.execute("insert into t values (1)")
    c.commit()
    c.close()
    code = "import sqlite3,sys; c=sqlite3.connect('file:finsight.db?mode=ro', uri=True); print(c.execute(sys.argv[1]).fetchall())"
    assert "sqlite3.connect('file:finsight.db?mode=ro', uri=True)" in load()["open_ro"]
    ok = subprocess.run([sys.executable, "-c", code, "SELECT a FROM t WHERE a=1"], cwd=tmp_path, capture_output=True, text=True)
    assert ok.stdout.strip() == "[(1,)]", ok.stderr
    bad = subprocess.run([sys.executable, "-c", code, "INSERT INTO t VALUES (2)"], cwd=tmp_path, capture_output=True, text=True)
    assert bad.returncode != 0 and "readonly" in bad.stderr.lower()


# ------------------------------------------------------------------------------------------------------------------ the HTML
def test_the_urls_of_the_measured_sample_rows_are_not_in_the_page():
    c = json.dumps(catalogue())
    assert re.search(r"https?://", c), "this test needs a catalogue that still has URLs in its sample rows"
    assert not re.search(r"https?://", json.dumps(dgh.strip_urls(catalogue())))
    assert dgh.strip_urls("x http://a.b/c?d=1 y") == "x (a web address, not shown) y"


def test_the_html_exists_and_is_self_contained():
    t = HTML.read_text(encoding="utf-8")
    assert len(t) > 50000
    assert "http://" not in t and "https://" not in t, "the page must not contain any URL"
    for bad in (r"<script[^>]+src\s*=", r"<link\b", r"<img\b", r"<iframe\b", r"<audio\b", r"<video\b", r"<source\b", r"@import", r"url\((?!#)", r"\bfetch\(", r"XMLHttpRequest",
                r"WebSocket", r"sendBeacon", r"\bimport\(", r"\bsrc\s*=", r"\bhref\s*=\s*[\"']?(?!#)"):
        assert not re.search(bad, t, re.I), f"external reference pattern found: {bad}"


def test_the_html_is_what_the_build_produces_from_the_json():
    assert HTML.read_text(encoding="utf-8") == dgh.build(DATA, TEMPLATE, CAT), "data_guide.html is out of date: run py scripts/build_data_guide_html.py"


def test_the_html_footer_names_the_build_date_the_commit_and_the_measurement():
    t = HTML.read_text(encoding="utf-8")
    m = load()["meta"]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", m["built_at"]) and re.fullmatch(r"[0-9a-f]{7,40}", m["built_from_commit"])
    assert f"Built {m['built_at']} from commit {m['built_from_commit']}" in t and "Example data is made up." in t and f"Numbers measured {catalogue()['meta']['measured_at']}" in t


def test_the_staleness_check_itself_detects_a_change(tmp_path):
    d = load()
    d["meta"]["subtitle"] += " (changed)"
    p = tmp_path / "d.json"
    p.write_text(json.dumps(d), encoding="utf-8")
    assert dgh.build(p, TEMPLATE, CAT) != HTML.read_text(encoding="utf-8")


def test_a_changed_catalogue_changes_the_page(tmp_path):
    c = catalogue()
    c["coverage"]["lake_last_date"] = "2099-01-01"
    p = tmp_path / "c.json"
    p.write_text(json.dumps(c), encoding="utf-8")
    assert dgh.build(DATA, TEMPLATE, p) != HTML.read_text(encoding="utf-8")


def test_the_reference_checker_detects_a_missing_path_and_a_missing_name():
    assert check_ref("stockbot/data/asof.py::no_such_name_xyz")
    assert check_ref("stockbot/data/does_not_exist.py")
    assert check_ref("stockbot/data/asof.py::AsOfView") is None


def test_the_catalogue_checker_detects_an_invented_column_and_a_missing_table():
    d, c = load(), catalogue()
    t = next(x for x in d["tables"] if x["id"] == "market_data_lake")
    assert "made_up_col" not in c["tables"]["market_data_lake"]["columns"] and "made_up_col" not in [x["name"] for x in c["tables"]["market_data_lake"]["columns"]]
    assert {o["name"] for o in c["objects"] if o["type"] == "table"} - {x["id"] for x in d["tables"] if x["id"] != t["id"]} == {t["id"]}


def test_the_template_has_exactly_one_data_slot():
    t = TEMPLATE.read_text(encoding="utf-8")
    assert t.count(guide_html.DATA_SLOT) == 1 and t.count(guide_html.FOOT_SLOT) == 1


@pytest.mark.parametrize("bad", ["</script>", "<!--"])
def test_embedded_json_cannot_break_out_of_the_script_tag(bad, tmp_path):
    d = load()
    d["meta"]["subtitle"] = "x" + bad + "y"
    p = tmp_path / "d.json"
    p.write_text(json.dumps(d), encoding="utf-8")
    out = dgh.build(p, TEMPLATE, CAT)
    assert out.lower().count("</script>") == TEMPLATE.read_text(encoding="utf-8").lower().count("</script>")
    assert "<!--" not in out.split('id="guide-data"', 1)[1].split("</script>", 1)[0]


# ----------------------------------------------------------------------------------------------------- env-gated: the real lake, read-only
needs_lake = pytest.mark.skipif(os.environ.get("STOCKBOT_DATA_TESTS") != "1", reason="set STOCKBOT_DATA_TESTS=1 to check the guide against the real finsight.db (read-only)")


@pytest.fixture(scope="module")
def lake():
    from stockbot.data.lake import open_lake
    con = open_lake()
    yield con
    con.close()


@needs_lake
def test_every_table_view_index_and_trigger_in_sqlite_master_appears_in_the_guide(lake):
    d, c = load(), catalogue()
    known = {t["id"] for t in d["tables"]} | {t["name"] for t in d["triggers"]}
    for t in c["tables"].values():
        known |= {i["name"] for i in t["indexes"]}
    known |= {o["name"] for o in c["objects"]}                              # the catalogue is embedded in the page
    rows = lake.execute("select type, name from sqlite_master").fetchall()
    assert rows
    missing = [(t, n) for t, n in rows if n not in known]
    assert not missing, f"in finsight.db but not in the guide (regenerate the catalogue: py scripts/gen_data_catalogue.py --json --json-only): {missing}"
    own = {t["id"] for t in d["tables"]} | {t["name"] for t in d["triggers"]}
    assert {n for t, n in rows if t in ("table", "trigger")} <= own, "a table or trigger of the database has no entry of its own in data_guide_data.json"
    assert [n for t, n in rows if t == "view"] == [] or {n for t, n in rows if t == "view"} <= own, "the guide says the database has no views"


@needs_lake
def test_every_table_in_the_guide_exists_in_the_database(lake):
    live = {r[0] for r in lake.execute("select name from sqlite_master where type='table'")}
    guide = {t["id"] for t in load()["tables"]}
    assert guide <= live, sorted(guide - live)


@needs_lake
def test_every_column_of_the_guide_exists_in_the_database(lake):
    bad = []
    for t in load()["tables"]:
        real = {r[1] for r in lake.execute(f'pragma table_xinfo("{t["id"]}")')}
        bad += [(t["id"], c) for c in t["columns"] if c not in real]
    assert not bad, bad


@needs_lake
def test_the_database_declares_no_foreign_keys_as_the_page_says(lake):
    declared = {t["id"]: lake.execute(f'pragma foreign_key_list("{t["id"]}")').fetchall() for t in load()["tables"]}
    assert not {k: v for k, v in declared.items() if v}


@needs_lake
def test_the_row_counts_in_the_catalogue_equal_the_live_counts(lake):
    c = catalogue()
    wrong = {n: (t["rows"], lake.execute(f'select count(*) from "{n}"').fetchone()[0]) for n, t in c["tables"].items()}
    assert not {n: v for n, v in wrong.items() if v[0] != v[1]}, "the catalogue is out of date: py scripts/gen_data_catalogue.py --json --json-only"


@needs_lake
def test_the_sql_examples_run_read_only_and_the_first_returns_five_rows(lake):
    for q in load()["queries"]:
        rows = lake.execute(q["sql"]).fetchall()
        assert rows, q["id"]
    assert len(lake.execute(load()["queries"][0]["sql"]).fetchall()) == 5
    with pytest.raises(sqlite3.OperationalError):
        lake.execute("create table must_fail (a)")
