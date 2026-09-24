# Guest annotation placement and atomic NAMD clips

Guest annotations now pass bounded world-space obstacles from the rendered meshes
and atom instances into the same screen-space occupancy/layout algorithm as the
editor. Obstacles are recomputed from current guest transforms, so camera movement
and streamed coordinates affect placement. Matrices update once per overlay frame.
Guest callouts auto-layout even when the presenter pinned them: the presenter's
screen coordinates do not describe the guest's independently chosen camera. The
published annotation data remains unchanged. Placement remains best-effort if the
structure and callouts fill the viewport, as in the editor.

Obstacle sampling is capped at 4096 instances/meshes. Disc rasterization now clips
its iteration to viewport cells, preventing an enormous near-camera sphere from
causing an unbounded off-screen loop. This is a conservative mesh-bound occupancy
approximation, not pixel-perfect depth-buffer occlusion.

File → Sharing exposes Include recorded trajectory again, wired to the actual NAMD
controller, pause action and solvent-frame readiness. Clips accept Full, VDW,
ball-and-stick and stick part views. Atomic export awaits the exact requested frame
and topology application regardless of coarse playback settings, reports missing
coordinates, and awaits restoration of the inspected frame. Changing the design,
trajectory or representation cancels capture and prevents restoring into the new
context. Surface, assembly, multi-view and water clips remain unsupported.

Existing limits remain enforced: 2–120 frames, 16 MiB per raw frame patch, 128 MiB
compressed clip data, 512 MiB package and the existing render-channel count budget.
No atom subsampling was introduced. Large structures can exceed those limits;
no workstation or institutional-network performance threshold is claimed.

Validation: 292 viewer/controller/annotation unit tests passed. Tests include
actual atomistic-renderer and display-controller round trips for VDW, ball-and-stick
and stick (including out-of-order guest frame application), exact asynchronous
atomic readiness/failure, representation-change cancellation, guest structure
avoidance after camera changes, and near-camera occupancy bounds. Chromium guest
annotation placement/update/hide tests and the production build passed. The build
retains its existing bundle-size warning.
