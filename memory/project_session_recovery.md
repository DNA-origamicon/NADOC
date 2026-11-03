---
name: project-session-recovery
description: Backend restart/disconnect resilience + planned multi-document support; Phase 1 shipped 2026-05-23
metadata: 
  node_type: memory
  type: project
  originSessionId: d4ba1455-c6ab-4945-b1f6-7a6068c94aad
---

# Editor lifecycle resilience + multi-document (session recovery)

## Topic navigation and current boundaries

Reorganized October 17, 2026. Read the retained contracts here, then only the
matching detail below. Dated results and old handoffs are not new verification
or authorization; current user instructions and `CLAUDE.md` take precedence.

## Close-session display lifecycle — 2026-10-08

- Desktop `api.closeSession()` sends `docHeaders()` on DELETE `/design`; omitting
  the header cleared the default slot while retaining the active tab's document.
- `api/document_request_scope.js` retires this tab's `/design` responses on
  `nadoc:document-reset`. Pending GETs abort; saves/mutations are not interrupted,
  but their late responses cannot restore the closed document. Geometry calls
  from delayed callbacks skip the empty welcome screen. Browser cancellation
  does not forcibly interrupt the backend's synchronous geometry computation.
- Readiness visibility and refresh follow the actual welcome-screen visibility
  through `shared/welcome_visibility.js`: suppress the widget and stop polling
  until the editor opens, including reloads with a retained design object.
- Regression coverage: `client_session_close.test.js`, readiness controller and
  visibility tests, and the smoke Close Session case (delayed geometry, cancellation,
  document-scoped deletion, readiness polling interval and reload).

Plan file: `~/.claude/plans/we-need-to-better-elegant-cerf.md`. Two phases.
Direction chosen by user: resilience now, true multi-document later; **silent
server-side recovery** on restart; eventually **each editor owns its document**.

<a id="phase-1--shipped-2026-05-23-single-document-resilient"></a>
- [Phase 1 — SHIPPED 2026-05-23 (single-document, resilient)](details/project_session_recovery/01-phase-1--shipped-2026-05-23-single-document-resilient.md#phase-1--shipped-2026-05-23-single-document-resilient)

<a id="phase-2--shipped-2026-05-23-multi-document-backend"></a>
- [Phase 2 — SHIPPED 2026-05-23 (multi-document backend)](details/project_session_recovery/01-phase-1--shipped-2026-05-23-single-document-resilient.md#phase-2--shipped-2026-05-23-multi-document-backend)

<a id="follow-up-fix-2026-05-23--cross-contamination-between-open-files"></a>
- [Follow-up fix 2026-05-23 — cross-contamination between open files](details/project_session_recovery/01-phase-1--shipped-2026-05-23-single-document-resilient.md#follow-up-fix-2026-05-23--cross-contamination-between-open-files)

<a id="follow-up-fix-2026-05-24--part-editors-clobbered-each-other"></a>
- [Follow-up fix 2026-05-24 — part editors clobbered each other](details/project_session_recovery/02-follow-up-fix-2026-05-24--part-editors-clobbered-each-other.md#follow-up-fix-2026-05-24--part-editors-clobbered-each-other)

<a id="follow-up-fix-2026-05-27--surface--atomistic-reps-broken-missing-docheaders"></a>
- [Follow-up fix 2026-05-27 — surface + atomistic reps broken (missing docHeaders)](details/project_session_recovery/02-follow-up-fix-2026-05-24--part-editors-clobbered-each-other.md#follow-up-fix-2026-05-27--surface--atomistic-reps-broken-missing-docheaders)
