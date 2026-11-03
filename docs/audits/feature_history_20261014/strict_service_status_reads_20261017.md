# S33 — Strict desktop session-status reads

October 17, 2026. Delivered against HEAD `96ab701e`; unrelated changes preserved.
Exactly two GETs join strict dispatch: `/api/vr/references` and
`/api/collaboration/peers/status`. No mutation method or neighboring route opens.

## Contract and implementation

`part_strict_service_reads.py` validates closed queries and captures the selected
policy/document session, then rechecks them after bounded response encoding.
It never reads a canonical Design or obtains a publication permit. Existing
strict dispatch owns body/media/method refusal and never falls back to compatibility.
Service reads do not require geometry publication gates or create an empty session.

VR status reuses `vr_references.read_references` and the original `_read_state`
process/host configuration validation. A private optional reader seam bounds the
state/event files; ordinary endpoint behavior is unchanged. Existing localhost/
configured-self-Tailscale and Origin checks remain. Inactive, other-document and
stale-process sessions return the ordinary inactive report; malformed/missing event
content retains ordinary event-null semantics. Oversized/nonregular files refuse
rather than being mislabeled inactive. Cancellation drains the read thread.

Peer-status inspection found a real write: `_probe_peer` repairs a saved Tailscale
URL when an alternate address responds. Strict mode now explicitly selects
`read_only=True` in the same existing service owner. It reports the same effective
address/reachability but does not register it. Ordinary callers still repair the
registry, verified in the same fake-transport test. Cache keys include the mode,
so a strict cached observation cannot bypass a later ordinary repair. Existing
coalescing, eight-second probe deadline, DNS timeout and shared-task ownership
remain. Strict probes stream response headers/status and close without downloading
an unbounded identity body; tokens are neither sent by this reachability probe nor
returned in public status. No live remote peer was contacted during validation.

`service_status_io.StatusReader` reads regular files only with nonblocking open,
closes descriptors on all paths, and applies the existing 8 MiB metadata allowance
cumulatively. Read-only peers admit at most 128 records with exact four-string
fields of at most 4096 characters each. Status output uses the existing 200,000-node/
2,000,000-byte display bound. These are input/output bounds, not a new filesystem
latency guarantee. Host configuration and service owners remain trusted; request
fields cannot select paths, workspace or read-only mode. No new cache/queue/owner.

## Validation actually run

Sequential guarded `just test-focused TARGET` runs: **114 distinct passes**.

| Target | Result | Seconds |
|---|---:|---:|
| `tests/test_part_strict_service_reads.py` | 28 passed | 3.31 |
| `tests/test_collaboration_status.py` | 4 passed | 2.85 |
| `tests/test_vr_references.py` | 8 passed | 2.80 |
| `tests/test_vr_state_publication.py` | 2 passed | 2.72 |
| `tests/test_part_strict_http.py` | 61 passed | 3.81 |
| `tests/test_project_collaboration_api.py` | 11 passed | 3.21 |

An initial 24-case strict-service run passed in 3.83 s before cancellation and
additional budget coverage. Fixtures use isolated metadata, current test-process
identity and `httpx.MockTransport`, never user sessions or network endpoints.
Coverage includes VR inactive/active/mismatched/stale/event-error states, Origin/
remote-client refusal, peer online/offline/alternate-address results, no secret
exposure or strict registry writes, ordinary repair, cache reuse, cancelled shared
probe ownership, drained VR threads, stale policy/session, closed methods/queries,
oversized file/count/field/output and cumulative/nonregular file refusal.

Changed-file Ruff passes, including the complete touched VR and strict-dispatch
modules. Diff review caught and removed an unintended reader substitution in an
unrelated VR cleanup function; that function is identical to baseline in the final
change. `git diff --check` passes. `just lint-memory`: 0 errors/0 warnings. Current
links, unique 38 milestones/21 Done, 60 engineering rows, issue/manual status and
sole S34 successor checked.

`just test-smart --dry-run` selects FULL for accumulated `main.py` changes, then
FAST fallback without a dedicated session. **Zero broad tests ran.** Nineteen
historical timing candidates remain debt; no new test exceeds the five-second
per-test threshold. Required selector text is boilerplate, not a FAST pass:

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
Only request `just test-session` when a broad/full sweep is actually needed.
```

No browser, full frontend, scientific run or VR hardware qualification. S29's
browser lifecycle remains pending; active-job polling is still refused. Its normal
handler reconciles statuses and can write job metadata, so it must be qualified
explicitly rather than treated as a raw read. No current code admits that endpoint.

## Cleanup and sequencing

Own final pytest roots 5/6/7 were removed after cwd/open-file/memory-map checks:
no accessible references; 31 inaccessible/exited records limit the inspection.
Root5 held 2 files/20 bytes, root6 was empty, root7 held 29 files/12,561 bytes.
Pytest retention removed earlier task roots. Own roots are absent; unrelated
`pytest-0` remains. Disposable logs and documentation script removed after recording
results. No app servers, native viewers or user simulations launched.

**21/38 milestones Done; 17 remaining (8 core,9 parked); delta +0/+0.** U1–U60
remain 60 engineering checkpoints; this adaptation gets no new U number. Fixed
FH-20/FH-27/FH-28 exits and ISSUE-100/MV-48 remain open. All four production gates
remain false; no commit/push. No scientific rules, constants or goldens changed.

**S34**, unstarted, is the sole successor: qualify exactly `/api/jobs/active` with
ordinary status parity and an explicit reconciliation-side-effect boundary.
The [handoff](session_handoff.md#next-bounded-task) defines its objective, parent,
files, acceptance, exclusions and stop condition. No S34 implementation began.
