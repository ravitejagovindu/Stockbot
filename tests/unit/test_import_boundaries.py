"""Import-boundary test for stockbot/ (restructure plan section 2, guards a-c of the Stop-1 review). Rules and checker: tests/fixtures/boundaries.py."""
import os
from pathlib import Path

import pytest

from tests.fixtures import boundaries as B

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "tests" / "fixtures" / "boundary_violations"


def _covered(v, allow):
    mod, name, _ = v
    return any(mod == m and (name == p or name.startswith(p + ".")) for (m, p) in allow)


def _uncovered(root):
    return sorted(v for v in B.check(root) if not _covered(v, B.LEGACY_ALLOWLIST))


def test_real_tree_has_no_violations_beyond_the_allowlist():
    assert _uncovered(ROOT) == []


def test_allowlist_has_no_stale_entries_and_every_entry_names_its_removal_phase():
    found = B.check(ROOT)
    stale = [(m, p) for (m, p), ph in B.LEGACY_ALLOWLIST.items() if not any(m == v[0] and (v[1] == p or v[1].startswith(p + ".")) for v in found)]
    assert not stale, f"allowlist entries whose edge no longer exists (delete them): {stale}"
    assert all(str(ph).startswith("Phase ") for ph in B.LEGACY_ALLOWLIST.values())


@pytest.mark.parametrize("case,needle", [
    ("strategy_imports_strategy", "a strategy may not import another strategy"),
    ("engine_imports_session", "database library inside engine"),
    ("engine_imports_session", "legacy"),
    ("live_imports_backtest", "live may not import backtest"),
    ("risk_uses_network", "network library inside risk"),
    ("validation_imports_live", "validation may not import live"),
    ("sys_path_hack", "sys.path edit"),
    ("legacy_import", "legacy"),
])
def test_seeded_violations_are_caught(case, needle):
    rules = [r for _, _, r in B.check(FIX / case)]
    assert any(needle in r for r in rules), (case, rules)


def test_clean_fixture_passes():
    assert B.check(FIX / "clean") == set()


def test_no_python_files_under_top_level_data_except_listed_legacy():
    present = {p.relative_to(ROOT).as_posix() for p in (ROOT / "data").rglob("*.py")}
    unlisted = sorted(present - set(B.LEGACY_DATA_PY))
    gone = sorted(set(B.LEGACY_DATA_PY) - present)
    assert not unlisted, f"new code under data/ (data/ is for non-code files; put code in stockbot/data): {unlisted}"
    assert not gone, f"listed legacy files that no longer exist (delete the entries): {gone}"


@pytest.mark.skipif(os.environ.get("STOCKBOT_FINAL_CHECK") != "1", reason="the allowlists must be empty at STOP 5 (run with STOCKBOT_FINAL_CHECK=1)")
def test_allowlists_are_empty_at_the_end():
    assert not B.LEGACY_ALLOWLIST and not B.LEGACY_DATA_PY
