# QR meeting entry and mobile tracking prototype

Open **File → Sharing**, enable a link, then **Print large tracking QR** for
phone-camera testing. Print at **100% / actual size** on A4 or US Letter, measure
the 100 mm ruler, and mount the sheet flat and stationary. The QR square including
its white quiet zone is 150 mm. Scan it with the phone’s normal camera to open the
invitation, enter a guest name, then open **Phone tracking · prototype → Start
camera tracking** and allow camera access. Use the HTTPS public invitation on phones.

The phone shows its camera feed, highlights the matching QR and estimates its
position relative to the paper: right, up, and out toward the viewer, in cm.
The large printed QR configures the 150 mm size automatically. The combined
**Print meeting target** sheet retains a 150 mm AprilTag `tag36h11` ID 0 and a
40 mm guest QR; its phone default is 40 mm. Enlarged or reduced prints require
entering the measured QR width, including the white border. A screen QR has no
fixed physical size: measure and enter it if using a screen for a bench test.

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

## Tracking limits

This is a local mobile tracking diagnostic, not yet a registered VR portal or
an attendee-position feed to the Vive. Frames and poses stay in the browser.
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
- `mobile_qr_tracking.js`: opt-in browser camera lifecycle, decoding and status.
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
