"""docs/restructure/tools/removed_tests.py - lists the test functions that exist at HEAD but not in the working tree (deleted files and deleted functions) and appends them to
docs/restructure/REMOVED_TESTS.md with the reason and the replacement you pass in a JSON file.

Usage: py docs/restructure/tools/removed_tests.py <reasons.json> "<phase label>"
reasons.json: {"tests/unit/x.py": {"reason": "...", "covered_by": "..."}, ...}   (a file not in the map is reported and stops the run)
Counts: parametrised tests count once per function here; the per-commit G1 arithmetic uses pytest's collected counts (run with --collect-only before and after).
"""
import ast
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def names(src: str) -> list:
    out = []
    for n in ast.parse(src).body:
        if isinstance(n, ast.FunctionDef) and n.name.startswith("test_"):
            out.append(n.name)
        elif isinstance(n, ast.ClassDef):
            out += [f"{n.name}.{m.name}" for m in n.body if isinstance(m, ast.FunctionDef) and m.name.startswith("test_")]
    return out


def main() -> int:
    reasons = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    label = sys.argv[2]
    changed = subprocess.run(["git", "status", "--porcelain", "--", "tests"], cwd=ROOT, capture_output=True, text=True).stdout.splitlines()
    rows, missing = [], []
    for line in changed:
        status, path = line[:2].strip(), line[3:].strip().strip('"')
        if "->" in path or not path.endswith(".py") or status not in ("D", "M", "MD", "AD", "DM"):
            continue
        old = subprocess.run(["git", "show", f"HEAD:{path}"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8").stdout
        if not old:
            continue
        now = (ROOT / path).read_text(encoding="utf-8") if (ROOT / path).exists() else ""
        gone = [n for n in names(old) if n not in (names(now) if now else [])]
        if not gone:
            continue
        if path not in reasons:
            missing.append(path)
            continue
        r = reasons[path]
        rows.append(f"| {label} | `{path}` | {', '.join('`' + g + '`' for g in gone)} ({len(gone)}) | {r['reason']} | {r['covered_by']} |")
    if missing:
        print("NO REASON GIVEN FOR:", missing)
        return 1
    with open(ROOT / "docs/restructure/REMOVED_TESTS.md", "a", encoding="utf-8") as fh:
        fh.write("\n" + "\n".join(rows) + "\n")
    print(len(rows), "rows appended")
    return 0


if __name__ == "__main__":
    sys.exit(main())
