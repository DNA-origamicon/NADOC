# Full simulation / feature-coverage loop

Drive all four structure-prediction engines — **CanDo FEM · mrDNA · oxDNA · NAMD** — to cover the four
unconventional design features (**extra crossover bases · linkers/overhang connections · E-fields · anchors**)
AND emit a **shared, comparable set of prediction descriptors** so the engines cross-validate one another
across the quick→rigorous continuum.

**Two UX/architecture tracks now ride the same loop** (user-authorized scope expansion 2026-07-08; see the
JSON `meta.ux_overhaul_tracks`). The feature-coverage tail (M4, N3, O2) is *parked, not dropped* — these two
tracks are the priority until their milestones land:
- **Track U — Unified panel (proposal A):** collapse the **6 bespoke per-engine panels + triplicated
  E-field/Anchors/Surface cards** into ONE *Simulate* section with an engine selector, driven by a capability
  descriptor. Precedent: CHARMM-GUI (one interface, many MD backends). = **M-UNIFIED-PANEL**.
- **Track P — Job planner (proposal B):** a generic **`MdPipeline`** so the user queues a **multi-stage chain**
  that runs *unattended* — the motivating case: *E-field→hard-surface (deposition) → anchors (immobilize) →
  E-field sweep in several directions*. Today that is three hand-babysat jobs. The backend already ships the
  chaining primitives (`parent_job_id`, `run_kind="production"`, `seed_oxdna/mrdna_job_id`, ensemble); P
  generalizes them into one object + an executor + a linear-stage-list UI. = **M-JOB-PLANNER** / **M-DEPOSITION-CHAIN**.

Invoke with **`/continue-coverage`** (or say *"continue full simulation/feature coverage"*). One session = one
task. The manager (this main-loop session) reads the authoritative plan + the last handoff, picks the
next-best task by the rubric below, implements it with a machine-checkable oracle, validates, commits, and
overwrites the handoff.

- **Authoritative task list:** [`sim_coverage_plan.json`](sim_coverage_plan.json) — machine-parseable, seeded
  all-`pending`. **The loop edits ONLY `status` + `notes`.** It may not add/remove/reorder/rewrite tasks;
  scope changes need the user. (JSON, status-only edits, all-seeded-failing: the long-running-agents harness
  pattern — resists drift better than a Markdown checklist.)
- **This file:** protocol + decision rubric + per-engine phased narrative + the living handoff.
- **Session log + oracle catalog:** [`sim_coverage_log.md`](sim_coverage_log.md) — MIRROR the oracles.
- **Metrics + cross-engine results:** [`sim_coverage_metrics.md`](sim_coverage_metrics.md).

## The bright line (read first)

The pass criterion is **a comparable prediction**, never "the engine ran" or "a wrapper exists". Every task
ships a **headless entry point** + a **reusable oracle that asserts a property** (anchor held, deflection along
field, descriptors agree within tol) — not HTTP 200, not "it completed". A feature that can't be measured
against another engine isn't coverage; it's a passthrough. End every session's log row with the mandatory
line: **"Comparable prediction gained, not just a run: ___."**

**Bright line for the U/P tracks** (different work, same rigor): the pass criterion is a **capability or a
de-duplication proven by an oracle**, never "the panel renders" or "a button exists". For **Track U** that's a
**per-engine PARITY test** — the unified card/base emits the *same payload the bespoke card produced today*
(shape/byte parity per engine), so consolidation provably changes nothing observable. For **Track P** it's a
**CHAIN test** — a stage runs *seeded from the previous stage's output*, and on a stage failure the chain
*halts and resumes from the failed stage* (not a full restart). End a U/P session's log row with:
**"Capability/de-dup proven, not just wired: ___."**

Three-Layer Law is absolute here: **every engine output is Physical/display-only.** Anchors + field specs are
**job-request annotations**, never `Design` edits. CanDo extra-base/linker *elements* are mesh-build details
derived from existing topology metadata (`Crossover.extra_bases`, `overhang_connections`) — not topology
mutations. If a task tempts you to write back to topology, stop and re-read.

## Manager decision rubric (how "next-best" is chosen)

Deterministic, re-runnable, grounded — state the pick + a one-line why *before* implementing, so the user can
veto.

1. **Eligible set** = tasks with `status == "pending"` whose every `dep` is `status == "done"`. (Parse the JSON;
   don't reason from memory.)
2. **Hard ordering (dependencies + physics):**
   - The **shared-metric track (S1–S5) leads.** No cross-validation *claim* is possible until the comparison
     card exists — `M-METRIC-CORE` is the first milestone. (A feature can be *built* before S-track, but its
     cross-validation result can't be *reported*, so prefer landing S first.)
   - Within an engine, feature deps hold: **anchors before E-field** (a uniform field needs ≥1 anchor or the
     structure just streams — the oxDNA COM-drift gotcha applies to every engine), **connector element (C3)
     before linkers (C4)**.
   - **The U/P tracks are the current priority** (2026-07-08) over the parked feature tail (M4/N3/O2). Their
     deps: **U1 (descriptor) before U2/U3**, **U2+U3 before U4 (the consolidation)**; **P1 (MdPipeline) before
     P2/P3**, **P4 (planner UI) needs P2+P3+U2** (it reuses the unified Forces card). Prefer landing **U1 and
     P1 first** — each is the foundation its track builds on, and they're independent so either is a valid
     opener. The two tracks can interleave; finishing one track's in-progress task beats opening the other.
3. **Rank the eligible set by leverage** = `(coverage-gap closed) × (cross-validation value) / effort`,
   with a bonus for **unblocking a milestone** (especially `M-METRIC-CORE`, then `M-CANDO-FIELD` — the headline
   result: does the cheap FEM predict oxDNA's field deflection?).
4. **Prefer finishing an in-progress track** over opening a new one (context locality).
5. **Tie-break:** the handoff's `▶ NEXT`, else lowest `effort`.
6. **One task per session.** Single main loop. Use **read-only subagents** only for (a) investigating the target
   engine's current code and (b) a fresh-context diff-vs-plan review. **Do NOT spawn implementer swarms** —
   multi-agent coding is ~15× tokens with poor real-time coordination (Anthropic multi-agent-research finding);
   it's the wrong default for a solo-dev implementation loop.

## Per-session loop protocol

1. **Resume.** Read the `▶` handoff below + `git log -5` + `sim_coverage_plan.json`. Run `just smoke` (or the
   relevant fast check) **before new work** to catch a regression from a prior session.
2. **Pick.** Compute the eligible set + rank (rubric). If a `/continue-coverage <TASK-ID>` arg was given, use
   that (still verify its deps are met). State: *"Picking `<ID>` — `<one-line why>`."*
3. **Investigate.** `rg` the real seams for this engine/feature (a read-only subagent if it spans many files).
   Confirm the plan's named functions/routes still exist. **Any confusion about DNA topology, polarity, or
   which layer a change belongs in → ask the user first, implement nothing** (CLAUDE.md).
4. **Oracle first.** Decide the oracle form and write it (or its skeleton) *before* the feature — a property
   assertion, not a smoke run. Set `task.status = "in_progress"`.
5. **Build.** Module-first (`initX({deps})→{api}` / `backend/core` service; `backend/core` imports nothing from
   `backend/api`). `main.js` gains only imports + factory init + thin wiring (cite LOC Δ; must stay flat).
   Metrics land in the **shared card pattern** (generate → view → export PNG/CSV — §"Metrics are a hard
   requirement").
6. **Fast/slow tag.** Oracle math, descriptor computation, card pure-helpers, conf-emission checks → **fast**
   (run in `just test` / `just test-frontend`). Real engine runs (oxDNA CUDA, NAMD, mrDNA ARBD, CanDo nonlinear
   on a large design) → **slow**: add the test's module basename to `_SLOW_MODULES` or its function name to
   `_SLOW_TESTS` in [`tests/conftest.py`](tests/conftest.py) (the repo mechanism — a central registry auto-marks
   `slow`; there is **no** `NADOC_RUN_*_SLOW` env gate). `just test-fast` (`-m "not slow"`) must stay ~fast.
7. **Gate.** Oracle green; `just test` (or `just test-fast` for a fast-only task — say which) + `just lint`
   clean; `just test-frontend` + `just smoke` for stateful frontend. Cite pass counts; flag any drop.
8. **Display-vs-oracle check (per new validation/card).** Write a **one-off** Playwright spec that loads a
   doc-pinned design, runs/mocks the engine, opens the card, **scrapes the displayed numbers/graph and asserts
   they equal the headless oracle's numbers** (within tol) + screenshots. **If displayed ≠ oracle, STOP and ask
   the user** — the card may be measuring something different than the oracle believes. Then delete the spec
   (troubleshooting-only) and file an `MV-N` row in [`manual_validation_debt.md`](manual_validation_debt.md)
   for the standing human-eye check.
9. **Review.** A fresh-context read-only subagent reviews the diff against this task's plan entry:
   *"correctness + does it satisfy the stated oracle; flag only real gaps, not style."* (Adversarial reviewers
   invent gaps otherwise.)
10. **Commit (auto, to master).** After the gates are green: **one descriptive commit to master** —
    `feat(<engine>-coverage): <task> + <oracle>` with the repo's co-author trailer. **No push** (the user
    pushes per the two-computer protocol). Auto-commit is authorized *for this loop only*, giving each session a
    clean git checkpoint (harness recovery pattern). Anything not green does NOT commit.
11. **Record.** Set `task.status = "done"` (+ `notes` if useful) in the JSON; derive milestone `status`. Append a
    log row (oracle catalog entry if the oracle is reusable) + a metrics row (with the mandatory justification
    sentence). **Overwrite** the `▶` handoff below (≤8 lines). Route: a bug → `issues_ledger.md`; a
    can't-headless pixel op → `MV-N`; genuinely stuck → set `status="blocked"` + `notes`, log the difficulty,
    and pick a different eligible task or ask.

## Metrics are a hard requirement (generatable · viewable · exportable)

Every new engine metric and the cross-engine comparison MUST be **generatable, viewable, and exportable as data
or PNGs**, mirroring the shipped oxDNA/MD metrics cards
([`memory/project_oxdna_metrics_card.md`](memory/project_oxdna_metrics_card.md)). Reuse the shared machinery —
do **not** rebuild it:
- **Backend:** `backend/core/<engine>_trajectory.py` (or `shape_metrics.py` for the comparison) with a one-pass
  `*_metric_series(...)` + `count_*_frames`; `backend/api/routes_<engine>_metrics.py` daemon-thread registry
  (`POST .../metrics/start` + `GET .../metrics/{run_id}`, register in `main.py`).
- **Frontend:** a **thin** `<engine>_metrics_card.js` binding `idPrefix` + client `start/poll` fns onto the
  shared `initMetricsCard({...})`; reuse `metric_graph.js` (vanilla-canvas chart, **PNG = `canvas.toDataURL`**),
  `metric_graph_popup.js` (Display), `metric_export_modal.js` (**PNG / Data / Both**, CSV from `metricCSVs`).
  `main.js` LOC Δ = 0. Refresh on `nadoc:design-changed`.
- The **comparison card** (`shape_compare_card.js`, task S5) overlays each engine's descriptor profiles (RMSF,
  deviation), a scalar table with per-observable deltas, and agreement scores — same generate/view/export.

## The cross-engine comparison metric (per-observable reference)

Every engine already emits a display-position map keyed `(helix,bp,dir,copy)` for its overlay
(oxDNA `/display`, CanDo `deformed_positions`, mrDNA `_display_positions`, NAMD md frame). **The metric layer
sits on top of that shared substrate** — `compute_shape_descriptors(positions, design)` is engine-agnostic.

**Descriptor set:** global twist (total ° and °/turn) · bend angle (arc-span) + radius · radius of gyration ·
end-to-end · per-bp RMSF · per-nt deviation-from-design (+ RMSD) · per-nt E-field deflection (map, free-region
projection-along-field, anchored drift). RMSF needs an ensemble/NMA source per engine (CanDo NMA; oxDNA/NAMD/
mrDNA trajectory variance).

**Reference per observable** (user decision, 2026-07-05): **oxDNA** = relaxed shape + field-deflection;
**CanDo** = RMSF/flexibility (the experimentally-validated flexibility tool); **NAMD** overrides as gold for any
observable once a NAMD run for that design exists. `compare_descriptors` emits: scalar signed %-delta,
RMSF Pearson/Spearman, aligned-shape RMSD (Kabsch, reuse `_rigid_superpose`), field-deflection cosine similarity
+ magnitude ratio.

## Per-engine phased plan (narrative — live status is the JSON)

**Shared-metric track (S) — leads; gates all cross-validation.**
`S1` shape descriptors → `S2` RMSF/deviation → `S3` compare_descriptors (per-observable reference) →
`S4` unified field-response → `S5` comparison card (generate/view/export). = **M-METRIC-CORE**.

**CanDo FEM (C) — highest leverage: cheapest engine, most missing features, cleanest seams.** Seams confirmed:
`assemble_prestress_force` ([fem_solver.py:455](backend/physics/fem_solver.py#L455)) is the load-vector to add
q·E to; `apply_boundary_conditions` ([fem_solver.py:552](backend/physics/fem_solver.py#L552)) is the Dirichlet
seam to generalize for anchors; `predict_shape` ([fem_solver.py:1071](backend/physics/fem_solver.py#L1071))
gains `anchors=`/`field=`.
`C1` anchors (Dirichlet BC) → `C2` E-field (q·E nodal load) [**M-CANDO-FIELD** with S4/S5/O1: does the FEM
predict oxDNA's deflection?] → `C3` extra bases as FJC/nick-soft elements → `C4` linkers as connector elements →
`C5` feed the card. = **M-CANDO-COMPLETE**.

**mrDNA (M) — via ARBD external forces.**
`M1` anchors (ARBD restraints) → `M2` E-field (ARBD constant/grid force) → `M3` extra bases into the ARBD model
→ `M4` linkers into the model → `M5` metrics card + RMSF (fix the `_display_positions` copy-key gap).

**NAMD (N) — native features, mostly unwired.**
`N1` emit native `eField` in conf + UI → `N2` anchors picker on the existing consref/conskfile restraints →
`N3` extra-base/linker validation coverage (already atomistic) → `N4` bridge md RMSF into the shared card as the
gold-override source.

**oxDNA (O) — reference/maintenance.**
`O1` emit shared descriptors (the reference column) → `O2` close residual gaps as logged.

**M-ALL-ANCHORS-FIELD** = every engine runs an anchored field job with a comparable deflection descriptor.
**M-FULL-COVERAGE** = all engines × all four features, all feeding the card.

**Unified panel (U) — proposal A. Consolidate 6 panels → 1, proven by parity.** Seams (from the UI inventory):
already-shared = `metrics_card.js` (bound by 3 thin ≤21-line files — the proven pattern to copy), `job_tree.js`
(`flattenJobTree`, engine-agnostic), `md_engines_logic.js` (`ENGINE_ORDER` gating), and the physics math
(`efield_math.js`, `oxdna_floor_math.js`). Still bespoke = the 5 `*_jobs_panel.js` shells + the *triplicated*
E-field/Anchors/Surface DOM (`efield_setup.js` vs `cando_efield_setup.js` vs `lammps_forces_setup.js`, sharing
math not markup).
`U1` capability descriptor (the data that drives one card stack) → `U2` shared Forces card factory (kills the
triplication) → `U3` shared jobs-panel base (run buttons + job list) → `U4` engine selector + one *Simulate*
section, unsupported cards greyed-with-tooltip (NN/G spatial-consistency, CHARMM-GUI model). = **M-UNIFIED-PANEL**.

**Job planner (P) — proposal B. Chain jobs that run unattended.** Today chaining exists only as three
special-cased provenance hops (`parent_job_id` + `run_kind="production"`, `seed_oxdna_job_id`,
`seed_mrdna_job_id`); there is **no** generic pipeline object. `job_tree.js` already *reconstructs* the
provenance DAG, so the data model is half-built.
`P1` `MdPipeline` stage-spec object (generalize the three hops into one ordered list) → `P2` chain executor
(submit stage N+1 on N's completion; halt + resume-from-failed-stage per LogRocket) → `P3` cross-engine
output→input (oxDNA relax → NAMD production, right coordinate convention) → `P4` linear stage-builder overlay
(reuses U2's Forces card per stage; duplicate-stage for a field sweep). = **M-JOB-PLANNER**.
**M-DEPOSITION-CHAIN** (headline, mirrors M-CANDO-FIELD) = the *E-field→surface → anchors → field-sweep* chain
runs unattended from one Plan Run (P1+P2+P4+U2; reuses the already-done N1 field + N2 anchors plumbing).

## Single-line invocation

> `/continue-coverage` — read `sim_coverage_plan.json` + the handoff, pick the highest-leverage eligible task,
> build it with an oracle, validate (fast/slow-tagged) + one-off display-vs-oracle Playwright check, auto-commit
> to master, update the JSON status + log + metrics + this handoff. (Optionally `/continue-coverage <TASK-ID>`.)

## Next-session handoff

*Living pointer — OVERWRITE this each session (protocol step 11). Keep it ≤8 lines. Live task status is the JSON,
not here.*

- ▶ STATE — **`P2` DONE 2026-07-08** (chain EXECUTOR). `backend/core/md_chain_executor.py` = an engine-agnostic state machine turning a P1 `MdPipeline` into a live self-advancing chain: stage N spawns SEEDED FROM stage N-1's realised child on completion (`next_spawn` picks `parent_job_id=prev.job_id`); a stage FAILURE HALTS (no downstream); `resume_chain` retries-ONLY-failed (completed stages keep their job_id + `done`, never re-run). Injected `spawn`/`job_status` callbacks; primitives `reconcile_running`/`next_spawn`/`mark_spawned` (async driver awaits a real spawn between two pure transitions), `step_chain` composes them sync. Persistence → `workspace/md_chains/{id}/chain.json`. `stage_forces_conf` reuses `external_forces_block`. NAMD wiring in the API layer: `routes_md._chain_spawn` REUSES `spawn_md_production` verbatim; `advance_chains` driven by the MD supervisor = unattended; `POST /md/chains`+`/resume` routes. CHAIN oracle 12 FAST (RED-verified, 2 mutants) + 4 route (real stage-0 child). Three-Layer clean. main.js LOC-Δ=0. Also DONE: P1, U1 (both 2026-07-08). Feature tail (M4/N3/O2) parked.
- ▶ NEXT — **stay on U/P.** Track-P openers (both unblocked): **`P3`** (cross-engine output→input — generalize `seed_oxdna/mrdna_job_id` so a stage hands one engine's relaxed coords to another in the right coordinate convention; the `cross_engine` flag P1 already sets marks the hop; FAST parity-with-the-existing-seed-hop, SLOW real oxDNA→NAMD handoff) — natural next toward the deposition chain; **or `U2`** (shared Forces card factory — collapse triplicated `efield_setup.js`/`cando_efield_setup.js`/`lammps_forces_setup.js` into `initForcesCard({engine,deps})` over `efield_math`/`oxdna_floor_math`, grey unsupported per U1; **ADAPTED-CODE PIN RULE** applies, owes an MV row). **`P4`** (planner UI) needs P2✓+P3+U2, so it's not yet open. U3 (jobs-panel base) unblocked too (dep U1). **P2 FOLLOW-UP owed:** thread stage forces into the production *reseed* conf end-to-end (`ProductionRunRequest.field`/`anchors` + emission) + a live 2-stage-chain MV row.
- ▶ U/P BRIGHT LINE — prove a **capability or a de-duplication**, not "it renders"/"a button exists". Track U = **per-engine PARITY** (unified card emits the same payload the bespoke card did). Track P = **CHAIN** (stage N seeded from N-1; halt + resume-from-failed-stage). Log row ends: "Capability/de-dup proven, not just wired: ___."
- ▶ ⚠ PRE-EXISTING xdist ISOLATION FLAKE — non-deterministic 1-test failure (`test_job_archive` / `test_cando_extra_bases`, different victim each run, BOTH pass isolated, unrelated to these tracks). Root = `test_md_milestone1.py::TestProductionAppend._routes_md` leaks a stubbed `backend.api.routes_md` into `sys.modules` (see `memory/project_test_parallelization.md`). Out of loop scope; don't chase.
- ▶ SEAMS (from the UI inventory) — already-shared to REUSE: `metrics_card.js` (the thin-binding pattern to copy), `job_tree.js`, `md_engines_logic.js`, `efield_math.js`/`oxdna_floor_math.js`. Still-bespoke to CONSOLIDATE: 5 `*_jobs_panel.js` + the triplicated `efield_setup.js`/`cando_efield_setup.js`/`lammps_forces_setup.js`. Chaining primitives to GENERALIZE: `MdJob.parent_job_id` + `run_kind="production"` + `seed_oxdna/mrdna_job_id`.
- ▶ REFERENCE — per-observable: oxDNA=shape+field, CanDo=RMSF, NAMD=gold-when-present. Metrics MUST be generate/view/export. Auto-commit to master, no push. Live 4-engine eyeball owes **MV-21**; U4/P4 will each owe a new MV row.

## Don't

- Don't mark a task `done` without its oracle passing (evidence, not "it ran"). Don't edit/remove tests to go
  green. Don't add/reorder/rewrite JSON tasks (status + notes only).
- Don't rebuild the metrics-card machinery — bind the shared factory. Don't grow `main.js` with cohesive logic.
- Don't spawn implementer swarms (single main loop + read-only investigation/review subagents only).
- Don't write engine output back to `Design` topology (Three-Layer Law). Don't reason geometrically about
  crossovers/polarity — ask first.
- Don't run broad Playwright suites in the routine cycle — one-off, deleted after verify, then an `MV-N` row.
- Don't push to remote (the user pushes). Don't skip the pre-work smoke check.
