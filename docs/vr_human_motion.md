# Human controller motion for VR testing

The first implementation lives in `tools/vr_motion/`. It creates reproducible
synthetic reaches, imports real Vive motion, describes movement statistics, exports
ScryWrite Witness scripts, and plays traces through the existing live bridge.
No runtime, display configuration, native controller path, or design mutation
implementation is replaced.

## Dataset location — retain for future sessions

On the Vive workstation, the BEHAVIOR-100 **raw VR** v0.5.0 dataset is archived at:

```text
/media/jojo/Archive/NADOC_archive/datasets/vr/behavior-100/
  behavior_virtual_reality_v0.5.0.tar.gz
  manifest.json
  catalog.json
  raw/virtual_reality/*.hdf5
  example.hdf5
```

`manifest.json` records source URL, download time, SHA-256, bytes, extraction
inventory and verification status. This is the raw sensor/action dataset, not
the much larger rendered imitation-learning dataset. Keep originals immutable.
Verified download: 1,791,999,788 archive bytes; 500 extracted HDF5 recordings
totalling 6,838,436,528 bytes. SHA-256:
`5b521af825660163aa616fc397b435218b94eaeaf03c65adc8d2d6a0f2729a17`.
The location is workstation-specific; do not create a root-drive substitute if
the Archive mount is absent. Dataset redistribution terms have not been established;
the data is local and is not vendored into the source repository.

Sources: [dataset downloads](https://behavior.stanford.edu/behavior_100/dataset.html),
[raw field documentation](https://stanfordvl.github.io/behavior/vr_demos.html).
The upstream iGibson source files used to verify the data contract are retained
beside the archive, from commit `04c01e85fbb50408135729089ac11a4b1d2dd61c`.
`catalog.json` indexes task names and frame counts. Regenerate it with
`uv run --with h5py python -m tools.vr_motion catalog RAW_DIRECTORY OUTPUT.json`.
Add `--measure` to scan durations and tracking coverage; otherwise those fields are
explicitly null. The retained whole-dataset index uses the lightweight mode because
the full scan contended with substantial archive-drive I/O load. Imported clips
can be summarized individually without a full-dataset pass.

## Generate and inspect a movement

Run from the repository root. Only HDF5 import needs the optional `h5py` dependency;
generation, summaries, export and live playback use the Python standard library.
Retained local evidence goes under the existing archive-backed
`.development-artifacts/vr-human-motion/` directory.

```bash
mkdir -p .development-artifacts/vr-human-motion
python -m tools.vr_motion reach .development-artifacts/vr-human-motion/reach.motion.json \
  --start 0.25 1.25 -0.35 --target 0.35 1.30 -0.50 --seed 42
python -m tools.vr_motion summary .development-artifacts/vr-human-motion/reach.motion.json
python -m tools.vr_motion witness .development-artifacts/vr-human-motion/reach.motion.json \
  .development-artifacts/vr-human-motion/reach.scry
native/vr_viewer/build/nadoc-vr-viewer --validate-witness \
  .development-artifacts/vr-human-motion/reach.scry
```

Feed the generated `.scry` to the existing `just scrywrite-witness SCENE SCRIPT`
workflow. Witness steps count application frames; their wall-clock duration depends
on runtime cadence. Export converts XYZW quaternions to Witness's WXYZ order,
quantizes sample times to the requested frame rate, rejects button edges that
collapse into one frame, and rejects scripts above the existing 10,000-command cap.
It does not add success assertions: callers must assert the intended UI/design result.

Use `--profile path.json` for any subset of these fields:

```json
{
  "position_sigma_m": 0.002,
  "rotation_sigma_deg": 0.4,
  "correlation_s": 0.12,
  "endpoint_bias_m": [0, 0, 0],
  "overshoot_fraction": 0.03,
  "reaction_s": 0.15
}
```

These are **illustrative, uncalibrated stress-test settings**, not estimates of a
typical person or Vive tracking accuracy. The model uses minimum-jerk movement,
a smooth overshoot/correction phase, quaternion interpolation and temporally
correlated Ornstein–Uhlenbeck perturbations. Standard deviations are per axis.
The final pose is not snapped onto the target. The seed and complete parameters
are saved in the trace. Different sample rates do not produce identical sampled
noise realizations even with the same seed.

## Import actual human motion

```bash
uv run --with h5py python -m tools.vr_motion import-behavior \
  /media/jojo/Archive/NADOC_archive/datasets/vr/behavior-100/example.hdf5 \
  .development-artifacts/vr-human-motion/behavior-example.motion.json \
  --start-frame 10 --count 300
python -m tools.vr_motion summary .development-artifacts/vr-human-motion/behavior-example.motion.json
```

Import preserves both controller poses, head pose, tracking validity, analog
trigger and touchpad samples, source frame indices, file hash and task metadata.
Analog values remain metadata: this version does not invent trigger thresholds or
map the source task's button events onto NADOC menu/grip operations.

Timing uses cumulative `frame_data[:,3]` (`last_frame_dur` in the source writer).
The nominal `render_timestep=1/30` is simulation time and must not be used to infer
human speed. Measured durations approximate observation intervals, not hardware
timestamps. Invalid durations and missing frames fail explicitly. The inspected
300-frame example covers about 20.02 seconds, rather than 10 seconds at nominal 30 Hz.

Imported motion remains `iGibson_world_unregistered`. Live playback and Witness
export reject it until an explicit rigid registration is supplied:

```text
python -m tools.vr_motion register INPUT OUTPUT \
  --rotation QX QY QZ QW --translation X Y Z \
  --controller-rotation CX CY CZ CW
```

Registration applies `p_local = R*p_source + translation` and
`q_local = R*q_source*C`; `C` is an optional controller-local axis correction.
Calibration must establish source axes/origin and the Vive grip/aim convention.
It is recorded as caller-supplied, not automatically verified. No floor, target,
controller orientation or human height is guessed. Tracking gaps must be segmented
before playback; this first version does not silently interpolate through them.

Summaries report path length and speed/angular-speed percentiles. Those describe
recorded movement including tracking effects, not target error or isolated tremor.
Do not add the synthetic default noise to an imported recording automatically.

## Live VR playback

For the pose-only desktop demonstration, `python -m tools.vr_motion.demo_loop
SOCKET EYE_EVIDENCE OUTPUT_DIRECTORY` repeats a 12-second cyan/orange bimanual
sweep anchored to the first eye in a submitted capture's `evidence.json`. It uses
the seeded movement model and the existing live bridge, and never presses buttons.
Close the viewer to stop immediately, or create `OUTPUT_DIRECTORY/STOP` to stop
after the current lap. The desktop mirror remains the physical left-eye view.
This demonstration uses synthetic movement, not recorded BEHAVIOR trajectories.
It pauses while unfocused and repeats a pose-only lap after a timing timeout,
recording that interruption. Regression playback retains strict failure behavior.

Use the existing opted-in viewer from [the live-agent guide](scrywrite_live_agent.md).
With a standalone `control` viewer already running:

```text
python -m tools.vr_motion live TRACE.json \
  --socket /private/session/viewer.sock \
  --trace .development-artifacts/vr-human-motion/live-commands.jsonl
```

Without `--socket`, the bridge uses backend-state discovery. Browser-connected
`transactions` mode requires the explicit `--allow-transactions` option; use an
isolated design copy. Live playback never moves the physical HMD.

The same trace can contain button edges in its `events` array, for example:

```json
[
  {"t": 0.5, "hand": "right", "button": "trigger", "pressed": true},
  {"t": 0.7, "hand": "right", "button": "trigger", "pressed": false}
]
```

Supported edges are menu, grip and trigger, on an explicitly posed hand. Live
playback sends poses before edges at the same timestamp, waits for an application
frame after each edge and at completion, pins session/command sequence, rejects
sample gaps above 0.5 seconds, and aborts if pacing falls more than 150 ms behind
(configurable up to 1 s). It releases inputs on completion/error/interruption.
An uncertain command is never retried; cleanup observes the sequence before
release and will not release a replacement viewer. If cleanup cannot connect,
the viewer's existing two-second input lease remains the fallback.

This is paced socket playback, not atomic per-frame scheduling: two hands are
sent sequentially and some pose samples may not reach a rendered frame. Use the
recorded bridge observations to assess delivery. The adapter never claims that
input acknowledgement proves visual success or a persisted design mutation.

## Validation and next work

Focused tests exercise seeded motion, overshoot/bias, correlated noise, quaternion
conversion, native Witness parsing, source timing/registration, playback pacing,
deadline abort, session replacement, uncertain delivery cleanup and actual native
handler IPC. The native harness explicitly has no OpenXR runtime. Physical-headset
validation of this new modeller is pending (MV-38).

The initial gate passed 19 focused tests, including the real native handler IPC
test, and imported the upstream example. A plot comparing ideal and perturbed
seed-42 motion is retained at
`.development-artifacts/vr-human-motion/seed42-review.png`.
Scoped Ruff checks passed; repository-wide lint remains blocked by three unrelated
findings (`routes_oxdna.py`, `test_oxdna_peg.py`, `test_streptavidin.py`). Memory lint
has five unrelated missing-index entries. `frontend/src/main.js` LOC delta: 0.

Next: calibrate registration on a visible Vive fixture; add resampling/segmentation,
analog input support, a physical NADOC motion recorder with intended-target/outcome
labels, and dataset-fitted task-conditioned profiles. Keep device faults separate
from human variation. Measure missed selections, accidental activations, correction
attempts, completion time and placement error against held-out people/tasks before
claiming predictive human performance.

## Live interface debugging workflow

Stop other scripted input producers, launch the diagnostic viewer in ScryWrite
`control` mode with SteamVR focused, then run:

```sh
python -m tools.vr_motion.validate_interface /path/to/viewer.sock \
  .development-artifacts/vr-interface-validation/new-run
```

The output directory must be new. Open its `report.html` for requested/observed
path plots, stereo images, individual checks and numeric measurements; `report.json`
contains all sampled poses and frame/command identifiers. Failures return nonzero,
preserve partial reports, and release inputs. No browser transaction mode is accepted.

The workflow measures 31 bimanual requested poses against production hand poses
observed after a frame barrier (62 pose comparisons), positional RMSE/p95/max in mm,
quaternion error in degrees and command-plus-frame round-trip time. Samples are
frame-paced: this validates applied paths, **not** real-time motion fidelity, tracking
latency or human accuracy. Tiny differences include native JSON rounding.

Stereo captures label actual rendered controller fragments with stencil classes
4 (left) and 5 (right); both remain overlays in mirror diagnostics. Later surfaces
can overwrite these tags. At least 10 surviving pixels per hand per eye passes the
visible checkpoint. Moving both hands offscreen must produce zero pixels. This
proves app-submitted eye visibility at those checkpoints, not every trajectory
frame or headset compositor scanout. Production guides currently draw without
depth testing, so scene geometry does not hide them; later UI can cover them.

Menu testing opens the tablet with the left menu button, aims the right controller,
and checks a reversed-ray miss followed by a Tools click and the resulting page.
Holding the tablet and aiming with the same hand moves the target; use separate
hands for this stationary-target test. Reports include production world-space hit
rectangle axes, width/height, controller distance, nominal angular size (without
foreshortening), signed edge margin, independent ray intersection, observed hover,
and resulting page. One hit and one miss establish a smoke test, not a population
success rate. Unexported special controls have zero axes and fail geometry analysis
explicitly; radial acquisition, text readability, drag/resize and user calibration
remain additional scenarios.

Verified live evidence: `.development-artifacts/vr-interface-validation/`.
Keep the physical HMD pose authoritative. Never interpret synthetic input
agreement as calibrated human behaviour or a browser design commit.

## Intended route and observed trails

`--controller-path FILE` enables a diagnostic overlay in the native viewer and
its submitted headset eyes. `FILE` contains `hand x y z` per line (0 left, 1 right),
OpenXR_LOCAL metres; `#` comments are allowed. It never controls the HMD.
Use `tools.vr_motion.path_preview` to generate a noiseless intended route and a
separate perturbed motion from a current eye capture. The initial desktop preview
is a **single pass**, not a loop; the last completed trails remain visible.

- Dashed pale blue / pale gold: intended left / right route.
- Solid green / magenta: observed left / right controller trail, sampled from the
  production hand poses, not copied from the requested trajectory.
- Trails record at least 1mm movement, retain at most 4096 points per hand and
  start fresh after invalid tracking/release or a jump over 25cm. Release holds
  the last trail; the next valid segment clears it. Guides draw as overlays.
- Diagnostic paths use overlay class 3, never controller identity classes 4/5.

```sh
python -m tools.vr_motion.path_preview /path/to/evidence.json /new/preview/directory
# Add --controller-path /new/preview/directory/intended.path to viewer launch.
python -m tools.vr_motion live /new/preview/directory/actual.motion.json \
  --socket /path/to/viewer.sock --trace /tmp/one-pass.jsonl
```

`actual.motion.json` is the simulated input, while the solid native trail shows
what was actually applied. The preview's 12mm per-axis variability and 12% overshoot
are illustrative and deliberately distinguishable, not fitted population values.
Review: `.development-artifacts/vr-path-preview/left.png`, `right.png`, `legend.txt`.

## Exploratory motion clustering and profiles

The source dataset was collected from **five participants** using Vive hardware,
not 500 independent people ([collection documentation](https://stanfordvl.github.io/behavior/vr_demos.html)).
No athlete, age-group or caffeine labels are used or inferred. Clusters describe
recording-hand motion styles. Without intended targets, motion alone cannot tell
us aiming accuracy, intentional corrections, skill or physiological steadiness.

```sh
OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 uv run --with h5py --with scikit-learn \
  python -m tools.vr_motion.cluster \
  /media/jojo/Archive/NADOC_archive/datasets/vr/behavior-100/behavior_virtual_reality_v0.5.0.tar.gz \
  .development-artifacts/vr-motion-clusters/new-run
```

The archive is read sequentially and each HDF5 is processed in memory individually.
An extracted directory is also accepted. Originals are read-only. `report.html`
contains a filterable scatterplot and links to raw features, assignments, quality
flags, cluster centers and representative source recordings. Import a representative
with `import-behavior`, inspect its quality and explicitly register coordinates
before playback. No automatic population fit is applied to the motion model.

Features: head-relative translational median/p90 speed, fraction below 0.05m/s,
median acceleration, and moving-interval direction change. Shared head translation
is subtracted to suppress navigation; residual head motion and sensor/timing effects
remain. Intervals crossing invalid tracking, frame gaps, dt outside (0,100ms] or
steps over 25cm are excluded. Quality gate: ≥95% tracked, ≥90% good intervals,
≤1% jumps, sufficient samples. Excluded recordings receive **no motor-style label**.
Acceleration is timing-sensitive and is not a tremor or accuracy measurement.

Task/hand medians are subtracted from log1p features before IQR scaling and clipping
to ±5, then deterministic four-cluster KMeans is fitted. Four is an exploratory
choice, not a discovered number of human populations. Tasks still confound results,
especially small groups; no held-out-participant generalization is established.

2026-09-22 result (`vr-motion-clusters/run-02`): 500 recordings, 1,000 hand-recordings,
804 qualified / 196 excluded. Silhouette 0.293 (overlapping groups); alternative-seed
adjusted Rand 0.993–1.000 indicates stable optimization, not validated motor classes.
18 task/hand groups have fewer than three qualified examples.

| Cluster | Recording-hands | Median speed m/s | Paused fraction | Interpretation within this analysis |
| --- | ---: | ---: | ---: | --- |
| 0 | 129 | 0.101 | 30.1% | Slower, more paused |
| 1 | 144 | 0.188 | 12.2% | Faster, more continuous |
| 2 | 112 | 0.119 | 28.5% | Lower direction-change/acceleration |
| 3 | 419 | 0.136 | 19.1% | Broad central group |

For controlled interface testing, `reach --preset` independently varies speed and
variability: `steady_fast`, `steady_deliberate`, `variable_fast`,
`variable_deliberate`. These are **synthetic, uncalibrated stress-test settings**;
use the same intended target and seed across profiles, and measure actual hit/miss
outcomes with the live workflow. They are not demographic proxies or learned cluster
centroids. `--duration` may override the preset duration; `--profile` and `--preset`
are mutually exclusive. Example:

```sh
python -m tools.vr_motion reach /tmp/reach.json --start 0 1 -0.4 \
  --target 0.2 1.1 -0.6 --preset variable_fast --seed 42
```

## Required preset progression

User policy: start initial debugging with `steady_fast`; final validation includes
`steady_fast`, `steady_deliberate`, `variable_fast`, and `variable_deliberate`.
Use the same task/seed and report all outcomes, including sensitivity failures.

## Extrude paint and wheel validation

The viewer's `--controller-path` file can now be atomically replaced between
stages. It checks for updates every 250ms, keeps the last valid route on invalid
input, and exposes `controller_path_generation` so tests wait for the correct
route. Diagnostic paths render above menu panels, remain class-3 overlays, and
are not counted as controller identity pixels.

```sh
# Viewer must use --controller-path /tmp/my-private-session/intended.path.
# Start with a valid path file exported by path_preview.
python -m tools.vr_motion.extrude_probe /path/to/viewer.sock \
  /tmp/my-private-session/intended.path \
  .development-artifacts/vr-extrude-probe/new-initial-run
# After initial debugging, run the complete preset matrix:
python -m tools.vr_motion.extrude_probe /path/to/viewer.sock \
  /tmp/my-private-session/intended.path \
  .development-artifacts/vr-extrude-probe/new-final-run --final
```

Default is `steady_fast`. `--final` uses all four presets with seed 42, the same
physical-eye-derived anchor and target geometry. Setup clears the previous draft
through the existing tool lifecycle; each profile starts with zero length and an
empty footprint. Semantic activation bypasses radial acquisition. Tests use direct
controller poses, real trigger edges, production frame barriers and 20Hz paced
input; they fail rather than retry when more than 150ms late. Buttons are released
on exit and no loop starts.

Stages: paint cells (0,0)/(0,1)/(0,2), return-stroke erase, wheel up, wheel down.
Intended wheel travel is 3.5 notch distances (middle of the three-detent bin), then
a stationary hold before trigger release to exclude intentional flick momentum.
Wheel acquisition starts at its center; this does not test noisy acquisition from
a distance. Reports record actual vs expected cell sets, unintended painting,
trigger release, expected/actual base-pair changes, target dimensions, frame/pose
samples, timing, requested-input error and deviation from the ideal route.
`report.html` includes both-eye screenshots and path plots; nonzero exit means
one or more outcomes failed, even when the complete experiment ran successfully.

Live evidence: `.development-artifacts/vr-extrude-probe/validated-matrix/`.
Both steady presets passed paint/erase and ±21bp wheel travel. Both variable
presets passed paint/erase but produced extra upward wheel detents. Preserve the
failures as sensitivity findings; do not relabel a noisy gesture as successful or
retune the preset to hide the discrepancy. These are one-seed smoke tests, not
population success rates. The control-mode interface still reports
`commit_supported:false`; no authoritative extrusion/document commit is validated.

Final reset-draft matrix (2026-09-22; expected up/down +21/−21 bp):

| Preset | Paint / erase | Wheel up / down | Overall |
| --- | --- | --- | --- |
| steady_fast | Pass | +21 / −21 | Pass |
| steady_deliberate | Pass | +21 / −21 | Pass |
| variable_fast | Pass | +35 / −28 | Wheel precision failure |
| variable_deliberate | Pass | +49 / −21 | Wheel precision failure |

All four released the wheel correctly and produced no cross-paint. The full matrix
ran to completion but **did not pass** precision validation. These figures are from
`validated-matrix/report.json`; earlier exploratory runs are retained separately.
