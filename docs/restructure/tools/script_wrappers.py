"""docs/restructure/tools/script_wrappers.py - Phase 8 helper, run AFTER move_modules.py moved scripts into a package.

Usage: py docs/restructure/tools/script_wrappers.py <package dotted path> <module> [<module> ...]
For each moved module: fix the repo-root depth (Path(__file__).parents[1] -> parents[n]), drop the sys.path insert lines (the package is importable; no path hacks inside stockbot/),
and write a thin wrapper at scripts/<module>.py that only runs the package module as __main__ (arguments pass through unchanged).
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WRAPPER = '''"""Thin command-line wrapper: the logic lives in {pkg}.{mod} (restructure Phase 8). Run from anywhere: py scripts/{mod}.py [args]."""
import runpy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
runpy.run_module("{pkg}.{mod}", run_name="__main__", alter_sys=True)
'''


def main(pkg, mods):
    depth = len(pkg.split(".")) 
    for m in mods:
        p = ROOT / (pkg.replace(".", "/") + f"/{m}.py")
        s = p.read_text(encoding="utf-8")
        crlf = "\r\n" in s
        s = s.replace("\r\n", "\n")
        s = re.sub(r"(_?ROOT = Path\(__file__\)\.resolve\(\)\.)parents\[1\]", rf"\1parents[{depth}]", s)
        s = re.sub(r"^# Add project root to sys\.path\n", "", s, flags=re.M)
        s = re.sub(r"^if str\(_?ROOT\) not in sys\.path:\n    sys\.path\.insert\(0, str\(_?ROOT\)\)\n", "", s, flags=re.M)
        s = re.sub(r"^sys\.path\.insert\(0, str\(_?ROOT\)\)\n", "", s, flags=re.M)
        p.write_text(s.replace("\n", "\r\n") if crlf else s, encoding="utf-8", newline="")
        (ROOT / "scripts" / f"{m}.py").write_text(WRAPPER.format(pkg=pkg, mod=m), encoding="utf-8")
        left = [l for l in s.split("\n") if "sys.path" in l or "parents[" in l]
        print(f"{m}: wrapper written; remaining path lines: {left}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])
