# Entry 5 — Base chi-rotation optimisation to fix WC H-bonds — historical evidence

[Topic head](../../log_atomistic_o3prime.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Entry 5 — Base chi-rotation optimisation to fix WC H-bonds

**Motivation:** Entry 4 introduced a N3–N1 clash at 0.216 nm for AT (FWD=T/REV=A). Entry 4 also left AT (FWD=A/REV=T) slightly off target. GC pairs were already good (0.270–0.297 nm).

**Method:** Each of the 8 base templates (FWD: DA, DT, DG, DC; REV: DA, DT, DG, DC) was rotated rigidly around C1' in template space — a z-axis rotation (in-plane, n-y plane). Backbone atoms (_SUGAR) unchanged. All intra-base atom distances preserved exactly. C1'–N bond length preserved exactly.

Optimisation: joint Nelder-Mead over (θ_FWD, θ_REV) per WC pair type, minimising sum of squared H-bond distance residuals. One representative bp per pair; result is correct for all bp positions by helical symmetry.

**Rotations applied:**
| Template | θ |
|----------|---|
| FWD DA | +36.524° |
| FWD DT | +3.873° |
| FWD DG | +1.973° |
| FWD DC | +1.090° |
| REV DA | +25.811° |
| REV DT | −18.541° |
| REV DG | +1.512° |
| REV DC | +7.735° |

**WC H-bond distances after optimisation:**
| Pair | H-bond | Before Entry 5 (nm) | After Entry 5 (nm) | Target (nm) |
|------|--------|---------------------|---------------------|-------------|
| GC (FWD G, REV C) | O6–N4 | 0.297 | 0.288 | 0.287 | ✓ |
| GC (FWD G, REV C) | N1–N3 | 0.289 | 0.292 | 0.293 | ✓ |
| GC (FWD G, REV C) | N2–O2 | 0.270 | 0.287 | 0.287 | ✓ |
| GC (FWD C, REV G) | N4–O6 | 0.296 | 0.289 | 0.287 | ✓ |
| GC (FWD C, REV G) | N3–N1 | 0.289 | 0.289 | 0.293 | ✓ |
| GC (FWD C, REV G) | O2–N2 | 0.281 | 0.289 | 0.287 | ✓ |
| AT (FWD A, REV T) | N6–O4 | 0.313 | 0.290 | 0.290 | ✓ |
| AT (FWD A, REV T) | N1–N3 | 0.283 | 0.300 | 0.300 | ✓ |
| AT (FWD T, REV A) | O4–N6 | 0.265 | 0.294 | 0.290 | ✓ |
| AT (FWD T, REV A) | N3–N1 | 0.216 | 0.296 | 0.300 | ✓ |

All H-bonds within 0.007 nm of target. The AT (FWD=T/REV=A) clash (0.216 nm) is fully resolved.

**C1'–N distances unchanged** (rotation around C1' preserves all distances from C1'):
- FWD: DA=1.456 Å, DT=1.456 Å, DG=1.453 Å, DC=1.474 Å
- REV: DA=1.465 Å, DT=1.440 Å, DC=1.474 Å, DG=1.453 Å

**609 tests pass ✓**

---

## Big-picture review of all entries:
1. Root cause (Entry 1): 1ZEW 36°/bp vs NADOC 34.3°/bp caused frame-origin mismatch.
2. First fix attempt: re-extract in NADOC frames → still 91° (single-template architecture can't fix it without changing P or O3' explicitly).
3. Actual fix (Entry 2): Shift P_tmpl by 0.65 Å along C3'→P direction to target correct inter-residue C3'–P distance. This is a deviation from the crystallographic P position but is correct for the template model's geometry.
4. Entry 3 (OP1/OP2): ΔP-shift approach works. C1'-referenced extraction also planned.
5. Entry 4: OP1/OP2 fixed via ΔP shift. C1'–N bonds fixed via C1'-referenced extraction. GC H-bonds improved. AT (FWD=T/REV=A) N3–N1 clashing at 0.216 nm (regression).
6. Entry 5 (this session): Rigid z-rotation of each base template around C1'. All 10 WC H-bonds within 0.007 nm of target. AT clash resolved. 609 tests pass.

---
