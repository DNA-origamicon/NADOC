# VR representation parity and acknowledgements — 2026-09-29

Three independent faults were found through the real browser and native viewer:

- The API client's visualization publisher silently converted seven supported
  representations to Full. Both publication paths now use `nativeRepresentation`,
  the shared eleven-representation contract. Surface could render on desktop
  while VR remained at 99%; it now receives the actual Surface acknowledgement.
- Native selective installation treated the reference axes injected into an
  otherwise absent Full block as replacement geometry. Loading Surface/Hull/
  Cylinders could erase resident Full, leaving Beads blank. Installation now
  respects availability derived before reference axes are added.
- Sidebar ray intersection was missing from controller-guide rendering. An
  unpressed controller now draws a ray to the nearest open sidebar, independently
  of molecular selection. Closed menus have no such ray.

Cylinder export now calls the desktop `buildHelixObjects` builder in cylinder
LOD and exports its actual mesh triangles and normals. This shares the 1.125 nm
radius, staple-domain segmentation, persisted strand/group colors, cluster
palettes, half cylinders and curved tubes. Native rendering uses triangle indices
for these faces. The old narrower scaffold-colored reconstruction remains only
as compatibility fallback for direct serializer callers without desktop geometry.
Lighting still differs between the desktop and native renderers. This does not
add synchronization for transient desktop radius-slider edits after export.

## Verification and retained attempts

The browser tour opens a private `__e2e__` copy of the user's 24HB through the
production Open flow, then invokes View in VR. Only the actual browser publishes
acknowledgements. Diagnostic scene placement centers the part in the tracked
view. ScryWrite moves the controller using the existing motion profiles. Each
representation must reach 100%, have its requested style active, and show over
100 identified model pixels in each submitted eye. Reference axes cannot satisfy
that oracle. The source document is compared before/after; private files,
documents, caches, viewer and sidecars are removed in failure-safe cleanup.

- `all-reps-baseline` and `all-reps-diagnosis`: Surface reproduced at 99% with
  desktop publications still saying Full. The desktop screenshot showed Surface.
- `all-reps-shared`: interrupted after the publisher's outdated list was found.
- `all-reps-fixed`: controller timing failed while broad suites were competing
  for CPU. Motion thresholds were retained.
- `cylinders-shared`: native cylinder loading, visible pixels and desktop menu
  passed. Diagnostic response logging raced browser shutdown; the logger now
  handles teardown without changing feature assertions.
- `all-reps-final`: Surface, Hull, Cylinders, Beads and Ball & Stick acknowledged
  at 100%, but image inspection exposed zero model pixels for Beads. The next
  controller reach also overlapped a delayed desktop-view upload. The oracle now
  checks pixels after every representation; a three-second settling interval is
  outside each measured reach. No timing threshold was relaxed.

Native real-GL regressions pass for all eleven first acknowledgements, partial
scene installation preserving Full, sidebar hover-ray presence/absence and
rendered primitive identity/occlusion. Selective export tests: 14 passed,
including measured cylinder radius and saved staple color. Frontend: 577 files,
7,283 tests passed, 1 skipped.

Backend selector: `FAST  (fast suite only)`. 9,444 passed, 93 skipped; the previously
observed `tests/test_geometry.py::test_the_scalar_and_loop_skip_fast_paths_agree`
failed again. Runtime: 45 seconds / 60-second budget.

Selector deferral, verbatim:

> DEFERRED: this change would have needed the FULL suite, but no test-dedicated
> session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
> This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
> Only request `just test-session` when a broad/full sweep is actually needed.

Browser diagnostics retain an unrelated private-copy `/design/save-workspace`
HTTP 500 and unavailable WebXR-runtime message; the browser falls back to the
native companion normally. These are logged separately from uncaught page errors.
Stereo captures establish submitted eye output, not through-lens comfort.

## Final accepted evidence

`all-reps-complete/representation-summary.json` records all eleven styles plus a
second Cylinder switch reaching 100% with visible, identified model pixels in
both submitted eyes. Counts ranged from 50,711 (Beads, right) to 137,288 (Hull,
left). Full survived every partial installation. This proves the full list's
loading/rendering path; it does **not** mean the full heavy-session motion matrix
passed. That session retained several 151–163 ms late reaches and stopped after
three failed deliberate reaches. Its source document and private resources were
cleaned up.

`cylinder-final-matrix/result.json` passed on the final rebuilt binary after
extracting the ray helper into SidebarRuntime: all four presets, seven successful
Full/Cylinder switches, 16 real browser publications, zero timing retries or
uncaught browser errors, final desktop Cylinders, and identifiable geometry in
both eyes. Captures show the unpressed aiming ray and colored domain cylinders.
The native GL regressions also passed after this final build.

`just smoke`: 23 passed. `just lint` found one unrelated unused `pathlib.Path`
import in `tests/test_cpd_shape_revision_v2.py`; the changed VR files pass scoped
Ruff. `git diff --check` and JavaScript syntax checks pass. `main.js` LOC delta is
+1, solely error logging; the sidebar ray implementation is in its runtime module.

`validation-20260929/cleanup.json` verifies all nine owned viewer processes,
sockets and sidecars absent, no private workspace files/caches, and an unchanged
smoke fixture. The interrupted diagnosis left an empty owned socket directory;
the cleanup audit removed it. Original design equality passed in each wrapper.
Validation logs and screenshots remain under `.development-artifacts/vr-lazy/`.
