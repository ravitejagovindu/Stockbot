"""Shared sector rule (shared-rules C1): every unmapped symbol is its OWN sector, UNMAPPED:<SYMBOL>, in backtest, paper and live (one implementation, stockbot/data/sector_map.py)."""
import pytest

from stockbot.config.shared import load_shared_config
from stockbot.data import sector_map as SM
from stockbot.engine.decide import EventData
from stockbot.risk.arbitration import OpenPos, Proposal, arbitrate
from stockbot.risk.caps import CapLimits

CFG = load_shared_config()
LIMITS = CapLimits(CFG.portfolio_risk.max_concurrent_positions, CFG.portfolio_risk.max_total_portfolio_risk_pct, CFG.portfolio_risk.max_sector_exposure_pct)
EQUITY = 1_000_000.0
POS = 80_000.0          # 8% of equity: one fits a 15% sector cap, two do not
RISK = 5_000.0          # 0.5% of equity: nowhere near the 15% total-risk cap


def test_mapped_symbol_keeps_its_sector_and_is_case_insensitive():
    assert SM.sector_for("RELIANCE") == "ENERGY" == SM.sector_for("reliance") == SM.sector_for(" Reliance ")
    assert SM.is_mapped("HDFCBANK") and not SM.is_mapped("NON_EXISTENT_TICKER_XYZ")


def test_unmapped_symbol_is_its_own_sector():
    a, b = SM.sector_for("NON_EXISTENT_TICKER_XYZ"), SM.sector_for("OTHER_UNMAPPED_ABC")
    assert a == "UNMAPPED:NON_EXISTENT_TICKER_XYZ" and b == "UNMAPPED:OTHER_UNMAPPED_ABC" and a != b
    assert SM.sector_for("non_existent_ticker_xyz") == a                 # same symbol, same key, whatever the case
    assert SM.UNMAPPED_PREFIX == "UNMAPPED:" and "UNKNOWN" not in a


def test_blank_or_unknown_csv_sectors_count_as_unmapped(monkeypatch):
    monkeypatch.setattr(SM, "_load", lambda: {"AAA": "", "BBB": "UNKNOWN", "CCC": "IT"})
    assert SM.sector_for("AAA") == "UNMAPPED:AAA" and SM.sector_for("BBB") == "UNMAPPED:BBB" and SM.sector_for("CCC") == "IT"
    assert not SM.is_mapped("AAA") and not SM.is_mapped("BBB") and SM.is_mapped("CCC")


def test_sector_lookup_is_the_one_mapping_for_all_paths():
    lk = SM.SectorLookup()
    assert lk.get("RELIANCE") == "ENERGY" and lk.get("NON_EXISTENT_TICKER_XYZ") == "UNMAPPED:NON_EXISTENT_TICKER_XYZ"
    assert lk.get("NON_EXISTENT_TICKER_XYZ", "ignored default") == "UNMAPPED:NON_EXISTENT_TICKER_XYZ"          # never falls back to None or to the caller's default
    from stockbot.live import runner
    assert runner.SectorLookup is SM.SectorLookup                          # live and paper use the same class; the backtest wiring imports it from here too


def _admit(symbols, lookup, open_positions=()):
    props = [Proposal("s", sym, lookup.get(sym), POS, RISK, float(len(symbols) - i)) for i, sym in enumerate(symbols)]
    return {d.symbol: d for d in arbitrate(props, limits=LIMITS, equity=EQUITY, open_positions=open_positions)}


def test_sector_cap_does_not_pool_unmapped_names():
    lk = SM.SectorLookup()
    unmapped = [f"UNMAPPED_NAME_{i}" for i in range(6)]
    got = _admit(unmapped, lk)
    assert all(d.accepted for d in got.values())                            # six separate sectors of 8% each: none blocked by the sector cap (before: the second one was)


def test_sector_cap_still_applies_to_a_mapped_sector():
    lk = SM.SectorLookup()
    banks = [s for s, sec in SM._load().items() if sec == "FINANCIALS"][:3]
    got = _admit(banks, lk)
    assert [got[s].accepted for s in banks] == [True, False, False] and "sector_FINANCIALS" in got[banks[1]].reason


def test_a_mapped_sector_does_not_absorb_unmapped_names():
    lk = SM.SectorLookup()
    bank = next(s for s, sec in SM._load().items() if sec == "FINANCIALS")
    held = [OpenPos(bank, "FINANCIALS", POS, RISK, "s")]
    got = _admit(["UNMAPPED_NAME_A", "UNMAPPED_NAME_B"], lk, open_positions=held)
    assert all(d.accepted for d in got.values())


def test_position_and_total_risk_caps_are_unchanged_for_unmapped_names():
    lk = SM.SectorLookup()
    names = [f"UNMAPPED_NAME_{i:02d}" for i in range(14)]
    got = _admit(names, lk)
    assert sum(d.accepted for d in got.values()) == 12 and CFG.portfolio_risk.max_concurrent_positions == 12 and got[names[12]].reason == "BLOCKED_BY_RISK" and not got[names[13]].accepted
    big = [Proposal("s", n, lk.get(n), POS, 80_000.0, 20.0 - i) for i, n in enumerate(names[:4])]          # 8% risk each: total-risk cap 15% admits one
    out = arbitrate(big, limits=LIMITS, equity=EQUITY)
    assert [d.accepted for d in out] == [True, False, False, False] and "total_risk" in out[1].reason and CFG.portfolio_risk.max_total_portfolio_risk_pct == 15.0


def test_backtest_path_gets_the_same_sector_keys_through_decide():
    """decide() reads ``event_data.sectors.get(symbol)``; with the shared lookup the sector of an unmapped symbol is its own key (backtest and paper wiring)."""
    ev = EventData(sectors=SM.SectorLookup())
    assert ev.sectors.get("NON_EXISTENT_TICKER_XYZ") == "UNMAPPED:NON_EXISTENT_TICKER_XYZ" and ev.sectors.get("TCS") == SM.sector_for("TCS")


def test_no_live_path_still_calls_the_pooled_bucket_UNKNOWN():
    import inspect
    from stockbot.live import runner
    assert '"UNKNOWN"' not in inspect.getsource(runner) and "capped bucket (UNKNOWN)" not in inspect.getsource(runner)
    assert '"UNKNOWN"' not in inspect.getsource(SM).replace('("", "UNKNOWN")', "")
