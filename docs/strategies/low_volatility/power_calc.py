"""Power arithmetic for the low_volatility pre-registration draft (stage 1). Standard library only. Reads NO data and no database: every input below is an ASSUMPTION or a
number from the stage 1 counts study (697 modelled entries 2016-2026, 5.4 a month, about 5.4 per monthly cohort), and is printed with the result. No return of this strategy
has been computed.

Method: as docs/strategies/near_52w_high/power_calc.py (normal approximation to the one-sided test of H0: mean paired net-R difference <= 0).
  SE = sd_pair / sqrt(n_trades / DEFF); power = Phi(edge / SE - c); MDE80 = (c + z_0.80) x SE.
c = 2.2 is the F9-fitted critical value of the monthly dual-block rule for ONE strategy (docs/F9_POWER_RESULTS.md). c = 2.8 is an ASSUMED value for the joint Max-T over the
K = 4 family (2.2 plus the shift from 1.645 to 2.24, the Bonferroni critical value for K = 4; the real Max-T is less conservative than Bonferroni, so 2.8 is cautious).
DEFF: the entries of one monthly cohort are made on the same day (same market, same month); DEFF = 5.4 means the cohort behaves as ONE observation (effective sample = the number
of cohorts, about 123 of 130 months). Overlap between cohorts (a 21-session hold against a month of 17 to 23 sessions) adds little beyond that.

Run: py docs/strategies/low_volatility/power_calc.py
"""
from math import sqrt
from statistics import NormalDist

N = NormalDist()
Z80 = N.inv_cdf(0.80)
Z_IDEAL = N.inv_cdf(0.95)                  # 1.645
C_DUAL = 2.2                               # fitted to docs/F9_POWER_RESULTS.md, monthly 81 periods
C_FAMILY = 2.8                             # ASSUMED, K = 4 joint Max-T, dual rule (see the docstring)
N_TRADES = 697                             # stage 1 counts model, 2016 to 2026 (nominal; ignores stops, which would raise it)
SD_PAIR = (0.9, 1.2, 1.5)                  # ASSUMED SD of the paired per-trade net-R difference (nothing measured)
DEFF = (1.0, 2.0, 3.0, 5.4)                # ASSUMED design effect (5.4 = one observation per monthly cohort)


def power(edge: float, sd: float, deff: float, n: int, c: float) -> float:
    return N.cdf(edge / (sd / sqrt(n / deff)) - c)


def mde80(sd: float, deff: float, n: int, c: float) -> float:
    return (c + Z80) * sd / sqrt(n / deff)


def main() -> None:
    print(f"nominal trades {N_TRADES}; z0.80 {Z80:.3f}; ideal c {Z_IDEAL:.3f}; dual-rule c {C_DUAL}; assumed K=4 family c {C_FAMILY}")
    print()
    print("MDE at 80% power (R per trade), then power at 0.15 R and at 0.20 R, for c = dual (K=1) and c = family (K=4)")
    print("sd_pair  DEFF  n_eff | MDE80 dual  MDE80 fam | pow@0.15 dual  fam | pow@0.20 dual  fam")
    for sd in SD_PAIR:
        for d in DEFF:
            row = [mde80(sd, d, N_TRADES, C_DUAL), mde80(sd, d, N_TRADES, C_FAMILY), power(0.15, sd, d, N_TRADES, C_DUAL), power(0.15, sd, d, N_TRADES, C_FAMILY),
                   power(0.20, sd, d, N_TRADES, C_DUAL), power(0.20, sd, d, N_TRADES, C_FAMILY)]
            print(f"{sd:>6.1f} {d:>5.1f} {N_TRADES / d:>6.0f} | {row[0]:>9.3f} {row[1]:>10.3f} | {row[2]:>12.2f} {row[3]:>5.2f} | {row[4]:>12.2f} {row[5]:>5.2f}")
    print()
    print("Expectancy gate (min_expectancy_r 0.15) as a point estimate, sd_trade 1.3 assumed:")
    for d in (1.0, 2.0, 3.0, 5.4):
        se = 1.3 / sqrt(N_TRADES / d)
        print(f"  DEFF {d:.1f}: SE {se:.3f}; chance the estimate is >= 0.15 when the true value is 0: {1 - N.cdf(0.15 / se):.3f}; "
              f"true value needed for the lower 95% bound to exceed 0.15: {0.15 + Z_IDEAL * se:.2f}")


if __name__ == "__main__":
    main()
