---
type: project
status: active
authority: canonical
review_after: 2026-10-01
---
# oxDNA relaxation and display

Canonical current state for local oxDNA relaxation, health gates, display, surfaces, and
CG-to-atomistic handoff. Historical phases and experiments are in
[the archive](project_oxdna_relaxation_archive.md).

## Current state

- Managed jobs persist their topology, initial configuration, design snapshot, stage plan,
  progress, health, and final display state.
- Relaxation uses staged minimization/MD with base-pair retention, backbone stretch, and energy
  convergence checks. Headless production defaults must be scientifically scaled, not mock-sized.
- Absolute-coordinate forces such as surfaces and anchors require `fix_diffusion = false`.
- The NAMD seed is a pure function of oxDNA coordinates and orientation; design transforms must not
  be applied a second time. Unpaired ssDNA is rigid-stamped during backmapping. Synthetic crossover
  inserts must be read with `include_extra_bases=True` and flow through the same
  `_frame_atomistic_overrides` used by the atomistic display, so their simulated CM/a1/a3 pose
  replaces the native placement. The seed's final global recenter preserves relative coordinates.
- Atomistic display uses vectorized stamping and compact binary transport. Fine molecular surfaces
  are generated per strand to preserve geometric separation rather than only coloring one fused mesh.
- The three-tab job wizard has a pure validation oracle and a reusable Playwright driver. Regression
  coverage traverses every engine variant plus Local, Alpine, and RunPod UI paths using a disposable
  two-helix design. Local prepared-job creation is wired; Alpine and RunPod selection/preview are wired,
  but remote creation is still deliberately blocked by the frontend launch boundary.
- Alpine adaptive-memory oxDNA was built and compute-node verified on 2026-08-27 (SLURM
  `31744722`, CUDA architectures 80/90). Remote submission should use
  `/projects/jojo6687/nadoc_jobs/nadoc_builds/oxdna-adaptive/install/bin/oxDNA` and set
  `LD_LIBRARY_PATH=/projects/jojo6687/nadoc_jobs/nadoc_builds/oxdna-adaptive/install/lib`.
  `DNAnalysis` is installed beside `oxDNA`; both binaries were verified against the bundled GCC
  runtime on an Alpine `acpu` compute node.
- RunPod validation on 2026-08-27 established both capability and correctness for the adaptive
  CUDA lists. Upstream allocated 140,997.86 MB and completed no step in 373 seconds for the
  451,584-nt nonuniform BigO assembly, while adaptive initialized at about 219 MB and ran at
  2.56054 ms/step. On a 597-nt control that forced capacity growth from 8 to 110, one-step
  energies/positions/orientations matched upstream exactly and velocity differences were at
  mixed-precision scale (maximum `2.98e-8`). Both completed a deterministic 10,000-step smoke
  test with about 1.7% adaptive overhead. The isolated validation spent $1.14834 of a $2 cap.

## Binding invariants

- Relaxed physical coordinates are display/simulation state and never write back to topology.
- Preserve the frozen job design for every downstream map, metric, export, and child job.
- Inserted/extra nucleotides need a disambiguating copy/index convention; a bare
  `(helix, bp, direction)` key is insufficient.
- Surface and field coordinates are absolute; do not enable diffusion removal for those runs.
- CUDA availability and WSL driver/toolkit problems are environment findings, not reasons to alter
  the scientific protocol silently.

## Open work

- The high-quality surface path is shipped; further ChimeraX matching would require a deliberate
  solvent-excluded/Connolly or adaptive-mesh project, not another coarse-bead tuning pass.
- Verify any remaining live/headless default disparity before using relaxation quantitatively.
- Keep oxDNA and NAMD child-package artifact propagation in parity.

## Verification

Use fast unit/integration tests for protocol rendering, health, mapping, and binary formats. Exercise
display changes in the running app. Run the wizard path regression with
`cd frontend && npx playwright test e2e/oxdna_job_wizard_paths.spec.js --reporter=list`; it intercepts
job creation and paid-provider calls and removes its generated design. Real oxDNA simulation tests are
heavy and test-session-only.
