"""Fail-before check: for each case, apply a one-line mutation to the code under test, run the named test(s), require a FAILURE, restore the file.

Usage: py docs/restructure/tools/fail_before.py <cases.json> [--append docs/restructure/PARTB_FAIL_BEFORE.md]
cases.json: [{"test": "tests/unit/x.py::test_a", "file": "stockbot/engine/types.py", "old": "text", "new": "text", "why": "what the mutation breaks"}, ...]
A case passes the check when the mutated run FAILS (the test detects the defect) and the unmutated run PASSES.
The file is always restored (byte-identical) in a finally block.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def run(test: str) -> bool:
    r = subprocess.run([sys.executable, "-m", "pytest", test, "-q", "-x", "-p", "no:cacheprovider"], cwd=ROOT, capture_output=True, text=True)
    return r.returncode == 0


def main() -> int:
    cases = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    rows, bad = [], 0
    for c in cases:
        f = ROOT / c["file"]
        orig = f.read_bytes()
        text = orig.decode("utf-8")
        if text.count(c["old"]) != 1:
            print("MUTATION NOT UNIQUE/FOUND:", c["file"], c["old"][:50])
            bad += 1
            continue
        try:
            clean = run(c["test"])
            f.write_bytes(text.replace(c["old"], c["new"]).encode("utf-8"))
            mutated = run(c["test"])
        finally:
            f.write_bytes(orig)
        ok = clean and not mutated
        bad += 0 if ok else 1
        rows.append((c["test"], c["file"], c["why"], "passes clean / FAILS mutated" if ok else f"PROBLEM clean={clean} mutated_passes={mutated}"))
        print(("OK  " if ok else "BAD ") + c["test"], "-", c["why"])
    if "--append" in sys.argv:
        out = Path(sys.argv[sys.argv.index("--append") + 1])
        new = not out.exists()
        with out.open("a", encoding="utf-8") as fh:
            if new:
                fh.write("# Part B fail-before evidence\n\nEach row: the test, the code file, the mutation that breaks it, and the result (the test must pass on the real code and FAIL on the mutated code).\n\n| test | code mutated | defect introduced | result |\n|---|---|---|---|\n")
            for r in rows:
                fh.write("| " + " | ".join(x.replace("|", "/") for x in r) + " |\n")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
