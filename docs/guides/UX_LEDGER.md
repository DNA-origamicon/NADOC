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
| GUIDE-UX-004 | Extrude: deformed continuation on square lattice | Source review: `backend/core/lattice.py::make_bundle_deformed_continuation` uses `honeycomb_position` and honeycomb phase/direction conventions without a square branch; `BundleDeformedContinuationRequest` does not carry strand-filter/ligation inputs. A recorded operation alone would not establish correct square placement. | Demonstrate the deformed entry point and Cancel; do not publish a deformed extrusion from the square example. | Open. Implement and review square-aware continuation and option semantics separately, then verify source-end attachment, lattice identity, preview/commit agreement and independent replay before completing guide coverage. |

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
