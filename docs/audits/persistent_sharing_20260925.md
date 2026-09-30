# Persistent local sharing gateway — 2026-09-25

The editor server now prepares its public viewer connection at startup, without
publishing a design. All presentations reuse that one gateway. Enable link
activates a fresh invitation; End presentation revokes guest sessions and releases
shared scene data without closing the connection. Closing/changing the part also
revokes access. Late uploads are revoked instead of being attached to the next part.
Each presentation gets two hours starting at activation, independent of gateway age.
Server restart/shutdown invalidates invitations. If the editor process disappears
abruptly, its detached managed gateway stops after 90 seconds without a heartbeat.

No cloud storage, account purchase, domain change, per-file tunnel, or automatic
file upload was introduced. Stable per-file URLs were not needed for this speedup;
invitations are currently fresh per activation. First connection startup/recovery
still depends on the provider; public DNS/HTTPS checks remain enforced. Missing
host prerequisites are reported in Sharing and retried in the background.

## Verification

- Frontend: 7,055 passed, 1 skipped, 542 files.
- Node host/middleware/public-access regressions: 21 passed. Includes background
  startup before any share request, a gateway idle for 24 simulated hours, fresh
  two-hour room lifetime, expiry delivering a terminal guest event without polling,
  ending/re-enabling on the same gateway, restart invalidation, and owner loss.
- Sharing browser tests: 2 passed, including real editor export, guest rendering,
  End presentation and Close Session revocation, visible selectable link/password
  fields, right-side copy icons, and readiness messaging. Warm second enable for a
  small scaffolded part measured 279 ms and 319 ms across two runs.
- Smoke: 23 passed, including part and assembly teardown.
- Production build passed. `main.js` LOC delta: 0.
- Real public relay Chromium check passed with normal certificate validation and
  public DNS resolution: wrong password denied, correct password rendered the
  synthetic scene, orbit changed pixels, ending access cleared the guest viewer,
  the old room returned 410, and a new presentation used the warm connection.
  Local invitation creation: 4 ms; re-enable: 1 ms. Guest Join-to-visible-scene:
  224 ms / 291 ms. These are small-scene measurements, exclude invitation delivery
  and page navigation, and are not promises for large designs or other networks.
- Cold startup did encounter transient TLS disconnects/timeouts before both relays
  passed. No certificate, DNS, identity, or endpoint-isolation checks were bypassed.

Broader validation remains unsuccessful outside the sharing change:
`just test-smart`: `decision: FAST  (fast suite only)`; 9,130 passed, 9 failed,
91 skipped. Failures concern animation geometry, assembly flatten/simulation,
scadnano photoproducts, oxDNA jobs, and CanDo snapshot reconstruction.

```text
  DEFERRED: this change would have needed the FULL suite, but no test-dedicated
  session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
  Ask the user to run `just test-session` (their terminal), then `just test-slow`.
```

`just lint` reports one unrelated unused `math` import in
`tests/test_cpd_validation_gate.py:2`. These files were not changed for sharing.

Evidence: `.development-artifacts/persistent-sharing-20260925/` contains logs,
artifact inventory, and `sharing-dialog.png` (dummy credentials). Test parts,
isolated host credentials and Playwright output directories were removed. No
new test project snapshots remained; existing test histories dated September
12–22 were preserved. Public diagnostic invitations were revoked in `finally`.

## Persistent design invitations — 2026-09-30

Supersedes the fresh-invitation behavior above. Opening a part or assembly now
allocates a stable invitation on the existing host, without exporting its scene.
The Sharing dialog makes link/password/QR available before presentation preparation.
Presentation → Start (also Start presentation in Sharing) exports and publishes the
current design. Guests see an automatically updating inactive/preparing page until
Start finishes. Copy controls remain usable during preparation. Temporary public
HTTPS failures are shown as retrying progress, not terminal errors.

Stop, document change/close, host restart, and the two-hour session deadline remove
scene data and revoke guest sessions, but preserve invitations. Reset link rotates
address/password/QR and terminates existing access. Unsubmitted guest join forms
also return to the waiting page after Stop. Old cookies cannot access a restarted
presentation. Existing password and guest-only QR authentication remain enforced.

Credentials are stored atomically, owner-readable/writable, outside the editor's
static root in `~/.nadoc/presentation-links-<workspace hash>.json` on the hosting OS.
The map uses separate part/assembly identities, does not modify design files, and
survives host restarts. No always-available service was added: host-off navigation
still produces the browser's connection error. Reusing URLs assumes the same host,
checkout, and public hostname/port. The Windows/WSL command helper carries the new
link routes and identity header; its transport was exercised locally, not on a
fresh Windows installation.

Background allocation respects disabled automatic hosting, returning a pending
state instead of launching the provider on document open. Explicit Sharing/Start
can still initiate setup. Failed persistence preserves the previous invitation.

Validation:

- `just test-frontend`: 580 files passed; 7,308 passed, 1 skipped. Subsequent guest
  waiting/Stop refinements: 38 focused tests passed.
- Host, middleware, persistent registry, and spawn regressions: 21 passed. Includes
  restart persistence, password denial, old-cookie denial, expiry, reset revocation,
  preparation without publication, concurrent allocation, atomic-write failure,
  storage outside the static root, and constrained Windows-helper routing.
- Real Chromium editor/guest tests: 2 passed. Exercised menu Start, pre-Start waiting,
  joining, Stop before and after joining, same-link restart, reset, document close,
  copy/QR/print controls, and connection progress. A small warm restart measured
  257 ms; this is not a general latency guarantee.
- `just smoke`: 23 passed, including assembly exit and Close Session. The first run
  caught background hosting starting when disabled; fixed and rerun successfully.
- Production build and `git diff --check` passed. `main.js` LOC delta: 0.
- Cleanup verified: no test-prefixed workspace files, isolated :5174 sharing-control
  or status file, Playwright output/report directory, or test project stores remain.
  Test histories were removed by global teardown. Raw diagnostic logs are retained
  only in `.development-artifacts/persistent-design-links-20260930/`.

Broader checks are not clean. `just test-smart` selected `decision: FAST  (fast suite
only)`: 9,484 passed, 6 failed, 93 skipped. Failures are in geometry scalar/loop skip
parity, simulated surface probe/field extraction, and fixed-color VR preview controls;
these sources were not changed for sharing. The guard also reported ten tests over
its five-second budget (117 seconds total). The slow-test triage skill and project
parallelization notes were reviewed: mechanisms include native mesh export (10.07 s),
mrDNA model construction (9.12/6.89 s), mocked oxDNA orchestration (8.60 s), cold boto
import (8.31 s), toolchain probing (7.24 s), surface extraction (6.47 s), mocked wheel
interaction (6.26 s), async catalog responsiveness (6.23 s), and mocked NAMD lifecycle
(5.17 s). That run overlapped frontend/browser work; isolated timing triage remains
outstanding. No test markers, budgets, or guards were changed to conceal these results.

```text
  DEFERRED: this change would have needed the FULL suite, but no test-dedicated
  session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
  This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
  Only request `just test-session` when a broad/full sweep is actually needed.
```

The broader Node sweep reported 45 passed and one unchanged failure in
`prepared_room_state.test.mjs`: the test expects immediate disconnection while the
implementation allows bounded draining. `just lint` found one unrelated unused
`pathlib.Path` import in `tests/test_cpd_shape_revision_v2.py:3`.
