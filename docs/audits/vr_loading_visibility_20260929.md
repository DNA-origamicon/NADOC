# Visible geometry during VR representation loading

The previous model was already retained while CPU preparation and staged GPU
upload ran. The frame-delivery guard hid it after three slow frame gaps. That
explains why some atomistic transitions went blank even though Surface appeared
to retain its predecessor.

The guard now renders unlit three-pixel points from the displayed instance
buffers: atom positions, both bond endpoints, and box/surface primitive centres.
This avoids another export, CPU geometry preparation or GPU geometry upload.
The normal model remains visible until the guard activates. The target still
activates atomically after its upload fence and desktop acknowledgement; failure
or cancellation restores normal rendering of the retained model. Shadows remain
suppressed while the guard is active.

The fallback uses the same model transform, colors, depth, IDs and volume clipping.
Picking still uses the retained model's existing geometry. This is an approximate
point-cloud view, not a new molecular representation or changed topology. Its draw
cost still scales with the displayed primitive count; no universal frame-rate
bound is claimed.

## Verification

Real-GL regressions cover each primitive family from two eye positions, model
translation, an offscreen negative control, depth occlusion, object ownership IDs,
picking and unchanged geometry after leaving fallback. Staged-upload cancellation
and atomic activation checks remain in the same focused suite.

The registered **Full startup, loading visibility and representation progress**
tour now requires design pixels in both eyes during preparation and additionally
captures the point fallback when the frame guard activates. Its four-profile
matrix loads Cylinders, Surface, Stick and VDW, including Surface → Stick.

Evidence is retained under `.development-artifacts/vr-loading-visible/`.
The tour frames the private 24HB copy in the tracked view and enlarges the mirror.
It uses private desktop acknowledgements. Submitted-eye evidence does not prove
through-lens comfort or a real browser acknowledgement path.

The first four-profile run (`matrix-01`) passed the loading/ready stereo and
actual desktop checks. A follow-up run explicitly captures the active guard,
after correcting shader-controlled point sizing. Rebuilding during the first run
made `/proc/PID/exe` refer to the replaced binary, so the normal stop helper no
longer recognized its owned process. The exact recorded test process was stopped
and its recorded IPC paths removed using the existing cleanup routine. No user
viewer was running before either launch.

Final validation (`matrix-02`) passed all four controller profiles. Every
transition retained visible design pixels in both eyes during normal loading,
with separately captured and verified active point fallback, then displayed the
requested representation at 100%. Measured request-to-ready intervals were
5.56 s (Cylinders), 60.93 s (Surface), 22.57 s (Stick), and 29.24 s (VDW).
These are end-to-end load intervals, not GPU performance benchmarks.
The actual desktop visibility check passed. The final viewer exited and all
recorded session paths, socket and representation files were confirmed absent.

Native rebuild and both focused real-GL tests passed (staged representation and
ScryWrite object IDs). Python workflow compilation and whitespace checks passed.
Retained captures and logs remain in the artifact directory; no user design was
modified. The next VR launch uses the rebuilt viewer.
