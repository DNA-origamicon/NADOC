# S43 — sealed desktop campaign after foreground admission corrections

Parent FH-20, supporting FH-27/FH-28. HEAD `96ab701e`; startup handoff and current
source agree that S41/S42 are delivered. No unrelated changes removed, production
behavior changed, gates enabled or scientific constants/goldens modified.

The campaign uses the existing sealed browser spec with all lifecycle/console
assertions and time/resource limits intact. Only failure diagnostics changed:
relative request timestamps and compact canonical/browser revision, history/redo,
geometry count, private-root count and panel text at failure. Diagnostic checkpoint
requests have a three-second timeout; panel text is limited to800 characters.

## Invocation evidence

Command for each serialized invocation:

```text
NADOC_HISTORY_E2E_SEALED=1 just validate-safe uv run python scripts/run_deformation_history_e2e.py
```

Invocation1: root `/tmp/__e2e__history-fvjdyibn`, Bend40.3s and Twist39.2s failed.
Both pass initial adoption/readiness, Open/edit, Cancel, exact canonical/browser
preservation and private-root removal, then reopen/edit and receive Apply200.
Both fail the existing five-second popup-not-visible assertion. Bend's response
window includes Apply200/status200/design200; Twist additionally receives
geometry200/revision200/status200/cancel200. These responses alone do not prove
successful final adoption, geometry equality, proof or console acceptance: those
later assertions were not reached. Console records genuine403 and429 failures.

Source inspection locates the remaining refresh path in
`deformation_preview_endpoints.refreshCommitted`: status, design, geometry,
revision, status, then controller adoption and editor teardown. This is a lead
for bounded investigation, not a proven root cause of the retained popup.

## Scope and retained debt

No assertion, timeout, worker cap or resource budget was weakened. No production
fix was made. Console errors are retained; unsupported startup403s and background
429s remain separate unresolved obligations. No pytest, Vitest, broad suite or
scientific test was run. Node syntax, selector/debt and current-record checks are
recorded at closeout. main.js LOC Δ0.

The fixed milestone exits remain open:21/38 Done,17 remaining (8 core,9 parked),
delta+0/+0; U1–U60 unchanged. ISSUE-100/MV-48 remain open. No external permission
blocker, commit/push or milestone closure. The explicit goal remains active.

Invocation2: root `/tmp/__e2e__history-hh5v57x4`, Bend60s and Twist46.5s failed.
Bend completes initial adoption and readiness-query removal, then cannot click
Feature Log because `.toast[role=status]` repeatedly intercepts pointer events.
The test times out at60s; diagnostic evaluation then refuses because the page is
already closed. No Open/Cancel/Apply result is claimed for that execution.

Twist again passes Open/edit/Cancel preservation and receives Apply200, then fails
the five-second popup-close assertion. Relative response timestamps:

| Response | Milliseconds after case start |
|---|---:|
| Apply200 | 42156 |
| First receipt status200 | 42247 |
| Design200 | 44320 |
| Geometry200 | 46187 |
| Revision200 | 47519 |
| Final receipt status200 | 47613 |
| Cleanup cancel200 | 47892 |

The final receipt check arrives5.457s after Apply. Later failure diagnostic at
48943ms reports browser/canonical revision2,84 geometry points,history1,redo0 and
privateRoots0. This snapshot happens after the failed assertion; it cannot turn
that failure into a pass or establish exact geometry/proof equality. The snapshot
also does not by itself prove popup closure. No timeout was raised. Genuine403/429
console errors remain; the final empty-console assertion is not reached.

Campaign total: **zero passes/four failures**, cap exhausted. S44 is the sole
unstarted successor: correct and qualify coherent receipt-bound sealed refresh
latency through the existing projection/consumer seam. See the
[handoff contract](session_handoff.md#next-bounded-task). Toast interference and
unsupported/background calls remain separate later obligations.

## Checks and cleanup

- Storage preflight passes on `/tmp`,661GiB free; installed browser read-only.
  Before each invocation, workspace/project/log files, browser profiles/downloads,
  Vite/tool caches and Playwright output were inventoried under its fresh root.
  Screenshots/traces/video stayed off. Fixture close runs in test finally;
  launcher finally stops owned processes and removes the complete root.
- Both printed roots independently confirmed absent. No accessible process has
  either root marker (31 protected/exited environments unreadable). Ports8004 and
  5177 have no listeners and accept SO_REUSEADDR server binds. No owned fixture
  data remains outside the removed roots; user workspace was never selected.
- Node syntax check passes for changed spec. `just lint` passes; `just lint-memory`
  reports zero errors/zero warnings. Diff check passes;332 current-document/affected
  paragraph links resolve. Ledger independently counts21/38 Done and60 U rows.
  Four production gates remain false. No broad/backend/frontend suite was executed.
- `just test-smart --dry-run` selects FULL from accumulated main.py changes then
  FAST fallback, executing zero tests. It does not establish a FAST pass. Existing19
  historical timing candidates and prior triage remain unchanged. Verbatim debt:

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
Only request `just test-session` when a broad/full sweep is actually needed.
```

After all invocation/selector handles completed, `/proc` cwd/open-file/mapping
checks found zero accessible references to the three owned logs and temporary
record-update script (31 protected/exited processes unreadable). Removed73,122
bytes and independently verified all four paths absent. Raw browser roots were
already removed by the launcher; compact evidence above is retained. No cleanup
claim relies only on a passing test body.

Handoff, implementation/acceptance plans, fixed ledger, project memory and current
ISSUE-100/MV-48 paragraphs agree: S43 campaign complete, desktop acceptance
incomplete, S44 sole unstarted successor. No successor implementation began.
