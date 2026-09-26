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

- Trajectory/startup performance (2026-09-26, batch 3): compact MD frames now
  reach the atomistic renderer directly, avoiding sparse serial-span expansion.
  One immutable page-order mapping is cached and content-checked across pages;
  topology rebuilds invalidate it. Missing coverage retains the expansion fallback.
  Superseded queued interactive scrubs are dropped before reading; active reads
  may fill the cache, while explicit preparation/playback requests stay protected.
  First-open sphere/bond matrices use direct packed writes with unchanged math.
  GPU colour/alpha uploads are skipped when final Float32 values are unchanged;
  instance matrices/colours use dynamic usage from creation. Paired CPU medians
  at 150k atoms: construction 1.4–1.6×, compact snapshots ~1.6×; the sparse fixture
  removes 28.8 MB coordinate scratch. These exclude network/shader/render time.
  Browser A/B matched eight pixel states and picking; unchanged repaint uploads
  fell from 10 calls / 169,152 bytes to zero on the 5,040-atom fixture.
  See [batch 3 audit](../docs/audits/loading_open_20260926/README.md).

- Surface/colour performance (2026-09-26): scalar simulation surfaces reuse
  compatible geometry/normal/colour/alpha buffers; content comparisons detect
  mutable coordinate/connectivity payloads and attribute versions invalidate
  normals after ordinary animation. Changed geometry retains exact Three.js
  normals; incompatible buffers are disposed. Atomistic colouring resolves each
  endpoint and distinct sRGB colour once per repaint, with one alpha dirty mark
  per mesh. Caches expire per repaint to preserve mutable-map semantics.
  Paired CPU medians: large scalar refresh/recolour ~15×, fully moving scalar
  surfaces ~2.5×, cluster/scalar repaint ~2×, CPK selection ~5×. Browser A/B on
  5,040 atoms and 31,118 surface faces matched all 18 pixel states and picking
  for spheres, impostors, Phong and physical materials. No mesh decimation or
  end-to-end FPS claim. See [batch 2 audit](../docs/audits/surface_colouring_20260926/README.md).

- Active visualization performance (2026-09-25): atomistic interpolation computes
  each row once in a reusable Float64 workspace and writes sphere/bond buffers
  directly; live MD updates use the same allocation-free writers. Hidden atomistic
  representations skip interpolation work. Direct recorded-atom PBC placement
  batches equal-length strand medians and applies strand lattice shifts in one
  gather. Paired synthetic benchmarks: interpolation 3.0–4.4×, cluster interpolation
  ~4.7×, live frame updates ~1.9×, PBC preparation 2.5–2.6×. Coordinates and instance
  buffers compare exactly against the old paths. Browser check on a real 5,040-atom
  6hb fixture matched pixels/picking/colour/opacity across interpolation, snapshot
  and live updates. These are CPU-kernel gains, not measured end-to-end FPS.
  See [active-feature ranking and verification](../docs/audits/active_visualization_20260925/README.md).

- Guest presence (2026-09-23): compact guest initials in the Presenting toolbar;
  all participant chips (Me/Presenter included) stacked longest-name-first in the
  guest canvas upper left. Random host-assigned
  colors persist on reconnect; live SSE connections determine membership.
  Guest Share view publishes one camera pose: ping, 15-second chip glow, persistent
  glasses action, and smooth 0.9-second transition for guests/editor. Re-sharing
  replaces the pose; saved views survive guest disconnect until presentation end.
  Private job selection blocks presenter camera application. No live guest authority.
  Guest Follow uses the saved-view easing; Jump and Performance buttons are removed
  (metrics remain on Ctrl+P). Two local health flags drive red wifi/circuit warnings
  on guest/editor rosters; no hardware identifiers are collected.

- Guest visualization feedback (2026-09-23): shared nanopore paths use a validated
  thick-line export adapter; vector arrows retain their instance transforms/colors.
  Existing visualization progress is relayed as Loading visualization plus a bar.
  Host End clears the guest scene and displays Presentation ended. Updated hosts
  advertise `guest-visualizations-v1`; older active hosts need a later restart.

- Integrated presentation controls (2026-09-23): `viewer/presentation_controls.js`
  mounts a persistent Presenting indicator at the top center of `#canvas-area`.
  Glasses toggle camera sharing (initially off) through the native editor or current
  shared job; private job browsing pauses guests. End invokes the same host-stop
  action as the sharing dialog. The editor no longer offers Open presenter or the
  legacy Broadcast dialog entry. Camera authority transfers across native/job mode
  without a new guest invitation. Standard visualization tools remain available.
- Job sharing (2026-09-23): oxDNA/NAMD Visualizations headers expose green Share / red
  Stop sharing while a presentation invitation exists. Shared job identity is independent
  of private selection; switching selection pauses guests on the last published frame.
  Explicitly sharing another job moves the row dot and reuses the invitation. Stop selects
  native positions + Full in the editor and publishes the native model without ending the
  guest session. `viewer/job_sharing.js` owns the workflow; render patches are streamed at
  up to eight samples/s without preparing a full clip. See
  [viewer documentation](../docs/prepared_viewer.md#job-sharing-through-one-invitation-2026-09-23)
  for protocol limits and upgrade behavior.

- Job-list disk reads, status reconciliation and MD manifest/fingerprint decoration run in
  worker threads, preserving per-document context so polling cannot occupy the HTTP event
  loop while a part loads. mrDNA process discovery checks the command before resolving cwd.
  Peer reachability polls share in-flight work across tabs and cache completed results for
  10 seconds; healthy saved addresses skip reverse DNS, and probes have an 8-second total
  deadline. Background peer polls also suppress the editor operation modal. These probes
  do not transfer shared files. Regression coverage:
  `test_status_poll_responsiveness.py`, `test_collaboration_status.py`, and the existing
  cross-host checkout/address-migration tests in `test_project_collaboration_api.py`.
- Readiness is an explicit state with a reason, not a generic on/off dot.
- All representations honor the same “Align to design pose” choice.
- NAMD atom mapping prefers the persisted segid-to-chain metadata and frozen `design.json`; child
  jobs inherit those artifacts or resolve them through their parent lineage.
- Explicit solvent transport uses the `NSLV` binary format. Every optional block is described by
  the header; water, ions, and box can be enabled independently.
- Water is shell-filtered or whole-box; ions are complete and rendered per species; the periodic
  box uses the same display affine as DNA.
- Interactive NAMD playback starts with eight exact strided frames, then reads ahead in 16-frame
  pages. The rest of the selected trajectory fills in the background and remains cached for
  random scrubbing, within a 1.5 GiB coordinate budget. JSON fallback frames are normalized
  to float64 typed arrays, preserving precision and making their memory count toward that
  budget; one foreground page is retained even if that page alone exceeds the budget. Dense float64 heavy-atom caches omit
  empty serial slots; only the displayed frame expands into a reusable sparse scratch array.
  Foreground seeks precede the next background page. The panel reports the loaded count,
  fully buffered state, or memory limitation; stopping releases the retained stream.
  Frame readiness gates the shared playback clock; missing frames
  show buffering and stall rather than snap to a different sampled frame. Authored/ranged exports
  retain their full-preparation contract. Optional visible ion/box companions retain their own
  readiness gate; a package residue census proving no graphene suppresses invisible companion work.
- Playback uses a DNA-only PSF identity/bond table cached by file identities and complete design,
  direct DCD prefix reads with one-frame I/O lookahead, columnar MDAM topology, and MDAF v2 dense
  float64 coordinates plus original sparse serials. Synthetic/unsupported mappings fall back to
  the original reader. Metadata cache is private and bounded; up to three idle killable workers
  reuse imports/tables and expire after 30 seconds. No geometry is regenerated for supported jobs.
- The flexibility map drives every representation. For NAMD, all-atom modes use the simulation's
  own atom topology at trajectory-average, PBC-repaired/Kabsch-aligned coordinates; surface mode
  builds the mean molecular envelope and carries the same per-nucleotide RMSF onto its vertices.

- NAMD composite playback uses NTRJ v2: 12 floats per nucleotide (backbone,
  inward direction, measured ring-plane normal, measured ring centroid). Full applies
  those centers directly; native slab offsets remain the fallback for other overlays.
  Ring atoms are imaged relative to their residue anchor before centroid/plane fitting,
  including phosphate-less O5′ termini. Coarse and all-atom playback align against the
  same measured/junction-balanced display reference. Legacy NTRJ v1 and oxDNA frames
  remain readable.
- Atomistic base colors use strand/helix/bp/direction/copy identity. A strand can revisit
  the same bp index and direction on many helices; strand/bp/direction alone collides.

- `backend/core/md_frame_alignment.py` owns the rigid alignment and sequential inlier guard
  used by live coarse display and trajectory extraction. Per-reader periodic-image selection
  and atom mapping remain explicit; no pose/phase constants changed. The extraction matched
  its pre-refactor implementation exactly across 500 frame comparisons. Portable synthetic
  tests cover known rotations, nonrigid exclusion, independent reader state, and the inlier
  guard. Native and large-fixture checks remain separate (see `docs/maintenance_2026_09.md`).

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

### P5 loading performance audit (2026-09-15)

Real GPU browser, P5 stride 20: about 3.17 s from selecting trajectory loading to actual
ball-and-stick frame advance, with advisory cold archive pages and empty derived topology cache.
250 selected frames preserve every extracted atom/base value; cold read + alignment (~10.7 s)
matches raw HDD reads (~10.9 s). See `docs/audits/24hb_p5_trajectory_performance_20260915.md`
and `scripts/benchmark_md_playback.py` for scope, research, reproduction, and buffering limits.

Full-buffer follow-up: P5 stride 20 reaches first playback in 3.13 s and buffers all 302
selected frames in 32.09 s on the advisory-cold HDD. Six distant cached scrubs take 115–135 ms
including browser rendering, with zero coordinate requests. See the audit follow-up section.
