---
type: project
status: active
authority: canonical
---
# VR human motion modeller

User requested 2026-09-22: archive the BEHAVIOR raw Vive dataset and begin a human
movement modeller for live VR and ScryWrite.

- Dataset root: `/media/jojo/Archive/NADOC_archive/datasets/vr/behavior-100/`.
  Original: `behavior_virtual_reality_v0.5.0.tar.gz`; extracted files:
  `raw/virtual_reality/*.hdf5`; `manifest.json` holds hash, bytes, source and inventory.
  `catalog.json` indexes tasks and frame counts. Optional `catalog --measure` scans
  durations/tracking; the retained lightweight catalog marks these fields null.
  Catalog verification: all 500 files opened, 2,254,200 frames, 102 source task labels;
  file bytes agree with the extraction manifest.
  Verified full gzip/tar read: 500 HDF5 recordings, 6,838,436,528 extracted bytes.
  Archive: 1,791,999,788 bytes; SHA-256
  `5b521af825660163aa616fc397b435218b94eaeaf03c65adc8d2d6a0f2729a17`.
  Separate `example.hdf5` is the upstream small example. Do not redownload to `/`
  or `workspace/` if Archive is absent. Preserve originals; redistribution license
  not established. This is BEHAVIOR-100 VR raw, not BEHAVIOR-1K robot data.
- Module: `tools/vr_motion/`; commands: `python -m tools.vr_motion --help`.
  Runbook: [human motion](../docs/vr_human_motion.md).
- Synthetic seeded minimum-jerk reach with overshoot/correction, endpoint bias,
  reaction interval and correlated position/orientation perturbations. Defaults are
  explicitly **uncalibrated**, not fitted population or tracking-error estimates.
- HDF5 import needs optional `h5py` (`uv run --with h5py ...`). Both hands, head,
  analog metadata, validity, source/hash retained. Use recorded `last_frame_dur`,
  NOT nominal simulation 30 Hz for human motion timing. Source commit and inspected
  writer/simulator files are retained alongside the dataset.
- Recorded source coordinates require explicit rigid registration plus optional
  controller-axis correction before live/Witness playback. No automatic floor/axis
  inference; no automatic extra noise; invalid tracking segments are rejected.
- Witness exports use existing format/parser. Live playback uses existing bridge,
  session/sequence checks, bounded pacing and input release; no HMD override.
  Analog inputs are not replayed in v1. Browser transactions require explicit flag.
- Verification: focused tests plus native application-handler IPC and native Witness
  parser; new modeller has not been exercised in physical VR. MV-38 tracks this.
  Evidence: `.development-artifacts/vr-human-motion/` (archive-backed).
  Initial focused gate: 19 passed. Scoped lint passed; full lint has three unrelated
  findings and memory lint has five pre-existing missing-index entries.
- Next: registration + visible headset check; recorded-trace resampling; physical
  NADOC recorder with intended targets/outcomes; task-conditioned calibrated profiles.

## Live desktop demonstration, 2026-09-22

- `tools/vr_motion/demo_loop.py` runs a 12-second pose-only bimanual sweep, anchored
  to a captured physical eye. Uses the synthetic model; not dataset-fitted movement.
- Launched the diagnostic chiral scene with the existing submitted left-eye mirror,
  stable-view scene placement and live `control` socket. No browser-edit bridge.
- Runtime launcher was updated by Steam and lost `cap_sys_nice`; user completed the
  official desktop setup authentication. Confirmed restored capability and fresh
  compositor direct-mode acquisition. No display/runtime configuration changed.
- Current launch/socket/PIDs are in
  `.development-artifacts/vr-human-motion-live/launch.json`; `status.json` tracks
  laps, `loop.log` records completion/failure, `controllers-left.png` and
  `controllers-evidence.json` retain submitted-eye evidence. These are current-run
  references, not persistent process identities. Closing the mirror stops the viewer;
  create `STOP` in that directory to end the loop after its current lap.
- Intermittent host timing stalls aborted and released initial loops; a completed
  lap had approximately 1.4 ms maximum pacing lag. The pose-only demonstration now
  logs timeouts and repeats the interrupted lap; it pauses while unfocused and pins
  the original session. Regression playback still fails on missed deadlines.
  Desktop mirror verified submitted/tracked with visible cyan/orange controllers;
  wearer usability and dataset registration remain open. Focused tests: 20 passed.
- Final ready run uses `runtime_directory` from `launch.json` for active logs,
  `status.json` and `STOP` (currently `/tmp/nadoc-motion-6e5vnq8r/`). Moved active
  diagnostic writes off the busy archive drive. Verified two complete laps and
  submitted/tracked/changing physical-eye mirror; second lap max lag 0.154 ms.
  Archive-backed `ready.json` and `verified-*` files preserve the readiness check.
  The current desktop mirror is maximized; cyan/orange guides surround the chiral
  diagnostic origami. No controller button inputs or document edits are involved.

## Live UI validation (2026-09-22)

User confirmed the live demonstration was visible. Added
`tools/vr_motion/validate_interface.py`, `metrics.py`, and `report.py` for repeatable
control-mode live tests, requested/observed paths and HTML/JSON reports. Native
captures identify each rendered controller with stencil classes 4/5 and export
menu hit rectangle axes. Both-eye visibility and offscreen negative control,
left-hand menu open, right-hand miss/hit and Tools page transition pass live.
Evidence: `.development-artifacts/vr-interface-validation/` (failed run-01 retains
the same-hand tablet-motion diagnostic; run-02 passes). Stop the demo input producer
before validation; never run two writers against one session. This is submitted
app-image evidence, not compositor acknowledgement or human calibration. See
`docs/vr_human_motion.md` for command, metrics, thresholds and limits.

Final rebuilt viewer validation: `vr-interface-validation/run-03/report.html`
and `report.json`: all six checks pass; 38 focused Python/IPC tests and actual
OpenGL identity/overlay-occlusion regression pass. Pose-only demo restored using
run-03 physical-eye anchor. See launch.json for current processes.
Retained final stereo PNGs, controller class buffers, evidence and report; discarded
unused depth/object-ID buffers and earlier-run raw captures (earlier report JSONs retained).

## Paths and clustering (2026-09-22)

User requested loop termination: stopped the demo. Viewer now holds a **static**
one-pass path preview, no loop process. Current launch.json records `loop_pid:null`.
`--controller-path` loads a planned route; pale dashed blue/gold = intended L/R,
solid green/magenta = actual production hand trail. Native module
`controller_paths.hpp` bounds trails and splits tracking-loss/jump segments.
Evidence and generated inputs: `.development-artifacts/vr-path-preview/`.

`tools/vr_motion/cluster.py` analyzed all 500 archived raw recordings (1,000 hands),
804 quality-qualified, 196 excluded; 4 exploratory clusters, silhouette .293,
seed ARI .993–1.000. Features: head-relative speed, pause fraction, acceleration,
direction change, task/hand adjusted. Reports/assignments/representatives:
`.development-artifacts/vr-motion-clusters/run-02/report.html`. Data comes from five
participants; never identify clusters with athlete/child/caffeine or motor skill.
No intended targets means no observed accuracy or corrective-intent ground truth.
Synthetic `reach --preset` options steady_fast/steady_deliberate/variable_fast/
variable_deliberate provide independently controlled speed/variability stress tests;
these are not fitted cluster centroids. See docs/vr_human_motion.md for workflows.

## User testing policy (2026-09-22)

Initial development/smoke tests must use **steady_fast**. Final validation must
exercise **all four** presets: steady_fast, steady_deliberate, variable_fast,
variable_deliberate. Keep the same target/task and seed when comparing profiles;
record misses and deviations rather than relaxing thresholds to make profiles pass.
Apply this policy to future VR interface tests, including Extrude paint and wheel.

## Extrude probing workflow

`tools/vr_motion/extrude_probe.py`: default steady_fast, --final all four, same
seed/geometry and reset draft per profile. Paint three cells, erase, wheel +3/-3
detents; records real poses, cells, bp deltas, release and unintended paint.
`--controller-path` now hot-reloads atomically; generation telemetry verifies the
loaded stage; diagnostic trails draw above the panel. Reports retain failures.
Final evidence: `.development-artifacts/vr-extrude-probe/validated-matrix/`.
Both steady presets pass. Variable presets paint/erase correctly but overshoot
wheel detents; no cross-paint or stuck trigger observed. Do not claim four-profile
success or document extrusion: commit_supported remains false. No loop started.
Final reset-draft matrix: steady_fast +21/-21bp, steady_deliberate +21/-21bp,
variable_fast +35/-28bp, variable_deliberate +49/-21bp (expected +21/-21).
Paint/erase, wheel release and no-cross-paint passed all four. The matrix completed
but failed wheel precision for both variable presets. 44 Python tests and native
unit/OpenGL checks passed. Desktop left showing final static trails; inputs released.
Retained final screenshots/inputs/reports (~11.8MB); discarded duplicate earlier
captures and unused anchor depth/ID buffers, retaining earlier report JSONs.

Unified inspector (2026-09-22): `tools/scrywrite_inspector` and
`frontend/scrywrite/inspector`; see `docs/scrywrite_inspector.md`. Shared
`tools/vr_motion/session.py` owns session/sequence/capture/release checks across
playback and probes. User policy: hide the chiral scene fixture when its scene/ID
tests finish so it does not obscure Extrude/menu debugging; restore only for
scene-dependent validation. Hidden mode preserves geometry and normalization.

Visible-motion correction (2026-09-22): user reported no visible paint/traces despite
state passes. Do not repeat state-only claims. Use `visual_checks.py` for both-eye
surface-contact stencil/RGB coverage, alignment, painted-cell pixels and four-second
persistence; `desktop_check.py` verifies the actual X11 client against a fresh mirror.
Native captures include mirror.png and viewport provenance. Contact traces differ
from the floating controller-body paths. Inspector publishes stage captures during
review holds, has magnification and a paint-only retained-review action. View-facing
placement comes from simulated wrist compensation, preserving physical head tracking.

Regression findings from the visible-motion gate: arm a new trace only AFTER
moving to its start (otherwise repositioning contaminates wheel-down). A broad
intended underlay alone can be covered by variable-profile crossings; retain a
thin intended centre line on top. Both regressions were detected by projected
pixel coverage/alignment, despite successful pose/state checks. Keep those gates.
