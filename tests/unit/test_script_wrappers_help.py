"""Every thin wrapper under scripts/ answers --help, exits 0 and writes nothing anywhere (reviewer ask B at STOP 4).

Writing is detected by fingerprinting (path, size, mtime) of every file under data/, docs/, scripts/, stockbot/, state/ and of finsight.db (+ -wal/-shm) before and after
each run. The scripts are run against the REAL tree on purpose: that is where an accidental write would hurt (one slip of this kind happened at STOP 4)."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WRAPPER_MARK = "Thin command-line wrapper"
WRAPPERS = sorted(p for p in (ROOT / "scripts").glob("*.py") if WRAPPER_MARK in p.read_text(encoding="utf-8").split("\n", 1)[0])
WATCHED = ("data", "docs", "scripts", "stockbot", "state")


def fingerprint() -> dict:
    out = {}
    for top in WATCHED:
        for dirpath, dirnames, filenames in os.walk(ROOT / top):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            for f in filenames:
                p = Path(dirpath) / f
                st = p.stat()
                out[str(p.relative_to(ROOT))] = (st.st_size, st.st_mtime_ns)
    for name in ("finsight.db", "finsight.db-wal", "finsight.db-shm"):
        p = ROOT / name
        if p.exists():
            st = p.stat()
            out[name] = (st.st_size, st.st_mtime_ns)
    return out


def test_there_are_wrappers_to_check():
    assert len(WRAPPERS) >= 20


def test_every_wrapper_and_the_provenance_readme_is_tracked_by_git():
    """Slip found in Phase 10: the wrappers existed on disk but were never committed (a new file at the path of a moved script is untracked, and `git add -u` does not add it)."""
    tracked = set(subprocess.run(["git", "ls-files", "scripts"], cwd=ROOT, capture_output=True, text=True).stdout.split())
    missing = [f"scripts/{p.name}" for p in WRAPPERS if f"scripts/{p.name}" not in tracked]
    assert not missing, f"wrappers not tracked by git: {missing}"
    assert "scripts/provenance/README.md" in tracked


@pytest.mark.parametrize("script", WRAPPERS, ids=lambda p: p.name)
def test_help_answers_and_writes_nothing(script):
    before = fingerprint()
    r = subprocess.run([sys.executable, str(script), "--help"], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, (script.name, r.stderr[-400:])
    assert r.stdout.lstrip().startswith("usage:"), (script.name, r.stdout[:200])
    after = fingerprint()
    changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    assert not changed, f"{script.name} --help changed files: {changed[:10]}"
