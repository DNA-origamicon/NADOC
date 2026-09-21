# Temporary LAN invite prototype — 2026-09-20

The standalone production viewer can now open a single prepared snapshot from an
expiring invite link, after display-name entry. This is independent static
navigation, not the shared-highlight/presenter-follow phase. The host process is
separate from NADOC's Python/editor servers and exposes only built assets and the
selected package. No scientific/topology code changed; `main.js` delta for this
step is zero.

## Verified

- Node HTTP host test passes: unauthenticated package denial, invalid invites,
  cross-origin join denial, name validation, four-browser session capacity,
  cookie reuse, exact static route surface, no-store headers, expiry, and stop.
- Production Playwright host test passes: name prompt, automatic package loading,
  actual pointer orbit, performance dialog, no editor API requests, and visible
  disconnect status after host shutdown. An initial screenshot comparison under
  concurrent unit-suite load did not observe camera movement; the isolated rerun
  passed. This is functional evidence, not an FPS result.
- Voltron export/open app check passes again: 22,629,044-byte package and identical
  800 × 600 editor/viewer images, zero editor API requests in the viewer.
- Full frontend suite: 477 files / 6,688 tests passed.
- Stateful smoke suite: 23 passed, including console-error and teardown gates.
- Production build and `just lint` passed; existing large-chunk warning remains.

The LAN review artifact is retained at
`/tmp/nadoc-lan-test-20260920/VoltronCoreArmV2.nadocview` for the requested second
laptop test. Its display title was changed to `VoltronCoreArmV2 (test snapshot)`;
no scene arrays were changed. Result: 22,629,052 bytes, SHA-256
`0cddd374c24c9d0c93c7a4f2596d11be992006966534a1fede844b97d9c1380d`.
Its source-document hash still refers to the isolated test copy. It is not a
recorded simulation package. Remove the retained package after laptop acceptance.

## Broader backend validation limitations

`just test-smart` selected `FAST` (the changed-since-last-full scope includes
unrelated historical files). Results: **8,789 passed, 7 skipped, 7 failed**.
All seven failures are in `tests/test_photoproduct_review.py`, whose fixture copies
missing evidence from `/media/jojo/Archive/NADOC_archive/photoproduct_evidence/`.
Those files/tests were not changed for this viewer work. The command also failed
its timing guard because the adsorption packing test took 5.16 seconds while the
large SwiftShader browser run was competing for CPU.

The selector reported verbatim:

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
Ask the user to run `just test-session` (their terminal), then `just test-slow`.
```

The repository slow-test triage workflow was applied. The offender builds and
compares two deterministic 31-protein coatings plus atom-cloud clash checks; it
does not launch a simulation. An isolated `just test-file tests/test_streptavidin.py`
passed all 10 tests, with the offender at 3.96 seconds and no budget violations
(14-second guarded command). No test was relegated and no guard/budget was changed:
this run establishes that the observed overrun is sensitive to concurrent load.
The full backend suite remains unverified because its external evidence is absent.

## Network boundary

The first Windows listener returned HTTP 200 locally at `192.168.0.15:5182`, but
WSL-to-Windows LAN access timed out. The unelevated shell could not administer
Windows Firewall. The optional PowerShell launcher requests one narrowly scoped
local-subnet rule for the Node program, port, and interface and removes it in
`finally`; this requires the user's Windows administrator approval. No router
forwarding, persistent service, or internet tunnel is configured.

The LAN transport is unencrypted HTTP and only intended for the user's trusted
network. The invite is a bearer secret, not verified user identity. Real laptop
reachability, GPU performance and browser/OS compatibility remain separate checks.
Already downloaded views remain local after the process stops.
