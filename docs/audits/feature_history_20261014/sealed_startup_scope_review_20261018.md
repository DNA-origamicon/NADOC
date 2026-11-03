# S47 startup inventory and scope correction — October 18, 2026

Parent: FH-20, supporting FH-27/FH-28. HEAD remains `96ab701e`.
The user clarified that simulation relevance is saved-source freshness. General job
execution, recommendations and job-list UI are outside feature-history scope.

The guarded inventory ran before the runtime draft:
`NADOC_HISTORY_E2E_SEALED=1 just validate-safe uv run python scripts/run_deformation_history_e2e.py`.
Exit1: zero full passes, two failures at the unchanged strict console assertion.
Both fixtures passed Open/Cancel preservation, Apply, final geometry and independent
native proof. Apply-to-adoption: Bend3492ms, Twist3251ms, under the unchanged5s check.
Each fixture recorded37 HTTP403 responses, no429s, across these15 routes:

| HTTP failure | Count per fixture |
|---|---:|
| `403 GET /api/md/setup-presets` | 1 |
| `403 GET /api/oxdna/live/available` | 1 |
| `403 GET /api/oxdna/available` | 2 |
| `403 GET /api/library/files` | 1 |
| `403 GET /api/primitives` | 1 |
| `403 GET /api/vr/status` | 1 |
| `403 GET /api/design/placement-integrity-status` | 2 |
| `403 GET /api/library/disk-usage` | 1 |
| `403 POST /api/design/animations` | 1 |
| `403 GET /api/md/run-dir-status` | 1 |
| `403 GET /api/engines/status` | 1 |
| `403 GET /api/oxdna/jobs` | 2 |
| `403 GET /api/simulate/jobs` | 19 |
| `403 GET /api/simulate/recommendation` | 2 |
| `403 GET /api/md/jobs` | 1 |

The retained spec edit aggregates at most64 distinct failure keys plus overflow.
It changes no console assertion, timeout, geometry comparison or independent proof.
The proposed capability endpoint/helper and simulation, animation, placement and
startup wiring were unvalidated and removed following the user's scope correction.
Seven formerly clean runtime files again match HEAD; client retains only its S46
16-line diff (+14/-2). The new capability helper is deleted. Prior dirty work is
preserved. This is a diagnostic/scope decision, not delivered capability support.

Full desktop acceptance remains failed; no console errors are filtered. No new full
frontend/backend/smoke suite was run for this diagnostic-only final change. S46
passes are historical. Existing broad FULL debt remains. No scientific changes,
production simulations, commits, pushes or gate enablement.

S48 is the sole unstarted successor: one historical Bend edit with downstream
Sweep, complete geometry comparison against independent cold replay and source/
history preservation. See the handoff for deliverables, checks and stop condition.
Counts remain21/38 Done,17 remaining (8 core9 parked), delta0; U1–U60 unchanged.
FH-20/FH-28 stay growth flagged; ISSUE-100/MV-48 remain open.

Final syntax, lint, link, rollback and cleanup results are recorded below.

Final checks: `node --check frontend/e2e/sealed_history.spec.js`, `just lint`,
`just lint-memory` (0 errors/0 warnings), and `git diff --check` pass.
Seven runtime rollback files match HEAD byte-for-byte; client retains S46's +14/-2
diff. All current S47 evidence links resolve and seven records select S48.
The broader eight-record scan found 397 existing local targets and 19
missing historical targets; these are not new S47 links and are not repaired here.
- Historical missing target in `issues_ledger.md`: `.development-artifacts/benchy_20261005/Benchy_v4_initial_invalid.nadoc`.
- Historical missing target in `issues_ledger.md`: `.development-artifacts/benchy_20261005/cluster_bug_evidence.json`.
- Historical missing target in `issues_ledger.md`: `.development-artifacts/benchy_20261005/native_model_validation.json`.
- Historical missing target in `issues_ledger.md`: `.development-artifacts/benchy_20261005/cluster_bug_evidence.json`.
- Historical missing target in `issues_ledger.md`: `.development-artifacts/benchy_20261005/build.log`.
- Historical missing target in `issues_ledger.md`: `.development-artifacts/benchy_20261005/native_model_validation.json`.
- Historical missing target in `issues_ledger.md`: `.development-artifacts/benchy_20261005/native_model_views.png`.
- Historical missing target in `issues_ledger.md`: `.development-artifacts/benchy_20261005/Benchy_v4_candidate.provenance.json`.
- Historical missing target in `issues_ledger.md`: `.development-artifacts/vr-output-capture-20261012/normal-launch-integration-20261013/launch-handoff.json`.
- Historical missing target in `issues_ledger.md`: `.development-artifacts/vr-output-capture-20261012/normal-launch-integration-20261013/recording-validation/index.html`.
- Historical missing target in `issues_ledger.md`: `.development-artifacts/vr-output-capture-20261012/normal-launch-integration-20261013/recording-validation/postfix-summary.json`.
- Historical missing target in `issues_ledger.md`: `.development-artifacts/vr-output-capture-20261012/normal-launch-integration-20261013/final-config-document-verification.json`.
- Historical missing target in `issues_ledger.md`: `.development-artifacts/vr-output-capture-20261012/normal-launch-integration-20261013/browser-reconnect/verification.json`.
- Historical missing target in `issues_ledger.md`: `.development-artifacts/vr-output-capture-20261012/menu-hover-followup-20261013/native-audit.json`.
- Historical missing target in `issues_ledger.md`: `.development-artifacts/vr-output-capture-20261012/menu-hover-followup-20261013/recording-analysis/identity-follow-summary.json`.
- Historical missing target in `issues_ledger.md`: `.development-artifacts/vr-output-capture-20261012/menu-hover-followup-20261013/native-freeze.json`.
- Historical missing target in `issues_ledger.md`: `.development-artifacts/vr-output-capture-20261012/menu-hover-followup-20261013/interaction-timing-findings.json`.
- Historical missing target in `issues_ledger.md`: `.development-artifacts/vr-output-capture-20261012/menu-hover-followup-20261013/deployment/final-verification.json`.
- Historical missing target in `issues_ledger.md`: `.development-artifacts/vr-output-capture-20261012/menu-hover-followup-20261013/deployment/browser-connected.png`.

Both owned roots (`/tmp/nadoc-s47-xPo32V` and
`/tmp/__e2e__history-pw1s1p2b`) are independently absent. The exact scratch
directory contained only inventory.log and was removed after reference checks:
no accessible cwd/fd/maps/environment references;31 protected/exited processes
unreadable. Ports8004/5177 accept server-style binds. All four gates remain false.
