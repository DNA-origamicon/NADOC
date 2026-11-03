---
name: extra-base-4fs-geometric-fixb
description: "24hb extra-crossover-base 4 fs NAMD: the winning seed is the GEOMETRIC build + Fix B (heavy bases), NOT the oxDNA position-seed. oxDNA seeding was the blocker."
metadata: 
  node_type: memory
  type: project
  originSessionId: 4f290b8b-2035-48ed-882d-40180304acb5
---

# Extra-crossover-base 4 fs NAMD — geometric build + Fix B is the answer (oxDNA seed was the blocker)

## Topic navigation and current boundaries

Reorganized October 17, 2026. Read the retained contracts here, then only the
matching detail below. Dated results and old handoffs are not new verification
or authorization; current user instructions and `CLAUDE.md` take precedence.

**Proven locally end-to-end on the RTX 3080 Ti (2026-07-15), free.** For DNA-origami with
unpaired "extra" bases at crossovers (24hb_1xT: 338 extra T), a stable **4 fs** production step
needs TWO independent things, and the prior oxDNA-seed pipeline got exactly one of them while
*introducing* a fatal problem:

| build | inter-residue ring clash | heavy extra bases (Fix B) | 4 fs result |
|---|---|---|---|
| oxDNA-seeded (`build_ideal_duplex_seeded_model`) | ✗ 0.3 A ring overlaps | ✓ | k=0.1 catastrophe (70× vel) |
| geometric only (`prep_24hb.py --pre-declashed`) | ✓ 0 clashes | ✗ HMR lightens C5' to 8 amu | RATTLE fails at 4 fs hand-off |
| **geometric + Fix B (`prep_24hb_seeded.py --geometric`)** | ✓ 0 clashes | ✓ ×8 heavy | ✅ full ladder + unrestrained MGHH 4 fs |

**Generalizes to ANY declash stem — not just the 24hb.** `prep_24hb_seeded.py <stem> --geometric`
takes the design stem as an argument; `--geometric` ignores the oxDNA-job arg and runs the
geometric build + Fix-B path for whatever stem you pass. Proven 2026-07-19 on **6hb_2xT** (178 k
atoms): the seeded package came back `declash=False, fast_relaxation.enabled=True,
production_timestep_fs=4.0, gpu_resident=True`, Fix-B applied to 48 extra-base residues (×8), gate
clean. This is the sanctioned rescue for any design RunPod would otherwise force to 1 fs (see
`REFERENCE_RUNPOD_RUNBOOK` §0). Small-bundle designs still carry the *separate* exp29 cohesion risk
(`project_md_prep_relaxation`) — geometric+Fix-B fixes the 4 fs integrator, not bundle cohesion; probe
unrestrained-MGHH before committing a production run. **CONFIRMED 2026-07-19:** the 6hb_2xT ladder
ran 4 fs stably to completion (no crash/NaN) but melted at k=0 (C1' → 84 %, delocalized) — 4 fs fix ✓,
bundle cohesion ✗. A valid 4fs build, but NOT a usable free-dynamics validation target.

<a id="-2026-07-29--4-fs-runs-stably-on-a-1xt-design-straight-off-the-declash-relax-historical"></a>
- [✅ 2026-07-29 — 4 fs runs STABLY on a 1xT design straight off the DECLASH relax (historical)](details/project_extra_base_4fs_geometric_fixb/01-2026-07-29--4-fs-runs-stably-on-a-1xt-design-straight-off-the-de_archive.md#-2026-07-29--4-fs-runs-stably-on-a-1xt-design-straight-off-the-declash-relax-historical)

## The two causes (both must be fixed)
1. **Ring clashes.** The oxDNA POSITION seed (`xb_pos_override`) drops each extra base's CM into
   an IDEAL-lattice duplex whose neighbours are NOT at oxDNA positions → the ~6 A aromatic ring
   interpenetrates a neighbour ring at 0.3–2.0 A (10 residue pairs in 1xT, ALL involving a THY).
   Topologically locked: no-ENM minimize opens it only to ~2.0 A; 25 ps soft doesn't move it.
   **The oxDNA CG beads are NOT overlapping** (min CM–CM 2.05 A) — it is a pure BACKMAP artifact.
   Orientation is NOT the cause: forcing the ring to oxDNA's relaxed a1/a3 (verified normal·a3=0.99)
   still leaves 132 clashes; the plain GEOMETRIC bow-out build has **0**. So: drop the position seed.
2. **Fast extra-base modes.** Even clash-free, the extra bases' fast sugar-pucker / thymine-methyl
   heavy-atom modes blow a 4 fs RATTLE step; standard HMR **lightens** those carbons (C5' → 7.98 amu)
   making it worse. **Fix B** = scale the extra-base masses UP (×8, thermodynamically free — Z_config
   is mass-independent, so the measured inter-helix stiffness is unchanged). Without it the geometric
   build RATTLE-fails on an extra-base C5' at the 4 fs hand-off.

<a id="what-ships"></a>
- [What ships](details/project_extra_base_4fs_geometric_fixb/02-what-ships.md#what-ships)

<a id="local-probe-recipe-free-35-min-no-runpod"></a>
- [Local probe recipe (free, ~35 min, no RunPod)](details/project_extra_base_4fs_geometric_fixb/02-what-ships.md#local-probe-recipe-free-35-min-no-runpod)

## Open
- 2xT (676 extra, TWO per crossover) — VALIDATED 2026-07-16 (job `336a067ba241`). The geometric
  build DOES have extra-base clashes here (150 inter-res ring + 203 sugar pairs <2.2 A, unlike 1xT's
  0) because the two inserts per crossover stack — BUT the pipeline handles it: both clashing
  partners are FREE ssDNA, so the no-ENM minimise + 25 ps soft relax them apart (unlike the 1xT
  oxDNA case where the partner was a FIXED ideal-lattice duplex base), and Fix B holds the modes.
  Full local 4 fs probe CLEAN through unrestrained MGHH (TEMP 298 K, TOTAL flat). So all three
  variants (0/1/2 xT) reach stable 4 fs via geometric+FixB.
- Supersedes the oxDNA-seed rationale in `experiments/exp43_runpod_bench/PIPELINE_4FS_EXTRA_BASES.md`
  (that doc says seeding is REQUIRED; it is actually counterproductive — update it).
- 0xT NAMD ladder is complete on the volume (job `383f7dcc4a5d`); production not yet run.
- Also delivered: SNUPI FEM + mrDNA CG both ran all three 24hb variants (local, free) — see report.

<a id="snupi-convergence-checker--auto-detect-enough-frames-auto-terminate-2026-07-18"></a>
- [SNUPI convergence checker — auto-detect "enough frames", auto-terminate (2026-07-18)](details/project_extra_base_4fs_geometric_fixb/03-snupi-convergence-checker--auto-detect-enough-frames-auto-termina.md#snupi-convergence-checker--auto-detect-enough-frames-auto-terminate-2026-07-18)

<a id="-critical-caveat--the-checker-validates-the-wrong-dof-for-the-deliverable-2026-07-18"></a>
- [⚠ CRITICAL CAVEAT — the checker validates the WRONG DOF for the deliverable (2026-07-18)](details/project_extra_base_4fs_geometric_fixb/03-snupi-convergence-checker--auto-detect-enough-frames-auto-termina.md#-critical-caveat--the-checker-validates-the-wrong-dof-for-the-deliverable-2026-07-18)

<a id="rebuild-progress-2026-07-18"></a>
- [Rebuild progress (2026-07-18)](details/project_extra_base_4fs_geometric_fixb/03-snupi-convergence-checker--auto-detect-enough-frames-auto-termina.md#rebuild-progress-2026-07-18)

<a id="deployed-full-dof-checker-2026-07-18--replaces-the-wrong-dof-original"></a>
- [DEPLOYED full-DOF checker (2026-07-18) — replaces the wrong-DOF original](details/project_extra_base_4fs_geometric_fixb/03-snupi-convergence-checker--auto-detect-enough-frames-auto-termina.md#deployed-full-dof-checker-2026-07-18--replaces-the-wrong-dof-original)

<a id="stiffness-extraction-findings-2026-07-18--2xt-pod-reaped-6ns-user-call-0-billing"></a>
- [Stiffness EXTRACTION findings (2026-07-18) — 2xT pod REAPED @6ns (user call), $0 billing](details/project_extra_base_4fs_geometric_fixb/03-snupi-convergence-checker--auto-detect-enough-frames-auto-termina.md#stiffness-extraction-findings-2026-07-18--2xt-pod-reaped-6ns-user-call-0-billing)

<a id="3dna-kabsch-frame-attempt--the-convention-wall-2026-07-18"></a>
- [3DNA Kabsch frame attempt + the CONVENTION WALL (2026-07-18)](details/project_extra_base_4fs_geometric_fixb/03-snupi-convergence-checker--auto-detect-enough-frames-auto-termina.md#3dna-kabsch-frame-attempt--the-convention-wall-2026-07-18)

<a id="curves-calibration--verdict-use-curves-as-the-per-frame-engine-2026-07-19"></a>
- [Curves+ CALIBRATION — verdict: use Curves+ as the per-frame engine (2026-07-19)](details/project_extra_base_4fs_geometric_fixb/04-curves-calibration--verdict-use-curves-as-the-per-frame-engine-20.md#curves-calibration--verdict-use-curves-as-the-per-frame-engine-2026-07-19)

<a id="refined-2xt-extra_base_co--all-1159-post-eq-frames-2026-07-19"></a>
- [REFINED 2xT extra_base_co — all 1159 post-eq frames (2026-07-19)](details/project_extra_base_4fs_geometric_fixb/04-curves-calibration--verdict-use-curves-as-the-per-frame-engine-20.md#refined-2xt-extra_base_co--all-1159-post-eq-frames-2026-07-19)

<a id="-curves-per-frame-pipeline-validated-2026-07-19--regular_bp-recovers-b-dna--correct-couplings"></a>
- [✅ Curves+ per-frame pipeline VALIDATED (2026-07-19) — regular_bp recovers B-DNA + correct couplings](details/project_extra_base_4fs_geometric_fixb/04-curves-calibration--verdict-use-curves-as-the-per-frame-engine-20.md#-curves-per-frame-pipeline-validated-2026-07-19--regular_bp-recovers-b-dna--correct-couplings)

<a id="results--2xt-extra-base-motif-first-quantitative-estimate-2026-07-19"></a>
- [RESULTS — 2xT extra-base motif FIRST QUANTITATIVE ESTIMATE (2026-07-19)](details/project_extra_base_4fs_geometric_fixb/04-curves-calibration--verdict-use-curves-as-the-per-frame-engine-20.md#results--2xt-extra-base-motif-first-quantitative-estimate-2026-07-19)

<a id="-cross-helix-extractor-built--calibrated--extra-base-motif-6x6-delivered-2026-07-19"></a>
- [✅✅ CROSS-HELIX EXTRACTOR BUILT + CALIBRATED — extra-base motif 6x6 DELIVERED (2026-07-19)](details/project_extra_base_4fs_geometric_fixb/04-curves-calibration--verdict-use-curves-as-the-per-frame-engine-20.md#-cross-helix-extractor-built--calibrated--extra-base-motif-6x6-delivered-2026-07-19)
