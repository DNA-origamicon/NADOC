# Guide-driven UX findings

[Guide library](README.md) · [Coverage ledger](LEDGER.md)

Guide completion and UX resolution are separate. These observations were made
while capturing the desktop Extrude guide on November 11, 2026. None is
claimed fixed by selecting a workaround in the recipe.

| ID | Feature / step | Observation | Recipe workaround | Status / acceptance |
|---|---|---|---|---|
| GUIDE-UX-001 | Extrude: select footprint | The floating tool panel covers origin cells at the capture viewport. Clicking their projected locations hits the panel rather than the lattice. | Use an unobstructed footprint (current 3×6 draft: rows 0–2, columns 1–6); verify that each target reaches the canvas. Move the floating panel when needed. | Open. Review panel placement/occlusion and ensure intended targets remain reachable through an obvious interaction. |
| GUIDE-UX-002 | Extrude: inspect result | The initial camera emphasizes helix ends; fitting after orbit can leave geometry behind the sidebar. | Right-drag to expose length, fit, then scroll down slightly. | Open. Review framing against the unobscured viewport and whether a useful post-extrusion view is discoverable. |
| GUIDE-UX-003 | Extrude: change length units | Switching bp/nm keeps the numeric field and reinterprets it, rather than converting the value to preserve physical length. | Explicitly enter 21.376 nm for the 64 bp example, then restore 64 when switching back to bp. | Open. Review whether unit conversion or clearer feedback would prevent unintended length changes. |
| GUIDE-UX-004 | Extrude: deformed continuation on square lattice | Source review: `backend/core/lattice.py::make_bundle_deformed_continuation` uses `honeycomb_position` and honeycomb phase/direction conventions without a square branch; `BundleDeformedContinuationRequest` does not carry strand-filter/ligation inputs. A recorded operation alone would not establish correct square placement. | Exclude deformed continuation from the focused Extrude lesson; keep Bend in its own guide. Do not publish a deformed extrusion from the square example. | Open. Implement and review square-aware continuation and option semantics separately, then verify source-end attachment, lattice identity, preview/commit agreement and independent replay before completing guide coverage. |

| GUIDE-UX-005 | Startup / early guide screenshots | The delayed selection-shortcut toast appeared in fresh browser contexts and obscured guide images; its one-time flag was browser-local. | None. Removed the automatic startup hint; shortcuts remain available on demand under Help. | Resolved November 12, 2026. Fresh-start/reload smoke checks pass with the old flag absent. All 65 guide screenshots were recaptured with a check rejecting this hint. |

Workflow revision, November 11: Extrude now separates normal-view cross-section
selection from a fitted 3D length preview, using the same cross-section controller
as Sweep. The camera fit reserves space beside the popup. This addresses the
selection/framing friction behind GUIDE-UX-001/002; human review across window
sizes remains tracked as MV-61. Unit conversion and square deformed-continuation
semantics (003/004) are unchanged.

For each new finding, record the guide/step, reproduction context, user impact,
workaround, status and acceptance check. Link to the central issue ledger if the
finding is promoted to a development issue; do not imply that this local ID is
already a centrally triaged bug. Preserve findings when guides are regenerated.

Editorial revision, November 12: removed cancellation, Undo/Redo and history-editing
chapters from Extrude. Bend is now a separate lesson. GUIDE-UX-004 remains open;
removing its demonstration does not resolve the implementation gap.

| ID | Workflow | Finding | Guide handling | Status |
|---|---|---|---|---|
| GUIDE-UX-006 | Bend: radius field | The label “Curvature” uses nm and controls a radius, while mathematical curvature has inverse-length units. | Explain the actual radius meaning beside the screenshot. | Open. Review renaming the field to Radius and keeping the κ readout distinct. |
| GUIDE-UX-007 | Bend: review preview controls | The preview expires after 60 seconds from preparation, including time spent reviewing settings; controls become disabled and ask the user to reopen. Full rendering and multiple screenshots exceeded this lifetime. | Capture one populated controls image per preview session, then apply promptly. The 256 bp guide exceeded the lifetime under Chromium’s default software renderer; ANGLE OpenGL completed both bends within their sessions. Do not extend the lease or hide the expired state. | Open. Review a user-visible renewal/recovery workflow and distinguish active editing from abandoned previews. |
| GUIDE-UX-008 | Bend: inspect after Apply | After a successful recorded bend, the captured scene remained dimmed with a tool marker even after turning BLUNT off and moving the cursor away. | Reopen the saved part before inspecting the result. Escape, BLUNT off and moving the cursor did not clear the display artifact. | Open. Review tool-exit state and opacity restoration after Bend publication. |
| GUIDE-UX-009 | Bend: live plane guides | Plane B retained its original pose while the owned preview bent the selected cluster. | The owned editor now refreshes both guides from the evaluated display axes and restores prefix axes when preview is disabled. | Resolved. Regression tests cover both plane poses and teardown; the two-cluster Tools → Bend capture verifies plane B translation/rotation and selected helix membership. |

Twist guide review: the same two-cluster workflow uses two adjacent 180° twist
intervals with opposite handedness. The recipe retains GUIDE-UX-008’s saved-part
reopen for clean result framing and verifies that only the selected cluster is
deformed. Both Full 3D and the cadnano path view display the same saved loop/skip
marks. Preview settings and Apply remain within the existing session lifetime.

Twist correction review, November 12: the guide exposed independent square
baseline and twist marks, including an RH/LH sign mismatch. New Add Loops/Skips
commands now combine signed contributions within each duplex/deformation
interval and preserve separate opposite-handed sections. Saved legacy histories
retain their original replay behavior. Native CanDo-style FEM confirms the
corrected handedness on a 3×6×256 bp bundle; requested-angle calibration remains
open (RH +180° predicts +43.0°, LH −180° predicts −11.1°). The native model uses
per-helix net strain and cannot validate the local cancellation pattern itself.

Feature Log guide review:

| ID | Workflow | Finding | Guide handling | Status |
|---|---|---|---|---|
| GUIDE-UX-014 | Embedded part history | The part-instance delete branches in `feature_log_panel.js` splice feature records without rebuilding molecular state, unlike standalone-part dependency-aware deletion. | Explain the current difference and direct provenance-preserving edits to the source part editor. Do not exercise those deletion paths in authored examples. | Open; identified by implementation review, not an assembly deletion capture. |
| GUIDE-UX-015 | History navigation | The standalone part rail requires dragging its blue handle; clicking a bare notch does not seek. The Feature Log launcher can open another sidebar rather than focus the existing one. | Teach handle dragging and use the already open Feature Log sidebar. | Open; observed during guide capture preparation. |

Capture review: the helper now waits for finite CSS animations to finish before
taking a screenshot, preventing modal captures at their transparent opening
frame. The Feature Log recipe waits for the saved indicator before opening
source-bound context actions; the successful run verifies suppression and
unsuppression as separate operations.

| ID | Workflow | Finding | Guide handling | Status |
|---|---|---|---|---|
| GUIDE-UX-016 | Repair proposal comparison | The 18-helix, 80 → 96 bp proposal evaluates, but Compare authored geometry returns HTTP 413 and shows only “Repair request failed (413)”; Fit comparison stays disabled. | Observed in the earlier capture; the advanced proposal exercise is now excluded from the designer guide. | Open; expose an actionable limit explanation and qualify supported comparison sizes. No limits were changed for the guide. |


| ID | Workflow | Finding | Guide handling | Status |
|---|---|---|---|---|
| GUIDE-UX-017 | Bend → Autoscaffold → Autostaple | Autoscaffold added 268 scaffold bases outside the earlier Bend ranges. Their straight coordinates displaced the terminal runs; scrubbing faithfully restored the defect. | New Autoscaffold commands explicitly inherit each extended scaffold root's deformation membership. Include complementary views before and after routing and after scrubbing, plus a consecutive-base continuity check. | Fixed in new recorded routing commands; legacy recipes preserve their original replay behavior. |

Multi-perspective review, November 14: inspected F3 images 18–19, F4 images
20–22, F5 images 24–25 and the returned-to-F5 images 30–31. The end-region
angle exposes the loops on both sides that the main oblique view overlaps with
the body. The caps follow the bent structure; Autostaple changes staple routing
and assigns scaffold sequence while preserving scaffold topology and coordinates.
The first alternate-view attempt clipped the part and was rejected; the accepted
recipe fits the part after each orbit and leaves a margin. These views reveal
terminal displacement and gross connection discontinuities, not atom-level
clashes or physical validity. Numeric continuity and history checks supplement
visual review; neither a nonempty feature log nor replay equality proves geometry
correctness. See the explicit review procedure in MAINTENANCE.md.


| ID | Workflow | Finding | Guide handling | Status |
|---|---|---|---|---|
| GUIDE-UX-018 | Move feature position | The native dropdown inherited light text over a white background and overflowed the small modal. | Use NADOC's shared select primitive, constrain it to the modal width, and check rendered contrast and bounds during capture. Remove advanced repair-proposal authoring from the designer lesson. | Fixed; step 37 visually reviewed after recapture. Measured contrast 16.02:1, control within modal bounds. |

Merge follow-up: recaptured against incoming master changes. Reviewed end-region
images 19, 22, 25 and 31 and the Move dialog at 37 again; the scaffold ends remain
in place and the standard dropdown retains 16.02:1 contrast. Independent saved
and reopened process audits and all browser history checks passed.
