# 4. File type and wrapping details leak into the UI — historical evidence

[Topic head](../../md_integration_plan.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

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
