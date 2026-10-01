# QR meeting entry and mobile tracking prototype

Guests scan the invitation QR and enter their name. Guest entry no longer mounts
**Phone tracking · prototype**, requests camera access, or exposes camera settings.
The camera diagnostic module remains covered by its unit tests but is not part of
the guest interface. Printed QR invitations continue to work normally.

On touch devices, a bordered rotation button in the header replaces the previous
rotation prompt. A solid rectangle shows the current viewport orientation, an arrow points
to the opposite orientation in a fainter outline, and the icon updates on rotation.
It appears after sign-in. Tapping requests fullscreen when needed, then locks to
the opposite orientation. Unsupported requests show an inline Auto-rotate hint.
Browser requirements: [ScreenOrientation.lock](https://developer.mozilla.org/en-US/docs/Web/API/ScreenOrientation/lock).

## Authentication

A new host generates a separate random 256-bit QR invitation for each room.
Scanning it substitutes for the meeting password and grants only guest access;
it never includes a password or presenter credential. Ordinary copied guest links
still require the generated password on public hosts. Name validation, participant
limits, origin checks, session cookies and room expiry/revocation remain enforced.
Anyone with a photograph or copy of the QR can join until the presentation ends.
This is a bearer meeting pass, not cryptographic proof of physical presence.
Starting a new presentation requires a new printed QR. Existing running hosts
must be upgraded through the normal sharing flow; older hosts retain password
prompts and do not expose the large-tracking print button.

## Retained diagnostic module (not mounted in guest UI)

This is a local mobile tracking diagnostic, not yet a registered VR portal or
an attendee-position feed to the Vive. Frames and poses stay in the browser.
Native Vive calibration is a separate [Share-tab workflow](vr_qr_calibration.md);
it does not yet connect these mobile poses to VR.
The QR must remain visible; there is no inertial/world tracking after it leaves
the image. Loss, mismatched invitation and stalled video clear the current position.
Stop, hiding the page, closing the panel, leaving the page or ending the meeting
releases the camera. Permission requests completing after Stop are also released.

The decoder processes frames up to 720 px on their longest side approximately
6.7 times per second. Four decoded corners define a planar homography, decomposed
using an approximate pinhole camera. Metric scale comes from measured print size;
the initial vertical camera angle is assumed to be 60 degrees and is adjustable.
No device-specific focal calibration or lens-distortion correction is available
in this pass. Pose rejection uses size, orthogonality, depth and reprojection
checks. Estimates can be noisy or biased, particularly at oblique angles. They
must not be treated as collision-avoidance measurements.

For initial meetings use one flat target visible to everyone. A cube requires
identified faces and known rigid transforms; it can follow after flat-target
validation. Repeated identical target sheets would be ambiguous spatial anchors.

## Implementation and validation

- `meeting_target*.js`: local SVG QR printing, previews and invitation lifecycle.
- `mobile_qr_tracking.js`: retained camera diagnostic module and unit tests; not mounted during guest entry.
- `qr_pose.js`: independently tested planar camera-pose math.
- `prepared_view_host.mjs`: separate guest QR credential and password bypass only
  after server-side validation of that credential.

Decoder API: [jsQR](https://github.com/cozmo/jsQR). Browser camera requirements:
[getUserMedia](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia).
The combined target’s static marker is the official
[AprilRobotics ID-0 image](https://github.com/AprilRobotics/apriltag-imgs/blob/master/tag36h11/tag36_11_00000.png).

Automated checks cover synthetic known camera poses, permission/disposal races,
credential separation, password preservation, room expiry, printed QR decoding
and dimensions, and synthetic-video tracking/loss/reacquisition in the production
browser viewer. Physical print scale, iOS/Android cameras, acquisition distance,
camera calibration, motion jitter, headset alignment and VR attendee markers
remain on-site validation work. No physical phone/headset result is claimed.

### Guest UI simplification — 2026-09-30

The rotation button sits alongside the header controls, with the same border and
a 44 px touch target. On narrow phones the title occupies its own row, keeping
the buttons visible and outside the canvas. Verified both orientations in the running
production viewer, QR name-only entry without a camera request, and touch orbit,
pinch, pan, and recentering. Validation: 7,308 frontend tests passed (one skipped),
seven browser checks, 23 smoke tests, build and lint passed. Screenshots and logs:
`.development-artifacts/mobile-orientation-20260930/`. Test artifacts were cleaned.
`main.js` LOC delta: 0.

Header-button follow-up: 7,309 frontend tests passed (one skipped). The mobile
browser test verifies header containment, the matching border, a 44 px target,
and touch-triggered fullscreen/orientation calls in both directions. Platform
orientation APIs are mocked in that browser test; physical Android rotation is
not verified here. Production screenshots in both orientations were inspected:
`.development-artifacts/mobile-rotate-button-20260930/`. Main.js LOC delta: 0.
