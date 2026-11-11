"""Acceptance item (restructure plan, Phase 10): the tree contains no strategy EXCEPT the ones the owner has approved by name. The allow-list is APPROVED_STRATEGY_IDS in
tests/fixtures/boundaries.py (a deliberate, reviewed change to that file). A listed folder may be absent. A folder under stockbot/strategies/ that is not listed fails, and every listed
folder keeps the import boundary (it imports only the interface, the spec, the data view types and stockbot.engine.exit_policy; never another strategy). Interfaces and the registry live in
stockbot/strategies; other strategy-shaped code is only the dummy under tests/ and the old macro kill switch kept as provenance (decision D1). Inside an approved folder: at most one
strategy class and no overlay.

Exit policies (exit-policies task, deliberate change): classes implementing the exit-policy interface are allowed in exactly two places, the shared library
stockbot/engine/exit_policies/ and a strategy's own folder stockbot/strategies/<name>/. Strategies and overlays are still allowed nowhere outside tests/."""
import ast
from pathlib import Path

import pytest

from stockbot.strategies.registry import default_registry
from tests.fixtures import boundaries as B

ROOT = Path(__file__).resolve().parents[2]
INTERFACES = ["stockbot/engine/exit_policy.py::ExitPolicy", "stockbot/strategies/base.py::Overlay", "stockbot/strategies/base.py::Strategy"]
APPROVED_STRATEGY_FOLDERS = list(B.APPROVED_STRATEGY_IDS)
LIBRARY_POLICIES = ["stockbot/engine/exit_policies/fixed_hold.py::FixedHold", "stockbot/engine/exit_policies/trailing_stop.py::TrailingStop"]


def kinds_of(n: ast.ClassDef) -> set:
    """A class with a ``propose`` method is a strategy; with ``evaluate`` and a ``version`` attribute an overlay; with ``initial_state`` + ``on_corporate_action`` an exit policy."""
    methods = {m.name for m in n.body if isinstance(m, ast.FunctionDef)}
    attrs = {t.target.id for t in n.body if isinstance(t, ast.AnnAssign) and isinstance(t.target, ast.Name)} | {t.targets[0].id for t in n.body if isinstance(t, ast.Assign) and isinstance(t.targets[0], ast.Name)}
    out = set()
    if "propose" in methods:
        out.add("strategy")
    if {"initial_state", "on_corporate_action"} <= methods:
        out.add("exit_policy")
    if "evaluate" in methods and "version" in attrs:
        out.add("overlay")
    return out


def exit_policy_home(rel: str) -> bool:
    """True for a path where an exit-policy class may live: stockbot/engine/exit_policies/<file>.py or stockbot/strategies/<name>/.../<file>.py."""
    p = rel.split("/")
    return (len(p) == 4 and p[:3] == ["stockbot", "engine", "exit_policies"]) or (len(p) >= 4 and p[:2] == ["stockbot", "strategies"])


def scan(root: Path, dirs=("stockbot", "scripts")):
    """All classes with an interface shape under ``root``: [(relative path, class name, kinds)]."""
    hits = []
    for d in dirs:
        for f in sorted((root / d).rglob("*.py")):
            rel = f.relative_to(root).as_posix()
            for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
                if isinstance(n, ast.ClassDef) and kinds_of(n):
                    hits.append((rel, n.name, kinds_of(n)))
    return hits


def approved_strategy_home(rel: str, approved=APPROVED_STRATEGY_FOLDERS) -> bool:
    """True for a path inside an approved strategy folder: stockbot/strategies/<approved id>/.../<file>.py."""
    p = rel.split("/")
    return len(p) >= 4 and p[:2] == ["stockbot", "strategies"] and p[2] in approved


def approved_strategy_hits(hits, approved=APPROVED_STRATEGY_FOLDERS):
    """The strategy classes (and only those) sitting in an approved folder."""
    return [(rel, name) for rel, name, kinds in hits if kinds == {"strategy"} and approved_strategy_home(rel, approved)]


def unlisted_strategy_folders(root: Path, approved=APPROVED_STRATEGY_FOLDERS) -> list:
    return sorted(p.name for p in (root / "stockbot" / "strategies").iterdir() if p.is_dir() and p.name != "__pycache__" and p.name not in approved)


def forbidden(hits):
    """Hits that are not an interface definition, not a lone strategy class in an approved folder and not an exit policy in an allowed home."""
    out = []
    for rel, name, kinds in hits:
        if f"{rel}::{name}" in INTERFACES:
            continue
        if kinds == {"strategy"} and approved_strategy_home(rel):
            continue
        if kinds == {"exit_policy"} and exit_policy_home(rel):
            continue
        out.append(f"{rel}::{name}")
    return out


def test_the_strategies_package_holds_only_the_interface_the_spec_and_the_registry():
    names = {p.name for p in (ROOT / "stockbot" / "strategies").glob("*.py")}
    assert names == {"__init__.py", "base.py", "registry.py", "spec.py"}, names


def test_the_strategies_folder_holds_only_approved_strategy_folders():
    """Every folder is on the allow-list (a listed folder may be absent); no strategy- or overlay-shaped class under stockbot/strategies except the two interface Protocols and at most one
    strategy class per approved folder."""
    assert unlisted_strategy_folders(ROOT) == [], unlisted_strategy_folders(ROOT)
    hits = [h for h in scan(ROOT) if h[0].startswith("stockbot/strategies/")]
    inside = [f"{rel}::{name}" for rel, name, kinds in hits if kinds & {"strategy", "overlay"}]
    approved = approved_strategy_hits(hits)
    assert sorted(inside) == sorted(["stockbot/strategies/base.py::Overlay", "stockbot/strategies/base.py::Strategy"] + [f"{r}::{n}" for r, n in approved]), inside
    folders = [r.split("/")[2] for r, _ in approved]
    assert len(folders) == len(set(folders)), f"more than one strategy class in a folder: {folders}"


def test_the_allow_list_holds_exactly_the_five_approved_ids():
    assert B.APPROVED_STRATEGY_IDS == ("near_52w_high", "short_term_reversal", "trend_breakout_100d", "low_volatility", "pullback_uptrend")


def test_an_unlisted_strategy_folder_fails_and_a_listed_or_absent_one_does_not(tmp_path):
    (tmp_path / "stockbot" / "strategies" / "short_term_reversal").mkdir(parents=True)
    assert unlisted_strategy_folders(tmp_path) == []                       # listed, the others absent: fine
    (tmp_path / "stockbot" / "strategies" / "secret_alpha").mkdir()
    (tmp_path / "stockbot" / "strategies" / "__pycache__").mkdir()
    assert unlisted_strategy_folders(tmp_path) == ["secret_alpha"]


def test_a_strategy_class_is_allowed_only_inside_an_approved_folder_and_no_overlay_anywhere():
    k = kinds_of(_cls(STRATEGY))
    assert forbidden([("stockbot/strategies/low_volatility/strategy.py", "S", k)]) == []
    assert forbidden([("stockbot/strategies/secret_alpha/strategy.py", "S", k)]) == ["stockbot/strategies/secret_alpha/strategy.py::S"]
    assert forbidden([("stockbot/risk/strategy.py", "S", k)]) == ["stockbot/risk/strategy.py::S"]
    assert forbidden([("stockbot/strategies/strategy.py", "S", k)]) == ["stockbot/strategies/strategy.py::S"]       # not inside a folder
    ov = kinds_of(_cls(OVERLAY))
    assert forbidden([("stockbot/strategies/low_volatility/o.py", "O", ov)]) == ["stockbot/strategies/low_volatility/o.py::O"]


def test_every_approved_folder_on_the_real_tree_obeys_the_import_boundary():
    own = tuple(f"stockbot.strategies.{i}" for i in B.APPROVED_STRATEGY_IDS)
    assert [v for v in B.check(ROOT) if v[0].startswith(own)] == []


def _tree(root: Path, sid: str, body: str) -> Path:
    d = root / "stockbot" / "strategies" / sid
    d.mkdir(parents=True)
    for p in (root / "stockbot", root / "stockbot" / "strategies", d):
        (p / "__init__.py").write_text("")
    (d / "strategy.py").write_text(body, encoding="utf-8")
    return root


OK_IMPORTS = ("from stockbot.strategies.base import Proposal\nfrom stockbot.strategies.spec import StrategySpec\nfrom stockbot.data.asof import AsOfView\n"
              "from stockbot.engine.exit_policy import ExitPolicy\n")


@pytest.mark.parametrize("sid", B.APPROVED_STRATEGY_IDS)
def test_the_boundary_checker_accepts_the_allowed_imports_and_catches_forbidden_ones_for_every_approved_id(tmp_path, sid):
    assert B.check(_tree(tmp_path / "ok", sid, OK_IMPORTS)) == set()
    other = next(i for i in B.APPROVED_STRATEGY_IDS if i != sid)
    cases = [("from stockbot.engine.decide import decide\n", "may not import engine"), ("from stockbot.engine.exit_policies import fixed_hold\n", "may not import engine"),
             (f"from stockbot.strategies.{other} import strategy\n", "may not import another strategy"), ("from stockbot.risk import sizing\n", "may not import risk"),
             ("import requests\n", "network library")]
    for n, (bad, rule) in enumerate(cases):
        got = B.check(_tree(tmp_path / f"bad{n}", sid, OK_IMPORTS + bad))
        assert any(rule in r for _, _, r in got), (sid, bad, got)


def test_the_default_registry_and_the_default_live_book_are_empty():
    from stockbot.live.runner import default_book
    assert len(default_registry) == 0 and default_book().strategies == ()


def test_no_class_outside_tests_implements_the_strategy_or_overlay_or_exit_policy_interface_except_where_allowed():
    hits = scan(ROOT)
    assert forbidden(hits) == [], forbidden(hits)
    # what is allowed is exactly the interface definitions plus the library's two policies (a new policy file must be added here on purpose)
    approved = approved_strategy_hits(hits)
    assert sorted(f"{rel}::{name}" for rel, name, _ in hits if (rel, name) not in approved) == sorted(INTERFACES + LIBRARY_POLICIES)


def _cls(src: str) -> ast.ClassDef:
    return next(n for n in ast.parse(src).body if isinstance(n, ast.ClassDef))


POLICY = "class P:\n    def initial_state(self, p, v): ...\n    def on_corporate_action(self, s, f): ...\n"
STRATEGY = "class S:\n    def propose(self, *a): ...\n"
OVERLAY = "class O:\n    version = '1.0.0'\n    def evaluate(self, v, s): ...\n"


def test_the_path_rule_allows_a_policy_only_in_the_library_or_a_strategy_folder():
    pol = kinds_of(_cls(POLICY))
    assert pol == {"exit_policy"}
    allowed = ["stockbot/engine/exit_policies/x.py", "stockbot/strategies/alpha/exits.py", "stockbot/strategies/alpha/sub/exits.py"]
    denied = ["stockbot/engine/x.py", "stockbot/engine/exit_policy.py", "stockbot/engine/exit_policies/sub/x.py", "stockbot/risk/x.py", "stockbot/strategies/x.py",
              "stockbot/live/x.py", "scripts/x.py", "stockbot/backtest/x.py"]
    assert all(forbidden([(p, "P", pol)]) == [] for p in allowed)
    assert all(forbidden([(p, "P", pol)]) == [f"{p}::P"] for p in denied)


def test_a_strategy_or_overlay_is_forbidden_everywhere_including_the_allowed_policy_homes():
    for src in (STRATEGY, OVERLAY, STRATEGY + POLICY.replace("class P", "class Q")):
        k = kinds_of(_cls(src))
        for p in ("stockbot/strategies/alpha/x.py", "stockbot/engine/exit_policies/x.py", "stockbot/risk/x.py"):
            assert forbidden([(p, "C", k)]) == [f"{p}::C"], (src, p)
    mixed = kinds_of(_cls("class M:\n    def propose(self): ...\n    def initial_state(self): ...\n    def on_corporate_action(self): ...\n"))
    assert mixed == {"strategy", "exit_policy"} and forbidden([("stockbot/strategies/alpha/x.py", "M", mixed)])


def test_the_scan_finds_a_policy_in_a_seeded_tree_and_the_boundary_check_catches_its_forbidden_import():
    from tests.fixtures import boundaries as B
    seeded = ROOT / "tests" / "fixtures" / "boundary_violations" / "strategy_policy_imports_library"
    hits = scan(seeded, dirs=("stockbot",))
    assert [(r, n) for r, n, _ in hits] == [("stockbot/strategies/alpha/pol.py", "AlphaExit")] and forbidden(hits) == []      # allowed by the path rule ...
    assert any("strategies may not import engine" in rule for _, _, rule in B.check(seeded))                                    # ... but its import of the library is caught
