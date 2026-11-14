"""The fast-view switch after the merge: subclasses honour it (and a new one cannot silently bypass it), every run records which view it used, and the live path refuses the memory view."""
import ast
import importlib
import importlib.util
from datetime import timedelta
from pathlib import Path

import pandas as pd
import pytest

from stockbot.backtest.manifest import run_manifest
from stockbot.backtest.runner import run_backtest
from stockbot.config.shared import load_shared_config
from stockbot.data import asof_memory
from stockbot.data.asof import AsOfView, active_view_name
from stockbot.data.asof_memory import MemoryAsOfView
from stockbot.data.lake import open_lake
from stockbot.live import MemoryViewNotValidated, refuse_memory_view
from stockbot.live.adapter import LiveAdapter
from stockbot.live.health_check import check
from stockbot.live.runner import Book, run_eod
from stockbot.live.state_store import StateStore
from tests.fixtures import mini_lake
from tests.fixtures.dummies import FixedPolicy, ScriptedStrategy, make_spec
from tests.fixtures.engine_run import CFG as ENGINE_CFG, EVENTS, policies
from tests.fixtures.lakefile import _make

ROOT = Path(__file__).resolve().parents[2]
DS = mini_lake.sessions()
EXEMPT: dict = {}        # class name -> why it may stay on the SQL view. Empty on purpose: every subclass honours the switch.


@pytest.fixture(scope="module")
def lake(tmp_path_factory):
    p = tmp_path_factory.mktemp("fv") / "lake.db"
    _make(p)
    return p


# ---------------------------------------------------------------- the name of the view
def test_active_view_name_both_values(monkeypatch):
    monkeypatch.delenv("STOCKBOT_VIEW", raising=False)
    assert active_view_name() == "sql"
    for v, want in (("sql", "sql"), ("", "sql"), ("nonsense", "sql"), ("memory", "memory"), (" Memory ", "memory")):
        monkeypatch.setenv("STOCKBOT_VIEW", v)
        assert active_view_name() == want


@pytest.mark.parametrize("name", ["sql", "memory"])
def test_the_manifest_and_the_run_record_the_view(lake, monkeypatch, capsys, name):
    monkeypatch.setenv("STOCKBOT_VIEW", name)
    s = ScriptedStrategy(make_spec("dummy", "timed"), {})
    r = run_backtest(lake, DS[298], DS[300], 1_000_000.0, [s], policies(FixedPolicy(id="timed", max_days=5)), ENGINE_CFG, EVENTS, seed=7)
    assert r.manifest["asof_view"] == name
    assert f"asof_view: {name}" in capsys.readouterr().out
    assert run_manifest(shared_config=ENGINE_CFG, strategies=[s], window=(DS[298], DS[300]), initial_equity=1.0)["asof_view"] == name


def test_the_view_name_changes_nothing_else_in_a_run(lake, monkeypatch):
    s = ScriptedStrategy(make_spec("dummy", "timed"), {})
    out = {}
    for name in ("sql", "memory"):
        monkeypatch.setenv("STOCKBOT_VIEW", name)
        r = run_backtest(lake, DS[298], DS[300], 1_000_000.0, [s], policies(FixedPolicy(id="timed", max_days=5)), ENGINE_CFG, EVENTS, seed=7)
        out[name] = (r.decisions, r.trades, r.equity_curve, {k: v for k, v in r.manifest.items() if k != "asof_view"})
    assert out["sql"] == out["memory"]


# ------------------------------------------------------------- subclasses and the switch
def test_a_subclass_is_built_on_the_memory_view_and_answers_like_the_sql_one(lake, monkeypatch):
    class Capped(AsOfView):
        def raw_bars(self, symbol, lookback=400, start=None, end=None):
            if lookback is None and start is not None and end is None:
                end = start + timedelta(days=9)
            return super().raw_bars(symbol, lookback, start, end)

    conn, day, start = open_lake(lake), DS[mini_lake.N_SESSIONS - 1], DS[mini_lake.BREAKOUT - 20]
    monkeypatch.delenv("STOCKBOT_VIEW", raising=False)
    sql = Capped(conn, day)
    assert type(sql) is Capped and not isinstance(sql, MemoryAsOfView)
    monkeypatch.setenv("STOCKBOT_VIEW", "memory")
    mem = Capped(conn, day)
    assert isinstance(mem, Capped) and isinstance(mem, MemoryAsOfView) and type(mem).__name__ == "Capped" and mem.as_of == day
    assert asof_memory.memory_variant(Capped) is type(mem)                      # one variant per class
    for sym in ("FIXCO", "NIFTY50_INDEX"):
        capped = mem.raw_bars(sym, None, start=start)
        assert len(capped) < len(AsOfView(conn, day).raw_bars(sym, None, start=start))   # the override really acts
        pd.testing.assert_frame_equal(sql.raw_bars(sym, None, start=start), capped, check_exact=True)
        pd.testing.assert_frame_equal(sql.adjusted_bars(sym), mem.adjusted_bars(sym), check_exact=True)
    assert sql.sessions() == mem.sessions() and sql.symbols_trading() == mem.symbols_trading()


def _subclass_files():
    hits = []
    for base in ("stockbot", "scripts"):
        for f in sorted((ROOT / base).rglob("*.py")):
            tree = ast.parse(f.read_text(encoding="utf-8"))
            for n in ast.walk(tree):
                if isinstance(n, ast.ClassDef) and any((getattr(b, "id", None) or getattr(b, "attr", None)) in ("AsOfView", "MemoryAsOfView") for b in n.bases):
                    hits.append((f, n.name))
    return hits


def _load(path: Path):
    if path.parent.name != "scripts":
        return importlib.import_module(".".join(path.relative_to(ROOT).with_suffix("").parts))
    spec = importlib.util.spec_from_file_location("fv_scan_" + path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_every_asof_subclass_in_the_code_honours_the_switch_or_is_listed_as_exempt(monkeypatch):
    found = _subclass_files()
    assert {n for _, n in found} >= {"MemoryAsOfView", "ForwardCappedView"}      # the scan really sees the known ones
    classes = {name: getattr(_load(f), name) for f, name in found}
    monkeypatch.setenv("STOCKBOT_VIEW", "memory")
    for name, cls in classes.items():
        if name in EXEMPT:
            assert EXEMPT[name].strip(), f"{name} is exempt without a reason"
            continue
        obj = AsOfView.__new__(cls)
        assert isinstance(obj, MemoryAsOfView), f"{name} (an AsOfView subclass) bypasses STOCKBOT_VIEW=memory: make it honour the switch or list it in EXEMPT with the reason"
        assert isinstance(obj, cls)
    monkeypatch.setenv("STOCKBOT_VIEW", "sql")
    for name, cls in classes.items():
        if cls is not MemoryAsOfView:
            assert not isinstance(AsOfView.__new__(cls), MemoryAsOfView)


# ------------------------------------------------------------------------- live safety
def test_the_live_path_refuses_the_memory_view(lake, tmp_path, monkeypatch):
    cfg = load_shared_config()
    book = Book((ScriptedStrategy(make_spec("dummy", status="paper"), {}),), {"fixed": FixedPolicy()})
    store = StateStore(tmp_path / "state.db")
    monkeypatch.setenv("STOCKBOT_VIEW", "memory")
    with pytest.raises(MemoryViewNotValidated, match="memory view is not validated for live; unset STOCKBOT_VIEW"):
        refuse_memory_view()
    with pytest.raises(MemoryViewNotValidated):
        run_eod(cfg=cfg, book=book, as_of=DS[300], store=store, lake=lake, out_dir=tmp_path / "t", mode="PAPER")
    with pytest.raises(MemoryViewNotValidated):
        LiveAdapter(store, lake, book.strategies, book.policies, cfg, EVENTS)
    with pytest.raises(MemoryViewNotValidated):
        check(open_lake(lake), store, DS[300])
    monkeypatch.setenv("STOCKBOT_VIEW", "sql")
    refuse_memory_view()                                                          # SQL: no error
    monkeypatch.delenv("STOCKBOT_VIEW", raising=False)
    refuse_memory_view()
    LiveAdapter(store, lake, book.strategies, book.policies, cfg, EVENTS)
