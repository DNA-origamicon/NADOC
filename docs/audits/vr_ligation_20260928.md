# VR radial Ligate — 2026-09-28

The radius wheel now contains Ligate, Nick, Undo and Redo. Ligate accepts trigger
pickup of either terminal polarity, displays a stretched bond, snaps to an
opposite-polarity end on another strand, and saves one forced ligation on release.
Nick, Undo and Redo are gray placeholders in this slice. Existing authoring tools
remain available through their sidebars. See [interaction details](../vr_ligation.md).

## Validation

- System-toolchain native viewer build succeeded; focused native tests: **5/5**.
- Frontend ligation, shared crossover rules, session and end-arrow tests: **60/60**.
- Backend ligation, VR routes and tour suites: **76/76**.
- Browser Debug menu smoke test passed, including discovery, validation launch
  request and launcher error feedback.
- Final physical OpenXR runtime campaign with synthetic controllers: **4/4**
  profiles (`steady_fast`, `steady_deliberate`, `variable_fast`,
  `variable_deliberate`). Each physically selects wheel sectors, verifies inactive
  sectors, rejects an incompatible release, and creates bonds from both 3′ and 5′
  pickup orders. Each successful release adds exactly one forced ligation and one
  minor-operation child, merges two strands, refreshes native geometry, and is
  undone to the exact original strands and forced-ligation list on desktop.
- Cyan stretched and green compatible preview segments passed independent
  projected pixel checks in both submitted eyes and the native mirror buffer.
  Offscreen negative controls failed as required. Saved-bond semantic ownership
  resolves to the expected endpoint pair and has visible pixels in both eyes.
  Representative wheel, preview and committed mirror frames were visually inspected.
- Stale catalog, duplicate journal delivery, invalid terminals and failed requests
  have focused software coverage; they are not additional live campaign claims.

Final evidence: `.development-artifacts/vr-ligation/69c3958ea7/result.json`.
Per-profile `end/<profile>/.../from-3/` and `from-5/` retain reaches, capture
provenance, stereo/mirror PNGs and pixel reports. Temporary workspaces and viewers
were removed on exit. Reproduce via Debug → VR Tours & Tests → Tools · Authoring →
**Ligate ends with the radius wheel**, or:

```sh
uv run python -m tools.vr_workflows.ligation_tour --validate
```

## Retained iterations and limits

Initial campaign `d1843f0fe6` passed three profiles but missed a source pickup in
`variable_deliberate`. The probe now permits at most three ordinary reaches when
runtime acquisition feedback remains absent; every attempt is retained. The final
campaign needed one additional reach in `variable_deliberate/from-3`; all other
pickups completed without retries. Motion profiles, selection radius and pixel
thresholds were unchanged. Ordinary grip framing puts the fixture in the actual
tracked view before measured reaches. The production preview follows the same
direct segment as the native saved bond, with three adjacent strokes for mirror
visibility. Input-lease expiry cancels an active drag.

This establishes runtime input, mutation and rendered visibility on the small
natural-pose fixture. It does not establish physical human comfort or through-lens
legibility, nor a broad live campaign for Expanded, occluded ends or large designs.
The mirror evidence is its actual render buffer, not an operating-system desktop
window capture. Nick and radial Undo/Redo remain future work; desktop Undo is
verified here.
