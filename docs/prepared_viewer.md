# Experimental prepared viewer snapshots

The first local package prototype captures the currently visible 3D scene into a
`.nadocview` file and opens it in `viewer.html`, without an editor backend. It uses
the same scene runtime and Orbit/Trackball/Multiscale controls as NADOC. This is an
intermediate Phase 1/2 checkpoint, not a completed presentation product.

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

## Package contract

- Magic `NADOCVW1`, bounded JSON manifest, aligned binary typed arrays; 512 MiB file
  limit and 16 MiB manifest limit. Coordinates are not expanded into JSON numbers.
- Nanometre coordinates, version and exact Three.js revision, camera/clip planes,
  visible object matrices, shared geometry/material tables, instance matrices and
  colors, draw ranges, material groups, embedded PNG textures and lights.
- Existing per-instance alpha is restored using NADOC's trusted shader patch.
  Unknown/custom shader pipelines, clipping, morphs, skinning and unsupported
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
- A snapshot may contain a physical frame currently displayed, but it has no
  recorded trajectory, frame topology contract or playback controls. Treat it as
  a static display, not a simulation archive.

This experimental schema is pinned to its renderer version. Unsupported versions
are rejected; future schema migration remains part of the package development.

## Remaining acceptance work

The complete phase gates remain open: stable scientific selection references;
base/domain/cluster inspection; shared assembly shader transforms; all supported
representations and physical overlays; recorded cube_pore trajectories/graphene/ions;
package readiness/error UX; long-session and large-design hardware performance;
join/highlight/jump/follow rooms; meeting-scoped hosting; browser/OS matrix.

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
at 60 per minute across the host. Four browser sessions per snapshot, eight
snapshots / 512 MiB aggregate, and the two-hour default lifetime remain enforced.
Later editor changes do not alter a published snapshot.

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
runs Node. This older LAN-only CLI is optional; the Help menu uses internet sharing. This is a static viewing test: guests orbit independently; names do
not yet provide a participant roster or shared presenter state.

The process allows four browser sessions (including any presenter browser),
expires after two hours by default (maximum eight), and stops immediately with
Ctrl-C. A restart creates a new invite and forgets prior sessions. Cookie-based
session credentials protect the package; the host exposes no editor routes,
workspace listing, arbitrary files, or write operations. Reloading and rejoining
in the same browser reuses its slot. Slots otherwise remain occupied until the
host ends; participant management is deferred.

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
