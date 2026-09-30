# VR startup and menu depth

Normal **View in VR** starts the native OpenXR application before constructing
molecular geometry. A world-space loading panel is placed at the first valid
tracked head height, facing the user's initial horizontal viewing direction.
The panel stays anchored in the room as the user looks around.

The progress bar reports completed preparation stages, not an estimated fraction
of elapsed time. The current task and the complete stage list remain visible:
nucleotide geometry, Full display geometry and selection metadata, natural export,
validation/compression, native parsing,
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

VR exports only the natural pose. Expanded Quick View has been removed from VR,
including duplicate geometry, interpolation and tool-placement dependencies.
Use model scaling and physical movement for close inspection. Desktop Quick View
remains available; its expanded geometry is not transferred into VR.


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

The Vive System button (below the trackpad) belongs to SteamVR; the application
Menu button opens NADOC sidebars. NADOC does not bind `/input/system/click`.
When SteamVR takes OpenXR focus, NADOC now releases held inputs, cancels active
controller grabs and uncommitted end pulls, and preserves scene/menu placement.
On return, release the controller buttons before starting a new interaction.

September 30 dashboard investigation: SteamVR 2.17.10 has dashboard, desktop and
new-desktop settings enabled; system-button forwarding to applications is off.
The Steam browser helper had logged a GPU crash and was restarted. A temporary
explicit toolbar-display diagnostic produced readable Steam toolbar pixels and
was restored afterward. That attempt changed no Steam configuration settings. This does
not establish normal System-button activation or desktop mouse interaction:
the connected headset had no valid pose and no controllers were connected.
Evidence is in `.development-artifacts/steamvr-dashboard-20260930/`.
Finish with a tracked headset and powered controllers: open SteamVR's dashboard
and Desktop in SteamVR Home, then repeat during a normal NADOC session and check
that returning does not move the model or leave a button held.

The subsequent tracked-headset test confirmed that System opens the dashboard,
but selecting Desktop crashes Steam itself. At 10:35:02, the 32-bit Steam VR
client logged `Failed to load pixel shader ! (size=2147483647)` while initializing
`CVulkanVRRenderer`; the kernel recorded a fault in NVIDIA's
`libnvidia-glcore.so.580.178.04`. Steam's exit then tears down SteamVR. This matches
the failure reported in [Valve's Linux issue 963](https://github.com/ValveSoftware/SteamVR-for-Linux/issues/963).
It occurred outside NADOC. The browser-helper restart does not fix this failure.
Crash logs, dump and the original settings are preserved under the evidence
directory's `desktop-crash-103502/` subdirectory.

The older-renderer workaround (`dashboard.useNewDesktop=false`) also failed
on this X11 machine: the physical Desktop click at 10:42:41 produced the same
shader error and Steam crash. The setting was verified false and has now been
removed. Evidence is retained in `desktop-crash-104241/`. Do not repeat this
workaround as a known fix.

The next diagnostic uses Steam's Game Versions & Betas UI to select Valve's
`previous` branch (SteamVR 2.16.7, build 23791826), replacing build 25330290.
The user confirmed selecting Desktop no longer crashes, but the desktop is blank.
This is not a working Desktop fix. NADOC's separate X11 desktop tablet is now
reachable from the left-hand VR tab for comparison. Restore the current
release by choosing Default Public Version in the same UI; do not mix individual
runtime libraries across releases.

September 30 appearance investigation restored Default Public Version,
SteamVR 2.17.10 build 25330290. The Visualization color regression reproduced
under both 2.16.7 and 2.17.10; it was traced to NADOC's native accent table,
not the runtime downgrade. Standard SteamVR Desktop remains unresolved.

September 30, 14:33: kernel logs confirmed a global out-of-memory event during
VR development. The automatic viewer build could run Ninja's default parallel
build of every target, including test executables; multiple compiler processes
were consuming about 1 GB each. Automatic builds now serialize across processes
with a file lock and compile only `nadoc-vr-viewer` with `--parallel 1`. The
freshness check runs under the lock. Manual verification must likewise avoid
overlapping builds and VR sessions on this host.
