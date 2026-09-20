# Viewer A/B measurements — Phase 0

The first checkpoint measures the existing viewer; it does not yet introduce a
candidate renderer. A/B labels identify builds, not a renderer toggle. No speedup
or large-design parity has been demonstrated yet.

## Capture from the application

1. Load a part or assembly and wait until the requested representation is ready.
   Begin with Full. For simulation review, choose the same job/frame or recorded
   playback range and speed in both builds. Capture does not start or stop a job.
2. Frame the design using a saved camera pose. Keep viewport, browser zoom, device
   pixel ratio, representation, colors, lighting, and quality identical in A/B.
3. Open **Help → Open Log…** (Process Log), expand **Performance comparison**.
4. Choose **A** for the frozen baseline, **B** for the development branch. The
   panel defaults to B on `feature/standalone-viewer-presentations` and A on the
   detached baseline; the build record includes branch identity. Choose
   **Repeatable orbit**, normally 20 seconds. The orbit makes one revolution per
   20 seconds; repeated runs reuse the first starting pose. **Use current viewpoint**
   resets that starting pose for the next run.
5. Click **Start capture**. The log closes so its table does not affect timing.
   Keep the tab in front. Camera gestures are temporarily disabled for an orbit
   run and restored afterward. Freeform mode allows normal gestures/playback.
6. Reopen the log after the interval. **Copy latest metrics** copies the complete
   `[NADOC_VIEWER_PERF v1] {...}` line. If clipboard access fails, select/copy the
   textarea. The same line is in a completed log row and the browser console.
7. Paste the A and B records into the development conversation. Include whether
   simulations or other heavy applications were running on the same computer.

Run one warmup and at least five measured runs for each scenario, alternating
A/B. Do not run both visible viewers at once on the same GPU. Freeform measurements
are useful diagnostic evidence, but are not repeatable scripted regressions.

Fields currently implemented: frame interval p50/p95/p99/worst, sample counts,
slow frames over 33.333/50 ms, mean FPS, last render-pass draw/triangle/resource
counts, approximate sampled JS heap when available, initial camera/settings,
viewport, browser and available GPU metadata, document hash, build/source hash,
elapsed time, validity and invalidation reason. Source hashes are evaluated at
Vite startup/build: restart the test server after edits; do not benchmark HMR.

Limitations: no physical input-to-photon/GPU time, no GPU byte measurement, no
peak process memory claim, and no automatic load/picking timing in this first
capture. Unsupported values are null. Renderer counts describe the previous
render pass, not a complete multi-view/postprocessing frame. Existing operation
entries still report load/application phases separately. A document hash does not
prove equivalence of externally loaded simulation data or all assembly assets;
recorded scene-package/content hashes will add that guarantee in the next phases.
Do not interpret a valid capture as an automatic performance acceptance verdict.

Tab hiding, context loss, viewport changes, fixture replacement, representation
changes, manual stop, or a stalled loop invalidate the run. Captures do not change
design topology, save files, run simulations, or upload telemetry.

## Run captures from the local controller

The development viewer now connects to a restricted test bridge through Vite's
existing socket. No browser extension, debugger launch, or separate browser
installation is needed. A production benchmark preview can opt in explicitly with
`NADOC_VIEWER_TEST=1`; its browser URL also needs `?viewer-test=1`. Ordinary production
visits do not connect. Preview captures use a same-origin event connection, with no
polling or screenshot work inside the measured render loop.
It accepts **inspect**, **snapshot**, **capture**, **open**, and **visit** commands. File opening
uses NADOC's existing File → Open workflow; it does not execute arbitrary JavaScript
or launch simulations.

From the repository root:

```bash
node scripts/viewer_test.mjs sessions
node scripts/viewer_test.mjs inspect --session SESSION_ID
node scripts/viewer_test.mjs open --session SESSION_ID --file VoltronCoreArmV2.nadoc
node scripts/viewer_test.mjs capture --session SESSION_ID --runs 5 --warmups 1 --seconds 20 --output /absolute/path/to/new-evidence-directory
```

If exactly one viewer is connected, `--session` can be omitted. Session listings
contain registration-time information; **inspect** obtains current state, including
the window URL, loaded design, camera, visibility, viewport, and controls. A reload
creates a new session ID. Load the fixture once, close Process Log, and keep that
tab visible, the window unminimized, and the computer awake. Avoid other GPU work.
**open** replaces the scene in the selected tab with the requested native file; use a
dedicated benchmark tab for repeated fixture changes. Paths are workspace-relative
`.nadoc` or `.nass` paths, including subdirectories. Normal loading handles identities,
workspace paths, assembly references, camera framing, and progress/error reporting.
Failed/partial assembly loads report an error rather than a successful capture setup.
Add `--file VoltronCoreArmV2.nadoc` to **capture** to load, settle, snapshot, warm up,
measure, and save evidence in one command. No file picker or manual scene setup is
required. Recorded-trajectory job/frame setup still uses its existing UI.

For loading without **any browser**, the standard-library Python controller accepts
either a backend workspace file or a local native source file:

```bash
python3 scripts/nadoc_load.py --api http://127.0.0.1:8020 --doc benchmark-a --file VoltronCoreArmV2.nadoc
python3 scripts/nadoc_load.py --api http://127.0.0.1:8020 --doc benchmark-a --source /absolute/path/to/design.nadoc
```

The backend document ID is explicit, and its previous contents are replaced. Prefer
an isolated benchmark backend. `--source` leaves the original local file untouched;
assembly part references must still resolve in the target backend workspace. This
prepares backend state only: GPU timing and screenshots require a rendering browser.
Native formats are supported here; other import formats retain their existing import
tools. No permanently running test server or additional browser software is needed.

The capture command saves `captures.json` incrementally (including invalid runs
and errors), plus `before.png` and `after.png` for visual review. Screenshots contain
the viewer canvas only, not editor panels or the whole desktop. They run outside
the timed intervals; normal rendering retains its original drawing-buffer settings.
Each timing record still appears in Process Log and the browser console for manual
copy/paste. One warmup and five 20-second runs are the defaults. Evidence directories
must be new: existing measurements are never silently overwritten.

Controller requests require a random credential stored with owner-only permissions
in the OS temporary directory. It is never sent to browser JavaScript. The endpoint
accepts authenticated loopback requests without a browser Origin header. The file is
removed on normal server shutdown; a killed server can leave a stale credential file,
which does not authorize the next server. Commands are serialized per server; use
only one visible, rendering benchmark viewer at a time across servers. Results are
bounded to the latest 32 commands in server memory. Save evidence before restarting.

For a development-mode comparison, prepare the instrumented baseline below and
run its Vite development server on 5180 against its isolated backend on 8020.
Use the production protocol below for performance acceptance:

```bash
VITE_API_PORT=8020 npx vite --host 127.0.0.1 --port 5180 --strictPort
```

Open and load the same fixture there. The controller supports another checkout:

```bash
node scripts/viewer_test.mjs sessions --root /home/joshua/NADOC-viewer-baseline/frontend --port 5180
node scripts/viewer_test.mjs capture --root /home/joshua/NADOC-viewer-baseline/frontend --port 5180 --output /absolute/path/to/new-baseline-evidence
node scripts/viewer_test.mjs compare --a /path/to/baseline/captures.json --b /path/to/candidate/captures.json
```

Older baseline checkouts need the new bridge instrumentation; preparing a fresh
baseline with the updated script includes it. A bridge-enabled frozen checkout is
prepared at `/home/joshua/NADOC-viewer-baseline-bridge`, with a byte-identical copy of
VoltronCoreArmV2 in its own workspace; the older baseline checkout is preserved.
Use that root in the commands above. No baseline servers are left running.
Variants come from the actual build's
default, not a controller label switch. Comparison rejects identical frontend hashes,
mixed builds, fewer than five measured runs, invalid captures, or mismatched workloads.
It reports the median of per-run p95 frame times, not a pooled percentile or a visual
acceptance verdict. Alternate builds for a controlled comparison; sequential batches
can still reflect thermal/load drift. Current fixture hashes do not verify simulation
content. Visual review and trajectory parity remain separate checks.

The server checks source identity again before each timed run and rejects stale
startup metadata after edits. Finish edits, restart Vite, and reload before a batch.
Hidden tabs, changing fixtures/viewports/settings, context loss, and stalled rendering
retain the manual capture's invalidation behavior. Starting a second capture or a
snapshot during a capture is rejected.

## Compare production builds in the same real browser

Build each checkout with its isolated backend port, then start its preview with
the same port setting and `NADOC_VIEWER_TEST=1`. The automated runner expects frozen
A on 8020/5180 and candidate B on 8021/5181. Candidate B's backend must use an
isolated `NADOC_WORKSPACE` containing byte-identical fixture copies; neither backend
uses reload or session recovery during measurement.

```bash
# In baseline/frontend, with its isolated backend on 8020:
VITE_API_PORT=8020 npm run build
NADOC_VIEWER_TEST=1 VITE_API_PORT=8020 npx vite preview --host 127.0.0.1 --port 5180 --strictPort

# In candidate/frontend, with its isolated backend on 8021:
VITE_API_PORT=8021 npm run build
NADOC_VIEWER_TEST=1 VITE_API_PORT=8021 npx vite preview --host 127.0.0.1 --port 5181 --strictPort

# From the candidate repository, with the normal editor connected on 5173:
node scripts/viewer_ab.mjs --output /absolute/path/to/new-comparison
```

The runner uses one visible browser, visits A/B in ABBAABBAAB order, loads Voltron,
settles, snapshots outside timing, and runs one warmup plus one measured 20-second
orbit per visit. It aborts on an invalid run or unequal workload hashes/settings.
It records five measured runs per build, file-open workflow times, heap/resource
counts, and before/after images. It returns the browser to the original editor and
reopens the fixture afterward. Override `--file` for another native workspace file.
The **visit** command is limited to the same loopback hostname and ports
5173/5180/5181, and checks reachability before leaving the working page.

Per-run file-open time includes normal application load/progress completion;
it is not a cold-filesystem, app-startup, GPU-upload, or input-to-photon metric.
The first visits should be preflighted equally so filesystem/asset caches are warm.
No claims about Zoom/network quality, four-client meetings, or trajectories follow
from a static local render-loop comparison.

## Preserve A independently of later changes

From the development checkout, create a new detached baseline worktree:

```bash
python3 scripts/prepare_viewer_baseline.py /home/joshua/NADOC-viewer-baseline
```

The script pins the pre-refactor commit and adds only capture instrumentation.
It refuses existing directories, does not commit anything, and records provenance.
Dependency directories are symlinked to the existing installation; do not reinstall
dependencies through those links. Viewer assets and the workspace stay separate.
Run the script again to a *new* directory if the instrumentation contract changes.

For production-build comparisons, use separate terminals in the baseline checkout:

```bash
# Terminal 1, baseline root. No reload and no session recovery.
NADOC_DISABLE_SESSION_CACHE=1 uv run uvicorn backend.api.main:app --host 127.0.0.1 --port 8020 --timeout-graceful-shutdown 5
```

```bash
# Terminal 2, baseline frontend directory.
VITE_API_PORT=8020 npm run build
VITE_API_PORT=8020 npx vite preview --host 127.0.0.1 --port 5180 --strictPort
```

Open `http://127.0.0.1:5180`. Load *copies* of benchmark files into the isolated
baseline workspace, never originals you are actively editing. Assembly source
paths must resolve to copied parts as well. Keep fixture content identical.
The baseline launch does not expose the app to other machines.

Candidate B needs its own isolated workspace/backend and frontend ports (for
example 8021/5181), with the same build mode and measurement instrumentation.
Do not use the live editor backend on port 8000 for automated comparisons.
Stop test terminals with Ctrl-C when finished. Preserve original copyable records.

## Remaining Phase 0 gates

- Selected: VoltronCoreArmV2 for Full/protein/nanoparticle viewing and cube_pore for
  graphene/ion-transport trajectories. A large assembly fixture remains outstanding.
- Static Voltron production A/B is complete for the first decoder extraction;
  repeat after later viewer changes. Measure instrumentation overhead separately.
- Load/picking/trajectory-specific instrumentation and scene-content identity.
- Manual visual/gesture acceptance and browser matrix checks in later phases.

## Production comparison — current checkpoint

Five measured 20-second orbits per build on Windows Chrome/RTX 2080 SUPER at
1272 × 833: baseline/candidate median FPS 42.34/42.78, p95 26.0/26.6 ms,
file-open workflow 5.57/5.64 seconds. Median sampled peak JS heap is 792/772 MB.
Initial regression gates pass. All 20 primary before/after PNGs match; camera and
controls restore. Candidate has more tail spikes, retained in the report; a separate
BA confirmation pair did not repeat the sustained p95 spike. Full results and limits:
[production comparison](audits/viewer_ab_production_20260920/README.md).

This validates the current static decoder extraction, not standalone package,
trajectory, assembly, meeting, or Zoom quality. The automation loads fixtures itself
and keeps manual Process Log captures available for future checks.

## Earlier checkpoint evidence

The local API bridge has now loaded VoltronCoreArmV2 and captured a real Windows
Chrome/RTX 2080 SUPER batch: one warmup plus five valid 20-second orbits, median
39.876 FPS and median per-run p95 28.700 ms at 927 × 833. Camera/controls restored;
before/after canvas PNGs were byte-identical. Raw records, images, and limitations
are in `audits/viewer_live_20260920_repeat/README.md`. This validates automation and
current-build repeatability; the subsequent production comparison above supplies
frozen-baseline A/B evidence at a different viewport and build mode.

The user supplied a valid 20-second VoltronCoreArmV2 capture on Chrome/Windows and
an RTX 2080 SUPER: 500 intervals, mean 24.98 FPS, p95 46.5 ms, p99 49.7 ms, sampled
JS heap 533,742,405 bytes. The reported last render pass had 2,677 draw calls and
6,069,870 triangles. These are observed costs, not a diagnosis of the bottleneck.
The original A label is preserved in `audits/viewer_user_reference_20260920.json`;
the frozen-worktree provenance was not confirmed, so it is a hardware reference.
The capture does not include a manual visibility/controls-restoration verdict.

Small-scene headless A/B probes produced real records saved in
`audits/viewer_headless_probe_20260920.json`. They are **ineligible for a performance
verdict**: software rendering is noisy, workspaces/background traffic differed,
and runtime document hashes differed despite using identical source files.
The Voltron headless probe yielded insufficient frame samples, not a valid result.
Stable prepared-scene hashes and measured instrumentation overhead remain acceptance
work. Controlled hardware runs are now available for the static Voltron checkpoint.
