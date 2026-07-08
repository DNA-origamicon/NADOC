# Full simulation / feature-coverage loop

Drive all four structure-prediction engines — **CanDo FEM · mrDNA · oxDNA · NAMD** — to cover the four
unconventional design features (**extra crossover bases · linkers/overhang connections · E-fields · anchors**)
AND emit a **shared, comparable set of prediction descriptors** so the engines cross-validate one another
across the quick→rigorous continuum.

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

## Single-line invocation

> `/continue-coverage` — read `sim_coverage_plan.json` + the handoff, pick the highest-leverage eligible task,
> build it with an oracle, validate (fast/slow-tagged) + one-off display-vs-oracle Playwright check, auto-commit
> to master, update the JSON status + log + metrics + this handoff. (Optionally `/continue-coverage <TASK-ID>`.)

## Next-session handoff

*Living pointer — OVERWRITE this each session (protocol step 11). Keep it ≤8 lines. Live task status is the JSON,
not here.*

- ▶ STATE — **M-METRIC-CORE DONE** (S1–S5); **M-CANDO-FIELD/COMPLETE DONE** (C1–C5); **NAMD anchor+field pair DONE** (N1✓+N2✓); **M-ALL-ANCHORS-FIELD DONE** (CanDo C1/C2, NAMD N1/N2, mrDNA M1/M2). **`M5` mrDNA card-source DONE 2026-07-08 → the comparison card now carries THREE live engines (oxDNA O1, CanDo C5, mrDNA M5).** M5: `backend/core/mrdna_shape_source.py` `build_mrdna_shape_source(shape_frame, core_reference, *, rmsf=None, field=None)` — the O1/C5 twin, same SOURCE-BUNDLE CONTRACT: core-filter the relaxed display frame → ABSOLUTE `compute_shape_descriptors` + map a per-nt RMSF list. **CG-trajectory RMSF** = `mrdna_runner.mrdna_trajectory_rmsf(design, job_dir)`: reconstruct the per-nt frame at each DCD timestep (`nuc_pos_override_display_from_coarse` per frame, evenly subsampled to `max_frames=40`) → shared S2 `rmsf_from_ensemble(align=True)` (Kabsch strips CG box diffusion). **COPY-KEY GAP fix**: `_display_positions` emits crossover inserts as `{helix_id:"__xb__", bp_index:<crossover-id STRING>, direction:k}` — the string bp_index crashes the shared `_dev_key` (`int(bp_index)`); the gap bites the SHAPE column (`_filter_to_reference_core`/`_core_column_key` drop them before descriptors), and `_rmsf_profile` skips non-int bp defensively (the production RMSF path is int-key-only — no `__xb__` — since it uses the override, not `_display_positions`). Route `GET /mrdna/jobs/{id}/shape-source` (mirrors C5) → `{ready, n_frames, ...bundle}`. Frontend `api.getMrdnaShapeSource` + `getSources` → `[oxdna, cando, mrdna]`; `main.js` captures `const mrdnaPanel` + lazy `getMrdnaJob` (+4 LOC, no-TDZ like getCandoJob). Oracle `tests/test_mrdna_shape_source.py` 8 fast + 1 slow. `just test` 4352 passed / 72 skip / 1 xfail **+ 1 documented xdist active-design flake** (`test_namd_efield::test_no_field_skips_both_guards`, passes isolated + alongside — additive card code never touches `design_state`); vitest 2294; smoke 23. Field deferred (`field:None`, like O1/C5). Live mrDNA-column eyeball owes **MV-21** (updated w/ M5 slice).
- ▶ SOURCE-BUNDLE CONTRACT (proven by O1+C5+**M5**; reuse for N4) — each engine builds `{engine:"<lower>", descriptors:compute_shape_descriptors(core_frame), rmsf:[{helix_id,bp_index,direction,copy,rmsf_nm}], shape_frame:core_frame, field:...|None}` and returns it from `getSources`; **core-filter first** (`_filter_to_reference_core` vs `core_reference_geometry`), emit the engine's own ABSOLUTE descriptors. mrDNA RMSF source = `rmsf_from_ensemble` over per-frame reconstructions. **`main.js` capture-panel + lazy `get<Engine>Job` = +4 LOC pure wiring, no TDZ.**
- ▶ NEXT — Toward `M-FULL-COVERAGE`: **`N4`** (NAMD card-source **gold-override**, dep S5✓ — the 4th/last live column; reuse the SOURCE-BUNDLE CONTRACT; bridge existing md RMSF/metrics; when a NAMD run exists it OVERRIDES the reference per policy via `reference_for`), then mrDNA `M3` (extra bases into the ARBD model — verify past the display bridge, deps met) → `M4` (linkers, dep M3 — reuse C4's WLC-connector), NAMD `N3` (extra-base/linker validation, deps met), oxDNA `O2`. **Recommend `N4`** (finishes the card's engine roster; highest cross-val value; proven contract) — then the feature-coverage tail M3/M4/N3. **For N4: NAMD md RMSF from the trajectory (production_rmsf-style), shape from an MD frame; extra-base/linker softening → assert RMSF flexibility, NEVER a twist/bend direction.**
- ▶ SOURCE-BUNDLE CONTRACT (proven by O1+C5; reuse for M5/N4) — each engine builds `{engine:"<lower>", descriptors:compute_shape_descriptors(core_frame), rmsf:[{helix_id,bp_index,direction,copy,rmsf_nm}], shape_frame:core_frame, field:field_response_profile(...)|None}` and returns it from `getSources`. **A direction-less RMSF (CanDo NMA) emits `direction=None` — still pairs, `_rmsf_per_bp` collapses direction.** **Core-filter first** (`_filter_to_reference_core(frame, core_reference_geometry(design))`) so ssDNA ends don't skew twist/bend. Emit the engine's own ABSOLUTE descriptors (not a differential-vs-its-analytic). `build_comparison_report` + the card do the rest.
- ▶ REUSE — `build_comparison_report(sources)` → `{ready, engines, references{shape,rmsf,field}, scalars[{name,reference,cells{engine:{value,signed_pct_delta}}}], rmsf_profiles, agreement[{engine,shape_rmsd_nm,rmsf,field}], field{reference,rows[]}}`. Field/agreement reference resolves among **field-carrying engines** (not policy `references.field`). Math: `compare_descriptors`/`compare_field_response`/`reference_for` in `shape_metrics.py`.
- ▶ GOTCHAS banked — **extra-base/linker softening is NON-MONOTONE in a distributed load → assert RMSF flexibility (sign-safe, CanDo's observable), NEVER a twist/bend DIRECTION** (crossover-geometry reasoning forbidden; C3: inserts on ALL crossovers *lower* free-field projection while disintegrating the bundle to ~7nm RMSF — use a SUBSET/band; the compliant connector reuses existing nodes, no added mesh nodes). **"match existing values" is ambiguous: pin the ESTIMATOR not the UI graph** (O1: absolute vs differential twist — same `measure_bundle_twist`, different reference+frame; LESSONS-from-O1). **cross-engine RMSF collapses to per-bp before matching** (direction-keyed→silent None; S3). field-response NOT Kabsch-aligned (anchored region = common frame). Uniform field needs ≥1 anchor (COM-drift) in every engine (mrDNA: the runner RAISES if the field's anchors held 0 beads — chip-count ≠ resolved-beads); **ARBD constant force = a RAMP POTENTIAL `U=-(F·r)` via `add_grid_potential` (`arbdmodel.grid.constant_force`), NOT `forceXGrid` — the tabulated-force path CRASHES ARBD on a constant grid**; a CG bead's field force scales by its nt-content via its MASS (`nt=mass/dpn`; beads carry charge 0); a damped CG field oracle predicts OVERDAMPED drift `D·F·T/kT` (engine's own D), not ballistic ½at²; CanDo bend/twist exp36-calibrated (don't regress); every output Physical-layer only; pre-existing ruff debt (~20 errors in OTHER test files) — don't sweep (`feedback_no_bulk_reformat`).
- ▶ REFERENCE — per-observable: oxDNA=shape+field, CanDo=RMSF, NAMD=gold-when-present (`reference_for`). Metrics MUST be generate/view/export (mirror the oxDNA card). Auto-commit to master, no push.

## Don't

- Don't mark a task `done` without its oracle passing (evidence, not "it ran"). Don't edit/remove tests to go
  green. Don't add/reorder/rewrite JSON tasks (status + notes only).
- Don't rebuild the metrics-card machinery — bind the shared factory. Don't grow `main.js` with cohesive logic.
- Don't spawn implementer swarms (single main loop + read-only investigation/review subagents only).
- Don't write engine output back to `Design` topology (Three-Layer Law). Don't reason geometrically about
  crossovers/polarity — ask first.
- Don't run broad Playwright suites in the routine cycle — one-off, deleted after verify, then an `MV-N` row.
- Don't push to remote (the user pushes). Don't skip the pre-work smoke check.
