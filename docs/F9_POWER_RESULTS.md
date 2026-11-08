# F9 power study — results (pre-registered rule applied mechanically)

Design, blocks and decision rule: `docs/F9_PREREGISTRATION.md` (committed before this ran; Amendment 1 on the entry probability also before). Westfall-Young step-down Max-T, studentized circular block bootstrap, FWER alpha 0.05, B = 2,000 draws, K = 6 configs, dual rule (significant at both blocks). Size: 2,000 replications (SE at nominal 0.0049); power: 1,000 replications per cell (SE <= 0.016). Seed 20261108.

## Size (all six configs true nulls)

| frequency | periods | blocks | trades per period | period SD of paired return | size (dual) | single block 1 | single block 2 | within 0.0451-0.0549? |
|---|---|---|---|---|---|---|---|---|
| weekly | 60 | 4 and 8 | 0.60 | 0.855% | 0.0580 | 0.0620 | 0.0700 | NO |
| weekly | 81 | 4 and 8 | 0.60 | 0.865% | 0.0555 | 0.0595 | 0.0670 | NO |
| monthly | 60 | 2 and 3 | 2.60 | 1.831% | 0.0625 | 0.0660 | 0.0705 | NO |
| monthly | 81 | 2 and 3 | 2.59 | 1.744% | 0.0630 | 0.0680 | 0.0665 | NO |

## Power of config 1 (dual rule), by injected edge in R per trade

| frequency | periods | +0.05 R | +0.10 R | +0.15 R | +0.25 R | +0.50 R | observed mean shift at +0.10 R (per period) |
|---|---|---|---|---|---|---|---|
| weekly | 60 | 0.027 | 0.031 | 0.085 | 0.212 | 0.644 | +0.061% |
| weekly | 81 | 0.024 | 0.061 | 0.110 | 0.253 | 0.800 | +0.068% |
| monthly | 60 | 0.060 | 0.139 | 0.319 | 0.718 | 0.998 | +0.289% |
| monthly | 81 | 0.070 | 0.155 | 0.371 | 0.786 | 0.999 | +0.255% |

## Decision (rule fixed in advance: size within 0.05 +/- SE AND power >= 80% at +0.10 R per trade)

| frequency | periods | size | size ok | power at +0.10 R | power ok | acceptable | smallest edge on the grid with >= 80% power |
|---|---|---|---|---|---|---|---|
| weekly | 60 | 0.0580 | no | 0.031 | no | no | none on the grid (max +0.50 R) |
| weekly | 81 | 0.0555 | no | 0.061 | no | no | +0.50 R |
| monthly | 60 | 0.0625 | no | 0.139 | no | no | +0.50 R |
| monthly | 81 | 0.0630 | no | 0.155 | no | no | +0.50 R |

**No design is acceptable under the pre-registered rule.**
