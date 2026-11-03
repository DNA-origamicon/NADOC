# Architecture map (grounded, from a read-only sweep 2026-07-11) — supporting detail

[Topic head](../../project_snupi_frontend_tab.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

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
