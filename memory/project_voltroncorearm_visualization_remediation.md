---
name: voltroncorearm-visualization-remediation
description: "Persistent execution plan for making every VoltronCoreArm Display-MD state fast, observable, robust, and Playwright-verifiable"
metadata:
  node_type: memory
  type: project
  status: complete
  started: 2026-08-15
---

# VoltronCoreArm visualization remediation

## Topic navigation and current boundaries

Reorganized October 17, 2026. Read the retained contracts here, then only the
matching detail below. Dated results and old handoffs are not new verification
or authorization; current user instructions and `CLAUDE.md` take precedence.

<a id="objective"></a>
- [Objective](details/project_voltroncorearm_visualization_remediation/01-objective.md#objective)

<a id="reproduction-fixture"></a>
- [Reproduction fixture](details/project_voltroncorearm_visualization_remediation/01-objective.md#reproduction-fixture)

<a id="baseline"></a>
- [Baseline](details/project_voltroncorearm_visualization_remediation/01-objective.md#baseline)

<a id="work-ledger"></a>
- [Work ledger](details/project_voltroncorearm_visualization_remediation/01-objective.md#work-ledger)

<a id="v1--authoritative-alpine-connection-state"></a>
- [V1 — Authoritative Alpine connection state](details/project_voltroncorearm_visualization_remediation/01-objective.md#v1--authoritative-alpine-connection-state)

<a id="v2--explicit-refresh-gate-diagnostics"></a>
- [V2 — Explicit refresh-gate diagnostics](details/project_voltroncorearm_visualization_remediation/01-objective.md#v2--explicit-refresh-gate-diagnostics)

<a id="v3--honest-readiness-semantics"></a>
- [V3 — Honest readiness semantics](details/project_voltroncorearm_visualization_remediation/01-objective.md#v3--honest-readiness-semantics)

<a id="v4--request-coalescing-and-polling-contention"></a>
- [V4 — Request coalescing and polling contention](details/project_voltroncorearm_visualization_remediation/01-objective.md#v4--request-coalescing-and-polling-contention)

<a id="v5--initial-design-loadrender-contention"></a>
- [V5 — Initial design-load/render contention](details/project_voltroncorearm_visualization_remediation/01-objective.md#v5--initial-design-loadrender-contention)

<a id="v6--bounded-playwright-visual-verification"></a>
- [V6 — Bounded Playwright visual verification](details/project_voltroncorearm_visualization_remediation/02-v6--bounded-playwright-visual-verification.md#v6--bounded-playwright-visual-verification)

## Geometry invariants

Do not trade correctness for speed. Every final retained/refreshed-frame run must keep:

- 14,179 frame positions.
- 72/72 overhang keys present.
- Maximum adjacent overhang spacing below 0.8 nm.
- Maximum rod/bead angle below 12 degrees.
- Reference overhangs and reference crossover arcs hidden.
- No browser console or page errors.

<a id="execution-order"></a>
- [Execution order](details/project_voltroncorearm_visualization_remediation/03-execution-order.md#execution-order)

<a id="completion-record"></a>
- [Completion record](details/project_voltroncorearm_visualization_remediation/03-execution-order.md#completion-record)

<a id="2026-08-15--loop-1-remote-refresh-truthfulness"></a>
- [2026-08-15 — Loop 1: remote refresh truthfulness](details/project_voltroncorearm_visualization_remediation/03-execution-order.md#2026-08-15--loop-1-remote-refresh-truthfulness)

<a id="2026-08-15--loop-2-honest-readiness-contention-and-bounded-verification"></a>
- [2026-08-15 — Loop 2: honest readiness, contention, and bounded verification](details/project_voltroncorearm_visualization_remediation/03-execution-order.md#2026-08-15--loop-2-honest-readiness-contention-and-bounded-verification)

<a id="2026-08-15--loop-3-eliminate-rebuild-fan-out-and-broad-regression"></a>
- [2026-08-15 — Loop 3: eliminate rebuild fan-out and broad regression](details/project_voltroncorearm_visualization_remediation/03-execution-order.md#2026-08-15--loop-3-eliminate-rebuild-fan-out-and-broad-regression)

<a id="2026-08-15--loop-4-complete-remote-state-matrix-without-mutating-the-run"></a>
- [2026-08-15 — Loop 4: complete remote state matrix without mutating the run](details/project_voltroncorearm_visualization_remediation/03-execution-order.md#2026-08-15--loop-4-complete-remote-state-matrix-without-mutating-the-run)

## Final completion audit

| Requirement | Authoritative evidence | Verdict |
|---|---|---|
| Persistent remediation plan | This document, V1-V6 ledger and dated loops | complete |
| Alpine state consistency | structured gate, event-state repaint, pre-click status reconcile; unit + Playwright state matrix | complete |
| Actionable refresh gating | reason/label/title/enabled + DOM `data-gate-reason`; all branches unit-tested | complete |
| Honest readiness | `topology-ready` -> `frame-cached` -> `frame-applied`; focused tests + timeline | complete |
| Duplicate request removal | transport and endpoint coalescers; latest timeline has zero overlapping identical GETs | complete |
| Initial-load performance | 38.35 s -> 17.02-17.19 s; operation and Server-Timing attribution | complete |
| Required slow work explained | dual 29,418-position measured/deformed and straight geometry builds account for 8.15 s | complete |
| Bounded headless verification | 31.6-41.8 s diagnostics; scene pixels explicit GPU opt-in; 1.1 min geometry test | complete |
| Initial/intermediate/final states | 17/17 Playwright prediction matrix and current UI screenshots | complete |
| Geometry correctness | 14,179 positions and every geometry invariant passed | complete |
| Regression breadth | 322 Vitest files / 5,609 tests and production Vite build passed | complete |

Project completed 2026-08-15. Future GPU-backed pixel baselines and a naturally running
Alpine job may add evidence, but they are not required to reproduce or validate the fixed
visualization state machine and must not mutate this completed simulation fixture.

<a id="2026-08-15--loop-5-service-availability-incident"></a>
- [2026-08-15 — Loop 5: service-availability incident](details/project_voltroncorearm_visualization_remediation/04-2026-08-15--loop-5-service-availability-incident.md#2026-08-15--loop-5-service-availability-incident)

<a id="2026-08-15--loop-6-cached-completed-frame-must-not-look-failed"></a>
- [2026-08-15 — Loop 6: cached completed frame must not look failed](details/project_voltroncorearm_visualization_remediation/04-2026-08-15--loop-5-service-availability-incident.md#2026-08-15--loop-6-cached-completed-frame-must-not-look-failed)

<a id="2026-08-15--loop-7-selected-job-ownership-of-the-alpine-submit-control"></a>
- [2026-08-15 — Loop 7: selected-job ownership of the Alpine submit control](details/project_voltroncorearm_visualization_remediation/04-2026-08-15--loop-5-service-availability-incident.md#2026-08-15--loop-7-selected-job-ownership-of-the-alpine-submit-control)

<a id="2026-08-15--loop-8-selected-job-synchronizes-the-clusters-card"></a>
- [2026-08-15 — Loop 8: selected job synchronizes the Clusters card](details/project_voltroncorearm_visualization_remediation/04-2026-08-15--loop-5-service-availability-incident.md#2026-08-15--loop-8-selected-job-synchronizes-the-clusters-card)

<a id="2026-09-1617--loop-9-event-loop-threading-codex--client-side-connection-pool-contention"></a>
- [2026-09-16/17 — Loop 9: event-loop threading (Codex) + client-side connection-pool contention](details/project_voltroncorearm_visualization_remediation/04-2026-08-15--loop-5-service-availability-incident.md#2026-09-1617--loop-9-event-loop-threading-codex--client-side-connection-pool-contention)

<a id="2026-09-17--loop-10-user-authorized-live-server-testing-found-and-fixed-the-real-bottleneck"></a>
- [2026-09-17 — Loop 10: user authorized live-server testing; found and fixed the real bottleneck](details/project_voltroncorearm_visualization_remediation/05-2026-09-17--loop-10-user-authorized-live-server-testing-found-and.md#2026-09-17--loop-10-user-authorized-live-server-testing-found-and-fixed-the-real-bottleneck)

- [2026-09-17 — Loop 10: user authorized live-server testing; found and fixed the real bottleneck — continued detail](details/project_voltroncorearm_visualization_remediation/05-2026-09-17--loop-10-user-authorized-live-server-testing-found-and.md)
