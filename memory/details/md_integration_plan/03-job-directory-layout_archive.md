# Job directory layout — historical evidence

[Topic head](../../md_integration_plan.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

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
