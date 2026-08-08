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
  be applied a second time. Unpaired ssDNA is rigid-stamped during backmapping.
- Atomistic display uses vectorized stamping and compact binary transport. Fine molecular surfaces
  are generated per strand to preserve geometric separation rather than only coloring one fused mesh.

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
display changes in the running app. Real oxDNA simulation tests are heavy and test-session-only.
