# ✅ MPI parallel — VERIFIED 2026-07-06 (was the ⚠ build gap) — supporting detail

[Topic head](../../project_lammps_oxdna.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

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
the default `1e-5 → 5e-3` ([lammps_interface.py](../../../backend/physics/lammps_interface.py) —
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
- Model: [backend/core/lammps_job.py](../../../backend/core/lammps_job.py) — `LammpsJob`
  dataclass + `LammpsStatus` (queued/preparing/running/failed/stopped/completed),
  atomic save/load/list_jobs (`workspace/lammps_jobs/{id}/job.json`), `new_lammps_job`.
  Lean: no health/retries/staleness/archival.
- Orchestration (added to [lammps_runner.py](../../../backend/core/lammps_runner.py)):
  `_RUNNING`/`_ACTIVE_PIDS` registry, `is_running`, `parse_thermo_step` (progress from
  LAMMPS thermo rows), async `run_job` (launch in own process group, stream→`lammps.log`,
  track `current_step`, set terminal status+`frames`), `start_job` (background thread +
  loop, mirrors oxdna/namd), `stop_job` (in-proc killpg+cancel / orphan /proc path),
  `reconcile_lammps_status` (dead-running→stopped; no auto-resume).
- Routes: [backend/api/routes_lammps.py](../../../backend/api/routes_lammps.py) —
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
- Pure logic: [lammps_jobs_logic.js](../../../frontend/src/ui/lammps_jobs_logic.js) —
  `progressPct`, `jobIsActive`/`anyActive`, `runButtonState`, `availabilityMessage`,
  `jobRowLabel`, `buildCreatePayload` (input coercion). Unit-tested (10).
- Factory: [lammps_jobs_panel.js] (recorded path: `../frontend/src/ui/lammps_jobs_panel.js`) —
  `initLammpsJobsPanel()→{refresh}`, self-contained (imports `* as api`). Converged onto
  the unified-panel shared machinery (U3): job list via the canonical
  `jobs_panel_model`/`jobs_panel_render` (slice 2a; keeps its inline Stop via the renderer's
  row-action slot), and the section-collapse + advanced-drawer + REST-poll @1.5s scaffold via
  `initJobsPanelBase` (slice 2c-2, `arrowStyle:'class'` + an onClose that drops views + the
  forces gizmo; the viz-card collapse stays bespoke). jsdom-tested (19, incl. the 2c-2 parity block).
- Markup: `#lammps-jobs-panel` section in [index.html](../../../frontend/index.html) (before
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
