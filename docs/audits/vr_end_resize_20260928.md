# VR end resize — 2026-09-28

Implemented trigger acquisition of selected end arrows, axis-projected whole-bp
extension/shortening, desktop limits, release-to-save, authoritative scene refresh,
and one Undo step per release. Either controller can acquire; scene grips, lost
tracking/focus, changed targets and Expanded transitions cancel an active drag.
Desktop and native share end-role choice, terminal-run limits and collision limits.

Discoverable workflow: Debug → VR Tours & Tests → Tools · Authoring →
**Resize selected ends**. See [interaction details](../vr_end_resize.md).

## Validation

- Native viewer rebuilt with the system compiler/linker. Focused native tests:
  4/4 pass (end resize, interaction, view-volume interaction, Move panel).
- Frontend end-arrow/session tests: 46/46 pass, including signed deltas, collision
  limits, stale/duplicate requests and repeated journal-event delivery.
- Backend resize/protocol/tour suites: 74/74 pass; two added tour-launch cases also
  pass. Backend validates view-space handles and confines publication to the
  viewer's document.
- Debug menu browser smoke test passed: both launchers are visible and validation
  submits the named end-resize workflow; launcher error feedback remains visible.
- Final physical OpenXR runtime with synthetic controller input: **4/4 profiles**
  (`steady_fast`, `steady_deliberate`, `variable_fast`, `variable_deliberate`).
  Each extended +12 bp, shortened −6 bp, added one minor operation per release,
  refreshed the native scene, and independently undid both edits on desktop.
- Projected cyan/yellow/orange arrow regions passed pixel checks in both submitted
  eyes and the actual mirror buffer. Offscreen targets fail the same check.
  Representative final frames were inspected visually.

Final evidence: `.development-artifacts/vr-end-resize/42939ae168/result.json`;
per-profile `physical/` and `trim/` folders retain reaches, capture provenance,
stereo/mirror PNGs, pixel checks and final state. Test workspaces and viewers were
removed on exit.

## Retained iterations and limits

`a605897442` passed extension/Undo state checks but captures were blank because
initial geometry was outside the tracked view. `f22d784d9c` added ordinary grip
framing outside measured motion and passed extension pixels for all profiles.
`44d80109e6` exposed an incorrect test assumption: consecutive desktop minor edits
share a Fine Routing parent, with one child and Undo step per release.
`fbc2068688` caught only six cyan mirror pixels after extension (eight required).
The production arrow gained a spatial shaft and four head edges to remain visible
after downsampling. Thresholds and human-motion profiles were unchanged in the
final passing run.

Natural pose received the full live runtime campaign; Expanded offset/projection
and transition cancellation have software coverage. Multi-end limit logic reuses
the desktop implementation. Physical human comfort/through-lens legibility and a
broader live multi-end/Expanded campaign remain separate checks.
