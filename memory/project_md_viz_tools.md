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
