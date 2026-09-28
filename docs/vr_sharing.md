# VR Share controls and presentation feasibility

Open the left controller's menu button panel and select **Share**. Link setup and
starting the presentation remain on desktop. The VR panel provides:

- **Pause perspective**: stops the current camera broadcast; guests retain the last
  view and can explore independently. The link remains hosted.
- **Resume perspective**: resumes perspective sharing in the existing room.
- **End presentation (all links)**: uses the desktop End action, stops hosting, and
  disables the VR controls. Restart from desktop.

The status row shows inactive, paused, sharing, pending, or failed. Controls follow
the desktop's busy state and wait for acknowledgement. Missing desktop updates
expire after three seconds. Failures retain the desktop error details and allow
retry. There are no link creation, copying, invitation, or hosting-start controls.

The default-on **Show VR model** toggle now shares a tracked headset/controller
figure with estimated arms, independently of the desktop camera. See
[VR presenter model](vr_presenter_model.md) for behavior and scale registration.

## Feasibility assessment

**Presenting while wearing VR is feasible now as remote control of a desktop-hosted
presentation. A true first-person VR broadcast is not implemented.** The panel
explicitly labels the source as the desktop camera.

| Capability | Current support / remaining work |
| --- | --- |
| Manage an established presentation | Implemented: pause/resume perspective, end all links. Same desktop handlers, room and leases. |
| Present design edits made in VR | Existing committed edits update the desktop document. `native_view_tool_sharing.js` publishes settled design/display snapshots in the explicitly shared context. This is snapshot sharing, not every drag preview. |
| Present VR view-toggle changes | Toggles invoke desktop view tools, whose prepared-scene changes use that same publication path. |
| Show headset perspective | Feasible extension. `editor_broadcast.js` currently captures the desktop prepared camera every 250 ms. Native head/eye poses and `livePresentationJson` expose the data needed to derive a camera in source coordinates; no production bridge joins these today. |
| Show VR model grabs, rotation and scale | Currently local presentation transforms. They do not change the desktop camera or published design. A VR camera source must incorporate the inverse model-to-tracking transform, source normalization, export rotation and model offset. |
| Share controller gestures | Implemented with the transient VR presenter figure and short controller direction indicators. Live edit previews are still separate work. |
| Multi-user VR collaboration | Separate larger effort: guest immersive navigation, ownership/concurrency, remote avatars/pointers and lifecycle handling. Current guest controls are browser-based. |

The next useful extension would be an explicit **Desktop / VR perspective** choice
within an already-started desktop session. Send one cyclopean camera in model
coordinates; preserve the existing guest opt-in follow behavior. Smooth head jitter,
bound transmission frequency, and pause on tracking loss, browser disconnect or VR
exit. Test conversion through grip rotation, two-hand scaling, recenter, export
rotation and layout changes. A spectator camera may be more comfortable than raw
head motion; that needs user evaluation. The current 4 Hz desktop publisher and
existing guest interpolation establish transport reuse, not acceptable VR-follow
latency or comfort.

## Review and validation

Debug → **VR Tours & Tests** → **Left sidebar** → **Share presenter controls**
provides a repeatable demo and four-profile validation. Its hosting transport is
simulated; it creates no public link. It uses the real desktop presenter handlers,
local VR transport, controller rays and trigger clicks. The isolated temporary
workspace is deleted, `__e2e__` artifacts are removed by global teardown, and the
owned native viewer is stopped even on test failure.

See [validation audit](audits/vr_share_20260928.md) for evidence and limitations.
