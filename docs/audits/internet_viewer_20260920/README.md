# Internet prepared-viewer checkpoint — 2026-09-20

Intent: guests on unrelated networks open an ordinary HTTPS invitation, enter a
name/password, and navigate without an installation, account, certificate warning,
file picker, or network configuration. Host setup is separate from guest entry.

## Implemented and verified

- Public guest listener and separate local management listener; the public route
  cannot reach `/host/*`, the editor, workspace files or simulation APIs.
- Per-snapshot 96-bit random password plus 256-bit invitation token. Passwords do
  not appear in URLs. Secure/HttpOnly/SameSite cookies, exact HTTPS join origin,
  bounded join attempts, snapshot revocation and host lifetime.
- Help-menu internet wording and **Copy invitation** with link/password/instructions.
- Native Windows background helper (no visible console, no elevation or incoming
  firewall change). Foreground Funnel lifecycle preserves unrelated provider routes.
- Owner approved Funnel. Actual helper start/stop/restart verified: stopping removes
  its foreground public route and both loopback listeners, while private editor
  port 5173 remains unchanged. Private credential/invitation artifacts have mode600.
- Full frontend: **478 files / 6,694 tests passed**.
- Node host/control/provider checks: **6 passed**.
- Production HTTPS browser fixture: **1 passed**; wrong password blocks the scene,
  correct password loads, pointer orbit changes pixels, cookie flags verified, no
  browser/download dialogs or page errors, and disconnect indicator works. The
  fixture's self-signed certificate exception applies only to this isolated test.
- Actual Help copy/share/revoke regression: **1 passed**.
- Stateful app smoke: **23 passed**. Build, Ruff lint and diff whitespace check pass.
- main.js delta for this step: **0 lines**.

## Broader backend check limitations

`just test-smart` selected **FAST (fast suite only)**: 8,789 passed, 7 skipped,
7 failed. All seven failures are unchanged photoproduct review tests requiring
absent `/media/jojo/Archive/NADOC_archive/photoproduct_evidence/...` source archives.
No photoproduct files were modified by this work.

Deferred output, verbatim:

```
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
Ask the user to run `just test-session` (their terminal), then `just test-slow`.
```

The aggregate guard reported 120s >90s. Following the triage-slow-tests skill,
inspected `.nadoc-slow-candidates.json`: zero individual budget violators, slowest
existing streptavidin test 4.62s. These viewer changes add no Python tests or shared
fixtures; no newly introduced broad probe/fixture cost was identified. No budgets,
markers or guards were changed, and no slow suite or simulation was launched.

## Artifacts and remaining acceptance

Preflight inventory: `/tmp/nadoc-internet-preflight.json`. After browser tests,
workspace, project, session and Playwright workspace inventories match exactly;
no temporary share-upload or isolated internet/share test directories remain.
Routine logs are `/tmp/nadoc-internet-*.log`. No host credential, guest password or
invitation token is retained in this audit.

The reusable 22.6 MB Voltron package remains outside the user workspace at
`/tmp/nadoc-lan-test-20260920/VoltronCoreArmV2.nadocview` for the laptop test.
The private current invitation is in `/tmp/nadoc-internet-voltron-share.json`.
The public-route browser check passed at 2026-09-21T02:14:17Z. Public DNS was
verified through Google and Cloudflare; browser resolution was deliberately pinned
to public relay 208.111.34.11 rather than private Tailscale DNS. Normal certificate
validation succeeded (no override). The second public relay 208.111.35.209 also
returned HTTPS200 with certificate verification success. See
`public-browser-check.json` and `voltron-public-view.png`.

The browser denied an incorrect password, loaded the complete Voltron snapshot
with the correct password, displayed its 3D model, and produced no page errors or
browser/download prompts. Public admin/editor paths returned404 and unauthenticated
scene access returned401. Whole functional script duration was125s under software
rendering, including retries/screenshots/security checks; this is neither isolated
load latency nor a GPU measurement. A fresh invitation was created afterward and
the automated room revoked so all four guest slots are available. The obsolete
LAN host was stopped through its own management API; its normal launcher cleanup
removes its temporary firewall rule. The pre-existing Node block was not modified.


The software browser checks establish functionality, not real-GPU performance.
Four-guest transfer contention, real laptop GPU/appearance, browser/OS matrix,
shared highlights/jump/follow and recorded cube_pore trajectories remain open.
