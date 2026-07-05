# exp37 — CanDo-FEM skip-vs-twist landscape (workspace/3x6x400_Sq_test.nadoc)

18 helices, best-guess 180 skips (10/helix). Solver: FINE (nonlinear), n_steps=20. Best-guess twist **14.31°**, rmsd **0.442 nm**.

## Uniform density sweep (all helices = count)

| count | total skips | twist° | bend° | rmsd nm | dev_max nm |
|--:|--:|--:|--:|--:|--:|
| 4 | 72 | 46.475 | 0.373 | 1.1239 | 2.7036 |
| 6 | 108 | 36.096 | 0.291 | 0.8321 | 2.0231 |
| 8 | 144 | 25.308 | 0.269 | 0.5806 | 1.4065 |
| 9 | 162 | 19.82 | 0.254 | 0.4895 | 1.138 |
| 10 | 180 | 14.307 | 0.298 | 0.4415 | 0.9489 |
| 11 | 198 | 8.792 | 0.267 | 0.4501 | 0.8669 |
| 12 | 216 | 3.305 | 0.412 | 0.5117 | 0.9086 |
| 13 | 234 | -2.127 | 0.378 | 0.61 | 1.0604 |
| 14 | 252 | -7.478 | 0.298 | 0.7297 | 1.2854 |
| 15 | 270 | -12.732 | 0.347 | 0.8618 | 1.5493 |
| 16 | 288 | -17.873 | 0.534 | 1.0008 | 1.8435 |
| 18 | 324 | -27.709 | 0.465 | 1.2893 | 2.4869 |
| 20 | 360 | -36.913 | 0.33 | 1.5841 | 3.1477 |
| 24 | 432 | -53.188 | 0.692 | 2.1758 | 4.4806 |
| 28 | 504 | -66.721 | 0.887 | 2.7617 | 5.805 |
| 32 | 576 | -77.872 | 1.463 | 3.3373 | 7.1112 |
| 36 | 648 | -87.096 | 1.805 | 3.9026 | 8.394 |
| 40 | 720 | -94.557 | 2.123 | 4.4565 | 9.6528 |

**Uniform twist→0 crossing ≈ 12.61 skips/helix**

## Per-helix twist authority (∂ vs skip count, near best-guess)

| helix | ∂twist/∂skip (°) | ∂rmsd/∂skip (nm) |
|---|--:|--:|
| h_XY_1_0 | -0.520 | 0.0123 |
| h_XY_1_1 | -0.513 | 0.0042 |
| h_XY_1_2 | -0.495 | -0.0012 |
| h_XY_1_3 | -0.486 | -0.0012 |
| h_XY_1_4 | -0.469 | 0.0043 |
| h_XY_1_5 | -0.465 | 0.0124 |
| h_XY_2_3 | -0.313 | 0.0284 |
| h_XY_0_3 | -0.279 | 0.0282 |
| h_XY_0_2 | -0.274 | 0.0282 |
| h_XY_2_2 | -0.272 | 0.0287 |
| h_XY_2_1 | -0.265 | 0.0306 |
| h_XY_0_1 | -0.264 | 0.0304 |
| h_XY_2_4 | -0.246 | 0.0309 |
| h_XY_0_4 | -0.236 | 0.0307 |
| h_XY_2_5 | -0.174 | 0.0356 |
| h_XY_0_0 | -0.143 | 0.0356 |
| h_XY_0_5 | -0.125 | 0.0357 |
| h_XY_2_0 | -0.035 | 0.0362 |

## Joint twist+deviation optimum → **analytic-1**

- twist **-0.368°** (from 14.31°), bend 1.662°, rmsd 0.4985 nm, 208 skips (best-guess 180).
- marks written to `results/optimized_marks.json` (NOT applied to the design).

## RECOMMENDED sub-1° config (spread — physical)

`12base+6@13`: **12 skips/helix on all 18 helices + 13 on the middle row** (h_XY_1_0…1_5, the
6 highest twist-authority helices). Verified FINE solve:

| | twist° | bend° | rmsd nm | total skips |
|---|--:|--:|--:|--:|
| best-guess (autorefine) | 14.31 | 0.30 | 0.44 | 180 |
| **recommended spread**  | **0.37** | **0.33** | **0.54** | **222** |
| concentrated auto (1 helix @38) | −0.37 | 1.66 | 0.50 | 208 |

Marks: `results/optimized_spread.json` (NOT applied to the design). Full sweep in
`results/stage2_spread.csv`; twist crosses 0 between 6 and 8 helices bumped to 13.

### Root cause of the ~10-15° floor
The live autorefine minimises deviation RMSD, whose minimum sits at ~10 skips/helix (twist +14°).
The twist optimum is ~12.6 skips/helix. Deviation-min ≠ twist-min → a deviation-driven refiner
structurally cannot reach twist→0. Nulling twist needs ~+42 skips (12/helix + middle-row 13) and
costs ~0.10 nm of RMSD (0.44→0.54) — an intrinsic twist↔deviation tradeoff, not a solver failure.
