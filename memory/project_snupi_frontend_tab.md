---
name: snupi-frontend-tab
description: Build prompt + architecture map for the frontend SNUPI structure-prediction engine tab (P5 of the SNUPI mimic). Backend ready via predict_shape(material="snupi").
metadata:
  node_type: memory
  type: project
---

# SNUPI frontend engine tab — fresh-session build brief (P5)

## Shaded result rendering (2026-11-19)

`snupi_result_view.js` uses mrDNA's instanced sphere/stick rendering approach with
opaque, lit materials and per-instance colors. The existing compact CVIZ endpoint
is used at every SNUPI result size; CanDo retains its own threshold/renderer.
Coarse FEM output draws the saved axis segments and crossover joint pairs, with
RMSF colors where available. Predicted shape and trajectory use helix-colored
nucleotide beads; flexibility and deviation use their saved scalar maps and the
live scale widget; missing scalar values are neutral gray. Playback reuses tiled instance buffers and requests one frame
at a time. Progressive bead prefixes bound distant drawing work; zoom restores
full detail, and every coordinate remains available for playback/materialization.
Coarse tubes/joints always retain every recorded segment.
This is visualization of NADOC's SNUPI-model results, not an import of the external
MATLAB SNUPI application's renderer. No simulated coordinates or topology change.
Completed-job selection defaults to coarse output unless the user explicitly
chooses a display mode (including Off). Evidence/checks: ISSUE-250.

## Activity and selected cluster (2026-11-18)

The shared engine-tab activity poll includes SNUPI alongside CanDo, mrDNA and
NAMD; preparing/running jobs show the standard NADOC spinner. SNUPI/mrDNA detail
rendering updates `solver_cluster_card.showJob`, selecting the job's provider and
restoring its saved remote settings when selection changes. Same-job polls retain
next-run edits. RunPod displays selected-job pod/GPU/requested RAM/CPU/quote/budget
separately from live rental offers; deselection clears those job details.
The RunPod help text describes automatic default SNUPI environment setup and
optional linear/Stokes CUDA; custom environments and mrDNA remain user-managed.

## Launch resource admission (2026-11-18)

`solver_resources.py` checks count-based RAM, mrDNA GPU memory and output disk
estimates before creating a job and again on start/restart. It uses the complete
part or flattened assembly projection, includes fragmented chains and SNUPI
hydrodynamics, and compares local capacity after headroom/reservations and cgroup
limits. Local launches reserve RAM/VRAM until completion. Remote RAM is compared
with the requested allocation; local snapshot/result disk space is still checked.
Sparse fill and ARBD overhead are conservative planning allowances, not measured
peak guarantees. Remote GPU eligibility uses Alpine profile capacities and live RunPod catalog VRAM, with 15% headroom; RunPod rechecks before renting. API resource refusals
open a dismiss-only popup through `solver_resource_denial.js` for create/restart.

## Remote resource wizard (2026-11-18)

Coarse/Fine opens `solver_resource_wizard.js` when Alpine or RunPod is selected.
The estimate endpoint uses the current solver options and whole assembly compact
projection. Users choose resources, RAM, CPUs, time, paths and provider settings,
then review and explicitly submit/rent. Undersized or unknown GPU memory is
ineligible for mrDNA. SNUPI retains a CPU fallback, so the wizard has no mandatory
VRAM minimum; optional CUDA dynamics performs a separate runtime headroom check. Alpine RAM is capped by the profile and
allocated CPU count. RunPod queries live stock/prices in the selected volume's
datacenter for the requested host RAM/CPU minima, then checks again before review
and rental; this is not a capacity reservation. Controls use the standard NADOC
input/select/button primitives, with monospace numerical fields. Cancel/dispose creates no job. Local launch stays unchanged.
Whole-card Alpine VRAM lives in `Partition.gpu_vram_gb`; unknown values fail closed
for GPU solvers. This wizard selects whole GPUs, not MIG slices.

The wizard now uses a scrollable radio list (`solver_resource_list.js`) with
availability, general Alpine queue wait, and approximate completion. Alpine data
comes from the shared availability endpoint; whole-GPU GRES is matched without
adding MIG slices. RunPod rows include unavailable cards, disabled with a reason,
and a refresh queries the edited RAM/CPU allocation. Completion uses the existing
solver progress runtime heuristic, explicitly labeled with reference hardware;
there is no calibrated per-node/GPU speed model. Unknown wait/startup stays unknown.
The maximum-time field remains a cap, never a runtime prediction.

## Alpine and RunPod execution (2026-11-18)

The shared `solver_cluster_card.js` / `solver_runpod_card.js` factories provide
Local, Alpine and RunPod execution for parts and whole assemblies. Existing
Coarse/Fine buttons retain their solver options and send the execution target.
The card copies the NAMD/oxDNA shell and radio row, sorts immediately after Jobs,
and reuses their Alpine availability and RunPod GPU picker. Provider-specific
solver paths and resource limits live under collapsed **Solver settings**.
`solver_cluster.py` manages Alpine submission receipts, scheduler reconciliation,
cancellation and verified result download; `solver_runpod.py` adds a compute
budget, exact-pod watchdog and cleanup. Remote jobs bypass local PID reconciliation.
The default RunPod SNUPI environment is provisioned automatically on the persistent
volume; custom paths, Alpine and mrDNA environments remain user-managed. RunPod
interruption recovery is manual; neither adapter adds checkpoint continuation. See
[setup and limits](../docs/solver_cluster_execution.md). BigO-poly Coarse + RMSF
completed on RunPod as job `b958e97feeae`; result retrieval and pod cleanup were verified.

SNUPI Stop is hidden while idle and shown only for queued/preparing/running jobs,
independently of which completed result is selected.

## Topic navigation and current boundaries

Reorganized October 17, 2026. Read the retained contracts here, then only the
matching detail below. Dated results and old handoffs are not new verification
or authorization; current user instructions and `CLAUDE.md` take precedence.

## Result visualization guards (2026-09-28)

Large static jobs now use the shared compact FEM renderer and guarded metrics
factory through SNUPI adapters. Deviation/cylinder preparation runs off the API
event loop. All dynamics playback uses indexed, bounded single-frame requests and
zoom-adaptive points with GPU-buffer reuse, cancellation and backpressure; it no
longer loads the full trajectory into the browser. Engine changes release active
views and pending loads so hidden playback cannot continue. Coordinates remain unchanged;
trajectory points omit orientations/slabs. See [audit](../docs/audits/snupi_visualization_guards_20260928.md)
for scale-fixture provenance, validation and manual visual-quality debt.

<a id="-shipped-2026-07-11--first-class-snupi-engine-tab-separate-tab-path"></a>
- [✅ SHIPPED 2026-07-11 — first-class SNUPI engine tab (separate-tab path)](details/project_snupi_frontend_tab/01-shipped-2026-07-11--first-class-snupi-engine-tab-separate-tab-pa.md#-shipped-2026-07-11--first-class-snupi-engine-tab-separate-tab-path)

<a id="-2026-07-13--solve-now-runs-in-a-detached-subprocess-survives-uvicorn---reload"></a>
- [⚙ 2026-07-13 — solve now runs in a DETACHED subprocess (survives `uvicorn --reload`)](details/project_snupi_frontend_tab/01-shipped-2026-07-11--first-class-snupi-engine-tab-separate-tab-pa.md#-2026-07-13--solve-now-runs-in-a-detached-subprocess-survives-uvicorn---reload)

<a id="anchors--e-fields--surfaces--the-investigation-deliverable"></a>
- [Anchors + E-fields + surfaces — the investigation deliverable](details/project_snupi_frontend_tab/01-shipped-2026-07-11--first-class-snupi-engine-tab-separate-tab-pa.md#anchors--e-fields--surfaces--the-investigation-deliverable)

<a id="the-prompt-paste-into-the-fresh-session"></a>
- [THE PROMPT (paste into the fresh session)](details/project_snupi_frontend_tab/01-shipped-2026-07-11--first-class-snupi-engine-tab-separate-tab-pa.md#the-prompt-paste-into-the-fresh-session)

<a id="architecture-map-grounded-from-a-read-only-sweep-2026-07-11"></a>
- [Architecture map (grounded, from a read-only sweep 2026-07-11)](details/project_snupi_frontend_tab/02-architecture-map-grounded-from-a-read-only-sweep-2026-07-11.md#architecture-map-grounded-from-a-read-only-sweep-2026-07-11)

## Notes
- Module-first: new logic in `snupi_*` modules; `main.js` gets imports + init + thin wiring only.
- `predict_shape` returns DISPLAY-ONLY positions/RMSF (Physical layer) — never write topology.
- Related heads: [[snupi-mimic]] (backend/verdict), simulate_panel_overhaul, cando_fem, md_viz_tools,
  md_engines_panel, mrdna_panel (clean clone precedent).

## Historical BigO-poly Langevin submission (2026-11-18; superseded)

The before case below was subsequently terminated. Optimized two- and ten-monomer
jobs completed successfully; see `project_snupi_dynamics.md` for measured scaling
and receipts. No RunPod pod from those runs remains active.

The original job `4c9ec02f01e5` was stopped during setup to deploy remote
telemetry; pod deletion was independently verified (spent $0.531981). Replacement
`bebad41f65e7` uses the ordinary assembly projection/create API with the same
Coarse, Langevin, RMSF, diagonal Stokes, no tails/anchors/field settings. It is
associated with `BigO-poly.nass` in the unified job list. RunPod pod
`84j90s4fjgre6t`, volume `77pnhye88p`, 75 GiB/eight CPUs, RTX 4090 host at
$0.89/hour; replacement cap $4.46 keeps the combined cap under $5. Watchdog
deadline: `2026-11-19T07:43:00Z`. Check managed status before starting another run.

`snupi_progress.js` renders actual completed dynamics steps out of 60,000,
ignoring static load steps and weighted phase fractions. Setup is indeterminate;
stale remote samples are labelled last known. Backend receipts report named
setup phases and measured integration-only rates, resetting for retries. No
timestep/physics changes were made. Live setup telemetry is verified; a completed
Langevin trajectory is not yet confirmed. Evidence:
`.development-artifacts/snupi-runpod-progress-20261118/checks.json`.

## Dynamics stage timeline (2026-11-18)

`snupi_stage_timeline.js` derives ordered stage rows from existing worker phases:
remote preparation, mesh, stiffness, stable timestep, optional hydrodynamic
friction, integration, analysis/save and remote download. Dynamics steps ARE
integration, not a later stage. A later reported phase establishes completion of
earlier stages; unknown telemetry leaves scientific stages pending. No invented
stage timestamps or setup percentages. Terminal jobs stop showing live stages;
stale transport labels the last reported stage. Both the SNUPI panel and unified
job poll use the same stateless renderer and NADOC theme colors. This frontend
change requires no restart of the ongoing RunPod worker.
