---
type: project
status: active
authority: canonical
---
# Password-protected public sharing

User requirement: guests on any network use an ordinary browser plus the invitation
and meeting password, or scan a guest-only QR and enter a name (2026-09-28); never require guest Tailscale/VPN installation or accounts.
The hosting computer needs Node, signed-in Tailscale, HTTPS and Funnel permission.

Desktop sharing on WSL/non-native-VR hosts treats the optional presenter-pose
feed as unavailable (`avatar: null`), rather than returning repeated 503 errors.
The pose endpoint still enforces local-client and trusted-origin checks; native
VR launch remains restricted to supported Linux desktops.
Ending a presentation, resetting its invitation, or closing its document cancels
the editor's in-flight drawing read before revocation, preventing stale-room errors.
The WSL Windows request helper must allow `broadcast/view-lock` and `drawings`,
as well as the server routes. The public browser check exercises this transport,
lock/unlock and late joining, and loading-overlay stacking above all roster rows.
Guest loading sits above participant lists and below the terminal overlay.

The previous Windows success and full public-relay check are recorded in
`docs/audits/internet_viewer_20260920/README.md`. On Compy5000, local/private DNS
initially hid authoritative public NXDOMAIN. Public DNS subsequently appeared;
network access must be verified publicly, not inferred from private browser success.

The editor server warms one public gateway at startup, without publishing a design.
Opening a part or assembly allocates a stable invitation without exporting or
publishing its scene. Presentation → Sharing offers Copy link/password and a
reusable guest QR; Presentation → Start exports and publishes the current design.
Guests see an automatically updating inactive/preparing page until Start completes.
Stop, document close/change, expiry, and host restart revoke sessions and release
scene data, while retaining the design invitation. Reset link rotates its address,
password, and QR and ends any active session. Host-local credentials are stored
atomically in private `~/.nadoc/presentation-links-<workspace hash>.json` on the hosting OS, keyed by
part/assembly ID; no existing design files are rewritten. Keep this file private.
Links persist on this host at its current public address; changing computers or
public hostname/port requires distributing the new address. With the host off,
the browser cannot load a waiting page. Each active session still gets two hours.
Late uploads after document close are revoked. Managed hosts stop after 90 seconds
without an editor heartbeat, protecting against abrupt editor-process death.
Background retries/heartbeats run every 30 seconds; active builds are not upgraded
by these ticks. NADOC_SHARE_AUTOSTART=0 disables warming (used by isolated tests).
No separate setup button or terminal command is required. Tailscale installation,
sign-in and owner approval remain host prerequisites.
`node scripts/setup_sharing.mjs --check --browser` is an optional diagnostic.
See `docs/sharing_host_setup.md`.
The runtime checks Google + Cloudflare public DNS, pinned public IPv4 relay HTTPS
with normal TLS validation and exact host identity, and isolated editor/admin URLs.
Starting presentations remains blocked until verified; repeated checks retain existing rooms.
The optional browser check verifies password denial/acceptance, scene load/orbit and
isolation using a disposable invitation, revoked in finally. No workspace files.

Preserve unrelated Tailscale services. Choose free supported HTTPS ports 443,8443,
10000; never reset the provider or weaken passwords/certificates to work around DNS.
Keep pending hosting running while DNS publishes. Host upgrades end active sessions; stable invitations remain inactive until Start. Current capacity is four guest browser sessions across hosted snapshots, with
separate presenter access so a full guest room cannot block camera sharing or locking, and active sessions expire after two hours by default, never with gateway age.
Native Windows/WSL transport is preserved; the 2026-09-24 setup changes were exercised
on Linux, not freshly executed on a new Windows installation.

## QR guest entry / mobile tracking (2026-09-28)

New hosts expose `qrUrl` with a separate per-room 256-bit guest-only credential.
The QR join bypasses the password only after server validation; ordinary guest
links keep password authentication. A copied QR grants the same guest access
whenever that design is presenting until Reset link, so this is not proof of physical presence.
Sharing shows a QR, the combined AprilTag/40 mm QR sheet, and **Print large
tracking QR** (150 mm including quiet zone, `qrmm=150` configures the phone).
QR guests can start a local camera diagnostic showing a target outline and
approximate phone position relative to the QR. It uses jsQR and a planar pose
estimate with assumed/adjustable vertical FOV; target must stay visible. No
camera frames or poses are transmitted. Mobile poses are not connected to VR
portal rendering or attendee markers. Native Share now has separate Vive QR
calibration (docs/vr_qr_calibration.md); physical alignment is still unverified. See `docs/meeting_room_target.md`.
Software-only synthetic camera validation is separate from pending physical
print, phone compatibility, calibration and headset testing.

## Guest pointing and screenshots (2026-09-30)

Guest viewers have a **Draw** toggle. Desktop users hold Shift and the primary
mouse button; mobile users draw with one finger without a modifier. Mobile Draw
leaves Follow and holds the camera steady, blocking rotation, zoom, and recentering
until toggled off. A presenter lock cancels mobile Draw and takes camera control;
mobile Draw remains disabled until the host unlocks. Desktop drawing remains
available while locked. Both locked and voluntary Follow use the same interpolated
camera path without reconstructing controls each frame; authored animation frames
remain synchronized exactly. Marks hold for two seconds and fade over 500 ms;
camera or scene changes clear them. Authenticated guest updates use bounded
point batches and server expiry, never design storage. `guest-drawing-v1` hosts
relay marks through meeting state; the editor reads a small authenticated channel
every 200 ms while presenting. Matching camera poses see each other's marks,
including the presenter after selecting a guest's shared perspective. Different
perspectives do not. Coordinates use viewport heights so differing aspect ratios
remain aligned. Desktop drawing works while perspective is locked without changing it.

**Screenshot** downloads a PNG of the current rendered 3D canvas, composited onto
its background, excluding DOM controls, view cube, captions and drawing overlays.
Rendering and copying occur synchronously to avoid an already-cleared WebGL buffer.
Existing hosting processes need restarting to load the new viewer and channel.

`frontend/e2e/drawing_share.spec.js` exercises the presenter plus three guest
contexts, matching/independent views, expiry, clearing, locked drawing, and a
nonblank downloaded PNG unchanged by a covering magenta DOM overlay. It derives
whole-structure framing from rendered bounds: the picking harness's original
bead close-up could orbit off the structure. Four PNGs documenting that initial
empty view and the final visible screenshot, plus a fifth PNG of visible ink, are retained under
`.development-artifacts/guest-drawing/`. Browser downloads, test designs, project
histories, credentials and report folders are cleaned after the test.

Validation: 7,328 frontend tests passed (one skipped), 32 focused sharing-host
tests passed, 23 smoke tests passed, and the multi-client browser/pixel test,
production build and lint passed. `main.js` change: zero lines. The backend FAST
run had 9,485 passed, 93 skipped and the same six failures in untouched scalar
geometry, surface extraction and VR color-control tests as before this feature.
Guard output:

> DEFERRED: this change would have needed the FULL suite, but no test-dedicated
> session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
> This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
> Only request `just test-session` when a broad/full sweep is actually needed.

## Full-room presenter controls (2026-10-01)

Guest admission and presenter access are counted separately. Four guests can join
before the editor shares a perspective; starting, stopping, and locking the
presenter camera do not consume another guest slot. A fifth guest remains blocked.
Embedded presenter scene refresh receives the current host capabilities, avoiding
false restart errors for supported view tools/annotations when locking.
The dedicated `frontend/e2e/perspective_capacity.spec.js` browser regression joins
four guests and exercises sharing, stopping, locking from stopped, and unlocking.

Validation: 7,333 frontend tests passed (one skipped), 14 focused Node host tests
passed, production build passed, and the dedicated four-guest browser regression
passed. Test designs, credentials/status sidecars and browser report folders were
verified removed. Logs are retained under `.development-artifacts/perspective-capacity/`.
An expanded drawing scenario reached sharing/locking successfully but failed its
later ink-visibility check after locking; drawing behavior remains unresolved and
its original test was left unchanged. The new capacity regression is independent.
The broad backend `just test-smart` selected FAST but was interrupted by the
2026-10-01 out-of-memory event before producing a pass count; it was not rerun.
Its broad-suite deferral was:

> DEFERRED: this change would have needed the FULL suite, but no test-dedicated
> session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
> This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
> Only request `just test-session` when a broad/full sweep is actually needed.

## Simulation Share feedback (2026-10-01)

Simulation sharing uses the same editor broadcast lease, so the full-room capacity
fix also permits starting a job stream with four guest sessions connected.
Job Share now immediately shows Sharing… / Stopping… and disables duplicate
clicks while pending. Status/errors sit immediately below the Visualizations
header, outside its collapsible body, and start/stop errors also reach the visible
presentation bar. Retrying clears the previous bar error. Pending frame failures
are handled inside toggle's error/finally boundary so controls recover.

Validation: all 7,335 frontend tests passed (one skipped), capped at two workers;
30 focused job/share-link tests passed after the final error-reset change. The
browser regression passed with four separate guest sessions, active presenter
camera handoff, an injected failed start and retry, oxDNA/NAMD switching, live
frame changes, private-selection isolation, and return to native. These use HTTP
job fixtures and real render buffers; no scientific simulation was launched.
`frontend/e2e/job_sharing.spec.js` now uses the configured isolated test port,
cleans the credential/status sidecar, and stores five review PNGs plus three logs
under `.development-artifacts/job-sharing/`. Workspace test files, credentials,
and Playwright output directories were verified absent after teardown.

## Presentation representation limits and cancellation (2026-10-01)

Active sharing sets the editor's ephemeral `presentationActive` state. Detail
Surface is disabled in the View menu/sidebar and rejected by the design, region,
assembly and simulation surface transports. Quick Surface remains available.
A global detailed surface is switched to Quick Surface on presentation entry;
ending the presentation restores the menu choice without restarting expensive work.
Surface operations expose Cancel. Cancel and representation switches abort all
pending surface requests and send document-scoped cancellation to the server.
The server stops at its next measured surface checkpoint; it cannot preempt a
native numerical call already executing. Early cancellation is retained briefly
so a late-arriving request never starts. Representation generations prevent stale
heavy completions from replacing the newest selection. Unneeded native atom
loads are aborted on switch-off; shared loads required by pinned regions/volumes
are preserved, and stale global atom responses do not repaint the current view.

Validation: 7,340 frontend tests passed (one skipped), four focused surface-progress
backend tests passed, and the four-guest browser regression passed with delayed
surface transport, explicit Cancel, F4 cancellation, detailed menu/sidebar blocking
while presenting and restoration after End. No expensive surface calculation was
launched in the browser test. Browser test designs, credentials and report folders
were verified removed. Logs live in `.development-artifacts/presentation-surface/`.
The capped two-worker `just test-smart -- --maxfail=1` selected FAST and stopped at
the previously observed, untouched `test_the_scalar_and_loop_skip_fast_paths_agree`
failure: 2,778 passed, 17 skipped, one failed. Its broad-suite deferral was:

> DEFERRED: this change would have needed the FULL suite, but no test-dedicated
> session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
> This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
> Only request `just test-session` when a broad/full sweep is actually needed.
