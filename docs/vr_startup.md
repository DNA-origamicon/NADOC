# VR startup and menu depth

Normal **View in VR** starts the native OpenXR application before constructing
molecular geometry. A world-space loading panel is placed at the first valid
tracked head height, facing the user's initial horizontal viewing direction.
The panel stays anchored in the room as the user looks around.

The progress bar reports completed preparation stages, not an estimated fraction
of elapsed time. The current task and the complete stage list remain visible:
nucleotide geometry, Full display geometry and selection metadata, natural export,
Expanded Quick View geometry and export, validation/compression, native parsing,
GPU preparation and first part frame. Startup loads **Full only**, even when the
desktop previously displayed another representation. The existing
first-frame-ready signal still means the part is ready, rather than an empty
loading scene.

The backend exports a frozen copy of the document on a worker carrying the
request's document context. Scene and progress publication are atomic. Parsing
runs off the headset render thread; only Full is uploaded at startup. Startup errors remain visible in the headset, and
**Stop VR** or closing the companion window cancels the session. CPU export
cancellation is checked at stage boundaries. Individual GPU uploads are still
synchronous, so this does not guarantee a frame deadline during every upload.
SteamVR initialization and rebuilding an outdated native binary remain startup
prerequisites; an already built viewer no longer waits for the model export.

Other representations load on first selection. The selected button contains a
progress bar beneath its label, with a one-decimal percentage. Completed export
records and parsed input lines drive progress within preparation stages; this
is not an elapsed-time estimate. The previous representation remains visible
until the new one can be displayed. Loaded geometry remains available in the
session; document refreshes invalidate it. Errors leave a retry message in the
button. Switching requests supersedes obsolete exports and parser results.

Cylinder exports use the desktop `helix_renderer` builder, including its 1.125 nm
default radius, staple-domain palette, half cylinders and curved tubes. Native
VR renders these exported faces directly instead of reconstructing narrower
scaffold-colored axis tubes. Desktop and VR still use different scene lighting.

All eleven representation identifiers share the browser publication contract;
Surface, Hull, Beads, VDW and input previews must never be silently published as
Full. A completed native load waits for this real desktop acknowledgement.
Controller rays extend to an open sidebar as soon as the controller aims at it,
without requiring a trigger press or changing molecular point selection.

The expanded pose is the existing **Expanded Quick View**: a display-only spread
of the part, not a simulation or design change. Each loaded representation
includes its normal and expanded geometry, so Full's expanded toggle is ready
at startup.

Menus use same-eye color and depth snapshots. World-space controller sticks,
selection spheres and other guides now participate in depth testing and depth
writes. Blur taps reject geometry in front of the menu. Full-resolution samples
avoid foreground colors leaking through a prefiltered mipmap into nearby glass.
The existing 15-pixel blur extent and white tint are retained.

Reusable checks in **Debug → VR Tours & Tests → Controls & layout**:

- **Cold startup and headset loading progress** launches a private copy of 24HB
  through the normal backend route and captures loading and ready stereo frames.
- **On-demand representation loading** checks button progress in both eyes,
  continued frames, retained previous geometry, and successful style application.
  Validation covers all four motion presets.
- **Menu blur and controller depth** moves a controller in front of and behind a
  menu, checks sharp foreground pixels in both eyes, and removes the menu as a
  negative control proving that the rear controller was present. Validation runs
  all four existing motion presets.

These checks own and close their viewer and keep evidence under
`.development-artifacts/vr-startup/` and `.development-artifacts/vr-depth/`.
They do not edit the source part. Stereo captures establish application-submitted
pixels, not through-lens legibility or headset comfort.

Validation and retained attempts: [September 29 audit](audits/vr_startup_depth_20260929.md).

Full-only startup measurements and on-demand checks: [lazy-loading audit](audits/vr_lazy_representations_20260929.md).

Backend clean shutdown/reload now closes its owned native viewer and waits for
session-file cleanup. The registered browser-to-headset check uses real browser
acknowledgements; see [workflow and lifecycle audit](audits/vr_browser_lifecycle_20260929.md).
