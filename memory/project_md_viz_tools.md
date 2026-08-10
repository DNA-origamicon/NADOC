---
type: project
status: active
authority: canonical
review_after: 2026-10-01
---
# MD visualization tools

Canonical state for Display MD, trajectory playback, RMSF/flexibility maps, solvent/ion/box
overlays, alignment, and atomistic/surface representations. Detailed incident history is in
[the archive](project_md_viz_tools_archive.md).

## Current state

- Readiness is an explicit state with a reason, not a generic on/off dot.
- All representations honor the same “Align to design pose” choice.
- NAMD atom mapping prefers the persisted segid-to-chain metadata and frozen `design.json`; child
  jobs inherit those artifacts or resolve them through their parent lineage.
- Explicit solvent transport uses the `NSLV` binary format. Every optional block is described by
  the header; water, ions, and box can be enabled independently.
- Water is shell-filtered or whole-box; ions are complete and rendered per species; the periodic
  box uses the same display affine as DNA.
- Trajectory playback prebuild is visible on the play button. Scrubbing may fetch one frame, while
  smooth playback requires the prepared runway/cache.
- The flexibility map drives every representation. For NAMD, all-atom modes use the simulation's
  own atom topology at trajectory-average, PBC-repaired/Kabsch-aligned coordinates; surface mode
  builds the mean molecular envelope and carries the same per-nucleotide RMSF onto its vertices.

## Binding invariants

- Simulation-job selection and visualization ownership are separate. Deselecting leaves the active
  visualization intact. In the NAMD tab, selecting a different job retargets Display MD to that
  job's latest frame and recomputes an active flexibility map or occupancy cloud for that job; an
  active trajectory is instead turned Off because scrub/playback state must never cross job identity.
  Other queued/terminal-job inspection does not implicitly replace visualization run controls.
- The display affine is computed once by the coordinate path and handed to every overlay; never
  re-derive alignment independently for solvent or the box.
- Analyze the job's frozen topology, not whichever design is currently open.
- A binary header must describe exactly the blocks written. Test every on/off combination.
- Frame-varying solvent membership is capacity-allocated and snapped, never interpolated by index.
- The ion legend and renderer must describe the same species source.
- Atomistic mapping failures return the specific missing-artifact/mismatch reason.

## Open work

- A runway-ahead playback mode could start before the entire atomistic trajectory is cached, but
  it needs an explicit stall/resume design; it is not currently selected work.
- Continue consolidating duplicated trajectory/display mapping paths when a concrete caller is
  touched, with an integration test through that caller.

## Verification

Run focused frontend/backend tests and exercise the affected representation in the app. Solvent,
alignment, and overlay changes require visual comparison on a representative completed job.
