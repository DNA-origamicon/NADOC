---
name: project_lammps_oxdna
description: "LAMMPS + CG-DNA as a NADOC engine — CPU-parallel oxDNA for very large assemblies; Phases 1-6 shipped (detect→run→jobs→UI→trajectory→viz card); MPI parallel run VERIFIED (5.85× @8 ranks); external-force mapping (field/anchor/wall → LAMMPS fixes) VERIFIED headless; next = wire forces through REST/UI, then torque"
metadata: 
  node_type: memory
  type: project
  originSessionId: d8652554-53d4-4370-8c3d-913cab89c81f
---

# LAMMPS + CG-DNA (parallel oxDNA) engine

## Topic navigation and current boundaries

Reorganized October 17, 2026. Read the retained contracts here, then only the
matching detail below. Dated results and old handoffs are not new verification
or authorization; current user instructions and `CLAUDE.md` take precedence.

## ⚠ UI CHANGED 2026-07-10 — LAMMPS is no longer a tab/panel
The dedicated **"LAMMPS — parallel oxDNA"** sidebar section + its tab in the engine
selector were **REMOVED**. LAMMPS is now the auto engine-policy's CPU fallback (GPU busy
→ same oxDNA2 FF, multi-core), so its runs appear in the **unified Simulate job list**
with a subtle **[L]** badge, feeding the Phase-C master card ([[project_simulate_panel_overhaul]]).
**Backend / runner / transcoder / viz endpoints (`/api/lammps/*`) are UNCHANGED** — only the
frontend consolidated. `lammps_jobs_panel.js` was deleted; **`lammps_jobs_logic.js`,
`lammps_display.js`, `lammps_forces_setup.js` survive** (the master card owns `initLammpsDisplay`
for [L]-node viz). A LAMMPS run is created only via the CPU fallback (`createLammpsJob`) or a
re-run from the master card — the old launch/forces UI is unreachable by design. Everything
below documents the still-valid engine internals; ignore its "dedicated sidebar section" wording.

<a id="-resume-here-handoff-2026-07-06"></a>
- [▶ RESUME HERE (handoff 2026-07-06)](details/project_lammps_oxdna/01-resume-here-handoff-2026-07-06.md#-resume-here-handoff-2026-07-06)

<a id="goal-long-horizon"></a>
- [Goal (long-horizon)](details/project_lammps_oxdna/01-resume-here-handoff-2026-07-06.md#goal-long-horizon)

<a id="why-lammps-established-verified-this-session"></a>
- [Why LAMMPS (established, verified this session)](details/project_lammps_oxdna/01-resume-here-handoff-2026-07-06.md#why-lammps-established-verified-this-session)

<a id="build-flags-confirmed-on-docslammpsorg-2026-07-06--these-drift-re-verify"></a>
- [Build flags (confirmed on docs.lammps.org, 2026-07-06 — these drift, re-verify)](details/project_lammps_oxdna/01-resume-here-handoff-2026-07-06.md#build-flags-confirmed-on-docslammpsorg-2026-07-06--these-drift-re-verify)

<a id="phase-1--shipped-2026-07-06-detection--registry--panel--doctor--guide"></a>
- [Phase 1 — SHIPPED 2026-07-06 (detection + registry + panel + doctor + guide)](details/project_lammps_oxdna/01-resume-here-handoff-2026-07-06.md#phase-1--shipped-2026-07-06-detection--registry--panel--doctor--guide)

<a id="phase-2--shipped-2026-07-06-native-converter--runner--real-run-verified"></a>
- [Phase 2 — SHIPPED 2026-07-06 (native converter + runner + REAL-run verified)](details/project_lammps_oxdna/01-resume-here-handoff-2026-07-06.md#phase-2--shipped-2026-07-06-native-converter--runner--real-run-verified)

<a id="-mpi-parallel--verified-2026-07-06-was-the--build-gap"></a>
- [✅ MPI parallel — VERIFIED 2026-07-06 (was the ⚠ build gap)](details/project_lammps_oxdna/02-mpi-parallel--verified-2026-07-06-was-the--build-gap.md#-mpi-parallel--verified-2026-07-06-was-the--build-gap)

- [✅ MPI parallel — VERIFIED 2026-07-06 (was the ⚠ build gap) — continued detail](details/project_lammps_oxdna/02-mpi-parallel--verified-2026-07-06-was-the--build-gap.md)

<a id="phase-3--shipped-2026-07-06-managed-job--rest-backend-only-real-verified"></a>
- [Phase 3 — SHIPPED 2026-07-06 (managed job + REST; backend-only, real-verified)](details/project_lammps_oxdna/02-mpi-parallel--verified-2026-07-06-was-the--build-gap.md#phase-3--shipped-2026-07-06-managed-job--rest-backend-only-real-verified)

<a id="phase-4--ui-dedicated-section--shipped-2026-07-06"></a>
- [Phase 4 — UI (dedicated section) — SHIPPED 2026-07-06](details/project_lammps_oxdna/02-mpi-parallel--verified-2026-07-06-was-the--build-gap.md#phase-4--ui-dedicated-section--shipped-2026-07-06)

<a id="soft-start-fire-minimize-preamble--shipped-2026-07-06"></a>
- [Soft-start (FIRE minimize preamble) — SHIPPED 2026-07-06](details/project_lammps_oxdna/03-soft-start-fire-minimize-preamble--shipped-2026-07-06.md#soft-start-fire-minimize-preamble--shipped-2026-07-06)

<a id="trajectory-read-back--viewer--shipped-2026-07-06-user-can-visually-inspect"></a>
- [Trajectory read-back + viewer — SHIPPED 2026-07-06 (user can visually inspect)](details/project_lammps_oxdna/03-soft-start-fire-minimize-preamble--shipped-2026-07-06.md#trajectory-read-back--viewer--shipped-2026-07-06-user-can-visually-inspect)

<a id="visualizations--processing-card-oxdna-parity--shipped-2026-07-06"></a>
- [Visualizations & processing card (oxDNA parity) — SHIPPED 2026-07-06](details/project_lammps_oxdna/03-soft-start-fire-minimize-preamble--shipped-2026-07-06.md#visualizations--processing-card-oxdna-parity--shipped-2026-07-06)

<a id="external-force-mapping--shipped-2026-07-06-backend-primitive-real-verified"></a>
- [External-force mapping — SHIPPED 2026-07-06 (backend primitive; real-verified)](details/project_lammps_oxdna/03-soft-start-fire-minimize-preamble--shipped-2026-07-06.md#external-force-mapping--shipped-2026-07-06-backend-primitive-real-verified)

<a id="force-mapping-restui-wiring--shipped-2026-07-06-field--anchors--gizmo-live-verified"></a>
- [Force-mapping REST/UI wiring — SHIPPED 2026-07-06 (field + anchors + gizmo, live-verified)](details/project_lammps_oxdna/04-force-mapping-restui-wiring--shipped-2026-07-06-field--anchors--g.md#force-mapping-restui-wiring--shipped-2026-07-06-field--anchors--gizmo-live-verified)

## Follow-up phases (NOT started)
- **Torque-to-failure protocol** (+ the loading-rate/sequencing caveats above).
- ~~Enable + verify the **MPI parallel** run~~ **DONE 2026-07-06** (see the ✅ block above).
- Health/metrics read-back (reuse oxDNA health on `traj.oxdna.dat`); multi-scaffold
  designs need every scaffold sequenced (assign per-strand) before a run.

## Caveats for the science phases (record now, don't solve yet)
- CG-MD rupture is **loading-rate-dependent** — a single torque ramp
  over-estimates quasi-static strength. A proper study needs a rate series +
  Bell/Dudko–Hummer–Szabo extrapolation, or a free-energy/umbrella framing.
- Failure localises at the **weakest staple domains**, so designs MUST be fully
  sequenced (oxDNA binding strengths are sequence-dependent).

Sibling engine features: [[project_md_engines_panel]] (the panel this plugs into),
[[project_oxdna_relaxation]], [[project_oxpy_binding_patch]]. Pipeline pitfalls:
[[feedback_cg_pipeline_lessons]].

---

## ⚠️ WSL GPU HAZARD — installing LAMMPS's CUDA deps broke ALL GPU engines (2026-07-09)

Installing LAMMPS's GPU/CUDA stack via Ubuntu's `apt install nvidia-cuda-toolkit` pulled in
`libnvidia-compute-535` (a *native Linux* NVIDIA driver). In WSL the GPU is reachable ONLY through the
Windows-driver passthrough (`/usr/lib/wsl/`); the native package dropped a mismatched
`libnvidia-ptxjitcompiler.so.535` into the ldconfig path that shadows the driver-matched one → **every CUDA
engine that JIT-compiles PTX segfaults (`rc=-11`) at first kernel launch**, oxDNA relax included. See
[[project_oxdna_relaxation]] §"UPDATE 2026-07-09" and [[LESSONS]] K1 for the full diagnosis + the shipped
`oxdna_subprocess_env` LD_LIBRARY_PATH fix. **Do NOT install `nvidia-cuda-toolkit` / native `libnvidia-*`
in WSL** — build LAMMPS against the `cuda-toolkit-13-3` packages + the WSL passthrough driver instead.
