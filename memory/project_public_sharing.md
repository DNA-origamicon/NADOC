---
type: project
status: active
authority: canonical
---
# Password-protected public sharing

User requirement: guests on any network use an ordinary browser plus the invitation
and meeting password, or scan a guest-only QR and enter a name (2026-09-28); never require guest Tailscale/VPN installation or accounts.
The hosting computer needs Node, signed-in Tailscale, HTTPS and Funnel permission.

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
Keep pending hosting running while DNS publishes. Host upgrades end active sessions; stable invitations remain inactive until Start. Current concurrency remains three
guests plus presenter, and active sessions expire after two hours by default, never with gateway age.
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
