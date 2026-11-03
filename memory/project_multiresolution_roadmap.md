---
name: Multi-resolution DNA origami simulation pipeline roadmap
description: Long-horizon plan for MrDNA-inspired CG→atomistic→GROMACS pipeline in NADOC, including staged exports, extensions, and validation designs
type: project
originSessionId: c428e99e-8e62-49bc-9619-c9563281a0f3
---

# Multi-Resolution Simulation Pipeline — Persistent Roadmap

## Topic navigation and current boundaries

Reorganized October 17, 2026. Read the retained contracts here, then only the
matching detail below. Dated results and old handoffs are not new verification
or authorization; current user instructions and `CLAUDE.md` take precedence.

This long-horizon roadmap retains its original phase decisions and dated pipeline assumptions. Current managed-job behavior is owned by [MD jobs](project_md_job_system.md) and [simulation lifecycle](project_simulation_runtime.md); old preferences here do not supersede those later contracts.

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

<a id="pipeline-architecture-revised-2026-04-20--mrdnaarbd-as-reference"></a>
- [Pipeline Architecture (REVISED 2026-04-20 — MrDNA/ARBD as reference)](details/project_multiresolution_roadmap/01-pipeline-architecture-revised-2026-04-20--mrdnaarbd-as-reference.md#pipeline-architecture-revised-2026-04-20--mrdnaarbd-as-reference)

<a id="extra-crossover-bases--terminal-extensions"></a>
- [Extra Crossover Bases & Terminal Extensions](details/project_multiresolution_roadmap/01-pipeline-architecture-revised-2026-04-20--mrdnaarbd-as-reference.md#extra-crossover-bases--terminal-extensions)

<a id="extra-crossover-bases"></a>
- [Extra Crossover Bases](details/project_multiresolution_roadmap/01-pipeline-architecture-revised-2026-04-20--mrdnaarbd-as-reference.md#extra-crossover-bases)

<a id="terminal-extensions--sticky-ends-single-stranded-overhangs"></a>
- [Terminal Extensions / Sticky Ends (Single-Stranded Overhangs)](details/project_multiresolution_roadmap/01-pipeline-architecture-revised-2026-04-20--mrdnaarbd-as-reference.md#terminal-extensions--sticky-ends-single-stranded-overhangs)

<a id="validation-designs-from-mrdna-paper"></a>
- [Validation Designs (from MrDNA paper)](details/project_multiresolution_roadmap/01-pipeline-architecture-revised-2026-04-20--mrdnaarbd-as-reference.md#validation-designs-from-mrdna-paper)

<a id="phase-checklist"></a>
- [Phase Checklist](details/project_multiresolution_roadmap/01-pipeline-architecture-revised-2026-04-20--mrdnaarbd-as-reference.md#phase-checklist)

<a id="phase-1--robust-gromacs-pipeline-prerequisite-complete--april-2026"></a>
- [Phase 1 — Robust GROMACS Pipeline (prerequisite) [COMPLETE — April 2026]](details/project_multiresolution_roadmap/01-pipeline-architecture-revised-2026-04-20--mrdnaarbd-as-reference.md#phase-1--robust-gromacs-pipeline-prerequisite-complete--april-2026)

<a id="phase-2--oxdna-cg-export--relax-complete--april-2026"></a>
- [Phase 2 — oxDNA CG Export + Relax [COMPLETE — April 2026]](details/project_multiresolution_roadmap/01-pipeline-architecture-revised-2026-04-20--mrdnaarbd-as-reference.md#phase-2--oxdna-cg-export--relax-complete--april-2026)

<a id="phase-3--cgatomistic-axis-refitting-complete--april-2026"></a>
- [Phase 3 — CG→Atomistic Axis Refitting [COMPLETE — April 2026]](details/project_multiresolution_roadmap/01-pipeline-architecture-revised-2026-04-20--mrdnaarbd-as-reference.md#phase-3--cgatomistic-axis-refitting-complete--april-2026)

<a id="phase-3b--cgatomistic-redesign-per-helix-spline-from-arbd-fine-stage-complete--april-2026"></a>
- [Phase 3b — CG→Atomistic Redesign (per-helix spline from ARBD fine stage) [COMPLETE — April 2026]](details/project_multiresolution_roadmap/01-pipeline-architecture-revised-2026-04-20--mrdnaarbd-as-reference.md#phase-3b--cgatomistic-redesign-per-helix-spline-from-arbd-fine-stage-complete--april-2026)

<a id="phase-4--gromacs-export-via-cg-path-complete--april-2026"></a>
- [Phase 4 — GROMACS Export via CG Path [COMPLETE — April 2026]](details/project_multiresolution_roadmap/02-phase-4--gromacs-export-via-cg-path-complete--april-2026.md#phase-4--gromacs-export-via-cg-path-complete--april-2026)

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

<a id="why-avoiding-namd-in-favor-of-gromacs"></a>
- [Why: Avoiding NAMD in Favor of GROMACS](details/project_multiresolution_roadmap/03-why-avoiding-namd-in-favor-of-gromacs.md#why-avoiding-namd-in-favor-of-gromacs)
