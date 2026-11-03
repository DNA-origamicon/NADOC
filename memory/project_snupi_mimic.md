---
name: snupi-mimic
description: "Plan — recreate base SNUPI \"for free\" (transcribe published params into the existing CanDo FEM + validate vs on-disk atomistic MD). Extra-crossover-base extension = the only paid MD."
metadata: 
  node_type: memory
  type: project
  originSessionId: 50fa1bce-741d-4cbe-a62f-7e750db8c0f9
---

# SNUPI mimic — get base SNUPI for free

## Topic navigation and current boundaries

Reorganized October 17, 2026. Read the retained contracts here, then only the
matching detail below. Dated results and old handoffs are not new verification
or authorization; current user instructions and `CLAUDE.md` take precedence.

**Goal:** Test whether *base* SNUPI can be recreated at ~$0 new MD by (1) transcribing SNUPI's
published per-motif parameters (`Literature/SNUPI_SI.pdf`, Tables S1–S5) into a param DB and
(2) wiring them into NADOC's existing corotational beam FEM (`backend/physics/fem_solver.py`),
then validating against on-disk full-atomistic MD (6hbx100_noT). If it holds, the
extra-crossover-base extension (the only part needing GPU MD) plugs into the same param DB.

## STATUS — extra-base extension SHIPPED (2026-07-19)
The `extra_base_co` motif (unpaired extra bases at a crossover → compliant CO-beam) is **derived,
wired, and shipped**: `snupi_material.MOTIF_FAMILIES` (74→75) + `snupi_params.json` + `fem_solver`
classifier / CO-beam diversion. Replaces the old k_rot=0 WLC-spring placeholder.
- **Parameters** (atomistically MEASURED, 24hb_2xT 6 ns, Curves+-calibrated Kabsch cross-helix 6×6):
  rotational hinge **GJ≈27, EIy≈27, EIz≈13** pN·nm² (robust, converged, replicate-confirmed); **EA≈965
  is an UPPER BOUND** (translational is the slow DOF); the **15 couplings are 0** (measured small/noisy).
- **Validation (held-out 24hb_1xT, 9 ns): MODEST positive.** SNUPI-`extra_base_co` beats the k_rot=0
  placeholder in the correct direction — per-bp RMSF MAE **1.41 vs 1.77 Å** at the extra-base junctions —
  but the match is loose: correlation flat (~0.52), both over-predict ~1.7×. Confounds: (a) 2-insert
  motif on a 1-insert structure (too soft), (b) 9 ns under-samples the slow global modes → atomistic
  RMSF biased low. Harness: `experiments/exp43_runpod_bench` (scratchpad `validate_24hb_1xT.py`).
- **A clean SMALL-structure size-independence test is BLOCKED.** 6hb_2xT rebuilt 4fs-safe
  ([[extra-base-4fs-geometric-fixb]]) ran 4 fs stably, but the small bundle **melts at k=0** (C1'→84 %,
  delocalized — exp29 [[project_md_prep_relaxation]] cohesion, reconfirmed). No clean free-dynamics
  window (k=0 melts, k=0.01 suppresses the fluctuation). Size-independence therefore rests on SNUPI's
  verified motif-locality, not a direct small-bundle run.
- **Bottom line:** a mechanistically-grounded improvement over the placeholder, shipped with honest
  caveats — NOT a tight quantitative validation. Strengthening needs a longer 24hb reference (converge
  slow modes) or a cohesively-stable small extra-base design (bigger bundle, or +salt per exp29).

<a id="why-this-is-cheap-established-2026-07-11"></a>
- [Why this is cheap (established 2026-07-11)](details/project_snupi_mimic/01-why-this-is-cheap-established-2026-07-11.md#why-this-is-cheap-established-2026-07-11)

<a id="the-three-deltas-cando--snupi"></a>
- [The three deltas (CanDo → SNUPI)](details/project_snupi_mimic/01-why-this-is-cheap-established-2026-07-11.md#the-three-deltas-cando--snupi)

<a id="validation-data--on-disk-no-new-md"></a>
- [Validation data — ON DISK, no new MD](details/project_snupi_mimic/01-why-this-is-cheap-established-2026-07-11.md#validation-data--on-disk-no-new-md)

<a id="phases"></a>
- [Phases](details/project_snupi_mimic/02-phases.md#phases)

- [Paper reproduction + cross-comparison (2026-07-11) — `experiments/exp42_snupi_cross_compare/` — continued detail](details/project_snupi_mimic/02-phases.md)

<a id="paper-reproduction--cross-comparison-2026-07-11--experimentsexp42_snupi_cross_compare"></a>
- [Paper reproduction + cross-comparison (2026-07-11) — `experiments/exp42_snupi_cross_compare/`](details/project_snupi_mimic/03-paper-reproduction--cross-comparison-2026-07-11--experimentsexp42.md#paper-reproduction--cross-comparison-2026-07-11--experimentsexp42_snupi_cross_compare)

## Risks / rules
- **Convention conversions** (3DNA vs beam element; SNUPI's own co-rotated local triad). The
  `bundle_stiffness.json` cross-check catches gross errors. Transcribe SNUPI's OWN convention —
  do NOT reuse the Euler-ZYZ extraction pipeline (gimbal-locked K_q3/K_q5; see
  [[feedback_bundle_param_extraction]]).
- **Three-Layer Law:** FEM output is PHYSICAL/display only, never writes topology.
- Don't touch `_PHASE_*`. Concurrent sessions share this tree — never git stash/reset/restore/checkout;
  forbid git in subagent prompts.

<a id="-shape-solve-fix-2026-07-12--snupi-fine-no-longer-stretches-2"></a>
- [⚠ Shape-solve fix (2026-07-12) — snupi Fine no longer stretches ~2×](details/project_snupi_mimic/04-shape-solve-fix-2026-07-12--snupi-fine-no-longer-stretches-2.md#-shape-solve-fix-2026-07-12--snupi-fine-no-longer-stretches-2)

<a id="handoff"></a>
- [Handoff](details/project_snupi_mimic/04-shape-solve-fix-2026-07-12--snupi-fine-no-longer-stretches-2.md#handoff)
