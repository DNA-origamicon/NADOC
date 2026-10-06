# VR simulation results

The left **Simulations** tab follows the desktop engine order: CanDo, SNUPI,
mrDNA, oxDNA, NAMD. Engine tabs remain at the top. The Jobs card mirrors the
current desktop list, including labels, selection and child-job rows.
Select a job to extend the menu to the right with that engine's actual
Visualizations card controls. Selecting a job with the menu open closes the right
sidebar to prevent the two panels from overlapping. Each column scrolls independently. Point and pull Trigger to activate a control;
point at a scrollbar and click or drag its thumb to page. Unclicked touchpad
swipes scroll the column under the ray. Left-pad clicks are reserved for the
selection wheel.

Availability and checked states come from the desktop controls. Select choices
appear as individual buttons; numeric/range controls have minus/plus steps with
the desktop's bounds. Trajectory controls are excluded. Selecting a result invokes
the normal desktop event handler, including its job-specific loading and guards.
The existing native scene stream transports actual displayed meshes, colors and
opacity. **Frame result** fits the currently displayed meshes, which can extend
beyond the original design. These are display operations, never topology edits.

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
```

Demo starts with `steady_fast`; validation requests all four unchanged human-motion
profiles. Navigation, activation, desktop state, native result delivery and submitted
stereo captures are retained beneath `.development-artifacts/vr-simulations` (or the
Debug launcher's output directory). The tour records unavailable modes per job and
activates available static modes across the job list. It repositions the menu and
uses normal model grips to fit/enlarge results for observation. Those presentation
adjustments are outside measured navigation reaches.

Software-generated controller input and submitted-eye captures do not establish
physical headset legibility, comfort or panel scanout. See the [implementation audit](audits/vr_simulations_20260928.md)
for the runs actually completed and any failed attempts.

## Known CanDo result bug

The existing `2hb_1xT` CanDo predicted shape expands far beyond its native shape.
This is a known unresolved result bug, not expected deformation. The design itself
or small designs in general are suspected contributors; the cause is unconfirmed.
Debugging it is deferred at the user's request. VR checks establish navigation,
activation and faithful display of the saved result, not scientific correctness of
that shape. Framing/enlarging the result for observation does not repair it.
