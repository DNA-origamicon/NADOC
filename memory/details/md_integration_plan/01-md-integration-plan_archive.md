# MD Integration Plan — historical evidence

[Topic head](../../md_integration_plan.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

# MD Integration Plan

Goal: NADOC should make molecular dynamics feel like a native design workflow,
not an external file-management exercise. The default path should be a single
button that prepares, runs, monitors, visualizes, and summarizes a simulation.
Advanced users should still be able to inspect and tune the protocol without
needing to know VMD, Tcl, wrapping commands, DCD/PSF/PDB quirks, or run
directories.

## Current Building Blocks

### Export and setup

- `backend/core/namd_package.py` builds a complete dry NAMD package with
  CHARMM36 DNA topology generated in pure Python. This removed the older need
  for VMD/psfgen just to complete angles and dihedrals.
- `backend/core/namd_solvate.py` builds explicit-solvent NAMD packages using
  GROMACS for water placement, Python ion replacement, CHARMM36/CUFIX force
  fields, PME/NPT configs, and bundled launch scripts.
- `backend/core/namd_solvate.py` now supports Mg-hexahydrate placement as
  `MGH` residues, plus `mgh_extrabonds.txt` Mg-O restraints. New packages use
  the published-style MGH Mg-O restraint default (`k=1 kcal/mol/A^2`,
  `r0=1.94 A`) rather than the older overly stiff `k=500` placeholder.
- `backend/core/gromacs_package.py` builds GROMACS packages, including solvated
  runs and oxDNA-pre-relaxed package generation.
- `backend/api/crud.py` already exposes exports for PDB, PSF, NAMD bundle,
  NAMD-complete, GROMACS-complete, GROMACS background jobs, and oxDNA-assisted
  GROMACS jobs.
- `backend/core/periodic_cell.py` builds periodic 21 bp / multi-period NAMD
  packages with wrap bonds, periodic solvation, fixed-Z workflows, and
  generated phase configs.

### Monitoring and analysis

- `experiments/exp25_full_origami_relaxation/scripts/basepair_monitor.py`
  identifies reference C1' base pairs, watches a growing DCD, writes JSONL
  health metrics, and can terminate NAMD on trip.
- `experiments/exp25_full_origami_relaxation/scripts/watson_crick_monitor.py`
  computes a stricter Watson-Crick heavy-atom proxy. This caught failures that
  C1' distance alone missed.
- `experiments/exp25_full_origami_relaxation/scripts/run_segmented_health_checks.py`
  runs segmented NAMD stages and triggers C1' plus Watson-Crick checks at
  staged boundaries such as 10%, 50%, and 100%.
- `experiments/exp23_periodic_cell_benchmark/check_progress.py` parses NAMD
  logs and can generate health plots for periodic runs.
- `backend/core/md_metrics.py` parses GROMACS logs, counts frames, and derives
  trajectory time and ns/day.
- `backend/api/ws.py` streams GROMACS trajectories over `/ws/md-run`, aligns
  frames to the current NADOC design, and supports seek/latest playback.

### Visualization already present

- `frontend/src/ui/md_panel.js` provides a Molecular Dynamics panel with
  server-side file browsing, topology/trajectory loading, playback controls,
  live polling, speed/stride controls, opacity, bead size, amplification, and
  representation modes.
- `frontend/src/scene/md_overlay.js` renders MD bead overlays inside NADOC.
- `frontend/src/scene/atomistic_renderer.js` supports atomistic/ball-stick style
  rendering for streamed frames.
- `frontend/src/ui/periodic_md_panel.js` loads PSF/PDB/DCD locally, parses DCD
  headers and frame slices, scrubs large trajectories without loading the whole
  file, and can apply periodic frames back onto the design preview.
- `frontend/src/scene/periodic_md_overlay.js` renders periodic MD atoms,
  ball-and-stick bonds, DCD frames, and alignment/tiling for periodic windows.
- `frontend/src/scene/md_segmentation_overlay.js` and the periodic panel expose
  some design-window segmentation concepts useful for displaying which regions
  are periodic, deviant, or end regions.
- `frontend/src/ui/op_progress.js` provides a reusable progress overlay with
  determinate and indeterminate modes plus cancellation support.

## Key Gaps

### 1. No first-class MD job model

Current MD work is split between exports, ad hoc experiment scripts, local run
directories, and file-picker playback. NADOC needs a persistent MD job object:

- `job_id`
- design snapshot hash and name
- engine/protocol: NAMD explicit, NAMD periodic, GROMACS, oxDNA pre-relax
- physical system summary: atoms, water, Na, Cl, Mg/MGH, box dimensions
- stage plan: minimization, NVT warmup, NPT, restraint release, production
- current stage/segment, percent complete, wall time, ns/day
- health metrics over time
- latest available frame
- artifacts: topology, coordinates, trajectory, logs, restarts, health report
- status: queued, preparing, running, paused, failed, stopped, completed

The job model should live server-side and be persisted to disk as
`md_jobs/<job_id>/job.json` so sessions survive browser refreshes.

### 2. NAMD is not yet integrated into the API/runtime loop

GROMACS export jobs exist, and GROMACS trajectory streaming exists. NAMD package
generation exists, but NAMD execution and NAMD health streaming are still mostly
experiment scripts.

Needed:

- `POST /api/md/jobs` to create a job from the current design and selected
  protocol preset.
- `GET /api/md/jobs` and `GET /api/md/jobs/{job_id}` for job listings/status.
- `POST /api/md/jobs/{job_id}/start`, `/pause`, `/stop`, `/resume`.
- A background runner that launches NAMD, tails logs, parses ENERGY/TIMING
  lines, and emits job events.
- A stage runner that uses segmented configs so health checks happen naturally
  at 10%, 50%, and 100% without manual intervention.
- An artifact manager that hides directory names but exposes safe downloads for
  advanced users.

### 3. Health checks are experiment scripts, not product services

The monitors need to become backend modules, not scripts under `experiments/`.

Move/adapt:

- `basepair_monitor.py` -> `backend/core/md_health.py`
- `watson_crick_monitor.py` -> `backend/core/md_health.py`
- NAMD log parsing -> `backend/core/namd_metrics.py`
- stage report writing -> reusable `MdHealthSample` records

Health signals to expose:

- C1' paired fraction
- Watson-Crick reference-relative fraction
- mean and p90 H-bond proxy distance
- temperature, pressure, pressure average
- volume and volume drift
- performance ns/day
- fatal-error/sentinel detectors
- stage-specific gates and current pass/fail state

Health policy should be explicit. Example default gates:

- `C1' paired >= 90%`
- `Watson-Crick reference-relative >= 85%` during restrained warmup
- no NAMD fatal errors
- temperature within a stage-dependent tolerance after warmup grace
- pressure allowed to be extreme during fixed-volume minimization/NVT, then
  expected to settle during NPT
