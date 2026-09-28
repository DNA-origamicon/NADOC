# VR presenter model

**Show VR model** is a default-on toggle in the left controller's menu-button
**Share** tab. It shows guests a simple headset, shoulder bar, estimated upper arms
and forearms, plus tracked controller bodies and short direction indicators. There
is no equivalent desktop toggle. Links and the start of sharing remain desktop-only.

Create the shared view on desktop, enter VR, and let guests open the invitation.
Guests see the figure without needing to follow the desktop camera. They can orbit
around the design while the presenter points and gestures. Pause perspective leaves
the figure visible; Show VR model hides it independently. Ending the share, exiting
VR, losing head tracking, or losing the pose stream hides the figure. An untracked
controller hides its arm until tracking resumes. Opening a new VR session defaults
the toggle to on again.

This requires a host advertising `vr-avatar-v1`. If an older host was already running,
end and restart sharing on desktop to load the updated guest viewer.

## Approximation and research

Headset and controller poses are tracked. Shoulder and elbow positions are estimates;
three tracked devices cannot uniquely determine a person's torso or elbow pose.
The geometry is procedural, with no external mesh asset or skeleton dependency.

References reviewed:

- [Daniel Holden: Simple Two Joint IK](https://www.theorangeduck.com/page/simple-two-joint)
  derives analytic two-joint positioning and discusses the bend-plane axis.
- [Unity: Two Bone IK](https://docs.unity3d.com/Packages/com.unity.animation.rigging@1.2/manual/constraints/TwoBoneIKConstraint.html)
  describes a tracked target and a separate bend-direction hint.
- [Google VR: Arm models](https://developers.google.com/vr/elements/arm-model)
  describes estimating a controller position from rotation. NADOC already has
  positional tracking, so it keeps those measured positions and estimates elbows.

The implementation is original analytic math: put shoulders 18 cm to either side
of a head-yaw-based neck, 22 cm down and 8 cm back from the eye center. Each arm
uses two nominal 32 cm links. For shoulder `s`, wrist `w`, distance `d`, and a unit
bend vector `b` perpendicular to `w-s`, the elbow is

`e = (s+w)/2 + b * sqrt(L² - (d/2)²)`.

The bend hint points outward, downward and slightly backward. Degenerate directions
have finite fallback axes. For unreachable targets, both estimated links stretch
slightly rather than moving the measured controller. These dimensions communicate
gestures; they are not a calibrated anatomical reconstruction. Guest interpolation
smooths short pose intervals; reacquired controllers snap to their measured pose.

## Scale and coordinate registration

The scientific model is unchanged. The native model mapping is

`tracking = G * [k * (R * source_nm - center) + offset]`.

`G` includes one-/two-hand model manipulation, `k` is native normalization, and `R`
is the desktop-to-native export rotation. The backend inverts that complete mapping.
The guest applies it to the entire metric avatar, including headset/controller size
and arm thickness. Therefore **doubling the model's VR scale halves the presenter
figure's guest-space size**, while preserving its relationship to the design.
Rotating or moving the model similarly changes where the guest sees the presenter.

The avatar is a transient object outside the exported scientific scene. It neither
changes topology/history nor forces a model snapshot upload on every gesture.
Native capture is bounded to 20 Hz; browser publication is 10 Hz with one request
in flight and no queue. The existing authenticated local management transport and
guest SSE stream carry a bounded validated packet, scoped to the current room revision.
Poses expire after 1.5 seconds at the guest. The local feed expires after one second.
This is supported on the existing direct and WSL persistent sharing transports.

Guest model replacement reattaches the transient avatar. Multi-overlay rendering
adds it after the representation layers, using the final layer's depth buffer;
those independently rendered layers do not provide a single combined depth surface.

## Review

Debug → VR Tours & Tests → Left sidebar → **VR presenter model**.
The demo uses a real local sharing host, real guest SSE and viewer rendering, and
profile-driven physical controller input. It creates no public invitation. The
validation mode runs all four controller-motion presets. Guest captures and projected
bone pixel checks are retained in `.development-artifacts/vr-avatar/`.
See [validation audit](audits/vr_presenter_model_20260928.md).

## Guest-visible VR controls

With **Show VR model** on, guests also see the presenter's open left/right sidebar
menus, the view-toggle tablet with its desktop icons, legacy tool/desktop panels,
and the native controller/tool guides. These include pointing rays, the radius
wheel, scissors, impending nick highlights, ligation previews and end-resize arrows.
Panels retain their actual text, active/disabled states and hover highlights.
Guests can orbit around this display, but cannot operate its controls. Closing a
panel removes it from the guest scene; disabling the VR model hides the controls
with the figure. The same inverse model transform positions and scales everything.

The native exporter reuses rendered panel textures (RGBA PNGs, cached until the
texture changes) and the actual tracking-space guide vertices. GPU readback uses
a pixel-pack buffer and a polled fence; PNG encoding runs in a background job.
Each panel has at most one capture/encode in flight, so rapid changes coalesce
without waiting for GPU transfer or compression on the XR frame thread. It excludes test
witness overlays and recorded controller-path diagnostics. No mesh/model/history
export is involved. The local/management packet limit is 4 MiB, with bounded panel
count, image dimensions and guide vertices. Guests only decode inline PNG data,
not presenter-supplied URLs. Native desktop panels transmit the desktop pixels
already displayed on that VR panel while it is open.

The ordered guest event stream sends each unchanged panel image once per connection,
then sends its corners and a reuse marker. New/reconnected guests receive full images.
Backpressure coalesces pending poses to the latest state; a guest that cannot drain
for five seconds disconnects and can reconnect. This avoids both growing queues and
incorrectly disconnecting on the first menu-sized packet. Pose expiry continues to
hide stale presence. Restart an older running sharing host to load the updated
viewer/transport (`vr-ui-v1`).

Debug → VR Tours & Tests → Left sidebar → **VR menus and tools in guest view**
provides the reusable demo and four-profile validation. Evidence is under
`.development-artifacts/vr-presence-ui/`.

See the [guest controls audit](audits/vr_guest_controls_20260928.md) for delivered
pixel evidence and the remaining controller-motion timing validation limit.
