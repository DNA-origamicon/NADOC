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
```

The browser check intercepts VR transport and exercises the real desktop Join
backend in an isolated temporary workspace. The physical tour uses the generated
two-cluster fixture and production controller handlers; `--validate` runs all four
unchanged human-motion presets. Both retain evidence on the Archive drive and
verify cleanup of their temporary designs and revision stores. Short Archive
scratch paths keep native Unix sockets below the operating system's path limit.

Recorded software checks, physical-runtime attempts and performance limits are in
[the implementation validation report](../.development-artifacts/vr-join-20261011/verification-summary.json).
The Vive used here runs at 90 Hz. Scripted controller playback and submitted-eye
captures verify interaction and rendering; they do not establish human comfort
or an output rate above 90 fps. Apply/scene-refresh windows can repeat or drop
compositor frames even when the live movement preview stays within budget.
