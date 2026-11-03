---
name: project_cando_fem
description: "Native CanDo-replica FEM shape predictor (twist/curvature/RMSF). Phase 0 research DONE — GO w/ conditions. Method spec, reference-data path, phase plan."
metadata: 
  node_type: memory
  type: project
  originSessionId: e1d46763-a32b-48c8-a9b2-03be170aa027
---

# Native CanDo FEM shape predictor

## Topic navigation and current boundaries

Reorganized October 17, 2026. Read the retained contracts here, then only the
matching detail below. Dated results and old handoffs are not new verification
or authorization; current user instructions and `CLAUDE.md` take precedence.

**Completed-result visualization (2026-09-27):** above 50k nucleotides, CanDo
uses exact-position points and true-axis/joint lines, identified in the UI. A
bounded compact endpoint avoids full snapshot/ensemble downloads; GPU scalar
recoloring, cancellation epochs and hidden native source roots prevent stale or
expensive display work. Deviation now follows the displayed representative
conformation. Large metric graphs use the same compact data. Solver/topology
unchanged. See [visualization audit](../docs/audits/cando_visualization_guards_20260927.md).

**Thermal reconstruction (2026-09-27):** a per-job reference context and coordinate-only
frame path avoid rebuilding reference geometry and discarded orientation/axis records
48 times. BigO bounded reconstruction measurements: 50–51 s → 9.2–9.9 s/frame
(5.1–5.5×), coordinate agreement below 1e-12 nm; this does not include normal-mode
time. Float64 frames stream to the unchanged JSON schema. Progress reports each
frame, statistics, representative reconstruction and saving; cancellation checks
those boundaries. See [optimization audit](../docs/audits/cando_thermal_optimization_20260927.md).

**Assembly execution (2026-09-27):** CanDo/SNUPI assembly launches prepare a canonical
backend-only Design, avoiding full flattened browser geometry. Creation is off the API
event loop; assembly results render the job snapshot. BigO (30 copies, 211,680 FEM nodes)
direct static coarse solves complete in ~94–97 s, ~5.5 GiB peak RSS with one BLAS thread.
Playwright verified both full BigO launches and cylinder result views (~162–163 s
per job with the browser active), plus full nucleotide display on two copies.
Full-size NMA/thermal/dynamics performance is not established by that static check.
See [execution audit](../docs/audits/assembly_fem_execution_20260927.md).

**RESUME HERE →** `experiments/exp36_cando_fem_validation/HANDOFF.md` (scorecard, architecture,
bend-gap diagnosis, PRIORITY CanDo designs to run, next-session plan). This file is the running
log; the HANDOFF is the entry point for a fresh session.

## 2026-09-25 — assembly and correlation performance

Global stiffness assembly now batches nonzero COO contributions and returns the
same editable LIL API. Generalized correlation batches at most 2,048 pairs per
row chunk, retaining the existing covariance/MI formula. Benchmark medians:
assembly 32–59× faster on 504/3,528-node bundle fixtures; correlation after NMA
6.6× faster on 504/1,500-node synthetic 200-mode inputs. These are kernel timings,
not whole-solver or UI speedups. Physical parameters and element frames unchanged.
See [audit and validation](../docs/audits/performance_20260925/README.md).

<a id="-2026-07-13--disconnected--ssdna-connected-blocks-no-longer-explode-general"></a>
- [⚙ 2026-07-13 — disconnected / ssDNA-connected blocks no longer explode (general)](details/project_cando_fem/01-2026-07-13--disconnected--ssdna-connected-blocks-no-longer-explo.md#-2026-07-13--disconnected--ssdna-connected-blocks-no-longer-explode-general)

<a id="phase-0-verdict-2026-07-02-go-with-two-hard-conditions"></a>
- [Phase 0 verdict (2026-07-02): **GO, with two hard conditions**](details/project_cando_fem/01-2026-07-13--disconnected--ssdna-connected-blocks-no-longer-explo.md#phase-0-verdict-2026-07-02-go-with-two-hard-conditions)

<a id="cando-method-is-fully-specified-in-primary-lit-reimplementable"></a>
- [CanDo method IS fully specified in primary lit (reimplementable)](details/project_cando_fem/01-2026-07-13--disconnected--ssdna-connected-blocks-no-longer-explo.md#cando-method-is-fully-specified-in-primary-lit-reimplementable)

<a id="reference-data-path-exists-but-is-manual--user-dependent-condition-1"></a>
- [Reference-data path EXISTS but is MANUAL + user-dependent (condition 1)](details/project_cando_fem/01-2026-07-13--disconnected--ssdna-connected-blocks-no-longer-explo.md#reference-data-path-exists-but-is-manual--user-dependent-condition-1)

<a id="solver-is-not-vendorable-condition-on-effort"></a>
- [Solver is NOT vendorable (condition on effort)](details/project_cando_fem/01-2026-07-13--disconnected--ssdna-connected-blocks-no-longer-explo.md#solver-is-not-vendorable-condition-on-effort)

<a id="what-1-to-1-can-mean-condition-2"></a>
- [What "1-to-1" can mean (condition 2)](details/project_cando_fem/01-2026-07-13--disconnected--ssdna-connected-blocks-no-longer-explo.md#what-1-to-1-can-mean-condition-2)

## Open questions to resolve before/within later phases
1. Exact per-skip/loop → Δrest-length/Δrest-twist mapping (use NADOC analytic as
   oracle; may need to inspect Off-Lattice-CanDo .inp generation or contact Bathe lab).
2. Do HC vs SQ change any modulus, or only ground-state twist/bp + interhelix spacing? (likely latter)
3. ADINA vs Abaqus convergence differences vs the live server output.
4. Quantitative validation table (Dietz 2009 twisted bundles/curved beams/gears,
   6-helix bundle: twist °/turn, radius nm, RMSF) — pull from Castro 2011 / Kim 2012
   supplementary; not captured in the research pass.

<a id="existing-assets"></a>
- [Existing assets](details/project_cando_fem/02-existing-assets.md#existing-assets)

<a id="phase-plan"></a>
- [Phase plan](details/project_cando_fem/02-existing-assets.md#phase-plan)

<a id="-bend-gap-was-a-measurement-artifact--corrected-2026-07-03-exp36"></a>
- [⚠ BEND "GAP" WAS A MEASUREMENT ARTIFACT — CORRECTED (2026-07-03, exp36)](details/project_cando_fem/02-existing-assets.md#-bend-gap-was-a-measurement-artifact--corrected-2026-07-03-exp36)

<a id="constants-aligned-to-cando--nick-model-2026-07-03"></a>
- [CONSTANTS ALIGNED TO CANDO + NICK MODEL (2026-07-03)](details/project_cando_fem/02-existing-assets.md#constants-aligned-to-cando--nick-model-2026-07-03)

<a id="exp37--skiptwist-landscape-map--sub-1-config-2026-07-05--experimentsexp37_cando_skip_twist_map"></a>
- [exp37 — skip→twist LANDSCAPE MAP + sub-1° config (2026-07-05) — `experiments/exp37_cando_skip_twist_map/`](details/project_cando_fem/02-existing-assets.md#exp37--skiptwist-landscape-map--sub-1-config-2026-07-05--experimentsexp37_cando_skip_twist_map)

<a id="exp37-follow-up--twist-objective-wired-into-autorefine-2026-07-05"></a>
- [exp37 FOLLOW-UP — twist objective WIRED INTO autorefine (2026-07-05)](details/project_cando_fem/03-exp37-follow-up--twist-objective-wired-into-autorefine-2026-07-05.md#exp37-follow-up--twist-objective-wired-into-autorefine-2026-07-05)

<a id="generalization-progress-2026-07-05--g1-done-g2-done"></a>
- [Generalization progress (2026-07-05) — G1 done, G2 done](details/project_cando_fem/03-exp37-follow-up--twist-objective-wired-into-autorefine-2026-07-05.md#generalization-progress-2026-07-05--g1-done-g2-done)

<a id="generalization-g3--g4-2026-07-05--both-plan-refining-partly-negative"></a>
- [Generalization G3 + G4 (2026-07-05) — both plan-refining (partly negative)](details/project_cando_fem/03-exp37-follow-up--twist-objective-wired-into-autorefine-2026-07-05.md#generalization-g3--g4-2026-07-05--both-plan-refining-partly-negative)

<a id="g1-wired-into-fem_refine-honeycomb-path-2026-07-05"></a>
- [G1 WIRED into fem_refine honeycomb path (2026-07-05)](details/project_cando_fem/03-exp37-follow-up--twist-objective-wired-into-autorefine-2026-07-05.md#g1-wired-into-fem_refine-honeycomb-path-2026-07-05)

<a id="anchors--dirichlet-bc-2026-07-06-sim-coverage-task-c1"></a>
- [ANCHORS — Dirichlet BC (2026-07-06, sim-coverage task C1)](details/project_cando_fem/03-exp37-follow-up--twist-objective-wired-into-autorefine-2026-07-05.md#anchors--dirichlet-bc-2026-07-06-sim-coverage-task-c1)
