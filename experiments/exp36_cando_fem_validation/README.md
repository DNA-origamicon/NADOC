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
- **`gen_bend_diagnostics.py`** — the BEND-GAP diagnostic battery (§4): 15 designs
  (`B1_*`…`B5_*`) that isolate why the FEM converts only ~68% of a programmed bend.
  Adds staple-crossover **thinning** (by `process_id=="auto_crossover"`, keeps the single
  scaffold) + an **off-crossover/off-end mark-relocation** pass
  (`feedback_loopskip_no_crossover_ends`) + clean sequence CSVs. Writes
  `_bend_diagnostics_manifest.json` + `BEND_DIAGNOSTICS_SUBMISSION.md` (submit guide).
- **`fem_bend_diagnostics.py`** — in-code FEM experiments (§5, no CanDo run): baseline
  bend (linear + nonlinear), **dense inter-helix coupling** stress test, and the
  **axial/bend energy partition** on 05 & 06.
- **`analyze_cando_pdb.py`** — analyses a CanDo multi-model atomic PDB → global bend
  angle + radius of curvature + planarity + contour + RMSF availability, from MODEL 1.
  `uv run python analyze_cando_pdb.py <pdb> --expect-bend 90 --expect-R 45.5 [--dump-centerline out.txt]`

## BEND-GAP diagnostic battery (2026-07-03) — `B1_*`…`B5_*`, awaiting CanDo
15 designs in `workspace/cando validation/`, submission guide in
`BEND_DIAGNOSTICS_SUBMISSION.md`. Families: **B1** crossover-density sweep (6HB 90° bend,
staple crossovers 112/56/28/1 — THE key run), **B2** bend-angle series (30/45/60/90/135°),
**B3** length series at fixed R≈45 nm (105/210/420 bp = 45/90/180°), **B4** 2HB+4HB 90°
bends, **B5** square-lattice 6HB bend (confounded by ~149° intrinsic SQ-correction twist —
optional). All: single scaffold, 0 marks on crossovers/ends, `?`-free CSV (verified at
caDNAno level).

### §5 cheap diagnostic ALREADY resolved — CanDo `05.inp` element census (no CanDo run)
Extracted from `05_bend_90.zip/structure_NLSA.inp`: **1225 BDNA + 33 NICKDNA beams,
117 HJ crossover elements, 5 ssDNA connectors** (1264 nodes = bp). **117 HJ ≈ our 122
crossovers → CanDo does NOT mesh denser inter-helix coupling than we do.** HJ = finite-
length **compliant B31H beams** (span 2.25–3.8 nm, mean 2.68 nm, DNA section EI=230/GJ=460),
**not rigid links**. ⇒ The bend gap is **not** sparse coupling; it is the crossover model
(rigid link vs compliant beam) and/or the eigenstrain→bend conversion. This reframes B1:
the sweep now tests the density *dependence*, not whether CanDo is denser (it isn't).

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

### Batch 2 (2026-07-03) — labels SCRAMBLED; identified by content (node count = definitive)
Fingerprint each zip by CanDo node count (=bp; ins/del shifts it from baseline 1264),
planarity (λ3/λ2: ≈1 straight rod, <0.2 flat bent arc), and bend. Node-count key:
+30→04(loops), −30→02, −60→03, net-0→{01 straight,05 bend86,06 bend166}.

| ZIP filename | nodes | TRUE design | data |
|---|---|---|---|
| `01_control_straight` | 1264 | **01 control** ✓ | straight, twist≈0° (validates twist baseline) |
| `02_twist_half_turn` | 1294 | **04 twist_opposite** ✗mislabel | twisted; magnitude pending per-helix estimator |
| `03_twist_full_turn` | 1264 | **06 bend_180** ✗mislabel | 166°/R24.1nm (below) |
| `05_bend_90` | 1264 | **05 bend_90** ✓ | 86°/R46 |

**06_bend_180 result:** CanDo bend **165.6°** (span 164 / sag 167), R **24.1 nm** vs analytic
180°/22.7 nm → **92% of ideal** (R +6%). Hairpin relaxes MORE than the gentle bend
(95%→92%) — higher strain, more continuum relaxation, as predicted. Atomic planar 0.063.

**Bend calibration so far:** 05 → 95%, 06 → 92%. The efficiency-vs-strain trend is the FEM
signal. NADOC-FEM targets: 05≈86°, 06≈166°.

**PRESENT (by content): 01, 04, 05, 06. MISSING: 02 (twist_half −30 skips), 03 (twist_full
−60 skips)** — the two deletion/positive-twist designs. NB the user's zips *labeled* 02/03
are actually 04/06, so the real 02 & 03 still need submitting.

**OPEN — twist magnitude estimator.** Bend pipeline is robust (2 exact estimators agree).
Twist proxies (2-fold covariance axis, 6-fold order parameter on all atoms) give
inconsistent 70–168° for 04 — aliasing between the intra-helix backbone spiral and the
bundle twist. The 6-fold order param DID read control=0° correctly (baseline OK). TODO:
per-helix-centroid azimuth tracker (cluster 6 helices per axial slice → follow each helix's
angle about the bundle axis → mean rate × length). Needed before trusting any twist number.

Pending CanDo: real 02, real 03 (re-submit as honeycomb).

### Refinement structures staged (2026-07-03) — for FEM calibration
Generated in `workspace/cando validation/` (honeycomb, 210 bp, marks off crossovers/ends,
`scratchpad/gen_extra_structures.py`), each with `.nadoc`+`.cadnano.json`+`_sequences.csv`:
- **07_2hb_twist** — 2-helix, 5 skips/helix (single scaffold via SEAMLESS routing; seamed
  gives 2 scaffolds on 2HB). Isolates duplex GJ from bundle coupling (decouples the two
  twist-damping parameters).
- **08_18hb_straight** — 18-helix control (cross-section baseline).
- **09_18hb_twist** — 18-helix, 5 skips/helix (SAME density as design 02 → direct
  cross-section comparison of twist damping).
- **10_18hb_bend** — 18-helix 90° bend (cross-section scaling of bend vs 6HB design 05).
All: 1 scaffold, 0 marks on crossovers/ends (caDNAno-verified), CSV `?`-free, analytic
twist 171.4° / bend R 45.5 nm preserved. Gotcha fixed: auto loop/skip candidate must be
interior to BOTH strands (scaffold AND staple) — a scaffold-interior bp can be a staple
terminus. Pending user CanDo submission.

### Whole battery regenerated — NO marks on crossovers/ends (2026-07-03)
Principle (user, now [[feedback_loopskip_no_crossover_ends]]): auto-generated loops/skips
must never sit on a crossover or strand end (nick/terminus/u-turn); manual placement stays
free. Original battery violated this (02 had skips at bp 0, a terminal u-turn end
crossover; 04/05/06 had 20–45 marks on crossovers). Regenerated all 5 loop/skip designs:
- **Twist (02,03,04):** fresh uniform marks at common crossover/end-free bps (twist is
  count-set → positions free). 02→[22,64,105,148,190], 03→[12,32,…,198], 04 loops same as 02.
- **Bend (05,06):** gradient via deformation, then relocate ONLY offending marks to nearest
  free interior bp (per-helix net count preserved → bend preserved).
Verified caDNAno-level: **0 marks on crossovers, 0 on strand ends** (all 5). Preserved:
twist 171.4/342.9/−171.4°, bend R 45.5/22.7 nm (exact analytic), all CSVs `?`-free.
Forbidden set = crossover bps ∪ all strand domain endpoints ∪ 6-bp helix-end margin.
`scratchpad/regen_battery_clean.py`.

NOTE the CanDo failure of 02/03 is still not definitively explained (04/05/06 RAN with
marks on crossovers). Candidate causes now all removed: bp-0 terminal-crossover skip, marks
on crossovers, `?` CSV. Core realizers (`twist_loop_skips`/`bend_loop_skips`) do NOT yet
enforce the no-crossover/end rule — flagged follow-up. Pending CanDo: resubmit 02–06.

### Sequence-CSV '?' bug — FIXED (2026-07-03)
CanDo crashed/skipped on 02 & 03 because their exported sequence CSV had `?` bases.
Root cause: `routes_sequences.py` computed staple length as the raw bp-range
`Σ(|end−start|+1)`, ignoring loop/skips — so for SKIP (deletion) designs the real
sequence is shorter than the range and got padded with spurious `?` (02: 10 staples,
03: 21; 05/06 also affected, 12/… — they ran anyway but were also dirty). Fix: use the
loop/skip-adjusted count `sequences.strand_nucleotide_count(strand, design)` (wraps the
canonical `_strand_nt_with_skips` the assignment already uses) in both the CSV and XLSX
exports. Regression tests in `test_sequences.py` (`TestStrandNucleotideCount`,
`TestSequenceCsvExportSkips`). Clean CSVs for all 6 designs written to
`workspace/cando validation/*_sequences.csv` (0 `?`). `just test`: 3817 passed (1 unrelated
xdist flake). **When re-submitting, upload these clean CSVs.**

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
