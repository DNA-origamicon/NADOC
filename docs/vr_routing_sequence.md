# Routing and sequencing in VR

The right **Tools** sidebar exposes the same active Routing and Sequencing actions
as the desktop: Autoscaffold, Full Autostaple, Route for Polymerization, Add
Loops/Skips, Clear All Loop/Skips, Assign Scaffold Sequence, Assign Staple
Sequences, Generate Overhangs, and Hairpin/Dimer Checker. Undo and Redo are also
available there and on completed-operation dialogs.

Point and trigger to activate an action. Autoscaffold offers Seamed and Seamless;
scaffold assignment offers M13mp18, p7560, p8064 and a custom-sequence editor.
The custom editor has A/C/G/T/N, Backspace, Clear and Done controls. It preserves
text entered on the desktop, updates the ordinary length/validation warnings,
and uses the same custom-sequence override rule as the desktop.

Dialogs open on a separate tablet just in front of the current menu. Back/Cancel
and guidance stay at the top; longer choices and messages scroll using the normal
pointer/trackpad controls. Closing a dialog restores access to the original menu
with its position and scroll unchanged. The controller menu button also returns
from the current dialog. Dialogs consume input so model selection, manipulation,
and underlying menu actions cannot fire through them.

Desktop handlers own validation, progress, document changes, and Undo/Redo.
Hairpin/Dimer Checker is an on/off analysis toggle, not a document mutation.
Operation messages remain in VR until dismissed. Background autosave does not
block these controls. Sequenced events and snapshot versions reject duplicated,
stale, disabled, and background-dialog requests. The transport is local-only and
bound to the active VR document.

Implementation: `vr_routing.js`, `/api/vr/routing`, `routing_panel.hpp`, and the
normal native sidebar input/rendering pipeline. The generated Tools catalog must
be refreshed with `node frontend/scripts/generate-vr-sidebar-catalog.mjs` if its
entries change.

Validation entry points:

- Frontend `src/scene/vr_routing.test.js` and `src/scene/vr_session.test.js`.
- Backend `tests/test_vr_routing.py`.
- Native `nadoc-vr-routing-panel-test` and the standard menu layout audit.
- Playwright `e2e/vr_routing.spec.js`: real desktop mutations through VR controls,
  confirmation cancellation, sequence entry, toggle state, and Undo/Redo.
- Opt-in `e2e/vr_routing_physical.spec.js` with `NADOC_PHYSICAL_VR_TEST=1`:
  real native controller events and submitted stereo menu pixels. Set
  `NADOC_VR_PROFILE` to a human-motion preset and `NADOC_VR_ROUTING_EVIDENCE` to a
  retained development-artifact directory. The probe derives an eye-facing wrist
  pose from the runtime panel axes before measured interaction.

Validated October 6, 2026: all 74 native tests, focused frontend/backend tests,
production builds, and the real-document browser workflow passed. Native routing,
Undo, popup navigation and custom input passed all four motion presets, with 12
stereo captures per preset and offscreen negative checks. The final review pose
places the menu 0.60 m ahead of the tracked eye. Evidence and earlier failed
attempts are retained under `.development-artifacts/vr-routing-validation-20261006/report.json`.
This establishes controller operation and submitted-eye rendering, not a manual
through-lens comfort review.
