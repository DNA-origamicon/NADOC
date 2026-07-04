---
name: feedback_display_toggle_visual_verify
description: Verifying a display/viz toggle by asserting panel STATUS TEXT is a false pass — you must screenshot the actual render; multi-doc e2e needs a doc-pinned load or it renders nothing.
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 2a3a0aa4-a713-4edd-97e6-0e0a03d7fb9b
---

A CanDo deform-toggle "verified in app" was a **false pass**: the e2e asserted only the
panel's "Showing: model deformed" status text (and `deformActive()`), never the actual 3D
render. The toggle shipped with a real visual bug (ssDNA scaffold ends + loop bases stranded
at native positions → stretched fanning lines) that the status-text check sailed past. The
user caught it with a screenshot.

**Why:** panel state / status text updating ≠ the geometry rendered correctly. This is the
CLAUDE.md "tests don't validate UI correctness" rule, but the subtle version — a passing
*app-driven* assertion can still be blind if it checks a DOM label instead of the pixels.

**How to apply:** to verify a display/visualization toggle (CanDo/mrDNA/oxDNA deform, reps,
overlays), **capture a screenshot of the canvas and actually look at it** (Read the PNG),
OFF vs ON at the same camera. Assert on the render, not a status string.

Two e2e gotchas that made this hard (both cost multiple runs):
- **Multi-doc "No active design":** the smoke Playwright config starts its OWN backend, and a
  plain `goto('/')` gives the page a fresh empty doc — a design loaded via `POST /design/load`
  on the default doc never appears (`getBackboneBeadScreenPositions` → 0, canvas blank). Load
  it INTO the page's doc: `goto('/?doc=X')`, `POST /design/load` with header `X-NADOC-Doc: X`,
  then broadcast `design-changed {docId:X}` on `BroadcastChannel('nadoc-design')`, then wait for
  `backboneSpheres.count > 0`. Mirror `scene_harness.loadScaffoldedPart`.
- **Panel job-filter:** an API-loaded design has no UI workspace path, so the jobs panel hides
  its job — check `#cando-jobs-show-all` before expecting the row.

For a real fixture the FEM solver handles, use `workspace/6hb_curved.nadoc` (tiny synthetic
scaffolded parts have no duplex core → `predict_shape` now raises a clear "needs a duplex core
of at least 2 base pairs" ValueError, surfaced as the job's "Failed: …"). See [[project_cando_fem]].
