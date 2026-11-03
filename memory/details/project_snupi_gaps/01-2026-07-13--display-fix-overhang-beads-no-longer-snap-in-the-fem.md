# ⚙ 2026-07-13 — DISPLAY fix: overhang beads no longer snap in the FEM overlay — supporting detail

[Topic head](../../project_snupi_gaps.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## ⚙ 2026-07-13 — DISPLAY fix: overhang beads no longer snap in the FEM overlay
Symptom (user, VoltronCore, 55 overhangs): the deform/flex overlay looked "massively overstretched" even after
the shape fix. Root cause (confirmed): `deformed_positions_with_axis` (the FEM display path, cando+snupi) winds
EVERY bead onto the duplex axis, but OVERHANG beads carry no FEM node — winding them DROPS the overhang ball-joint
rotation that the RENDER applies (`apply_overhang_rotation_if_needed` in `_geometry_for_helices`, line ~349). So on
`applyFemPositions` the overhangs snapped off their rotated pose (~16 nm), AND those misplaced beads skewed the
whole-structure Kabsch fit → a global ~7.6 nm DUPLEX offset too. Proof: clean 6HB (no overhangs) FEM-vs-render =
**0.14 nm**; VoltronCore duplex 7.6 / overhang 16 nm. **Fix** (`fem_solver.deformed_positions_with_axis`): omit every
overhang-domain bead (built from `domain.overhang_id` over `domain_bp_range`) + every fully-unmeshed helix from the
emitted positions AND the Kabsch — `applyFemPositions` then leaves them at their correct RENDERED pose (the snapshot
the overlay draws on). After: **0 overhang beads emitted**, duplex offset 7.6→4.4 nm (the residual is the real ~3.3 nm
FEM deformation, not an artifact). Clean bundles unaffected (every helix meshed). Tests: cando_field/cando_linkers/
snupi_job green (32). The block (2×3) also benefits.
## ⚙ 2026-07-13 — DISPLAY fix #2: winding rise-scale bug (the "still-open" residual — was NOT minor)
Symptom (user, VoltronCore): SNUPI overlay STILL had stretched bonds between overhangs and their embedded staples
even after DISPLAY fix #1. Root cause (confirmed, isolated at u=0 → no solve, no deformation involved):
`_wound_backbones_for_helix` computed the per-bp rise as `rise_geom = |axis_end - axis_start| / helix.length_bp`.
On a helix carrying a long IN-LINE ssDNA overhang tail, `axis_end` stops at the paired-duplex end (the last FEM node)
while `length_bp` counts the unpaired tail too → the ratio is ~½ the true rise (VoltronCore worst helix 0.179 vs
0.334). That wrong scale corrupts the bead's `s→bp→axial` mapping, misplacing EVERY duplex bead axially by an amount
growing LINEARLY along the helix (0.5 nm near the duplex start → **~25 nm at the tip**). Since overhang beads are held
at their rendered pose (fix #1), the moved staple beads pull away → stretched junction bonds. Measured at u=0 on
VoltronCore: duplex bead |FEM_display − rendered| mean **5.4 / max 19.4 nm**; the 55 overhang↔staple JUNCTION beads
mean **9.0 / max 19.1 nm**, 52/55 > 2 nm. (Not the FEM deformation — this is u=0; not cluster transforms — VoltronCore
render == straight, single Kabsch residual 0.00.) The earlier "~21 nm for a FEW beads" note undersold it: pervasive,
~20 nm mean across every overhang-bearing helix.
**Fix** (`fem_solver._wound_backbones_for_helix`, ~line 1799): `rise_geom = BDNA_RISE_PER_BP` (0.334) — the constant
`nucleotide_positions` always spaces beads at, independent of `axis_end`. So `x = bp_start + s/rise_geom` = the bead's
TRUE bp and `_at_bp` anchors each bead onto its own bp's deformed node. After: VoltronCore u=0 junction stretch **9.0 →
0.40 nm mean (0.67 max), 0 junctions > 2 nm** (down from 52/55); curved-bundle winding still ⊥ the deformed tangent.
- **⚠ do NOT use the FEM node spacing (FEM_RISE_PER_BP 0.34) or a node-span rise for this** — an attempt to zero the u=0
  error that way BROKE the curved case: warping the bp coordinate is invisible on a straight helix but on a bent axis it
  anchors beads to the WRONG node, so they stop winding perpendicular to the deformed tangent
  (`test_fem_solver.test_deform_backbones_wind_around_the_curved_axis` fails, perp 0.39 vs <0.15). The bead↔bp
  registration MUST use the bead rise; the residual is only the node-grid difference.
- **Residual (~0.4 nm mean / 0.67 max, sub-bond-length):** pre-existing FEM-node-grid (0.34) vs geometry-grid (0.334)
  drift — `_at_bp` interpolates FEM node abs positions (0.34) while beads live on the 0.334 grid. It's uniform across the
  WHOLE overlay (not overhang-specific; duplex↔duplex bonds share it, so it was never noticed). Killing it needs the
  display to unify on the geometry grid (rebuild both the winding anchor AND the `res["axis"]` output as
  geometry-straight + FEM displacement) — a bigger, riskier change touching the cylinder rep; deferred unless bonds still
  read long. cando+snupi share this path.
Pin: `tests/test_cando_linkers.py::test_wound_backbones_no_rise_collapse_with_ssdna_overhang_tail` (helix whose
`axis_end` stops short of `length_bp`; asserts u=0 recon err < 1 nm; proven to FAIL 4.93 nm on the old formula).


## ⚙ 2026-07-13 — DISPLAY fix #3: 47% of every frame was beads the renderer cannot draw
`nucleotide_positions` emits a bead at EVERY bp of a helix, strand or no strand — and a helix is routinely
declared far longer than the strands on it (VoltronCore: a 288-bp helix carrying 48 bp of duplex). The renderer
draws only nucleotides with a `strand_id` (`_geometry_for_helices` → helix_renderer's `assignedGeometry`), so
**12 921 of VoltronCore's 27 687 emitted beads were unaddressable dead payload** — and, being the beads furthest
outside the meshed bp range, the winding extrapolated them wildly (4.5 nm mean / **19 nm max** motion across a
trajectory, vs 0.26 nm for a real duplex bead) **while sitting in the Kabsch fit**. Same class of bug as fix #1
(overhang beads skewing the fit). **Fix** (`deformed_positions_with_axis`): emit only strand-covered beads.
Payload 27 687 → **14 766** (−47%); the fit improved — u=0 FEM-display vs the rendered pose **0.40 → 0.241 nm
mean / 0.67 → 0.565 max** (so fix #2's "residual" is now half what it was). `test_predict_shape_covers_every_
nucleotide_including_each_loop_copy` had ENSHRINED the dead payload (its oracle was the raw lattice, though its
docstring claimed "every nucleotide the renderer draws"); it now pins a **bijection** with the drawn set.
Cando+snupi share this; ordinary fully-covered bundles are byte-identical. Also new: `deformed_positions_with_axis`
now optionally emits SIMULATED free-ssDNA tail beads (`tail_positions=`/`tail_nodes=`, [[project_snupi_ssdna]] SS-4)
— they ride the same rigid alignment but stay OUT of the Kabsch, which fix #1 is the reason for.

## Visual-vs-NAMD automation + the shape gap (2026-07-12)
`scripts/snupi_visual_compare.py` quantifies EVERY SNUPI display mode against the free-k0 NAMD DCD
(shape RMSD to the MD mean + twist/bend/span; RMSF pattern; DCCM), across cando / snupi-default /
snupi-corotational. CI-safe building-block pins in `tests/test_snupi_visual_compare.py`. Findings
(`experiments/.../visual.json`):
- **The default (ES-free) shape is the CLOSEST to the NAMD mean structure** — RMSD 0.57–0.65 nm
  (~2% of the bundle). The deform/deviation/cylinder visuals "look like the design" because a
  well-formed bundle genuinely IS mostly straight (NAMD confirms; SQ bend 14.6° FE vs 13.2° MD — match).
- **The corotational+electrostatics path OVER-deforms** (bend 55–67° vs MD 7–13°, RMSD 1.7–2.7 nm) —
  the ES force is too strong when it drives the shape. Confirms the shape-fix (ES-free default) was
  right; the corotational-for-shape path needs ES-magnitude calibration before it's usable.
- **Genuine shape gap = intrinsic TWIST** (HC 23.6° the straight-start FEM misses; snupi-default 0°).
  This is **G10** (SNUPI's canonical initial config: ω≈34.3°/bp HC / 33.75° SQ, 2.25 nm CO). Closing it
  = the shape twist matches MD. Touches the GEOMETRIC layer (Three-Layer) → confirm before implementing.
- **RMSF + DCCM (flexibility) match NAMD** — the validated channels, unaffected.

## ✅ Phase D DONE (2026-07-12) — G4 + G5 + G11 (full corotational Newton; opt-in, shape-only)
- **G4 corotational 3D beam** — `backend/physics/snupi_corotational.py`. Element-independent corotational
  (EICR): wraps the STANDARD 12×12 linear beam (`local_beam_stiffness_12`) as the local core and adds the
  corotational filter (CR frame `_cr_frame` z=chord + Battini mean-rotation aux vector; reference offsets
  so rest/rigid motion → zero deformation; SO(3) `exp_so3`/`log_so3`). `element_force_tangent` returns the
  CONSISTENT internal force `f_g=T·K₁₂·d_local` — the piece the earlier naive Newton lacked. Pins
  `tests/test_snupi_corotational.py`: rigid-body ⇒ zero force; small load ⇒ EXACT linear-EB `δ=FL³/3EI`
  (ratio 1.000); large load ⇒ converges with elastica foreshortening.
- **G5 Newton–Raphson** — `solve_corotational`: load-stepped global Newton, tracks node positions + triads
  (triads via exp-map), step-capped. **Uses the analytic MATERIAL tangent `T·K₁₂·Tᵀ` (`geometric=False`)**
  in the integration — a modified Newton that converges robustly WITHOUT the O(12·n_el) finite-difference
  geometric tangent (which is far too slow at bundle scale; the exact numerical tangent is kept for the
  benchmark tests). Convergence comes from the consistent internal force, not the exact tangent.
- **G11 electrostatic consistent tangent** — the inter-helix Debye–Hückel force + **FULL** tangent
  (`axial_only=False`, the indefinite perpendicular term a real Newton tolerates) enters each iteration via
  the `extra_ft` hook, ramped with the load; ssDNA springs too.
- **Wired opt-in**: `predict_shape(material="snupi", corotational=True)` → `_solve_snupi_corotational`
  (fem_solver). Default (`corotational=False`) = the validated fixed-point predictor, unchanged; cando
  untouched. **6HB/84 (1260 nodes) converges in ~47 s** (≈ the fixed-point's 52 s), finite + physically
  bounded (span 37.6 vs 44.9 nm — the geometric foreshortening). Pin
  `test_corotational_integration_on_real_design_converges` (small 2HB, ~4 s).
- **Refinements DONE (2026-07-12):** (a) the corotational local element now uses the FULL SNUPI anisotropic +
  coupled 6×6 material (twist–stretch + EIy≠EIz, via `_snupi_element_stiffness`), not just the diagonal
  rigidities — the couplings are live in the Fine shape solve (still converges, 6HB finite). (b) G7's **MI-based
  generalized correlation** added: `compute_generalized_correlation_matrix` (Lange–Grubmüller closed form for
  the Gaussian NMA, [0,1], captures off-axis coupling the Pearson DCCM misses). Pin `test_g7_generalized_*`.
- **Remaining caveat:** eigenstrain + field are dead loads in the corotational solve (not co-rotated).
  **Verdict unchanged: Phase D improves only the Fine SHAPE, not the validated RMSF/DCCM metrics (separate NMA).**
  ALL gaps G1–G12 now closed. **G9 closed 2026-07-13** (SS-1 — SNUPI's real ssDNA element, measured from
  the binary; see [[project_snupi_ssdna]]). Only **G10** remains (canonical 2.25 nm CO init config).

## ✅ Phase C DONE (2026-07-12) — G7 + G8 (new observables, no impact on the RMSF verdict)
- **G7 BP–BP cross-correlation matrix (DCCM, S11).** `compute_correlation_matrix(K, n, M)` — the
  Pearson correlation of per-bp displacement fluctuations from the free-free NMA modes
  (`C_ij = <Δr_i·Δr_j>/√(<|Δr_i|²><|Δr_j|²>)`, k_BT cancels). Valid corr matrix (symmetric, unit diag,
  [−1,1]); nearest-neighbor ~1, decays with separation. Shared modes helper `_nma_modes`. Pins `test_g7_*`.
  - **MD comparator** `scripts/snupi_dccm_compare.py` (→ `experiments/exp42.../dccm.json`): builds the MD
    DCCM from per-frame bp-center C1' (reusing the md_trajectory ctx), compares FE-vs-MD off-diagonal
    entries. **HC 6hbx100_noT: snupi→MD 0.491 vs cando 0.454 — SNUPI captures the motion TOPOLOGY better**
    (a second, independent validation channel confirming the RMSF verdict). SQ 3x4SQ: tie (0.387/0.393).
- **G8 bending persistence length from NMA frequencies (S12).** `persistence_length_from_nma(K,mesh,design,M)`
  — treats the bundle as a free-free Euler-Bernoulli beam, inverts the fundamental bending frequency ω₁
  (β₁L=4.730) with the bundle length + mass/length → EI_eff → L_p = EI_eff/k_BT. **6HB: L_p_bend ≈ 2.6 µm
  (105bp) / 4.5 µm (210bp), EI_eff ~46–80× a single helix — physical (≫ dsDNA 50 nm).** Self-consistency:
  the degenerate bending pair agrees (ratio ≈ 1.00). Pins `test_g8_*`.
  - **Caveats (documented in the docstring):** (1) TORSION L_p = None — these short/thick bundles have NO
    separable low-frequency pure-twist mode (twist ≫ bending stiffness, so twist modes sit high + mix;
    verified). (2) The full E-B OVERTONE series (β₂L=7.853…) does NOT cleanly appear at these aspect ratios
    (observed ω-ratios 1,1,1.72,1.97… ≠ E-B 1,2.76,5.40…), so only the fundamental is used. (3) L_p shows
    some length sensitivity (2.6→4.5 µm) — end effects on short beams; longer bundles give cleaner L_p.
- **Verdict unchanged (G7/G8 are [+] observables):** SNUPI ≥ CanDo, now confirmed on TWO channels (RMSF
  magnitude + DCCM motion topology). Remaining: Phase D (full corotational Newton) — deferred, high-risk,
  shape-only; **needs an explicit go.**

## ✅ Phase B DONE (2026-07-12) — G3 + G2, gated behind `material="snupi"`
- **G3 single/double crossover classification (S4).** `_classify_crossovers` (adjacency rule,
  confirmed w/ user): crossovers between the same helix pair in an adjacent-bp cluster (≥2) →
  `double_co`; a lone crossing (helix ends/seams) → `single_co` (much softer — EA ~8%, bending/torsion
  ~40% of double). `FEMRigidLink.co_type` → the assembler uses `family_mean_D(co_type)` (both means PD,
  sidesteps single_co per-motif indefiniteness). On 6hbx100_noT: 56 double / 10 single (all at ends).
  The **angle correction** (S4.2) is a documented NO-OP for our mimic: SNUPI applies it to CO *rest
  geometry* (Θ) which it itself calls mechanically negligible, and we use NADOC geometry for the initial
  config. Pins `test_g3_*`.
  - **exp42 (snupi vs MD): G3 is the biggest single win.** HC 6hbx100_noT pearson **0.604→0.620**
    (+0.015), spearman +0.006; SQ 3x4SQ pearson **0.743→0.761** (+0.019), spearman **0.620→0.643**
    (+0.023). Physical: softening the single COs at the floppy helix ends fixes the known end-RMSF
    under-prediction. cando byte-identical.
- **G2 bp-frame registration (S3.3 / eq 3.18). KEPT ON per user (fidelity over metric).** Each element's
  transverse frame registered so the soft bending axis EIy(Roll,158) lies along the base-pair long axis =
  the **C1'–C1' cross-strand direction** (NADOC's locked `base_normal`; convention confirmed w/ user,
  mechanically pinned `test_g2_*`). `FEMElement.R_bp`; `assemble_global_stiffness(bp_registered_frame=)`
  scoped to the RMSF NMA (shape solve keeps reframed frames); cando byte-identical.
  - **exp42: a WASH-to-slightly-negative (as the memory predicted — anisotropy self-cancels over a turn).**
    pearson HC +0.0035 / SQ +0.0017; spearman HC **−0.0146** / SQ −0.0022. Net ~neutral; kept ON for
    fidelity to the published model, not because it improves the RMSF pattern. Note: C1'–C1' is tilted
    ~15° from the true 3DNA dyad (150° groove) — a small approximation the user accepted.
- **Cumulative (pre-Phase-A → post-Phase-B, snupi vs MD):** HC pearson 0.598→0.623 (+0.025), spearman
  0.423→0.420 (~flat, G2 ate the G1/G3 rank gains); SQ pearson 0.742→0.763 (+0.021), spearman
  0.623→0.641 (+0.018). SNUPI still ≥ cando on both lattices; **G3 the standout, G1 modest, G6/G2 washes.**
- **Next: Phase C** (G7 BP–BP correlation matrix; G8 persistence length from NMA — needs G6's frequencies).
  Both are new observables, no bp-frame/topology risk.
