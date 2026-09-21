# Help → Share link checkpoint — 2026-09-20

Implemented a local editor dialog that captures the current visible part/view,
starts a temporary host if necessary, and provides Copy link, Open viewer,
Stop sharing, and Stop hosting all links. Each capture has a distinct immutable
snapshot, room identifier, invite token, cookie namespace and expiry. Opening a
second part does not change the first link's package. Limits: eight snapshots /
512 MiB total, four browser sessions per link, two-hour host lifetime.

`main.js` change for this step is +2 lines: one import and one factory init,
with the existing export factory result retained for reuse. No Python/scientific
geometry implementation or source design was changed.

## Verification

- Full frontend suite: 478 files, **6,691 passed**.
- Final stateful smoke suite: **23 passed**, including console-error and teardown
  gates. Final workspace/project inventory again matched preflight; disposable
  Playwright output was removed and the isolated share credential was absent.
- Node host/middleware tests: **3 passed**, covering invite protection, exact file
  routes, same-origin/local-host controls, capacity, cookie/snapshot isolation,
  independent revocation, expiry, and shutdown.
- Actual isolated editor/guest app test: **passed**. Uses Help → Share link,
  exports alpha and beta native test parts, clicks Copy link and reads the actual
  clipboard, opens each in a guest browser, checks the correct part, revokes beta,
  confirms alpha still opens, and stops the host. No page errors in guests or
  unexpected editor console errors. Source/test files are in
  `frontend/e2e/share_link.spec.js`.
- Production build and `just lint` passed; existing bundle-size warning remains.

The first app run exposed a real invite-navigation bug: changing only the fragment
in an already-open viewer tab did not reinitialize its join flow. The viewer now
handles hash changes, and canonical copied links also include a non-secret query
identifier so different parts cause a normal page navigation. The regression has
both a unit test and the passing two-part app exercise.

## Native Windows / WSL boundary

The approved Windows host initially accepted TCP but did not answer HTTP while
its native output was attached to the elevated interactive/transcript console.
Running the same code with captured output responded normally. The PowerShell
launcher now redirects Node output to local log files and waits for the child,
keeping the event loop independent of console interaction. Its scoped firewall
rule is removed in `finally` when the host exits. Force-killing the entire
launcher can skip that cleanup; no guest access remains without a listener.

A WSL request to the Windows physical LAN address still timed out even after the
scoped rule, while native Windows HTTP worked. Editor control requests therefore
use a local Windows Node subprocess and file-only credential. Any binary upload
uses a mode-0600 file in a private temporary directory and is removed in `finally`.
The guest firewall rule is not widened to admit WSL NAT. Windows UNC creates new
files with default permissions, so the launcher pre-creates the credential with
mode 0600; the running file's mode was checked. The credential is never returned
to the editor browser or guest. Browser-origin requests cannot use the host's
management API.

Native verification: the Windows listener answers HTTP, local editor status
reports the running host, and a 22,629,052-byte Voltron test package was published
through the actual editor-control transport. One part-specific Voltron link is
retained in the active host for the user's laptop test. The guest link/token are
not committed to this record. The artifact originates from the prior read-only
Voltron round-trip and has only a changed display title; its source hash is still
the isolated test copy's hash.

Real laptop reachability, browser/OS compatibility, and GPU performance remain
manual acceptance checks. This checkpoint is trusted-LAN HTTP, not encrypted
remote hosting, shared presenter highlights, or recorded trajectories. The active
Windows host retains its startup build; newly created links carry query identity
for compatibility with that build. A fresh host loads the latest build.

## Artifact ownership

Playwright owns the isolated :8001/:5174 servers. Its test part names use the
`__e2e__` prefix and existing teardown removes parts/project stores. The share
spec owns an isolated :5174 control file and removes it in `afterAll`. Temporary
Node host tests and WSL upload directories have failure-safe cleanup.

After the two-part check, project-entry inventory matched preflight, no new
prefixed workspace artifacts or upload directories remained, and the isolated
control file was absent. The Voltron source SHA-256 remained
`f0c03351c3962b6a50ae96e7e8cfb5e6722701572be36d9aca3b85df066148f6`.
The user-requested active host/control logs and previous LAN snapshot are retained
outside the workspace under `/tmp` for this meeting/test only. User editor servers
on 8000/5173 remain running. No commit or push was requested for this step.

## Broader backend gate

`just test-smart` decision: **FAST (fast suite only)**. Result: **8,789 passed,
7 skipped, 7 failed** in 102.73 seconds. The same seven
`tests/test_photoproduct_review.py` failures require external archive evidence
absent on this PC; none belongs to the viewer implementation. The selector's
message is retained verbatim:

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
Ask the user to run `just test-session` (their terminal), then `just test-slow`.
```

The guard also reported `FAST SUITE TOO SLOW`: 107-second command versus the
90-second aggregate backstop. Slow-test triage found **zero per-test violators**
across 8,803 tests; the slowest was the existing streptavidin adsorption packing
check at 4.49 seconds (below the 5-second limit), followed by its biotin case at
3.68 seconds. The pattern spans existing geometry/review/assembly tests, not a
new shared fixture or native host probe from this work. Following the triage
skill's aggregate-growth rule, no arbitrary test was relegated, no budget/guard
was weakened, and no gated slow suite or simulation was launched. The broader
backend command is not reported as passing.

## HTTP startup correction (ISSUE-31)

The user's LAN browser exposed a gap in the original checks: HTTP localhost is a
trustworthy origin, but an ordinary LAN address is not. The optional performance
automation bridge called `crypto.randomUUID()` before checking whether automation
was needed, crashing the whole viewer where that API was unavailable. The bridge
now remains inactive without that capability; manual capture does not require it.

The prepared-host Playwright configuration now includes `chromium-lan-http`, using
`http://nadoc-lan.test` mapped to loopback strictly for isolated test transport.
The browser itself confirms `isSecureContext === false` and both
`crypto.randomUUID` and `crypto.subtle` are undefined. It then joins, loads the
scene, orbits, resets, completes a one-second manual capture and obtains metrics.
Both insecure and localhost production projects passed. Full frontend suite:
478 files / 6,692 tests passed. No `main.js` changes for this fix. Software timings
remain functional evidence, not GPU performance acceptance.

The active host freezes built assets in memory. Applying the corrected build
therefore requires a host restart and a replacement invite. The repair reuses the
same retained Voltron snapshot and requests only the remaining meeting lifetime.

Final HTTP-fix checks: **23 smoke tests passed**, production build and lint passed.
The Windows host was restarted with the same snapshot and approximately its
original expiry (20:47 Denver time); the old invite was revoked and a replacement
was issued. Native Windows HTTP fetched the running host's HTML and all five
referenced assets and found byte-for-byte matches with the corrected production
build. The non-secret deployment hashes are in `http_fix_deployment.json`.
Workspace/project inventory remained unchanged, browser-host/upload temporary
directories were absent, and disposable Playwright output was removed. Only the
user-requested meeting artifacts remain under `/tmp`.
