# S44 — coherent sealed publication refresh

Parent FH-20 desktop/latency acceptance, supporting FH-27/FH-28. HEAD remains
`96ab701e`; current handoff and S43 timing evidence match source. Existing dirty
changes are preserved. No scientific constants/goldens, production gates, worker
counts, resource/time limits, storage or lifecycle owners changed.

## Correction

The existing sealed GET/design accepts the closed opt-in query
`include_geometry=true`. Its internal `design-display` worker operation decodes
one captured revision and returns the existing full design projection plus the
same native geometry/straight-position projection. Both share one worker,
admission, source/policy/session check, five-second deadline and combined
2,000,000-byte/200,000-node display allowance. The internal operation is not a new
HTTP path. Default GET/design and GET/geometry retain their prior contracts.
Malformed, repeated or misplaced query parameters refuse explicitly.

The existing preview refresh adapter requests that opt-in. When inline geometry
is present, it validates completeness and design identity and skips the separate
geometry GET; malformed inline data refuses without fallback. Legacy ordinary
GET/design ignores the optional query and keeps the existing separate geometry
request. Both receipt/session checks and the revision read remain, as does the
controller's final local document/epoch check before canonical adoption. No cache,
parallel worker, new authority or polling/error suppression was introduced.

Tests independently compare combined native Bend/Twist output with the existing
separate projections, assert one worker and unchanged canonical state, and verify
cleanup. A combined-budget case proves that packets fitting separately can refuse
as one combined response; resource limits remain fixed. Initial test calculation
omitted the existing graph-memory accounting and produced one failed assertion;
the test calculation was corrected, not the production budget.

Browser spec adds compact Apply-to-adoption timing and a final-state/geometry/proof
milestone log. Assertions and deadlines are unchanged. main.js LOC Δ0.

## Validation and remaining scope

Actual checks, browser verdict, cleanup and sole successor are recorded at closeout
below. This correction alone does not qualify desktop console/startup behavior or
close FH-20. Unsupported startup403s/background429s and toast interference remain
outside this task. No commit/push, rollout enablement or legacy pruning.

## Executed validation (closeout October18)

- Backend: initial full display-reader file30 passed/1 failed in26.67s (test-only
  budget calculation described above). Corrected combined selection7 passed,
  24 deselected in10.27s. Added combined inflight revision/policy/cancel selection:
  3 passed,31 deselected in2.96s. **34 distinct cases pass across these runs**;
  this is not a claim of a new34-case single invocation. Each used guarded
  `TMPDIR=/tmp/nadoc-s44-nzTrGe just test-focused tests/test_part_immutable_display_reads.py`
  with `-k combined` or `-k combined_inflight` for the selections.
- `TMPDIR=/tmp/nadoc-s44-nzTrGe just test-frontend`: **9287 passed,1 skipped across
  771 files**,351.95s. New/ordinary preview transport tests:35 pass within that run.
  Existing ORJSONResponse deprecation and frontend diagnostic warnings retained.
- `just lint` and Node spec syntax pass; memory lint and link/count/diff checks
  recorded below. No broad backend suite, scientific run or production rollout.

Two serialized app invocations used the unchanged guarded sealed command:
`NADOC_HISTORY_E2E_SEALED=1 just validate-safe uv run python scripts/run_deformation_history_e2e.py`.

| Invocation/root | Case | Result |
|---|---|---|
|1 `/tmp/__e2e__history-1uedw076`|Bend40.3s|Cancel preservation passes; popup closes and revision adopts in4636ms after Apply. Later geometry/proof HTTP-success boolean fails; exact status was not captured.|
|1|Twist60s|Toast intercepts Feature Log click before Open.|
|2 `/tmp/__e2e__history-dqbm38dr`|Bend60s|Toast blocks an Open/edit/Cancel-stage click; pending response wait also times out. No Apply timing obtained.|
|2|Twist20.8s|Open429: `{"detail":"A part history operation is already running"}`. Diagnostic revision1/history0/redo1/privateRoots0.|

**Zero passes/four failed executions.** First Bend's later diagnostic confirms
browser/canonical revision2,84 geometry points,history1,redo0/privateRoots0.
No final native geometry equality/proof/empty-console pass is claimed. The final
HTTP diagnostics added before invocation2 were not reached there; do not invent
the status of invocation1's late failure. Genuine403/429 console errors remain.

S44 is **partial for desktop qualification**: combined projection/transport is
delivered and tested; Bend meets the five-second adoption assertion once, but
Twist timing and complete desktop acceptance remain unqualified. The next bounded
S45 addresses passive polling versus foreground history admission. Readiness is
still a foreground read in current source, but no browser holder instrumentation
proves it caused the observed Open429. S45 must reproduce the actual conflict.
Full successor: [current handoff](session_handoff.md#next-bounded-task). Startup
capability/403 qualification and toast behavior remain separate later obligations.

ISSUE-100/MV-48 remain open.21/38 Done,17 remaining (8 core,9 parked), delta+0/+0;
U1–U60 unchanged. No new major checkpoint or milestone closure. No permission
blocker; the explicit milestone goal remains active.

## Final checks and cleanup

Repository-wide lint passes; memory lint reports zero errors/zero warnings. Node
spec syntax and diff checks pass.334 local links across current task documents
and affected issue/manual paragraphs resolve; counts independently match21/38 Done
and60 U rows. All four production gates remain false. main.js Δ0.

Storage preflight passes on `/tmp` with661GiB free. Each browser invocation's full
writable inventory (workspace/project/logs, profiles/downloads, caches and
Playwright output) stayed under its fresh launcher root, with screenshots/traces/
video off. Both roots independently verified absent, no accessible marked process
remained and ports8004/5177 had no listeners and accepted server-style binds.
Final scan had31 protected/exited environments unreadable (first check32).

Focused/backend/frontend logs and scratch used `/tmp/nadoc-s44-nzTrGe`. After all
handles completed, `/proc` cwd/open-file/mapping inspection found zero accessible
references (31 protected/exited processes unreadable); runtime source/configuration
had no dependency on that root. Removed615,406 bytes and independently confirmed
the root absent. Unrelated scratch, installed runtimes and user data preserved.

`just test-smart --dry-run` routes FULL from accumulated main.py changes and prints
FAST fallback while executing zero tests. It establishes no FAST pass. Existing19
historical slow candidates/prior triage and failed broad debt remain unchanged.
Verbatim debt:

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
Only request `just test-session` when a broad/full sweep is actually needed.
```

Handoff, implementation/acceptance plans, milestone ledger, project memory and
ISSUE-100/MV-48 current paragraphs agree on S44's partial desktop qualification
and S45 as the sole unstarted successor. No successor implementation began.
