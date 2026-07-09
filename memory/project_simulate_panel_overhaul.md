---
name: project_simulate_panel_overhaul
description: Simulate-panel UX overhaul — one collapsible Simulate section, static engine headers, context Run/Stop/Resume, master Job status card
metadata:
  node_type: memory
  type: project
---

# Simulate panel UX overhaul (2026-07-08, in progress)

Direct user request (not the coverage loop). Consolidate the Dynamics-tab simulation UI
into one clean **Simulate** section with a **master Job status card** and context
Run/Stop/Resume buttons. Builds on the U-track (unified panel) work — the engine selector
(`engine_selector.js`, U4) already fronts the 5 engine panels.

## User's spec (verbatim intent)
- Make the **Simulate header collapsible**; **remove per-engine header collapse**.
- **Remove the Periodic MD** section from the frontend.
- **Unify** card styling, name, order across engines.
- Move all job status outputs, loading bars, and buttons into a **UX-reviewed master Job
  status card** (ONE global card reflecting the selected engine — user chose "one global").
- When a job starts, its outputs should be **visually clean**.
- **Every job-initiating button flips to Stop** the instant its job runs (press Relax →
  "Stop Relax"); selecting a **stopped** job flips it to **Resume**. Apply across all engines.
- User decisions (AskUserQuestion): one global master card · context buttons IN the card ·
  implement directly (no mockup) · structural changes first.

## Phase A — structural (SHIPPED + verified, committed `73db970`)
- **Periodic MD panel removed**: DOM block + `periodic_md_panel.js` + `periodic_md_overlay.js`
  + `main.js` wiring + stale e2e spec. Client-only, no backend (see [[periodic_md]]).
- **Per-engine headers no longer collapse** — static labels. New `collapsible:false` option on
  `jobs_panel_base.js::initJobsPanelBase`: forces the section open (ignores persisted state,
  no heading listener), keeps the advanced-drawer + poll, and **defers `onOpen` to a
  microtask** (a permanently-open panel inits early in `main.js`, before late-declared deps
  like `_workspacePath` → firing onOpen synchronously was a TDZ; the microtask fires after the
  synchronous init body). All 5 panels pass `collapsible:false`; the 5 engine `<h2>`s keep a
  title `<span>` so `engine_activity_headers.js` can still hang its busy-spinner there.
- **Simulate section collapses as one**: `index.html` wraps the selector + capability strip +
  all engine panels in a collapsible `#simulate-body`, driven by `initJobsPanelBase` (wired in
  `main.js`, arrowStyle:'class'). `main.js` net **−8 LOC**.

## Phase B — naming (SHIPPED, committed `73db970`)
Unified divergent card titles to the U1 descriptor (`engine_capabilities.js` CARD_LABELS):
LAMMPS "Surface" → "Hard surface"; CanDo "Display" + others' "Visualizations & processing" →
"Visualizations". **Card ORDER + deeper styling deferred into Phase C** (which reorganizes the
same panels — reordering now would be redone). Canonical order = `CARD_KEYS`
(run, efield, anchors, surface, advanced, viz, metrics, joblist).

## Phase C — master Job status card + context Run/Stop/Resume (IN PROGRESS)
**Foundation (SHIPPED, committed `73db970`):** `frontend/src/ui/job_run_control.js` —
pure `runControlState(selectedJob, {verb, isActive, isResumable, busy}) → {action,label,disabled}`
with `RUN_ACTION={RUN,STOP,RESUME}`. The rule: nothing/completed selected → `▶ <verb>`;
selected job active → `■ Stop <verb>`; selected stopped/failed → `↻ Resume <verb>`. Active
wins over resumable. 9 unit tests. Each engine supplies its own predicates + verb.

**Engines wired (pattern = extract `_launchRelax`, add `_runControl`/`_stopSelected`/
`_resumeSelected`, dispatch the run btn's click on `_runControl().action`, paint label from
it, retire the redundant detail Start/Stop):**
- **oxDNA** (committed `73db970`): gated to the RELAXATION phase (`isActive:isRelaxRunning`) so
  a running PRODUCTION phase keeps "▶ Relax" (disabled) + a production-phase Stop stays in the
  detail. Detail Start retired. 99 panel tests (3 rewritten).
- **NAMD** (done, **uncommitted as of this file**): pure exported `mdRunControl(job,{busy})` —
  `isActive:mdJobIsActive`; **local** stopped/failed → Resume here, but an **Alpine** job's
  cluster-gated resume stays on its dedicated resume button (Alpine is never "Resume" here,
  though an in-flight Alpine job still shows Stop=scancel). Detail Start/Stop retired; Alpine
  submit/resume/ensemble keep their dedicated buttons. +9 `mdRunControl` tests.

**REMAINING:**
1. Wire the context button into **LAMMPS, mrDNA, CanDo** (lighter — no Alpine; mrDNA/CanDo have
   Coarse+Fine, so decide which action the context verb tracks — likely the primary/Coarse).
2. **Master Job status card consolidation**: fold the 5 bespoke `#*-jobs-progress` bars, status
   lines, Health cards, Metrics cards, and detail blocks into ONE global card in the Simulate
   section that reflects the selected engine's active/selected job; "visually clean when
   running"; apply the canonical CARD_KEYS order. Reuse the shared seams
   (`jobs_panel_render.js`, `metrics_card.js`, `job_tree.js`).

## Verification + debt
- Gates each slice: `just test-frontend` (vitest, currently **2398 passed**) + `just smoke`
  (23/23). NO backend/Python touched in the whole overhaul.
- **Live-gesture verification is blocked by the doc-context limit** (API `design/load` doesn't
  set the frontend workspace path → the per-design job filter drops mocked jobs → Playwright
  can't drive job selection; same as U4's MV-28). So the run/stop/resume + collapse *gestures*
  are unit-verified (real panel factory drives the button DOM) but owe manual rows:
  **MV-30** (Simulate collapse + static engine headers + Periodic-MD gone), **MV-31** (context
  Run/Stop/Resume on oxDNA + NAMD). See [[manual_validation_debt]].
- Related: [[project_md_job_system]], [[project_md_engines_panel]] (install gates prepend to
  `#oxdna-jobs-body`/`#md-panel-body` — still valid). U-track lives in `SIM_COVERAGE_PLAN.md`.
