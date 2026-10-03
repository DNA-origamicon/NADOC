# VR Move/Rotate first-grab optimization — 2026-10-02

The retained candidate constructs the first packed preview from the displayed,
CPU-prepared representation instead of rebuilding the entire style. A clean
full-24HB Ball & Stick live comparison reduces maximum `setToolPreview` work
from **560.525 ms to 128.697 ms** (77%). Both runs pass cluster translation,
rotation, commit, save/reopen and Undo. This improves the first-grab hitch;
it does **not** establish sustained 90 Hz or eliminate first-grab blocking.

Evidence: `.development-artifacts/vr-preview-20261002/`. The clean reference is
`baseline-cluster-retry`; the initial candidate smoke is `candidate-live`.
The original `workspace/24hb_0xT.nadoc` remains the immutable live input, copied
into private workspaces (24 helices, 76 strands, 6,720 nucleotides; SHA-256
`bc51978e952aeaf7880c3892fa47ade2105eedd08b17ad25706709422ef7f45f`).

## Decision and implementation

Current-code profiling separated a 558.853 ms first-grab `setStyle` call from
subsequent packed-preview updates (3.251 ms p95 during the measured reach).
First-grab preparation therefore took priority over GPU-side motion transforms.
The earlier selection-tint and staged-scene-activation fixes remain in place.

`prepared_preview.inc` reuses the active resident's prepared primitive ordering,
radii, normals, filtering and ownership index. It late-binds current colors and
stable object IDs, preserves explicit endpoint weights over aliases, deduplicates
indexed rows, and constructs the existing committed-pose preview cache. It
detaches resident GL buffers before uploading any changed geometry, so Cancel
and later style restoration cannot expose a modified static cache.

The fast path is limited to Full, Stick, Ball & Stick and VDW with a matching
active resident, no pending style, no committed transform and no visualization
positions/colors/slab frames. Other cases retain the established renderer.
Continuous preview transforms, uploads, bounds, picking and commit/Undo use the
existing code. Molecular geometry, topology, eye resolution, shadows, lighting,
controller profiles and timing gates are unchanged.

## Controlled renderer comparison

The final registered diagnostic compares both setup implementations in the same
binary, using the archived full-size snapshots from `vr-split-20260930`. These
are separate from the current live input. Each mode uses five warmups and 40
measured frames; the first-grab call is measured separately before warmups.
Two 1852×2056 eye-sized draws and the production shadow pass use the RTX 3080 Ti.
These serialized GL measurements are not live OpenXR frame rates.

| Representation | Target | Legacy first grab (ms) | Prepared first grab (ms) |
|---|---|---:|---:|
| Full | Nucleotide | 18.740 | 8.185 |
| Full | Cluster | 48.602 | 12.117 |
| Stick | Nucleotide | 164.369 | 60.638 |
| Stick | Cluster | 395.776 | 90.383 |
| Ball & Stick | Nucleotide | 284.645 | 118.546 |
| Ball & Stick | Cluster | 737.523 | 164.616 |
| VDW | Nucleotide | 131.633 | 50.150 |
| VDW | Cluster | 525.108 | 68.864 |

The complete machine-readable results are in
`renderer-matrix/first-preview.json`. All **32 paired rendered images are
byte-identical** across idle, selected idle, translation and rotation. Continuous
update medians are similar: for Ball & Stick cluster translation/rotation,
1.78/1.69 ms legacy versus 1.72/1.65 ms prepared. Continuous-motion improvement
is not the retention claim.

## Live observations and limits

The steady-fast clean reference and candidate use the same full-size design,
profile, seed, browser drawing preference off, native mirror and timing gates.
The prepared setup itself takes 123.673 ms; total first-preview work is 128.697 ms.
The synthetic controller tour verifies submitted stereo motion and persistence,
not through-lens comfort or human-calibrated movement.

The moving reach's application cadence is 60.11 FPS in the clean reference and
51.33 FPS in the first candidate smoke. Subsequent packed-update p95 is 3.251
versus 3.099 ms. The short reach includes changing runtime pacing; these results
do not establish a sustained FPS gain. Selected stationary intervals remain
about 44.76 FPS in these browser-linked tours, despite the earlier standalone
selected-idle 90 Hz result. That earlier result is not transferable to every
view/setup. Further work must isolate this difference and retain compositor data.

Failed attempts remain visible: the first baseline cluster run's compositor
sampler started before SteamVR and exited; that run later timed out during a
post-commit capture. An accidental analysis of the accumulated 1.5 GB global
log overlapped that late stage and was interrupted; the clean retry avoids
that load and passes. The baseline nucleotide case fails target acquisition
before preview execution. Neither failure counts as an optimized workflow pass.

## Regression coverage and reproduction

Five native checks pass: rigid preview, origin, staged representation, scene
activation and coordinate playback. The extended first-grab test covers all
four supported styles in strand/CPK coloring, explicit zero/fractional endpoint
weights, duplicate owner aliases, untouched primitives, Cancel, committed and
restored resident buffers, owner changes, Undo, and the existing depth/picking
and view-volume checks.

The reusable entry remains **Debug → VR Tours & Tests → Tools · Authoring →
Move / Rotate · renderer regression**. Its saved-scene A/B option is:

```sh
uv run python -m tools.vr_workflows.move_preview_check \
  --scene-dir .development-artifacts/vr-split-20260930 --compare-setup \
  --output .development-artifacts/vr-move-preview/new-comparison
```

The final full-24HB Ball & Stick cluster campaign passes **all four profiles**:
steady-fast, steady-deliberate, variable-fast and variable-deliberate. Each
includes the real browser edit, submitted stereo geometry checks, save/reopen
and Undo. First-preview work is respectively 116.501, 121.683, 112.980 and
123.042 ms. The final steady-fast repeat versus the clean baseline is a 79%
reduction (560.525 → 116.501 ms). Packed-update p95 during motion is
2.73–3.30 ms; the corresponding short moving intervals span 47.32–77.15 FPS.
They do not meet a universal 90 Hz gate.

The task's `final-profiles` directory retains each profile's native trace,
compositor samples, browser results and captures. Failed profile stages remain
coverage limits; a valid trace alone is not a workflow pass.

All four final single-nucleotide profiles fail `selected geometry was not pointed
at` before preview/cache execution, matching the baseline's steady-fast failure.
Thus the final live matrix is **4/8 workflow passes**, with complete cluster
coverage and no live nucleotide-preview validation. The isolated nucleotide
renderer results do not close that acquisition gap.

The focused tour-catalog suite passes **35 tests**. No frontend or backend
production code changed, and no broad suite was run for this native optimization.
`git diff --check` passes. The user's original design hash is unchanged, all
owned viewers and private workspaces are gone, and no new bridge credential
files remain. Eleven empty owned socket directories were removed; the failed
post-commit capture was moved into the task archive. Seventy-two PPM captures
were losslessly converted to PNG and their redundant PPM files removed. Raw
stereo depth/ID buffers and useful failed-attempt evidence remain archive-backed
for audit replay. See `artifact-cleanup.json` and `cleanup.json`.
