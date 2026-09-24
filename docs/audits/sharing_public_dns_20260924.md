# Sharing public DNS failure — 2026-09-24

Affected hostname: compy5000.tailb6f5b9.ts.net; HTTPS port 10000.
The real 24hb_0xT invitation remains in the active host; no invitation token or
password is recorded here. No private Tailscale routes were changed.

At approximately 17:52–17:55 UTC:
- Host status: running, correct foreground Funnel to loopback 5183, AllowFunnel true.
- Tailscale capabilities include funnel/https and ports 443,8443,10000.
- ShieldsUp false; no current health warnings; tailnet lock disabled.
- Local private DNS resolves to 100.89.83.24, explaining the prior browser pass.
- Google and Cloudflare public DoH return Status 3 (NXDOMAIN), A and AAAA.
- Direct queries to all four ns[1-4].dnsimple.com servers return authoritative
  NXDOMAIN. This is not merely a cached error in the guest browser.
- HTTPS requests to each known public ingress address (199.38.181.54 and
  209.177.145.137), using curl --resolve for this exact hostname and port,
  return HTTP 200 for /viewer.html with normal TLS verification enabled.
  These are diagnostic overrides only, not a proposed guest URL or hosts-file fix.

The public gateway/application path works when DNS is bypassed. The remaining
failure is public DNS publication. Last host restart was 17:47:33 UTC.
Tailscale documents up to ten minutes for initial public DNS publication:
https://tailscale.com/docs/features/tailscale-funnel
A similar authoritative NXDOMAIN symptom has been reported upstream, although
that report involved a device rename not established here:
https://github.com/tailscale/tailscale/issues/21156

Final check after ten minutes (2026-09-24T17:57:49.899323+00:00): both public resolvers still returned NXDOMAIN. Public sharing remains blocked by provider DNS publication.

Follow-up: public DNS later returned both public relay addresses. The new setup routine and real public browser checks passed; see sharing_setup_20260924.md. The host requires no guest VPN.
