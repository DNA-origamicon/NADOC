# Controller dimensions — 2026-09-27

Native viewer measurements now use normalized model-local endpoints. The focused
right panel hides both desktop-mapped sidebars and restores their previous open
states, tabs and offsets on either menu-button exit or main Dimensions-button
exit. New/exit freezes the previous line; model grips also pin live endpoints.
Each valid controller trigger independently pins/recalls its endpoint unless UI
input owns that trigger. Model presentation changes preserve nanometer lengths.

The list uses eye/eye-off and X controls, with pointer and trackpad activation.
The selected row has a leading arrow. Dimensions/New/Clear remain fixed above
five scrolling entries, and new lines automatically scroll into view. The panel
frame contracts for short lists and preserves border movement/resizing. Session
measurements remain local to the native viewer, without desktop document writes.

Evidence is retained under `.development-artifacts/vr-dimensions/`:

- `steady-fast`: initial behavior checks passed; pixel check exposed labels
  above the sampled button interior. Labels were centered.
- `steady-fast-centered`: line visibility check failed because test controller
  positions used world -Z instead of the actual tracked viewing direction.
- `steady-fast-framed`: observation positions derived from the native panel's
  actual right/up vectors, preserving physical head tracking. Native stereo line,
  control pixels and actual desktop matching passed.
- `validated`: steady profiles passed; variable-fast exposed new entries created
  beyond the visible list. Fixed sticky commands and automatic entry scrolling.

The fixture uses an empty authoring scene and the actual model presentation
transform. Tests prove measurement attachment to that transform, not new molecular
geometry or through-lens headset comfort. No runtime/display configuration or
controller motion profile has been changed. Failed runs are retained.
- `final`: native panel fix and small pointer-icon checks passed in both steady
  profiles. The longer-list tour then requested an older off-page entry without
  scrolling; the workflow was corrected to use pad scrollbar navigation before
  accessing retained entries. This did not require relaxing hit targets or profiles.

Native CTest passes 39/39, including pin/recall, invalid tracking, model-coordinate
invariance, list actions, dynamic frame bounds, five-entry pagination and restoration.
The catalog's DOM hierarchy generator test also passes. The main viewer delegates
measurement drawing and input ownership to the feature modules.

Final validation: `final-scrolled/result.json` passes all four unchanged presets
(steady_fast, steady_deliberate, variable_fast, variable_deliberate), including
pointer eye/delete icons and pad selection, independent endpoint pin/recall,
unchanged nm under model movement/resizing, retained entries, sticky commands,
scrollbar navigation and both exit routes. Menu triggers are explicitly checked
not to pin new endpoints. All 92 stereo control pixel checks pass. The live cyan
line is checked at independently projected positions in both eyes, with a blank
mask negative control. The actual X11 desktop check passes at 100% feature-pixel
agreement (22,835 pixels; required 95%, unchanged tolerance). Owned viewer and
socket are removed; SteamVR remains available. Through-lens comfort is not claimed.

Live review command:

```sh
just vr-menu-tour --dimension-checks --validate
```

## Tour clearance correction

User review found that the earlier tour mixed measurement placement with menu
interaction. `dimensions_check.py` now derives one measurement workspace beside
the actual panel frame. It resets measurements between profiles and parks/pins
new lines in that workspace before resuming pointer or pad menu tests. Model
movement is vertical, and resizing stays within the same clear workspace.

Every endpoint trigger requires pointer mode, native `dimension` input ownership,
no controller ray intersection with the full panel, and at least 10 cm clearance
for controller tips and selected endpoints. Every sampled measurement movement
also checks tip/ray clearance and ownership. New focused negative tests reject
panel collisions, near-edge tips, menu focus/ownership, angled ray intersections,
and pinned lines moved into the menu.

Verification: four focused tests pass. Initial steady run passes stereo and actual
desktop checks (100% feature agreement). `clear-workspace-validated/result.json`
passes all four unchanged controller profiles; 480 measured motion samples have
at least 0.16939 m tip clearance. The line is visibly beside the menu in both eye
captures, with the same 95% line-pixel threshold. Evidence lives under
`.development-artifacts/vr-dimensions/clear-workspace-{steady,validated}/`.

The final desktop-only check of the all-profile run failed (2.302% matching pixels,
95% required); the command correctly returned nonzero. Its native interaction and
stereo checks passed. The failed desktop crop was not retained, and the cause of
that separate display mismatch is not established. Both owned viewers and sockets
were cleaned up; no thresholds, controller profiles, or production VR behavior
were changed by this tour correction.
