# Assembly Visualization audit — 2026-09-27

Scope: the Visualization tab, starting with the reported multi-view, multi-overlay,
and spatial view-volume failures in `workspace/BigO-poly.nass` (30 copies of BigO).
Assembly sharing is recorded separately in `assembly_sharing_20260927.md`.

## Findings and changes

| Capability | Finding | Resolution |
| --- | --- | --- |
| Comparison representation/coloring | Controls invoked the part-only representation setter; copying an assembly scene also retained callbacks into live GPU textures. | Build independent assembly renderer resources per pane/layer, using the same source geometry and representation primitives as the native renderer. |
| Framing and overlay separation | Bounds ignored instance placement; active-part geometry could drive assembly framing. | Use the assembly renderer's world bounds, with proper instanced bounds for ordinary meshes. |
| Camera clipping / View Actions | Native clipping could overwrite comparison frusta; hidden native geometry also removed the bounds needed for volume-scene framing. Unhide All wrote part visibility. | Comparison renderers own their clipping; volume scenes supply logical assembly bounds for fit/reset. Unhide All reveals assembly instances and groups through assembly APIs. |
| Native display restoration | Comparison controls could write the part representation while leaving assembly copies unchanged. | Preserve authored instance representations and global coloring when opening/closing assembly comparisons. |
| Assembly changes during comparisons | Panes did not refresh for assembly state changes. | Serialize refreshes; reject stale asynchronous scenes and dispose owned resources. |
| Volume ownership/persistence | Volumes read/wrote `currentDesign` even in assembly mode; `.nass` lacked the field. | Assembly-owned `view_volumes`, validated by the existing `ViewVolume` model, with lightweight metadata GET/PUT and normal assembly serialization. |
| Spatial membership | Part helix/base keys collided across repeated instances; positions lacked assembly transforms. | Namespaced instance/column keys; transform local backbone and skipped-column samples before applying the existing box/hex/rotation membership rules. |
| Volume representations | The part display controller explicitly cleared layers in assembly mode. | Use the same CG/atom/surface layer renderer behind per-instance host adapters. Surface regions resolve the instance's source and reuse the part surface pipeline. Atomistic, protein and surface feeds now apply the same instance cluster overrides as CG geometry. |
| Scale | Expanding every BigO copy into separate primitive renderers is unnecessary. | Keep unaffected copies in shared GPU instancing; expand only copies intersecting enabled volumes. Serialize display builds and discard stale results. Hulls use the same projected volume apertures, including overhang markers. |
| Controls | Move, resize, rotate, naming, representation, coloring, opacity, overlap, outline and enabled states were tied to part ownership. | Reuse the existing controller and controls with active-document ownership. Enabled volumes and visible outlines also carry into multi-view/overlay. Deleted columns are included in base-layer masks, avoiding isolated cylinder fragments in heavy windows. No new molecular geometry or topology algorithms. |

Metadata edits follow the existing part-volume convention: display revisions, without
adding topology feature-history entries. Explicit instance/source geometry remains
read-only throughout visualization.

## Validation

- Final `just test-frontend`: 7,092 passed, 1 skipped (548 test files).
- Production build: passed.
- Focused assembly API tests: 77 passed.
- Focused volume API tests: 4 passed, including part/assembly validation parity,
  `.nass` round-trip, part isolation, and instance-source surface routing.
- `just test-smart` decision: `FAST  (fast suite only)`; 9,286 passed, 15 skipped,
  8 failed: seven require absent photoproduct review evidence under
  `/media/jojo/Archive/NADOC_archive/photoproduct_evidence/`; the eighth is an
  unrelated CPD atom-position snapshot mismatch (`test_cpd_preview`). No evidence,
  geometry locks, or snapshot goldens were changed.

Selector notice (verbatim):

```
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
```

The fast-suite timing guard flagged six tests while browser and frontend verification
were competing for CPU. Following `.claude/skills/triage-slow-tests/SKILL.md`, inspected
and reran only the reported software checks in isolation: loop-copy mapping 0.99 s,
unwrap adjacency 0.37 s, electrode configuration writer 0.68 s, precise crossover
spec 0.55 s, scaffold/crossover spec comparison 0.53 s, and deterministic protein
packing 4.02 s. All passed below the 5 s limit; no test markers or guard budgets changed.
These checks generate software fixtures, not physical simulations.

Browser verification completed:

- `assembly_visualization.spec.js`: BigO's 30-instance multi-view/overlay/volume
  lifecycle passed (4.4 min under software WebGL), with no console errors or HTTP
  failures. Authored instance representations remained unchanged.
- Small assembly: all 11 comparison representations, atomistic/surface volume
  layers, volume carry-through into overlays, and `.nass` export/reimport passed.
- Existing part-volume regression: box/hex, overlapping layers, move/resize/rotate,
  enable/outline controls, camera interaction and persistence passed. Updated its
  click targets to use header text, row padding and canvas-relative coordinates
  rather than fields or sidebars in the current stacked-panel layout.
- Inspected browser-rendered comparison and volume scenes during the tests.

## Artifact ownership

Browser tests import renamed `__e2e__` assembly/part copies. The repository's global
teardown removes their saved files and project history; session-cache persistence is
disabled for the isolated test backend. Browser traces/screenshots are removed by the
cleanup reporter. The original BigO assembly and source part are read-only fixtures.

Final cleanup verified: no `__e2e__` workspace files or project-history paths remain,
and Playwright output/report directories were removed by teardown. SHA-256 checks
confirmed both original BigO files were unchanged.
