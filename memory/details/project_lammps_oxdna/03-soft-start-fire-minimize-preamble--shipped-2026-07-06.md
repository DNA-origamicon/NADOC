# Soft-start (FIRE minimize preamble) — SHIPPED 2026-07-06 — supporting detail

[Topic head](../../project_lammps_oxdna.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

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
- Backend converter ([lammps_interface.py](../../../backend/physics/lammps_interface.py)):
  `quat_to_exyz(q)→(a1,a3)` (inverse of `exyz_to_quat`, cols of the rotation matrix)
  + `lammps_dump_to_oxdna_traj(dump_text, out)` — parse the dump (sort atoms by id →
  oxDNA/NADOC order), write an oxDNA `.dat` trajectory. Round-trips to 2e-15.
- Endpoint ([routes_lammps.py](../../../backend/api/routes_lammps.py)):
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
- [lammps_display.js](../../../frontend/src/ui/lammps_display.js) — lean controller
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
- [lammps_interface.py](../../../backend/physics/lammps_interface.py) (pure): `LammpsForceSpec`
  dataclass (`force`/`anchor_ids`/`anchor_stiff`/`wall`); `compress_id_ranges`
  (atom-id list → compact `A:B` group arg); `axis_wall_from_extent` (dir+extent →
  `(face,coord)`, raises on non-axis-aligned); `build_force_fixes` (spec → fix lines);
  `boundary_line` (p-p-p unless walled); `build_input_file(p, force_spec=None)` injects
  the fixes at the TOP of the production block (post-minimise, so `spring/self` tethers
  to production-start positions = oxDNA `pos0`). `OXDNA_LENGTH_UNIT`/`NM_TO_OXDNA`/
  `DEFAULT_ANCHOR_STIFF` mirrored locally (asserted == `constants` in tests).
- [lammps_runner.py](../../../backend/core/lammps_runner.py): `resolve_lammps_forces(design,
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
