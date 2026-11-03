# ▶ RESUME HERE (handoff 2026-07-06) — supporting detail

[Topic head](../../project_lammps_oxdna.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## ▶ RESUME HERE (handoff 2026-07-06)
**State:** Phases 1-6 SHIPPED + committed to master (`feat(lammps): …`). LAMMPS is a
full NADOC engine: detect/install (MD Engines panel + `scripts/lammps_doctor.py`),
native oxDNA→LAMMPS transcoder + runner (FIRE soft-start), managed jobs + REST
(`/api/lammps/jobs`), and a full **"Visualizations & processing"** view (display / RMSF /
deviation / trajectory) that reuses the oxDNA backend (`oxdna_health`) + frontend
(`oxdna_display` pure mappers) verbatim. Live-verified end-to-end on a 14,485-nt design.
**MPI parallel run VERIFIED (2026-07-06)** — see the "MPI parallel — VERIFIED" block below.
(The run/viz UI now lives in the unified Simulate list, not a dedicated panel — see the
2026-07-10 note above.)

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
- Detection: [backend/core/oxdna_runner.py](../../../backend/core/oxdna_runner.py) —
  `find_lammps()` (`$LAMMPS_BIN` → `lmp`/`lmp_mpi`/`lmp_serial` on PATH →
  `~/lammps/build/lmp`) + `lammps_supports_cgdna(path)` (runs `lmp -h`, greps stdout
  for `oxdna`/`cg-dna`; cached by (path, mtime) — the LAMMPS analog of
  `oxdna_supports_cuda`). `lammps_available()` mirror added.
- Registry + plan: [backend/core/engines.py](../../../backend/core/engines.py) —
  `LAMMPS_REPO`, `"mpi"` toolchain probe (mpirun/mpiexec/mpicxx/mpic++),
  `_lammps_plan()`/`_lammps_commands()` (**auto, target CPU/CPU (MPI), never CUDA**
  — unlike `_source_build_plan`), the `lammps_oxdna` row in `engines_status()`, and
  a **CG-DNA-degraded** block (installed but built w/o CG-DNA → degraded + rebuild
  plan, no GPU condition — mirrors the oxDNA CUDA-degraded case). Added to
  `installable_engine_keys()`.
- Auto-build: [backend/core/engine_install.py](../../../backend/core/engine_install.py) —
  `install_steps("lammps_oxdna")` (shallow clone → cmake w/ the 3 pkgs + BUILD_MPI
  when `tools["mpi"]` → `cmake --build`), `_verify` maps to `find_lammps`. Streams
  over the same `/ws/engines/install` WS; `NADOC_ENGINES_FORCE_MISSING=lammps_oxdna`
  simulation switch works.
- Panel: [frontend/src/ui/md_engines_logic.js](../../../frontend/src/ui/md_engines_logic.js)
  — `ENGINE_ORDER` gains `lammps_oxdna` (after `oxdna`); `actionLabel` now reads
  optional `install.degraded_action_label`/`degraded_guided_label` so LAMMPS's
  degraded rebuild says "Rebuild with CG-DNA"/"Add CG-DNA…" instead of the oxDNA
  default "Rebuild for GPU"/"Enable GPU…". No `md_engines.js` change (rows render
  generically). **main.js LOC Δ = 0** (nothing touched).
- Doctor: [scripts/lammps_doctor.py](../../../scripts/lammps_doctor.py) — sibling of
  `oxdna_doctor.py`; reuses `engines_status()` + `install_steps`; `--fix` builds.
- Guide: [docs/lammps_setup.md](../../../docs/lammps_setup.md) (linked from the panel via
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
- Transcoder (pure): [backend/physics/lammps_interface.py](../../../backend/physics/lammps_interface.py)
  — `exyz_to_quat` (verbatim port), `parse_topology`/`parse_configuration`,
  `build_data_file(top,conf)` (atom types A/C/G/T→1-4, positions+quats, FENE bonds
  from `n3`, box encloses+min-edge, **raises on unsequenced/'N'**),
  `LammpsInputParams`+`build_input_file` (the 6 oxdna2 pair overlays + `oxdna2/fene`
  + `fix nve/asphere`+`fix langevin` idiom from the shipped examples, custom dump w/
  quaternion cols). Uses `units lj` (oxDNA's native units = NADOC's conf.dat units).
- Runner: [backend/core/lammps_runner.py](../../../backend/core/lammps_runner.py) —
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
