# VR Share controls and presentation feasibility

Open the left controller's menu button panel and select **Share**. Invitation display and link management remain on desktop. The VR panel provides:

- **Start presentation**: publishes the current design using the same lifecycle as desktop, without opening a desktop dialog.

- **Pause perspective**: stops the current camera broadcast; guests retain the last
  view and can explore independently. The link remains hosted.
- **Share headset perspective**: shares a smoothed first-person headset camera in the existing room. It also switches an active desktop camera broadcast to the headset.
- **Admit new guests**: admits responsive waiting guests immediately, releasing only
  enough of the longest-present guests to make room. With no waiting guests it
  frees the oldest guest’s slot. Presenter access is retained.
- **Guest counts**: active and waiting guests for this presentation.
- **End presentation (all links)**: uses the desktop End action, stops hosting, and
  disables active-session controls. Start again from VR when ready.

The status row shows inactive, paused, sharing, pending, or failed. Controls follow
the desktop's busy state and wait for acknowledgement. Missing desktop updates
expire after three seconds. Failures retain the desktop error details and allow
retry. Copying and displaying invitations remain desktop actions.

The default-on **Show VR model** toggle now shares a tracked headset/controller
figure with estimated arms, independently of the desktop camera. See
[VR presenter model](vr_presenter_model.md) for behavior and scale registration.

## Feasibility assessment

**VR presenters can share a headset-driven first-person camera.** Guests render the shared model locally and choose Follow presenter. This is a camera stream, not captured headset video. Desktop perspective sharing remains available from the desktop toolbar.

| Capability | Current support / remaining work |
| --- | --- |
| Manage an established presentation | Implemented: pause/resume perspective, end all links. Same desktop handlers, room and leases. |
| Present design edits made in VR | Existing committed edits update the desktop document. `native_view_tool_sharing.js` publishes settled design/display snapshots in the explicitly shared context. This is snapshot sharing, not every drag preview. |
| Present VR view-toggle changes | Toggles invoke desktop view tools, whose prepared-scene changes use that same publication path. |
| Show headset perspective | Implemented: native mid-eye position and orientation map into source coordinates; the camera publishes at up to 10 Hz and guests smooth it every render frame. |
| Show VR model grabs, rotation and scale | Headset following incorporates the inverse model-to-tracking transform, source normalization, export rotation and model offset. Desktop camera sharing is unchanged. |
| Share controller gestures | Implemented with the transient VR presenter figure and short controller direction indicators. Live edit previews are still separate work. |
| Multi-user VR collaboration | Separate larger effort: guest immersive navigation, ownership/concurrency, remote avatars/pointers and lifecycle handling. Current guest controls are browser-based. |

Headset following uses a 70° vertical spectator field of view with guest-device aspect ratio. Near and far planes scale with the VR model transform. Guest-side orientation interpolation uses quaternions and position interpolation stays first-person, avoiding an orbit around the moving look target. The default damping time constant is 180 ms; angular motion is capped at 90°/s and translation at one tracking metre/s. Large deliberate turns therefore take longer to catch up. These defaults require human comfort feedback rather than implying a through-lens comfort result.

Tracking loss holds the view and retains Follow preference; fresh tracking resumes automatically. A host-issued 1.5-second camera expiry also holds stale cameras if other presence events continue. Transport errors pause broadcasting. Headset sharing is independent of **Show VR model**. Following guests hide the presenter’s headset/body to avoid self-occlusion, while controllers and panels remain visible. Independent guests still see the avatar. Trajectory sharing must be stopped before enabling headset perspective; animation controls retain camera ownership during animation.

## Review and validation

Debug → **VR Tours & Tests** → **Left sidebar** → **Share presenter controls**
provides a repeatable demo and four-profile validation. It uses a real test-owned local host; it creates no public link. It uses the real desktop presenter handlers,
local VR transport, controller rays and trigger clicks. The isolated temporary
workspace is deleted, `__e2e__` artifacts are removed by global teardown, and the
owned native viewer is stopped even on test failure.

See [validation audit](audits/vr_share_20260928.md) for evidence and limitations.

## Guest capacity and model-size scaling (2026-10-16)

The user reports mostly successful mixed mobile, PC and Mac sessions. Treat that
cross-device acceptance gap as closed; large-model delays remain observed. The
user also validated VR avatar visualization on mobile devices.

The production LAN and internet launchers currently inherit `maxGuests = 16` from
`scripts/prepared_view_host.mjs`. This is a host-wide guest-session limit across
rooms, not a measured hardware limit. The presenter does not consume a guest slot.
Guest leases and queued admission are described below. Sixteen-session admission
has an automated burst test; this is not a sixteen-device rendering benchmark.

This workstation exposes a Ryzen 9 9950X (16 cores / 32 threads) and about 30 GiB
RAM to the host environment. Guests render on their own devices. The server keeps
prepared scenes in memory and sends each guest the complete replacement scene
for committed design edits; it does not render a separate video per guest.
Consequently the primary scaling estimate is bytes transferred, not raw base-pair
count. Representation, overlays and geometry detail affect the prepared size.

For N guests, a prepared scene of S decimal MB and effective outbound bandwidth B
Mbps, the ideal aggregate transfer floor is `8 × N × S / B` seconds. At sixteen guests:

| Scene size | 100 Mbps | 1 Gbps |
| --- | --- | --- |
| 5 MB | 6.4 s | 0.64 s |
| 20 MB | 25.6 s | 2.56 s |
| 100 MB | 128 s | 12.8 s |

These are arithmetic transfer floors, not measured demo latency. Add generation,
roughly 1–2 seconds of polling/settling, export, any host upload/tunnel overhead,
and guest download/decode/GPU reconstruction. Slow clients and shared Wi-Fi can
increase the times. An already-loaded stationary model needs little scene traffic;
avatar/menu traffic is separate and scales with guest count. No hardware ceiling or few-second large-model latency is established by this
estimate.


## Admission and audience rotation (2026-10-16)

The host admits 16 guest sessions across presentations; presenters do not use
these slots. Overflow enters a host-wide FIFO queue, bounded to 256 waiting
sessions. The same browser cookie preserves queue order and admission age on
reload or reauthentication. Names are not identities: different browser profiles
can still join separately. Queue traffic uses a five-second presence request and
does not download a model, subscribe to avatar events, or enter the participant
roster until admitted. Join attempts are bounded to 240 per minute host-wide;
queue polling and acceptance do not repeat the join request.

Browser acknowledgements renew the lease. Server-sent event heartbeats and
ordinary status/download requests do not. Hidden pages suspend live streams and
transfers immediately and lose their place after two minutes. Two minutes without
acknowledgements also releases an active place, allowing temporary disconnections
to recover. Waiting tickets expire after 90 seconds without acknowledgement.
A one-second server sweep reclaims places even without new join attempts.

Visible guests who have not interacted for five minutes are prompted only while
someone is waiting. They have 30 seconds to choose **I’m still watching**; normal
trusted pointer, wheel or keyboard activity also renews their activity time.
**Leave presentation** releases a place immediately. Automatically freed places
are reserved for the next responsive visible waiting guest for 30 seconds; they
must choose **Join now**, otherwise the offer expires and the next guest is offered
it. A returning or released guest chooses **Join again** and goes behind existing
waiting guests. Released-session records expire after ten minutes.

Desktop’s persistent presentation toolbar shows **Admit new guests**, active and
waiting counts, and **Guests → Remove**. The left VR **Share** tab exposes the same
Admit action and counts through the existing document-bound desktop bridge.
Admission remains available while guest perspective is locked; perspective
pause/resume retain their separate availability rules.
Actions use the local host credential; guest cookies cannot rotate or remove the
audience. Rotation is scoped to the current presentation, uses remaining capacity
before evicting, and replaces only enough oldest guests to admit its responsive
visible queue (up to the host limit). Admission is atomic on the host, so evicted
guests cannot reclaim a slot ahead of that queue. With no eligible waiting guest,
one oldest guest is released. Other presentations’ guests are never evicted.
Browser notification arrives on the next presence poll, normally within five
seconds; “immediate” admission means no additional Join-now confirmation, not an
instant model download. Existing queued offers count as reserved slots.

A released or hidden session cannot start new scene, trajectory or event-stream
requests. Its active streams and transfers are terminated. These controls manage
live access; they cannot erase a model someone already downloaded. Load the new
host and viewer builds before the demo; an already running detached host retains
its old code and reports a build mismatch.

## Guest-name screening research and implementation

The screening is local and server-side, including QR entry. It combines bounded
Unicode input, normalization for comparison, a maintained profanity dataset,
common-disguise matching, narrow legitimate-name exceptions, and a neutral-name
fallback message. It preserves the displayed spelling and does not send names to
a moderation service. Names are rendered with text APIs rather than HTML.

[OWASP input-validation guidance](https://cheatsheetseries.owasp.org/cheatsheets/Input_Validation_Cheat_Sheet.html)
recommends server-side validation, bounds and preserving legitimate scripts and
punctuation; normalization and profanity filtering do not replace safe output
handling. [Unicode UTS #39](https://www.unicode.org/reports/tr39/) describes
confusable-character mechanisms, explaining why visual disguise needs separate
consideration from exact-word comparison.

The selected [Obscenity library](https://github.com/jo3-l/obscenity) provides an
English dataset, normalization/disguise transformers and false-positive controls.
The host uses its recommended transformers after compatibility normalization,
plus a punctuation/space-collapsed screening copy. Exact name-token exceptions
currently cover Dick, Dickinson and Penistone; they do not exempt other words in
the name. Tests cover repeated letters, leetspeak, full-width letters, diacritics,
separated profanity, slurs and ordinary names in multiple scripts. Control and
format characters are rejected, and display names are limited to 40 Unicode
code points. Obscenity is pinned to 0.4.6 in the frontend dependency lockfile and
loaded only by the host; no browser moderation service or API key is needed.

Cloud classifiers with custom blocklists are another standard option, as in
[Azure’s moderation/blocklist documentation](https://learn.microsoft.com/en-us/azure/ai-services/content-safety/how-to/use-blocklist).
For this short-name demo field the local filter avoids their network dependency.
This is basic English-oriented screening, not a guarantee against every abusive
phrase, language, emoji or spelling. Narrow exceptions and neutral nicknames
handle false positives; presenter removal covers names that slip through.


## Admission validation evidence

The focused suite passes 60 host/transport/policy tests, 39 frontend tests and
five backend bridge tests. A host test starts 32 join requests concurrently,
then fills out a 116-session burst: exactly 16 active and 100 queued. It verifies
protected admission controls, no queued scene/stream access, rotation, rejoining,
name rejection and slot offers. Fake-clock tests cover five-minute inactivity,
30-second prompt/offer expiry, hidden/disconnected expiry and queue bounds.
This establishes admission behavior, not large-model throughput with 16 physical
devices.

The real local-host browser test passes desktop and mobile-size guest flows,
including rejected names, queue position, no scene download before admission,
oldest-first desktop replacement, explicit Leave, timed offers, rejoining and
individual removal. The physical-runtime variant passes all four controller
motion profiles with guest perspective locked: each VR button activation is
followed by a host check that the correct oldest guest lost live access and the
queued guest gained it. Stereo and desktop pixel checks pass, and offscreen
negative controls fail as intended. These establish rendered controls and input
behavior, not through-lens headset comfort. Native and frontend builds and Python
lint pass.

Evidence and logs are retained under
`.development-artifacts/guest-admission-20261016/`. Earlier failures are retained:
`browser/` exposed the fixture reading an invitation before presentation creation;
`vr/` exposed missing controller/startup setup; `vr2/` showed the new action below
the first menu page. The probe now uses tracked-head-relative controller setup,
and admission/status were moved to the top of Share. Motion presets, target sizes,
acquisition thresholds and retry limits were not relaxed. `final/` includes the
four-profile run with perspective locked; `desktop-final/` dismisses the ordinary
onboarding tip before capturing the toolbar so it does not cover guest counts.
Test-created host credentials, viewers and temporary workspaces are cleaned up;
no public invitation or production presentation was started by these checks.

## VR presentation lifecycle (2026-10-16)

The left **Share** tab now includes **Start presentation** and **End presentation (all links)**. Start uses the desktop presentation lifecycle for the current design, without opening a desktop dialog. Availability, pending-action acknowledgement, busy state, and failures synchronize to VR. Start is unavailable while a presentation is active or the design is unavailable; End stops the presentation for all guests. The design’s reusable invitation remains available for the next presentation.

QR spatial alignment and cube calibration tools have been retired. The desktop Presentation menu retains guest QR invitations and ordinary presentation controls.

Validation for this removal/lifecycle change: 45 focused frontend tests, five backend tests, frontend/native builds, and the native sidebar check (945 controls, zero layout failures) passed. Browser printing decodes the exact guest invitation and confirms both AR print controls and cube export are absent. The real local-host VR test repeats Start/guest-load/End/access-revocation across steady_fast, steady_deliberate, variable_fast and variable_deliberate. All four preserve the invitation across restart. Stereo menu pixels, offscreen negative controls, and desktop mirror checks pass. These establish rendered visibility, not through-lens comfort. Test-owned host, viewer, credentials and documents are cleaned up.

Evidence: `.development-artifacts/vr-presentation-20261016/` (`results.json`, `initial/`, `final/`, and build/browser logs). The initial print-unit check caught a missing SVG attribute value; that XML validity issue was fixed before browser validation. Motion profiles, hit geometry and visibility thresholds were unchanged; controller reach traces are retained with the captures.

## Headset-follow validation (2026-10-16)

Use **VR Share → Share headset perspective** while presenting; guests select **Follow presenter**. **Pause perspective** holds their last view. Desktop perspective controls retain the desktop source. Source changes wait for outstanding pose requests, preventing an obsolete camera from entering a new lease. Hosts advertise `headset-follow-v1`; an older host must restart before this source can be enabled.

The real local-host integration passed all four controller profiles, with desktop guests on steady profiles and mobile-size guests on variable profiles. Each cycle verified opt-in, convergence to the live headset camera, visible molecular pixels with a model-hidden negative control, pause, navigation out of Follow, and End/access revocation. Native menu stereo pixels and desktop mirrors passed all sixteen action checks. Numerical tests cover rotated/scaled/translated tracking transforms, jitter attenuation, angular/translation caps, 30/60-fps convergence, tracking loss/recovery, stale-state expiry, camera-source handoffs, and first-person avatar visibility. Backend tests (5), transport tests (20), focused frontend tests, and frontend/native builds passed.

Evidence: `.development-artifacts/headset-follow-20261016/results.json` and `validation/`. Earlier captures/logs are retained: the first attempt used an invalid synthetic pointer event; the second was interrupted when a test click targeted an overlaid presence badge. The final run uses a real click in an unobstructed canvas area. No motion-profile, hit-target or pixel thresholds were relaxed. These checks establish camera/render behavior; subjective smoothing comfort and rapid physical-head motion still need human evaluation. Test hosting, credentials, documents and the owned native viewer were removed.

## Protected demo display (2026-10-16)

A presentation host allows one protected demo display in addition to the 16 normal guest places. Copy **Demo display password** from the presenter’s sharing dialog. On the display, open the existing guest link or scan the existing printed QR, select **Set up demo display**, and enter that password and a display name. No separate URL is needed. Existing invitation IDs, QR tokens and guest passwords are preserved when the display credential is added.

The display skips the guest queue and is exempt from audience rotation, idle prompts and automatic guest removal. It automatically follows an available shared desktop or smoothed headset perspective, without requiring a Follow click. It waits between presentations and rejoins when the same design is presented again. Setup is remembered in session storage for that browser tab, including reloads. **Exit demo display** clears the saved setup and releases the protected place. The display is read-only and cannot control the presentation.

Only one display is allowed across the host’s rooms. A second display receives an occupied-place message; if the previous display has been offline for more than two minutes, a password-authenticated replacement can reclaim the place. Network outages can still interrupt rendering. Closing a tab may discard its saved setup.

Validation: 26 host/policy tests, eight presence/link/display tests (overlapping coverage), 53 unique focused frontend tests, the frontend build and a real local-host browser integration passed. The browser test fills all 16 guest places plus a queue, adds the display, verifies automatic Follow and rotation protection, reloads the tab, ends and restarts the presentation, checks automatic rejoining, and exits. It compares the rendered QR before and after restart and verifies stable invitation credentials. Evidence: `.development-artifacts/demo-display-20261016/`. This task changes no native VR controls; prior headset-follow validation covers that camera source.

## Sweep editing and headset Follow fix (2026-10-16)

A real Feature Log sweep edit reproduced the display freeze: the headset publisher stopped with **Invalid VR presenter UI**. Camera extraction had validated optional native menu graphics along with head tracking. It now validates the head pose and tracking transform independently of menu/controller graphics. Headset-only broadcast also avoids capturing the desktop scene, so temporary desktop view unavailability does not stop tracking. Document identity, source-hash checks, tracking validation and stale-camera expiry remain enforced.

The build and 52 focused frontend tests pass. Real local-host protected-display tests pass the complete Edit/Cancel/Edit/Apply/Undo/Redo sequence with `steady_fast` and `steady_deliberate`. They check camera messages stay below the 1.5-second expiry gap, automatic Follow stays active, the new scene arrives, and the rendered camera converges to the headset after each scene replacement. Captures show the display while editing and after Apply; hiding the molecular scene makes the pixel check fail as intended.

The four-profile run stopped at `variable_fast` after three missed simulated reaches to a sweep adjustment button. A fresh-design diagnostic reproduced that miss; `variable_deliberate` separately missed the sweep point button. Those profiles are not passing end-to-end evidence, and no hit geometry, motion presets, retry counts or camera thresholds were relaxed. The fix changes no native controls. These checks establish rendered camera/scene behavior, not through-lens comfort.

Evidence, including the original reproduction and all subsequent runs: `.development-artifacts/sweep-headset-follow-20261016/results.json`. The existing invitations and QR credentials are unchanged.

## Compact live sweep preview (2026-10-16)

VR sweep nodes now have a 24 mm visible radius (previously 12 mm) and a 32 mm trigger/grip selection radius (previously 16 mm). Both drawing and picking use shared native constants. Crosshair strokes are also doubled; the saved molecular geometry is unchanged.

While a sweep draft is open, ordinary guests and protected displays receive a separate, read-only preview containing its path, nodes, selected-node color, and cross-sections. It works with independent guest navigation, headset Follow, or the avatar hidden. Native sweep wireframes are excluded from the avatar graphics payload to avoid duplicating the detailed geometry. Existing invitations, passwords, and printed QR tokens are untouched. Restart the native viewer and presentation hosting, then refresh the presenter/guest pages to load the new code; the host advertises `sweep-preview-v1`.

Transport uses the existing ordered state connection, with per-connection omission of unchanged preview geometry. A new connection receives the complete current preview. The publisher polls at up to 10 Hz, sends geometry only when it changes, and coalesces large drafts to a target of 64 KiB/s per viewer. Small one-second heartbeats renew a three-second expiry. Cancel, scene replacement, and End clear the preview; the normal scene publication delivers the applied model. Stalled clients retain only the latest pending state. Host publishing requires management authority, a matching scene revision, a bounded body, and rate limits. The stream allowance accommodates 16 guests, one protected display, and a presenter.

Preview limits are 256 nodes, 512 sampled path points, one footprint of up to 128 hull vertices and 256 sampled cell centers, and one section basis per node. Guests reconstruct the cross-sections locally; very large footprints use bounded detail. Camera-only local pose responses and editor camera acknowledgements omit menu textures and preview geometry, preventing those large packets from slowing head tracking. The bandwidth target applies to preview geometry, not total presentation traffic or the initial burst.

Validation evidence is retained in `.development-artifacts/sweep-preview-20261016/`. The live probe aims 25 mm off a node center, outside the old selection radius, then drags it with a standard motion profile. Review holds are outside the measured drag. Guest pixel checks compare the visible preview against the same scene with only the preview hidden; Open, Cancel, Edit, Apply, Undo and Redo are checked along with headset camera timing. Native stereo/menu captures and a deliberately offscreen menu negative control are retained. These checks establish rendered results, not through-lens comfort or throughput on 17 physical devices.

Earlier runs are preserved: the initial unit fixture lacked a runtime scene; two live runs exposed oversized camera responses during avatar-menu setup; after stripping those payloads, both steady profiles passed the unchanged 1.5-second camera expiry threshold. The timing check now uses host publication timestamps instead of delayed test callbacks. The variable-fast profile remained blocked by three misses on the overlapping Feature Log Close control. A diagnostic attempt using the controller Menu button did not dismiss that panel in this mode and was reverted; no production hit geometry or motion thresholds were altered to make that test pass. The variable-deliberate profile passed on a mobile-sized viewport. This probe now uses direct enlarged-node dragging; it does not establish that earlier noisy numeric-button reach problems are resolved.

Final release verification: 47 focused frontend tests, 22 host tests, five backend tests, the native sweep draft/picking executable, and both builds passed. The final bandwidth-budget build also passed the real-host steady-fast workflow. Exact packet sizes, camera publication gaps and profile outcomes are recorded in `results.json` under the evidence directory.


## Eight-guest live demo observation (2026-10-16)

The user tested up to eight simultaneous guests while presenting in VR, sharing
the headset perspective, and editing a sweep. The workflow worked, but VR became
very laggy and maintaining a good framerate was difficult. This validates the
functional workflow at that observed audience size, not comfortable VR performance
or a maximum hosting capacity. FPS, model size, and network/device measurements
were not supplied, so the bottleneck is not yet established. At the user's request,
performance investigation and optimization are deferred; no performance change
is included for this report.
