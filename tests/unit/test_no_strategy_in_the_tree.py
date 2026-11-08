"""Acceptance item (restructure plan, Phase 10): the tree contains no strategy. Interfaces and the registry live in stockbot/strategies; the only strategy-shaped code is the dummy
under tests/ and the old macro kill switch kept as provenance (decision D1)."""
import ast
from pathlib import Path

from stockbot.strategies.registry import default_registry

ROOT = Path(__file__).resolve().parents[2]


def test_the_strategies_package_holds_only_the_interface_the_spec_and_the_registry():
    names = {p.name for p in (ROOT / "stockbot" / "strategies").glob("*.py")}
    assert names == {"__init__.py", "base.py", "registry.py", "spec.py"}, names


def test_the_default_registry_and_the_default_live_book_are_empty():
    from stockbot.live.runner import default_book
    assert len(default_registry) == 0 and default_book().strategies == ()


def test_no_class_outside_tests_implements_the_strategy_or_overlay_or_exit_policy_interface():
    """A class with a ``propose`` method is a strategy; with ``evaluate(view, overlay_state)`` an overlay; with ``initial_state`` + ``on_corporate_action`` an exit policy."""
    hits = []
    for d in ("stockbot", "scripts"):
        for f in (ROOT / d).rglob("*.py"):
            for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
                if isinstance(n, ast.ClassDef):
                    methods = {m.name for m in n.body if isinstance(m, ast.FunctionDef)}
                    if "propose" in methods or {"initial_state", "on_corporate_action"} <= methods or ("evaluate" in methods and "version" in {t.target.id for t in n.body if isinstance(t, ast.AnnAssign) and isinstance(t.target, ast.Name)} | {t.targets[0].id for t in n.body if isinstance(t, ast.Assign) and isinstance(t.targets[0], ast.Name)}):
                        hits.append(f"{f.relative_to(ROOT).as_posix()}::{n.name}")
    # the interface definitions themselves (Protocol classes) are the only allowed hits
    assert sorted(hits) == ["stockbot/engine/exit_policy.py::ExitPolicy", "stockbot/strategies/base.py::Overlay", "stockbot/strategies/base.py::Strategy"], hits
