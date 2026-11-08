"""Apply the pre-registered decision rule (docs/F9_PREREGISTRATION.md) to data/f9/power_results.json and write docs/F9_POWER_RESULTS.md."""
import json, math
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]

def main():
    res = json.loads((ROOT / "data/f9/power_results.json").read_text())
    SIZE_LO, SIZE_HI, MIN_POWER, EDGE_OF_INTEREST = 0.05 - math.sqrt(0.05 * 0.95 / 2000), 0.05 + math.sqrt(0.05 * 0.95 / 2000), 0.80, 0.10
    cells = {(r["freq"], r["n_periods"], r["edge"]): r for r in res}
    L = ["# F9 power study — results (pre-registered rule applied mechanically)", "",
         "Design, blocks and decision rule: `docs/F9_PREREGISTRATION.md` (committed before this ran; Amendment 1 on the entry probability also before). "
         f"Westfall-Young step-down Max-T, studentized circular block bootstrap, FWER alpha 0.05, B = 2,000 draws, K = 6 configs, dual rule (significant at both blocks). "
         f"Size: 2,000 replications (SE at nominal {math.sqrt(0.05*0.95/2000):.4f}); power: 1,000 replications per cell (SE <= 0.016). Seed 20261108.", "",
         "## Size (all six configs true nulls)", "", "| frequency | periods | blocks | trades per period | period SD of paired return | size (dual) | single block 1 | single block 2 | within 0.0451-0.0549? |", "|---|---|---|---|---|---|---|---|---|"]
    verdict = {}
    for f in ("weekly", "monthly"):
        for n in (60, 81):
            r = cells[(f, n, 0.0)]
            ok = SIZE_LO <= r["size_any_dual"] <= SIZE_HI
            verdict[(f, n)] = {"size_ok": ok, "size": r["size_any_dual"]}
            L.append(f"| {f} | {n} | {r['blocks'][0]} and {r['blocks'][1]} | {r['trades_per_period']:.2f} | {r['mean_period_sd']*100:.3f}% | {r['size_any_dual']:.4f} | {r['size_any_block1']:.4f} | {r['size_any_block2']:.4f} | {'yes' if ok else 'NO'} |")
    L += ["", "## Power of config 1 (dual rule), by injected edge in R per trade", "", "| frequency | periods | " + " | ".join(f"+{e:.2f} R" for e in (0.05, 0.10, 0.15, 0.25, 0.50)) + " | observed mean shift at +0.10 R (per period) |", "|---|---|---|---|---|---|---|---|"]
    for f in ("weekly", "monthly"):
        for n in (60, 81):
            row = []
            for e in (0.05, 0.10, 0.15, 0.25, 0.50):
                r = cells[(f, n, e)]
                row.append(f"{r['cfg1_sig_dual']:.3f}")
                if e == EDGE_OF_INTEREST:
                    verdict[(f, n)]["power"] = r["cfg1_sig_dual"]; verdict[(f, n)]["shift"] = r["mean_observed_shift_cfg1_minus_nulls"]
            mde = next((e for e in (0.05, 0.10, 0.15, 0.25, 0.50) if cells[(f, n, e)]["cfg1_sig_dual"] >= MIN_POWER), None)
            verdict[(f, n)]["mde"] = mde
            L.append(f"| {f} | {n} | " + " | ".join(row) + f" | {verdict[(f, n)]['shift']*100:+.3f}% |")
    L += ["", "## Decision (rule fixed in advance: size within 0.05 +/- SE AND power >= 80% at +0.10 R per trade)", "", "| frequency | periods | size | size ok | power at +0.10 R | power ok | acceptable | smallest edge on the grid with >= 80% power |", "|---|---|---|---|---|---|---|---|"]
    acc = []
    for f in ("weekly", "monthly"):
        for n in (60, 81):
            v = verdict[(f, n)]; pok = v["power"] >= MIN_POWER; a = v["size_ok"] and pok
            if a: acc.append((f, n))
            L.append(f"| {f} | {n} | {v['size']:.4f} | {'yes' if v['size_ok'] else 'no'} | {v['power']:.3f} | {'yes' if pok else 'no'} | {'**YES**' if a else 'no'} | {('+%.2f R' % v['mde']) if v['mde'] else 'none on the grid (max +0.50 R)'} |")
    L += ["", ("Acceptable designs: " + ", ".join(f"{f} {n}" for f, n in acc)) if acc else "**No design is acceptable under the pre-registered rule.**"]
    (ROOT / "docs/F9_POWER_RESULTS.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
