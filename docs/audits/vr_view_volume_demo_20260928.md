# View Volumes ScryWrite tests and demo — 2026-09-28

The Debug catalog now exposes **VR Tours & Tests → View Volumes → View volumes
demo / validation**. Both invoke the same document-bound ScryWrite workflow on
an isolated fixture. Demo mode uses `steady_fast`, holds observable milestones
outside measured motion, and leaves the final volume visible until Stop tour or
Ctrl+C. `--exit` provides bounded automation. Validation skips review holds,
tests both shapes across all four motion profiles, and exits.

The workflow now drives the actual title card and menu controls using
trackpad/trigger events: square/hex creation, outline hide/show, disable/enable,
delete, and return. Original desktop records must survive those operations.
The existing centroid, rigid movement/rotation, side-face resize, scene grip and
persistence checks now also test end-face length resizing independently from
width/radius and centroid position.

Highlight verification samples inset face edges away from the orange controller
at the face center. Unit tests ensure a controller alone cannot pass; blank,
wrong-color, offscreen, behind-camera, empty and missing-eye evidence also fails.
The menu-created mirror was visually inspected and shows the original record
plus square/hex records and their controls.

Verification:

- 17 focused Python tests pass, including demo/validation catalog routing,
  fixed launcher arguments, evidence negatives, and persistence tests.
- Both Chromium tour-menu scenarios pass, including the new demo/validation
  flyout and its direct-launch request.
- All eight live-runtime validation cases pass, covering both shapes and all
  four presets, menu controls, side/end resizing and persistence. The stronger
  face-edge assertion was also applied to all sixteen recorded face captures:
  every sampled edge matched in both eyes. The final bounded demo exercises
  that assertion directly with both shapes.

Evidence:

- [Full validation](../../.development-artifacts/vr-view-volumes/tour-validation-20260928/result.json)
- [Face-edge evidence recheck](../../.development-artifacts/vr-view-volumes/tour-validation-20260928/face-perimeter-recheck.json)
- [Bounded complete demo](../../.development-artifacts/vr-view-volumes/demo-complete-20260928/result.json)
- [Menu mirror](../../.development-artifacts/vr-view-volumes/demo-20260928/menu-created/mirror.png)

Commands: `just vr-view-volumes-demo` and `just vr-view-volumes-test`.
For bounded demo automation: `just vr-view-volumes-demo --hold 0.5 --exit`.
See [the user-facing demo instructions](../vr_workflow_demo.md#view-volumes-demo-and-scrywrite-validation).
The tests use simulated controllers in the physical runtime; human through-lens
comfort is not established by these captures.
