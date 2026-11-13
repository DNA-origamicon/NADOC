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
