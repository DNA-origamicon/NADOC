# Reusable public-sharing setup — 2026-09-24

Requirement: any guest network, ordinary browser, invitation and password only.
Reviewed the successful native Windows/public-relay procedure from
internet_viewer_20260920/README.md. Compy5000's public DNS eventually appeared;
no hostname change, DNS bypass for guests, provider reset or private-route takeover
was required. The previous local-browser-only check was insufficient.

Implementation:
- Host checks two public DNS resolvers; private/MagicDNS answers never count.
- Pin TLS connections to returned public relays, verifying the normal hostname
  certificate, this exact host's non-secret probe identity, and editor/admin 404s.
- Check every 30s and refuse creation while public access is unverified. Existing
  rooms are not revoked on transient check failure. Pending DNS is shown honestly.
- File → Sharing has a setup/check card with per-check progress and retries.
- Portable setup/check CLI, missing-viewer build, actionable host prerequisites,
  exact configured private-editor origin and non-destructive provider port selection.
- Repeatable public browser test creates/revokes its own synthetic invitation,
  checks wrong-password/unauthenticated denial, correct-password load and orbit,
  editor/admin isolation, normal TLS and public relay DNS override (not MagicDNS).
- New-host guide and durable memory link document Windows/WSL owner-side setup,
  approval steps, DNS wait/retry, lifetime/concurrency and cleanup.

Validation:
- Frontend: 543 files; 7,047 passed, 1 skipped.
- Node sharing/provider checks: 36 passed.
- Setup dialog real-browser exercise: 1 passed; pending DNS becomes ready without
  publishing a design. Isolated bridge removed; no workspace design created.
- Production build passed. main.js LOC delta: 0.
- Live `node scripts/setup_sharing.mjs --browser` passed all checks on Compy5000,
  including both public relay addresses and wrong/correct password browser behavior.
- Published 24hb_0xT snapshot preserved privately across the helper upgrade and
  restored with a fresh invitation; upgrade scratch removed after successful restore.
- Restored 24hb_0xT was separately verified in a real browser pinned to a public relay: wrong password rejected, correct password loads its model, orbit changes pixels, no browser errors.
- Diagnostic invitations revoked in finally; only the user's 24hb_0xT room remains.

Linux execution verified. Native Windows/WSL launch/transport paths are preserved
but were not rerun on a newly installed Windows computer in this session.
Public-relay tests deliberately bypass private DNS with public resolver answers and
validate TLS normally. They do not guarantee every guest ISP permits this endpoint.
Logs retained locally under .development-artifacts/sharing-setup-20260924/.

## Automatic setup follow-up

At user request, removed the separate host setup card/button. Normal Create link
starts the helper and automatically polls public readiness for up to fifteen
minutes, publishing only after verification; no terminal command is required.
Host-owner sign-in/provider approval errors remain actionable. Disposing the app
cancels pending polls; a timeout leaves background hosting running for DNS publication.
The Node command remains an optional diagnostic, not a new-computer requirement.

Validation: 7,051 frontend tests passed (1 skipped), production build passed,
and the real-app browser regression passed: one Create link action waits for
DNS and publishes automatically, with no setup button or premature publication.
Provider traffic was intercepted in this UI regression; the previous public-relay
and password verification remains recorded above. No new public test room created.
main.js LOC delta: 0.
