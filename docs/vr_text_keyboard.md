# Shared VR text keyboard

All VR text fields use the QWERTY component in
`frontend/src/scene/vr_text_keyboard.js` and the matching native geometry in
`native/vr_viewer/src/text_keyboard.hpp`. Numeric-only widgets retain their
existing numeric pads. File naming and custom scaffold sequence entry are the
current hosts; a host retains its own validation, submission, cancellation and
feature-recording paths.

Create one `createVRTextKeyboard()` per editor. Publish its
`controls(input, options)` alongside the host's Done/Cancel actions and a
read-only `info-*` value row through `createVRRouting`. Use the default
`text-key-` IDs. Native routing recognizes these IDs independent of dialog title
and presents the standard large keyboard. `file-key-` IDs remain compatible.
Call `reset()` on editor teardown. No new native layout or drawing code is needed
for another input or textarea host.

Options: `maxLength`, `transform(character)` and `accepts(character)` let hosts
restrict entry. Sequence entry uppercases and allows A/C/G/T/N; it does not apply
or alter a sequence until the existing host action does so. Files retain their
120-character bound and their original Create/Save/Cancel handlers.

The 43-key layout has staggered QWERTY rows, a number row, wide Backspace, Shift,
Space and a symbol-page toggle. Keys keep the existing 134 mm local faces and
0.84 opening VR scale (70% of the former 1.2). Text inserts at the caret, replaces a selection and sends native
DOM input events. Backspace removes a selection or the preceding Unicode code
point. Disabled, read-only, detached and superseded inputs cannot be edited.
Changing target resets Shift and symbols. The desktop style evaluator uses only
local sample text and does not bind to a document field.

## Production Bevel / Slate and analog travel

The shared VR keyboard now uses option 2, Bevel / Slate, for character keys and
host actions such as Cancel and Create. Production and the desktop evaluator
share `keyboard_slate.hpp`: the same chamfered caps, shadow border, slate palette,
hover edge and lettering. Gallery-only selectors and demo actions are omitted.

Key depression follows analog trigger pressure continuously through 6 mm of local
travel (5.04 mm at the default 0.84 scale). A half squeeze produces half travel.
Text still enters only on the existing 0.88 activation threshold; release below
0.60 rearms it, and holding does not repeat. The resting cap plane remains the hit
surface so depression cannot move the target away from a shaky pointer.
Disabled keys do not depress. Tracking loss, blocked input and closing the popup
clear pressure; two controllers over one key use the larger pressure. Pending
browser acknowledgements block duplicate actions without bouncing the cap up.

## Desktop style evaluation

Open **Debug → VR Component Gallery → Text keyboard · four button styles desktop
demo**. This launcher is desktop-only, both in the API and native command parser.
Select a style, click keys to enter sample text, try Shift, symbols, Backspace,
Clear and Disable Keys. Press O for an angled view, F for front, right-drag to
orbit, scroll to zoom, S to capture, and Escape to close. Selection does not
change the production VR keyboard style.

1. Flat / Quiet: 8 mm face depth, simple border and one legend.
2. Bevel / Slate: 26 mm face depth, chamfered sides and shadow border.
3. Soft / Capsule: 50 mm face depth, rounded keycaps and broad curved edges.
4. Mechanical / Detail: 75 mm face depth, sockets, inset caps, secondary legends
   and F/J home marks.

These depths are local model dimensions; the desktop evaluator uses 0.75 scale.
All four reuse production key positions and hit boxes. Pressing visibly depresses
the face, releasing on the same key types once, and releasing off-key cancels.

Focused checks: frontend keyboard/host tests; native keyboard/routing/gallery
checks; `tools.vr_workflows.keyboard_desktop_check` for real GLFW mouse input and
screen delivery; `tools.vr_workflows.file_keyboard_check --validate` for seeded
production ray accuracy; the existing File workflow for browser-backed native
VR entry/cancellation and menu discoverability. Evidence is retained under
`.development-artifacts/vr-keyboard-studies/`. Through-lens comfort remains MV-71.

Validation record (2026-11-24): 26 focused frontend tests and 55 tour/API tests
passed. Native checks cover every key, generic-title popup routing, four style
states, shared mesh geometry, symbol glyphs, front/angled rendering and offscreen
negative captures. The actual desktop mouse check passed typing, Backspace and
disabled-key rejection for every style; all eight screen captures matched the
native window output and passed the window-edge clipping check. Review:
`.development-artifacts/vr-keyboard-studies/index.html`.

The seeded ray test used 2,150 uncorrected samples per profile: steady fast and
steady deliberate 100%, variable fast 99.907%, variable deliberate 99.814%.
These exceed the existing 95% threshold and are synthetic hit tests, not measured
human accuracy. The 25-stage initial browser/native workflow also passed all
four profiles; the final expanded workflow additionally exercises symbols and
passed all four profiles with 33 stereo/desktop review stages and four cancelled
New Part attempts. Its 147 reaches include 29 retry reaches; this is completed
workflow validation, not uncorrected first-attempt accuracy. The owned viewer
closed normally and its workspace/credentials were removed, with no saved
structures. Evidence: `live-symbols-02/` under the review directory above.
The shared sidebar regression checked 861 controls with zero layout failures.
The first live run timed out before its initial frame capture; its cleanup record
is retained. Desktop attempts are retained, including the missing external mouse
utility (replaced with X11/XTest) and the initial clipped oblique framing.
An earlier expanded run (`live-final/`) lost its viewer connection during the
second profile; the native process logged a normal exit with no recorded reason.
That failed run and runtime tail are retained alongside the successful retry.

Bevel / Slate validation (2026-11-24): frozen approved key meshes match production
vertex positions and colors for idle, hover, selected, disabled, half and full
press states. Native runtime checks cover two controllers, tracking loss, blocked
input, closure and pending acknowledgements. Front/angled captures at 0/25/50/75/
100% pressure and offscreen negatives pass. Seeded uncorrected ray results remain
100% for steady profiles, 99.953% variable fast and 99.814% variable deliberate
(2,150 samples each). Review: `.development-artifacts/vr-keyboard-slate/index.html`.

Retained live attempts: `live-01` stopped at SteamVR server-pipe readiness;
`live-02` exposed an outdated lower-half sampling region for the new top-aligned
readout. The sampled region was corrected without changing the visibility
threshold. `live-03` passed the first profile's pressure/Cancel checks but stopped
on a 184 ms motion-playback delay above the unchanged 150 ms limit. These runs
remain failed evidence, with their cleanup records retained.
The `live-04` run exposed a capture immediately after a symbol-page action,
while browser acknowledgement still marked controls unavailable. The File demo
now waits for acknowledged letter-key state before that capture; activation and
visibility thresholds are unchanged.
The `live-05` process had already loaded an uppercase label expectation before
its lowercase bridge-label correction landed; it timed out at that wait. A fresh
process is required to validate the corrected harness.

The final `live-06` launch failed before NADOC opened: the compositor logged
`VRInitError_Init_HmdNotFound`, leaving the final-output recorder unavailable.
The full four-profile live workflow is therefore **not validated** for this
change. The first profile's live pressure check passed in `live-03`, `live-04`
and `live-05`: 0/25/50/75/85/100% depression, 70% hold without repeat, release,
and half-pressed Cancel without closing. No partial trigger entered text.
Native tests and all four offline ray profiles pass; through-lens feel and the
remaining live profiles remain open under MV-71. All six attempts removed their
temporary workspace and credentials and saved no structures.

## Border manipulation and smaller default (2026-11-24)

The keyboard opens at scale 0.84, exactly 70% of its former linear size. Keys
retain the shared local layout. A continuous border with corner grips marks the
actual manipulation target: hold a trigger on the border to move; double-trigger
and hold to resize, or use both controllers. Near the panel, grip the border to
move and use both grips to resize. Border ownership blocks key activation.

The native popup now participates in the established border handlers. Resizing
persists across typing and browser acknowledgements; reopening starts at 0.84.
The File demo includes trigger movement/resize, size persistence while typing,
and physical grip movement before cancellation. Gallery-only controls remain
absent. Existing large-scale accuracy results above are historical, not evidence
for the new opening size.

At the new scale, 2,150 uncorrected samples per profile yield: steady fast and
steady deliberate 100%, variable fast 97.116%, variable deliberate 96.419%. All pass
the unchanged 95% gate. Native input tests cover trigger/grip move and resize;
render checks cover the border and proportional key travel. The standalone render
camera was moved closer to retain the previous framing/visibility threshold;
that framing is not a physical-headset legibility result. Evidence:
`.development-artifacts/vr-keyboard-border/index.html`.

The reduced-size live demo exposed sparse sampling of a lone glyph in its wide
readout. The checker now samples at pixel density and counts distinct pixels;
the visibility threshold remains unchanged. The initial border sweep acquired
successfully but was too small at the oblique ray angle to satisfy the 25 mm movement
check; the next run uses a larger intended sweep with the same motion profiles.
Failed attempts are retained under `vr-keyboard-border/live-01` and `live-02`.

The `live-03` attempt completed the first profile's gestures and cancellation,
then captured the second profile's post-resize Shift check before acknowledgement.
That capture now uses the existing settled-state wait instead of a fixed frame
count. The unsuccessful run remains retained.

`live-04` completed both steady profiles, then variable-fast border acquisition
failed from the opposite-edge pose inherited from typing. The next run explicitly
reaches a 0.6 m border approach with the same noisy trajectory. This is a separate
observation condition; the original failed reach is retained, and no hit target
or acceptance threshold changed.

Final validation: `live-05` passed all four motion profiles with 57 stereo and
actual desktop review stages and four cancelled New Part attempts. Pressure,
trigger move/resize, physical grip movement, and size persistence during typing
passed for every profile; native checks additionally cover two-grip resizing.
Border acquisition uses the explicitly reached 0.6 m diagnostic approach above.
This is completed workflow validation with correction/retry reaches, not measured
human first-attempt accuracy. The owned viewer closed normally; temporary workspace
and credentials were removed, with no saved structures. Through-lens comfort
remains MV-71. Ten new export/connectivity checks and three existing export
regressions pass; actual native renders verify all four roots in both models.
