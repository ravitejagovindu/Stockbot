"""scripts/merge_asm_gsm_snapshots.py: dry run writes nothing; apply merges without overwriting existing rows; idempotent."""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import merge_asm_gsm_snapshots as mg  # noqa: E402
import snapshot_asm_gsm as snap       # noqa: E402


def _mk(path, rows, raw):
    c = sqlite3.connect(path)
    c.executescript(snap.DDL)
    c.executemany("insert into asm_gsm_daily_snapshot values (?,?,?,?,?,?,?,?,?,?,?)", rows)
    c.executemany("insert into asm_gsm_snapshot_raw values (?,?,?,?,?,?)", raw)
    c.commit(); c.close()


def row(d, sym, stage="Stage I", t="x"):
    return (d, "GSM", sym, "INE1", "Co", stage, "c", "d", t, 1, "2026-11-08T19:00:00")


def test_dry_run_apply_and_idempotence(tmp_path):
    src, dst = str(tmp_path / "s.db"), str(tmp_path / "m.db")
    _mk(src, [row("2026-11-08", "AAA", "SRC"), row("2026-11-09", "AAA")], [("2026-11-08", "reportGSM", "t", 200, 1, "[]"), ("2026-11-09", "reportGSM", "t", 200, 1, "[]")])
    _mk(dst, [row("2026-11-08", "AAA", "MAIN")], [("2026-11-08", "reportGSM", "t", 200, 1, "[]")])
    before = Path(dst).read_bytes()
    r = mg.merge(src, dst, apply=False)
    assert r["asm_gsm_daily_snapshot"]["would_add"] == 1 and Path(dst).read_bytes() == before        # dry run: byte-identical
    mg.merge(src, dst, apply=True)
    c = sqlite3.connect(dst)
    assert c.execute("select stage from asm_gsm_daily_snapshot where snapshot_date='2026-11-08'").fetchone()[0] == "MAIN"   # existing row kept
    assert c.execute("select count(*) from asm_gsm_daily_snapshot").fetchone()[0] == 2
    assert c.execute("select count(*) from asm_gsm_snapshot_raw").fetchone()[0] == 2
    c.close()
    mg.merge(src, dst, apply=True)
    c = sqlite3.connect(dst)
    assert c.execute("select count(*) from asm_gsm_daily_snapshot").fetchone()[0] == 2


def test_dry_run_on_target_without_tables_creates_nothing(tmp_path):
    src, dst = str(tmp_path / "s.db"), str(tmp_path / "m.db")
    _mk(src, [row("2026-11-08", "AAA")], [("2026-11-08", "reportGSM", "t", 200, 1, "[]")])
    sqlite3.connect(dst).close()
    r = mg.merge(src, dst, apply=False)
    assert r["asm_gsm_daily_snapshot"]["would_add"] == 1
    assert sqlite3.connect(dst).execute("select count(*) from sqlite_master").fetchone()[0] == 0
