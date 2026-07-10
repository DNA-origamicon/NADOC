---
name: project_lammps_oxdna
description: "LAMMPS + CG-DNA as a NADOC engine — CPU-parallel oxDNA for very large assemblies; Phases 1-6 shipped (detect→run→jobs→UI→trajectory→viz card); MPI parallel run VERIFIED (5.85× @8 ranks); external-force mapping (field/anchor/wall → LAMMPS fixes) VERIFIED headless; next = wire forces through REST/UI, then torque"
metadata: 
  node_type: memory
  type: project
  originSessionId: d8652554-53d4-4370-8c3d-913cab89c81f
---

# LAMMPS + CG-DNA (parallel oxDNA) engine

## ▶ RESUME HERE (handoff 2026-07-06)
**State:** Phases 1-6 SHIPPED + committed to master (`feat(lammps): …`). LAMMPS is a
full NADOC engine: detect/install (MD Engines panel + `scripts/lammps_doctor.py`),
native oxDNA→LAMMPS transcoder + runner (FIRE soft-start), managed jobs + REST
(`/api/lammps/jobs`), a dedicated **"LAMMPS — parallel oxDNA"** sidebar section, and a
full **"Visualizations & processing"** card (display / RMSF / deviation / trajectory)
that reuses the oxDNA backend (`oxdna_health`) + frontend (`oxdna_display` pure mappers)
verbatim. Live-verified end-to-end on a 14,485-nt design. **MPI parallel run now
VERIFIED (2026-07-06)** — see the "MPI parallel — VERIFIED" block below.

**Pick up with ONE of (in rough priority):**
1. **Field-run display alignment** — the field-run trajectory display still uses
   whole-structure Kabsch, which partly rotates away a bend. A field run's deflection
   would read better with anchor-positional alignment (like the oxDNA efield display —
   thread `align_keys`/`rotate=False` through the LAMMPS `_traj_inputs` →
   `composite_trajectory`). The anchor keys are already stored on `job.forces['anchor_keys']`.
2. Health/metrics read-back polish; multi-scaffold per-strand sequencing UX.
   (Torque-to-failure was a moonshot example, NOT a goal — dropped per the user.)

**⚠ DEBUG LESSON (6hbx100 "no bowing", 2026-07-07):** a user's field run showed no
dynamics/bowing. Root cause = the **field was ~150× too weak** (0.06 pN/nt, set by a
GIZMO DRAG — the `nmPerPnForN` base-count scaling makes a normal drag map to a tiny
per-nt force on a big design; TYPE the magnitude instead). Measured: anchors held
(0.008 nm), free beads pure thermal jitter (0.09 nm), midpoint bow 0.064→0.067 nm (zero).
Field dir was fine (84° off-axis ≈ perpendicular). Secondary: the anchors were on the
**ssDNA overhangs** = flexible hinges that don't transmit a bending moment (the oxDNA
efield lesson — anchor the DUPLEX ends to bend a bundle). Also a 48-nm 6hb is far
shorter than its bending persistence length → nearly rigid; even a strong safe field
bows it only modestly. Fix shipped: a **weak-field hint** (below `EFIELD_PN_LOW`=0.5
pN/nt the field-card ready line warns "⚠ very weak — unlikely to visibly deform").

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

### ✅ MPI parallel — VERIFIED 2026-07-06 (was the ⚠ build gap)
`libopenmpi-dev` (OpenMPI 4.1.6) now installed. **Build gotcha:** the conda toolchain
(`~/miniforge3`) is on PATH; its linker can't find OpenMPI's `libopen-pal.so.40`/
`libopen-rte.so.40` (in `/usr/lib/x86_64-linux-gnu`, ldconfig knows them). Fix = build
with a **clean system toolchain**, not conda's:
```
rm -rf ~/lammps/build_mpi && mkdir ~/lammps/build_mpi && cd ~/lammps/build_mpi
env -i PATH=/usr/bin:/bin HOME=$HOME cmake -D PKG_CG-DNA=on -D PKG_MOLECULE=on \
  -D PKG_ASPHERE=on -D BUILD_MPI=on \
  -D CMAKE_C_COMPILER=/usr/bin/gcc -D CMAKE_CXX_COMPILER=/usr/bin/g++ \
  -D CMAKE_BUILD_TYPE=Release ../cmake
env -i PATH=/usr/bin:/bin HOME=$HOME cmake --build . -j$(nproc)
```
→ real `MPI v3.1: Open MPI 4.1.6` binary (not STUBS), CG-DNA+oxdna2 present. Copied to
the detection path `~/lammps/build/lmp` (serial backup at `~/lammps/lmp_serial_bak`);
`find_lammps()`+`lammps_supports_cgdna` pick it up, `ldd` shows system libmpi.
**Verified real (this box):** 6hb×1000bp = **12,000 atoms**, 3000 steps —
box decomposes 1×1×1→1×1×8 and **wall time 73.6s(1)→41.4s(2)→20.9s(4)→12.6s(8) =
1.78×/3.53×/5.85×** near-linear speedup. **Correctness:** step-0 thermo (E_pair,E_bond,
TotEng) **bit-identical across 1/2/4/8 ranks** (force field is decomposition-invariant).
6000-atom run gave 1.91×/3.49× at 2/4. Full **managed-job path** (`run_job` with
`job.ranks=4`) → `completed`, log shows `1 by 1 by 4 MPI processor grid`. UI already has
the "MPI ranks" input (`index.html:3940`) wired browser→REST→job→mpirun. All 40 LAMMPS
tests pass against the MPI binary. **No code changed — only the binary.** [[manual_validation_debt]]
MPI item is cleared.

**Rank guard (core-count cap) — SHIPPED 2026-07-10.** The MPI-ranks input was
unbounded (hardcoded `max="64"`); a user could request more ranks than the machine
has, and OpenMPI **refuses `-np N` above the physical-core count** ("not enough
slots") — a confusing hard launch failure. Fix caps ranks at the **physical** core
count (NOT logical/hyperthread: OpenMPI slots = physical cores, and HT siblings give
no MD speed-up — verified on this box, 16 phys / 32 logical, `mpirun -np 17 refused`).
- `lammps_runner.available_cpu_cores()` — physical-core count (psutil if present →
  `/proc/cpuinfo` distinct (physical id, core id) → `os.cpu_count()` → 1).
- `GET /lammps/available` now includes `max_ranks`; `POST /lammps/jobs` 400s on
  `ranks > max_ranks` (fires before design/prep). Verified live: `ranks=17/32 → 400`.
- Frontend: `lammps_jobs_logic.maxRanks`/`ranksError` + `buildCreatePayload({cores})`
  clamp; panel `_boundRanksInput()` sets the input `max`+tooltip from availability and
  the `_launch` guard toasts before a doomed create. Browser-verified: input `max=16`,
  tooltip "Up to 16 physical CPU cores available", 0 console errors. **main.js Δ = 0.**
  Tests: backend +3 (runner core-count, availability shape, ranks-over-cores 400),
  frontend +4 (maxRanks/ranksError/clamp). Full backend suite 4586 passed.

**"Cores" relabel + ⚡ auto-optimize — SHIPPED 2026-07-10.** "MPI ranks" was jargon;
the input is now labelled **"CPU cores"** (payload still sends `ranks` — backend
unchanged). A ⚡ button next to it (`#lammps-jobs-cores-auto`) sets the input to the
cores **free right now**, so a LAMMPS run launched while a NAMD/oxDNA job is using
cores won't oversubscribe.
- `lammps_runner.free_cpu_cores()` — physical ceiling minus the 1-min load average
  (`os.getloadavg()[0]` ≈ busy cores), clamped to [1, total]. `GET /lammps/available`
  now also returns `free_ranks` (re-sampled per call). Live: idle load 0.42 → free 16.
- Frontend: `lammps_jobs_logic.freeRanks(available)`; panel `_optimizeCores()` re-fetches
  availability (fresh sample) and sets the input to `freeRanks`, toasting "Set to N free
  cores (M busy…)". Browser-verified: label "CPU cores", ⚡ sets 2→16 (all free), 0 errors.
  **main.js Δ = 0.** Tests: backend +3 (free-core bounds/under-load/availability field),
  frontend +5 (freeRanks + panel bound/optimize/over-cores-blocked).
- **Higher-rank run VERIFIED (2026-07-10):** user's ranks=6 run on `6hbx100_noT` (1328
  atoms) decomposed 1×2×3, 6 MPI tasks @99.4% CPU, **80 s vs ~226–293 s @ rank 1 =
  ~2.8–3.7×** (sub-linear — tiny design, strong-scaling limit; larger designs scale better).

**⚡ TIMESTEP FIX — SHIPPED 2026-07-10 (~500× faster LAMMPS).** `LammpsInputParams.timestep`
was `1e-5`, copied verbatim from the upstream **lj_units** oxDNA2 demo (`in.duplex2`) — an
ultra-conservative showcase value. Standalone oxDNA runs this exact FF at `dt=0.005`. Changed
the default `1e-5 → 5e-3` ([lammps_interface.py](../backend/physics/lammps_interface.py) —
`LammpsInputParams.timestep`). **Validation (throwaway scripts, all on `6hbx100_noT`):**
(1) stability sweep — clean energies `1e-5 … 1e-2`; (2) NVE energy conservation — drift/τ
smallest at `5e-3`, degradation only past it; (3) **dt-convergence `0.005` vs `0.001`** at
matched physical time / real M13+WC seq / T=0.1 — mean E_pair within 1.3%, E_bond 0.8%,
**mean RMSF within 0.1%** ⇒ timestep-converged = accurate. NB: a cross-engine oxDNA-vs-LAMMPS
mean-RMSF comparison is a POOR dt probe — dominated by equilibration state + global bending of
the long flexible bundle (oxDNA fully MC→MD→equil-equilibrated → floppy ends ~30 nm; LAMMPS
fresh-from-FIRE → stiff ~0.44 nm); use the within-engine dt-convergence instead.

**⇒ GPU-vs-CPU BENCHMARK (matched dt=0.005, GPU idle):** oxDNA-CUDA is **13.3×** faster than
LAMMPS-CPU-16 on 6hbx100 (1328 nt) and **46.6×** on 18hb (14172 nt); GPU always wins when free,
gap grows with size. ⇒ **oxDNA-GPU is the default engine; LAMMPS-CPU is a fallback** for GPU-busy
(esp. small designs / long queues) or VRAM-overflow. Proteins force oxDNA. Feeds the planned
auto engine-policy + resource status line + GPU-busy dialog (plan `enchanted-riding-balloon`).

**⚠ Follow-up (auto-build path):** the in-app auto-build (`engine_install.install_steps`,
`lammps_doctor.py --fix`, panel "Rebuild") runs cmake/make under the process's default
env — on THIS box that means the conda toolchain, which hits the `libopen-pal`/`libopen-rte`
linker failure above and would silently fall back to a STUBS (serial) build even though
`tools["mpi"]` is now true. The working MPI build required `env -i PATH=/usr/bin:/bin` +
explicit `/usr/bin/gcc,g++`. If MPI auto-build matters, `install_steps("lammps_oxdna")`
needs to force the system toolchain when conda is on PATH. Not fixed this session (manual
build done by hand).

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
  `initLammpsJobsPanel()→{refresh}`, self-contained (imports `* as api`). Converged onto
  the unified-panel shared machinery (U3): job list via the canonical
  `jobs_panel_model`/`jobs_panel_render` (slice 2a; keeps its inline Stop via the renderer's
  row-action slot), and the section-collapse + advanced-drawer + REST-poll @1.5s scaffold via
  `initJobsPanelBase` (slice 2c-2, `arrowStyle:'class'` + an onClose that drops views + the
  forces gizmo; the viz-card collapse stays bespoke). jsdom-tested (19, incl. the 2c-2 parity block).
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

## External-force mapping — SHIPPED 2026-07-06 (backend primitive; real-verified)
NADOC's oxDNA external forces (`oxdna_interface`: `string` field / `trap` anchors /
`repulsion_plane` surface) now map onto LAMMPS fixes so a LAMMPS run can be steered
like an oxDNA one. **No unit conversion in the mapping** — a NADOC LAMMPS run uses
`units lj` = oxDNA's native units, so forces are already in oxDNA force units,
coords in oxDNA length units (the runner does pN→oxDNA + nm→oxDNA before building
the spec).

**The three mappings (conventions verified against LAMMPS `src/`):**
- oxDNA `string` (F0·dir, particle=-1) → **`fix addforce all fx fy fz`** — `f[i]+=value`,
  a constant per-atom force. EXACT.
- oxDNA `trap` (pin to pos0, stiff) → **`fix spring/self K`** on an id group — LAMMPS is
  `F=-K·(r-r0)`, `E=½K·dr²` (checked `fix_spring_self.cpp`), the SAME harmonic form as
  oxDNA's trap, so **K == anchor_stiff 1:1** (default 1000 → ~0.03 nm RMS). EXACT.
- oxDNA `repulsion_plane` → **`fix wall/harmonic`** (AXIS-ALIGNED only) — a soft harmonic
  cushion within a cutoff of the wall. Confines to the same half-space but its form
  differs (repulsion_plane = zero on allowed side, linear in penetration; wall/harmonic
  = `2ε·(cutoff−δ)` within cutoff). General plane orientation would need `fix wall/region`
  — DEFERRED. **Real-run gotcha:** `fix wall` requires its axis to be NON-periodic, so a
  walled run flips that axis's `boundary` to `fm`/`mf` (wall face fixed, opposite
  shrink-wrapped so a pushed-out atom isn't lost) — physically correct (a substrate
  breaks periodicity along its normal), see `boundary_line`.

**File map:**
- [lammps_interface.py](../backend/physics/lammps_interface.py) (pure): `LammpsForceSpec`
  dataclass (`force`/`anchor_ids`/`anchor_stiff`/`wall`); `compress_id_ranges`
  (atom-id list → compact `A:B` group arg); `axis_wall_from_extent` (dir+extent →
  `(face,coord)`, raises on non-axis-aligned); `build_force_fixes` (spec → fix lines);
  `boundary_line` (p-p-p unless walled); `build_input_file(p, force_spec=None)` injects
  the fixes at the TOP of the production block (post-minimise, so `spring/self` tethers
  to production-start positions = oxDNA `pos0`). `OXDNA_LENGTH_UNIT`/`NM_TO_OXDNA`/
  `DEFAULT_ANCHOR_STIFF` mirrored locally (asserted == `constants` in tests).
- [lammps_runner.py](../backend/core/lammps_runner.py): `resolve_lammps_forces(design,
  conf, field=, wall=, anchors=, anchor_stiff=)` → `(LammpsForceSpec, meta)`, the analog
  of `oxdna_interface.write_run_forces` (SAME descriptor shapes: `field={field_pN,dir}`,
  `wall={dir,offset_nm,stiff}`, `anchors=[…]`). Reuses `resolve_anchor_particles` +
  `pn_to_oxdna_force` (no new topology reasoning); **raises `LammpsError` on field-without-
  anchor** (oxDNA GOTCHA 1). `prepare_lammps_job` gained `field=/wall=/anchors=/
  anchor_stiff=` kwargs (all optional, backward-compatible) + a `forces` meta in its
  return.

**Verified REAL (this box, MPI lmp):** field(200 pN)+strand-anchor on a 6hb → anchored
beads mean **0.008 nm** / max 0.024 nm from tether (spring holds), free beads **0.090 nm**
of which **0.084 nm is along +x (the field dir)** — i.e. the field pushes the free part
along the field while anchors hold, exactly oxDNA string+trap. Wall run completes rc0
with `boundary p p fm`. Tests: `test_lammps_interface.py` (+9 pure: ranges/wall-extent/
non-axis-raise/fix-lines/boundary/injection-order/const-match), `test_lammps_runner.py`
(+6: resolve field-needs-anchor/field+anchor pN-conv+1-based-ids/wall/prepare-with-forces/
prepare-none + the slow real field-holds-anchor-deflects-free, registered slow in conftest).

## Force-mapping REST/UI wiring — SHIPPED 2026-07-06 (field + anchors + gizmo, live-verified)
The headless force primitive is now driveable from the app.
- **Backend.** `CreateLammpsJobRequest` += `field`/`wall`/`anchors`/`anchor_stiff`;
  `create_lammps_job` passes them to `prepare_lammps_job`, **400s on a field-without-
  anchor** (`LammpsError`), and stores the `forces` meta on the job. `LammpsJob` +=
  `forces: dict|None` (persisted). Tests: `test_lammps_routes` (+ field-without-anchor
  400 fast; + real steered create records forces meta / fixes in `in.lammps`, slow).
- **Frontend — three separate collapsible cards** in the LAMMPS section, mirroring the
  oxDNA panel (updated 2026-07-07 from the original single combined card): **Electric
  field** (`lammps-field-*`), **Anchors** (`lammps-anchors-*`), **Surface**
  (`lammps-surface-*`) — one module `ui/lammps_forces_setup.js`
  (`initLammpsForcesSetup({gizmo,getSelection,getBaseCount,onChange})→{getForces,
  fieldNeedsAnchor,detachGizmo,refresh}`) manages all three via a small `_card()`
  collapse helper (each collapses independently). `getForces()→{field,anchors,wall}`.
  **Reuses `scene/efield_math.js`** (field+anchor helpers: `resolveSelectionAnchors`,
  `addAnchors`/`removeAnchor`, `arrowLenForPn`, `fieldColorHex`/`fieldZone`,
  `EFIELD_PN_LOW`) **and `scene/oxdna_floor_math.js`** (`floorSurfaceSpec`/
  `formatOffsetNm` → the surface `wall={dir,offset_nm,stiff}` payload, six-axis side
  dropdown) + the **same `efield_gizmo`** (a SECOND instance —
  `initEfieldGizmo(...,name)` gained an optional group-name arg, default unchanged;
  LAMMPS uses `'lammps-efield-gizmo'`). Field = pN/nt + x/y/z dir (drag the scene arrow),
  anchors = "Add selected" from the scene selection (overhang/strand/domain/cluster/base)
  → chips. Gizmo attaches only when the card is open AND the field is enabled.
  - **Jobs card now follows the oxDNA example:** filters to the **current design** via
    the shared `filterJobsForPart(_jobs, getWorkspacePath(), showAll)` (job
    `design_source_path` ↔ loaded design path) + a **"show all designs"** toggle
    (`lammps-jobs-show-all`, localStorage-persisted); statuses already render via
    `statusBadge`/`statusKeyFor('lammps',…)`. Create now sends `design_source_path` +
    the forces; a field-without-anchor is blocked client-side with a toast.
  - `buildCreatePayload` gained `designSourcePath`/`field`/`anchors` (attaches only
    non-empty). `initLammpsJobsPanel` gained `getWorkspacePath` + `forcesSetup` deps.
  - **main.js Δ = +9** (import + `initLammpsForcesSetup` factory + the LAMMPS gizmo
    instance + the two new panel deps — wiring only, no cohesive logic).
  - **Surface (wall) UI** (2026-07-07): the Surface card's enable/axis/offset/stiff →
    `wall` payload; the backend `wall=` path (axis-aligned `fix wall/harmonic`, non-
    periodic boundary) was already there. `buildCreatePayload` + the panel now also
    forward `wall`. **`_card` gotcha:** the field card's `onClose:_syncGizmo` runs during
    init before the card handle exists → `fieldCard` is a hoisted `let` (null-guarded in
    `_syncGizmo`), NOT a `const` (a `const` TDZ throws even through `?.`).
  - **Anchor glow + surface grid = same as oxDNA** (2026-07-07): LAMMPS anchors drive the
    SAME purple `anchorGlow` instance (`designRenderer.setAnchorGlow`, InstancedMesh named
    `'anchorGlow'`, count>0 = glowing) via `lammps_forces_setup.getAnchors()` +
    `onChange → main._refreshLammpsAnchorGlow` (glows whenever ≥1 anchor is marked — not
    gated on the field, unlike oxDNA's `fieldOn && anchors`). The Surface toggle drives the
    shared View grid via a new `setSurfaceGrid` dep → `_viewToolButtons.setSurfaceGrid({
    enabled,axis,offsetNm})` (identical to `oxdna_floor_setup`). **TDZ pattern:** onChange /
    setSurfaceGrid reference main.js consts created after the factory, so the module GATES
    them behind a `_ready` flag (`_notify`/`_pushGrid` no-op until construction settles) —
    the same "never fire onChange during construction" rule the oxDNA glow relies on. The
    LAMMPS panel+forces init was MOVED in main.js to AFTER the anchorGlow/`_viewToolButtons`
    setup so it can share them. The existing `nadoc:left-tab-change` handler clears the glow
    for both engines.
  - Tests: `lammps_forces_setup.test.js` (field null-until-enabled, weak-field warning,
    anchors-from-selection, fieldNeedsAnchor, gizmo attach-gating, **surface wall spec**,
    **cards collapse independently**); `lammps_jobs_logic.test.js` (+payload path/forces/
    **wall** attach+omit); `lammps_jobs_panel.test.js` (+current-design filtering, show-all,
    forces payload, field-without-anchor blocked). Frontend suite 2269 green.
- **Verified:** frontend vitest 2266 green; backend lammps suite 57 green (incl. slow
  real steered run); vite build clean; smoke boot-clean (the 2 teardown-gate fails were
  an auto-scaffold timing flake in a test helper — passed on isolated retry, unrelated).
  **LIVE app-exercised** (throwaway Playwright on the running app, then deleted): loaded
  a scaffolded part → Dynamics → LAMMPS → External forces card renders + opens, enabling
  a field shows the graded "⚠ strong field — 25 pN/nt — add ≥1 anchor" ready line, the
  scene gizmo attaches, the "show all designs" toggle is present, **zero console errors**.

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
