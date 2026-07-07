---
name: project_lammps_oxdna
description: LAMMPS + CG-DNA as a NADOC engine — CPU-parallel oxDNA for very large assemblies; Phases 1-6 shipped (detect→run→jobs→UI→trajectory→viz card), serial-verified; next = force mapping / torque / MPI
metadata:
  type: project
---

# LAMMPS + CG-DNA (parallel oxDNA) engine

## ▶ RESUME HERE (handoff 2026-07-06)
**State:** Phases 1-6 SHIPPED + committed to master (`feat(lammps): …`). LAMMPS is a
full NADOC engine: detect/install (MD Engines panel + `scripts/lammps_doctor.py`),
native oxDNA→LAMMPS transcoder + runner (FIRE soft-start), managed jobs + REST
(`/api/lammps/jobs`), a dedicated **"LAMMPS — parallel oxDNA"** sidebar section, and a
full **"Visualizations & processing"** card (display / RMSF / deviation / trajectory)
that reuses the oxDNA backend (`oxdna_health`) + frontend (`oxdna_display` pure mappers)
verbatim. **Built + run SERIAL** and live-verified end-to-end on a 14,485-nt design.
Backend 4108 tests / frontend 2253 green.

**Pick up with ONE of (in rough priority):**
1. **MPI parallel run** — the engine's whole raison d'être is still UNVERIFIED. Needs
   `sudo apt-get install -y libopenmpi-dev` → rebuild `~/lammps/build` with
   `-D BUILD_MPI=on` → run `run_lammps(..., ranks=N)` and confirm domain decomposition
   speedup + identical physics. Runner code path exists (`build_lammps_argv` mpirun).
2. **External-force mapping** — NADOC E-field per-nt forces / surface wall / anchor
   traps → LAMMPS `fix`es (mirror `oxdna_interface`'s forces.txt), so a LAMMPS run can
   be steered like an oxDNA one. Groundwork for the torque study.
3. **Torque-to-failure protocol** — the actual science goal (mechanical failure of
   large assemblies). **READ the caveats block below first:** loading-rate dependence
   (needs a rate series + Bell/Dudko–Hummer–Szabo, not a single ramp) and
   full-sequencing requirement.

**Owed manual validation:** the live 3D deform-in-browser (viz card → model) is the
user's visual review; everything feeding it is verified. **Gotcha:** editing routes
reloads uvicorn → drops the in-memory active design → view endpoints 404 until a design
is re-loaded (job list persists; not a bug).

**Quick verify:** `just test` (backend) + `cd frontend && node_modules/.bin/vitest run`
(frontend). Live smoke: load a sequenced design → LAMMPS section → Run → select the run →
toggle the viz card. File map + per-phase detail are below.

## Goal (long-horizon)
Add **LAMMPS with the CG-DNA package** as a NADOC simulation engine so the
oxDNA/oxDNA2 force field can run **CPU-parallel via MPI domain decomposition** —
the only oxDNA that scales to large assemblies (tens of origami, ~0.5–2 M nt) that
single-GPU standalone oxDNA can't fit. Target science: mechanical failure of large
assemblies (torque-to-break), where the failure mode is base-pair unzipping /
crossover unbinding — which oxDNA captures and our other CPU tiers (CanDo FEM =
linear elastic, mrDNA = harmonic bonds) fundamentally cannot.

Same force field as standalone oxDNA; only the parallelisation differs. For a
single design, single-GPU oxDNA (`~/oxDNA/build_cuda`) is faster — LAMMPS+CG-DNA is
for systems too big to fit one GPU.

## Why LAMMPS (established, verified this session)
- Standalone oxDNA has **no** CPU parallelism (no OpenMP/MPI linked); CUDA is its
  only accelerator and it's single-GPU. LAMMPS CG-DNA is the parallel oxDNA
  (Henrich/Ouldridge/Romano/Rovigatti): full oxDNA/oxDNA2/oxRNA, seq-dependent,
  Langevin (`fix nve/dotc/langevin`), MPI domain-decomposed.
- Needs LAMMPS packages **CG-DNA + MOLECULE + ASPHERE**; `atom_style hybrid bond
  ellipsoid oxdna`, `bond_style oxdna2/fene`, `pair_style hybrid/overlay` of the 6
  oxdna2 terms (excv, stk, hbond, xstk, coaxstk, dh).
- This box: `mpirun`/`mpiexec` at `/usr/bin/`, 32 cores, 1 GPU; **LAMMPS not
  installed** (nothing to detect yet — Phase 1 detection returns not-found cleanly).

## Build flags (confirmed on docs.lammps.org, 2026-07-06 — these drift, re-verify)
```
git clone --depth 1 https://github.com/lammps/lammps.git ~/lammps
cd ~/lammps && mkdir build && cd build
cmake -D PKG_CG-DNA=on -D PKG_MOLECULE=on -D PKG_ASPHERE=on -D BUILD_MPI=on ../cmake
cmake --build . -j$(nproc)     # → ~/lammps/build/lmp
```
Two LAMMPS-isms: CMake source dir is **`../cmake`** (the subfolder, not repo root),
and the package flag keeps the **hyphen** (`PKG_CG-DNA`, NOT `PKG_CG_DNA` — a fast
model guessed the underscore; it's wrong). MPI is optional for the build (adds
`BUILD_MPI=on` only when an MPI toolchain is seen), but it *is* the whole point.

## Phase 1 — SHIPPED 2026-07-06 (detection + registry + panel + doctor + guide)
Engine key = **`lammps_oxdna`**. No runner yet.

**File map:**
- Detection: [backend/core/oxdna_runner.py](../backend/core/oxdna_runner.py) —
  `find_lammps()` (`$LAMMPS_BIN` → `lmp`/`lmp_mpi`/`lmp_serial` on PATH →
  `~/lammps/build/lmp`) + `lammps_supports_cgdna(path)` (runs `lmp -h`, greps stdout
  for `oxdna`/`cg-dna`; cached by (path, mtime) — the LAMMPS analog of
  `oxdna_supports_cuda`). `lammps_available()` mirror added.
- Registry + plan: [backend/core/engines.py](../backend/core/engines.py) —
  `LAMMPS_REPO`, `"mpi"` toolchain probe (mpirun/mpiexec/mpicxx/mpic++),
  `_lammps_plan()`/`_lammps_commands()` (**auto, target CPU/CPU (MPI), never CUDA**
  — unlike `_source_build_plan`), the `lammps_oxdna` row in `engines_status()`, and
  a **CG-DNA-degraded** block (installed but built w/o CG-DNA → degraded + rebuild
  plan, no GPU condition — mirrors the oxDNA CUDA-degraded case). Added to
  `installable_engine_keys()`.
- Auto-build: [backend/core/engine_install.py](../backend/core/engine_install.py) —
  `install_steps("lammps_oxdna")` (shallow clone → cmake w/ the 3 pkgs + BUILD_MPI
  when `tools["mpi"]` → `cmake --build`), `_verify` maps to `find_lammps`. Streams
  over the same `/ws/engines/install` WS; `NADOC_ENGINES_FORCE_MISSING=lammps_oxdna`
  simulation switch works.
- Panel: [frontend/src/ui/md_engines_logic.js](../frontend/src/ui/md_engines_logic.js)
  — `ENGINE_ORDER` gains `lammps_oxdna` (after `oxdna`); `actionLabel` now reads
  optional `install.degraded_action_label`/`degraded_guided_label` so LAMMPS's
  degraded rebuild says "Rebuild with CG-DNA"/"Add CG-DNA…" instead of the oxDNA
  default "Rebuild for GPU"/"Enable GPU…". No `md_engines.js` change (rows render
  generically). **main.js LOC Δ = 0** (nothing touched).
- Doctor: [scripts/lammps_doctor.py](../scripts/lammps_doctor.py) — sibling of
  `oxdna_doctor.py`; reuses `engines_status()` + `install_steps`; `--fix` builds.
- Guide: [docs/lammps_setup.md](../docs/lammps_setup.md) (linked from the panel via
  the plan's `doc` field).

**Tests:** `test_engines.py` (+8: plan CPU-not-CUDA, cmake flags, MPI on/off,
blocked-without-toolchain, installable, status row/capable/degraded),
`test_engine_install.py` (+3: cgdna flags+MPI, no-MPI, build dir),
`md_engines_logic.test.js` (+1: degraded-label override),
`md_engines.test.js` (+1: LAMMPS row renders as `Install (CPU (MPI))`). Full backend
suite green (the one `test_job_archive` fail is the known xdist active-design
isolation flake — passes isolated).

**Verified:** live `GET /api/engines/status` serves the row (installed False,
cgdna_capable None, target `CPU (MPI)`, mpi toolchain True); `lammps_doctor.py`
reports NOT FOUND cleanly. Panel row confirmed at API + jsdom-DOM level; not clicked
through the browser visually.

## Phase 2 — SHIPPED 2026-07-06 (native converter + runner + REAL-run verified)
User chose: **native writer (no tacoxDNA)**, install+verify a real run, stop at
convert+input-gen+runner (no UI). Topology-safety reading of "native": transcode
NADOC's **own already-validated** oxDNA `topology.top`/`conf.dat` → LAMMPS data —
NO re-derivation of strand polarity (read from the topology `n3` column) or
orientation (read from conf `a1`/`a3`). The one non-obvious mapping (body frame →
LAMMPS ellipsoid quaternion) is **ported verbatim** from the LAMMPS CG-DNA author's
reference `lammps/examples/PACKAGES/cgdna/util/generate.py::exyz_to_quat`.

**File map:**
- Transcoder (pure): [backend/physics/lammps_interface.py](../backend/physics/lammps_interface.py)
  — `exyz_to_quat` (verbatim port), `parse_topology`/`parse_configuration`,
  `build_data_file(top,conf)` (atom types A/C/G/T→1-4, positions+quats, FENE bonds
  from `n3`, box encloses+min-edge, **raises on unsequenced/'N'**),
  `LammpsInputParams`+`build_input_file` (the 6 oxdna2 pair overlays + `oxdna2/fene`
  + `fix nve/asphere`+`fix langevin` idiom from the shipped examples, custom dump w/
  quaternion cols). Uses `units lj` (oxDNA's native units = NADOC's conf.dat units).
- Runner: [backend/core/lammps_runner.py](../backend/core/lammps_runner.py) —
  `prepare_lammps_job(design,geom,dir,params)` (reuses `write_topology`/
  `write_configuration` w/ **oxdna_native_seed=True** → transcode → in.lammps),
  `build_lammps_argv` (serial `lmp -in`; `ranks>1`→`mpirun -np N` — opt-in, caller
  must have an MPI build), `resolve_lammps` (find+CG-DNA gate), async `run_lammps`
  (stream, verify traj frames). `LammpsError`.
- Tests: `test_lammps_interface.py` (17 pure), `test_lammps_runner.py` (8, incl.
  the **real e2e** gated on a CG-DNA lmp, registered slow in conftest `_SLOW_TESTS`).

**Verified REAL (this box):** built LAMMPS `~/lammps/build/lmp` (serial — see MPI
note), stock `duplex2` runs, and NADOC 6hb(42bp) design → oxDNA files → my LAMMPS
data (504 atoms/492 bonds) → `lmp` rc=0 → 5-frame trajectory, `E_pair` **deepens**
−0.41→−0.75 (duplex relaxing, NOT melting), `E_bond`~0.045, energies finite. Quat
port round-trips to 2.4e-15. Full backend suite 4091 passed (2 `test_md_executor`
fails are pre-existing xdist parallel-isolation flakes — pass isolated, executor
untouched).

### ⚠ MPI build gap on this box (parallel feature not yet exercised)
`libopenmpi-dev` is NOT installed (only the runtime wrappers, whose include dir is
dangling), so `-D BUILD_MPI=on` fails at cmake `find_package(MPI)`. Built **serial**
via `-D BUILD_MPI=off -D CMAKE_DISABLE_FIND_PACKAGE_MPI=TRUE` (STUBS). The whole
POINT of this engine — MPI domain decomposition — is therefore **not yet verified**;
the physics/correctness IS (serial CG-DNA = same force field). To enable parallel:
`sudo apt-get install -y libopenmpi-dev` → rebuild with `BUILD_MPI=on` → run with
`run_lammps(..., ranks=N)`. The runner's `mpirun` path is coded but real-run
unverified. **[[manual_validation_debt]]: MPI parallel run.**

## Phase 3 — SHIPPED 2026-07-06 (managed job + REST; backend-only, real-verified)
User chose **backend managed job + REST only** (no UI this phase). A LAMMPS run is
now a first-class persistent background job with a REST API.

**Decision:** a **lean NEW `LammpsJob` subsystem**, NOT grafted onto `OxdnaJob` (which
carries staged-relax/health/retry/staleness/archival semantics that don't apply to a
single LAMMPS run).

**File map:**
- Model: [backend/core/lammps_job.py](../backend/core/lammps_job.py) — `LammpsJob`
  dataclass + `LammpsStatus` (queued/preparing/running/failed/stopped/completed),
  atomic save/load/list_jobs (`workspace/lammps_jobs/{id}/job.json`), `new_lammps_job`.
  Lean: no health/retries/staleness/archival.
- Orchestration (added to [lammps_runner.py](../backend/core/lammps_runner.py)):
  `_RUNNING`/`_ACTIVE_PIDS` registry, `is_running`, `parse_thermo_step` (progress from
  LAMMPS thermo rows), async `run_job` (launch in own process group, stream→`lammps.log`,
  track `current_step`, set terminal status+`frames`), `start_job` (background thread +
  loop, mirrors oxdna/namd), `stop_job` (in-proc killpg+cancel / orphan /proc path),
  `reconcile_lammps_status` (dead-running→stopped; no auto-resume).
- Routes: [backend/api/routes_lammps.py](../backend/api/routes_lammps.py) —
  `GET /lammps/available`, `POST /lammps/jobs` (active design → undefined-base 400 →
  transcode+prepare → background start), `GET /lammps/jobs[/{id}]`, `POST /lammps/jobs/
  {id}/stop`. Reuses `design_state.get_or_404`, `_geometry_for_design`,
  `count_undefined_bases`, `_WORKSPACE_DIR`. Registered in `main.py` next to oxdna_router.
- Tests: `test_lammps_job.py` (5), `test_lammps_runner.py` +5 (parse/reconcile/run_job-
  failed/stop-missing), `test_lammps_routes.py` (6 — TestClient; the real create→run→
  complete lifecycle gated on lmp + registered slow). **Verified live:**
  `GET /api/lammps/available` → `{available:true, cgdna_capable:true}`; the slow route
  test drives a full HTTP create→poll→completed with a trajectory on disk. Full suite
  4102 passed (the lone `test_job_archive` fail is the known xdist flake — passes
  isolated, file untouched).

**NO UI, NO trajectory read-back** (a job's result is its status/progress + the on-disk
`traj.lammpstrj`). Serial run still (MPI gap above unchanged).

## Phase 4 — UI (dedicated section) — SHIPPED 2026-07-06
User chose a **dedicated section** (not an engine-toggle inside the fragile oxDNA
panel; not grafted). New "LAMMPS — parallel oxDNA" sidebar section between the oxDNA
and mrDNA sections, launch + monitor only (no trajectory viewer yet).

**File map (frontend):**
- Pure logic: [lammps_jobs_logic.js](../frontend/src/ui/lammps_jobs_logic.js) —
  `progressPct`, `jobIsActive`/`anyActive`, `runButtonState`, `availabilityMessage`,
  `jobRowLabel`, `buildCreatePayload` (input coercion). Unit-tested (10).
- Factory: [lammps_jobs_panel.js](../frontend/src/ui/lammps_jobs_panel.js) —
  `initLammpsJobsPanel()→{refresh}`, self-contained (imports `* as api`, mirrors the
  mrDNA panel: collapse via `setSectionCollapsed('dynamics',…)`, REST-poll list @1.5s
  while active, Run button, Advanced card params, per-row Stop). Reuses
  `statusBadge`/`statusKeyFor`. jsdom-tested (8).
- Markup: `#lammps-jobs-panel` section in [index.html](../frontend/index.html) (before
  `#mrdna-jobs-panel`); client fns `lammpsAvailable/createLammpsJob/listLammpsJobs/
  getLammpsJob/stopLammpsJob` in `api/client.js`.
- **main.js Δ = +2 wiring lines** (import + `initLammpsJobsPanel()`) + `lammps-jobs-panel`
  added to `_DESIGN_PANEL_IDS` (in-place). No cohesive logic in main.js — module-first OK.

**Verified:** frontend suite 2245 passed (+18 new); `just smoke` 23/23 (console-error
gate — app boots clean with the new section+wiring); **live browser check** against the
running app: section present, opening it hits the real `GET /api/lammps/available` →
status "LAMMPS ready — CPU-parallel oxDNA…", Run button enabled, list "No LAMMPS runs
yet.", zero console errors (throwaway script, deleted). NOT driven: an actual Run-click
on a loaded+sequenced design in the live browser (covered by the jsdom run→create flow +
the backend real create→run→complete route test).

## Soft-start (FIRE minimize preamble) — SHIPPED 2026-07-06
Motivated by inspecting the user's first live run (`6hbx100_noT`, 664 bp, 100k steps
→ 101 frames, completed, energetics healthy): the log showed ~74 `FENE bond too long`
warnings at setup — the idealised B-DNA seed places some crossover/nick backbone
bonds past oxDNA's native FENE length (worst ~2.38 sim units; FENE cliff is ~1.006).
On THAT design they self-relaxed after the first timestep (0 recur), but a
worst-case experiment proved the risk is real: **a badly strained seed's bonds do NOT
self-relax under direct MD** — production-start `E_bond` stayed ~9.1 through the whole
run (the oxdna2/fene force is clamped, so it can't pull a far-overstretched bond in at
production dt). Small-dt warmup + `fix nve/limit` barely helped; **FIRE `minimize`
drove it 9.1 → 0.07**.

Fix: `build_input_file` now prepends a **soft-start** (`LammpsInputParams.relax_iters`,
default 2000; 0 disables): `min_style fire` + `minimize 1e-4 1e-6 N 10N` +
`reset_timestep 0`, so the dumped trajectory is the production run alone. Minimise
relaxes translational positions only (bond overstretch); orientations keep their
correct seed a1/a3 and re-thermalise in production. This is the LAMMPS equivalent of
standalone oxDNA's "min" stage — and it's what makes the engine safe for the
large/strained assemblies that are the whole point. **Verified real:** strained seed
9.14→0.073 (no lost atoms); good 6hb unaffected (E_bond 0.045, Etot −1.24, 5 frames).
Tests: `test_input_file_has_soft_start_minimize_by_default` /
`_soft_start_can_be_disabled`; the real-run + route tests now exercise it. Full backend
suite 4159 passed. Internal default only (not exposed in the create request/UI/model).

## Trajectory read-back + viewer — SHIPPED 2026-07-06 (user can visually inspect)
Goal reached: a finished LAMMPS run scrubs in the 3D model via the EXISTING oxDNA
trajectory viewer. Key idea: the converter maps oxDNA `(a1,a3)`→LAMMPS quat, so
read-back is the inverse, then everything downstream is reused verbatim.

**File map:**
- Backend converter ([lammps_interface.py](../backend/physics/lammps_interface.py)):
  `quat_to_exyz(q)→(a1,a3)` (inverse of `exyz_to_quat`, cols of the rotation matrix)
  + `lammps_dump_to_oxdna_traj(dump_text, out)` — parse the dump (sort atoms by id →
  oxDNA/NADOC order), write an oxDNA `.dat` trajectory. Round-trips to 2e-15.
- Endpoint ([routes_lammps.py](../backend/api/routes_lammps.py)):
  `GET /lammps/jobs/{id}/trajectory` → convert dump→`traj.oxdna.dat` (cached by mtime),
  write a `design_ref.dat`, and **reuse `oxdna_health.composite_trajectory(design,
  [(‘lammps’,‘production’,dat)], ref)`** → the SAME `{keys,frames,stages,markers}`
  payload the oxDNA viewer consumes (each frame PBC-unwrapped + Kabsch-aligned).
  Guard: uses the **active design**; if its nucleotide count ≠ job.n_atoms →
  `{ready:false, reason}` (a different/edited design can't be mapped).
- Frontend: LAMMPS section gains a trajectory viewer (index.html `#lammps-jobs-viz`:
  play/slider/markers/label + Hide). Panel now takes `{ designRenderer }`, reuses
  **`oxdna_trajectory_player` (pure playback) + `framesToUpdates` + designRenderer.
  applyFemPositions`** (all from oxdna_display) — a "View" button on each finished run
  loads the trajectory and scrubs it onto the model; Hide restores it. Client
  `getLammpsTrajectory`. **main.js Δ = 0** (only the existing init line gained
  `{designRenderer}`).
- Tests: backend `test_quat_to_exyz_inverts…`, `test_dump_to_oxdna_traj…`, route
  `test_create_runs_to_completion_and_lists` (extended: full HTTP create→run→trajectory
  ready + keys/frames), `test_trajectory_guard_on_design_mismatch`; frontend panel
  View→applyFemPositions + guard-reason. Frontend 2247, backend 4171 (the 2
  test_md_executor fails = the known xdist flake, pass isolated).

**VERIFIED LIVE (full stack, HTTP):** loaded `3x6sq_m13`, assigned M13 scaffold +
staples, POST created a **14,485-nucleotide** run → completed → `GET …/trajectory`
`ready:true, n_frames=7, n_nucleotides=14485`. App left loaded with a viewable run for
the user's visual review. (Offline real chain + smoke + jsdom also green.)
**PAUSE POINT — user visually inspects results before continuing.**

## Visualizations & processing card (oxDNA parity) — SHIPPED 2026-07-06
Copied the oxDNA "Visualizations & processing" card into the LAMMPS section with the
SAME toggles presented the same way, **generalized so it's a different data source
through the same validated code**. The key enabler: the dump→`.dat` transcode means
EVERY oxDNA reader works on a LAMMPS run verbatim.

**Backend (100% reuse of validated health code):** 3 new endpoints, each = shared
`_traj_inputs(job_id)` helper (active-design guard + convert dump→`.dat` + design_ref)
→ the SAME `oxdna_health` function:
- `GET /lammps/jobs/{id}/display?align=` → last aligned frame as `positions` (via
  `composite_trajectory` last frame).
- `/rmsf` → `production_rmsf(design,[dat],ref)` + `rmsf_confidence` (flexibility map).
- `/deviation` → `production_rmsf` + `geometry_deviation_map(mean, core_ref)`.
All return the SAME payload shapes as the oxDNA routes.

**Frontend (reuse the validated pure mappers + player):**
- [lammps_display.js](../frontend/src/ui/lammps_display.js) — lean controller
  `initLammpsDisplay({designRenderer})` that runs LAMMPS data through oxdna_display's
  **exported pure mappers** (`toFemUpdates`/`rmsfColorMap`/`deviationColorMap`/
  `framesToUpdates`) + the SAME `designRenderer.applyFemPositions`/`applyScalarColors`.
  CG-only (no atomistic/surface heavy paths — LAMMPS is coarse-grained), so the fragile
  oxDNA controller is UNTOUCHED. Methods: displayJob/displayRmsf/displayDeviation/
  loadTrajectory/showFrame/stopAndRestore.
- Card markup copied into index.html (ids `lammps-jobs-*`), name-group `lammps-viz`:
  Off / LAMMPS display (+Align checkbox) / Flexibility (RMSF) / Deviation / View
  trajectory (play+slider+markers). Omits only the atomistic/surface granularity
  dropdown (N/A for CG-only).
- Panel rewritten: **job SELECTION** (click a row → highlight; radios enable only for a
  viewable finished run via `jobIsViewable`), the 5 radios wired to the controller
  (mutual-exclusion + teardown), Align re-fetches display, trajectory reuses
  `oxdna_trajectory_player` (onSeek→showFrame). Pure helpers `jobIsViewable`,
  `flexStatusText` in lammps_jobs_logic. Client `getLammpsDisplay/Rmsf/Deviation`.
  **main.js Δ = 0** (designRenderer already passed).
- Tests: `test_lammps_routes` (+display/rmsf/deviation on the real run), frontend
  `lammps_jobs_panel.test` rewritten to the card (11) + `lammps_jobs_logic` (+jobIsViewable/
  flexStatusText). Frontend 2253, backend 4108 green.

**Verified LIVE:** all 4 view endpoints ready on the 14,485-nt `3x6sq_m13` run
(display 14485 positions, rmsf/deviation 6 frames, trajectory 7 frames); the card +
all 5 toggles render in the running app; boot clean (console-error gate). The literal
3D deform-in-browser is the user's visual review (needs the run's design loaded).
**GOTCHA:** editing routes reloads uvicorn → drops the in-memory active design →
view endpoints 404 until a design is re-loaded (not a bug; the job list persists).

## Follow-up phases (NOT started)
- **Force mapping**: NADOC E-field per-nt forces, surface wall, anchor traps → LAMMPS
  `fix`es.
- **Torque-to-failure protocol** (+ the loading-rate/sequencing caveats above).
- Enable + verify the **MPI parallel** run (`libopenmpi-dev` → `BUILD_MPI=on` → ranks>1).
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
