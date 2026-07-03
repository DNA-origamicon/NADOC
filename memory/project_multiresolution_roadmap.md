---
name: Multi-resolution DNA origami simulation pipeline roadmap
description: Long-horizon plan for MrDNA-inspired CG→atomistic→GROMACS pipeline in NADOC, including staged exports, extensions, and validation designs
type: project
originSessionId: c428e99e-8e62-49bc-9619-c9563281a0f3
---
# Multi-Resolution Simulation Pipeline — Persistent Roadmap

This document persists across many sessions. Update phase checkboxes and notes as work progresses.

---

## Background & Motivation

**Current NADOC pipeline** (Phase 1, being validated April 2026):
```
scadnano → ideal B-DNA atomistic model → GROMACS EM+NVT
```
Problem: ideal placement creates 10¹²  kJ/mol LJ energy from crossover terminal atom clashes, requiring 90+ min CPU-only EM for large structures (~480k atoms).

**Goal**: MrDNA-inspired multi-resolution pipeline that:
1. Produces pre-relaxed structures via coarse-grained (CG) simulation
2. Allows export at any pipeline stage for debugging/validation
3. Handles extra crossover bases, sticky ends, and single-stranded extensions at the atomistic stage
4. Validates against MrDNA publication benchmarks
5. Uses GROMACS (not NAMD) for the final atomistic MD stages, leveraging its superior single-node GPU performance (~2–4× faster than NAMD)

**Reference**: Maffeo & Aksimentiev, *NAR* 48(9):5135, 2020. GitLab: `gitlab.engr.illinois.edu/tbgl/tools/mrdna`. Tutorials: `gitlab.engr.illinois.edu/tbgl/tutorials/multi-resolution-dna-nanostructures`.

---

## Pipeline Architecture (REVISED 2026-04-20 — MrDNA/ARBD as reference)

**Decision**: Use MrDNA + ARBD as the canonical CG engine (not oxDNA alone).
- ARBD is GPU-accelerated Brownian dynamics (RTX 2080 SUPER: ~0.05 ms/step for 148-particle model)
- mrdna runs 3 CG stages automatically: low-res 5bp/bead, then two high-res 2bp/bead+orientation
- mrdna outputs atomistic PDB/PSF directly (NAMD/CHARMM36 format); GROMACS is downstream
- oxDNA path remains available as fallback for designs mrdna can't handle

```
scadnano JSON
  │
  ├─[Stage 0]─ Ideal B-DNA atomistic model          ← always available
  │              backend/core/atomistic.py
  │
  ├─[Stage 1]─ MrDNA CG relaxation (3 ARBD stages) ← BRIDGE COMPLETE (2026-04-20)
  │              backend/core/mrdna_bridge.py → mrdna_model_from_nadoc(design)
  │              No cadnano conversion needed; builds SegmentModel directly from Design
  │              U6hb validated: 29 segments, ~3s on RTX 2080 SUPER
  │
  ├─[Stage 2]─ MrDNA atomistic PDB (hextube-3.pdb)  ← MrDNA output
  │              Spline-fit all-atom, CHARMM36 FF
  │
  ├─[Stage 3]─ GROMACS vacuum EM+NVT package        ← current endpoint
  │              backend/core/gromacs_package.py
  │              (input: MrDNA atomistic PDB instead of ideal B-DNA)
  │
  ├─[Stage 4]─ oxDNA CG (fallback)                  ← Phase 2 (CPU-only, slower)
  │              backend/physics/oxdna_interface.py
  │
  └─[Stage 5]─ GROMACS solvated production MD       ← already exists (solvate=True path)
```

**Staged export principle**: The API should be able to export a zip package at ANY of the above stages. This enables: (a) per-stage debugging, (b) running only what's needed, (c) direct comparison with MrDNA at equivalent stages.

---

## Extra Crossover Bases & Terminal Extensions

### Extra Crossover Bases
- 1–2 extra bp at crossover junctions beyond minimal geometry (common cadnano design pattern)
- Reduce bending rigidity at crossovers (1/3 that of helical DNA)
- Currently NOT specially handled in NADOC atomistic model — treated as normal bp
- In CG→atomistic transition: spline naturally accommodates; no special code needed
- **Action needed**: Verify NADOC correctly imports extra crossover bp from scadnano; confirm they appear in strand sequences and are placed correctly in the atomistic model

### Terminal Extensions / Sticky Ends (Single-Stranded Overhangs)
- ssDNA regions at 5'/3' termini (typically 5–20 nt)
- oxDNA handles natively (ssDNA + dsDNA mixed topology)
- GROMACS atomistic: requires special topology handling
  - ssDNA residues need standard CHARMM36 DNA residue types but with no base-pairing constraints
  - No position restraint (POSRE) for ssDNA since they're meant to be flexible
  - Longer equilibration needed (ssDNA RMSF is large)
- **CG→atomistic for ssDNA**: NOT spline-fit (B-form spline doesn't apply); use random coil placement or extended chain geometry as starting point
- **Action needed**: Design NADOC ssDNA detection (strand domains with no complement) and separate handling in both atomistic builder and topology generator

---

## Validation Designs (from MrDNA paper)

| Design | Source | Features | Validation metric |
|--------|--------|----------|-------------------|
| Curved six-helix bundle | `curved-hextube.json` in MrDNA GitLab | 6-helix, bent, uniform crossovers | RMSD vs cryo-EM |
| Slider origami (Castro lab) | MrDNA paper supplement | 6-helix shaft, 12 ssDNA flexible linkers, moving bearing | 500 µs CG dynamics, cryo-EM overlay |
| Pointer/caliper designs | MrDNA paper supplement | Rigid arm structures | RMSF maps |

**Validation protocol**:
1. Import MrDNA benchmark cadnano files into NADOC (via cadnano importer or scadnano equivalents)
2. Export at each pipeline stage
3. Compare Stage 3 (spline-fit all-atom PDB) RMSD to cryo-EM reference: target < 9 Å (MrDNA benchmark)
4. Compare Stage 4 GROMACS structure stability to MrDNA NVT trajectories

---

## Phase Checklist

### Phase 1 — Robust GROMACS Pipeline (prerequisite) [COMPLETE — April 2026]

**Scope**: Designs up to ~200k atoms (~6–32 helices, ≤50 skip sites). Larger designs require Phase 2 CG pre-relax; NS_trans_fix (482k atoms, 59 helices, 134 skips) is the boundary case that demonstrates this limit.

**Completed fixes** (branch `gromacs-testing`):

- [x] **PME electrostatics** — replaced reaction-field in all vacuum MDPs (`_EM_MDP`, `_NVT_MDP`, `_NVT_FREE_MDP`). RF with ε=80 caused artificial compaction; PME gives correct long-range repulsion via Ewald summation.
- [x] **Sequence scrambling fix** — `_build_sequence_map` in `backend/core/atomistic.py` now skips loop_skip positions (delta≤-1) when distributing sequence characters. Scadnano deletions are absent from the strand sequence string; previously every skip site shifted all downstream characters by one, giving 72.8% WC mismatch on NS_trans_fix and purine-purine clashes at 0.039 nm (LJ ~10¹⁴ kJ/mol).
- [x] **EM constraints regression fixed** — removed `constraints = h-bonds` from the vacuum `_EM_MDP` template. All DNA origami designs have O5'↔O1P crossover terminal atom pairs at ~0.05 nm between different GROMACS chains; constraining H-bonds during steepest descent causes >1000 LINCS warnings. Unconstrained `steep` EM resolves these freely via bonded force gradients. H-bond constraints belong in NVT only (already there).
- [x] **Ion placement** — `-scale 1.0` on `gmx insert-molecules`; box margin 2.5 nm for PME periodic image separation.
- [x] **U6hb EM validated** — 6-helix, 167,320 atoms (includes 72 loop residues from loop fix), 36 skip + 36 loop sites. Converged in 9,042 steps, Fmax = 847 kJ/mol/nm. No LINCS errors. ~20 min on 16 CPU threads (CPU-only PME). Re-validated 2026-04-20 post loop fix — 24% fewer EM steps vs old broken model (9,042 vs 11,837).

**Remaining for Phase 1 completion**:
- [x] U6hb NVT run (25 ps restrained + 50 ps free vacuum): **PASSED** — temperature 309→310 K at end of restrained, stable 310.3 K at end of free; potential −5.749×10⁶ kJ/mol (free, unrestrained); no LINCS errors. NVT throughput: 17.3–18.9 ns/day with GPU PME. Re-validated 2026-04-20 post loop fix.
- [x] Commit all Phase 1 fixes to `gromacs-testing` branch and merge to `phase7-loop-skip`

**NS_trans_fix notes (out of scope for Phase 1, informing Phase 2+)**:
- 59-helix square-lattice design, 134 skip sites, ~482k atoms, ~80 nm structure
- After sequence fix: WC complementarity 100%, LJ drops from 10¹² to −6×10⁵ kJ/mol within ~5000 EM steps — the sequence fix works correctly
- EM requires 20,000+ steps at ~300 ms/step (CPU PME only for `steep`) → ~90 min impractical wall-clock for routine use
- Square lattice geometry is NOT the issue; helix axis positions are handled correctly
- **Key insight for Phase 2**: NS_trans_fix-scale designs need CG pre-relax so that EM starts near-equilibrium. With a pre-relaxed structure, EM should converge in <2000 steps rather than 20,000+.
- Designs with >100 skip sites and >300k atoms should be flagged in the UI as recommended for CG pre-relax.

**EM performance benchmarks** (this hardware, April 2026):
- `steep` EM: CPU-only PME; 16 threads fastest; U6hb (164k atoms) ~20 min; NS_trans_fix (482k) ~90 min
- NVT/MD with `sd`: GPU PME works (`-pme gpu`); 160× faster than CPU PME; optimal: `-ntmpi 1 -ntomp 10 -pin on -pme gpu`
- Never run parallel GROMACS jobs; always serial for this hardware

### Phase 2 — oxDNA CG Export + Relax [COMPLETE — April 2026]
- [x] `backend/physics/oxdna_interface.py`: full topology + configuration export; read back CG positions
- [x] `write_oxdna_input()` — MC input with all required keys (restart_step_counter, time_scale=linear, verlet_skin=0.20, etc.)
- [x] `_compute_nuc_geometry()` — extrapolates along helix axis for bp indices beyond helix.length_bp (overhang domains)
- [x] Box auto-sized from actual backbone position extents + 20 nm margin (NOT 2× axis extent)
- [x] API: `POST /design/export/gromacs-cg-start` — background job; frontend checkbox wired
- [x] oxDNA installed at `/home/jojo/miniforge3/bin/oxDNA` (CPU-only build)
- [x] Validated on U6hb: 1000-step MC in 44 s, all backbone positions within 1.9 nm of helix axis
- [x] **Re-validated 2026-04-20 post loop fix**: 5108 nt (5036 + 72 loop copies), 64 strands. 1000-step MC in 44.0 s. Step-0 energy 51885 → final −0.046. Acceptance rates: trans=0.580, rot=0.895. Topology and conf files generated from empty geometry (auto-computed via _compute_nuc_geometry). END OF SIMULATION: everything went OK.

**Critical bugs found and fixed (will recur on new designs):**
- Overhang domains (bp > helix.length_bp) → zero positions → backbone bond = 0 → segfault. Fixed by `_compute_nuc_geometry`.
- Box centering corrupts CG coordinate system for axis refitting — do NOT center. oxDNA handles negative coords via PBC.
- Old segfault-inducing large box (290 nm, 2× max axis) was from helix-axis estimate; use position extents instead.

### Phase 3 — CG→Atomistic Axis Refitting [COMPLETE — April 2026]
- [x] `backend/core/cg_to_atomistic.py`: `build_atomistic_model_from_cg(design, conf_path)`
- [x] Approach: per-helix PCA axis fit (`_refit_helix_axes`) — fits a line through CG backbone positions per helix, projects original axis_start/axis_end onto fitted line. Does NOT directly override backbone positions.
- [x] Rationale: direct position override caused catastrophic LJ clashes due to local z-ordering noise in MC output. Axis refitting smooths this by reconstructing ideal B-DNA along the CG-fitted axis.
- [x] Validated on U6hb: fitted axis start shifts 0.05–0.10 nm (physically meaningful; captures crossover geometry)
- [x] **Validated on U6hb (2026-04-20): PCA axis-refitting does NOT improve EM.** Results:
  - CG path step 0 LJ: 3.51×10¹³ kJ/mol; ideal: 3.04×10¹³ (CG is 16% WORSE)
  - CG converged in 9,656 steps; ideal in 9,787 steps (1.3% difference — negligible)
  - Wall-clock: 12 min 54 s vs 13 min 9 s
  - **Root cause**: PCA averages 420+ positions per helix; a 0.05–0.10 nm axis shift doesn't change relative helix spacing at crossovers. Crossover O5'/O1P clashes are still ~0.05 nm.
  - **Phase 3 needs redesign** — see Phase 3b below

### Phase 3b — CG→Atomistic Redesign (per-helix spline from ARBD fine stage) [COMPLETE — April 2026]

**Implemented**: `nuc_pos_override_from_arbd_strands` in `backend/core/mrdna_bridge.py`
- Reads initial fine-stage PDB (NADOC frame) for bead→helix assignment; DCD for simulated positions
- Per-helix CubicSpline through aligned bead positions (1 DNA bead per bp = FORWARD backbone)
- FORWARD nucleotides from spline; REVERSE reconstructed via minor-groove rotation
- Crossover junction keys INCLUDED (not excluded) — CG crossover gap ~0.3-0.5 nm vs 0.05 nm ideal
- Fine stage: 2520 DNA beads for 5036 nt; spline interpolates between beads

**Key design lesson**: The fine stage has 1 DNA bead PER BASE PAIR (not per nucleotide); direction
assignment (FORWARD vs REVERSE) is not valid — both directions share a single bead at FORWARD
position.  Per-strand splines failed because of this bead model.  Per-helix splines work correctly.

**Validation result** (U6hb, commit 84e8148, 2026-04-24):
- Baseline (ideal B-DNA, 500-step cap): 500 steps, 132s, converged: True
- Phase 3b (CG override, 500-step cap):  14 steps,   8s, converged: True
- Step ratio: 0.03× — **PASS** (>50% reduction criterion)

**Also fixed** (April 2026, same commit):
- `-ter` flag missing from `gromacs_package.py` pdb2gmx call (was only in `md_setup.py`)
- Chain block count bug: count sequential letter changes (not unique letters) in both files
  so pdb2gmx gets correct stdin entries for U6hb's 64 chains (62 unique letters, 64 blocks)

**Cluster relaxation (future)**: Before validating on NS_trans_fix-scale designs (~482k atoms),
a pre-processing step to cluster-relax large designs on HPC is planned. NS_trans_fix validation
is explicitly out of scope until that step is designed.

### Phase 4 — GROMACS Export via CG Path [COMPLETE — April 2026]

**mrDNA-sourced sibling added 2026-07-02** (route established, hardware validation pending —
see `manual_validation_debt.md` MV-MRDNA-SEED): `POST /design/export/gromacs-mrdna-start`
seeds `build_gromacs_package` from a COMPLETED **fine-stage** mrDNA JOB's relaxed structure
instead of running oxDNA. Wiring lives in two `mrdna_runner.py` helpers —
`resolve_md_seed_inputs` (gates: completed + `fine_steps>0` + snapshot/PSF/DCD present; raises
UI-ready ValueError → 409) and `build_md_seed_override` (calls `nuc_pos_override_from_arbd_strands`,
crossovers INCLUDED). It seeds from the JOB's `design.json` snapshot, NOT the live design.
Gating + wiring pinned `tests/test_mrdna_md_seed.py` (7 fast + 1 skip-guarded integration).
**Still TBD (deferred with the user):** coarse-only fallback policy, ssDNA/overhang atomistic
handling (Phase 5), NAMD parity, and a frontend "seed MD" affordance in the mrDNA panel.
The end-to-end GPU→fine-ARBD→override→GROMACS-EM step-reduction payoff is unrun (needs a fine
job on a CUDA box; the one on-disk job is coarse-only).

- [x] `backend/api/crud.py`: `POST /design/export/gromacs-cg-start` — oxDNA relax → `_refit_helix_axes` → `build_gromacs_package`
- [x] `nuc_pos_override` parameter added to `build_gromacs_package`/`build_atomistic_model` but NOT used in CG path (axis refit approach is superior)
- [x] Frontend: "Pre-relax with oxDNA" checkbox in GROMACS export modal
- [x] **Verified (2026-04-20): Current CG path does NOT reduce EM.** The API endpoint and frontend exist and work, but the gromacs-cg path currently provides no benefit over the ideal path for this design. Pending Phase 3b redesign.

### Phase 5 — ssDNA Extensions in Atomistic Model
- [x] **ssDNA seed handling for the mrDNA→GROMACS path (2026-07-02).** mrDNA already
  simulates ssDNA as `NAS` beads (separate `SingleStrandedSegment`s), but the seed
  reconstruction discarded them → overhangs seeded at the ORIGINAL design-axis
  extrapolation, DETACHED from the relaxed body (a 1.4 nm broken backbone at the
  ss/ds junction + clash source). Fixed in `mrdna_bridge.nuc_pos_override_ssdna_from_arbd`
  (+ `_ssdna_runs`), merged into `build_md_seed_override`. Per unpaired run, three
  placement candidates — **A** spline through Kabsch-aligned `NAS` beads (real relaxed
  ss), **B** rigid-translate the ideal run onto the relaxed root (preserves the
  junction bond; the anchor nt lands one bond-length from the root, NOT coincident —
  that coincidence was a real LJ=2e37 bug caught + fixed via the clash oracle), **ideal**
  leave detached — and a **do-no-harm selector** keeps whichever sits farthest from the
  relaxed ds body cloud. Validated (real jobs): sparse OH6hb junction 1.41→0.89 nm
  (restored), no clash; dense 6hb_sim_v2 (user's 200k fine run) clash unchanged 0.087→0.080
  (do-no-harm holds). **KNOWN LIMIT:** long overhangs through a dense bundle core clash
  under *any* straight placement — the ds-only baseline already does (0.087 nm); the CG's
  few `NAS` beads can't route them clear. That's a separate geometry problem (soft-core /
  POSRE-warmup EM, or excluding ss from the first EM), not ssDNA reconstruction. Pins:
  `tests/test_mrdna_md_seed.py` (`_ssdna_runs` topology + skip-guarded junction/clash oracle).
- [ ] GROMACS topology: skip POSRE for ssDNA chains; flag in topology generation
- [ ] Extended-chain (not B-DNA) ideal geometry for ssDNA where no `NAS` beads resolve it
- [ ] Test: design with sticky ends → export → NVT → confirm ssDNA remains flexible

### Phase 6 — Production MD Validation
- [ ] Full MrDNA-comparable run: curved-hextube → oxDNA CG → spline atomistic → GROMACS 100 ns NVT
- [ ] RMSF comparison: NADOC-GROMACS trajectory vs MrDNA ARBD trajectory
- [ ] Speed comparison: GROMACS GPU-PME NVT vs MrDNA ARBD for equivalent wall-clock time

---

## Key Files

| File | Role |
|------|------|
| `backend/core/atomistic.py` | Stage 0 ideal atomistic model; `_atom_frame()` reused in Stage 3 |
| `backend/physics/oxdna_interface.py` | Existing oxDNA frame computation; extend to full export |
| `backend/core/gromacs_package.py` | Stage 4 GROMACS package builder |
| `backend/core/sequences.py` | `domain_bp_range()` — also drives CG topology |
| `backend/core/geometry.py` | `nucleotide_positions()` — helix axis geometry for CG bead placement |
| `backend/api/routes.py` | API routes; add staged export endpoints |

## Why: Avoiding NAMD in Favor of GROMACS
MrDNA's publication pipeline ends at NAMD for atomistic runs. GROMACS is preferred here because:
- ~2–4× faster single-node GPU performance (NVIDIA benchmarks)
- Better AMD GPU support
- Lower memory footprint per atom
- Already integrated in NADOC (existing `gromacs_package.py`)
- AMBER OL15 / CHARMM36 force fields both well-validated for DNA in GROMACS
