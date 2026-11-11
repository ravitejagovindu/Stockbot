"""Power arithmetic for the near_52w_high pre-registration draft (STOP 3). Standard library only. Reads NO data and no database: every input below is an ASSUMPTION or a
number from the STOP 1 / STOP 2 counts model, and is printed with the result. Nothing about any return of this strategy is used (none has been computed).

Method (normal approximation to the one-sided test of H0: mean paired net-R difference <= 0):
  SE      = sd_pair / sqrt(n_trades / DEFF)            sd_pair: SD of one trade's net-R minus the mean net-R of its matched random draws
  shift   = edge / SE                                  the non-centrality of the test statistic at a true edge of ``edge`` R per trade
  power   = Phi(shift - c)                             c = critical value of the registered rule
  MDE80   = (c + z_0.80) x SE                          the smallest true edge detected with 80% power
c = 1.645 is the ideal one-sided 5% test. c = 2.2 is the effective critical value implied by the F9 power study for the monthly dual-block rule (fitted to its table: shift = 12.05 x edge,
c = 2.22), which includes the extra stringency of requiring significance at two block lengths and the liberal-size correction. DEFF is the design effect of overlapping trades
(a trade is open for 40 sessions; about 12 are open at once, so concurrent trades share market, sector and style moves that the matched random draws only partly remove).

Run: py docs/strategies/near_52w_high/power_calc.py
"""
from math import sqrt
from statistics import NormalDist

N = NormalDist()
Z80 = N.inv_cdf(0.80)
Z_IDEAL = N.inv_cdf(0.95)                  # 1.645
C_DUAL = 2.2                               # fitted to docs/F9_POWER_RESULTS.md, monthly 81 periods (see the docstring)
N_TRADES = 786                             # STOP 1 counts model, 2016 to 2026 (nominal; ignores stops, which would raise it)
EDGES = (0.10, 0.15, 0.20, 0.25)
SD_PAIR = (0.9, 1.2, 1.5)                  # ASSUMED SD of the paired per-trade net-R difference (nothing measured)
DEFF = (1.0, 1.5, 2.0, 3.0)                # ASSUMED design effect of overlapping trades


def power(edge: float, sd: float, deff: float, n: int, c: float) -> float:
    se = sd / sqrt(n / deff)
    return N.cdf(edge / se - c)


def mde80(sd: float, deff: float, n: int, c: float) -> float:
    return (c + Z80) * sd / sqrt(n / deff)


def main() -> None:
    print(f"nominal trades {N_TRADES}; z0.80 {Z80:.3f}; ideal c {Z_IDEAL:.3f}; F9-fitted dual-rule c {C_DUAL}")
    print("\nMDE at 80% power (R per trade), then power at 0.15 R and at 0.20 R")
    print("sd_pair  DEFF  n_eff | MDE80 ideal  MDE80 dual | pow@0.15 ideal  dual | pow@0.20 ideal  dual")
    for sd in SD_PAIR:
        for d in DEFF:
            n_eff = N_TRADES / d
            row = [mde80(sd, d, N_TRADES, Z_IDEAL), mde80(sd, d, N_TRADES, C_DUAL),
                   power(0.15, sd, d, N_TRADES, Z_IDEAL), power(0.15, sd, d, N_TRADES, C_DUAL),
                   power(0.20, sd, d, N_TRADES, Z_IDEAL), power(0.20, sd, d, N_TRADES, C_DUAL)]
            print(f"{sd:>6.1f} {d:>5.1f} {n_eff:>6.0f} | {row[0]:>10.3f} {row[1]:>11.3f} | {row[2]:>13.2f} {row[3]:>7.2f} | {row[4]:>13.2f} {row[5]:>7.2f}")
    print("\nTrades needed for 80% power at 0.15 R (sd_pair 1.2), by design effect: ideal c, dual c")
    for d in DEFF:
        need = lambda c: d * ((c + Z80) * 1.2 / 0.15) ** 2     # noqa: E731
        print(f"  DEFF {d:.1f}: {need(Z_IDEAL):.0f} trades (ideal), {need(C_DUAL):.0f} trades (dual rule)")

    # Cross-check: scale the F9 monthly result. F9: shift = 12.05 x edge at 2.6 trades a month over 81 months; signal-to-noise per R scales with sqrt(rate x periods).
    f9_slope = 12.05
    rate_scale = (6.17 / 2.6) * (130 / 81)
    slope = f9_slope * sqrt(rate_scale)
    print(f"\nF9 scaling cross-check: slope {f9_slope} per R x sqrt({rate_scale:.2f}) = {slope:.1f} per R (assumes the same dependence and shorter F9 holds; optimistic for 40-session holds)")
    for e in (0.10, 0.15, 0.20):
        print(f"  power at {e:.2f} R: {N.cdf(slope * e - 2.22):.2f}")
    print(f"  MDE80: {(2.22 + Z80) / slope:.3f} R")

    # What a point-estimate gate (expectancy >= 0.15 R) can and cannot show: false-pass chance when the true expectancy is 0, and the true value needed for a 95% lower bound above 0.15.
    print("\nExpectancy gate as a point estimate (single-strategy net R per trade, sd_trade 1.3 assumed):")
    for d in (1.0, 2.0, 3.0):
        se = 1.3 / sqrt(N_TRADES / d)
        print(f"  DEFF {d:.1f}: SE {se:.3f}; chance the estimate is >= 0.15 when the true value is 0: {1 - N.cdf(0.15 / se):.3f}; true value needed for the lower 95% bound to exceed 0.15: {0.15 + Z_IDEAL * se:.2f}")


if __name__ == "__main__":
    main()
