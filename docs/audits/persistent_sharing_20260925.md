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
