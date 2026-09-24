---
type: project
status: active
authority: canonical
---
# Password-protected public sharing

User requirement: guests on any network use an ordinary browser plus the invitation
and meeting password; never require guest Tailscale/VPN installation or accounts.
The hosting computer needs Node, signed-in Tailscale, HTTPS and Funnel permission.

The previous Windows success and full public-relay check are recorded in
`docs/audits/internet_viewer_20260920/README.md`. On Compy5000, local/private DNS
initially hid authoritative public NXDOMAIN. Public DNS subsequently appeared;
network access must be verified publicly, not inferred from private browser success.

File → Sharing → Create link starts hosting and waits for public checks automatically.
No separate setup button or terminal command is required. Tailscale installation,
sign-in and owner approval remain host prerequisites.
`node scripts/setup_sharing.mjs --check --browser` is an optional diagnostic.
See `docs/sharing_host_setup.md`.
The runtime checks Google + Cloudflare public DNS, pinned public IPv4 relay HTTPS
with normal TLS validation and exact host identity, and isolated editor/admin URLs.
New invitations remain blocked until verified; repeated checks retain existing rooms.
The optional browser check verifies password denial/acceptance, scene load/orbit and
isolation using a disposable invitation, revoked in finally. No workspace files.

Preserve unrelated Tailscale services. Choose free supported HTTPS ports 443,8443,
10000; never reset the provider or weaken passwords/certificates to work around DNS.
Keep pending hosting running while DNS publishes. Host upgrades end old invitations;
copy the new invitation/password after restarting. Current concurrency remains three
guests plus presenter, and links expire with the meeting (two hours by default).
Native Windows/WSL transport is preserved; the 2026-09-24 setup changes were exercised
on Linux, not freshly executed on a new Windows installation.
