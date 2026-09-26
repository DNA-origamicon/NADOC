# Host a password-protected presentation from a new computer

Guests can join from an unrelated network with an ordinary browser, the invitation
link, and its meeting password. They do not install NADOC, Tailscale, or a VPN.
Keep the hosting computer awake and the NADOC server running. Three guest places are
available by default. Geographic reach does not mean unlimited simultaneous guests.

## One-time host setup

1. Install Node.js LTS (22 or newer recommended), install the repository's frontend
   dependencies (`cd frontend && npm ci`), and install Tailscale from
   https://tailscale.com/download on the hosting computer.
2. Start Tailscale and sign in. On Linux, use `tailscale up`; on Windows, sign in
   through the Tailscale app. In WSL, install Node and Tailscale on **Windows** too:
   the native Windows helper owns the public connection, while WSL runs the editor.
3. The tailnet owner must allow HTTPS certificates and Funnel for this device/user.
   If the first hosting attempt shows a Tailscale approval URL, open it on the host
   and complete the account approval. This approval is never a guest requirement.
   See https://tailscale.com/docs/features/tailscale-funnel for current provider steps.
4. Start NADOC and choose **File → Sharing… → Enable link**.
   Server startup already builds missing guest-viewer assets and starts one public
   connection in the background. The Sharing dialog shows its readiness even before
   activation. Enabling waits for public DNS/HTTPS verification if still pending;
   closing the dialog does not interrupt background setup. No design is published
   until you enable its link.
5. The link and password are visible in read-only fields. Double-click a field to
   select its full value, or use its right-hand copy icon (**Copy link** or
   **Copy password**). Send both to your guests.
   **End presentation** disconnects guests and enables **Enable link** again,
   while retaining the public connection. Closing the part session also revokes access.
   Each activation gets two hours; expiry releases the shared data but keeps the
   connection ready. Restarting the server invalidates all invitations.
   Errors appear in a collapsed **Error log** that you can expand.
   For optional diagnostics, run `node scripts/setup_sharing.mjs --check --browser`.
   The browser check may require `cd frontend && npx playwright install chromium`
   (plus Playwright's documented Linux libraries). This test dependency is not
   required for normal hosting or guest access.

The editor may be opened on localhost or this host's exact private Tailscale URL
configured by `start.sh --tailscale` (`NADOC_PUBLIC_URL`). Arbitrary Tailscale hosts
are not trusted to manage this host. Public guests cannot reach the editor or its
management API.

## What is checked

- Installed Node, frontend build, Tailscale CLI and signed-in state; the provider
  reports missing account/HTTPS/Funnel authorization to the host.
- A free supported HTTPS port: 443, then 8443, then 10000. Existing private routes
  remain unchanged. No blanket provider reset or incoming firewall rule is used.
- Google **and** Cloudflare public DNS must return public relay addresses. Private
  MagicDNS / 100.x addresses and a successful local browser do not count.
- HTTPS is connected directly to each returned public IPv4 relay, with normal TLS
  hostname/certificate checks, and must identify this exact running NADOC host.
- Public editor and management endpoints must return 404.
- The optional `--browser` check publishes a disposable synthetic view, pins browser
  resolution to a public relay, checks wrong-password denial and unauthenticated
  scene denial, joins with the correct password, loads the scene and orbits it,
  checks editor isolation, then revokes its invitation even after failure. It writes
  no workspace design, screenshot, trace, invitation file or browser profile.

The browser check needs one free snapshot/guest slot; run it before a meeting.
Continuous host checks run every 30 seconds. Each Enable link request waits automatically for public access before publication. A later outage is reported without revoking existing rooms.
A green check demonstrates this public relay path from the host's network, not
that every guest ISP permits the connection. A phone on cellular with Tailscale
turned off is a useful independent final acceptance check.

## Diagnose or repeat

`node scripts/setup_sharing.mjs --check` checks the running host without starting
one or exposing a design. Add `--browser` for the complete guest check.
Server startup prepares hosting automatically. Enable link also retries setup if needed. The CLI
is an optional diagnostic/setup tool, not a one-time requirement for each computer.
The dialog shows the current DNS or HTTPS wait reason. Its fifteen-minute deadline
also covers stalled startup/status requests; on timeout, Enable link becomes
available again and the error log explains the failure. The background host keeps
running, and a late response cannot publish an invitation from the timed-out attempt.

For NXDOMAIN, keep hosting running. The provider documents up to ten minutes for
DNS publication; on Compy5000 on 2026-09-24 publication took longer than ten minutes.
Automatic link creation and the optional setup command wait up to fifteen minutes, then reports failure with hosting
left running so publication can finish; try Enable link again later (or run the optional `--check`). Do not send invitations
until both public DNS checks pass. Restarting repeatedly can prolong the delay.
If authoritative DNS still lacks the hostname, collect the checks for Tailscale
support; do not ask guests to install Tailscale, disable certificate checking,
modify hosts files, or replace the link with a raw IP address.

A stale host must be stopped and restarted after a viewer/server upgrade; that
invalidates old invitations. End the presentation before upgrading and restart
the NADOC server. Background heartbeat checks do not upgrade an active host. Missing CLI/sign-in/approval errors require completing the
named host setup step and retrying. If all three public ports are occupied, free
only a known obsolete service or choose another host; NADOC does not overwrite it.

## Connection lifetime and resource use

One public gateway serves all presentations. Opening additional files does not
create tunnels or upload designs. Only explicitly enabled snapshots occupy host
memory, and ending/expiry releases them. The gateway checks public access every
30 seconds and receives a local editor heartbeat every 30 seconds. An abruptly
terminated editor loses its gateway within 90 seconds; normal shutdown ends it
immediately. Set `NADOC_SHARE_AUTOSTART=0` to disable automatic preparation.

A warm, healthy connection avoids DNS publication on subsequent enables. First
startup and recovery can still encounter provider delays. Snapshot export and
guest downloads still depend on design size and the network. No cloud storage
is used. Links are currently fresh invitations per activation; automatic stable
per-file URLs are not needed to reuse the connection.
