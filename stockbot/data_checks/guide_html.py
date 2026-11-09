"""Builds docs/guides/codebase_guide.html (one self-contained page) from docs/guides/codebase_guide_data.json and docs/guides/codebase_guide_template.html.

Offline, standard library only. The page does all its drawing in JavaScript from the JSON embedded in it, so the HTML is a pure function of the two input files:
``build(data_path, template_path)`` returns the same text every time (the footer date and commit come from the JSON "meta", written by ``--stamp``).

  py scripts/build_guide_html.py            rebuild the HTML from the JSON and the template
  py scripts/build_guide_html.py --stamp    first set meta.built_at (today) and meta.built_from_commit (git HEAD) in the JSON, then rebuild
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Optional, Sequence

from stockbot.config.paths import repo_root

DATA_SLOT = "/*__GUIDE_DATA__*/"
FOOT_SLOT = "<!--__GUIDE_FOOTER__-->"


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def embed_json(data: dict) -> str:
    """JSON that is safe inside a <script type=application/json> element: no closing tag, no comment opener, no U+2028/2029."""
    text = json.dumps(data, ensure_ascii=False, indent=1, sort_keys=False)
    return text.replace("</", "<\\/").replace("<!--", "<\\!--").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def build(data_path: Path, template_path: Path) -> str:
    data = json.loads(Path(data_path).read_text(encoding="utf-8"))
    tpl = Path(template_path).read_text(encoding="utf-8")
    if tpl.count(DATA_SLOT) != 1 or tpl.count(FOOT_SLOT) != 1:
        raise SystemExit(f"template must contain {DATA_SLOT} and {FOOT_SLOT} exactly once")
    m = data["meta"]
    footer = f"Built {_esc(m['built_at'])} from commit {_esc(m['built_from_commit'])}. Example numbers in this guide are made up."
    return tpl.replace(DATA_SLOT, embed_json(data)).replace(FOOT_SLOT, footer)


def _git_head(root: Path) -> str:
    return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root, capture_output=True, text=True, check=True).stdout.strip()


def main(argv: Optional[Sequence[str]] = None) -> int:
    root = repo_root()
    g = root / "docs" / "guides"
    ap = argparse.ArgumentParser(description="Build docs/guides/codebase_guide.html from codebase_guide_data.json and the template (offline).")
    ap.add_argument("--data", default=str(g / "codebase_guide_data.json"))
    ap.add_argument("--template", default=str(g / "codebase_guide_template.html"))
    ap.add_argument("--out", default=str(g / "codebase_guide.html"))
    ap.add_argument("--stamp", action="store_true", help="set meta.built_at (today) and meta.built_from_commit (git HEAD) in the JSON first")
    a = ap.parse_args(argv)
    if a.stamp:
        p = Path(a.data)
        d = json.loads(p.read_text(encoding="utf-8"))
        d["meta"]["built_at"], d["meta"]["built_from_commit"] = date.today().isoformat(), _git_head(root)
        p.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    text = build(Path(a.data), Path(a.template))
    Path(a.out).write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {a.out} ({len(text):,} characters)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
