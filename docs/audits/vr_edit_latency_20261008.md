# VR edit latency investigation — 2026-10-08

The original `workspace/Circle_spiral.nadoc` was imported into an isolated
workspace: 24 helices, 195 strands and 11,997 nucleotides. Full representation,
production Desktop 3D During VR preference off, SteamVR/OpenXR on the attached
Vive, and simulated controller trajectories drove the real native/browser/API
pipeline. The source file was never edited. This is runtime/stereo evidence,
not a human through-lens comfort assessment.

## Reproduction and cause

Two successful baseline edits took about 27 seconds each. The reported minute
was not reproduced exactly. The underlying topology mutation took 0.26–0.40 s;
the delay was VR scene export/publication, not the shared desktop resize solver.
Each release exported twice (12.2–13.3 s per export): autosave advanced the
revision while export ran, so the correct geometry was discarded and retried.

Profiling found repeated scalar spline and slab calculations, an avoidable
quadratic domain lookup, repeated selection/style serialization, and construction
of coarse geometry that a Full-only request subsequently discarded. HTTP polling
also competed with the CPU export for the Python interpreter lock. Native bond
feedback parsing blocked a render frame for 11–14 ms after each edit.

## Changes

- Batch centripetal spline evaluation and native slab arithmetic with NumPy.
  Preserve the scalar placement authority as the invalid-input diagnostic path;
  keep tolerances, native registration, topology and molecular constants.
- Index domain palette lookup; cache immutable export-local identities, ownership
  and palette strings; skip unrequested coarse representation construction.
- Publish a completed snapshot when only autosave persistence wrappers changed.
  Genuine concurrent scene edits still reject publication. Compare all other
  model fields, including future fields, and all non-signoff metadata.
- Run canonical export in one warmed spawned process, separate from HTTP polling.
  The parent retains revision, document, placement-review and publication checks.
  Shut the worker down with the VR backend lifecycle; preserve structured errors.
- Start VR refresh as soon as the shared desktop resize response is decoded,
  overlapping subsequent desktop store/geometry synchronization.
- Parse large ligation/bond feedback asynchronously and install complete vectors
  atomically. Poll the small scene manifest every three frames. Preserve the
  existing 1 ms per-frame staged-upload budget and old-scene visibility.
- Omit inactive Nick bond coordinates from resize inspector replies, keeping
  automated controller playback timely without altering Nick targeting.

The exporter/publication/feedback fixes benefit other VR scene edits too.
Desktop resize already used the same mutation endpoint and collision rules;
those remain shared. Slab batching also benefits desktop geometry generation.

## Verification and evidence

Paired exports of the original design took 10.4–11.3 s before and 1.50–1.65 s
after, outside the live VR session. Record identities and structure are unchanged;
the largest numeric wire delta was 2.67e-17 (floating-point roundoff). Regression
checks compare vectorized poses against the untouched scalar authority, reject
corrupt supplied poses with the same site diagnostics, and compare spline samples
against the desktop Three.js implementation.

Evidence is under `.development-artifacts/vr-edit-latency/`: `baseline-measured`
is the successful baseline; `final-live` is the final four-profile matrix.
Earlier failed observation attempts and intermediate profiles are retained.
The initial inspector payload was too large for timely controller playback;
the first imported end selection was blocked by existing neighboring staples.
The reusable probe now chooses two genuinely free termini without changing
source topology or bypassing collision limits. Existing Fine Routing parents
are handled when checking feature history.

Reproduce the complete runtime check:

```sh
scripts/validation_guard.sh uv run python -m tools.vr_workflows.tool_frame_audit \
  --tools end_resize --representations full --design workspace/Circle_spiral.nadoc \
  --validate --output .development-artifacts/vr-edit-latency/new-run
```

The existing **Debug → VR Tours & Tests → Tools · Authoring → Resize selected
ends** entry remains available. Imported-design runs verify +12/-6 on two ends,
selection retention, independent Undo, stereo/mirror arrow pixels, operation
latency, application submission cadence and compositor GPU/repeated/drop data.
Captures are outside measured commit intervals. Timing instrumentation adds
some overhead; application cadence is not headset scanout frequency.

## Final runtime results

All four profiles passed on the final source. Each row is extension / shortening;
latency ends only when the native scene revision and relocated handles are both
acknowledged. Each operation also retained selection and passed independent Undo.

| Controller profile | Extend | Shorten | Commit cadence | Repeated / dropped |
| --- | ---: | ---: | ---: | ---: |
| steady_fast | 3.09 s | 2.97 s | 89.53 / 89.52 FPS | 0 / 0 |
| steady_deliberate | 3.26 s | 3.14 s | 89.53 / 89.53 FPS | 0 / 0 |
| variable_fast | 3.03 s | 2.97 s | 89.53 / 89.53 FPS | 0 / 0 |
| variable_deliberate | 3.36 s | 3.08 s | 89.53 / 89.53 FPS | 0 / 0 |

Median latency was 3.08 s, range 2.97–3.36 s, versus approximately 27 s before.
This is about nine times faster, close to but not consistently below the 3 s
short-term ceiling; the sub-second objective is not yet achieved. The remaining
budget includes roughly 1.7 s for canonical full export, desktop response
transport/decoding, and native parsing/staged activation. A further large
reduction will require avoiding full-scene regeneration/transport on local edits
with correctly invalidated incremental updates; simply increasing render-thread
upload work would risk headset frame deadlines.

Across all eight commit intervals, application cadence was 89.52–89.53 FPS on the
90 Hz runtime, with zero long submission gaps and zero compositor repeated or
dropped frames. Non-runtime-wait wall time p95 was 1.55–2.19 ms; its largest frame
was 5.36 ms. GPU p95 was 3.45–3.84 ms. These are separate measurements, not numbers
to add as a combined frame cost. Baseline commit cadence was about 89.3 FPS.
Stereo committed captures were inspected in both eyes: the full circular model
and relocated cyan arrows remain visible and consistent. Automated pixel checks
also cover hover, preview, the mirror, and a negative offscreen control.

The input SHA-256 still matches the matrix manifest after all runs. No temporary
`nadoc-end-resize-tour-*` workspace or `__e2e__*` workspace artifacts remained.

## Regression-run conditions

The first `just test-smart` chose FAST with FULL deferred. It was interrupted
at 99% (10,244 passed, 44 failed, 90 skipped) after a disk-guard fake waited on its
simulated process: root `/tmp` had only 4.8 GiB free, below the real 5 GiB guard.
Most failures were the same disk condition in mocked job tests. The real guards
were not weakened. The rerun uses an archive-backed temporary directory through
a short `/tmp` symlink (native Unix socket path limits still apply).

Slow-test triage found no per-test budget violators. The 240 s aggregate was
inflated by the stalled disk test; no tests were reclassified and no timing
limits changed. An old native IPC executable also crashed; its production-handler
target was rebuilt with the system toolchain, and the rerun clears the Conda
`LD_LIBRARY_PATH` just as the live VR launcher does.

The seek-preview quaternion parity assertion originally required bit equality.
Vectorized arithmetic differed by 5.56e-17 in one center component. It now compares
every center/quaternion component to the untouched scalar authority with zero
relative tolerance and 2e-14 absolute tolerance, matching the new placement parity
coverage. No golden geometry or molecular registration was regenerated.

## Final software checks

- Four final Vive/OpenXR motion profiles: all passed (eight edits plus Undo).
- Native viewer and ligation/scene-refresh tests built; both native tests passed.
- Final focused Python checks: 50 passed in 3.94 s, including real spawned export,
  concurrent autosave/edit handling, source parity, startup/shutdown, seek preview,
  and the environment-sensitive worker/report tests.
- Earlier focused placement/VR checks: 167 passed; later export/representation
  checks: 118 passed. These overlap and are not summed as distinct tests.
- `just test-frontend`: 647 files passed, 7,709 tests passed, one skipped.
- `git diff --check`: clean.

The archive-backed `just test-smart` selected FAST and finished with 10,289 passed,
three failed, 90 skipped. Two Alpine worker failures were caused by pytest resolving
the archive symlink into a Unix socket path longer than the OS permits; both passed
in the final short-path focused run. The remaining native IPC test runs an existing
radial-history self-check before opening its socket. That check requires the radial
menu to be closed while the unchanged production `setPending()`/`open()` contract
keeps pending feedback visible. Neither that production behavior nor its assertion
was changed by this task. Thus the broad suite is not fully green.

The archive run also flagged two over-budget tests. With normal short temporary
paths, the placement-report subprocess test took 0.46 s and the worker survival
test 1.04 s. This was an environmental slowdown/failure, not newly heavy work;
no tests were reclassified and no budgets increased.

The selector's outstanding broad-suite debt is preserved verbatim:

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
Only request `just test-session` when a broad/full sweep is actually needed.
```

Frontend production build also passed (5.84 s). Temporary validation workspaces
and their archive symlink were removed; `cleanup.json` records the inventory.
About 8.75 GiB of useful baseline, failed-attempt and final stereo/timing evidence
is retained under the task artifact directory. The original source hash is unchanged.
