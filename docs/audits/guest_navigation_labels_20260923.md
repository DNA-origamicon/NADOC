# Guest navigation and persistent view labels

Guest prepared views now reuse the editor's bottom-right CSS view cube, including
axis/corner snaps and clockwise/counter-clockwise 90-degree roll controls. Bounds
come from the current guest scene. Navigation exits presenter-follow mode and
cancels guest shared-camera motion. The cube hides on scene clear and removes its
DOM, styles and animation callbacks when the viewer is disposed.

The persistent bottom-left tool legend also shows the published simulation engine,
visualization mode, canonical job display name, and run creation date. The date is
captured from `created_at` (Unix seconds), serialized as UTC, and displayed in the
guest's local time with a timezone label. Missing dates are marked unavailable.
Labels are validated and rendered as text. They travel in the prepared snapshot,
so changing a privately inspected job does not change a guest's published label.
Off/native snapshots clear the simulation label while keeping enabled tool labels.
Snapshot signatures include this metadata, so visualization changes republish it.

Export capability checks require `visualization-labels-v1` when a simulation label
is included. Restart an older running sharing host after its current meeting to
load the updated guest bundle and advertise support.

Validation: 216 relevant unit tests passed across the viewer and simulation job
list, including label serialization/validation, native cleanup, capability checks,
and leaving camera-follow via cube navigation. Two Chromium tests passed for
embedded tool labels, actual cube/roll navigation, label persistence and scene
clear. Production build passed with the existing bundle-size warning.
