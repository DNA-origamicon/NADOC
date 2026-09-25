# Host a password-protected presentation from a new computer

Guests can join from an unrelated network with an ordinary browser, the invitation
link, and its meeting password. They do not install NADOC, Tailscale, or a VPN.
Hosting is temporary; keep the hosting computer awake. Three guest places are
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
4. Start NADOC and choose **File → Sharing… → Create link**.
   NADOC builds missing guest-viewer assets, starts the temporary host and waits
   for public DNS/HTTPS checks automatically before publishing. There is no separate
   setup button or required terminal command. Progress appears in the existing
   sharing status; keep the window open while first-time DNS publication completes.
5. **Copy link** copies only the URL. Send the separately displayed password too.
   **Stop sharing all links** ends guest access and enables **Create link** again.
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
Continuous host checks run every 30 seconds. Each Create link request waits automatically for public access before publication. A later outage is reported without revoking existing rooms.
A green check demonstrates this public relay path from the host's network, not
that every guest ISP permits the connection. A phone on cellular with Tailscale
turned off is a useful independent final acceptance check.

## Diagnose or repeat

`node scripts/setup_sharing.mjs --check` checks the running host without starting
one or exposing a design. Add `--browser` for the complete guest check.
Normal link creation starts hosting and displays progress automatically. The CLI
is an optional diagnostic/setup tool, not a one-time requirement for each computer.

For NXDOMAIN, keep hosting running. The provider documents up to ten minutes for
DNS publication; on Compy5000 on 2026-09-24 publication took longer than ten minutes.
Automatic link creation and the optional setup command wait up to fifteen minutes, then reports failure with hosting
left running so publication can finish; try Create link again later (or run the optional `--check`). Do not send invitations
until both public DNS checks pass. Restarting repeatedly can prolong the delay.
If authoritative DNS still lacks the hostname, collect the checks for Tailscale
support; do not ask guests to install Tailscale, disable certificate checking,
modify hosts files, or replace the link with a raw IP address.

A stale host must be stopped and restarted after a viewer/server upgrade; that
invalidates old invitations. Stop hosting from the Sharing dialog before upgrading
an active meeting. Missing CLI/sign-in/approval errors require completing the
named host setup step and retrying. If all three public ports are occupied, free
only a known obsolete service or choose another host; NADOC does not overwrite it.
