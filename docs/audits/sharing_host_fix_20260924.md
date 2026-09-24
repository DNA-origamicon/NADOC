# Sharing startup correction — 2026-09-24

The default two-computer launcher uses a private HTTPS Tailscale editor origin,
but the sharing middleware admitted only localhost. Status polling hid the 403
behind a generic offline hint. This checkout also lacked frontend/dist/viewer.html,
and existing private Tailscale listeners occupied 443 and 8443.

Corrections:
- Admit only the exact NADOC_PUBLIC_URL HTTPS Tailscale origin configured by the
  launcher through the loopback proxy. Retain origin, host, custom-header and
  cross-site checks; arbitrary tailnet hosts remain rejected.
- Surface actual status errors instead of masking them as an offline host.
- Build missing guest assets on the first hosting request.
- Select the first free supported public port, including foreground listeners;
  readiness checks and the Funnel process use that selected port.
  Port availability follows https://tailscale.com/docs/features/tailscale-funnel.

Validation: production build passed; 7,044 frontend tests passed (1 skipped);
8 middleware/port-selection tests passed. Live startup from the configured private
editor origin succeeded using 10000 without changing the existing private routes.
A real browser imported a temporary copy of workspace/24hb_0xT.nadoc, created its
invitation through the sharing UI, and joined the actual HTTPS guest viewer with
its generated password. Browser run: 1 passed in 25.7s. This exercised the HTTPS
URL from this workstation, not from an independent off-tailnet guest device.
The temporary invitation was revoked in afterEach; test artifacts and the isolated
Vite bridge were checked absent. The empty real hosting session remains ready for
the user's invitation and expires automatically. Source design was not edited.
Logs and the one-off browser check are retained under
.development-artifacts/sharing-host-fix-20260924/; no credentials retained there.
