# VR simulation results

The left **Simulations** tab follows the desktop order: CanDo, SNUPI, mrDNA,
oxDNA, NAMD, Exp. Curved engine tabs open the accepted compact split menu.
Select a real job to focus its visualization modes and options; **Jobs** returns
to the list. Job names and timestamps come from the desktop list, with running
percentage or completed production duration when the job reports it. Parent rows
also expose their child-run expand/collapse action. Exp uses the current session.

Point and pull Trigger to select a mode. The right inspector mirrors its desktop
suboptions, including disabled states and exact numeric entry. Both controller menus
can remain open. Simulation results preserve Full, VDW, ball-and-stick, stick, oxDNA,
and coarse/fine mrDNA representations. Beads, cylinders, prisms and surfaces are
disabled while simulation data is displayed, and become available again on Off.
Changing representation preserves the selected trajectory source frame and scalar
colors. MD/oxDNA atomistic frames use their existing engine reconstruction; FEM and
CG sources use the visualized-coordinate atomistic builder. Reconstruction is
serialized and reports progress. Compact FEM views materialize the job snapshot
only when a different representation is requested, retaining frame/scalar identity.
The horizontal color mapper shares the desktop's range and recoloring callback.
Its min/max handles highlight under the ray; drag and release to apply a bound.
The palette button opens the existing six-choice popup around the left controller's
touchpad, with three haptic pulses. Each sector shows its gradient radially from
low (inside) to high (outside), without map names. Press, slide and release to
choose; hover highlights the sector edge. Reset restores the data range.

**Trajectory** first reads the frame count without downloading coordinates.
Set Start, End and Every using the smallest 20%-exposed thumbwheels, then press
**Load**. Hold Trigger on a wheel and drag vertically: slow movements adjust one
frame per detent, faster movements use 10-frame steps for 100+ source frames and
100-frame steps for 1,000+ frames. The current multiplier appears beside the active
wheel. Release stops immediately and sends one acknowledged range update. Start
and End cannot cross; Every stays between one and the source-frame count. Range
edits survive desktop heartbeat updates while dragging and awaiting acknowledgement.
The frame readout still opens exact source-frame entry. Requests for 500 or more
selected frames retain the native confirmation. The raised scrubber, side Play/Pause and lower Previous/Next
buttons operate on the selected source frames. Editing the range invalidates the
prepared frames. **Overlays** exposes the trajectory's visualization suboptions.
Buffering retains the displayed frame number and scrubber position.
Loading and buffering keep a progress indicator visible; unknown totals animate
rather than presenting a fabricated percentage. Errors remain visible in the menu.

NAMD, oxDNA and LAMMPS sample the requested interval before coordinate extraction, then
stream pages of eight frames. The browser retains at most two pages and applies
one frame at a time, preparing the next page during playback. NAMD ions and the
periodic cell follow the exact raw frame IDs in that page and draw only after the
matching DNA frame. Ion/cell extraction reuses cached PSF row/species tables and
the existing display affine, avoiding a whole-solvent topology per page. Cell
visibility reuses the prepared ion payload. Water retains the
desktop live-display availability rule. SNUPI reads indexed single frames. Native scene parsing and
bounds calculation run off the XR render thread. Geometry uploads are staged into
spare buffers; playback updates reuse the texture atlas. These measures bound
work and memory; measured frame/compositor timing is still required to establish
90 Hz on a particular scene and machine.

The scene stream transports actual displayed meshes, colors and opacity.
**Frame result** fits the currently displayed result. These are display operations,
never topology edits.

The browser/native bridge is document-bound. Versioned snapshots reject stale
requests; sequence acknowledgements prevent duplicate activations. Switching jobs
or engines invalidates old result targets. Native input waits for a desktop
acknowledgement before submitting another result action.

## Demo and validation

**Debug → VR Tours & Tests → Left sidebar → Simulation results · 2hb_1xT**
launches a private copy of the existing completed results. No simulation is launched.
The original design, metadata and result caches remain untouched. Immutable
DCD/XTC/TRR inputs are linked into a temporary workspace; writable files are copied.
The workspace and owned viewer are removed on exit, including failed tests.

```sh
uv run python -m tools.vr_workflows.simulation_tour
uv run python -m tools.vr_workflows.simulation_tour --validate
# Temporary 24HB fixture (also registered under the Left sidebar category):
uv run python -m tools.vr_workflows.simulation_24hb_tour --validate
```

Demo starts with `steady_fast`; validation requests all four unchanged human-motion
profiles. Navigation, activation, desktop state, native result delivery and submitted
stereo captures are retained beneath `.development-artifacts/vr-simulations` (or the
Debug launcher's output directory). The tour records unavailable modes per job and
activates available static modes, tests slow/fast drags on all three range wheels,
and exercises the explicit trajectory load/playback path. It repositions the menu and
uses normal model grips to fit/enlarge results for observation. Those presentation
adjustments are outside measured navigation reaches.

Software-generated controller input and submitted-eye captures do not establish
physical headset legibility, comfort or panel scanout. See the [implementation audit](audits/vr_simulations_20261012.md)
for the runs actually completed and any failed attempts.

## Known CanDo result bug

The existing `2hb_1xT` CanDo predicted shape expands far beyond its native shape.
This is a known unresolved result bug, not expected deformation. The design itself
or small designs in general are suspected contributors; the cause is unconfirmed.
Debugging it is deferred at the user's request. VR checks establish navigation,
activation and faithful display of the saved result, not scientific correctness of
that shape. Framing/enlarging the result for observation does not repair it.

Range-wheel validation (2026-10-12): both steady profiles passed full P1 RunPod
range editing, explicit loading and playback. Both rendered eyes and desktop
mirror showed all three cylinders. High-jitter acquisition remains limited:
variable-fast missed the Start cylinder and variable-deliberate missed All Frames.
The physical wheel highlight is the acquisition oracle; a hit on the surrounding
slot alone is insufficient. See `.development-artifacts/vr-range-wheels-20261012/review.json`
for retained failures and the atomic range-publication fix (ISSUE-72).
