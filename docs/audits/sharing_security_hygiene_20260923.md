# Sharing security, hygiene, and efficiency audit — 2026-09-23

## Scope and outcome

Reviewed the sharing paths in `frontend/src/viewer`, their scene/annotation/selection
integration, `frontend/prepared_share_*`, `scripts/prepared_*`, the launcher,
PowerShell entry point, Vite configuration, package lock, and sharing tests.
This is a source review plus local regression testing, not an external penetration
test or a certification for regulated research. Existing unrelated changes were
left alone. No public tunnel was started for testing.

Sharing now appears immediately below Workspace Hub in **File → Sharing…**.
The trigger ID, callers, browser tests, current documentation, and launcher help
were updated together. Historical audit notes retain their original menu names.

## Findings fixed

| Priority | Finding | Change |
| --- | --- | --- |
| Medium | Full sign-in reused an existing cookie, even when changing between guest and presenter. Anyone already holding that cookie could retain the newly assigned authority. | Rotate the cookie after every full authentication, invalidate the previous session, and immediately close its event streams. Same-role sign-in preserves display identity; role changes do not. Cookie-authenticated resume retains its existing role. |
| Medium | The eight-stream room limit could be exhausted by a single authenticated guest. | Limit each session to two event streams and reject additional streams with 429. Do not register presence or heartbeat work for a rejected subscription. |
| Medium | Scene downloads had no per-session concurrency limit, unlike frame downloads. Slow readers could keep multiple large scene buffers alive across revisions. | Limit concurrent scene transfers to two per session and release slots when the response closes. This is not a bandwidth quota. |
| Low | Library-level host expiration was checked on new requests; only the CLI wrapper reliably stopped existing streams at expiry. | The host's maintenance timer now closes the host and all streams at expiry, within its one-second tick. |
| Medium, deployment-dependent | npm audit reported seven affected packages (five high, two moderate), including Vite and Vitest. Development-server advisories matter if the editor itself is exposed. | Applied compatible lockfile updates without major upgrades: Vite 6.4.3, Vitest 4.1.11 and affected transitive dependencies. Full and production-only npm audits now report zero known advisories. This does not prove that every code path is vulnerability-free. |
| Efficiency | Slow status polls could overlap indefinitely on a delayed network. | Editor and guest status monitoring allow only one pending poll. |
| Efficiency | Each event broadcast serialized identical state separately for every listener. | Serialize once per broadcast; skip serialization when there are no listeners. Existing backpressure handling still disconnects slow consumers. |
| Hygiene/correctness | Export compatibility checks were duplicated and inconsistent across native, job, and editor broadcast paths. Recorded clips reconstructed only some capability flags. | Centralized the six prepared-view feature requirements. Recorded clips preserve their first export's complete compatibility metadata, including wide-line and section support. |

Session rotation follows [OWASP's session-management guidance](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html).
The reported priorities are qualitative review judgments, not CVSS scores.

## Controls verified and boundaries reviewed

| Area | Evidence and remaining boundary |
| --- | --- |
| Editor/control isolation | Internet mode uses separate loopback guest and management listeners. Only the guest listener is forwarded. Public `/host/*` is rejected. The local editor middleware checks loopback peer, Host, Origin, fetch-site and a custom header for writes. Host credentials remain in the local process/control file, not browser responses. |
| Invitation and session authority | Cryptographically random 256-bit invite, presenter and control credentials; separate guest/presenter tokens; generated internet password has 96 bits of entropy. Internet joins require the exact HTTPS origin and password. Guest session cookies are HttpOnly, Secure and SameSite=Strict. Guest writes cannot acquire presenter authority. |
| Browser safety | CSP restricts resources to the host and embedded images, blocks framing/object execution, and sets no-referrer and nosniff. Dynamic participant names, annotations, labels and errors use text rendering. Reviewed innerHTML uses are fixed templates/icons. No shared arbitrary scripts or remote image URLs are accepted by the prepared-scene loader. |
| Package and frame validation | Package/metadata limits, typed-array bounds, forbidden prototype keys, resource/depth/instance/texture limits, finite numeric validation and material/node allowlists are enforced before loading. Trusted shader variants are reconstructed locally. Compressed frames have decompression limits and revision/hash validation. SHA-256 here detects mismatches; it is not a digital signature identifying the presenter. |
| Publication privacy | Job and native publishers check document, selection/context and publication generations. Private job inspection retains the last public scene. A native stop clears simulation visuals before export. Guest packets contain prepared render data, not editor/backend API access. Render data still discloses visible scientific content, labels, annotations and title; clip metadata includes job/source information. |
| Lifecycle and performance | Live frames coalesce to the newest absolute frame, requests and decompression are bounded, obsolete revisions are rejected, guest views dispose their geometry/material resources, and timers/listeners are removed. The WSL streaming bridge uses a bounded queue and one subprocess rather than spawning per frame. |
| Process and file handling | Launcher/bridge use argument arrays rather than shell interpolation; control and temporary package files request restrictive permissions, and temporary upload directories are removed. POSIX mode flags do not establish Windows ACL isolation; local OS account permissions remain part of the trust boundary. |
| Revocation | Ending an invitation deletes its room and closes its streams; host expiry/stop clears every room. It cannot erase data a guest has already downloaded, saved, or captured. |

## Academic and business network considerations

- Internet sharing uses **Tailscale Funnel over HTTPS on port 443**. Guests use a
  normal browser without a Tailscale account or client. The host needs Tailscale
  and authorization to enable Funnel. Funnel is a **public internet endpoint**,
  protected here by NADOC's invitation/password, not by an institutional SSO login
  or tailnet membership. Tailscale documents HTTPS-only service, supported ports,
  and non-configurable bandwidth limits in its [Funnel documentation](https://tailscale.com/docs/features/tailscale-funnel).
- Institution-managed DNS, web filters, TLS inspection or endpoint policies may
  block `*.ts.net`, tunneling software, or long-lived event streams. Port 443 alone
  does not guarantee access. The host's exact sharing hostname and outbound
  Tailscale access should be reviewed with institutional IT where required; do not
  expose the Vite editor/API or disable network protections to work around a block.
  Tailscale's [firewall guidance](https://tailscale.com/docs/reference/faq/firewall-ports)
  describes its host connectivity requirements.
- Server-sent events carry live state. The server sends heartbeats and disables
  proxy buffering via `X-Accel-Buffering`, but intermediaries can ignore that hint.
  Reconnect is supported; there is no complete polling replacement for blocked or
  buffered event streams. Test a real guest on the intended network before a
  presentation. No campus/business firewall or TLS-inspection appliance was tested
  in this audit.
- The optional legacy **LAN host is plain HTTP** and does not require the generated
  internet password. Do not use it for confidential content on shared campus or
  business networks. Use the HTTPS sharing path or an institution-approved deployment.
- Invites use URL fragments, avoiding normal HTTP request/referrer logging, but
  the complete link can still be copied into chat archives, browser history,
  managed-browser telemetry, or screenshots. “Copy invitation” intentionally
  includes both link and password; forwarding it forwards access. A display name
  is self-asserted, not verified identity. Separate password delivery can reduce
  accidental forwarding but does not add SSO/MFA or recipient-specific revocation.
- Public invitation access is not automatically suitable for unpublished,
  confidential, contractual, export-controlled, or regulated research data. The
  remaining product needs for those deployments include institution-approved
  hosting, verified identity/SSO, participant-level revocation and audit retention.
  Existing sharing does not implement those controls.

## Further engineering opportunities (not implemented here)

1. **Proxy compatibility:** bounded status-based fallback for scene/camera updates
   when an event stream is silently buffered; exercise this with an actual proxy.
2. **Large scenes:** metadata-only updates for selections, pings, annotations and
   toggles where possible. Native changes currently republish a complete package,
   which can dominate latency under Funnel's bandwidth limits. Preserve snapshot
   revision/privacy guards when introducing a separate metadata channel.
3. **Render CPU:** shared annotations currently update world matrices and collect
   target vectors per annotation per frame. Batch this work and reuse buffers for
   large annotated scenes, with a benchmark before changing projection behavior.
4. **Public resource isolation:** serve/preload only the viewer's build dependency
   graph, instead of all permitted assets in `dist/assets`. Current exact asset
   lookup excludes arbitrary filesystem paths and source maps, but also loads and
   serves unused editor bundles. Do not package secrets in frontend assets.
5. **Abuse resilience:** global join rate limiting deliberately avoids trusting
   forwarded IP headers. An attacker who knows a room ID can consume that shared
   allowance. Per-session stream/download caps do not prevent volumetric attacks;
   a managed deployment needs trusted proxy-aware limits and upstream protection.
6. **Maintenance:** the host still repeats bounded request-body parsing in several
   routes. A shared reader with explicit limits and abort handling would reduce
   drift; keep API-specific response codes and stream backpressure behavior tested.

## Validation

- 132 viewer/selection unit tests passed, including compatibility requirements and
  non-overlapping guest status polling.
- 24 host/transport/room tests passed, including cookie rotation, invalidation of
  previous cookies/streams, per-session stream limits, expiry of an open stream,
  origin/role checks, room isolation, and trajectory/live-frame validation.
- Production build passed (existing bundle-size warning remains).
- Full `npm audit` and `npm audit --omit=dev`: zero known vulnerabilities.
- Chromium menu/publication regression passed: File → Sharing opens beneath
  Workspace Hub; updating across parts preserves the invitation and guest session.
  Test servers and generated workspace artifacts were cleaned up.
