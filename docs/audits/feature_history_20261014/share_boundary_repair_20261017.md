# S09 isolated history share boundary — October 17, 2026

Delivered: a proven harness configuration repair. Both unchanged tiny native
Bend/Twist browser cases now pass, including the strict empty-console assertion.
No full release acceptance or milestone closure is claimed.

## Reconciliation and fixed scope

HEAD remains `96ab701e`. Read CLAUDE.md, current handoff, project-memory head,
ledger, applicable source/rules and artifact policy. No applicable AGENTS.md found.
Existing dirty S02/S03/S05, scientific exclusions, memory maintenance and unrelated
changes were preserved. Only the test-only Vite configuration, its focused test,
and current tracking records changed. The spec itself, production sharing,
geometry, constants, gates, scientific authorization and test guards are unchanged.
No commit/push, external links, downloads or sharing service was started.

The fixed target was to identify the caller/configuration fault and correct only
a proven harness omission, with at most two diagnostic browser invocations.
Single worker, zero retries, 60-second case budget and all existing assertions stand.

## Cause and correction

`main.js` initializes `initShareLink` with the real store. In
`frontend/src/viewer/share_link.js`, the document-identity subscription invokes
`prepareInvitation` on identity changes (adoption/save); that invokes
`ensureInvitation(false, true)` and POSTs `/__nadoc_share/links` with
`background: true`. Its caught promise rejection does not erase the browser's
HTTP resource error. `NADOC_SHARE_AUTOSTART=0` controls server startup, not this caller.

Ordinary `frontend/vite.config.js` registers `preparedSharePlugin`. Its existing
background-links path reads host status and returns **202 `{pending: true}`**
when no host exists; it does not launch a host for that request. The isolated
config replaced the whole plugin list with the history gate transform, removing
this genuine protocol boundary and causing S08's 404s.

The isolated config now retains the real plugin with `autoStart: false`, empty
public origin, `controlFile` beneath the fresh owned root and a launch callback
that throws an explicit harness-disabled error. It neither reads ordinary host
credentials nor starts a host. No response mocking, new sharing service or console
filtering. Explicit start/non-background links return real 503 refusal; unknown
routes still return 404. Normal production configuration is unchanged.

## Validation actually run

- `just validate-safe npm --prefix frontend run test -- src/test-helpers/deformation_history_launch.test.js src/ui/design_readiness_boot.test.js`:
  **10 passed, 2 files, 1.10 s**. New focused test drives the actual middleware over
  a temporary loopback HTTP server: background pending, stopped status, explicit
  start/link refusal, unknown-route error and no credential/output files. Existing
  tests preserve default-false gates, unique transform and read-only adoption.
- `node --check frontend/e2e/deformation_history_vite.js` and
  `node --check frontend/src/test-helpers/deformation_history_launch.test.js`: passed.
- `just validate-safe uv run --no-sync python scripts/run_deformation_history_e2e.py --check-storage`:
  passed on `/tmp`, 661 GiB free. Ports were bindable before execution.
- `just validate-safe uv run --no-sync python scripts/run_deformation_history_e2e.py`:
  **2 passed, 24.6 s**, Bend 9.5 s, Twist 8.9 s. Exactly **one** invocation.
  Existing assertions cover native one-helix fixture adoption, private Open,
  matrix change on edit, exact backend/browser/saved-byte preservation through
  preview/Cancel, zero canonical preview writes, disposal/reopen, one Apply,
  one revision/history increment, redo clearing, stable IDs, changed inputs,
  adopted revision and empty console/page-error list.

Warnings: existing ORJSON deprecation and NO_COLOR/FORCE_COLOR messages.
No backend/full frontend suite or scientific campaign ran: this is test-harness
configuration only. Historical failed full-software and incomplete FAST/FULL debt
remain. These tiny automated cases do not qualify full controls, creation,
stale/refusal/lost-reply cases, undo/redo/save/reopen, representative chains,
visual/scientific correctness, latency or retained memory. ISSUE-100/MV-48 and
FH-20/FH-27 remain open; legacy production paths and disabled gates remain.

## Artifact inventory and cleanup

Reviewed before Playwright: fresh root owns workspace fixtures/project stores/logs,
playback, `.owner-start`, TMPDIR profiles/downloads, XDG/UV/Playwright/Vite caches,
Playwright results and error snapshots. No screenshot/video/trace. New potential
`share-control.json`/status paths are inside that root; no writer is launched.
Installed Chromium is a read-only dependency. Fixtures retain `__e2e__` names.
Launcher finally stops owned processes and removes the whole root after failure
or success. Focused middleware test finally closes its HTTP server and removes
its fresh temp root.

`/tmp/__e2e__history-yoo8sdes` was removed by the launcher and independently verified
absent. No focused `__e2e__history-share-*` temp roots or workspace history fixtures
remain. No accessible process has the exact owned-root marker; 31 protected
process environments were unreadable. An initial plain bind check returned
EADDRINUSE due to TCP TIME_WAIT: subsequent connection inspection found no
listeners, and SO_REUSEADDR binds passed for 8004/5177. No live service leak found.
Deleted byte totals were not metered. Only compact documentation retained.

## Closeout

**21/38 complete, 17 remaining (8 core, 9 parked); delta +0/+0; U1–U54 unchanged.**
S09 is complete within its fixed scope. The sole successor is **S10**, tiny-fixture
undo/redo/save/reopen acceptance, fully specified in the [handoff](session_handoff.md).
It is unstarted. Full parent exits are unchanged; no partial milestone credit.

Final checks: `just lint-memory` reports 0 errors/0 warnings; `git diff --check`
and scoped untracked-file whitespace checks pass. Checked 51 local link targets
across current records/report/matrix/memory: none missing. Ledger has 38 unique
FH rows, 21 Done; the handoff has exactly one fully specified S10 successor.
Current plan/ledger/memory/issue/manual sequencing agrees. The temporary records
update script was removed; no bulk evidence retained.
