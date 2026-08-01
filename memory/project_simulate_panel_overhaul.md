---
name: project_simulate_panel_overhaul
description: "Simulate-panel UX overhaul — Phases A/B shipped; Phase C half-done (P1): mrDNA+CanDo still lack the contextual Run/Stop/Resume button and still paint their own progress bars"
metadata: 
  node_type: memory
  type: project
  originSessionId: 68f44bf0-ff75-46c4-b4fc-6c7576403328
---

# Simulate panel UX overhaul

**Rank:** P1 — the user's verbatim spec ("every job-initiating button flips to Stop … apply
across all engines", "ONE master job status card") is unfulfilled for 2 of the engines; the
reference implementation already exists on oxDNA, so the remaining work is mostly pattern-copy
plus one genuine consolidation.

**Status (audited against code 2026-07-28):** Phase A (structural) and Phase B (naming) are
**SHIPPED and live**. Phase C is **~half done** — the foundation, oxDNA, and NAMD are wired;
**mrDNA and CanDo are entirely unstarted**, and mrDNA/CanDo still render their own visible
progress bars + status lines alongside the master card.

History (every dated ⚡ block, the phase write-ups, the Chain-Simulations build-out) →
`project_simulate_panel_overhaul_archive.md`. Don't read it in a routine loop.

## User's spec (verbatim intent — still the target)

- Simulate header collapsible; per-engine header collapse removed. **[DONE]**
- Periodic MD section removed from the frontend. **[DONE]**
- Unify card styling, name, order across engines. **[DONE for naming; order = `CARD_KEYS`]**
- All job status output / loading bars / buttons into ONE global master Job status card
  reflecting the selected engine. **[PARTIAL — oxDNA, LAMMPS, NAMD feed it; mrDNA + CanDo don't]**
- Every job-initiating button flips to **Stop** while its job runs; a stopped job's button flips
  to **Resume**. Across all engines. **[oxDNA + NAMD only]**

## Where the code actually lives (probed 2026-07-28)

| Thing | Path | State |
|---|---|---|
| Run-control primitive | `frontend/src/ui/job_run_control.js` — `RUN_ACTION`:19, `runControlState`:34 | live; imported by `simulate_jobs.js:29`, `oxdna_jobs_panel.js:32`, `md_jobs_panel.js:37` (RUN_ACTION only) |
| oxDNA context button | `oxdna_jobs_panel.js` — `isRelaxRunning`:232, `_runControl`:1201, `_stopSelected`:1217, `_resumeSelected`:1224, dispatch:1237 | live |
| NAMD run control | `md_jobs_panel.js` — `mdRemoteAwaitingSubmit`:143, `mdJobIsActive`:163, `mdRunControl`:176 (**always returns RUN**), `mdSelectedJobControl`:188, `_paintRunControl`:2142, `_paintJobControl`:2154 | live; button `#md-jobs-job-ctl-btn` (`index.html:5153`) in `#md-launch-row` (:5145), handler `md_jobs_panel.js:2214` |
| Master jobs card | `frontend/src/ui/simulate_jobs.js` — `masterProgressPct`:103 + `_pct1`:95 (**one decimal**, so a long production leaves 0 % in minutes not hours — see [[project_md_job_system]]), `masterStepText`:213 (exported) + `_etaSuffix`:207 (**time remaining, for EVERY engine** — BLADE/SNUPI no longer append their own), `_stepTotal`:191, `formatEta`:276 (now coarsens to `2d 06h`) | live; **only importer is `main.js:207`**. Panels notify it by `window.dispatchEvent('nadoc:sim-jobs-changed')` → listener `simulate_jobs.js:691` |
| mrDNA panel | `frontend/src/ui/mrdna_jobs_panel.js` (579 ln) | **no** `job_run_control` import; `coarseBtn`/`fineBtn`/`stopBtn`:202-218, launches:345, stop:459, own bar `#mrdna-jobs-progress` painted:416 |
| CanDo panel | `frontend/src/ui/cando_jobs_panel.js` (721 ln) | same shape — buttons:268-286, launch:409, stop:649, own bar painted:603; plus `initCandoMetricsCard` (`cando_metrics_card.js:32`) wired at :323 |
| Collapsible base | `jobs_panel_base.js` — `collapsible` param:86, gate:115, force-open:140 | 6 panels pass `collapsible:false` (md:956, mrdna:256, oxdna:1064, blade:281, cando:347, snupi:322) |
| Simulate section | `#simulate-body` `index.html:3679` ← `main.js:2413` `initJobsPanelBase(… arrowStyle:'class')` | live |
| Engine selector | `engine_selector.js` — tablist:92, `.engine-selector-btn`:96, `renderStrip`:131, `stripMount`:68 · `#engine-capability-strip` `index.html:3688` ← `main.js:2292` · `engine_capabilities.js` `CARD_KEYS`:53 `CARD_LABELS`:57 | live |
| Stop relocation | `main.js:2236` `_moveStopBelowLaunch` — covers **oxdna/mrdna/cando only** (:2246-2248); NAMD deliberately excluded (morphs in place); blade/snupi use `_moveRunControls`:2229 | live |
| Anchors halo | `oxdna_anchors_setup.js` — `_dispatch`:88, single `_emit`:96 · `main.js` `_anchorsByEngine`:2108, `_refreshAnchorGlow`:2109, listener:2115, engine-switch refresh:2308 | live, **no E-field gate**. Event payload is `{engine, anchors, glow, focusKey, highlighted}`; the halo consumes `highlighted`, not `anchors` |
| Chain Simulations | `chain_sim_model.js` + `chain_sim_panel.js:45` ← `main.js:195/2373`; `backend/api/routes_chain_sim.py` | live; tests `tests/test_routes_chain_sim.py` (8), `tests/test_chain_spawn_dispatch.py` (7) |
| Sequence guard | `routes_md.py:1169` calls `require_sequenced_scaffold` (`backend/core/md_sequence_guard.py:70`) before job creation; backstop `md_protocols.py:1807` | live; `tests/test_md_sequence_guard.py:55` (5 tests) |
| List progress | `routes_mrdna.py:237` / `routes_cando.py:192` — `progress_fraction` (4dp) + `eta_seconds` on running jobs only | live |

Note: tests live in **`tests/`**, not `backend/tests/` (earlier notes here had the wrong path).

## Open items (rewritten against the probe — this is what's actually left)

1. **mrDNA contextual Run/Stop/Resume — unstarted.** `mrdna_jobs_panel.js` still has
   `coarseBtn`/`fineBtn` + a separate `stopBtn` toggled by `job.status === 'running'` (:425).
   Copy the oxDNA pattern (`_runControl`/`_stopSelected`/`_resumeSelected` off `runControlState`).
   Open question kept from the original plan: with two launch buttons (coarse vs fine), decide
   which one the context verb tracks — likely Coarse as primary.
2. **CanDo contextual Run/Stop/Resume — unstarted.** Identical shape (:268-286 / :612 / :649).
   Its two launches are linear vs nonlinear corotational; same verb question.
3. **Fold `#mrdna-jobs-progress` into the master card.** `index.html:4293` is `display:none` in
   markup but `mrdna_jobs_panel.js:416-419` un-hides it and paints the bar while running — so the
   user sees two progress bars. NAMD's `#md-jobs-progress` is already **gone** (removed as
   "superseded by the master bar", recorded in [[project_md_sidebar_audit]]) — that's the model.
4. **Fold `#cando-jobs-progress`** (`index.html:4479`, painted `cando_jobs_panel.js:603-606`) —
   same as (3).
5. **Decide the fate of the bespoke status/detail blocks:** `#mrdna-jobs-status` (:4290, written
   mrdna:299), `#mrdna-jobs-detail-status` (:4444), `#cando-jobs-detail-status` (:4610), the CanDo
   metrics card, and NAMD's Health/`#md-jobs-metrics`/`#md-jobs-timeline` (:5587-5602). The spec
   says consolidate; in practice the rich per-engine detail may be worth keeping *inside* the
   master card (oxDNA already delegates its detail via `selectJob`). Pick one rule and apply it.
6. **`masterStepText` has no consumer outside its own module + test** (`simulate_jobs.js:187`).
   Either it's genuinely used internally only and the export is dead surface, or a panel was meant
   to call it. Check before item 3/4 — the step line is what the folded bars should feed.
7. **`#oxdna-jobs-progress` is still painted into a hidden element** (`index.html:3791`
   `display:none`; written `oxdna_jobs_panel.js:1508/1618`). Harmless but wasted work — delete
   the writer when touching (3)/(4).

Not blockers, but note for whoever picks this up: `manual_validation_debt.md` (repo **root**)
still lists **MV-30** (Simulate collapse + static engine headers + Periodic-MD gone), **MV-31**
(context Run/Stop/Resume on oxDNA + NAMD) and **MV-32** (chain-sim round-trip) as open PENDING
rows. They were recorded as blocked by a doc-context limit (an API-`design/load`ed design isn't
the frontend's active document, so Playwright can't drive job selection). **That limit is now
worked around** — see "Gesture-level verification" below; MV-30/31/32 are re-runnable.
MV-32 has a known duplicate-ID collision flagged at that file's L80.

## Job selection: click the selected row to DESELECT (2026-08-01)

`#simulate-jobs-list` is the ONE list the user clicks — every engine panel's own list is
`display:none` in `index.html` (the oxDNA one carries the comment saying so at :3860). Clicking a
row that is already selected now clears the selection instead of being a no-op.

**The rule: deselecting is not a job switch, so it discards nothing.** Whatever the job loaded
(trajectory frames, RMSF/deviation/strain map, the deform overlay, a live MD stream) stays on
screen and in its controller; only selecting a DIFFERENT job unloads/retargets it, exactly as
before. What clears is the row highlight, the master card, `#simulate-job-actions`, and the
engine panel's detail block.

| Where | What was added |
|---|---|
| `simulate_jobs.js` | `_deselect()` next to `_select()`; row `onClick` toggles; routes to the owning panel's `deselectJob()` (LAMMPS → `oxdnaPanel`, since it hosts the LAMMPS viz) |
| every engine panel | `_deselectJob()` + a `deselectJob` export. cando/snupi/blade deliberately skip `_retargetDisplayToSelection`; oxDNA skips `_setTrajOff`/`_clearRunCards` **and does not fire `nadoc:oxdna-job-selected`** (its listeners stop a running Live session and rebuild the export card — that's a job-switch reaction, not a deselect one) |
| cando/snupi/blade | `_syncDisplayModes` keeps the **"Off" radio enabled** whenever the display is active. Every other mode locks with no job selected; without this the lingering overlay could only be taken down by re-selecting the job |
| mrdna | the display/beads checkbox handlers no longer early-return on "no selection" for the **off** branch (same reason) |
| md | `_userDeselected` sticky flag — `_selectBestJob` runs on every poll and would re-select a beat later. `_selectDisplayJob` now prefers `_displayJobId` when nothing is selected, so deselecting can't jump the live display to another job |
| oxdna | new `_trajJobId` (who the loaded frames belong to). The "Unload trajectory?" confirm keys off it, not `_selectedId` — those differ after a deselect, and re-selecting the job whose trajectory is already up must not offer to unload it |

Pinned by: `simulate_jobs.test.js` (3), `oxdna_jobs_panel.test.js` (2 — incl. "deselect does not
unload the trajectory"), `md_jobs_panel.test.js` (2 — incl. "the poll does not re-select").

## Gesture-level verification — the doc-context limit is solved

`frontend/playwright.livedev.config.js` + opening the design through the **welcome-screen library
row** (not `POST /design/load`) gives a spec a real active document on the user's own dev servers,
so job selection IS drivable. `frontend/e2e/job_deselect.spec.js` is the worked example: pinned
`?doc=`, read-only w.r.t. jobs, walks all five engine tabs that have jobs on this machine
(oxDNA/NAMD/CanDo/SNUPI on `3x6x400_test`, mrDNA on `6hb_2xT`; BLADE has no jobs here).

Two gotchas it cost a run each to learn:
- **Screenshot the part from OUTSIDE it.** Dollying inside the structure amplifies sub-pixel
  camera drift into a wholly different image, so byte-comparison of two "identical" frames fails
  for reasons that have nothing to do with the feature. Always take a static A==A baseline first.
- The unified list's selection is an **inline `background`** on the row (`jobs_panel_render.js`),
  not a class — assert `el.style.background !== ''`.

## Verification + debt

- Each slice gated on `just test-frontend` (vitest) + `just smoke` (23/23). Chain Simulations
  touched Python → full suite run at the time: 4461 passed.
- Tests pinning the shipped parts: `job_run_control.test.js` (9), `md_jobs_panel.test.js`
  (mdRunControl "always ▶ Relax" matrix, `mdSelectedJobControl`, runpod cases),
  `chain_sim_model.test.js` (21), `chain_sim_panel.test.js` (4 jsdom),
  `tests/test_routes_chain_sim.py` (8), `tests/test_chain_spawn_dispatch.py` (7),
  `tests/test_md_sequence_guard.py` (5).
- Gesture-level verification is blocked by the doc-context limit above → the MV rows.

Related: [[project_md_job_system]] · [[project_md_engines_panel]] (install gates — prepend to
`#oxdna-jobs-body`/`#md-panel-body`) · [[project_md_panel_status]] (trajectory viewer, separate) ·
[[project_md_sidebar_audit]] (NAMD sidebar layout; owns the `#md-jobs-progress` removal) ·
[[manual_validation_debt]]. U-track lives in `SIM_COVERAGE_PLAN.md`.
