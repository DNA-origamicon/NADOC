# ⚙ 2026-07-13 — disconnected / ssDNA-connected blocks no longer explode (general) — supporting detail

[Topic head](../../project_cando_fem.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## ⚙ 2026-07-13 — disconnected / ssDNA-connected blocks no longer explode (general)
Symptom: SNUPI "Fine" on VoltronCore "completed" but rendered NOTHING (just axis lines) — the
nonlinear solve had diverged to **mm-scale** coords (rmsf_max ~1384 nm). Root cause: the duplex-core
mesh split into 2 disconnected bodies. A 6-helix sub-block joined to the body ONLY by the SCAFFOLD
threading through single-stranded STUB helices (`h_XY_4_10` scaf-only 4nt, `h_XY_3_10`) — the duplex
FEM can't bridge a connection running through unpaired ssDNA, so the block floated free; the single
centroid pin left it a free rigid body that ran away under the ES repulsion, and the free-free NMA had
6 EXTRA rigid modes → µm RMSF. Two general fixes in `fem_solver.py` (`[[snupi-mimic]]`, shared cando+snupi):
1. **`_add_linker_hops` → `_add_ssdna_hops`** — generalized from LINKER-only to ALL strands: any
   strand (scaffold/staple/linker) that hops meshed-duplex → unmeshed ssDNA → meshed-duplex on a
   DIFFERENT helix now gets a compliant WLC spring (contour = ssDNA run). This TETHERS ssDNA-connected
   blocks (the physical fix). ds-bridge rigid-link case stays LINKER-only (scaffold/staple ds crossings
   are already `Design.crossovers`). Clean fully-duplex bundles gain ZERO springs → validated numerics
   byte-identical (6HB: 0 springs, 1 component — asserted).
2. **Per-component robustness backstop** (`_mesh_component_labels` + `_ensure_components_pinned` in
   `predict_shape`): pin ≥1 node in EVERY connected component (over elements+rigid_links+springs) so no
   free body drifts, and pass `n_rigid = 6·n_components` to the RMSF NMA. Single-component → identical
   to legacy (one centroid pin, n_rigid=6). A spring-tethered block counts as CONNECTED (soft mode, not
   a zero mode) → bounded RMSF. Result: VoltronCore now 1 component, span 51×152×148 nm, rmsf 0.5–4.3 nm.
Tests: `tests/test_cando_linkers.py` (+4: component labels, per-component pin, clean-bundle-unchanged,
slow VoltronCore end-to-end). See [[LESSONS]] (disconnected-block explosion).

Goal: in-app FEM that reproduces CanDo's NONLINEAR predictions (global twist +
curvature + RMSF flexibility) to within a stated tolerance on the loaded design,
ZERO export. Multi-session. Three-Layer Law: FEM output is PHYSICAL/display only.
Motivation: oxDNA/mrDNA CG-MD under-reproduce programmed loop/skip curvature
(mrDNA ~18% of designed bend, plateaus — see [[LESSONS]] A9). CanDo (Bathe lab,
continuum FE) is the experimentally-validated shape/twist/curvature/flexibility tool.

## Phase 0 verdict (2026-07-02): **GO, with two hard conditions**
Deep-research (97-agent, 24/25 claims confirmed) resolved both gate questions.

### CanDo method IS fully specified in primary lit (reimplementable)
Sources: Kim/Kilchherr/Dietz/Bathe NAR 40(7):2862 (2012, PMC3326316); Pan/Sensale/
Arya/Bathe NAR 45(11):6284 (2017, off-lattice); Castro Nat Methods 8:221 (2011).

- **Element**: two-node Hermitian beam (Euler-Bernoulli-class, NOT Timoshenko),
  **one FE node per bp**, 6 DOF/node (3 trans + 3 rot). N nodes → N−1 elements.
- **Constants (verbatim, canonical across all CanDo papers)**: stretch **1100 pN**,
  bend **230 pN·nm²**, twist **460 pN·nm²**. Geometry: **2.25 nm** duplex diameter,
  **10.5 bp/turn** (34.29°/bp) honeycomb / ~10.67 (33.75°/bp) square, **0.34 nm/bp**
  rise. Bend 230 ⇒ L_p ≈ 50–56 nm; twist 460 ⇒ torsional L_p ≈ 112 nm.
  → **NADOC's archived fem_solver.py ALREADY carries EA=1100, EI=230, GJ=460.**
- **CanDo has NO twist-stretch coupling** (isotropic rod). The ~−90 pN·nm coupling
  in the original goal is single-molecule (Gore 2006), NOT CanDo. −277 pN·nm belongs
  to SNUPI (Lee-Kim, ACS Nano 2021), a DISTINCT MD-parameterized 6×6-stiffness model.
  **To match CanDo 1-to-1, do NOT add twist-stretch coupling.** (SNUPI would need
  MD per-step params — different, harder project.)
- **Crossovers** = rigid links of zero length (fix separation + orientation).
  **Nicks** = reduce bending & torsional stiffness ×100 (nick factor 0.01), keep
  full stretch. **ssDNA connections** = nonlinear modified-FJC springs.
  Off-lattice variant instead uses torsional-spring "alignment elements"
  (interhelix 1.85 nm; double-xover 1353/1353/135.3 pN·nm·rad⁻¹ about e1/e2/e3;
  single-xover drops e3 to 13.53).
- **Pre-stress mechanism** (the crux): each element has rest length 0.34 nm + rest
  twist 34.29°/bp. Lattice over/under-twist and Dietz **insertions/deletions
  (loops/skips)** enter as initial strain by deforming duplexes (stretch+twist)
  until crossovers come into spatial register, THEN energy-minimize → stored elastic
  energy drives global twist/curvature. **CAVEAT: exact per-skip → Δrest-length /
  Δrest-twist numeric recipe is NOT verbatim-published** (least-documented step).
  BUT NADOC already has the closed-form Dietz version:
  `loop_skip_calculator.predict_radius_nm` (κ = Σ ΔL_i·r_i / (L_nom·Σ r_i²), ΔL from
  bp×rise) + `predict_global_twist_deg`. Use these as the pre-stress oracle/sanity gate.
- **Solver**: geometrically **NONLINEAR** (finite rotations, large deflection),
  ADINA full-Newton historically; **the live web server now runs Abaqus (since
  2018-03-01)**. Material linear-elastic; the solve is geometrically nonlinear.
  Runtime 5–35 min. ⇒ Phase 3 (corotational/nonlinear beam FE) is genuinely
  required; the archived LINEAR solve cannot reach 90° bends / global twist.
- **RMSF/flexibility** = normal-mode analysis at the minimum, **200 lowest modes**,
  equipartition at **298 K**: RMSF_i ~ Σ_200 (kBT/λ_m)·φ²_{m,i}. Toggleable
  (jobInfo.NMA). (Archived solver already does eigsh shift-invert but only 30 modes,
  centroid-pinned, uncalibrated — bump to 200, validate.)

### Reference-data path EXISTS but is MANUAL + user-dependent (condition 1)
- **cando-dna-origami.org is LIVE (2026)**: 65,384 structures solved, 4,830 users.
  Accepts **caDNAno uploads** (+ off-lattice/Tiamat/CNDO). NADOC already exports
  caDNAno WITH loop/skip arrays (`cadnano.py:813`) → bridge is structurally intact.
- Outputs: **BILD** shape (Chimera), atomic **PDB**, thermal-fluctuation **AVI**,
  delivered as **ZIP by email**. **Interactive-only — NO API / NO batch / NO script.**
- ⇒ **I cannot run CanDo. The USER must** submit each fixture's caDNAno json to the
  web service and hand back the emailed BILD/PDB (+ any twist/curvature/RMSF numbers)
  as Phase-4 reference data. Without this, Phase-4 validation is impossible (NO-GO).

### Solver is NOT vendorable (condition on effort)
Only public Bathe-lab repo = **lcbb/Off-Lattice-CanDo** = MATLAB pre/post-proc that
shells out to proprietary **ADINA**; beam formulation + Newton solve are closed.
DAEDALUS/PERDIX/TALOS/METIS/ATHENA are routing/sequence-design tools — no mechanical
solve. ⇒ must **reimplement** the geometrically-nonlinear beam FE + NMA in-house
(Phase 3 is the real engineering).

### What "1-to-1" can mean (condition 2)
The reference is a **proprietary black-box (Abaqus)** with unpublished tolerances,
an under-documented pre-stress recipe, and an ADINA→Abaqus switch. **Bit-exact
reproduction is not provably attainable.** Near-quantitative agreement (twist &
bend within a few %, small shape RMSD, RMSF pattern correlation) IS attainable —
same beam model, same published constants. So "1-to-1" must be a **stated
tolerance**, per the user's own Phase-4 wording.
