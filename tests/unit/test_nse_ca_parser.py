"""F2 — NSE corporate-action subject parser: ratios follow the engine_core.adjustments convention."""
from __future__ import annotations

import pytest

from data.ingestion.nse_corporate_actions_history import parse_subject
from engine_core.adjustments import action_factor


def _factors(subject):
    return [(a["action_type"], action_factor({"action_type": a["action_type"], "ratio_numerator": a["num"],
                                              "ratio_denominator": a["den"]})) for a in parse_subject(subject)
            if a["action_type"] in ("SPLIT", "BONUS")]


@pytest.mark.parametrize("subject,expected", [
    (" Bonus 1:1", [("BONUS", 0.5)]),
    ("Bonus 4:1", [("BONUS", 0.2)]),
    ("Face Value Split (Sub-Division) - From Rs 10/- Per Share To Re 1/- Per Share", [("SPLIT", 0.1)]),
    ("Face Value Split (Sub-Division) - From Rs 2/- Per Share To Re 1/- Per Share", [("SPLIT", 0.5)]),
    ("Face Value Split From Rs.10/- To Rs.2/-", [("SPLIT", 0.2)]),
    (" Bonus 1:1/Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/- Per Share",
     [("SPLIT", 0.2), ("BONUS", 0.5)]),
    ("Annual General Meeting/ Dividend - Rs 29.50/- Per Share And Bonus 1:1", [("BONUS", 0.5)]),
    ("Bonus 2:5", [("BONUS", 5 / 7)]),
    ("Face Value Split Rs.10/- To Re.1/- Per Share", [("SPLIT", 0.1)]),                  # no "From" (SBIN)
    ("Fv Split Rs.10 To Rs.5", [("SPLIT", 0.5)]),                                         # M&M 2010
    ("Bonus 1:1 And Face Value Split From Rs.10/- To Rs.5/-", [("SPLIT", 0.5), ("BONUS", 0.5)]),
    ("Bonus 1 : 1", [("BONUS", 0.5)]),
    ("Scheme Of Arrangement - Bonus Debentures 6:1", []),                                  # not a price-moving bonus
    ("Scheme Of Arangement- Bonus - 1 Debenture For 1 Equity Share Held", []),
    ("Bonus Preference Shares 21:1", []),
])
def test_split_and_bonus_factors(subject, expected):
    got = _factors(subject)
    assert sorted(g[0] for g in got) == sorted(e[0] for e in expected)
    for (t, f), (t2, f2) in zip(sorted(got), sorted(expected)):
        assert f == pytest.approx(f2)


def test_other_types():
    assert [a["action_type"] for a in parse_subject("Demerger")] == ["DEMERGER"]
    assert parse_subject("Rights 1:15 @ Premium Rs 1247")[0]["action_type"] == "RIGHTS"
    assert parse_subject("Interim Dividend - Rs 7 Per Share")[0]["action_type"] == "DIVIDEND"
    assert parse_subject("Annual General Meeting") == []
    assert parse_subject("Bonus issue details awaited")[0]["action_type"] == "OTHER"


# ---- Step 4 fixes (reviewer: fix the patterns behind TVSMOTOR / TVSHLTD / SIYSIL / RADIOCITY / SHARONBIO)
@pytest.mark.parametrize("subject", [
    "Scheme Of Arrangement - Bonus Ncrps 4:1",       # TVSMOTOR 2025-08-25
    "Scheme Of Arrangement - Bonus Ncrps 46:1",      # TVSHLTD 2026-09-08
    "Scheme Of Arrangement - Bonus Ncrps 1:10",      # RADIOCITY 2023-01-13
    "Bonus Non-Convertible Redeemable Preference Shares 3:1",
])
def test_bonus_of_redeemable_preference_shares_is_not_price_moving(subject):
    acts = parse_subject(subject)
    assert [a["action_type"] for a in acts] == ["OTHER"]
    assert acts[0]["note"].startswith("NON_PRICE:")
    assert acts[0]["num"] is None and acts[0]["den"] is None


def test_bonus_and_split_with_face_value_wording():
    acts = {a["action_type"]: a for a in parse_subject("Bonus 1:1 / Face Value Split From 10/- To Face Value 2/-")}  # SHARONBIO
    assert (acts["SPLIT"]["num"], acts["SPLIT"]["den"]) == (2.0, 10.0)
    assert (acts["BONUS"]["num"], acts["BONUS"]["den"]) == (1.0, 1.0)
