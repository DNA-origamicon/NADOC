# Visualization card (2026-08-12) — supporting detail

[Topic head](../../project_mrdna_panel.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Visualization card (2026-08-12)

- Job-snapshot Relaxed shape, 5-bp CG beads, trajectory RMSF, and aligned
  deviation-from-design are mutually exclusive visualization modes.
- `/mrdna/jobs/{id}/snapshot-geometry` prevents old jobs from painting onto changed
  live topology; `/rmsf` reconstructs and rigid-aligns saved CG trajectory frames;
  `/deviation` compares the relaxed frame with that snapshot after Kabsch alignment.
- Physical strain is deliberately unavailable: coarse mrDNA output lacks the
  oriented backbone/base sites required for FENE or Watson–Crick strain. Do not
  substitute spline-spacing distortion and label it strain.

## Fine-job progress and restart recovery (2026-08-12)

- `start_job` publishes `preparing` while the large mrDNA model is generated, then
  `_run_job` persists top-level `running` before ARBD begins. Never gate progress on
  a stage-only status while leaving the job itself `queued`.
- Fine progress is measured from the 12-byte DCD NSET header for the real three ARBD
  phases: coarse, twist-enabled fine, and frozen-twist fine. The bar reserves 100%
  for extraction/cache completion.
- ARBD uses relative config paths after chdir, so orphan detection must match
  `/proc/<pid>/cwd` as well as cmdline. Completed three-phase outputs are finalized
  after a server reload if the Python runner died before writing display caches.

Shipped 2026-07-02. Brought the mrDNA/ARBD coarse-grained relaxation engine to
the frontend as a managed job system + panel, mirroring the oxDNA panel
([[project_oxdna_relaxation]]). Before this, mrDNA existed only as the one-shot
`/ws/mrdna-relax` WebSocket + the pure `mrdna_bridge.py` library — no job store,
no panel, no display.
