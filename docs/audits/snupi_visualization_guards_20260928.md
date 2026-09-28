# SNUPI result visualization guards — 2026-09-28

## Scope and findings

The previous assembly/CanDo work was committed and pushed as `53406b8b` to
`feature/standalone-viewer-presentations` before this work began. Unrelated
photoproduct edits, analysis and experiment outputs were excluded.

SNUPI static modes duplicated the former CanDo controller: large jobs rebuilt
full snapshot scenes, color changes rebuilt maps, old requests could win after
selection changes, and graphs retained unbounded per-job JSON caches. Dynamics
playback downloaded every frame and allocated object updates on every tick.

## Changes

- Above 50k nucleotides, all four static modes use the existing compact FEM
  protocol and zoom-adaptive point/axis-line renderer. Physical coordinates,
  copy/direction identities, all scalar rows and true axis/joint endpoints are
  retained. SNUPI uses its static/time-mean result, never CanDo thermal records.
- Share the guarded metrics-card factory through a SNUPI host adapter. Compact
  scalar aggregation yields to the event loop; duplicate loads coalesce, abandoned
  requests cancel, caches retain only the selected job's metrics, and graph errors
  become status messages. CSV exports retain all rows.
- Mode/job changes, Off, deletion and workspace/tab teardown invalidate requests.
  Periodic detail refresh cannot erase loading progress. Error text explains the
  failed load; large-view status identifies the drawing representation.
- Backend deviation/cylinder loading and computation run entirely in worker
  threads. Compact preparation shares the serialized build guard and atomic,
  source-stamped, disposable job-local caches with CanDo.
- SNUPI trajectory playback indexes legacy JSON without reading the whole file
  into a Python object. Requests decode only one bounded frame. Source changes
  invalidate the derived index/frame caches. Invalid indices, incomplete arrays,
  oversized frames, missing keys and coordinate-shape mismatches fail explicitly.
- All trajectory sizes use zoom-adaptive nucleotide points. Each frame preserves
  every backbone position; glyph orientation/slab detail is not drawn. The player
  retains one displayed frame and at most one requested frame, applies backpressure
  rather than queuing ticks, aborts superseded scrubs, and reuses GPU geometry.
  Pause/play, wrapping step controls, random scrubbing and Off remain available.
- Camera bounds follow the SNUPI result. `main.js` delta: **+1 line**, wiring only.
  No topology, solver, molecular placement, or saved physical result was changed.

## Verification method and limitations

No completed native BigO SNUPI job exists locally. The browser scale check copies
BigO's completed **CanDo static FEM display** (424,144 nucleotides) into a disposable
SNUPI transport fixture; this validates the shared result protocol and SNUPI UI at
BigO scale, **not SNUPI physical prediction**. A separate copied, completed native
SNUPI smallO dynamics job (`436657acd6f1`, 2,394 nucleotides, 40 frames) exercises
actual SNUPI snapshot rendering and trajectory playback/scrubbing. No solver is run.
The native assembly setup uses Hull Prism in the test copy to bound software-WebGL
setup/Off cost. Original assembly and result inputs remain read-only.

`scripts/verify_snupi_visualization.py` owns `/tmp/nadoc-snupi-viz-*`, copying only
required result files. It removes all imported `__e2e__` documents, revision stores,
logs, autosaves, derived caches and inputs in `finally`, after stopping only processes
with its exact workspace environment. Test bridge credentials are also removed;
the Playwright reporter removes screenshots/traces/reports even after failure.

Hardware-GPU close-up visual quality remains manual validation debt. Points do
not convey nucleotide orientation, and line views omit tube radii. Playback rate
is bounded by available frame preparation/download/render throughput, not a
promise of 12 FPS for every assembly. Results of final gates are recorded below.

## App verification

Full browser exercise: **1 passed (4.0 min)**. Four static modes retained all
424,144 nucleotide records or 465,480 axis/joint endpoints. Both graphs retained
all aggregated rows (RMSF 211,680; deviation 212,464). Camera and scalar controls,
mode races, Off during loading, native SNUPI snapshot display, native 40-frame
playback, last-frame scrub, single stepping and Off cleanup passed; no console
errors. Original BigO assembly bytes and in-app assembly state were unchanged.

| Mode | Maximum post-load 50-ms timer gap | GPU output at whole-assembly zoom |
|---|---:|---:|
| Predicted shape | 131 ms | 31,969 points |
| RMSF | 149 ms | 31,969 points |
| Deviation | 190 ms | 31,969 points |
| Axis/joint style | 185 ms | 50,206 lines |

All four had zero triangles. Initial native-to-result transition: 1.24 s maximum
timer gap; subsequent loading periods: 204–274 ms. First-use preparation and native
setup still take time; these are software-WebGL measurements, not hardware GPU
promises. Per-mode logged scenario times include interactions, screenshots/pixel
readback and timing waits, and are not pure load-time measurements.

An initial fixture attempt was interrupted after SNUPI rejected CanDo-only job
metadata fields; the test copy now selects SNUPI dataclass fields explicitly. The
next browser run exposed a scrubber ordering bug in the new player (pause refreshed
the slider before its requested value was captured). A DOM regression reproduces
that event path, and the corrected full browser run passed. Every attempt's
workspace, reports and test credentials were cleaned up.

An additional lifecycle audit found hidden playback could survive engine changes.
SNUPI and CanDo panels now clear active/pending result views at that boundary,
including player timers and graph caches. This uses the existing engine-change
event and adds no composition-root logic.

Focused native smallO assembly engine-exit browser check: **1 passed (18.3 s)**.
Leaving SNUPI removed the result group, stopped further trajectory-frame requests,
and returned its controls to Off. Early setup attempts used a raw part import
without entering an editable workspace and stalled on sidebar UI; the final test
uses the actual smallO assembly entry path. All attempt artifacts were removed.

Frontend aggregate: **557 files passed; 7,138 tests passed, 1 skipped**.
Focused backend visualization/index/route tests: **6 passed**. Production build
and `just lint` passed; build retains the existing large-chunk warning.

## Backend aggregate gate

`just test-smart`: **FAST**, **9,325 passed, 15 skipped, 8 failed**. The eight
failures match the pre-existing photoproduct debt: seven need the unavailable
external human-review packet, and one CPD preview golden differs. No SNUPI,
CanDo, or new visualization test failed. Pytest took 98.17 s; the guard took 107 s,
above its 90 s aggregate backstop. The required slow-test triage found **zero
per-test violators**, with the slowest at 4.32 s; 9,348 tests accumulated 420.5
worker-test seconds. No budget, guard, or test classification was weakened.

Selector notice, verbatim:

```text
  DEFERRED: this change would have needed the FULL suite, but no test-dedicated
  session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
  This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
  Only request `just test-session` when a broad/full sweep is actually needed.
```

No broad/full suite or new physical simulation was run.

Final smoke gate: **23 passed (2.1 min)** on dedicated ports 8001/5174.
`git diff --check` passed. Final cleanup confirmed no SNUPI test/smoke workspaces,
Playwright reports, or test bridge credentials remain. Verification logs were
removed after recording results here. The SNUPI changes were approved for commit and push after validation.
`53406b8b` is the preceding assembly/CanDo commit explicitly pushed before this task.
