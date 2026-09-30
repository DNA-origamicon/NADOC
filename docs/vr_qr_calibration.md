# Vive QR calibration and printable cube

In the VR **Share** tab, choose **Calibrate QR code**. A cyan edge-filtered mono
camera panel appears in the headset. Aim at the complete, well-lit target and hold
the headset and target still. A green outline marks a decoded target. After at
least 12 consistent observations over 0.8 seconds, the target is registered into
VR room coordinates and the camera stops. A small RGB axis marker remains at the
registered origin. The same button cancels acquisition; unsuccessful acquisition
times out after 90 seconds. Calibration does not require an active presentation.

For a flat target, use **Presentation → Sharing → Print large tracking QR**, printed at
100% actual size. The QR's entire square including the white quiet zone is 150 mm.
Small meeting-sheet QR codes default to 40 mm. Do not resize a print without
updating its encoded `qrmm` width. Arbitrary QR codes are rejected. Any NADOC
meeting target can establish a physical anchor; calibration does not join its
meeting or authenticate a guest. A target's print geometry remains meaningful
after its invitation expires, although scan-to-join will then fail.

The currently loaded scene's **source origin** moves to the flat QR center, or
the cube center for a cube face. Existing scene orientation and scale remain
unchanged. This changes only the VR presentation transform, not saved molecular
coordinates or topology. An empty scene can still register an anchor. Loading
another scene does not automatically snap it: calibrate again. Gripping/moving
the model afterward is allowed. Recalibrate after moving the physical target,
restarting VR or changing SteamVR room calibration.

## Learn a different cube plate arrangement

The conventional **Calibrate QR code** path assumes the named plate arrangement
unless a learned cube mapping exists. To learn a permutation or quarter-turn
rotation of the five plates, center one plate on each of the five closed faces,
leave the support opening uncovered, and choose **VR → Calibrate cube** in the
left controller sidebar. Keep the cube fixed on its stand and move around it;
hold your head still while each face is acquired. Do not rotate the cube in your
hand between scans. The first accepted face defines an arbitrary cube coordinate
orientation; all five recover the same physical center.

Each face requires 12 consistent observations over at least 0.8 seconds. The
room-space cube overlay updates live: red means more scanning is needed, green
means the face has passed acquisition. An unfolded map in the smaller camera
panel shows hidden faces too, labeled with their learned QR IDs. After all five
faces pass, the unmarked support face becomes gray, the mapping is saved, and
the camera stops. The world-space colored cube remains for review; it is a
calibration snapshot, not continuous tracking after the camera stops. Starting
another QR operation replaces the preview. The same button cancels scanning.
Incomplete sessions time out after five minutes and do not overwrite the last
complete mapping.

Face centers must agree within 12 mm and normals within 8 degrees of a cube
axis. A detected cube movement or repeated face rotation resets progress; wrong
sizes and duplicate face locations are rejected. These checks cannot detect
every symmetric rotation before a known face is revisited: keeping the physical
cube fixed throughout acquisition is required.

The mapping is saved locally in
`$XDG_DATA_HOME/nadoc/qr-cube-calibration.json` (by default
`~/.local/share/nadoc/qr-cube-calibration.json`). Only relative plate transforms
are saved, not room poses. **Share → Calibrate QR code** then uses the learned
arrangement to place the scene from any of the five faces, including after the
cube is moved or the viewer restarted. Mapping alone does not move the scene.
Recalibrate the arrangement after swapping plates. One physical cube is supported
at a time because the printed IDs are shared between print kits. With no saved
mapping, registration continues to use the conventional named arrangement.

## Camera implementation and requirements

This first implementation supports the original Linux HTC Vive. It uses the
proven V4L2 USB feed, the headset-serial-specific SteamVR `tracked_camera`
intrinsics, and OpenVR's camera-to-head transform. The supported camera model is
`DISTORT_FTHETA` with zero polynomial coefficients, as reported by this headset.
OpenCV fisheye remapping corrects the equidistant image before decoding. Other
lens models fail explicitly instead of applying an assumed focal length.

The decoder processes original grayscale/color pixels. Canny filtering affects
only the displayed panel. Square pose estimation rejects excessive reprojection
error and impossible depth/back-facing solutions. It combines the detected
camera pose with SteamVR STANDING tracking and then the native viewer's located
OpenXR STAGE-to-LOCAL transform. No OpenVR/OpenXR origin equivalence is assumed.
The stationary gate bounds observed head motion to 6 mm / 1.5 degrees and marker
variation to 15 mm / 3 degrees. Loss or a changed QR resets the gate.

USB frame exposure time is not synchronized to headset tracking. Holding still
reduces the resulting error; this is not a motion-calibrated measurement system.
The camera panel is a mono preview, not depth-correct full-world passthrough or
collision avoidance. Physical registration accuracy and through-lens comfort
remain pending on-site testing. No new mobile-to-VR pose publishing is included.

Capture and decoding run in a separate process, with one OpenCV compute thread.
The stream is drained continuously; decoding and preview publication are capped
at approximately 10 Hz.
The native renderer polls bounded atomic frames, uploads the preview and applies
only a stable accepted pose. Cancel/exit releases the camera and removes private
temporary files. No images, invitations or calibration poses are sent online.
Camera errors are shown in Share; helper-start errors also reach the viewer log.

Install/cache the isolated camera dependencies once (this does not change the
research Python environment):

```sh
uv run --no-project --python 3.12 --with openvr==2.12.1401 --with opencv-python-headless==4.12.0.88 python -c "import cv2, openvr"
```

The VR button uses that environment offline. The helper is launched from the
source checkout recorded when building the viewer. `uv` must be on PATH or in
`~/.local/bin`. SteamVR must be running and the Vive camera must be free.

## Printable QR cube

**Presentation → QR Cube (STL ZIP)** downloads the complete print kit,
including the support socket core, five QR plates, and assembly instructions.
No design needs to be loaded.

To generate the same kit from the command line, use a fresh output directory:

```sh
node frontend/scripts/generate-qr-cube.mjs OUTPUT_DIRECTORY
```

The output contains a **150 mm core** and **five flat face-plate STLs**. Each plate
has a 3 mm white base and 0.6 mm raised QR modules. Print flat, changing to black
at Z=3 mm, or paint the raised modules matte black. STL does not encode colors.
Unpainted single-color relief is not a reliable camera marker. Tiny white
channels separate diagonal relief contacts so the meshes remain manifold.

The core has a centered blind support socket opening on its bottom (-Z in the
STL). For the 150 mm core, it tapers from a **90 mm bottom diameter (60%)** to a
**45 mm flat-end diameter (30%)** over 138 mm of depth. The end leaves **15 mm
(10%)** to the lower white surface of the top QR pattern: 12 mm of core plus the
3 mm top plate. The circular walls use 128 segments. The bottom QR plate is
omitted so the stand/rod opening stays accessible; the five other face IDs and
marker offsets are unchanged. For a paper-label core, use
`cubeMesh(150, { topPlateBase: 0 })` to retain the 15 mm clearance without a plate.

For registration without arrangement calibration, glue each plate centered on
its named core face, with minimal adhesive thickness. Alternatively, use any
plate order and quarter-turn orientation, then run **VR → Calibrate cube**.
On vertical faces, QR top points toward cube top. On the top face it points toward
cube back. Top QR right points toward cube right. The encoded marker plane is 78.6 mm from cube center.
Measure finished print dimensions and verify recognition before calibration.

The five permanent `NADOC-CUBE:1:...` codes identify face geometry. They are not
expiring invitation links; keep the meeting's scan-to-join QR separate. Native
calibration accounts for each face's rotation/offset to find the same cube center.
Mobile cube registration is not implemented yet. Use only one such cube within
the calibration area; duplicate identical cubes are ambiguous.

## Repeatable validation

**Debug → VR Tours & Tests → Left sidebar → Calibrate QR code · Vive camera**
exercises the real Share control, camera preview in both eyes and cancellation.
Validation runs all four controller-motion presets. Point away from QR targets
for the automated preview/cancel check; use the normal button for on-site alignment. It does not claim a physical
QR lock when no printed target is present.

```sh
uv run python -m tools.vr_workflows.menu_tour --qr-checks --validate --hold 0 --exit
uv run --offline --no-project --python 3.12 --with openvr==2.12.1401 --with opencv-python-headless==4.12.0.88 python -m unittest tools.vr_qr.test_geometry tools.vr_qr.test_cube
node --test frontend/scripts/qr-cube.test.mjs
ctest --test-dir native/vr_viewer/build -R 'nadoc-vr-(interaction|sidebar-unit|qr-cube-render)' --output-on-failure
```

The geometry tests cover camera pose, face transforms, instability/loss rejection
and preserving model scale/orientation while snapping its source origin. STL
checks verify closed meshes, positive volume and separate face identities.
Rendered relief projections are independently QR-decoded in retained task evidence.
