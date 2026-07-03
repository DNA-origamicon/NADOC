# exp36 — CanDo FEM validation (reference-data pipeline)

Reference-data collection + analysis for the native CanDo-replica FEM shape predictor
(see `memory/project_cando_fem.md`). CanDo is the experimentally-validated continuum-FE
tool; we submit the NADOC validation battery to the real CanDo web service and analyse
the returned atomic models, so the future NADOC-FEM can be calibrated to reproduce them.

## Scripts
- **`gen_cando_battery.py`** — regenerates the 6 first-wave designs into
  `workspace/cando validation/` (6HB honeycomb, 210 bp, single scaffold; `.nadoc` +
  `.cadnano.json` + `_manifest.json` + `EXPECTED_VALUES.md`). Pipeline: create_bundle →
  auto_scaffold(seamed) → auto_crossover → auto_break → add_twist/add_bend →
  apply_loop_skip_deformations → export.
- **`analyze_cando_pdb.py`** — analyses a CanDo multi-model atomic PDB → global bend
  angle + radius of curvature + planarity + contour + RMSF availability, from MODEL 1.
  `uv run python analyze_cando_pdb.py <pdb> --expect-bend 90 --expect-R 45.5 [--dump-centerline out.txt]`

## CanDo output format (learned from 05_bend_90)
- Atomic-model ZIP = `structure_multimodel.pdb` + 3 PNG views.
- **31 MODELS**: MODEL 1 = full assembled equilibrium structure (all in chain A, ~1264
  nucleotides = 1 C1'/bp, 40k atoms); MODELS 2–31 = per-strand split. Parse **MODEL 1**.
- **B-factors are ZERO** in the atomic PDB → no RMSF here. Flexibility needs NMA enabled
  on submission and likely a SEPARATE output (coarse/flexibility file), not the atomic PDB.
- Coordinates in **Ångström**; contour ≈ design (210 bp × 0.34 = 71.4 nm).

## Robust bend measurement (A9-safe)
Two geometrically-exact estimators on the ordered cross-section-centroid centerline —
**arc-span** and **chord+sagitta** — which must agree (0.25° on 05). Estimators tried
and DISCARDED as non-robust: turning-angle integral (blows up on centerline jitter →
788°), straight-axis slab binning (mis-slices a curved arc → biased low, 42°). Order the
centerline by polar angle about the circle-fit center (monotonic for any planar arc);
NOT by projection onto a straight PCA axis.

## Results

### 05_bend_90 — FINAL (honeycomb, lattice-matched, received 2026-07-03)
| quantity | NADOC analytic (ideal) | CanDo honeycomb | (square, wrong) |
|---|---|---|---|
| bend angle | 90.0° | **85.8°** (span 85.7 / sagitta 86.0) | 72.5° |
| radius R | 45.5 nm | **46.4 nm** | 54.6 nm |
| contour | 71.4 nm | 70.3 nm ✓ | 70.5 nm |
| % of ideal | — | **95%** | 81% |
| planarity λ3/λ2 | — | 0.147 (planar ✓) | 0.102 |

Atomic PDB (85.7°/46.4 nm) and coarse BILD (86.0°/46.3 nm) agree to 0.3°.
**RMSF** (`structure_NMA_RMSF.txt`, 1264 nodes): min 0.498, max 1.365, mean 0.707 nm;
ends 1.26/1.33 nm (floppy), interior min 0.50 nm (stiff) — sensible profile.

**Finding: with matched honeycomb lattice, CanDo agrees with the NADOC analytic to ~5% on
bend (85.8° vs 90°) and ~2% on radius (46.4 vs 45.5 nm).** The earlier 19% gap was almost
entirely a LATTICE ARTIFACT (design submitted as square → hex→rect remap of moment-arms),
NOT continuum relaxation. The residual ~4° (86° vs 90°) IS the genuine continuum-relaxation
signal — small for a gentle bend; expect it larger on 06_bend_180 (hairpin, R≈23 nm).
**Lesson: the CanDo submission lattice must match the design's — always confirm
`readme.txt` "File type" against the design.** NADOC-FEM target for 05 = ~86°.

Pending CanDo submissions: 01 (control), 02/03/04 (twist), 06 (hairpin).

### ⚠ LATTICE CONFOUND — 05 was solved as SQUARE, our design is HONEYCOMB
The coarse ZIP (`05_bend_90.zip`) `readme.txt` says **File type: square**. The `.inp`
node cross-section is a clean 3×2 **rectangle** (x∈{33.8,36.0,38.2}, z∈{−33.8,−31.5},
2.2 nm) — NOT NADOC's honeycomb **hexagon** (middle column staggered ±1.13 nm, 2.25 nm nn).
caDNAno legacy JSON stores no lattice type, so **CanDo used the submission-form setting
(square)**. Our export is correct (self-detects honeycomb, scaf-array 252 = 12×21). The
hex→rect remap shifts the bend moment-arms (~1.95 nm hex col pitch vs 2.2 nm square,
~10–13%), so **72.5° is NOT a clean honeycomb comparison to the 90° honeycomb analytic**.
FIX: re-submit selecting **honeycomb** in the CanDo form (or regenerate the battery on
SQUARE lattice for an unambiguous single-lattice handshake). The 0.81 efficiency above is
provisional pending a lattice-matched run.

### CanDo output package (two ZIPs per submission)
- `*_atomic.zip`: `structure_multimodel.pdb` (MODEL 1 = full; 2–31 per-strand) + PNGs.
  **B-factors zero** (no RMSF here).
- `*.zip` (coarse/mechanical): **`structure_NMA_RMSF.txt`** (per-node RMSF nm — HERE is the
  flexibility data, 1264 nodes, 0.50–1.35 nm, ends floppy/interior stiff),
  `structure_NLSA_deformedShape.bild` (coarse bp-node shape — cleanest geometry, gave
  R=54.6/bend 72.8°, matches atomic to 0.3°), **`structure_NLSA.inp`** (the Abaqus deck),
  `structure_NMA_RMSF.bild`, `*HeatMapRange*`, PNGs, `readme.txt` (run params).

### CanDo FE model — decoded from `structure_NLSA.inp` (lattice-independent physics)
- Nodes = base pairs (1/bp). Elements: **B31H** (hybrid Timoshenko beam) for dsDNA,
  **NICKDNA** (nicked, softer), **HJ** (crossover beams), **CONN3D2** nonlinear connectors
  for ssDNA. Transverse shear ~rigid (55e6) → behaves ~Euler-Bernoulli.
- Beam section (coords in **Å**): BDNA `A=397.61, I=8313.62, J=33254.47`, `E=2.7665, G=1.3833`
  → **EA=1100 pN, EI=230 pN·nm², GJ=460 pN·nm²** (published constants, confirmed verbatim).
  G=E/2 → ν=0. NICKDNA: I,J ÷100 (bend/torsion ×100 softer), A retained (0.01 nick factor).
- **PRE-STRESS RECIPE (answers Phase-0 open Q1):** encoded as a **TEMPERATURE eigenstrain
  field** (`*Initial Conditions, type=TEMPERATURE`) + prescribed displacements to bring
  crossovers into register. Solver = staged nonlinear Abaqus: `InitialDisp` (nlgeom) →
  `HJgen` (activate junctions) → `Unloding1–6` (nlgeom, UNSYMM, INC=200; `*Temperature,
  op=mod` releases the eigenstrain in stages) → stabilized `DummyStep` → `NMA` perturbation
  (→ RMSF). This is the exact Phase-2/3 blueprint: temperature-driven initial strain +
  geometrically-nonlinear staged relaxation.
