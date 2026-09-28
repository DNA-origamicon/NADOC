# VR Move / Rotate validation — 2026-09-28

The right Tools panel and radial Move / Rotate entry use trigger grabs of a
selected center. Grips retain scene movement. A released grab saves one exact
transaction; its final matrix travels with Confirm, including when a browser
poll misses the intermediate Preview event. Selection is checked again after
asynchronous desktop preview activation.

The generated test part contains a desktop-painted 6HB, a seven-base overhang,
and a named helix cluster. Tests never open a fixture or existing user part.
Target selection, centroid acquisition, movement, wrist rotation, menu controls
and scene grips use actual ScryWrite controller input with unchanged profiles.

## Evidence and checks

Final matrix: `.development-artifacts/vr-move/fast-validated-20260928/`.
Each case retains controller reaches, before/preview/after stereo captures,
object IDs/depth, exact-scope geometry checks, saved `.nadoc`, Undo evidence,
controller-to-saved-center error, and release acknowledgment timing.

Expected changed/unchanged backbone counts are:

- Cluster: 91 / 420, including its attached overhang.
- Overhang: 7 / 504.
- Base: 1 / 510.

Independent checks require saved base poses to reproduce backend backbone/base
positions, unrelated bases to remain fixed, one history entry per grab, exact
Undo, and saved transforms surviving a fresh document load. Both submitted eyes
must contain identifiable moving target geometry and stationary other geometry.
The image oracle rejects blank and unchanged evidence. Saved center error must
remain below 2 mm relative to actual controller displacement; release must be
acknowledged within five seconds without regenerating the scene.

Native GL coverage also commits a cluster, switches representation, commits a
child base, checks updated parent/overhang centers, undoes the base, rotates the
overhang, and undoes it. This exercises cached ownership and related pivots used
for successive edits without rebuilding every representation.

## Findings retained from development

Failed runs remain alongside the final matrix. They exposed missing normals on
headless overhang marker quads, connecting bonds suppressing valid bead picks,
multiple bases being selected by a single Move / Rotate pick, and poor framing
relative to the tracked headset. The final tours use the ordinary Frame Model
control, hide the controls while editing, and record a grip-based oblique review
view separately from measured controller reaches.

A full native scene refresh on every release took 17.06 seconds on this small
part. It was removed from the rigid-edit path. Native endpoint ownership now
commits/undoes the existing geometry, and related handle centers receive the
correct average displacement. The interrupted `validated-20260928` run preserves
that timing evidence; the `fast-validated-20260928` matrix tests the final path.

The original workspace file autosaves Undo, so reload checks use the retained
on-disk copy captured immediately after saving the transformed part.

These captures establish application-submitted stereo rendering and controller
input behavior. They do not establish through-lens comfort or large-model
performance. Every tour stops its owned viewer and removes its temporary
workspace; only review evidence remains.

## Final result

All 12 physical-runtime cases passed. Native tests: 45; focused browser unit
tests: 113; backend/contract/oracle tests: 103. The frontend production build passed.

Release acknowledgment ranged from 0.356 to 0.709 seconds
(median 0.535), with no full scene rebuild in any case.
Maximum saved-center error was 0.0000101 m.
The exact saved Base identity was also checked against the native selection for
all four Base captures. These timings describe the generated 511-base test part.

| Target | Profile | Save acknowledgment (s) | Changed / unchanged bases |
| --- | --- | ---: | ---: |
| cluster | steady_fast | 0.412 | 91 / 420 |
| cluster | steady_deliberate | 0.584 | 91 / 420 |
| cluster | variable_fast | 0.597 | 91 / 420 |
| cluster | variable_deliberate | 0.709 | 91 / 420 |
| overhang | steady_fast | 0.526 | 7 / 504 |
| overhang | steady_deliberate | 0.543 | 7 / 504 |
| overhang | variable_fast | 0.356 | 7 / 504 |
| overhang | variable_deliberate | 0.539 | 7 / 504 |
| base | steady_fast | 0.531 | 1 / 510 |
| base | steady_deliberate | 0.481 | 1 / 510 |
| base | variable_fast | 0.588 | 1 / 510 |
| base | variable_deliberate | 0.485 | 1 / 510 |
