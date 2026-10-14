# VR Join clusters

Open **Tools → Join**. Join switches scene selection to **Cluster**. Pull a
trigger on the cluster to move, then point the right controller at its geometry
or cyan preview. Hold **Trigger** to translate and **Grip** to rotate about the
cluster center. Releasing retains the draft so repeated grabs can accumulate.

The **Position** and **Rotation** fields use the same ridged thumbwheels, borders,
labels, fonts, pointer beams and frosted panel as Move / Rotate. Position
adjustments snap to the nearest **1 nm** and angle adjustments to **15°**.
Unclaimed grips retain scene navigation; the menu border retains its grab and
resize behavior.

Nearby connection guides update while the cluster moves. They are provisional:
the desktop Join operation checks attachment compatibility, clearance and
routing before enabling **Apply**. Changing the pose retires the previous
validation. **Apply** commits the current pose and its validated connections in
one ordinary desktop Join history entry. Existing Join behavior also governs
unrouted precursor connections and later scaffold routing.

**Reach** adjusts the same 0.3–10 nm connection search radius as desktop Free
movement, in 0.1 nm steps. Changing it updates the live guides immediately and
requires validation of the new reach before Apply. The selection wheel retains
Cluster scope while Join is active. Late pose feedback cannot replace a newer
released draft.

**Cancel** discards the entire draft translation and rotation. The preview never
writes the original cluster pose or routing, so cancellation needs no compensating
design edit. Changing the selected cluster or leaving the tool also discards the
old draft. Undo/Redo after Apply use the shared desktop feature history.

Join retains the desktop restrictions on supported cluster ownership, existing
connections and routing. See [Join clusters](cluster_join.md) for the molecular
operation and validation limits.

## Rendering and verification

Movement uses the native Move / Rotate sampled geometry path: resident bounded
geometry plus a changing rigid matrix. A cached spatial index supplies provisional
guides with at most 256 moving sites, 4,096 pair comparisons and 32 guides per
frame. Full connection discovery and routing checks run asynchronously. Native
drawing consumes bounded connection feedback and rejects feedback for an obsolete draft. The frame budget
for 90 Hz is **11.11 ms**; asynchronous validation latency is measured separately
from rendering cadence.

The reusable check is available under **Debug → VR Tours & Tests → Tools ·
Authoring**. Software interaction, browser/backend routing and rendered panel
checks establish separate parts of the workflow. Physical controller comfort,
through-lens legibility and sustained headset frame rate require a tracked runtime
measurement; an offscreen render or a browser test cannot establish them.

```sh
uv run python -m tools.vr_workflows.join_tour --browser --validate
uv run python -m tools.vr_workflows.join_tour --profile steady_fast
uv run python -m tools.vr_workflows.join_tour --validate
uv run python -m tools.vr_workflows.join_tour --profile steady_fast \
  --capture-final /absolute/archive/active-compositor-capture-directory
```

The browser check intercepts VR transport and exercises the real desktop Join
backend in an isolated temporary workspace. The physical tour uses the generated
two-cluster fixture and production controller handlers; `--validate` runs all four
unchanged human-motion presets. Both retain evidence on the Archive drive and
verify cleanup of their temporary designs and revision stores. Short Archive
scratch paths keep native Unix sockets below the operating system's path limit.

The optional final-output run uses the existing instrumented compositor, with
two-second recordings around translation and rotation and a five-second recording
around Apply and native scene refresh. It requires the
pose journal and submitted-frame markers. Controller playback starts after the
capture acknowledgement, with recorder and controller commands serialized.
Released poses must receive feedback for their exact transform sequence. The
tour retains compact motion observations, operation intervals, recording reports
and copied pose journals; pixel integrity and repeated-image analysis use the
[current capture and tracking tools](vr_origami_tracking.md). A recording covers
only its acknowledged window, even if routing finishes later.

Recorded software checks, physical-runtime attempts and performance limits are in
[the current validation report](../.development-artifacts/vr-join-20261013/verification-summary.json).
The Vive used here runs at 90 Hz. Scripted controller playback and submitted-eye
captures verify interaction and rendering; they do not establish human comfort
or an output rate above 90 fps. Apply/scene-refresh windows can repeat or drop
compositor frames even when the live movement preview stays within budget.

### October 13 follow-up

The duplicate-preview sequence after Cancel/reselection now preserves its valid
proposal instead of leaving Apply stuck in checking (ISSUE-78). Nick/Ligate
feedback uses a persistent reader: header reads, parsing and old-table destruction
stay off the headset thread. Apply measurements now include native scene refresh.

Software validation: 7,906 frontend tests, 130 focused VR backend tests (including
seven recorder checks), four native checks, two browser Join/menu checks and 23
smoke checks passed. All four unchanged physical motion profiles now pass the
full Join/Cancel/reselection/Apply/Undo flow, producing one routed scaffold with
unchanged staples. Across the 20 explicit Join intervals, application cadence is
89.51–89.55 submissions/s. No frame exceeds the 11.11 ms non-runtime-wait CPU
budget (maximum 4.85 ms), and no compositor frames are dropped. Movement and
released validation have no repeated frames; Apply/refresh has 1–2 repeats per
profile. This supports responsive operation on the 90 Hz runtime, **not a strict
uninterrupted 90 FPS guarantee**. See `remote-matrix-metrics.json` in the evidence
folder for every interval, GPU timings and limitations.

The earlier pre-worker Apply interval ran at 83.05 submissions/s with 8 repeats
and 11 drops. Its Nick/Ligate phase peaked at 82.60 ms; the final four-profile
maximum is 0.0025 ms. The restart also relieved host memory pressure, so the
overall improvement cannot be attributed solely to the worker change.

The unexpected restart preserved source/binary hashes; its cause remains
unknown. SteamVR's open dashboard withheld input after restart. Sending its normal
`hide_dashboard_requested` / `return_to_game` command remotely restored focus;
no physical wake, runtime restart or settings change was required. Earlier
failures, the reviewed infrastructure-only placement-gate incident, and cleanup
records remain in the current validation report.

The final compositor capture also passed: 179 translation, 179 rotation and 448
Apply stereo frames were saved with complete pose journals. All 1,612 eye markers
joined exact submitted-frame identities with no unknowns, reuse or gaps. The
Apply clip includes the native scene revision change. First-frame ROI calibration
and its original failures are retained; the other 803 frames were held out with
unchanged decoder thresholds. See `final-pixels/summary.json` and
`final-capture-coverage.json`. These are captured display-surface pixels, not
through-lens or physical scanout measurements.

### Validation-data retention

After completed validation, delete raw compositor recordings, extracted images,
depth/object-ID buffers, pose/frame dumps, browser traces and copied test designs.
Keep compact outcomes, timing/failure summaries and a cleanup inventory. On
October 13 the user requested this policy; the completed October 11/13 Join data
was pruned accordingly. Historical raw-evidence links above are no longer
replayable; the validation summary and `bulk-cleanup.json` remain. The configured
viewer build and active SteamVR runtime are preserved. Retain large captures
beyond validation only on explicit user request.
