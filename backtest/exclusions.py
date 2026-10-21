"""backtest/exclusions.py — Fail-closed surveillance & earnings exclusion loader."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Tuple
import pandas as pd


def _to_date(d) -> date:
    if hasattr(d, "date") and callable(getattr(d, "date")):
        return d.date()
    if isinstance(d, str):
        return date.fromisoformat(d)
    return d


@dataclass
class Exclusions:
    asm: dict            # symbol -> [(start, end)]
    earnings: dict       # symbol -> sorted [event_date]
    block_days: int
    known_ahead_days: int
    applied: bool = True

    def asm_blocked(self, sym: str, d: date) -> bool:
        dt = _to_date(d)
        return any(s <= dt <= e for s, e in self.asm.get(sym.upper(), []))

    def earnings_within(self, sym: str, d: date) -> bool:
        dt = _to_date(d)
        lim = min(self.block_days, self.known_ahead_days)  # cannot block on dates live could not know
        return any(dt <= ev <= dt + timedelta(days=lim) for ev in self.earnings.get(sym.upper(), []))

    @classmethod
    def load(
        cls,
        out_dir: Path,
        regime: str,
        block_days: int,
        known_ahead_days: int,
        allow_unverified: bool = False,
    ) -> "Exclusions":
        asm_p = out_dir / f"pending_asm_gsm_matches_{regime}.csv"
        earn_p = out_dir / f"historical_earnings_{regime}.csv"
        problems = []
        if not asm_p.exists():
            problems.append(f"missing {asm_p.name}")
        if not earn_p.exists():
            problems.append(f"missing {earn_p.name}")

        asm: Dict[str, List[Tuple[date, date]]] = {}
        earn: Dict[str, List[date]] = {}

        if asm_p.exists():
            df = pd.read_csv(asm_p)
            unverified = df[df["status"] != "VERIFIED"] if "status" in df.columns else df
            if len(unverified):
                problems.append(f"{len(unverified)} ASM/GSM rows not VERIFIED in {asm_p.name}")
            verified = df[df["status"] == "VERIFIED"] if "status" in df.columns else df.iloc[0:0]
            for r in verified.itertuples():
                s = _to_date(r.start_date)
                e = _to_date(r.end_date) if pd.notna(getattr(r, "end_date", None)) and r.end_date else date(2099, 12, 31)
                asm.setdefault(r.symbol.upper(), []).append((s, e))

        if earn_p.exists():
            df = pd.read_csv(earn_p)
            if df.empty:
                problems.append(f"{earn_p.name} is empty")
            for r in df.itertuples():
                earn.setdefault(r.symbol.upper(), []).append(_to_date(r.event_date))

        if problems and not allow_unverified:
            raise RuntimeError("Pass 2 refused (fail-closed): " + "; ".join(problems))

        return cls(
            asm,
            {k: sorted(v) for k, v in earn.items()},
            block_days,
            known_ahead_days,
            applied=not problems,
        )
