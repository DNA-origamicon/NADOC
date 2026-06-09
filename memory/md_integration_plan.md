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

### 4. File type and wrapping details leak into the UI

Today users must choose `.gro/.tpr + .xtc` for GROMACS or `.psf/.pdb/.dcd` for
periodic NAMD. They also need to know when a trajectory needs `view_whole.xtc`,
when DCD frames are partially written, and how to stay safe-back from the tail.

Needed:

- A job-centric trajectory endpoint: `GET /api/md/jobs/{job_id}/frames/latest`
  and WebSocket `subscribe`.
- The UI should show "Latest positions" and "Playback" without exposing file
  extensions.
- Backend should select the correct topology/trajectory internally.
- Backend should manage wrapping/whole-molecule transforms and report a warning
  only if it cannot do so.
- For NAMD DCD, add server-side DCD frame streaming analogous to the GROMACS
  `/ws/md-run` path, so users do not manually load PSF/PDB/DCD.
- For periodic jobs, the server should know the periodic tiling metadata and
  provide already-aligned design-space frames.

### 5. No unified protocol presets

Recent experiments show that DNA origami MD is not a single universal config.
The UI should expose presets with short explanations and advanced override
drawers.

Suggested presets:

- `Quick Geometry Check`: dry or implicit, short, restrained, designed to catch
  topology/clash errors.
- `Explicit Solvent Stabilization`: TIP3P + NaCl + Mg/MGH, long minimization,
  restrained NVT/NPT, no unrestrained production by default.
- `Slow Restraint Release`: segmented k ladder with health gates at 10/50/100%.
- `Periodic Segment Probe`: 21 bp / 2-period periodic cell, fixed-Z handling,
  wrap bonds, and periodic visualization.
- `Full Origami Production Candidate`: only enabled after stabilization gates
  pass; defaults to dense ENM-retained production, matching published
  DNA-origami practice. Fully unrestrained production is an advanced research
  branch, not the default success criterion.

Advanced settings should include:

- engine: NAMD/GROMACS
- solvent: none/implicit/explicit
- ion model: bare Mg vs MGH, NaCl/MgCl2 concentrations
- temperature ladder
- pressure coupling mode
- restraint family: positional, dense ENM, Watson-Crick, hybrid
- restraint k ladder and stage lengths
- timestep/fullElectFrequency/rigidBonds
- GPU options and thread/device selection
- health gate thresholds and stop/continue policy

### 6. UI needs MD progress as a first-class panel

The existing MD panel is playback-oriented. Add a job-oriented MD workspace:

- Primary button: `Run MD`
- Preset selector with sensible defaults
- "Advanced" disclosure for parameters
- Job list with status chips
- Stage timeline: minimization -> warmup -> pressure settle -> restraint ramp
  -> production
- Segment gates shown as 10%, 50%, 100% dots with pass/fail/warning states
- Live metric cards:
  - temperature
  - pressure
  - volume
  - base-pair health
  - Watson-Crick health
  - speed
  - latest frame/time
- Live 3D toggle:
  - current CAD design
  - latest MD positions
  - difference/amplified displacement
  - base-pair failure highlights
  - periodic tiling preview if relevant
- Output log should be collapsed by default and translated into user-level
  messages, while raw logs remain downloadable.

The user should see "50 K NVT, 50% checkpoint passed" rather than needing to
read NAMD ENERGY lines.

## Proposed Architecture

### Backend modules

Create:

- `backend/core/md_job.py`
  - dataclasses/Pydantic models for `MdJob`, `MdStage`, `MdSegment`,
    `MdHealthSample`, `MdArtifact`.
- `backend/core/md_protocols.py`
  - protocol presets and config generation for NAMD/GROMACS/periodic jobs.
- `backend/core/namd_runner.py`
  - launch/stop NAMD, parse logs, manage restart files, segment sequencing.
- `backend/core/namd_metrics.py`
  - ENERGY/TIMING/PERFORMANCE parser.
- `backend/core/md_health.py`
  - reusable C1'/Watson-Crick analysis with DCD tail-safe behavior.
- `backend/core/md_frame_stream.py`
  - server-side frame loading/alignment for DCD/XTC, hiding format details.
- `backend/core/md_artifacts.py`
  - job directory layout, manifests, safe cleanup, downloads.

Reuse:

- `namd_solvate.py` for explicit-solvent and MGH package construction.
- `periodic_cell.py` for periodic package construction.
- `gromacs_package.py` for GROMACS presets.
- `md_metrics.py` for existing GROMACS metrics.
- `atomistic_to_nadoc.py` frame alignment ideas.

### API

Add:

- `POST /api/md/jobs`
  - body: preset + optional advanced overrides
  - returns job id and initial estimate
- `GET /api/md/jobs`
- `GET /api/md/jobs/{job_id}`
- `POST /api/md/jobs/{job_id}/start`
- `POST /api/md/jobs/{job_id}/stop`
- `POST /api/md/jobs/{job_id}/resume`
- `GET /api/md/jobs/{job_id}/artifacts`
- `GET /api/md/jobs/{job_id}/download/{artifact}`
- `WS /ws/md-jobs/{job_id}`
  - emits progress, metrics, health, latest-frame-ready, log summary
- `WS /ws/md-frames/{job_id}`
  - seek/latest playback without file picking

### Job directory layout

Use:

```text
workspace/md_jobs/<job_id>/
  job.json
  design_snapshot.nadoc
  protocol.json
  package/
    B_tube.psf
    B_tube.pdb
    forcefield/
    mgh_extrabonds.txt
    restraints/
  stages/
    00_min/
    01_050K_NVT_k20/
    ...
  output/
    restarts/
    trajectories/
    logs/
    health.jsonl
    metrics.jsonl
```

The user never sees this by default. Advanced users can open/download artifacts.

## Implementation Plan

### Milestone 1: Productize Current NAMD Health Runner

Purpose: make the F018/F020 workflow reproducible from NADOC without manual
commands.

Tasks:

- Move C1'/Watson-Crick monitor code into `backend/core/md_health.py`.
- Move segmented runner logic into `backend/core/namd_runner.py`.
- Add NAMD log parser for temperature/pressure/volume/ns/day.
- Add an `Explicit Mg/MGH Slow Release` protocol preset that generates:
  - MGH explicit-solvent package
  - DNA restraint PDB
  - segmented minimization/warmup/release configs
  - health gates at 10%, 50%, 100%
- Add a small API to create/start/stop one NAMD job.
- Store `job.json`, `health.jsonl`, and `metrics.jsonl`.

Acceptance:

- From current design, one API call creates a runnable MGH slow-release job.
- NAMD starts from the server.
- Health checks run after every segment.
- Failure stops the job and records a human-readable reason.

### Milestone 2: MD Job UI

Purpose: replace manual terminals with a NADOC-native progress view.

Tasks:

- Add a `Run MD` button to `frontend/src/ui/md_panel.js` or a new
  `md_jobs_panel.js`.
- Add preset selector and advanced drawer.
- Add job timeline and metric cards.
- Subscribe to `WS /ws/md-jobs/{job_id}`.
- Surface health gates with pass/fail/warn states.
- Use `op_progress.js` for preparing/building stages.
- Add stop button and "continue despite warning" only for advanced mode.

Acceptance:

- User can launch a preset from NADOC.
- User sees stage, segment, percent, temp, pressure, base-pair health, speed.
- User gets a clear failure message without opening a log.

### Milestone 3: Native Latest-Frame Visualization

Purpose: no manual PSF/PDB/DCD or VMD.

Tasks:

- Add server-side DCD frame reader for NAMD jobs.
- Add job frame streaming endpoint using job id rather than file paths.
- Reuse `md_overlay.js`, `atomistic_renderer.js`, and
  `periodic_md_overlay.js` as render targets.
- Add "Latest MD" toggle in the job panel.
- Add displacement amplification and base-pair-failure highlighting.
- For periodic jobs, encode tiling/window metadata in the job manifest and
  stream already-aligned periodic frames.

Acceptance:

- During a running NAMD job, NADOC can show the latest stable frame.
- Users can scrub completed frames without selecting files.
- The UI avoids partially-written frame errors by using backend safe-back logic.

### Milestone 4: Results and Design Feedback

Purpose: make MD useful for CAD decisions, not just simulation watching.

Tasks:

- Add "Save MD-relaxed reference" action that writes a `.nadoc` with persisted
  atomistic reference coordinates.
- Add "Compare to CAD" metrics:
  - per-helix displacement
  - local bend/twist
  - base-pair health map
  - crossover strain hotspots
- Integrate with existing atomistic reference extraction code from Exp23/Exp25.
- Add run summary report:
  - protocol
  - parameters
  - health timeline
  - final warnings
  - recommended next action

Acceptance:

- A completed stable restrained run can become the next CAD atomistic starting
  reference.
- The UI can identify where the model relaxed or failed.

### Milestone 5: Advanced Protocol Library

Purpose: support expert tuning without making basic users manage files.

Tasks:

- Protocol presets saved as JSON/YAML.
- UI import/export of protocol settings.
- Hardware benchmark cache per machine.
- GPU-resident toggle with benchmark warning.
- Restart from any stage/segment.
- Branch from any checkpoint with modified parameters.
- Add "clone job with changed parameter" workflow.

Acceptance:

- Advanced users can iterate like we do in experiments, but inside NADOC.
- Every branch keeps provenance and health summaries.

## Immediate Next Steps

1. Keep the current F020 MGH slow-release run as the reference implementation of
   segmented NAMD health gates.
2. Move monitors from `experiments/` to backend modules with tests on the
   existing F014/F020 trajectories.
3. Implement a minimal `MdJob` model and NAMD runner for one preset:
   `Explicit Mg-Hexahydrate Slow Release`.
4. Add backend job status endpoints.
5. Add the first UI pass: launch button, timeline, metric cards, and latest
   health table.
6. Add job-id-based latest-frame visualization.

## Design Principle

NADOC should keep the complexity, not hide the science. The default experience
should say:

> "Your design is equilibrating. The 100 K NVT stage is 50% complete. Base-pair
> health is 99.9%, pressure is still relaxing, and the latest structure is ready
> to view."

The advanced panel can show the exact NAMD config, force constants, restraint
ladder, ions, and logs. The main workflow should keep the user thinking about
the design, not about where the DCD landed.
