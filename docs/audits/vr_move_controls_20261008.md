# Move / Rotate controls and size-one polymer bend — 2026-10-08

Move now has an explicit Selection field, a persistent preview, separate right
trigger translation/right grip orientation, authored XYZ offsets rounded to
three decimal places, Euler rotation fields, 15-degree controller rotation snap,
and six 20%-exposed 0–100 preset thumbwheels. Each manual detent/arrow changes
1 nm or 1 degree. Green Apply is right of Cancel; both history buttons use the
existing versioned desktop/VR Undo/Redo channel. Apply commits one feature entry.

Polymer-circle count 1 is accepted, persisted, and restored. The corrected
single-copy calculation includes one closing connector step, so the occupied
endpoints do not coincide (see the off-by-one follow-up below). No new
strand-routing algorithm or molecular placement rule was added.

Validation:

- Native viewer built successfully using the system toolchain (the inherited
  Conda linker could not resolve system OpenXR/GL dependencies).
- `ctest --test-dir native/vr_viewer/build -R 'nadoc-vr-move-(panel|hands)$'`:
  both pass. Production input paths cover translation, release retention,
  grip rotation, snap, manual/wheel detents, Cancel, Apply, history requests and
  tracking loss. Frame tests cover rotated export bases and room transforms.
- 84 frontend unit tests pass across bend popup, move pose, tool transaction,
  VR history and renderer authority modules.
- Browser transaction test passes real backend Cancel/commit/Undo/Redo, exact
  cluster transforms and exact feature history. Only absent headset transport
  is intercepted.
- 81 backend tests pass across bend parameter/count persistence, full placement,
  scoped history and VR export. One known mutable-workspace count test is
  deselected in the final run; its earlier failure is retained and reviewed.
- Panel layout audit and actual GL rendering pass, including green Apply pixels
  and an offscreen negative. Image inspected at 800 × 1000; Return's duplicate
  status text was removed after the first render. No physical headset run:
  SteamVR was not running. Follow-up is MV-VR-MOVE-DRAFT.

The browser check uncovered an existing partial-update transport defect:
`patchNucleotides` discarded the supplied slab pose and placement source before
calling the strict position validator. It now passes all supplied authority and
slabless identity fields. The added regression compares actual bead/slab matrices
against a fresh render, including restoration; maximum matrix difference is zero.
No validator was weakened and no geometry golden changed.

Both generated placement incidents were explicitly reviewed using the repository
review workflow; the gate is clear. The second incident is the existing optional
Manual_Benchy test's 2526-record assumption: the user-editable document now has
6118 bases by independent domain count, and full/compact records agree exactly.
Its original bytes, test and expectations were preserved.

Evidence is retained in `.development-artifacts/vr-move-20261008/`, including the
panel, partial/fresh pose matrices and shared-coordinate plot, failure trace,
backend results, preserved Benchy snapshot, and explicit placement reviews.


## Circle_spiral follow-up

The saved `Circle_spiral.nadoc` exposed a missing display rule: all 12 periodic
seams still emitted three fading next-copy bases at each end. These 72 synthetic
preview bases are deliberately unselectable and lay about 0.3 nm from real sites,
creating the reported phantom strands. They are visualization objects, not saved
strand records.

`polymerization_preview` now hides the continuation for seams whose two endpoints
belong to a size-one circle bend. Frozen ranges, strand direction, affected helices
and bend-window overlap limit the rule to the correct seam. Other clusters and
multi-copy/open polymers retain their guides. Design updates refresh the rule in
place, including metadata-only changes, live preview and Undo/Redo.

Actual saved-file WebGL captures retain the same camera and molecular rendering
before and after. The fixed view has zero visible continuation bases, retains all
10,080 real nucleotides, and exactly matches a diagnostic capture that hid only the
old continuation group. 11,684 image pixels change from the original view; no other
pixels change. The user's file remains byte-for-byte identical (SHA-256
`b24ba293c3c977fec37156fe5df071e49701cd7bf7508381765b1a3e2e817daf`).

Evidence: `.development-artifacts/circle-spiral-preview/` contains the saved input
copy, canonical geometry, before/after/diagnostic images and numeric verification.
Unit regressions cover scoped and unscoped size-one circles, frozen ranges, wrong
directions, unrelated seams, other counts, zero bend, and real-renderer count/history
updates without rebuilding or altering selectable entries. This is a desktop WebGL
check; no new headset claim is made.

## Size-one seam off-by-one follow-up

The earlier endpoint-coincidence regression was incorrect: the first and last
occupied base-pair sites must be one step apart. Count 1 now uses
`360 / (bent seam span + 1)`; the polymerization bond completes the final step.
Multi-copy periodic placement retains its existing next-base transform.
Opening a saved count-1 bend recalculates and previews the corrected curvature;
Apply uses the existing deformation transaction and Undo/Redo. Saved files are
not silently rewritten.

Verified the actual `workspace/Circle_spiral.nadoc` using parameters emitted by
the production popup in Chromium. All 12 seams span 419 intervals across 420
occupied sites. Curvature changes from 0.8591885446 to 0.8571428638 degrees/bp
(the UI rounds the displayed angle). Every seam's bundle-centerline endpoint
gap changes from approximately zero to 0.3339958 nm. Advancing one more curved
step closes within 0.0000011 nm. Both rendered fixtures retain 10,080 real
nucleotides and zero visible continuation-preview beads.

Evidence: `.development-artifacts/circle-spiral-seam/` contains the source
snapshot, browser-emitted parameters, numerical verification, full geometry
fixtures, and before/after seam close-ups through the production helix renderer.
The close-up camera follows the same endpoint at the same offset in both images;
it is a diagnostic desktop rendering, not physical headset evidence. The user
file remains unchanged. The script's initial 1e-8 nm legacy-coincidence check
was adjusted to 1e-6 nm to account for the saved eight-significant-digit angle
(actual residual 7.3e-8 nm); the corrected one-step closure check is 2e-6 nm.

Validation: 26 frontend tests and 43 backend tests pass, including the actual
Circle_spiral stagger/window arithmetic, saved edit Preview/Apply, one-step
closure after save/reload, preview suppression, and existing multi-copy behavior.
Native Full placement review gate remains clear.

## Joined seams and compact desktop bend panel

The routed connector domains were already one ligated staple: Circle_spiral's
12 seams have reciprocal oxDNA 3′/5′ neighbour indices on the same strand. The
missing desktop connection was a rendering classification: every periodic seam
was suppressed as a hidden arc, even when its own part closed the seam.
`polymer_seams.js` now shares the authored count-1/scope predicate between ghost
suppression, ordinary backbone rendering and connection rebuild signatures.
Apply, circle edits, Undo/Redo and partial updates cannot retain stale bond/arc
membership. No strand duplication, extra scaffold closure or proximity-based
ligation was added. VR already emits the short same-strand backbone bonds;
a new native snapshot regression pins their presence and selection ownership.

The desktop popup uses a scrolling field body and fixed action footer. Angle and
Curvature (the existing radius in nm) share a row; the compass and row spacing
are smaller, and Info no longer repeats the plane explanation above Preview.

Validation:

- Full frontend suite: 647 files, 7,706 passed, one skipped. After the final
  partial-update guard, all 54 focused renderer/popup tests passed again.
- Eight polymer-router tests passed, including reciprocal exported seam
  neighbours after bend save/reload. One real-geometry VR snapshot test passed.
- The combined browser run passed all 23 smoke/assembly checks. Its panel test
  was interrupted by the development reload during the final renderer edit;
  the preserved failure shows the cleared editor. Rerunning the unchanged
  panel test against stable code passed. It checks both buttons fully in view
  at 1280×720 and 1280×480, even while the field body scrolls.
- Production helix rendering of the corrected Circle_spiral fixture has all
  12 ordinary, nonzero-radius seam bonds, 10,080 real nucleotides and no visible
  continuation ghosts. The compact panel screenshot shows both actions above
  y=461 in a 480-pixel viewport. This is desktop and native snapshot evidence,
  not physical headset validation. The native placement gate remains clear.

Retained evidence under `.development-artifacts/bend-joined/` includes the
rendered seam close-up, compact panel screenshot, layout coordinates, per-seam
render/export checks and browser logs (including the initial failed attempt).
The existing `.development-artifacts/circle-spiral-seam/after-fixture.json` is
its geometry input. Development captures write only to that artifact directory.
Browser persistence inventory: only `__e2e__` part/project files and their
revision stores; the smoke config disables session caching and global teardown
removes these on failure or success. The cleanup reporter removes Playwright
outputs. Final inspection found no such workspace files or Playwright output
directories. Retained evidence is about 1.7 MiB; no user design was modified.
`main.js` gained zero lines for this follow-up.
