---
name: snupi-frontend-tab
description: Build prompt + architecture map for the frontend SNUPI structure-prediction engine tab (P5 of the SNUPI mimic). Backend ready via predict_shape(material="snupi").
metadata:
  node_type: memory
  type: project
---

# SNUPI frontend engine tab — fresh-session build brief (P5)

## ✅ SHIPPED 2026-07-11 — first-class SNUPI engine tab (separate-tab path)

Chose the **separate tab** (clone cando_* → snupi_*), not the material-selector-on-CanDo fallback —
matches `ENGINE_KEYS` conventions + is a true engine tab. SNUPI is a thin wrapper on the SAME FEM:
the runner calls `predict_shape(design, material=job.material, anchors=, field=)` (material default
"snupi"; "cando" isotropic baseline is an in-tab A/B option surfaced as the Advanced "Material" selector).

### ⚙ 2026-07-13 — solve now runs in a DETACHED subprocess (survives `uvicorn --reload`)
The runner used to solve in an in-process daemon THREAD. On a large design (VoltronCore, ~7 000 FEM
nodes) the "Fine" solve legitimately takes 5–7 min, and any `uvicorn --reload` (a save under
`backend/`/`scripts/` — incl. a concurrent editor — or a manual restart) during that window killed the
thread → the job was stranded as **stopped** ("stops on its own"). Fix: `start_job` now spawns
`python -m backend.core.snupi_worker <ws> <job_id>` with `start_new_session=True`, so the solve is its
own session and the reloader (which signals only the server's group) no longer reaches it. Liveness =
persisted `job.pid` (`os.kill(pid,0)`), not a thread handle; `reconcile_snupi_status` promotes the
survivor to `completed` after a restart. Bonus: `stop_job` is now immediate (SIGTERM→SIGKILL the worker)
instead of waiting for the monolithic solve to finish. New: `snupi_worker.py` (thin process shell) +
`solve_and_cache()` (the callable solve body, tested in-process); `SnupiJob.pid` field.

**Files (clones, autorefine dropped — SNUPI is predict-only):**
- Backend: `backend/core/snupi_job.py` (SnupiJob, lean — no refine_* fields; +`material`, +`pid`),
  `backend/core/snupi_runner.py` (`solve_and_cache` = solve body; `start_job` spawns the detached
  `snupi_worker`; predict-only, no autorefine) + `backend/core/snupi_worker.py` (detached entry point),
  `backend/api/routes_snupi.py` (`/snupi/*` — create/list/status/progress/start/stop/delete/display/rmsf/
  deviation/cylinders/shape-source/available/error-log; reuses cando_deviation/cando_cylinders/
  cando_shape_source display processors — they're material-agnostic). Registered: `main.py` include,
  `routes_jobs.py` active scan tuple, `sim_jobs.normalize_snupi_job`, `routes_simulate` list merge.
- Frontend: `snupi_jobs_panel.js` (exports `jobDisplayName`+`selectJob`+`deleteSelected`; dispatches
  `nadoc:sim-jobs-changed`; poll via `jobs_panel_base`), `snupi_display.js` (reuses cando's pure colour
  mappers, clones only the stateful controller pointed at `/snupi/*`), `snupi_metrics_card.js` (reuses
  `cando_metrics.js` pure fns). Registry: `engine_capabilities` ENGINE_KEYS `['cando,snupi,mrdna,oxdna,namd]`
  + label + `snupi` CAPABILITIES block (surface `off`), `simulate_jobs._ENGINE_BADGE` `[SN]` + all engine
  maps, `forces_card` snupi id/variant entry. Cylinder overlay: `initCandoCylinders(scene)` reused (2nd
  independent instance).
- `main.js` **Δ +19 net LOC, pure wiring** (imports + factory init + panelEls/runControlEls/timeline/
  initSimulateJobs entries). index.html: `#snupi-run-controls` + full `#snupi-jobs-panel` block.

**Verify:** backend `just test-smart` escalated to **FULL** (new modules = foundational) → 4718 passed,
111 skipped, watermark bumped; new `tests/test_snupi_job.py` (10, incl. a real linear solve completing +
caching + the material→predict_shape wiring). Frontend `just test-frontend` **2683 pass** (+66; new
`snupi_jobs_panel.test.js` 9 pure-fn cases + engine_capabilities parity census updated for the 5th engine).
App-exercised via `e2e/snupi_tab.spec.js` (passing): tab renders as a sibling, panel + run controls show,
capability strip greys Hard surface, Advanced material selector (2 opts)+n_steps+with_rmsf, Anchors +
E-field cards toggle (field-no-anchor warns), viz radios locked until a completed job, **0 console errors**.
Full in-app job SUBMISSION not driven via E2E (doc-scoped multi-step bundle build hits the MV-28 multi-doc
friction that clobbers the design mid-build; same limit the CanDo/oxDNA panels are documented against) —
covered instead by the real-solve backend job tests.

### Anchors + E-fields + surfaces — the investigation deliverable
- **Anchors: ON.** Reuses the shared `initOxdnaAnchorsSetup` (parameterised `snupi-anchors-*` ids) →
  `predict_shape(anchors=)` (Dirichlet BC, already in fem_solver). Capability `on`.
- **E-fields: ON.** `forces_card` gained a `snupi` FORCES_FIELD_IDS + VARIANT entry (numeric, no gizmo —
  like CanDo); `predict_shape(field=)`. A field needs ≥1 anchor for COM drift (warn-only, non-blocking).
  Capability `on`.
- **Surfaces: OFF (greyed, exactly like CanDo).** RECOMMENDATION: ship surface off. The FEM has NO
  hard-wall boundary condition — `predict_shape` solves a free/anchored corotational beam network with
  loop/skip prestress + optional uniform field; there is no floor/penalty-plane term. Adding one would
  take a NEW `predict_shape` arg (`surface={dir, offset_nm, stiff}`) → per-node one-sided penalty springs
  (`k·max(0, offset − n·x)` on nodes below the plane) assembled into K each corotational load step, i.e.
  a contact nonlinearity (active-set / penalty) the current single-material solve doesn't have — a real
  solver change, NOT UI wiring. oxDNA/mrDNA get surfaces because their engines integrate external forces
  (`oxdna_floor_setup.js` / ARBD repulsion plane); the FEM has no such hook. Verdict: not worth it for a
  first-class tab — a wall BC is a fem_solver feature to scope separately (would apply to CanDo too, since
  same solver). Greyed with the reason tooltip "The SNUPI FEM has no hard-surface boundary condition."

Three-Layer Law respected: FEM output is Physical-layer / display-only; no topology writes.

---


Backend is DONE and committed (`128bd06`): the SNUPI mimic is a validated FEM material
(`predict_shape(design, material="snupi", anchors=, field=)` in `backend/physics/fem_solver.py`;
verdict snupi ≥ cando vs MD at $0 — see [[snupi-mimic]]). **This phase is UI/route wiring only — no
solver work.** SNUPI's exact sibling is **CanDo FEM** (same solver entry point, same panel/job/display
architecture). Clone that stack and thread `material="snupi"` through it.

## THE PROMPT (paste into the fresh session)

> Build a first-class **SNUPI** structure-prediction engine tab in the NADOC frontend, sibling to
> CanDo FEM / mrDNA / oxDNA / NAMD. The backend already exposes the engine: a SNUPI prediction is just
> `predict_shape(design, material="snupi", anchors=, field=)` (validated; see `memory/project_snupi_mimic.md`
> + `memory/project_snupi_frontend_tab.md` for the full architecture map). This is a UI + route/job
> wiring task — **do not touch the FEM solver**.
>
> Deliver, matching existing conventions (read `memory/project_simulate_panel_overhaul.md` +
> `memory/project_cando_fem.md` first, and the CanDo stack as the template):
> 1. **Engine registration** — add `'snupi'` to `ENGINE_KEYS` + an `ENGINE_CAPABILITIES` block
>    (clone `cando`) in `frontend/src/ui/engine_capabilities.js`; label; `[SN]` badge in
>    `frontend/src/ui/simulate_jobs.js` `_ENGINE_BADGE`. In-process solver → no install/availability gate.
> 2. **Unified jobs card** — the SNUPI panel plugs into the shared master job list (`simulate_jobs.js`):
>    export `jobDisplayName` + `selectJob(id)`, and dispatch `nadoc:sim-jobs-changed` on job-set/status
>    change (the idle-wake contract — mandatory or the master card won't refresh).
> 3. **Live progress bar** — REST polling via `jobs_panel_base.js` (`shouldPoll`, `POLL_MS`), a
>    `GET /snupi/jobs/{id}/progress → {overall, eta_seconds}` endpoint, `formatProgress`/`detailStatusText`
>    like CanDo. (No WebSocket — FEM job progress is polled.)
> 4. **Advanced card** — the collapsible drawer (`jobs_panel_base.js` + `advancedParams` ids): keep
>    `n_steps` + `with_rmsf`; add any SNUPI param knobs (e.g. a param-set/material-variant selector if useful).
> 5. **Visualization card + standard toggles** — clone `cando_display.js`: the mutually-exclusive radio
>    display modes (off / predicted-shape-deform / flexibility-RMSF / deviation / CanDo-style cylinders),
>    feeding the SHARED adjustable legend + colormap picker (`flex_scale.js` + `colormaps.js`). Plus a
>    metrics card (`cando_metrics_card.js` clone) if warranted.
> 6. **Backend route/job/runner** — clone `routes_cando.py`/`cando_job.py`/`cando_runner.py` →
>    `routes_snupi.py`/`snupi_job.py`/`snupi_runner.py`, where the runner calls
>    `predict_shape(..., material="snupi", anchors=, field=)`. Register the job kind in `routes_jobs.py`.
>    Add `material` handling if you instead extend CanDo (see decision below).
> 7. **Anchors + E-fields + surfaces INVESTIGATION** (explicit deliverable):
>    - **Anchors**: already wired for CanDo (`initOxdnaAnchorsSetup`, shared). Reuse for SNUPI —
>      `predict_shape` takes `anchors=` directly. Add `#snupi-anchors-toggle` + capability `on`.
>    - **E-fields**: already wired for CanDo (`forces_card.js` `initForcesCard({engine:'cando'})`,
>      `predict_shape(field=)`). Add a `snupi` entry to `FORCES_FIELD_IDS`/`FORCES_FIELD_VARIANTS` and
>      `#snupi-efield-toggle`; capability `on`. (A field needs ≥1 anchor for COM drift — same as CanDo.)
>    - **Surfaces**: NOT supported in the FEM today (no hard-wall boundary condition in `predict_shape`;
>      CanDo sets `surface = off(...)`). REPORT whether a FEM surface BC is worth adding (a floor/penalty
>      plane like oxDNA's `oxdna_floor_setup.js` / mrDNA's ARBD repulsion plane) or ship SNUPI with
>      **surface greyed out** exactly like CanDo. Recommend: ship anchors+efields on, surface off, and
>      write up what a FEM wall BC would take as a follow-up.
> 8. **main.js wiring only** (Module-first law — `main.js` gains ONLY imports + factory init + thin
>    per-action wiring; the cohesive logic lives in the new `snupi_*` modules): add `#snupi-jobs-panel`
>    + `#snupi-run-controls` in `index.html`, register in the `panelEls`/`runControlEls` maps + the
>    `initEngineSelector`/`initSimulateJobs` calls, `initSnupiJobsPanel(...)`. Cite `main.js` LOC Δ
>    (must be pure wiring).
>
> **Verify**: `just test-smart` for backend routes; `just test-frontend` for JS modules (≥1 vitest per
> extracted pure fn); and **exercise the tab in the running app** (`just frontend` + load a design like
> `Examples/26hb_platform_v3.nadoc` or `workspace/6hbx100_noT.nadoc`, submit a SNUPI job, watch the
> progress bar, flip the viz toggles, add an anchor + an E-field). Three-Layer Law: FEM output is
> DISPLAY-ONLY, never writes topology.
>
> **Key design decision to make first** (after reading the panel architecture): a fully SEPARATE tab
> (clone cando_* → snupi_*) matches `ENGINE_KEYS` conventions and is what's requested — OR the minimal
> path of adding a `material` selector to the existing CanDo tab (thread `material` through
> `CreateCandoJobRequest`→`CandoJob`→`cando_runner`). Prefer the separate tab for a true engine tab;
> note the minimal fallback if scope is tight.

## Architecture map (grounded, from a read-only sweep 2026-07-11)

**Registry/selector.** `frontend/src/ui/engine_capabilities.js` — `ENGINE_KEYS` (line ~30, fast→accurate
order), `ENGINE_LABELS`, `CARD_KEYS` (`run,efield,anchors,surface,advanced,viz,metrics,joblist`),
`ENGINE_CAPABILITIES` per-engine descriptor (the `cando` block ~108-122 is the template — cards carry
`domAnchorId`s, `protocols`, `advancedParams`). `frontend/src/ui/engine_selector.js`
`initEngineSelector({selectorMount,stripMount,panelEls,runControlEls,initial,labels,onSelect})` toggles
whole-panel display via `panelEls[key]`/`runControlEls[key]`; reflects install via `nadoc:engine-availability`.
`frontend/index.html`: `#simulate-panel`/`#simulate-body`, `#engine-selector-mount`,
`#engine-capability-strip`, `#simulate-run-controls` (per-engine run clusters), per-engine `.panel-section`
(`#cando-jobs-panel` ~4226, `#oxdna-jobs-panel` ~3707). `main.js`: `initEngineSelector({...})` ~2130,
`panelEls`/`runControlEls` maps, `initial:'oxdna'`, tab auto-switch on job events.

**Unified jobs card.** `frontend/src/ui/simulate_jobs.js` `initSimulateJobs({api,getWorkspacePath,
oxdnaPanel,mrdnaPanel,candoPanel,mdPanel,engineSelector})` (main.js ~2171). Reads `GET /simulate/jobs`
(merged), renders via `jobs_panel_model.js`+`jobs_panel_render.js`. `_ENGINE_BADGE` map (~44-49; add
`snupi:{text:'[SN]',...}`). Imports each engine's `jobDisplayName`; selecting a node calls
`panel.selectJob(id)`. HTML `#simulate-jobs*` (index.html ~3654-3685). `POLL_MS=1500`; wakes from idle on
`nadoc:sim-jobs-changed` (each panel MUST dispatch it — the overhaul fix).

**Progress.** REST polling, no WS for FEM. `frontend/src/ui/jobs_panel_base.js` owns the per-panel poll
(`shouldPoll({open,hasActive})`, `POLL_MS`). Per-job `GET /cando/jobs/{id}/progress → {overall,eta_seconds}`;
CanDo `formatProgress`/`detailStatusText` in `cando_jobs_panel.js`.

**Advanced card.** Drawer in `jobs_panel_base.js` (`*-adv-toggle`/`*-adv-body`); ids declared in
`engine_capabilities.js` `advancedParams`. CanDo: `#cando-jobs-n-steps`, `#cando-jobs-with-rmsf`
(index.html ~4287-4297).

**Viz card + standard toggles.** `frontend/src/ui/cando_display.js` `initCandoDisplay` — radios
`name="cando-display-mode"`: off / deform (predicted shape) / flex (RMSF) / deviation / cando (cylinders)
(HTML `#cando-display-card` ~4373-4394). Shared legend `frontend/src/ui/flex_scale.js`
(`flexScale.show({title,min,max,mapType,onRecolor})`, one instance in main.js) + `colormaps.js` (10 ramps).
Metrics: `cando_metrics_card.js`. Cross-engine compare: `shape_compare_card.js`.

**CanDo sibling backend.** `backend/api/routes_cando.py` (mounted `/api`): `POST /cando/jobs`,
`GET /cando/jobs`, `/{id}`, `/{id}/progress|start|stop|display|rmsf|deviation|cylinders|shape-source|error-log`,
`DELETE`, `GET /cando/available`. Request `CreateCandoJobRequest` (~95-115): `kind,nonlinear,n_steps,
with_rmsf,anchors,field,autostart,design_source_path` — **NO `material` field yet.** Runner
`backend/core/cando_runner.py` ~202 calls `predict_shape(nonlinear,n_steps,with_rmsf,anchors,field)` —
**does NOT pass `material`** (defaults cando). Job kind registry `routes_jobs.py:163`. Frontend client
`frontend/src/api/client.js` (`api.*`).

**Anchors/E-fields/surfaces.** Anchors: `predict_shape(anchors=)` + `#cando-anchors-toggle`
(index.html ~4304) via `initOxdnaAnchorsSetup` (shared oxDNA/cando). E-fields: `predict_shape(field=)` +
`#cando-efield-toggle` (~4320-4352) via shared `forces_card.js` `initForcesCard({engine:'cando'})`
(engine variants map ~45-50, 78). **Surfaces: none in FEM** — `cando.surface = off('CanDo FEM has no
hard-surface boundary condition.')`. Surfaces exist only for oxDNA (`oxdna_floor_setup.js`) / mrDNA (ARBD
plane). Adding one to SNUPI needs a new `predict_shape` wall BC.

## Notes
- Module-first: new logic in `snupi_*` modules; `main.js` gets imports + init + thin wiring only.
- `predict_shape` returns DISPLAY-ONLY positions/RMSF (Physical layer) — never write topology.
- Related heads: [[snupi-mimic]] (backend/verdict), simulate_panel_overhaul, cando_fem, md_viz_tools,
  md_engines_panel, mrdna_panel (clean clone precedent).
