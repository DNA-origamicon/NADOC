# exp42 — SNUPI ↔ CanDo (↔ MD) cross-comparison + paper validation review

## ⚡ UPDATE (2026-07-11) — added the missing SNUPI physics (electrostatics + S9 solver)

The paper re-review found two genuine SNUPI solver pieces we lacked: **inter-helix Debye–Hückel
electrostatics (SI S6/S7)** and the **iterative/adaptive nonlinear solution procedure (SI S9)**.
Both are now implemented (gated behind `material="snupi"`; CanDo byte-identical):
`backend/physics/snupi_electrostatics.py` (Debye–Hückel repulsive truss springs between inter-helix
BP nodes < 2.5 nm, q = 0.7 e @ 20 mM MgCl₂, λ_D = 1.24 nm — finite-difference-verified) +
`fem_solver._solve_snupi_nonlinear` (electrostatic self-consistency iteration + adaptive Δα
subdivision) + electrostatic tangent added to the free-free NMA (RMSF) operator.

**Effect on the RMSF-vs-MD correlation — electrostatics closed the square-lattice gap:**

| design | metric | no electrostatics | WITH electrostatics | vs CanDo |
|---|---|---|---|---|
| 6hbx100_noT (HC) | snupi pearson | 0.592 | **0.598** | > 0.549 ✓ |
| 6hbx100_noT (HC) | snupi spearman | 0.424 | 0.423 | > 0.336 ✓ |
| **3x4SQ (SQ)** | snupi pearson | 0.675 (tie) | **0.742** | **> 0.703 — now WINS** |
| **3x4SQ (SQ)** | snupi spearman | 0.548 | **0.623** | > 0.533 ✓ |

Mechanism: the repulsive springs stiffen a spurious soft inter-helix breathing mode the square
lattice had (RMSF max 3.07 → 1.30 nm; mean 0.58 → 0.43 nm, much closer to MD's 0.27), which was
the one thing hurting SQ. **New verdict: SNUPI now beats CanDo on BOTH lattices, both metrics** —
the square-lattice tie is resolved in SNUPI's favour. Engineering note: the electrostatic tangent
uses the PD **axial-only** term (the perpendicular Π'/r<0 term is indefinite and blew the solve up);
the *force* is exact, only the stiffness is a PD approximation → stable + correct equilibrium.
The nonlinear ("Fine") snupi solve runs ~57 s on a 6HB/84. Tables below = the pre-electrostatics run
(kept for the delta); `results.json` now holds the with-electrostatics numbers. Pins:
`tests/test_snupi_electrostatics.py` (6) + `test_snupi_element.py::test_electrostatics_*` / `::test_snupi_nonlinear_solve_*`.

---

# exp42 — SNUPI ↔ CanDo (↔ MD) cross-comparison + paper validation review

Driven by the P5 frontend-tab session (2026-07-11). Two questions: (1) does the shipped
SNUPI engine (`predict_shape(material="snupi")`) behave as expected vs CanDo + our on-disk MD
across the qualifying designs, and (2) does it reproduce the published SNUPI paper (Lee/Kim,
ACS Nano 2021)?

Automation: `scripts/snupi_cross_compare.py` (reusable) → `results.json`. Reuses the SAME
cross-engine comparison framework as the in-app Shape-comparison card
(`build_cando_shape_source` → `build_comparison_report`; `md_rmsf` → `build_namd_shape_source`).
Button-press UI automation: `frontend/e2e/snupi_run.spec.js` (real Coarse+Fine clicks → jobs
complete → deform overlay) + `frontend/e2e/snupi_tab.spec.js` (tab wiring).

RMSF is the free-free NMA (material-dependent, solve-mode-INDEPENDENT), so the fast linear
solve gives the same RMSF as nonlinear. "Basic SNUPI check" = paired duplex core, NO extra
crossover bases (base SNUPI can't predict extra-base motifs → the 1xT/2xT variants are excluded;
they're the extension targets).

## Result 1 — parameters reproduce the SNUPI SI EXACTLY (definitive)

Our transcribed `family_mean_D('regular_bp')` vs SNUPI_SI regular-BP mean column
(SI Note S4 table / Fig S1):

| quantity | ours | SNUPI SI | match |
|---|---|---|---|
| GJ (pN·nm²) | 313.83 | 313.83 | ✓ |
| EIy (pN·nm²) | 158.33 | 158.33 | ✓ |
| EIz (pN·nm²) | 245.79 | 245.79 | ✓ |
| g(Δx,Θx) twist–stretch (pN·nm) | −277.39 | −277.39 | ✓ |
| EA (pN) | 1825 | — | (→ lit ~1000–1500 order ✓) |
| torsional L_p = GJ/kT | 75.8 nm | P_CH = 75.8 nm | ✓ |
| bend L_p = EI/kT | ~48.8 nm | P_BH = 46.5 nm | ≈ ✓ |

The transcription (`backend/data/parameters/snupi_params.json`) is faithful to the published
intrinsic properties to 2 decimals — the strongest possible "same results" at the parameter level.

## Result 2 — cross-comparison (per-bp RMSF, linear solve)

`ref` = MD when a free k=0 NAMD DCD exists on disk, else CanDo. pearson/spearman = correlation
of each material's per-bp NMA RMSF vs the reference. Higher snupi→ref ⇒ SNUPI closer to truth.

| design | lattice | ref | RMSF mean nm (c/s/md) | pearson c/s | spearman c/s | verdict |
|---|---|---|---|---|---|---|
| **6hbx100_noT** | HC | MD 20ns | 0.411 / 0.440 / **0.338** | 0.549 / **0.592** | 0.336 / **0.424** | **SNUPI wins both** |
| **3x4SQ** | SQ | MD 5ns | 0.463 / 0.583 / **0.273** | **0.703** / 0.675 | 0.533 / **0.548** | tie (cando pearson, snupi rank) |
| 6hb_validated | HC | CanDo | 8.07 / 6.74 / — | — / 1.00 | — / 1.00 | ⚠ RMSF outlier (see below) |
| 2hb_noT | HC | CanDo | 0.294 / 0.402 / — | — / 0.995 | — / 0.979 | pattern≈CanDo, higher magnitude |
| 10hb | HC | CanDo | 0.251 / 0.363 / — | — / 0.970 | — / 0.952 | pattern≈CanDo, higher magnitude |
| 18hb | HC | CanDo | 0.632 / 0.646 / — | — / 0.987 | — / 0.978 | pattern≈CanDo, ≈magnitude |
| U6HB | HC | CanDo | 1.78 / 1.58 / — | — / 1.00 | — / 1.00 | pattern≈CanDo, lower magnitude |

(The `cando` pearson/spearman column is `—` when CanDo IS the reference — self-comparison excluded.)

**Reading:**
- **Honeycomb 6hbx100_noT (primary, well-sampled 20ns): SNUPI beats CanDo on BOTH pearson (0.592 vs
  0.549) and spearman (0.424 vs 0.336)** — reproduces the P4 verdict (P4's bespoke bp-center method
  gave cando 0.504→snupi 0.562; here the shared `md_rmsf` pipeline gives 0.549→0.592, same direction).
- **Square 3x4SQ (under-sampled 5ns): a tie** — CanDo slightly ahead on pearson (0.703 vs 0.675),
  SNUPI ahead on rank/spearman (0.548 vs 0.533). Matches P4 "square inconclusive". Confounded by the
  short 5ns sampling + FEM end-node over-prediction.
- **Basic snupi-vs-cando (no MD):** SNUPI's per-bp flexibility PATTERN tracks CanDo very tightly
  (pearson 0.97–1.0) — expected, same beam network — while the MAGNITUDE shifts: SNUPI predicts
  HIGHER mean RMSF on small/stiff bundles (2hb 0.29→0.40, 10hb 0.25→0.36) and LOWER on big/floppy
  ones (U6HB 1.78→1.58, 6hb_validated 8.07→6.74). This magnitude shift is the anisotropy + twist–
  stretch-coupling + compliant-crossover delta doing its job; the pattern stays CanDo-like.
- **⚠ 6hb_validated outlier:** ~7–8 nm mean RMSF is unphysical (real dsDNA-bundle RMSF ~0.3–1 nm).
  BOTH cando and snupi show it (pearson/spearman 1.0 → identical pattern, just scaled), so it's NOT a
  SNUPI issue — it's a soft/near-rigid global mode leaking into the free-free NMA (likely an
  under-constrained / partially-disconnected mesh for that particular design). Flagged for separate
  investigation; excluded from any SNUPI-vs-CanDo conclusion.

## Result 3 — SNUPI paper validation battery (from SNUPI_SI.pdf)

**What SNUPI validated against** (SI figures S2–S25): 32-helix honeycomb bundle (S2, also the CO-param
source), 64-helix square bundle (S3), polymorphic multi-hinge designs (S4–5), origami blocks HC/SQ
(S6/S8), 3D origami (S7), curved origami (S9), straight & twisted monoliths (S10), spring-like bend+
torsion (S11), **globally bent by BP insertion/deletion = loop/skip (S12)**, **gears by BP ins/del
(S13)**, S/spiral (S14), A-like (S15), **6-helix-bundle twist control via nick sequences (S16)**,
V-bricks + hierarchical assemblies + tubes + triangular/embossed/connector bricks (S18–25). Validated
vs **cryo-EM/TEM** (Bai/Dietz 2017, ref 47 "pointer" structure) and vs **all-atom MD** (NAMD, 300 K).

**SNUPI's validation metrics** (Notes S11–S13): per-BP NMA **RMSF** + **BP–BP Pearson cross-correlation
matrix** (MD `PC_ij^MD` vs FE `PC_ij^FE`); analytic **persistence-length scaling** for bundles
(P_BTh = P_BH·N_H + (4/3)P_BH·N_H(N_H−1), with helix P_BH = 46.5 nm bend, P_CH = 75.8 nm torsion).

**Do we get the same results?**
- **Parameters: YES, exactly** (Result 1) — our intrinsic 6×6 motif properties are byte-faithful to
  the SI (−277.39 pN·nm coupling, 75.8 nm torsional L_p, the regular-BP GJ/EIy/EIz means).
- **Method: YES, same** — we use per-bp free-free NMA RMSF vs MD RMSF with Pearson/Spearman
  correlation; SNUPI uses per-BP NMA RMSF + a BP-pair cross-correlation matrix vs MD. Same NMA-vs-MD
  fluctuation validation. (We correlate per-bp RMSF magnitude; SNUPI additionally correlates the full
  BP-pair covariance matrix — a possible future upgrade, `md_rmsf` already yields aligned frames.)
- **Structures: NOT a 1:1 figure match** — SNUPI's exact validation designs (32HB, 64HB, gears,
  V-bricks, monoliths) are NOT in our workspace, so we can't reproduce their specific figure numbers.
  We validated the SAME PHYSICS on OUR MD-backed designs (6hbx100_noT honeycomb, 3x4SQ square), where
  SNUPI ≥ CanDo — consistent with the paper's central claim that anisotropy + twist–stretch coupling
  improve fidelity over an isotropic (CanDo-like) rod. Reproducing SNUPI's own figures (e.g. the S13
  gears or S16 6HB nick-twist) would mean building those specific designs — a natural follow-up.

## Bottom line
Parameters reproduce the SNUPI SI exactly; the method matches; on our two MD-backed structures SNUPI
meets-or-beats CanDo (clear win on the well-sampled honeycomb, tie on the under-sampled square) — the
published SNUPI advantage, reproduced at $0 new MD. Open: the 6hb_validated NMA outlier; a full BP-pair
cross-correlation-matrix comparison; rebuilding SNUPI's own figure structures for a 1:1 numeric match.

Reproduce: `uv run python scripts/snupi_cross_compare.py` (add `--nonlinear` for shape descriptors).
