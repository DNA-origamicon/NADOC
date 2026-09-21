# Experimental prepared viewer and presentation sharing

The first local package prototype captures the currently visible 3D scene into a
`.nadocview` file and opens it in `viewer.html`, without an editor backend. It uses
the same scene runtime and Orbit/Trackball/Multiscale controls as NADOC. This is an
experimental viewer with temporary internet presentations and short prepared Full
trajectory clips. Full representation/assembly parity and hardware/WAN performance
acceptance remain open; see the [development plan](standalone_viewer_presentation_plan.md).

## Share one invitation throughout a meeting

1. Open the view you want to publish and choose **Help → Share link**.
2. For a new meeting, select **New invitation** and press **Create link for current
   view**. Send guests **Copy invitation**, which includes the HTTPS link and password.
3. To replace the shared content, select that existing **Presentation** and press
   **Update shared view**. Guests keep the same link, password, sign-in and camera.
4. Enable **Include recorded trajectory** to publish a prepared Full clip, or leave
   it off to publish a static view. Use **Play shared clip**, **Pause shared clip**
   and the shared-frame slider for the recording; normal editor MD playback stays private.
5. For editor camera/coloring/section changes, use **Help → Broadcast to presentation**.
   Stop broadcasting before replacing content. To broadcast visualizations after a
   clip, update the same presentation with a static view first.

The host can inspect other files while guests keep the last shared content.
**Open presenter** grants host controls; guests receive the ordinary invitation.
Content updates do not extend the original meeting expiry. **Stop sharing** revokes
one invitation; **Stop hosting all links**, host shutdown or expiry ends the session.

**One-time upgrade:** an already running helper keeps its loaded code. If NADOC
reports that it predates same-link updates, finish the meeting, stop hosting, and
create one new invitation. That restart ends the old links and sign-ins. Subsequent
content updates preserve the new invitation. Updating source files or rebuilding
alone does not upgrade the running helper.

The [latest validation record](audits/unified_sharing_20260921.md) covers the real
cube_pore static → trajectory → static browser flow, tests and remaining limits.

## Try it locally

1. Open a design in NADOC, select the desired 3D representation, and wait for all
   requested assets to appear. The package freezes what is currently visible.
2. Choose **Export → Prepared Viewer Snapshot… (experimental)**.
3. Open `/viewer.html` on the same local frontend server, then select or drop the
   exported file. Orbit, pan, zoom, double-click to center, and Reset view work there.
4. **Performance** exposes the same repeatable-orbit capture and copyable metrics
   as the editor. Keep camera, canvas dimensions, representation and hardware equal
   when comparing. The A/B label does not switch implementations.

For backend-free local use, build the frontend (`cd frontend && npm run build`),
serve `frontend/dist` with an ordinary static HTTP server, and open `/viewer.html`.
For example, from the repository root:

```bash
python3 -m http.server 5182 --bind 127.0.0.1 --directory frontend/dist
```

No Python API, simulations, or NADOC installation is needed in the viewing browser.
A static server still serves the application assets; double-clicking `viewer.html`
from disk is not a supported ES-module delivery mechanism. This command listens
only on the local machine. For meeting links, use the separate Help-menu flow below.

## Present from the standard editor

Create a link with **Help → Share link**, then choose **Help → Broadcast to
presentation…**. Select the meeting and independently enable **Share my
perspective** and **Share current visualizations**. Broadcasting starts off.
The visible broadcast badge and the Help toggle both stop it immediately locally;
the host rejects subsequent writes from its revoked lease. Guests keep the same
link, password, sign-in, and last successfully shared scene. A host-side 15-second
lease also stops an editor that closes or loses its connection without notifying it.

Camera messages are small, coalesced, and limited to four per second; guests still
choose Jump or Follow. Settled coloring, representation, and section changes send
replacement prepared scenes no more often than every three seconds. Visualizations
are checked once per second and wait until mouse gestures settle. Camera motion
alone does not re-export geometry. Guest scene replacement preserves independent
camera position; downloads are checked against the announced package SHA-256.

In multi-view, the last pane clicked or navigated is shared as one interactive 3D
view. Guests do not get the whole split layout. Trusted section planes and hatched
caps are supported; transform gizmos remain local. Unsupported custom shaders,
including the remaining assembly/atomistic adapters, stop publication with a
visible explanation and leave the last valid guest scene intact. This snapshot
update mechanism is not trajectory playback or scientific selection sharing.

Changing/opening another file stops broadcasting; turning it on again is explicit.
Camera-only mode checks the design hash against the shared snapshot before starting.
Editor broadcasting takes over the presenter seat from the standalone presenter
page and still counts toward the four-participant limit. The standalone presenter
can resume after editor broadcasting stops.

An already running host keeps its loaded application/code. A host started before
this feature must be stopped after the current meeting and started again with a
new link. NADOC detects this version mismatch and explains it in the dialog; it
does not silently restart the host or end working guest sessions.

Large-scene replacement can have noticeable preparation/upload/rebuild cost.
`[NADOC_PRESENTATION_UPDATE v1]` console entries record package bytes and elapsed
preparation/upload time. Real-GPU A/B on VoltronCoreArmV2 and cube_pore with this
toggle remains an acceptance check; functional browser tests do not establish FPS
parity. Incremental visual updates are a later optimization.

## Package contract

- Magic `NADOCVW1`, bounded JSON manifest, aligned binary typed arrays; 512 MiB file
  limit and 16 MiB manifest limit. Coordinates are not expanded into JSON numbers.
- Plain scene packages remain schema 1; sectioned packages use schema 2 so an old
  viewer rejects them instead of silently omitting the cuts. The current reader
  accepts both versions.
- Nanometre coordinates, version and exact Three.js revision, camera/clip planes,
  visible object matrices, shared geometry/material tables, instance matrices and
  colors, draw ranges, material groups, embedded PNG textures and lights.
- Existing per-instance alpha is restored using NADOC's trusted shader patch.
  Trusted section clipping planes and hatched stencil caps are preserved; editing
  gizmos stay local. Unknown/custom shader pipelines, morphs, skinning and unsupported
  image/material types fail explicitly. Photo/multiple-view rendering overrides
  and nonstandard camera layers must be exited before exporting. The file supplies no executable shaders
  or external image URLs. Allocation and texture-dimension budgets are checked.
- Interleaved attributes are copied into equivalent packed attributes. Repeated
  scene objects share decoded geometry/materials. Loading a new valid file disposes
  old GPU resources; a failed or stale load cannot replace the current view.
- Source document SHA-256 is included for matching existing frame-capture logs;
  the loaded package also gets a SHA-256 over its actual bytes. The source document
  hash does not verify simulation content. No native design document, structured sequence fields, feature history,
  workspace paths, editing endpoints or simulation jobs are included. Visible
  labels/textures and object names remain part of the snapshot.
- A normal snapshot may contain one physical frame but remains static. The explicit
  trajectory-link flow adds a bounded prepared recording and playback controls;
  neither format is a complete simulation archive.

This experimental schema is pinned to its renderer version. Unsupported versions
are rejected; future schema migration remains part of the package development.

## Remaining acceptance work

The complete phase gates remain open: stable scientific selection references;
base/domain/cluster inspection; shared assembly shader transforms; all supported
representations and physical overlays; full recorded-trajectory/graphene/ion acceptance;
package readiness/error UX; long-session and large-design hardware performance;
scientific highlight rooms and the browser/OS matrix. Temporary internet hosting
and camera-only Jump/Follow are implemented; their hardware/WAN acceptance remains open.

An assembly is not intentionally excluded as a product tier. The current package
prototype rejects unsupported shared assembly shaders because dropping their
transform patch would place instances incorrectly. That renderer contract must be
ported before claiming assembly parity. Atomistic impostor shaders likewise need
an explicit adapter; no fallback silently substitutes another representation.

The earlier production A/B report covers the decoder-extraction checkpoint only.
It is not performance acceptance for this new package viewer.

## Verification and artifact ownership

`frontend/e2e/prepared_viewer.spec.js` exercises native export, backend-independent
opening, navigation/reset, failed-load preservation, and same-pose canvas parity.
`NADOC_PREPARED_FIXTURE` opts into a read-only Voltron source; imported test copies
receive a `__e2e__` identity/name and omit history. Existing teardown removes test
parts and project stores. Downloads/images go only into Playwright output. No
simulation is launched. Software-rendered timings are not GPU acceptance evidence.

The initial [validation evidence](audits/prepared_viewer_20260920/README.md) includes
a 22.6 MB Voltron round-trip with identical reference/loaded images and no editor
API requests, small-scene navigation checks, and 6,685 passing frontend tests.
The package viewer's real-GPU performance gate remains open.


## Share the current part over the internet

On the hosting PC, use **Help → Share link… → Create link for current view**.
The default host now prepares an HTTPS invitation for guests on any network.
**Copy invitation** includes the link, a generated meeting password, and simple
browser instructions. Guests enter their display name and password; they need no
NADOC, Tailscale, VPN, extension, account, certificate exception, or file picker.
**Copy link** remains available for sending the password separately. The invitation
is a bearer credential; the display name is not verified identity.

Build the frontend before hosting (`cd frontend && npm run build`). The hosting PC
needs Node and a signed-in Tailscale CLI, with HTTPS and Funnel enabled by its owner.
First-time provider approval happens only on the hosting PC. NADOC surfaces the
provider's approval URL if this prerequisite is missing. The Windows/WSL launcher
starts a hidden background Node helper; it does not elevate PowerShell, create an
incoming firewall exception, change the network profile, or modify an existing
Node block rule. Guests connect to a publicly trusted HTTPS website.

Windows startup uses a short-lived native Node bootstrap with detached file-backed
logging. PowerShell only locates the installed executables; it does not supervise
the meeting process. This avoids a startup timeout that previously displayed an
encoded PowerShell command even when the helper had started successfully. NADOC
checks the authenticated local host before treating a bootstrap failure as fatal.
See the [startup correction validation](audits/share_launch_20260920.md).

The helper creates a foreground Tailscale Funnel on HTTPS port 443, proxying only
the prepared guest listener on local loopback port 5183. It refuses an occupied
provider port and preserves unrelated Serve/Funnel configurations (including the
existing private editor route). Host management lives on a separate loopback port
5184, requires a file-only bearer credential, and is never routed through Funnel.
Public `/host/*` and editor API requests return 404. The editor's control middleware
still accepts only local, same-origin requests with the explicit custom header.
WSL controls the Windows helper through a local Windows subprocess. Private upload
temporary files are removed in `finally`; credential files are pre-created mode0600.

Each snapshot gets an independent invite, 96-bit random password, and HttpOnly,
Secure, SameSite=Strict session cookie. Joining checks the configured HTTPS origin;
passwords travel in the request body rather than the URL. Join attempts are bounded
at 60 per minute across the host. Four participants across the host, including the presenter, eight
snapshots / 512 MiB aggregate, and the two-hour default lifetime remain enforced.
Later editor changes do not alter a published snapshot.

### Present a perspective

Use **Open presenter** in the host's Share link dialog, enter a name and the same
meeting password, then select **Share my perspective**. This opens the frozen
snapshot rather than sharing an editable document. **Copy invitation** always
copies the guest link; presenter authority uses a separate secret available only
through host management. One presenter is allowed per snapshot.

Guests start with independent navigation. **Jump to presenter** moves once;
**Follow presenter** tracks subsequent camera changes. Dragging, scrolling,
resetting or changing navigation mode exits Follow before handling the input.
Pausing, presenter disconnect or guest network loss also exits Follow.
Reconnection restores the latest state without taking over the guest's camera.
Closing a guest browser releases its participant slot after two minutes without a
heartbeat. Once joined, the presenter's sign-in and occupied slot remain reserved
until the meeting ends. Revoking a snapshot ends its event streams immediately.

**Leave presentation** pauses perspective sharing while keeping the room, guest
link and guest sign-ins intact. The presenter may work on another native file in
the editor, or open another prepared view privately in the presenter tab.
**Return to presentation** restores the latest shared snapshot and reconnects
the presenter. Guests never reload their scene or sign in again because the
presenter stepped away. They remain independent until choosing Follow again.
Dropping a different prepared file directly into an active presenter tab also
steps away automatically; the private file is never substituted into the room.

Closing and reopening the presenter invitation in the same browser resumes its
existing sign-in, even after the usual two-minute guest inactivity interval.
Guest reloads also reuse an existing valid sign-in. A different browser still
requires the presenter invitation and password; it can reclaim the presenter's
place after explicit Leave or two minutes disconnected, without affecting guests. The existing snapshot remains listed
under **Help → Share link**, regardless of which file is open in the editor.
Leaving the presentation does not stop the background host. The host PC must stay
awake, and the existing meeting expiry still applies; **Stop sharing**, **Stop
hosting all links**, host shutdown and expiry end availability. This does not make
links permanent or automatically restart expired public hosting.

Camera messages carry the exact package SHA-256 and a monotonically increasing
sequence. The host validates role, origin, bounds and rate; guests receive bounded
server-sent events. The presenter coalesces motion into at most ten POST requests
per second with only one camera request in flight. Following interpolates locally;
it does not regenerate or transfer geometry. Opening another package disables the
old presentation channel. This phase does not supply scientific selection or
base/domain/cluster highlighting.

Starting a performance capture pauses presenter broadcast and exits Follow so the
repeatable orbit owns the camera. These captures can assess independent navigation
with incoming room events, but do not measure Follow motion; that measurement is a
separate acceptance item. Keep canvas dimensions equal when comparing—the room
toolbar changes available height.

An already running helper retains its original server code and built assets.
New presenter controls become available in the next hosting session after the
updated frontend is built. Stop/start invalidates existing invitations.

**Stop sharing** revokes one snapshot; **Stop hosting all links**, expiry, or tunnel
loss ends the complete session. The helper closes both listeners and its owned
foreground tunnel. Keep the hosting PC awake while presenting. Tailscale's installed
background service may remain running, but the meeting route is session-scoped.
Ending sharing cannot retract bytes already delivered to a guest browser.

The design is served from this PC through a managed relay, not a permanent NADOC
cloud deployment. Tailscale documents that Funnel's relay does not terminate the
browser-to-host TLS connection. This is nevertheless third-party infrastructure,
with provider availability and bandwidth limits. Transfer time and eventual
highlight/playback latency need separate measurement from local orbit FPS.

Validation: host tests check password/origin enforcement, secure cookies, rate
limits, independent revocation and isolation of management; a production browser
test uses an isolated test-only TLS proxy to exercise wrong-password rejection,
automatic loading, navigation and disconnect. The owner has approved the provider, and native public-route startup/stop/restart
has been verified. The final public-browser check is recorded in the internet audit. No claim of remote GPU
performance acceptance follows from these local tests.

References: [Funnel architecture](https://tailscale.com/docs/features/tailscale-funnel),
[sharing a local service](https://tailscale.com/docs/use-cases/application-testing/share-local-dev-server-with-internet).

## Temporary same-network invite links

`scripts/prepared_view_host.mjs` serves the production viewer and one selected
package, independently of NADOC's editor/backend. Build the frontend, export a
snapshot, then run on the hosting PC:

```bash
node scripts/prepared_view_host.mjs --package /path/VoltronCoreArmV2.nadocview --dist frontend/dist --bind 192.168.0.15 --port 5182 --minutes 120
```

Use the host PC's actual LAN address for `--bind`. The command prints an invite
link containing a random secret in its fragment. Guests open the link, enter a
1–40 character display name, and the design downloads automatically. No NADOC,
Python, Node, extension, or file picker is needed on their laptop. Only the host
runs Node. This older LAN-only CLI is optional; the Help menu uses internet sharing.
The CLI prints a guest invitation; use the Help-menu flow for presenter access.

The process allows four browser sessions (including any presenter browser),
expires after two hours by default (maximum eight), and stops immediately with
Ctrl-C. A restart creates a new invite and forgets prior sessions. Cookie-based
session credentials protect the package; the host exposes no editor routes,
workspace listing, arbitrary files, or write operations. Reloading and rejoining
in the same browser reuses its slot. Guest slots expire after two minutes without
a heartbeat; presenter credentials and their slot persist until meeting end.
Explicit participant roster management is deferred.

This initial transport is **HTTP on a trusted local network**, not internet
hosting or encrypted access. Anyone on that network who has the invite can join;
a display name is not identity authentication. Do not forward this port through a
router. Different-network invitations use the HTTPS transport described above.
No permanent listener, scheduled task, cloud upload, or background service is
installed. A downloaded view can remain usable after hosting stops; stopping the
host revokes further access, not bytes already delivered.

On Windows/WSL, run the host with Windows Node on the Windows LAN interface, or
use native Windows PowerShell. WSL's NAT-only address is generally not the laptop's
route to the PC. If Windows Firewall blocks the port, the optional
`scripts/start_prepared_view.ps1` launcher creates a rule restricted to that Node
program, port, interface address and local subnet, then removes it in `finally`
when the host exits. That helper requires Administrator PowerShell; it does not
change the network profile or disable the firewall. An abrupt process/OS kill can
skip `finally`; any leftover rule is named `NADOC-Temporary-Viewer-*` and can be
removed through Windows Firewall. Without a listening host it serves nothing.

On plain HTTP, browser clipboard permission may be unavailable: the performance
panel selects the metrics text so normal Ctrl-C still works. Browser SHA-256 APIs
may also be unavailable outside HTTPS/localhost, so package identity may be null
in those diagnostic captures. LAN testing establishes reachability and usability;
it does not replace matched real-GPU performance comparisons or the browser/OS
acceptance matrix.

See the [LAN prototype validation record](audits/prepared_lan_20260920/README.md)
for completed browser/host tests and the separate Windows approval/network gate.

The [Help-menu validation record](audits/share_link_menu_20260920/README.md)
covers the actual copy/share/open flow and native Windows control transport.


## First recorded trajectory sharing slice (2026-09-21)

Load a NAMD trajectory in the main 3D **Full** part view, turn water off, and pause.
Open **Help → Share link**, enable **Include recorded trajectory**, and choose
first/last frame, interval, and samples per second. Use **Create link for current
view** for a new presentation or **Update shared view** for the selected existing
presentation. Preparation visits those frames through the normal
MD display controller and restores the inspected source frame. Cancel is available.
Send the invitation and password as usual. **Play shared clip**, **Pause shared clip**,
and the shared-frame slider operate the prepared recording, independently of the
editor's private trajectory player. The standalone presenter page also has controls.
Guests keep their own camera and existing name/password session. Closing the editor
dialog or privately opening another design does not remove the prepared recording.

A running host from before trajectory sharing cannot serve clips. Same-link content
replacement also requires the newer `share-content-v1` host capability. After the current meeting,
use **Stop hosting all links**, then create a new invitation with **Include recorded trajectory** enabled. This deliberately
ends old links; no active meeting is restarted automatically by the upgrade.

Each frame is an independently applicable, compressed patch against one prepared
scene. Coordinates match the exported Full display; patches update existing GPU
attributes instead of reconstructing the whole scene. The receiver downloads one
frame at a time, predicts ahead using measured transfer time, and skips old samples.
Pause/seek cancels obsolete requests and requests the exact selected sample. A small
status request periodically estimates clock delay from half the round-trip time;
this is approximate synchronization, not a latency guarantee. **Buffer clip** can
preload a short recording before playback, within the cache budget.

Initial limits: 2–120 samples, 1–30 requested samples/s (UI presets 4/8/15/30),
128 MiB compressed trajectory payload across the host's active clips, 16 MiB per
frame, and 32 MiB decompressed receiver cache. The initial scene is additional memory
and transfer. Clips remain in host memory until revoked/expired; disk-backed long
recordings are a later step. Source display structure/settings must remain stable
during preparation. Main-view NAMD Full parts are supported; assembly playback and
multi-view need temporal display adapters. Atomistic/surface and water are rejected.
Visible graphene/ions use the existing companion-frame readiness path; end-to-end
validation of those overlays remains open.

This is temporal adaptation only: fewer samples on slow connections, with no
interpolation or spatial simplification. It does not yet implement the proposed
segment approximation or atomic refinement on pause. Requesting 30 samples/s does
not establish 30 rendered FPS. **Copy trajectory metrics** emits
`[NADOC_TRAJECTORY_PERF v1]` with transferred bytes, applied/skipped samples, waiting
time, cache use and transfer timing. It explicitly distinguishes sample application
from renderer FPS. Use the existing Performance capture separately for render-loop
measurements; its repeatable orbit currently suspends trajectory application.

For initial trials, prepare 8–16 samples and use **Buffer clip** before playing.
The measured exact cube_pore patch was about 1.1 MB: 8 uncached samples/s would
require about 71 Mbps per guest before overhead. Compact molecular streaming is
still needed for efficient continuous playback.

A public Funnel link still sends each guest a separate copy from the hosting PC.
Three guests at 3 Mbps each would use about 9 Mbps upload plus overhead. The reported
50–100 Mbps upload is promising, but guest bandwidth, GPU speed and the tunnel must
still be measured. Real-GPU/WAN acceptance remains open; see
[validation record](audits/trajectory_sharing_20260921.md).


## One invitation across view and trajectory changes

The separate trajectory-link button has been removed. Select an existing
**Presentation** in Help → Share link and use **Update shared view**. Enable
**Include recorded trajectory** to publish a prepared clip; leave it off to publish
the visible static view. The guest URL, password, sign-in and meeting expiry stay
the same. Guests receive the new scene and retain their own camera; playback
controls appear or disappear with the recording. Preparation or validation failure
keeps the previous shared content. Select **New invitation** only for an intentionally
separate presentation. Turn off editor broadcasting before replacing its content.

The presenter entry remains a host action with separate authority; send guests the
ordinary invitation. See [same-link validation](audits/unified_sharing_20260921.md).
