"""The interactive codebase guide (docs/guides/codebase_guide.html) must stay true to the repository.

  * every path / module / script named in docs/guides/codebase_guide_data.json exists ("path::name" also needs ``name`` to occur in that file);
  * every stockbot/ package is in the JSON, and the import table in the JSON equals the rule table the build enforces (tests/fixtures/boundaries.py);
  * every content item carries a "source"; panel text stays short;
  * the HTML loads nothing from outside (no URL of any kind, no external script/style/image/font, no network API);
  * the HTML is exactly what scripts/build_guide_html.py produces from the JSON and the template (so it cannot go stale).
"""
import json
import re
from pathlib import Path

import pytest

from stockbot.data_checks import guide_html
from tests.fixtures import boundaries as B

ROOT = Path(__file__).resolve().parents[2]
GUIDES = ROOT / "docs" / "guides"
DATA = GUIDES / "codebase_guide_data.json"
HTML = GUIDES / "codebase_guide.html"
TEMPLATE = GUIDES / "codebase_guide_template.html"
REQUIRED_TERMS = {"session", "as-of", "ADTV", "R", "ex-date", "arbitration", "prereg", "ledger", "ticket", "PIT", "EQ series"}
LISTS_WITH_SOURCE = ("packages", "blocks", "engine_steps", "backtest_lane", "live_lane", "trade_steps", "add_items", "never_items", "validation_steps", "symptoms", "glossary")
RUNTIME_PATHS = {"state/live_state.db", "state/tickets", "state/tickets/", "finsight.db"}     # created by a first run / git-ignored


def load():
    return json.loads(DATA.read_text(encoding="utf-8"))


def walk(o):
    """Yield (key, value) for every dict entry in a nested structure."""
    if isinstance(o, dict):
        for k, v in o.items():
            yield k, v
            yield from walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from walk(v)


def named_paths(d):
    out = []
    for k, v in walk(d):
        if k in ("path", "source") and isinstance(v, str) and v:
            out.append(v)
        if k == "paths" and isinstance(v, list):
            out.extend(v)
    return out


def check_ref(ref):
    """None if the reference is fine, else a message. 'a/b.py::name' also requires ``name`` to occur in the file."""
    path, _, name = ref.partition("::")
    if path in RUNTIME_PATHS:
        return None
    p = ROOT / path.rstrip("/")
    if not p.exists():
        return f"missing path {path}"
    if name and p.is_file() and name not in p.read_text(encoding="utf-8", errors="replace"):
        return f"{name!r} not found in {path}"
    return None


def stockbot_packages():
    return sorted(".".join(p.parent.relative_to(ROOT).parts) for p in (ROOT / "stockbot").rglob("__init__.py") if "__pycache__" not in p.parts)


# ---------------------------------------------------------------------------------------------------------------- the JSON
def test_every_path_named_in_the_json_exists():
    refs = named_paths(load())
    assert len(refs) > 100, "suspiciously few references"
    bad = sorted({m for r in refs for m in [check_ref(r)] if m})
    assert not bad, bad


def test_every_stockbot_package_is_in_the_json():
    names = {p["name"] for p in load()["packages"]}
    for p in load()["packages"]:
        names |= {s["name"] for s in p.get("subpackages", [])}
    missing = [p for p in stockbot_packages() if p != "stockbot" and p not in names]
    assert not missing, f"packages missing from codebase_guide_data.json: {missing}"


def test_the_import_table_in_the_json_equals_the_enforced_rules():
    j = {p["id"]: set(p["may_import"]) for p in load()["packages"] if p["kind"] == "package"}
    assert j == {k: set(v) for k, v in B.ALLOWED.items()}


def test_every_content_item_has_a_source():
    d = load()
    for key in LISTS_WITH_SOURCE:
        assert d[key], key
        for it in d[key]:
            assert it.get("source"), f"{key}: item without source: {it.get('id') or it.get('n') or it.get('term') or it.get('title')}"
    for p in d["packages"]:
        for m in p.get("modules", []):
            assert m.get("path"), f"{p['id']}: module without path: {m}"


def test_panel_text_is_short():
    d = load()
    long = []
    for key in ("engine_steps", "backtest_lane", "live_lane", "trade_steps", "validation_steps"):
        for it in d[key]:
            for f in ("plain", "q"):
                if len(str(it.get(f, "")).split()) > 40:
                    long.append((key, it.get("n") or it.get("id"), f))
    for p in d["packages"]:
        if len(p["meaning"].split()) > 45:
            long.append(("packages", p["id"], "meaning"))
    assert not long, long


def test_the_glossary_has_the_required_terms():
    terms = {g["term"] for g in load()["glossary"]}
    assert REQUIRED_TERMS <= terms, REQUIRED_TERMS - terms


def test_the_engine_steps_follow_the_order_of_decide():
    """The step titles are tied to the section comments in engine/decide.py: the order of those comments is the order of the steps."""
    src = (ROOT / "stockbot" / "engine" / "decide.py").read_text(encoding="utf-8")
    order = [m.start() for m in (re.search(re.escape(k), src) for k in ("_validate_session(as_of", "# ---- 1) overlays", "# ---- 2) fills", "# ---- 3) corporate actions",
                                                                         "# ---- 4) proposals", "return dec, apply_decisions"))]
    assert order == sorted(order)
    ids = [s["id"] for s in load()["engine_steps"]]
    assert ids == ["validate", "overlays", "fills", "corporate", "step", "eligibility", "propose", "size", "arbitrate", "decisions"]


# ---------------------------------------------------------------------------------------------------------------- the HTML
def test_the_html_exists_and_is_self_contained():
    t = HTML.read_text(encoding="utf-8")
    assert len(t) > 20000
    assert "http://" not in t and "https://" not in t, "the page must not contain any URL"
    for bad in (r"<script[^>]+src\s*=", r"<link\b", r"<img\b", r"<iframe\b", r"<audio\b", r"<video\b", r"<source\b", r"@import", r"url\((?!#)", r"\bfetch\(",     # url(#id) is a reference to a marker inside the page itself
 r"XMLHttpRequest",
                r"WebSocket", r"sendBeacon", r"\bimport\(", r"\bsrc\s*=", r"\bhref\s*=\s*[\"']?(?!#)"):
        assert not re.search(bad, t, re.I), f"external reference pattern found: {bad}"


def test_the_html_is_what_the_build_produces_from_the_json():
    assert HTML.read_text(encoding="utf-8") == guide_html.build(DATA, TEMPLATE), "codebase_guide.html is out of date: run py scripts/build_guide_html.py"


def test_the_staleness_check_itself_detects_a_change(tmp_path):
    d = load()
    d["meta"]["subtitle"] = d["meta"]["subtitle"] + " (changed)"
    p = tmp_path / "d.json"
    p.write_text(json.dumps(d), encoding="utf-8")
    assert guide_html.build(p, TEMPLATE) != HTML.read_text(encoding="utf-8")


def test_the_reference_checker_detects_a_missing_path_and_a_missing_name():
    assert check_ref("stockbot/engine/does_not_exist.py")
    assert check_ref("stockbot/engine/decide.py::no_such_function_xyz")
    assert check_ref("stockbot/engine/decide.py::decide") is None
    assert check_ref("state/tickets/") is None


def test_the_template_has_exactly_one_data_slot():
    t = TEMPLATE.read_text(encoding="utf-8")
    assert t.count(guide_html.DATA_SLOT) == 1 and t.count(guide_html.FOOT_SLOT) == 1


@pytest.mark.parametrize("bad", ["</script>", "<!--"])
def test_embedded_json_cannot_break_out_of_the_script_tag(bad, tmp_path):
    d = load()
    d["meta"]["subtitle"] = "x" + bad + "y"
    p = tmp_path / "d.json"
    p.write_text(json.dumps(d), encoding="utf-8")
    out = guide_html.build(p, TEMPLATE)
    assert out.lower().count("</script>") == TEMPLATE.read_text(encoding="utf-8").lower().count("</script>")
    assert "<!--" not in out.split("id=\"guide-data\"", 1)[1].split("</script>", 1)[0]
