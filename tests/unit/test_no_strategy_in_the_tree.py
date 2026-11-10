"""Acceptance item (restructure plan, Phase 10): the tree contains no strategy. Interfaces and the registry live in stockbot/strategies; the only strategy-shaped code is the dummy
under tests/ and the old macro kill switch kept as provenance (decision D1).

Exit policies (exit-policies task, deliberate change): classes implementing the exit-policy interface are allowed in exactly two places, the shared library
stockbot/engine/exit_policies/ and a strategy's own folder stockbot/strategies/<name>/. Strategies and overlays are still allowed nowhere outside tests/."""
import ast
from pathlib import Path

from stockbot.strategies.registry import default_registry

ROOT = Path(__file__).resolve().parents[2]
INTERFACES = ["stockbot/engine/exit_policy.py::ExitPolicy", "stockbot/strategies/base.py::Overlay", "stockbot/strategies/base.py::Strategy"]
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


def forbidden(hits):
    """Hits that are not an interface definition and not an exit policy in an allowed home."""
    out = []
    for rel, name, kinds in hits:
        if f"{rel}::{name}" in INTERFACES:
            continue
        if kinds == {"exit_policy"} and exit_policy_home(rel):
            continue
        out.append(f"{rel}::{name}")
    return out


def test_the_strategies_package_holds_only_the_interface_the_spec_and_the_registry():
    names = {p.name for p in (ROOT / "stockbot" / "strategies").glob("*.py")}
    assert names == {"__init__.py", "base.py", "registry.py", "spec.py"}, names


def test_the_strategies_folder_holds_no_strategy_today():
    """No strategy folder, and no strategy- or overlay-shaped class anywhere under stockbot/strategies except the two interface Protocols."""
    folders = sorted(p.name for p in (ROOT / "stockbot" / "strategies").iterdir() if p.is_dir() and p.name != "__pycache__")
    assert folders == [], folders
    inside = [f"{rel}::{name}" for rel, name, kinds in scan(ROOT) if rel.startswith("stockbot/strategies/") and kinds & {"strategy", "overlay"}]
    assert sorted(inside) == ["stockbot/strategies/base.py::Overlay", "stockbot/strategies/base.py::Strategy"], inside


def test_the_default_registry_and_the_default_live_book_are_empty():
    from stockbot.live.runner import default_book
    assert len(default_registry) == 0 and default_book().strategies == ()


def test_no_class_outside_tests_implements_the_strategy_or_overlay_or_exit_policy_interface_except_where_allowed():
    hits = scan(ROOT)
    assert forbidden(hits) == [], forbidden(hits)
    # what is allowed is exactly the interface definitions plus the library's two policies (a new policy file must be added here on purpose)
    assert sorted(f"{rel}::{name}" for rel, name, _ in hits) == sorted(INTERFACES + LIBRARY_POLICIES)


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
