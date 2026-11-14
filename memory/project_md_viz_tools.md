---
type: project
status: active
authority: canonical
review_after: 2026-10-01
---

# MD visualization tools

## Topic navigation and current boundaries

Reorganized October 17, 2026. Read the retained contracts here, then only the
matching detail below. Dated results and old handoffs are not new verification
or authorization; current user instructions and `CLAUDE.md` take precedence.

Open work: consolidate duplicate trajectory/display mappings only when a concrete caller is touched, with integration coverage. Keep one shared display affine, frozen job topology, explicit atomistic mapping errors and job-owned visualization. Current-state details below include the October 12 periodic-image correction and September renderer/analysis work.

Canonical state for Display MD, trajectory playback, RMSF/flexibility maps, solvent/ion/box
overlays, alignment, and atomistic/surface representations. Detailed incident history is in
[the archive](project_md_viz_tools_archive.md).

## Current state

- Display MD measured slabs (2026-11-13): live WebSocket frames now reuse
  `md_base_frames` for ring centroids, plane normals, and named in-plane directions,
  including crossover inserts and O5'-anchored termini. `md_panel` preserves the
  `measured_base` marker; missing rings retain coarse fallback. Reset the cached ring
  layout on each load. Atomistic and Full use the same active design alignment
  reference (generated-model P sites had introduced a small representation-dependent
  offset). This is display-only; no design atoms or saved simulation inputs change.
  Read-only R1 local check: 2hb_2xT, August 5 2026 18:52 MDT, final available MGHH p50
  frame 29, all 98 centers within 9.2e-9 nm and plane normals within 7.5e-6 degrees
  of the real atomistic WebSocket reply. Browser replay verifies all 98 rendered
  slab centers one-to-one within 1e-5 nm and plane angles within .01 degrees.
  Evidence/reproduction scripts: `.development-artifacts/slab-audit/`; optional
  local app audit: `NADOC_SLAB_AUDIT=1` with `playwright.md-slab.config.js` (provide
  a temporary SCRYWRITE_TEST_WORKSPACE and clean it up after the run).
  Inspected `app/.../r1-base-closeup.png`; first overview retained separately because
  its bases were too small for visual review. Browser run uses real backend-recorded
  transport replies, not a live user session. Source file hash unchanged, temporary
  workspace removed and port5293 bridge credentials absent after both app runs.
  Checks: 5 measured-frame tests, 28 final WebSocket tests, 10,463 frontend tests
  (one skipped), lint; initial `test-smart` FAST passed 20,847 (90 skipped), FULL
  deferred because no test-dedicated session was open. The alignment-reference
  follow-up was checked by the final focused WebSocket run and real-run audit.

- Multi-overlay simulation refresh (2026-11-12): layers rebuild together on physical
  coordinate/scalar changes and retain the previous complete scenes while loading.
  Representation switching awaits job-owned heavy coordinates and Display MD's
  applied frame, including atom-to-CG wire reloads. Beads and Surface are enabled
  during simulation; Hull/Cylinders remain reference-only and temporarily use Full
  in existing overlay layers. Surface uses exact job meshes when available and
  the existing nucleotide-frame skinning for displays without a surface endpoint.
  Camera/separation follow display positions without resetting the camera on frames.
  `multi_overlay_simulation.spec.js` covers all nine supported styles, oxDNA live/
  relaxed/trajectory, Display MD, frame changes and Off restoration using intercepted
  simulation responses and a read-only duplex. Screenshots were inspected under
  `.development-artifacts/multi-overlay-app/`; the source hash stayed unchanged and
  temporary workspaces were removed. Full frontend suite: 10,462 passed, one skipped;
  final focused checks: 90 passed. Earlier browser attempts retained separately
  document binary-fixture and pre-navigation WebSocket-interception corrections.

- P1 RunPod periodic-image correction (2026-10-12): shared reassembly includes
  the intact, sequentially unwrapped assembly as a scored candidate and rounds
  strand-median lattice indices before scaling. Previously the circular-centroid
  pose could split an already intact 2HB across images; even-length ties could
  move strands by half a cell. Analysis/playback contexts now pass exact PSF
  segment IDs, including cached lightweight tables (version 5). On all 1,226
  frames of `7d5937e569c6`, mean phosphate RMSF is 1.038 → 0.288 nm and maximum
  design RMSD 2.886 → 0.870 nm. Integer shifts and within-strand displacements
  compare exactly; source data/topology unchanged. Reload/regenerate browser
  results computed before this fix. See `docs/audits/vr_palette_pbc_20261012.md`.

- Figure quality probe control (2026-09-26): the temporary eight-iteration
  comparison has been removed. Figure quality starts at 0.14 nm with an enabled
  probe slider; standard and figure presets remember independent radius values.
  Figure-quality regeneration happens on slider release. Native JSON/binary and
  simulation figure surfaces honor the chosen probe. Four smoothing iterations
  remain the default; grid resolution and atom geometry are unchanged.

- Active audit completed (2026-09-26, final batch): solvent matrices use the exact
  shared direct writers and upload only active instances; periodic images upload
  only changed Float32 position/color channels. Ball-and-stick water updates
  measured 2.05–2.73× faster (20k/100k waters). Unchanged protein trace refreshes
  reuse geometry while refreshing picking/centroid metadata; primitive snapshots
  detect in-place edits. Both part and assembly renderers share this factory.
  Trace-only synthetic refreshes measured 91–114× faster; cheap box/ovoid rebuilds
  remain unchanged after measurement rejected their cache. No particle sampling,
  tessellation or surface fidelity reduction. Evidence:
  `docs/audits/remaining_visualization_20260926/README.md`.

- Surface generation (2026-09-26, batch 4): object/cloud occupancy stamps the
  exact discrete spherical stencil with bounded NumPy scatter batches, avoiding
  full-volume scans per radius. Split surfaces group atoms once without changing
  strand/atom order; object-path nucleotide keys are resolved once per atom.
  Grid origins, radii, probe closing, marching cubes, smoothing and ownership
  remain unchanged. CUDA stencil closing is enabled by default when CUDA-enabled
  PyTorch is installed. Backend lifespan awaits a synthetic closing warm-up before
  accepting requests (import/context/convolution startup). Small workloads, memory
  limits and CUDA errors retain SciPy fallback; `NADOC_SURFACE_GPU=0` is a diagnostic
  CPU override. No enable flag is needed.
  The standard preset is a CG envelope; the beautiful design
  preset uses independent atomistic strand shells, while beautiful simulation
  frames currently use a fused shell. Neither is an analytical Connolly surface,
  and independent shells do not guarantee physical solvent gaps.
  Paired real-design checks preserve every vertex/face/identity: beautiful CPU
  generation improves 4.3–5.0×; warm CUDA reaches 7.2–8.7× versus the
  original path. Standard mode improves 1.17–1.25×. App preset toggles and original
  binary payload parity passed; all 28 new tests passed in the FULL suite (9,747 passed overall, 13 baseline
  failures unchanged). Default-on startup and app checks also passed.
  See [surface generation audit and external-method comparison](../docs/audits/surface_generation_20260926/README.md).

- [Current state — continued detail](details/project_md_viz_tools/01-current-state.md)

- [Current state — continued detail](details/project_md_viz_tools/01-current-state.md)

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

- Continue consolidating duplicated trajectory/display mapping paths when a concrete caller is
  touched, with an integration test through that caller.

## Verification

Run focused frontend/backend tests and exercise the affected representation in the app. Solvent,
alignment, and overlay changes require visual comparison on a representative completed job.

<a id="p5-loading-performance-audit-2026-09-15"></a>
- [P5 loading performance audit (2026-09-15)](details/project_md_viz_tools/02-p5-loading-performance-audit-2026-09-15.md#p5-loading-performance-audit-2026-09-15)
