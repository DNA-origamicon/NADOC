---
name: md-job-system
description: Milestone 1 MD integration — new backend modules for managed NAMD jobs
metadata: 
  node_type: memory
  type: project
  originSessionId: baf07637-75d1-45c3-9ad6-60ff363faf17
---

Implemented Milestone 1 of the MD integration plan (memory/md_integration_plan.md).


## The Job Wizard: every parameter, per stage, with its provenance (2026-08-03)

Setting a NAMD job up used to mean a flat "Advanced" grid of ~17 controls that reflected
none of the four layers actually deciding a run's settings — the request field's default,
the preset merged over it, a server-side override that discarded both, and a per-stage
derivation inside the conf writer. The number on screen was frequently not the number that
ran, and the ladder was invisible.

**`POST /md/protocol-plan` is now the source of truth** (`backend/api/routes_md_plan.py` →
`backend/core/md_plan.py`). It does not DESCRIBE the protocol: it CALLS the real conf
writers (`_segment_conf`, `_min_conf`, `build_production_conf`) and parses their output, so
the plan *is* the conf and cannot drift. No disk, no job record, no solvation — safe to
re-request behind a 250 ms debounce as the user types. It returns:

- every effective request field with its **provenance** (`user` / `preset` / `default` /
  `forced` / `derived`) and the reason — this is how you can tell whether a control does
  anything (`salt_mode="screening"` reports `mg_conc_mM` as `forced`, with `overridden_from`);
- the ordered stage table with each stage's full directive set, its **diff vs the previous
  stage**, and which values are still `conditional` (GPU-resident, detected generically by
  emitting each stage twice and diffing, not by a hardcoded key list);
- `conditions` + `retries`, every threshold IMPORTED from the module that enforces it
  (`CutoffParams`, `MAX_*_RESUMES`, `PISTON_SOFTEN_FACTOR`, `_RESIDENT_MIN_ATOMS`);
- `deferred` — what only resolves at solvation (cell vectors; `minimize_steps` is a FLOOR).

**The ladder is 22 columns, not 12 segments.** Every note in this repo saying "12/12" was
stale: `LADDER_CHUNK_PCTS` has 5 entries, so 4 rungs × 5 chunks = 20, plus the minimisation
slot and the `_0S_` settle stage. A carve drops the settle stage → 21.

**`production_segment_spec` is shared** between the plan and `_append_production_segments`
(LESSONS H16): two independent constructions is how a fix lands on one call site only.

### UI shape

- `＋ New job` (`#md-jobs-new-btn`) opens `frontend/src/ui/md_job_wizard.js`; the pure
  shaping is `md_job_wizard_model.js` (92 vitest cases).
- **Two tabs, not one split screen (2026-08-05).** Tab 1 `Protocol & settings` = mode
  (relaxation/production) + preset cards + every setting, full width in a 3-column flow
  (`.wizard-fields { columns: 380px 3 }`), footer Cancel / **Next →**. Tab 2 `What each
  stage runs` = totals, the 22-column table, conditions; footer Cancel / Create job /
  Create & run. Create is only offered on tab 2 — a run is not creatable until its plan has
  been shown. `state.tab` is NOT undoable (a tab is not a choice about the run).
- **Undo (`↶ Undo` beside the tabs, Ctrl+Z).** One stack of pre-change snapshots
  (`snapshotState` / `applySnapshot` / `pushUndo`, `UNDO_LIMIT = 50`) covering settings
  fields, stage-table cells, `⋯` set-every-stage, protocol, mode and ⚡ alike; `record()` is
  called at the top of every mutating handler. A commit that changes nothing never records
  (identical top-of-stack is dropped), so undo is never a no-op press. Cleared on `open()`.
  Escape inside a cell editor now `stopPropagation`s — it used to close the whole modal.
- **The three integrator axes are SEPARATE controls (2026-08-05, exp51).** `backend/core/
  md_integrator.py` is the single resolver: `resolve_integrator(dt, rigid_bonds, hmr)` fills
  `None` from the timestep (rigid → `none` at 1 fs / `all` above; HMR → on only at 4 fs) and
  `integrator_warnings()` returns the measured objections. New request fields:
  `relax_timestep_fs` / `relax_rigid_bonds` / `relax_hmr` and `production_rigid_bonds` /
  `production_hmr` (tri-state: null = auto). `_segment_conf` and `build_production_conf` take
  `rigid_bonds=` / `hmr=` and no longer derive them from `spec.soft` / `fast` / `ts`; HMR is
  expressed by WHICH PSF is named, and 4 fs with no `structure_psf` now falls back to
  `{stem}_hmr.psf` instead of the plain PSF (that fallback was the silent-unrepartitioned
  hole). `PlanContext` carries both, so **the stage table reflects the chosen axes** — it
  previously showed the auto values while the job ran the chosen ones. **Warn, never block**:
  every unsound combination is a `warning` condition whose `source` is
  `CreateJobRequest.<field>`, which is what places it (⚠ + `(Cn)`) against its own control.
  `plan.field_scopes` declares which run each field governs; the wizard groups its settings
  into **Relaxation ladder / Production run / Both runs** from it. The `fast` checkbox is
  retired from the UI (the backend field remains, and is what `relax_timestep_fs: None`
  falls back to, so old clients and saved drafts are unaffected).
- **The integrator controls are three plain widgets (2026-08-05).** Now that the axes are
  decoupled, the UI stopped explaining the coupling: **Timestep** is a dropdown reading
  `4 fs (faster, risks RATTLE)` / `2 fs (standard)` / `1 fs (conservative)` (same labels for
  ladder and production), and **rigid bonds** and **HMR** are plain CHECKBOXES, not
  auto/on/off dropdowns. A box shows the value the run will USE — untouched it follows the
  timestep's recommendation via the field's `fallback(plan, effectiveValue)`; ticking it
  makes the choice explicit and any mismatch raises its own ⚠ + `(Cn)` against that control.
  `effectiveValue()` exists because a fallback that reads a SIBLING (both boxes follow the
  timestep) must resolve that sibling's own fallback: an untouched timestep is stored as
  null and `Number(null)` is 0, which read as "1 fs" and left both boxes unticked on a 4 fs
  ladder. Field options: `check` maps the field's vocabulary onto the box ("all"/"none"),
  `parse` maps it back.
- **`Run every stage soft` is REMOVED from the wizard** — it is exactly
  `timestep 1 fs + rigid bonds off`, pinned by `TestForceSoftIsExpressible`. The backend
  `force_soft` field stays (the runner's automatic post-RATTLE rescue uses it).
  Writing that test found a bug: **`soft=True` capped every stage to 1 fs but sized step
  counts from the UNCAPPED timestep**, so a soft ladder ran 2.4 ns/stage from a 2 fs base
  and 1.2 ns from a 4 fs base instead of 4.8. `mgh_slow_release_segments` now sizes from
  `sizing_dt = 1.0 if soft else timestep_fs` (ladder stages AND the settle stage).
  `gentle` is deliberately NOT capped there — that is the declash half-length question,
  which has its own re-audit block and a test pinning it, and needs an experiment.
- **No setting silently changes a user's input any more (2026-08-05 removal pass).**
  Audited the whole MD subsystem for value substitutions; the ones that were invisible are
  gone or surfaced:
  - **Ladder tiers are a CEILING, not a fixed value** (`effective_timestep_fs(spec, fast,
    base_timestep_fs)`). They used to RAISE an explicit `relax_timestep_fs=1.0` to 2 fs
    while step counts stayed sized for 1 fs, so every stage ran **double** its intended
    time and the control looked inert. `md_plan` made the same call without the base, so
    the preview reported 2 fs and 2x the ns for confs that said 1 fs. Both fixed; a 1/2/4 fs
    ladder now totals ~19.5 ns as designed.
  - **The auto water-shell carve is REMOVED.** Prep computes the recommendation and records
    it as `prep_params.recommended_water_shell_nm`, and never applies it. The plan emits
    `water_box_will_not_fit` (source `CreateJobRequest.water_shell_nm`) so the wizard shows
    a ⚠ against the control. The old `auto_water_shell_nm` / `declined_water_shell_nm` keys
    had no reader anywhere and are gone.
  - **The CUDA tile-list CPU reroute now ASKS** — Gate **B2**, `job.decision.gate ==
    "cpu_reroute"`, same payload shape and modal as Gate B. It used to swap to the ~12x
    slower CPU build with only a log line. `resolve_gpu_decision` accepts `choice="cpu"`;
    acceptance is recorded as `prep_params.cpu_reroute_accepted` so a resume does not
    re-ask. `md_gate_b.hasPendingGpuDecision` matches both gates.
  - `ProductionRequest.dcd_freq` was validated, documented and used by the disk forecast,
    then dropped on the route that runs — now honoured (`production_segment_spec(dcd_freq=)`).
  - The missing-PSF 4 fs→1 fs downgrade and the from-seed 1 fs force now say so (warning
    text + `manifest.production_extension.integrator_downgrade`).
  - `estimate_md_disk` derived its timestep from `fast` alone; it now mirrors prep's tiers.
- **⚡ Optimize prefers a MEASUREMENT over the table** — `md_bench_probe.py` runs two confs
  differing by one line on the solvated package, reads NAMD's own `Benchmark time:`, and
  caches per **(GPU, NAMD build, thread count)** + size bucket in `workspace/
  md_bench_cache.json`. `md_optimize.gpu_resident_pays(n, workspace=, machine=)` consults it
  first and falls back to `_RESIDENT_MIN_ATOMS` only when unprobed. Seeded with exp52: at
  32.7k atoms the measurement says resident (True), the table says offload (False).
  `K_GPU_RESIDENT`/`K_OFFLOAD`/`_SMALL_SYSTEM_RESIDENT_PENALTY` remain the unprobed
  fallback and are now documented as extrapolations from one design on one card.
- **GPU-resident is decoupled from the timestep (2026-08-05, exp52).**
  `md_integrator.resident_decision()` is the single resolver for BOTH writers — hard
  incompatibility (GBIS / vacuum / fixed atoms / carved cell under `_RESIDENT_MIN_FILL`) →
  the user's explicit choice → the `_RESIDENT_MIN_ATOMS` size crossover. The timestep is
  **not an input** (a test pins that). `build_production_conf`'s `gpu_line = "" if ts == 1.0`
  is gone: it discarded an explicit `force_resident=True` at 1 fs. Measured on 2hb_1xT
  (32.7k atoms, RTX 2080 SUPER): resident is accepted and engages at 1/2/4 fs and is
  **1.86–2.06× FASTER** — which *contradicts* the ~100k-atom crossover that constant
  encodes. `_RESIDENT_MIN_ATOMS` is deliberately LEFT at 100,000 (it was measured on a
  3080 Ti at +p16); it is now a stated default the user's choice overrides, and the plan
  says which of the three rules decided it via the `gpu_resident_gate` condition, whose
  `source` is now `CreateJobRequest.gpu_resident` so it renders against that control.
  A choice that cannot be honoured is a `warning`, not a footnote. **K6's rider
  ("4 fs only survives under GPUresident") is refuted** — corrected in `LESSONS.md` and in
  `strip_gpu_resident`'s docstring.
- **`Timestep` (was "Production timestep") is the PRODUCTION integrator and is independent
  of `Fast relaxation`** (checked against the code 2026-08-05). `fast` sets the LADDER
  (4 fs vs 2 fs on hard segments; soft stays 1 fs, gentle 2 fs) and writes `{stem}_hmr.psf`
  at prep. `production_timestep_fs` is written to the manifest and read back by
  `_production_fast_plan` (`routes_md.py:1420`), which re-decides HMR itself — 4 fs builds
  the HMR PSF **on demand** even from a non-fast package (`routes_md.py:1543`), 1/2 fs use
  the plain PSF even from a fast one. So "fast on + 2 fs" is a legal, meaningful pairing,
  not a contradiction, and nothing overrides anything. Each option really does change more
  than the number (`build_production_conf`, `md_protocols.py:1117-1138`): 4 fs = rigidBonds
  all + HMR PSF, 2 fs = rigidBonds all + standard masses, 1 fs = rigidBonds **none** + no
  GPUresident line. The dropdown says so. Gap worth knowing: no validator couples them —
  `build_production_conf(timestep_fs=4.0, structure_psf=None)` would emit 4 fs against an
  unrepartitioned PSF; unreachable from the routes, which always pair them.
- **Conditions are labelled C1…Cn** (`conditionBadges` assigns them AFTER the sort, so the
  list order IS the numbering). Everywhere a condition applies, it is referenced as a
  hyperlink-styled `(C1, C4)` — hover gives the whole text, click switches to tab 2 and
  flashes it. References sit on: a stage column header (`conditionsByStage`), a settings
  field (`conditionsByField`, matched ONLY on the backend's own
  `source: "CreateJobRequest.<field>"` — never guessed from wording), and the totals line
  for `applies_to: "all"` conditions (`allStageConditions`), which would otherwise repeat
  on 22 identical column badges.
- `▶ Run` (`#md-jobs-run-btn`) is now ONE control over the SELECTED job — Run / Stop /
  Resume, via `runControlState`. `#md-jobs-job-ctl-btn` and `#md-jobs-prod-btn` are gone,
  and with them `mdSelectedJobControl` / `mdProductionAction`. A production child gets
  Stop/Resume like anything else.
- **Created ≠ started.** "Create job" sends `autostart:false`: the package is solvated and
  the job waits at `queued`, so every deferred value becomes real and Run is instant.
  `simulate_jobs.nodeNeedsPolling` (NOT `nodeIsActive`) stops the 1.5 s poll for such a job.
- The wizard sends **only touched fields + `relax_preset`**. The old panel sent every field
  unconditionally, which marked them explicit in `model_fields_set` and defeated the preset
  it was meant to follow — that is why the client-side merge mirror existed. It is gone.
- Production mode hides the preset cards (a relax preset says nothing about production) and
  labels each relaxation `"<part> run created YYYY-MM-DD HH:MM"`, never a job id.

### Production mode reached parity with relaxation (2026-08-06)

Setting a production run up through the wizard was half-built: it opened on a blank
relaxation form whatever was selected, it previewed a run it was not about to create, and
its settings were six hand-written controls with no provenance chip, no condition
reference and no warning icon. All of it is now the same machinery the ladder uses.

- **`＋ New job` on ANY selected completed run opens on Production, seeded from THAT run**
  (`md_jobs_panel.js` `newBtn` handler → `_wizard.open('production', {parentJobId})`).
  `open()` takes `parentJobId`; `ensureParent` no longer clobbers it, and
  `productionParents(..., {includeJobId})` keeps a deliberately chosen parent in the picker
  even when the part filter would drop it. `isProductionParent(job)` in the model is the
  ONE test both sides use, so the button and the picker cannot disagree.
- **An ARCHIVED relaxation is a legal parent now.** Archiving is a *disk* decision — the
  job dir moves to the archive drive and `MdJob.package_dir` follows it — and the spawn
  route always accepted one. The old `!j.archived` filter meant that on a machine where
  every finished relaxation had been archived to reclaim space (this one), production mode
  could only ever say "no completed relaxation for this part yet". The picker labels it
  `(archived — needs the archive drive mounted)`.
- **THE plan was of the wrong route.** `_production_plan` used
  `md_plan.production_stages` — the 10/40/50 % chunk ladder of the LEGACY append route
  (`POST /md/jobs/{id}/production`). The wizard's Create hits
  `POST /md/jobs/{parent}/production-run` → `md_ensemble.build_replica_package`, whose
  package is a **velocity reseed + ONE unchunked production conf**. So the table's first
  column carried 10 % of a step count for a run that was never going to be split, and its
  override indices were off by one against the builder's (`overrides_for_stage(…, 1)`).
  New `md_plan.replica_production_stages` / `replica_production_spec` / `reseed_parameters`
  mirror the builder; `production_stages` stays as the append route's model.
  `_stage_row` gained `accepts_overrides` (False on the reseed — the builder writes that
  conf without an overrides pass, so the column renders locked rather than accepting an
  edit it would drop).
- **Tab 2 is the relaxation stage being continued, then every stage the child runs.**
  `productionColumns(plan)` builds `[last_relax_stage (read-only reference), reseed,
  production]`; `changed` is computed against the RELAXATION column, not the previous
  stage. Rows are the union INCLUDING the relaxation's own directives (`paramRowsFor`), so
  a directive that exists only there — the ladder's ENM, its fixed atoms — still gets a
  row. Production cells are click-to-edit + `⋯` exactly like the ladder's.
- **Every production setting is a `renderField` descriptor** (`PRODUCTION_FIELD_DEFS`,
  grouped `This production run` / `Integrator and hardware`), so all of them carry a
  provenance chip, a `(Cn)` reference and a ⚠. Three controls that did not exist are
  there: **GPU-resident** (it was *sent* from `valueOf('gpu_resident')` but never drawn, so
  it could only ever be the package's default), **production rigid bonds** and **HMR**.
  Plus **velocity seed** and the undersized-cell override.
- **`ProductionRunRequest` gained `rigid_bonds`/`hmr`** — the sibling `ProductionRequest`
  has carried them since exp51, so every off-diagonal combination exp51 measured was
  unreachable from the one route the wizard uses. `build_replica_package` takes them too:
  `use_fast` is now `fast if hmr is None else hmr`, and the 4 fs→1 fs downgrade keys off a
  genuine **`hmr_build_failed`**, not off `not use_fast` — an explicit `hmr=False` at 4 fs
  is a warned-but-allowed choice, and treating it as a failed repartition silently ran a
  quarter of the requested time. The child manifest records the resolved
  `production_{timestep_fs,rigid_bonds,hmr}` so the next hop reads them instead of
  re-deriving.
- **New provenance: `inherited`** — "from the relaxation", i.e. recorded when the package
  was prepared. Distinct from `default` (nobody chose it). Served in a separate
  `plan.production_request` block, because the four shared keys resolve differently there:
  the create-request merge reports the PRESET's value while a child inherits the
  manifest's. `productionField(plan, key)` reads that block first, `plan.request` second.
- **`plan.inherited`** — parent, protocol, seed checkpoint, **real solvated atom count**
  (read from the package PSF, so GPU-resident is a fact rather than a deferred cell), cell,
  padding, ions, ladder base timestep, anchors, field. Rendered as a read-only
  "Inherited from this relaxation" block: a child hardlinks its parent's topology and
  copies its cell, so a control for any of it would be a control that does nothing.
- **Conditions now name the CONTROL that owns them** — `ProductionRunRequest.enm_restraints`
  / `.langevin_damping` / `.length_ns`, `CreateJobRequest.production_timestep_fs`. They
  used to be sourced to private helpers (`routes_md._assert_cell_fits_a_free_run`), which
  matches no field, so every production warning — including the one BLOCKING condition —
  sat in a list with nothing beside the control the user had to change.
  `REQUEST_SOURCE` in the model accepts both request models.
- **`WIZARD_DEFAULT_PRODUCTION_NS = 100.0`** lives in `routes_md_plan` and is returned in
  `plan.defaults`. `ProductionRequest.length_ns` falls back to 1 ns, which is a fine API
  default and a useless form one: the preview would show a 1 ns run while the control read
  100. The wizard reads the number rather than carrying its own, and an untouched length
  honestly reports `default` instead of "you set this".
- Production's five bespoke state slots (`lengthNs`/`dcdFreq`/`enmRestraints`/
  `langevinDamping`/`allowUndersizedCell`) are gone — they are ordinary `touched` entries,
  which is what let them render through the shared field machinery. `productionPayload`
  takes `{touched}` and sends **only what was touched** (renaming the two integrator axes
  to the spawn request's own field names), same law as `wizardPayload`.
- ⚡ Optimize is hidden in production mode: it recommends solvation and ladder settings,
  and a child re-solvates nothing.

#### Chaining: a completed PRODUCTION is a parent too (2026-08-06)

The backend has ALWAYS chained — `_production_seed_checkpoint` branches on `run_kind`,
`_completed_production_checkpoint` picks the last finished production segment, and
`build_replica_package` sets `continuation = parent.run_kind == "production"`, which stages
the parent's `restart.{coor,vel,xsc}` and makes the bridge conf *preserve* velocities. Only
the UI had no way to ask for it, and the plan endpoint DESCRIBED it wrongly.

**The distinction is the whole feature, and it is scientific, not cosmetic.** Off a
relaxation the child redraws velocities → an INDEPENDENT sample. Off a production the
velocities carry → it EXTENDS that trajectory, its frames are correlated with the parent's,
and the pair is one longer run. Treating the second as the first double-counts.
`plan.continuation` drives every sentence that differs; the picker labels each option
`… relaxation created …` / `… production run created …` (they read as duplicates otherwise),
and the help under it renders in `--strong` (warning-bordered) for a continuation.

What was wrong before, all now fixed and pinned:

| | Was | Now |
|---|---|---|
| Reference column | the parent's production segment run back through the **ladder's** conf writer (`stage_parameters`), inventing differences that were artefacts of the wrong emitter — `stepspercycle` 20 vs 10, the piston, the pairlist | `production_parameters` when the source stage is a production; the six ladder-vs-production `asymmetries` are suppressed entirely for a chain |
| `auto` restraints | looked for `relax_preset` on a production-only manifest, found none, fell through to **unrestrained** — silently dropping the network halfway along a chain | reads the parent's `production_recipe.enm_restraints`/`.langevin_damping`: a continuation inherits what it continues |
| Chemistry | `mg_conc_mM`/`ion_conc_mM`/preset read off the immediate parent → blank, "protocol (unrecorded)" | `routes_md.root_relaxation(job)` walks the parent chain; `inherited` also gains `root_job_id`, `chain_position`, `parent_length_ns` |
| Seed copy | "so repeated runs sample independent trajectories" — the opposite of what a continuation does | branches: in a chain the seed drives the Langevin stream from the inherited velocities on, it does not choose them |
| `last_relax_stage` | the key name was a lie on every chained plan | renamed **`source_stage`** `{name, stage, kind, params}`; tab 2 heads it `Continuing — …` vs `Relaxation — …` |
| Chain source health | `_completed_production_checkpoint` has **no health gate** (unlike the relaxation path) and nothing said so | new `chain_source_health` condition — info when the last sample passed or none was taken, warning with the measured C1′ when it failed. Warned, never blocked |

Also: `renderField` now renders the provenance **reason** and the field **help** as separate
lines. Reason used to REPLACE help — harmless while most reasons were empty, but once every
production field had one, every production control lost its explanation to a one-line
provenance note. A field's `help` may now be a function of `{continuation}`.

Pinned by `md_job_wizard_model.test.js` (137), `tests/test_md_protocol_plan.py` (119 — incl.
end-to-end fixtures for both a real relaxation package AND a chained production child),
`tests/test_md_ensemble.py` (the exp51 axes on the spawn path, incl. a
byte-identical-when-untouched pin), and the read-only live-server spec
`frontend/e2e/production_wizard.spec.js` (7).

**Still open:** there are no production PRESETS (the tiers are relaxation-only); the panel
still owns the environment for a production spawn (anchors, run target, E-field), which is
deliberate but means those choices are not in the wizard's own summary; and nothing yet
*renders* a chain as a chain — `chain_position` is stated in the wizard but the job list
still shows each leg as an independent child of the relaxation.
- The Advanced drawer is DELETED. Early-stop's *live* mid-relax role moved to
  `#md-jobs-live-controls`, shown only for a running local relaxation. ⚡ Optimize moved
  into the wizard (`onOptimizeMount`), writing into its touched state.
  - **That move shipped ⚡ Optimize broken and it stayed broken until 2026-08-06.** The
    commit deleted `let _lastSizedAtoms` *and* its only reader (the panel's GPU-resident
    warning painter) but left the write behind in `fetchRecommendation`. ES modules are
    strict mode, so the orphaned assignment threw `ReferenceError: assignment to
    undeclared variable _lastSizedAtoms` on every click, before the recommendation
    returned — ⚡ could never succeed. Fixed by deleting the write; nothing reads a
    panel-side atom count now (the wizard reads the package PSF directly), and
    `gpuResidentWarning` in `md_advanced_optimize.js` is left with no production caller.
    Note there is **no JS linter** in this repo (`just lint` is ruff-only), so this whole
    bug class — write to an undeclared name, only throws when the line runs — is invisible
    to both CI and the vitest suite.

### Two new presets (`md_presets.py`)

`literature` (verbatim Aksimentiev: early-stop OFF, `fast=False`, production dt **2.0 fs**,
padding 2.0 nm, and `allow_water_shell_carve=False`) and `design_speed` (every measured
accelerator on). `DEFAULT_PRESET` is still `standard`. New request field
`CreateJobRequest.allow_water_shell_carve` (default True): when False, prep REFUSES rather
than auto-fitting a carve, because a carve forces NVT, which deletes the settle stage and
the box-size equilibration criterion — the run stops being the published protocol.

**The carve is LOCKED off, and an unfittable job is warned — never refused.** Two separate
decisions, both revised after review:

- **Locked, not defaulted.** `RelaxPreset.locked: frozenset` is a new field: settings the
  preset owns outright, applied even against an explicit request, exactly as `protocol`
  already was. `literature` locks `allow_water_shell_carve`; nothing else in the catalogue
  locks anything. Rationale: a carved cell has no bulk phase, so the published 12.5 mM
  Mg²⁺ condition is not a concentration *of* anything, the far field is vacuum (ε≈1) not
  water, and the water/vacuum interface pulls the shell onto the solute — a carved run is
  a different experiment wearing this tier's name. The plan reports the field as `forced`,
  which is what makes the wizard render it read-only with the reason instead of offering a
  control that silently does nothing.
- **Warned, not refused.** Whether a system fits is a property of today's hardware, and
  the pre-flight is an estimate rather than a measurement, so the user is entitled to
  attempt the full box. `gateAMessage` returns `canProceed: true` / "Run anyway" for
  **every** non-`ok` tier when `carve_allowed === false`, naming what will happen (OOM at
  the first segment, before real compute) and the cheaper routes — lower padding, seed
  from oxDNA/mrDNA so the all-atom leg is short (the reference group's own answer, mrDNA:
  Maffeo & Aksimentiev NAR 2020), RunPod/cluster, or a tier that permits carving. Prep
  DECLINES the carve and builds at full box, recording `declined_water_shell_nm` in
  `prep_params`; it used to raise, which was wrong.

An earlier revision shipped `carve_refused` as a **`blocking`** condition, which made the
wizard refuse to create ANY literature run, fitting or not, with no way forward. The plan
cannot know whether a design fits — that needs a solvation profile (~26 s), far too
expensive for an endpoint re-requested per keystroke — so it states POLICY and the launch
gate does the checking. Never mark a plan condition `blocking` for something the plan has
not measured.

Two supporting fixes: `preflight_md_vram` applies the preset before judging (it was
pre-flighting padding 1.2 nm with carving allowed while prep would run 2.0 nm with it
refused), and Gate A's trigger is `(payload.water_shell_nm ?? 0) === 0` — the wizard sends
only touched fields, so an untouched shell is ABSENT and the old `=== 0` test skipped Gate
A for exactly the launches that most needed it. `_launchRelax` reads `adv.carve_allowed`
rather than the tier when deciding whether to apply a shell, because the tiers describe
how well a *carve* would fit, which is not the question this protocol asks.

## The run queue replaced Chain Simulations (2026-08-04)

With the wizard, a user can create any number of prepared jobs; the only way to run several
in sequence used to be the **Chain Simulations** panel, which authored a plan of
not-yet-existing stages. Jobs already sitting at `queued` had no way to say "go after that
one". That panel is **deleted** (frontend only — see [[project_simulate_panel_overhaul]] for
the removal surface; `routes_chain_sim.py`, `chain_sim_projects` and the `MdPipeline` chain
executor are untouched, so saved designs load unchanged).

**The model.** An ordered list of job ids in `<workspace>/md_queue.json`
(`backend/core/md_queue.py`), served by `backend/api/routes_md_queue.py`
(`GET/POST/PUT /md/queue`, `DELETE /md/queue/{id}`), drained once per MD-supervisor tick by
`advance_md_queue` (registered in `main.py`'s `_md_supervisor_loop`).

- **Server-owned and persistent.** The panel is a view onto it. Closing the tab does not
  cancel what is waiting — that is the whole point, and it is why this is not a frontend
  timer.
- **Strictly serial.** While ANY NAMD job is in flight, nothing starts. The drain is
  `running_job(jobs) is None` → start the head. Handoff latency is one supervisor tick
  (`_MD_SUPERVISOR_INTERVAL_S = 30 s`), which is nothing against an hours-long run.
- **One launch path.** The drain awaits the same `start_md_job` handler ▶ Run hits — a
  queued launch and a manual one cannot diverge.
- **Self-healing.** `next_startable` scans PAST a stale head (job deleted, started by hand,
  already finished) and returns those ids as `stale` to drop, so starting B by hand while
  `[A,B,C]` are queued never strands C. A launch that throws drops its entry (dequeued
  BEFORE the start attempt) rather than retrying forever.
- **Local-only.** `job_is_queueable` = local + (`queued` never-started OR `stopped`/`failed`).
  Excluded: `draft` (needs the wizard), `paused` (a GPU-resident decision a human must
  answer), and every remote job — an Alpine submit or a RunPod rental is a review-card
  decision, not something to fire unattended hours later. **`mdQueueable` in
  `md_jobs_panel.js` is the mirror; keep the two in lockstep** or the button offers a queue
  the server refuses.

**UI.** `▶ Run` (`#md-jobs-run-btn`) gains two more meanings via `mdRunControl`, which now
takes `{machineBusy, queuedIds}` straight from `GET /md/queue`:

| Selected job | Button |
|---|---|
| startable, machine free | `▶ Run` (unchanged) |
| startable/stopped, machine busy | `＋ Queue` → `POST /md/queue` |
| already in the queue | `✕ Queued #N` → `DELETE /md/queue/{id}` |

`RUN_ACTION` grew `QUEUE`/`DEQUEUE` (`job_run_control.js`); `runControlState` does not
produce them — the engine wrapper adds them. `#md-queue-wrap` under `#md-launch-row` lists
who is waiting, in order, each row clickable (selects the job) with a `✕` to drop out.

Pinned by `tests/test_md_queue.py` (23), `tests/test_routes_md_queue.py` (14),
`md_jobs_panel.test.js` (the queue matrix + `mdQueueable` + `mdQueueRowLabel`), and the
troubleshooting spec `frontend/e2e/md_run_queue.spec.js` (fakes `busy` by intercepting
`GET /api/md/queue` — it never starts a real run).

### Every stage parameter is editable (2026-08-04)

The stage table is no longer read-only. Any NAMD directive on any stage of either job type
can be overridden by hand, and the table carries **two independent highlights** that answer
different questions: `diff_vs_previous` ("what moves as the ladder advances") and
`overridden` ("where have I departed from the protocol I picked" — the reviewer's
question, and the one the protocol's NAME claims).

- **`md_protocols.apply_conf_overrides(conf_text, overrides)`** rewrites directives in an
  already-emitted conf: present ones replaced IN PLACE (so the conf keeps its order and its
  comments), absent ones appended under a marked heading, `None` deletes. Returns the input
  object unchanged when there is nothing to apply — the writers' byte-identical guarantees
  that the ensemble path depends on must not move for a job that overrides nothing.
- **`PROTECTED_DIRECTIVES`** refuses `structure`/`coordinates`/`outputName`/`binCoordinates`/
  … — not physics, the names the runner and the restart chain address a stage by, so
  rewriting one detaches the stage from its job rather than changing what it simulates. The
  plan endpoint turns the ValueError into a 400; the table renders those cells read-only so
  the edit cannot fail at submit.
- **Keyed by stage INDEX, not name** (`{"*": {...}, "3": {...}}`, wildcard merged first so a
  per-stage entry refines it). A stage's name carries the design stem, which the wizard does
  not know until prep and which would change under it; the index is stable between preview
  and run because both compute the ladder from the same builder.
- `CreateJobRequest.stage_overrides` / `ProductionRunRequest.stage_overrides` → prep → the
  emitted confs → recorded verbatim in the manifest → **declared in `protocol_fidelity` as
  a `hand-edited stages` deviation.** A hand edit is a departure from every protocol by
  definition, so it belongs in the package's own methods delta, not only in the confs.
- The plan emits an edited stage TWICE — protocol-only and with the edits — and diffs them.
  That makes "you have departed here" a computed fact rather than a claim, the same trick
  `conditional_keys` uses for GPU-resident.
- Wizard: click-to-edit in place (the value only makes sense beside its neighbours), a `⋯`
  per row for "set on EVERY stage" (22 columns cell-by-cell is not a usable feature), and a
  banner naming the protocol the run no longer is, with Reset. Blank restores the protocol;
  `(none)` deletes the directive — deliberately different instructions. Every one of these
  (including Reset) is on the undo stack, and Escape abandons the cell without closing the
  modal.
- CSS fix found while verifying: the body's first column is itself `position: sticky`, so
  the header at `z-index: 1` was being overwritten by scrolled rows (the minimisation
  column's name was showing a stray value). Header now outranks it, body cells opaque.

`tests/test_prepare_signatures.py` caught the new kwarg twice — every protocol entry point
must accept the one uniform set `routes_md` passes. GBIS accepts-and-ignores
`stage_overrides` on purpose: its ladder writes confs through its own emitter and would
need the same `apply_conf_overrides` pass, so silently dropping edits would be worse than
not offering them.

### Literature-comparability audit, 2026-08-03 → three fixes

An audit of every emitted parameter against the published protocol, looking for what a
critical reviewer could call a difference that makes NADOC results non-comparable. Three
findings were acted on; the full list (13 items, tiered) is in the audit section of
`REFERENCE_AKSIMENTIEV_PROTOCOL.md`.

**1. Production was genuinely unrestrained; the published productions are not.**
`build_production_conf` emitted `constraints off` and no network. This repo's own second
literature audit (`project_periodic_md.md`, 2026-05-18, vs Yoo & Aksimentiev PNAS
110:20099; Maffeo/Yoo/Aksimentiev NAR 44:3013; Shi et al. ACS Nano 13:12443) had already
concluded their 200+ ns "unrestrained" runs retain a network at k = 0.1 throughout, and
recorded a decision to adopt ENM-permanent production — **which was never implemented.**
Now: `ProductionRunRequest.enm_restraints` = `auto|on|off`. `auto` = on iff the parent was
relaxed with the `literature` protocol, so historical behaviour is preserved for every
other tier and old trajectories stay comparable with new ones. The network is built by
`md_protocols.write_production_enm` **from the equilibrated checkpoint the run starts
from** — a prep-time network would pull the structure back to the pre-ladder build, which
is worse than none. Remaining declared delta: base-ring/8 Å, not the papers' dense
all-non-H/5 Å; same k, sparser network, so lower effective stiffness. Fails open with the
reason in the manifest.

**2. `langevinDamping` was 5 ps⁻¹ everywhere, including production.** That is the
tutorial's *equilibration* value; production papers use ~1. At 5 the dynamics are
overdamped, so diffusion, relaxation and correlation times, ion residence and breathing
kinetics are all scaled by something unrelated to the system — equilibrium averages are
unaffected, which is why it went unnoticed. Split into `LADDER_LANGEVIN_DAMPING = 5.0` /
`PRODUCTION_LANGEVIN_DAMPING = 1.0`, settable per run via
`ProductionRunRequest.langevin_damping`. **This changes the physics of every new
production run** — hence the new `PRODUCTION_RECIPE_VERSION = 2`, which is to production
what `RELAX_RECIPE_VERSION` is to the ladder.

**3. `protocol_fidelity()` under-reported the delta.** Four always-on deviations were
missing entirely (production damping, `stepspercycle`/`pairlistdist` 20-10 vs the
tutorial's 12, the 200/100 production piston vs 1000/500, and stage chunking), plus
early-stop and production restraints, which are conditional. A manifest that lists a
shorter delta than the package actually has is worse than no manifest. `early_stop_relax`
now threads down to `prepare_mgh_slow_release` purely so this block can declare it —
a truncated ladder is a protocol deviation and the per-segment record was the only place
the real stage length existed. Every protocol entry point had to grow the kwarg
(`tests/test_prepare_signatures.py` pins that call-site uniformity, and caught it).

Note `AKSIMENTIEV_STEPS_PER_CYCLE = 20` is **not** the tutorial's number (12) — the name
asserts a provenance it does not have. Left as-is because renaming it touches the runner
and the benchmark harness, but the fidelity block now says so.

### Known defect, pinned not fixed

`prepare_mgh_slow_release` sizes ladder step counts from the REQUESTED `fast` flag, but a
declash design keeps `fast=True` while marking every segment `gentle` (2 fs). So each rung
simulates **2.4 ns, not 4.8**; the soft-start chunk 240 ps not 480. Pinned by
`tests/test_md_protocol_plan.py::test_declash_stages_run_half_their_intended_length` and
DISPLAYED by the wizard (ns = steps × the timestep the segment really runs at). Fixing it
doubles every declash relaxation and makes new runs non-comparable with existing declash
trajectories — a deliberate decision, deferred on purpose.
## Anchors reach production, and can be soft (2026-08-03)

**Two stacked bugs meant a NAMD production run could never be anchored at all.**

1. **The anchors card is a RELAX-launch form.** `_anchorsCard` was read at exactly one
   site (`_launchRelax`) and sent in the *create* payload. The Production button built its
   own body and never read it, and `ProductionRunRequest` had no `anchors` field — so
   picking bases and clicking Production silently discarded them. There is still no
   per-job anchors *display*, which is why the card kept showing an unsubmitted selection
   and looked like job state.
2. **`build_replica_package` dropped anchors AND the E-field.** It called
   `build_production_conf` without `anchors_file=`/`field=` and never staged the marker
   PDB. So even a correctly anchored relaxation produced an unanchored child — and an
   **E-field job's production child ran field-free** while its record claimed the field.
   (The sibling *append* route never had this hole: it reads both back out of the
   manifest.)

What exists now:

- **Anchors on the production request** — `ProductionRunRequest.anchors` (omit = inherit
  the parent's; `[]` = explicitly unanchored, the way to spawn a free control off an
  anchored parent), resolved by `routes_md._resolve_child_anchors` against the child's
  frozen `design.json`.
- **Atom-level anchoring without an atom picker.** The marker PDB was always per-atom;
  only the decision was per-residue (~20 heavy atoms per base). `anchor_atoms` is a PDB
  atom-NAME filter (`["C1'"]` → 1 atom/base). A filter matching nothing is a hard error,
  never a silent unanchored run. **Now PER ANCHOR — see the next section; `anchor_atoms`
  survives as the job-level default.**
- **Soft anchors** (`anchor_k`, kcal/mol/Å²) — `constraints`/`consref`/`conskfile`,
  `conskcol B`. **Production only**: the ladder's constraints channel is spent on the
  slow-release restraint, so relax stays hard `fixedAtoms`. Card control:
  `#md-anchors-stiffness`, default 0.02. A hard pin is a Dirichlet boundary — it
  propagates strain, kills local fluctuation, and is not rescaled by the barostat.
  Suppressing tumbling of a ~10 nm bundle held at both ends needs only ~0.01–0.03
  (k·((L/2)·sin θ)² ≈ kT at θ ≈ 10°).
  **A hard anchor also costs GPU-resident** (2026-08-04): NAMD 3 refuses `fixedAtoms`
  under `GPUresident`, so any segment emitting one drops to offload. Gated in BOTH conf
  writers — `_segment_conf` AND `build_production_conf` — since a fix in one leaves the
  other emitting the fatal pair (LESSONS H16/K12). Soft anchors are unaffected.
- **The `_0S_` settle stage now owns the constraints channel** (it carries no ENM), holding
  all DNA heavy atoms at k=1 rather than the old all-DNA `fixedAtoms` — that is what let it
  keep GPU-resident. `namd_runner.retarget_settle_restraints` re-points its reference at the
  minimised coords after minimisation. See [[REFERENCE_AKSIMENTIEV_PROTOCOL]].
- **`retarget_anchor_pdb`** re-points the soft reference at the child's OWN
  `equilibrated.coor`. Restraining to the prep-time build pose would pull the structure
  back to where the ladder moved it from, for the whole run — and would give each arm of a
  comparison a different pre-strain.
- `build_production_conf` no longer emits an unconditional `constraints off` (it would
  switch soft anchors straight back off). Unanchored/hard-anchored confs are unchanged.

Tests: `tests/test_namd_anchors.py` (atom filter, k-in-column-B, hard/soft emission,
retarget + its length guard), `tests/test_md_ensemble.py` (child carries anchors+field,
soft path references equilibrated coords, unanchored conf unchanged, missing file raises),
`tests/test_md_milestone1.py` (route-level inherit / `anchors: []` turns it off),
`frontend/src/ui/md_jobs_panel.test.js` (`mdAnchorAtomNames`, `mdAnchorStiffness`).

## Per-anchor atom holds + the per-ATOM halo (2026-08-05)

One job-level `anchor_atoms` could not hold a corner base rigidly while merely tethering a
distant overhang by its phosphate. **The choice now rides on the anchor DESCRIPTOR**, and
the halo shows the atoms it actually pins.

- **Data model — `atoms` on the descriptor**: `{kind:'strand', id:'s1', atoms:["C1'"]}`.
  **KEY PRESENCE is the authority signal**: `atoms` present (even as `null`) is that
  anchor's own decision; absent falls back to job-level `anchor_atoms`. `null` ≡ all heavy
  atoms. A `.get("atoms") or default`-style read collapses the two and leaks the default
  into rows that explicitly asked for all-heavy — the one subtle part, pinned on both
  sides. Chosen over a parallel array because descriptors already round-trip through
  `manifest.anchors.requested` → `GET /forces` → `applyConfig`, so **read-back came free**
  (and fixed the atoms select, which had been write-only its whole life).
- **Backend**: `namd_topology.resolve_anchor_atom_map(design, anchors, *, model,
  full_topology, default_atoms) -> {residue ordinal: frozenset|None}`.
  `resolve_anchor_residue_indices` is now a two-line delegate over it (its 6 callers
  unchanged). `write_anchor_restraints_pdb` accepts that Mapping in place of a `set[int]`
  — **a Mapping is authoritative and `atom_names` is then ignored**, since a `None` VALUE
  means "all heavy atoms for THIS residue". Two cost/correctness notes: anchors are
  GROUPED by atom set before resolving (≤5 groups for 4 presets, so the O(nucleotides)
  `resolve_anchor_particles` walk runs ≤5×, not once per anchor), and the key→ordinal
  index is `dict[key, list[int]]` because loop-insertion copies share
  `(helix_id, bp_index, direction)`. **Overlaps UNION, with `None` as the top element**
  (`_union_atom_names`) — monotone and order-independent; last-wins would depend on add
  order, which `dedupeAnchors` reshuffles and the UI never shows. `requested_atom_names`
  feeds the matched-nothing error so it names what was asked, not just the default.
- **Row labels are `H<n>:bp<i> Scaf|Stap`** (`efield_math.makeAnchorLabeller(design)`).
  `<n>` is the helix NUMBER shown in the viewport (`helix.label ?? its index`, the same
  rule `domain_ends.js:208` uses for the 3D number sprites) — **never the lattice id**.
  The old `base <uuid>.7 FORWARD` ran to ~50 chars; **that is what starved the Hold-atoms
  select to 6 px in the ~230 px sidebar, so the column looked absent**. Fixed on both
  sides: short labels AND `table-layout:fixed` + a `<colgroup>` (auto / 104px / 16px)
  with the label cell ellipsis-truncating (`title` carries the full text). Select is now
  96 px. **Never give the label cell `width:100%`.**
  The suffix is the strand ROLE, not FORWARD/REVERSE: which direction is scaffold flips
  per helix (2hb: helix 0 FORWARD is the staple, helix 1 FORWARD is the scaffold), so the
  direction word carries no meaning for the user. Resolved by finding the domain covering
  `(helix, bp, direction)` → `strand_type` (`scaffold→Scaf, staple→Stap, linker→Link,
  oh_binder→Bind`); an uncovered slot falls back to `Fwd`/`Rev` so the two strands of a
  base pair can never render as identical rows. Full vocabulary:
  `H2:bp23 Scaf` base · `H2:bp10-24 Stap` domain (bp RANGE, min/max — REVERSE domains
  store start > end) · `H2:bp23+1` extra base #1 at the crossover leaving that bp (`+*` =
  all; an insert has no bp of its own, so it is named by `half_a`) · `H2:bp26›2` tail base
  #2 beyond that terminus (`›*` = all; 5′ → first domain's `start_bp`, 3′ → last domain's
  `end_bp`) · `S3` / `C1` / `OH4` for scopes spanning many helices. An id the design
  doesn't know is flagged (`H?4a9c`, `S?gone`) rather than silently renumbered.
  The labeller indexes the design ONCE and is built per repaint, not per row. All 7 cards
  get it free: `getSelection()` returns the whole store state, so `currentDesign` is
  already reachable. `lammps_forces_setup.js` uses the same labeller.
  **e2e that assert on list text must match the vocabulary, not the old words** —
  `base_anchors.spec.js` counted the literal `"base "`; it now counts `[data-key]` rows.
- **Card is a scrollable TABLE** (`oxdna_anchors_setup.js`), one `<tr>` per anchor keeping
  `data-key`/`data-hl` verbatim, label as bare `<td>` textContent, `data-role="remove"` on
  the ×. **7 live instances** of this factory (oxdna/namd/cando/mrdna/snupi + occupancy ×2)
  — the Hold-atoms column is **opt-in via `ids.atoms`**, and row `<option>`s are CLONED
  from that element, so the four presets stay defined once in index.html. "Hold atoms" →
  **"Apply hold to all"**, blank (`selectedIndex = -1`) when rows disagree
  (`commonAnchorAtomsKey`). A row's `change` fires `_emit()` (not `_dispatch`) — unlike
  focus, held atoms are part of the run. **Never `_renderAnchors()` from a row select's own
  handler**: it wipes `innerHTML` and would replace the `<select>` mid-event.
- **Descriptor algebra** lives in `scene/efield_math.js` (7 new pure exports:
  `anchorAtoms`, `hasAnchorAtoms`, `anchorAtomsKey`, `withAnchorAtoms`,
  `withAllAnchorAtoms`, `commonAnchorAtomsKey`, `atomOptionByKey`); `mdAnchorAtomNames`
  moved there as `atomNamesFromValue` and is re-exported from `md_jobs_panel.js`.
- **Per-ATOM halo** (`anchor_glow.buildAnchorAtomIndex` → `atomistic_renderer
  .anchorAtomEntries`). Index is built from the **DESIGN, not geometry** — at `cylinders`
  LOD `getBackboneEntries()` is empty, so a geometry-derived index would inherit the
  long-standing "halo silently draws nothing" bug. `anchorAtomEntries` returns **null**
  (→ caller falls back to the coarse halo) when the rep is off, atoms aren't loaded, the
  payload is columnar, it has no `name` field, or the match exceeds `max` (20k).
  **Only `GET /api/design/atomistic` carries atom names** — the oxDNA columnar bundle
  drops them by design and the live MD frames never had them, so those paths fall back.
  Entries expose a LIVE `pos` getter reading `getMatrixAt` through
  `_state.elementMeshes[el]` resolved at READ time (survives `_rebuild`, tracks
  `applyPositionLerp`), with one shared scratch Matrix4+Vector3 because `refreshAllGlow`
  re-reads every entry each sim frame. **One glow layer, not an 8th**: `createGlowLayer`
  now honours a per-entry `scale` (mirroring `createMultiColorGlowLayer`), so per-atom and
  per-nucleotide entries share one draw call. `anchorAtomGlowScale` = 1.4 ballstick /
  2.6 vdw / 3.6 CG.
- **Switching on uses `atomisticRenderer.onAtomsChanged(cb)`, NOT
  `nadoc:representation-change`** — that event fires before the async atom fetch resolves,
  when the count is still 0. The callback is gated on a `${mode}|${count}|${columnar}`
  signature, which is what keeps an O(N-atoms) re-match off the live-MD frame loop.
  `main.js` gained one word (`atomisticRenderer` dep); **LOC Δ = 0**.
- Anchors with NO `atoms` key (oxDNA cards, occupancy scope picks) keep the
  per-nucleotide halo — that split is why this feature can't leak into the other cards.

Measured in-app (e2e `anchor_atoms.spec.js`, 32-nt anchored strand, ball-and-stick):
CG 32 spheres → `P` 32 → `P,C1'` 64 → all-heavy **640 (exactly 20×)**, and every glowing
sphere position matches a real P atom of an anchored base. F4 restores exactly 32.

Tests: `tests/test_namd_anchors.py` (+11: per-anchor map, union, `None` absorbs, absent →
default, present-null beats default, `atom_names` alias, delegate still a set, Mapping
ignores `atom_names`, duplicate residue keys, `requested_atom_names`),
`tests/test_md_job_forces.py` (+3 route round-trip incl. `atoms` echoed in `requested`),
`efield_math.test.js` (+27), `oxdna_anchors_setup.test.js` (+16, existing 26 green
UNEDITED — the table is behaviour-preserving), `anchor_glow.test.js` (+17),
`atomistic_renderer.test.js` (+11), e2e `anchor_atoms.spec.js` (2).

## Velocity seeds are drawn, not fixed (2026-08-03)

**Every path that starts a production run now draws a fresh random NAMD `seed`.** Before
this, the first production child of any parent got `54321` (`_DEFAULT_BASE_SEED + index`),
the append path inherited `build_production_conf`'s literal `54321`, and both the ensemble
route and the chain executor defaulted to the same base. Consequence found while reviewing
the 2hb extra-base set: `2hb_1xT`, `2hb_1-0xT` and `2hb_2xT` **all ran seed 54321** — three
designs being compared against each other shared one velocity realisation and one Langevin
force stream, which is a correlated thermal history in exactly the place a cross-design
comparison needs independence.

- `md_ensemble.random_seed(exclude=())` — `secrets`-backed draw in 1 .. `NAMD_SEED_MAX`
  (2³¹−1), with headroom so `base + n_replicas` cannot overflow, and `exclude` (a parent's
  existing sibling seeds) so a fan-out cannot collide onto one trajectory.
- `generate_seeds(base, n)` is unchanged and still pure/consecutive — only the **base** is
  now drawn. `md_pipeline.build_pipeline_plan` also keeps its fixed default (it is pure and
  test-pinned); the live caller `md_chain_executor.init_chain_run` passes a random base.
- **Reproducibility is by RECORDING, not by fixing.** The drawn value lands in
  `MdJob.ensemble_seed`, the child manifest's `ensemble.seed`, the segment stage label, and
  — for the append path — a new `production_extension.seed` key. `ProductionRunRequest.seed`
  and `EnsembleProductionRequest.base_seed` accept an explicit value to replay a past run.
- Tests assert the **contract** (in range, siblings distinct, pin honoured), never a
  literal seed: `tests/test_md_ensemble.py::test_random_seed_*`,
  `tests/test_md_milestone1.py::test_repeated_productions_get_distinct_seeds` /
  `::test_production_seed_can_be_pinned_to_reproduce_a_run`.


## Microsecond production runs are allowed, and priced before they start (2026-07-30)

**Symptom:** starting a 1 µs production child of a 2 ns `2hb_1xT` run showed only
`Production failed: [object Object]`.

Two independent faults, both worth knowing:

1. **The cap.** `steps` was `le=50_000_000` (200 ns at 4 fs) and `length_ns` `le=100.0`, so
   250M steps was rejected by **pydantic, before the handler ran**. A 422's `detail` is a
   *list of dicts*, not a string — `new Error(detail)` stringifies it to `[object Object]`.
   Now `MAX_PRODUCTION_STEPS = 1_000_000_000` / `MAX_PRODUCTION_NS = 10_000.0`
   (`routes_md.py`), shared by **all four** length-carrying models — `ProductionRequest`,
   `ProductionRunRequest`, `EnsembleProductionRequest`, `ChainStageRequest`. Keep them
   shared: a length one route accepts and another rejects is a bug that only appears in
   whichever panel uses the stricter one. 1e9 stays inside NAMD's int32 `numsteps`.
2. **The message.** `client.js` stored `json.detail` raw in **12** places, so *every* 422
   anywhere in the app rendered as `[object Object]`. `errorDetailToMessage(detail, fallback)`
   now flattens `[{loc, msg}]` → `"steps: Input should be less than or equal to …"`, caps at
   3 entries, and is used by all of them (it also replaced a hand-rolled copy that had been
   written for the binary-export path only). Tests: `frontend/src/api/error_detail.test.js`.

**What actually protects a long run** is the forecast, not a step count:

- `disk_guard.forecast()` gained `target_dir` + `volume` (`volume_root()` walks to the real
  mount point). This matters because `MdJob.job_dir` resolves an **archived** job onto its
  external drive — the in-run guard already polled that path, but the forecast reported free
  space without saying which disk, and the relax route (`estimate-disk`) measured the
  workspace even when `run_dir` pointed elsewhere. Both now measure the run's real volume.
- `estimate-production-disk` honours the request's **`dcd_freq`** (bytes scale as
  1/dcd_freq — forecasting the 2500 default while the panel sends 25000 under-read the run
  tenfold) and returns `est_ns_per_day` / `est_hours` via `_throughput_estimate()`
  (`md_optimize.predict_ns_per_day`, scaled by dt/4 since it is calibrated at 4 fs).
- New **`confirmBigRunOk`** (`ui/job_activity.js`): a Proceed/Cancel showing simulated ns,
  trajectory bytes, free space + volume, and estimated wall-clock whenever a run exceeds
  `BIG_RUN_BYTES` (10 GB) **or** `BIG_RUN_HOURS` (24 h). Deliberately independent of
  `confirmDiskSpaceOk`, which fires only when the disk would run *short* — an 80 GB / 17-day
  run onto a 5.8 TB archive drive raises no space warning at all and still wants confirming.
  Wired into both the production-child and relax launch paths.

Worked example (`2hb_1xT`, 62,677 atoms, archived to `/media/jojo/Archive`): 1 µs at 4 fs =
250M steps → **86.5 GB** at `dcd_freq 2500` (8.1 GB at 25000), `warn=false` (5.8 TB free).


## Throughput: MEASURE it, never model it (2026-07-30)

The first version of the estimate above used `md_optimize.predict_ns_per_day` and reported
**407 h (17 days)** for that 1 µs run. The real machine does it in ~3 days. The atom-count
model is calibrated against one GPU and read **7.5× low** here: 29.5 ns/day predicted at 2 fs
vs **220 measured** on the live 2hb production run.

`_measured_ns_per_day(job)` now reads the job's own NAMD logs and wins over the model:

- **`namd_metrics.benchmark_ns_per_day(log, head_bytes=256k)`** — NAMD emits
  `Benchmark time:` a few times right after a `run` starts and never again (line 277 of a
  2,446-line log; ~14 kB into the file). So this reads the **HEAD**, the mirror of the
  existing `last_timestep_from_tail`. `parse_namd_log` reads the whole file, which does not
  survive a multi-GB production log on a hot path.
- **The timestep comes from the matching manifest SEGMENT**, never from
  `relax_protocol_settings.timestep_fs` — those disagree in the wild (`8c116f8db22b` records
  4.0 there while every ladder segment ran at 2.0), and a wrong dt silently rescales the
  answer 2×. A log that cannot be paired with a segment is skipped, not guessed at.
- Production segments outrank ladder segments (unrestrained, production dt = the closest
  analogue). A restrained ENM segment is the fallback and reads ~1.6× pessimistic, which is
  the safe direction.
- The response carries `throughput_source`: `"measured:<segment>"` or `"model"`.

Result for the same 1 µs run: **407 h → 84.8 h** (relax-derived, 283 ns/day) or **54.5 h**
(production-derived, 440 ns/day). The model survives only for a package that has never run
a step.

The refusal text was also cut from a paragraph to one line (a test pins it under 250 chars);
the panel renders its own one-liner via `confirmUndersizedCell({lengthNs})`. The token
`allow_undersized_cell` is the load-bearing part — `isUndersizedCellRefusal` keys off it.

**Still open (not fixed here):**
- The panel sends `runpod_gpu_key` on the production spawn but `ProductionRunRequest` has no
  such field and no `extra=` config, so pydantic **silently drops it** — a RunPod production
  child carries no GPU selection.


## The production cell: sized once at prep, inherited forever (2026-07-30)

Follow-up to the entry above. "Standard relax then production" **cannot** produce a cell
big enough for a long free run, by construction:

- Relax prep passes `free_ns = _LADDER_FREE_NS = 4.8` ([md_protocols.py:82]), and
  `resolve_box_mode` returns **bbox** for anything ≤ `ROTATION_FREE_NS_THRESHOLD` (20 ns).
  Deliberate: a rotation cell is ~5× the water for a reorientation the restrained ladder
  never performs.
- **Nothing after prep re-solvates.** `build_replica_package` copies `box_ang` and hardlinks
  the parent PSF/PDB, so every production child — and every chained production — re-uses the
  ladder's cell verbatim.

Measured on `2hb_1xT`: solute swept diameter 93.2 Å in a 60.1 × 82.6 × 129.6 Å cell; a turned
solute **overlaps its own image by 33 Å**. Prep measured this correctly and recorded
`box_check.fits_rotated=False` on the parent — then `build_replica_package` wrote a child
manifest with **no `solvation` block at all**, and the guard's `fits_rotated=True` default
waved every child through. The verdict was computed, recorded, and discarded one hop later.

Fixes:
- `build_replica_package` carries `solvation` into the child manifest (the child's cell IS
  the parent's, so the verdict transfers unchanged).
- `_inherited_box_check(job)` walks `parent_job_id` (depth ≤ 8, cycle-safe) so jobs created
  *before* that fix — and chained productions two hops from the solvated package — still
  resolve a verdict. Fails open when no ancestor has one: packages predating `box_check`
  must not become unrunnable.
- `_assert_cell_fits_a_free_run` is now called from `spawn_md_production` too, not only the
  sibling append route. `ProductionRunRequest.allow_undersized_cell` is the override, and the
  panel offers it via `confirmUndersizedCell` on an `isUndersizedCellRefusal` message rather
  than making the user hand-craft a request.
- **`CreateJobRequest.production_ns_intent`** (panel: "Production intent (ns)") threads to
  `prepare_mgh_slow_release(free_ns=…)` → the box sizer. Set it above 20 ns and the package
  is rotation-sized up front. Recorded as `solvation.sized_for_free_ns`. This is the only
  point where the choice exists. Signature parity matters: `namd_gbis` must accept-and-ignore
  `free_ns` or `test_prepare_signatures` fails (it caught exactly that).

**Literature position (asked + answered 2026-07-30).** Resizing the cell is standard —
`DEFAULT_BOX_MODE` is already `"rotation"`. A weak **orientation restraint** to license a
smaller cell is NOT standard for this purpose (it appears for binding free energies, membrane
tilt, steered-MD reaction coordinates) and would bias the global rotational/bending dynamics a
long run exists to sample — **not implemented, deliberately**. Note the canonical Aksimentiev
protocol solvates `bbox ± 20 Å` and runs production there; that is sound for large slow-tumbling
origami and breaks for a small anisotropic bundle like a 2hb. See
[[reference-aksimentiev-protocol]].

Cost of doing it right on `2hb_1xT`: ~133 Å cube, 3.67× the water, 62.7k → ~230k atoms,
~59 → ~16 ns/day; 1 µs goes 17 → ~62 days. For a rod this anisotropic the usual alternative is
to keep the snug cell and analyse only internal coordinates (twist, rise, groove widths, bp
parameters), which imaging does not corrupt.


## The master bar reads the BOX TRACE, not just ENERGY frames (2026-07-30)

**Symptom:** a long production sat at 0 % for ~16 minutes after NAMD had demonstrably started
stepping. Measured on the live `2hb_1xT` 500 ns run: 15 min in, `restart.xsc` said step 585,000
while the bar read 0 %.

Not a stall and not the startup cost (the GPU tile-list probe + reseed took ~1 s at 62.7k atoms).
The bar's only step signal was the log's ENERGY frames, and `_production_output_freqs` prints
**~400 of them for the whole run** — deliberately, so GPU-resident mode is not dragged off the
card (LESSONS L7). On that run: `outputEnergies 312500` = 1.25 ns = **8.1 min of wall clock per
frame**, and one frame is 0.25 % of the run, so whole-percent rounding needed *two* frames before
the number could change. A textbook L2 ("a cadence denominated in steps is a latent bug once the
step count is a variable") — here the cadence scales with run *length*, so the longer the run,
the blinder the bar.

- `namd_metrics.last_xsc_step` (tail-read) + **`live_segment_step(package_dir, segment_name)`** —
  the furthest of the log's ENERGY frames, `output/<seg>.xst` (`xstFreq`, 2,500 steps ≈ 4 s on
  that run) and `output/<seg>.restart.xsc` (`restartfreq`). Nothing new is written; these markers
  already existed and nothing read them for progress.
- `routes_md._namd_running_fraction` calls it — so the REST job list AND the WS push (which
  reuses the same helper) both advance. `ws.py`'s `live_metrics.segment_progress` still uses the
  coarse parsed log; **it has no frontend consumer**, so it was left alone.
- Frontend `simulate_jobs.masterProgressPct` now reports **one decimal** (`_pct1`); whole values
  are unchanged, so short runs read exactly as before. `masterStepText` derives its step count
  from the raw `progress_fraction`, not the displayed percent (0.1 % = 125,000 steps there).

**Time remaining, same pass.** The step line now ends `· ~2d 06h remaining`.
`namd_metrics.benchmark_s_per_step` (HEAD-read) takes the step cost straight off the log's
Benchmark lines — **not** ns/day ÷ conf `timestep`, which needed two ingredients and the coarse
ENERGY step — and `eta_seconds(remaining_steps, s_per_step)` applies it to the steps left in the
running segment **plus every segment still queued**, so a ladder counts down to the end of the
ladder. Benchmark lines land ~30 s into a run, i.e. long before the first production ENERGY
frame. `_namd_live_progress` returns `(fraction, eta)` together and both the REST list and the WS
push stamp both — otherwise the estimate blinked in and out with whichever channel painted last.
`routes_jobs._md_eta_seconds` was rewritten onto the same helpers (it had the ns/day + whole-log
version, so the two endpoints could quote different numbers); `_conf_timestep_fs` died with it.
Frontend: `_etaSuffix` appends it for EVERY engine, so the BLADE/SNUPI branches of
`masterStatusText` no longer append their own (that would have printed it twice), and
`formatEta` coarsens past an hour — an MD run is measured in days, and the old m:ss form rendered
2¼ days as `3255m 12s`. No estimate is shown when the rate is unknown; a fabricated one is worse
than none.

## The minimisation is now ON the stage timeline (2026-07-30)

**Symptom:** a fresh run showed an all-pending timeline and a 0 % progress bar for the tens of
minutes it spent minimising. Nothing distinguished "minimising" from "hung".

Cause is structural, not a bug: the manifest keeps the pre-ladder step in its own
``minimization`` slot, NOT in ``segments``, because `namd_runner` indexes that list by
``current_segment_idx`` (prepending would shift the runner, the resume path and the early-stop
accelerator). The job record mirrored that, so the UI had nothing to draw.

- `MdJob.minimization: Optional[MdSegmentStatus]` — a separate field, deliberately not a member
  of ``segments``. Set at prep from the manifest; `namd_runner` stamps running/done/failed and
  backfills jobs prepared before the field existed.
- The manifest slot gained a **`stage` label** (`md_protocols.minimization_status` reads it, never
  assumes): an ensemble replica's slot is a zero-step **velocity reseed**, not a minimisation.
- `GET /md/jobs/{id}` reads the slot off the manifest when the field is None, so the ~84 existing
  jobs get the row too. Not persisted — a GET must not write job.json.
- Frontend: new pure module `frontend/src/ui/md_stage_timeline.js` (`mdMinimizationRow`,
  `mdShortStage`, `mdLatestStageLabel`), consumed by `md_jobs_panel` (leading timeline row, fed
  through the SAME row renderer as a segment so it gets the spinner + ✓) and `simulate_jobs`
  (master-bar tooltip). Row status is **inferred**, not just echoed: a started segment proves the
  minimisation finished (the ladder chains from its `.coor`), which keeps Alpine/RunPod runs
  truthful without a second status-writing path on the cluster side.

The master bar's **percentage** is unchanged — minimisation is not a segment, so it stays at 0 %
until segment 1; the tooltip and the timeline row say what is running instead of faking progress.

## Health is now sampled DURING a segment, not only at its end (2026-07-29)

**Symptom:** the panel's health bar (base-pairs / WC health / "latest") stayed empty for an entire
production run. Not a broken pipeline — a sampling-granularity gap.

`namd_runner` computed health only in its POST-segment block. A relaxation ladder has many
segments (12 when this was written; 20 + minimisation + settle today) so its bar fills in as it goes (10 samples on a real run); a **production run is ONE segment**, so
a 200 ns / 50M-step 4 fs job produced **exactly one sample, ~13 hours in**.

That hid a real result. The single end-point sample read **c1=0.850 / wc=0.641 (FAILED)**, while a
probe of the same run at 90 ns read **c1=0.950 / wc=0.744 (passed)** — the structure degraded over
the run and nothing recorded the trend.

**Fix:** `disk_guard.wait_proc_with_disk_guard` gained an `on_tick` hook (it already polled every
`GUARD_POLL_S` for free disk), threaded through `_run_namd_async`, and
`_make_inflight_health_tick` appends a sample every `NADOC_INFLIGHT_HEALTH_INTERVAL_S` (default
300 s). `run_health_check` reads `output/<segment>.dcd`, which NAMD writes incrementally, so the
data was always available — measured 13 s on a live 2.4 GB DCD, 27 s at full length, hence a
`busy` flag so a check that outlives its interval skips rather than piles up. `safe_back=2` skips
the tail NAMD may be mid-write on. The hook is total: a raising probe is logged and swallowed,
because monitoring must never be able to kill the run it watches. Set the interval to 0 to disable.

**Second-order fix that came with it:** `_production_ready_checkpoint` built its passed-set as
`{h.segment for h in health_samples if h.passed}` — "ANY sample passed". With many samples per
segment a run that degrades (0.950 → 0.850 above) would still count as healthy and be offered as a
production-ready checkpoint. Now uses the **LAST** sample per segment; identical to the old
behaviour when there is one sample per segment.

**Test-double gotcha:** seven `fake_namd` doubles pinned `_run_namd_async`'s exact signature and
broke on the new kwarg (18 failures). They now take `**_kw`. Worth knowing before adding another
parameter there.

## Health-card audit — an ADOPTED run is now a first-class run (2026-07-31)

The 2026-07-29 fix above was only wired into `_run_namd_async`, i.e. the path that **spawns** NAMD.
It missed the other one.

**Symptom:** on a local production run Temp / Pressure / Speed populated while Base pairs / WC
health / Latest / Broken bp / Shell charge showed spinning circles indefinitely. That split is the
diagnosis: the first three are parsed from the NAMD log by `ws.py` and are **runner-independent**;
the rest need the runner's probe.

**Root cause — orphan adoption.** When NAMD outlives its orchestrator (the dev server runs
`uvicorn --reload`, so **any backend edit during a run** does this), `run_job` adopts the survivor
via `_wait_for_segment_process` — which was a bare 10 s poll loop. No `on_tick`, **no disk guard**
(that lives inside `_run_namd_async` too), no `job.save`. Caught live: NAMD reparented to
`systemd --user`, a 776 MB growing DCD, `health_samples: []`, `job.json` frozen 10 h.

**Invariant now:** a segment gets identical services whether we spawned NAMD or adopted it.
`disk_guard._guard_interval` is shared by `wait_proc_with_disk_guard` and the new
`wait_external_proc_with_disk_guard` (liveness by probe, not by asyncio handle);
`_wait_for_segment_process(…, guard_dir=, on_tick=)` delegates to it. Both adopt sites are wired
(segment + minimisation). `_run_namd_async`'s signature is untouched — the seven doubles are safe.

**Also fixed, same audit:**
- Three of four `MdHealthSample` sites dropped `broken_bp_count` / `charge_within_shell_e` after
  computing them (only end-of-segment set them). All four now go through
  **`MdHealthSample.from_result(...)`** — `blocking` stays an explicit per-site argument, because
  `HealthCheckResult` defaults it True on error early-returns and the in-flight probe is advisory.
- `md_health`'s per-frame loop had a bare `except Exception: pass` that erased all three series
  plus the reason. Now: per-frame `try`, honours `safe_back`, and records `diagnostics_error` /
  `per_frame_ran` / `not_ready` (diagnostics NEVER change the pass/fail verdict, and stay out of
  `reason`, which the WC tooltip and production-checkpoint warning render).
- The loop opened `Universe(psf, pdb, dcd)` — a ChainReader whose **frame 0 was the reference
  PDB**, shifting `wc_per_frame` (read by the early-stop accelerator) by one. Now `Universe(psf, dcd)`.
- `run_health_check(per_frame=…)`. **The default MUST stay True** — `remote_health_eval` runs a
  staged copy on the Alpine node and exits `_EXIT_NO_WC` on an empty series, which would make every
  Tier-A stage HOLD. The in-flight probe passes `per_frame=False`: it discards the series anyway,
  and it runs *inline in the disk guard's poll loop*, so an O(n_frames) walk is a blind spot in
  disk-abort detection. Measured on the real 1043-frame DCD: **5.35 s → 1.70 s**.
- The probe read `output/<seg>.dcd`, but a resumed segment writes `<seg>.contN.dcd` — so after any
  auto-resume it sampled the frozen pre-crash trajectory forever. `_latest_segment_dcd` picks the newest.
- First probe now fires at `NADOC_INFLIGHT_HEALTH_FIRST_S` (30 s) then settles to the full interval;
  the card used to be blank for 5 min at every segment start even when healthy.
- `_jsonl_has_segment` parses JSON instead of substring-matching, and treats an **all-null** record
  (written from a truncated log) as absent so it can be recomputed. A record with a real `error`
  still counts, so a legitimately-failed check is not retried every supervisor pass.

**New: `MdJob.health_probe`** = `{enabled, interval_s, started_at, last_tick_at, last_at,
last_error, reason, adopted}`, published on the job payload and WS state. This is what lets the UI
explain an absence instead of spinning; see `project_md_sidebar_audit.md` for the tile rules.

**Three clocks, and they are NOT interchangeable** (found by resuming a real job right after the
first fix landed):
- `started_at` — when THIS segment's probe began watching. Set by the tick factory, which also
  resets `last_tick_at`/`last_at`/`last_error`/`reason` so a previous segment cannot answer for this one.
- `last_tick_at` — the probe RAN. Stamped on every tick including the ones that produce nothing.
- `last_at` — the probe produced a SAMPLE.

`job.created_at` is **not** a probe clock. A resumed run is hours old with a probe seconds old; the
first UI watchdog anchored on job age and so painted failed tiles the instant the job came back.
"The probe died" (silent for `2 × interval`) and "the probe is running but the DCD is still too
short" (`safe_back + 1` frames — at `dcdFreq 25000` / 4 fs that is ~10 min of wall-clock) are
different situations on different timescales, and both must be bounded separately.

`adopted` is a durable fact on its own key, deliberately not in `reason`: an adopted run samples
normally, so it must never read as the reason a metric is missing.

**Verified live** on the resumed 500 ns `2hb_1xT`: editing a backend file re-orphaned NAMD (PPID →
`systemd`), the supervisor re-adopted it, and the first complete sample landed ~90 s later —
`c1=0.927 wc=0.718 broken_bp=0 charge=243.9 diagnostics=ok`, read from the resume's `.cont1.dcd`.
Before the fix that same shape produced zero samples in 11 hours.

Pins: `tests/test_md_health_reporting.py` (39).

**Why:** Replace ad hoc experiment scripts with server-managed NAMD jobs that
persist through browser refreshes, run health gates automatically, and expose a
REST API.

**New modules:**

- `backend/core/md_job.py` — `MdJob` dataclass with status enum, health samples,
  segment list; persists to `workspace/md_jobs/{job_id}/job.json`.
- `backend/core/namd_metrics.py` — NAMD log parser using ETITLE/ENERGY columns;
  extracts TEMP, TEMPAVG, PRESSURE, GPRESSURE, VOLUME, TOTAL; ns/day from
  "Benchmark time: … days/ns" line.
- `backend/core/md_health.py` — C1'/WC health analysis as library functions
  (ported from exp25 scripts); `build_c1_pairs`, `build_wc_pairs`,
  `run_health_check`, `append_health_jsonl`.
- `backend/core/md_protocols.py` — `mgh_slow_release` preset: segment sequence
  (50K/100K/200K/300K NVT → 310K NPT k=5→0.05), config generation,
  `write_restraints_pdb`, `parse_box_from_namd_conf`, `prepare_mgh_slow_release`
  (calls `build_namd_solvated_package` + extracts ZIP + writes all conf files).
- `backend/core/namd_runner.py` — async segmented runner; uses
  `asyncio.create_subprocess_exec`; global `_RUNNING` dict; health gate after
  every segment; appends to `output/health.jsonl` and `output/metrics.jsonl`;
  stop via task cancellation + SIGTERM to process group.
- `backend/api/routes_md.py` — REST endpoints under `/api/md/`:
  - `POST /md/jobs` — prepare + optionally autostart (GROMACS solvation in threadpool)
  - `GET /md/jobs`, `GET /md/jobs/{job_id}` — list/status
  - `POST /md/jobs/{job_id}/start` / `/stop`
  - `GET /md/jobs/{job_id}/health` / `/metrics`
  - `GET /md/namd-available`

**How to apply:** When resuming MD job work or adding new protocol presets,
read this file and md_integration_plan.md for Milestones 2-5.

**Next milestone (2):** MD Job UI panel — Run MD button, preset selector,
job timeline, live metric cards, health gate display, WS streaming.

**Clean-stop UI fix (2026-07-04):** Stopping a running local job left the sidebar
showing a **spinning stage** + **"Unknown error"** (seen on the two stopped
`6hb_2xT` jobs `78a15b57195a`/`d097bad60cf2`). Two independent causes:
- Backend flipped `status→stopped` but never cleared `error` and left the in-flight
  segment marked `"running"` on disk. New shared helper `namd_runner.apply_user_stop(job)`
  sets stopped + `user_stopped=True`, clears `error=None`, and rewinds any `running`
  segment → `pending` (it re-runs from its checkpoint on resume). Called from ALL stop
  transitions: `_thread_main` finally (cancel), `stop_job` orphan path, and the three
  `routes_md.stop_md_job` sites (remote-disconnected, remote-scancel, local-not-in-registry).
- Frontend `md_jobs_panel.js`: a `stopped` job unconditionally showed the error box
  (`job.error ?? 'Unknown error'`), and the timeline spun on ANY `running` segment
  regardless of job liveness. Now pure `mdDetailErrorText(job)` returns null for a
  clean stop (box only when a message exists — failed submit / raced failure / legacy);
  `_renderTimeline` gates the spinner + `_segSymbol` on `mdJobIsActive(job)`, so a
  terminal job's leftover `running` segment renders as interrupted `·`, never spinning.
  This also heals already-saved bad job.json (no backend re-save needed).
  Tests: `TestOrphanStop::{test_stop_clears_error_and_reverts_running_segment,
  test_apply_user_stop_only_reverts_running_segments}`; vitest `mdDetailErrorText` block.

**Start/Stop buttons are spam-guarded (2026-07-05):** The Start + Stop buttons on
BOTH the MD and oxDNA job panels had no in-flight guard — a Stop request takes a beat
to register on the backend, so an impatient user could fire it several times. New shared
`frontend/src/ui/primitives/button_busy.js` (`runExclusive(btn, action, {label})`): a
module-level WeakSet keyed on the button element ignores re-entrant presses while one is
in flight, and it immediately disables + spins the button (`.nadoc-spinner` + `.is-busy`
CSS added to `components.css` for the inline-styled job buttons that don't carry `.btn`),
restoring the original label/disabled state in a `finally`. The 4 handlers
(`{md,oxdna}_jobs_panel.js` start/stop) now wrap their body in `runExclusive` with labels
"Starting…"/"Stopping…". Run/Prod/Seed/Archive already had their own `_launching`/`_seeding`/
disabled guards — left as-is. Pin: `button_busy.test.js` (7). MV-BTNBUSY logs the live
mash-the-button gesture (needs a running GPU job). No `main.js` change (panels are their own
factory modules).

**Resume doesn't update the detail/spinners (2026-07-04):** After clicking Start to
resume a stopped/failed LOCAL job, NAMD runs but the detail panel (stage timeline,
spinners) + live status froze — only the list rows updated. Cause: the Start handler
(and the Fix-modal "retry") did `await _fetchJobs(); _selectJob(_selectedId)`, but
`_selectJob` **early-returns when the id is unchanged**, so `_openDetailForJob` (which
opens the status WebSocket for a now-live job) never ran → no WS → no live updates.
This is the SAME failure the old "Monitoring model" note below describes, but the
`_ensureSelectedSubscription()` heal it credits **no longer exists** in
`md_jobs_panel.js` (refactored away) — so nothing re-subscribed. Fix: new
`_reselectJob(jobId)` = `_openDetailForJob(jobId)` when `id===_selectedId` (force
re-subscribe) else `_selectJob(jobId)`; Start handler + retry flow now call it. Backend
`/md/jobs/{id}/start` already sets `status=running` synchronously before returning, so
the WS opens against a live job. NOTE: still no periodic list/detail poll and no
`_ensureSelectedSubscription`, so a BACKEND auto-resume (supervisor relaunch) of a
selected terminal job won't live-update until the next `_fetchJobs` — button resume is
covered; passive auto-resume heal is a remaining gap.

**Crash/interruption resilience (added 2026-06-10):** NAMD jobs survive a
server/runner death. Four layers in `namd_runner.py`:

- **Mid-segment resume.** If NAMD is killed partway through a segment,
  `_write_resume_conf` rewrites the segment conf to read its own
  `.restart.{coor,vel,xsc}` (copied to a `<seg>.resumeN.*` input set),
  `firsttimestep` + `run <REMAINING>` runs only the steps that are left, and trajectory
  continues in a fresh `<seg>.contN.dcd` (partial `<seg>.dcd` preserved —
  display picks the newest). `_resume_step` reads the checkpoint step from
  `.restart.xsc`; returns None (fresh run) if final `.coor` exists or no restart.
  **Not `run upto N`** — NAMD 3.0.2's Tcl `run` rejects the `upto` keyword ("first arg
  not norepeat"); pinned by `test_md_resume::test_rewrites_directives`.
  The rewrite drops only `_RESUME_DROP` (inputs/outputs/step count) and keeps everything
  else verbatim, so a segment's restraints and `GPUresident` survive a resume unchanged.
- **Reconcile weighs evidence strongest-first (2026-08-05).** `reconcile_job_status`
  used to judge an interrupted job ONLY by its current segment, so any interruption
  landing *before* that segment wrote a checkpoint was reported as a dead segment and
  marked `failed` — which `resume_interrupted_jobs` then skips, discarding recoverable
  work. Two reachable windows did this: **during minimisation** (minutes long; every
  segment chains from `output/<min>.coor`, so no segment can have run while it is
  absent), and **between minimisation finishing and segment 0 spawning** (where the
  GPU-resident pre-flight probe and the declash rebuild live). Order now: completed
  outputs → missing `<min>.coor` (resumable, mirrors `run_job`'s own precondition for
  re-running minimisation) → restart checkpoint (resume) → **no segment log = never
  launched** (resumable; NAMD writes the log on spawn) → failed. No relaunch loop: a
  minimisation that truly cannot run fails inside `run_job` with the real rc.
  Tests: `test_md_resume::TestReconcileDuringMinimisation`. See LESSONS **C12**; the
  sibling case (NAMD *outlives* the orchestrator) is `_external_process_running`,
  pinned by `tests/test_md_min_orphan.py`.
- **Auto-resume on "periodic cell too small" (2026-07-06).** A full-solvation NPT
  segment (`useFlexibleCell no` + langevinPiston) shrinks the box ~3% linear as it
  relaxes to equilibrium density; NAMD fixes the patch grid at startup with only a
  tiny auto margin (~0.4 Å), so the shrink crosses the grid floor and NAMD exits
  `FATAL: Periodic cell has become too small for original patch grid!`. This is NOT
  a blow-up (T/P/energy stay healthy) and is self-healing: restarting from the
  checkpoint rebuilds the grid at the smaller box. New failure kind
  `FAILURE_CELL_SHRINK` (`md_vram.classify_failure_log`, pattern "Periodic cell has
  become too small") — kept distinct from `instability` ("Margin is too small" =
  RATTLE blow-up, which would just re-crash). In `run_job`'s `rc!=0` handler, when
  the kind is `cell_shrink` AND a usable checkpoint exists AND
  `seg.auto_resumes < MAX_CELL_SHRINK_RESUMES` (4), the job is left `running`
  (segment→running, `failure_kind=None`, `auto_resumes++`) so the supervisor
  auto-resumes it instead of dead-ending; past the cap it fails normally. Tests:
  `test_md_runner_proceeds::test_cell_shrink_*`, `test_md_vram` classifier row.
  **DO NOT "fix" this with a `margin` keyword** — a large margin crashes NAMD's GPU
  tile-list kernel on a carved box; pinned by `test_md_water_shell::test_no_explicit_margin_in_configs`
  (see [[water-shell-carve]]).
- **Orphan adoption.** A NAMD that outlived its orchestrator (dev-server reload —
  it runs with `start_new_session=True`) is detected via `/proc`
  (`_segment_process_running`) and *waited on* rather than duplicated.
  **STOP-KILL BUG (fixed 2026-07-03):** an adopted orphan's PID is never recorded in
  `_ACTIVE_PIDS` (the new worker only `_wait_for_segment_process`es it), so the old
  `stop_job` path-A killed `_ACTIVE_PIDS.get(job_id)` == `None` → it cancelled the
  wait, flipped the job to `stopped` on disk, and returned True while NAMD kept
  running on the GPU (orphaned to `systemd --user`). Symptom: Stop "does nothing",
  job shows stopped but a `namd3 …<seg>.conf` process is still live + `namd_pid` never
  cleared. Fix: `stop_job` now resolves the kill PID from `_ACTIVE_PIDS` → `_external_pid`
  (self-verifying /proc scan by conf name — catches the adopted orphan) → persisted
  `namd_pid`, and **always** kills the found process AND cancels the runner task,
  regardless of on-disk status (so a retry after a half-stop still kills). Cancel is
  issued *before* the kill so `CancelledError` beats the wait-loop's "ended without
  completing" FAILED check. Regression test: `TestOrphanStop::test_stop_adopted_orphan_kills_via_proc_scan`.
- **Auto-resume supervisor.** `resume_interrupted_jobs(workspace)` relaunches any
  job persisted as `running` with no live process and `user_stopped=False`.
  Called on startup AND every 30 s by `_md_supervisor_loop` in `main.py` lifespan.
  `reconcile_job_status` now keeps resumable jobs `running` (was `stopped`) so the
  supervisor picks them up; only `completed`/`failed`/user-`stopped` are terminal.
  New `MdJob.user_stopped` flag (set by /stop + on task-cancel, cleared by
  /start + production-append) prevents auto-resurrecting a deliberately paused job.

Recurring symptom this fixed: a long relaxation that "didn't complete" was usually
a clean inter-segment stall — NAMD finished the segment but the dev server had
reloaded, so nothing launched the next segment; it sat at `stopped` awaiting a
manual click. Investigated via `workspace/md_jobs/01968f730c8e` (18hb_42bp).

**Monitoring model + stale-state fix (added 2026-06-10):** Symptom — sidebar showed
"stopped — resume to continue from p100" while NAMD was actively running p100.
Root cause was NOT contention (backend has one writer: the runner thread, with
reconcile/supervisor guarded by `is_running` + `_external_process_running`; verified
exactly one NAMD process). It was frontend staleness:
- `md_jobs_panel.js` only opens the status WebSocket for *live* statuses; it treated
  `stopped` as terminal, and the resume action handlers called `_selectJob(sameId)`
  which early-returns — so after Resume, the panel never re-subscribed and the detail
  (incl. its old error banner) froze. Fix: `_resumeJob`/start handlers now call
  `_openDetailForJob` to force re-subscribe; new exported `isLiveStatus()` drives the
  WS decision; `_ensureSelectedSubscription()` on the 30 s prewarm timer heals any
  missed transition (dropped WS / server restart / backend auto-resume).
- Backend: `run_job` now clears `job.error` when (re)entering the running state and at
  each segment start, so a live job never carries a stale "interrupted/resuming" message.
- Validation: `tests/test_md_runner_proceeds.py` drives the full `run_job` state machine
  with a stubbed NAMD (`_run_namd_async`) + health check — asserts fresh→completed,
  mid-segment resume uses a resume conf, error clears, and re-run is idempotent. Frontend
  `isLiveStatus`/`resumeKindForJob` unit-tested; e2e `md_live_no_stale.spec.js` asserts a
  running job shows live status, no stale banner, and an open WS.

**Health scoring excludes deliberately-ssDNA residues (2026-07-04):** `md_health`
`build_c1_pairs`/`build_wc_pairs` take `exclude_residues` — the same (chain,resid)
keys `md_protocols.identify_unpaired_residues` produces (chain = segid[-1]), which
the declash ENM already excludes. `run_health_check` fills it via
`_unpaired_exclusion_set(psf,pdb)`: computes the ss set ONLY when the declash marker
`{stem}_build.pdb` exists (extra-base/declash designs), else empty → fully-duplex
designs unchanged. So crossover extra bases + other designed ssDNA can't form a
spurious geometric pair (e.g. inserted T landing near a real A across the gap) that
then "fails" and depresses the fraction. Pin: `tests/test_md_health_ss_exclusion.py`
(can-go-red: shows the spurious ss pair forms without exclusion, is dropped with it,
and the real duplex pair is restored). **CAVEAT — small effect on 6hb_2xT:** measured
on the live job `78a15b57195a` k=0.1 frame, exclusion moved WC 47.9%→48.6% (1 pair)
and C1' 77.3%→78.1% (4 pairs). The low WC is NOT the extra bases being counted — it's
that 6hb_2xT is largely UNSEQUENCED (453/656 bases default to THY), so only ~73 of 251
duplex C1' pairs are WC-complementary/scorable, and that sparse biased subset is
genuinely losing ref-relative H-bond contacts at low restraint. To trust WC as a health
signal on this design, assign the scaffold sequence first (see [[feedback-wc-calibration]]).

**Declash protocol for clashed single-stranded inserted bases (added 2026-06-11):**
Designs with extra unpaired bases at crossovers (e.g. "6hb_2xT" — 2 ss thymines
per junction via `crossover.extra_bases="TT"`) are BUILT in hard steric clash:
the geometric layer threads the inserted-T backbone through the cramped
inter-helix gap, overlapping neighbour-helix backbones (667 sub-2 Å overlaps,
P–P to 0.19 Å; 7× the passing baseline). Pinning them with the base-ring ENM
stores that strain and breaks marginal duplex pairs once dynamics starts →
health gate fails (6hb_2xT: C1' 85.2%<90, WC 77.2%<80 at first k=0.5 stage,
vs baseline 100%/95%).

Two complementary fixes, both shipped:
1. **Build geometry (`atomistic.py` `_build_extra_base_atoms`)** — extra-base
   sugar origins were `_lerp`'d along the STRAIGHT chord C3'(src)→C5'(dst)
   (through the gap); only the base *orientation* was bowed. Changed to place
   origins along the rendered bezier arc (`_arc_ctrl_pt`/`_bezier_pt`/
   `_bezier_tan`, BOW_FRAC_3D=0.3) so the loop bulges into solvent. Reduces true
   clashes 893→738 (−17%) but the RESIDUAL is the backbone minimizer
   (`_minimize_N_extra_base`) placing strained phosphate linkers (635/738 clashes
   involve a backbone atom; repel_pos only knows the same-junction opposite
   strand, not neighbour helices). Full build fix needs minimizer rework — deferred.
2. **MD declash protocol (`md_protocols.py` + `namd_runner.py`)** — the working
   route. `prepare_*(declash=True)`: detect ss bases (`identify_unpaired_residues`:
   C1' with no cross-seg partner <10.8 Å), minimise against an ss-EXCLUDED ENM
   (`{stem}_declash_k0.5.enm.extra`) so the ss bases relax out of clash (667→0).
   Runner hook after min → `rebuild_declashed_references`: overwrite `{stem}.pdb`
   from the declashed `.coor` (backup → `{stem}_build.pdb`), rebuild ss-excluded
   ENM ladder + restraints + health reference from declashed coords. Ladder runs
   the SOFT integrator (`SegmentSpec.soft` → rigidBonds none + 1 fs) because ~18
   residual ss-T↔scaffold contacts (<2.4 Å) crash rigid-bond RATTLE otherwise.
   VALIDATED on 6hb_2xT: first k=0.5 stage C1' 94.0% / WC 91.5% (both pass), vs
   85.2%/77.2% un-declashed. AUTO-ENABLED by `design_has_extra_bases(design)`
   (any crossover/forced-ligation `extra_bases`) inside `prepare_*`; the
   `CreateJobRequest.declash` flag only force-enables otherwise. Tests:
   `tests/test_md_declash.py` (pure config/IO). Soft integrator is needed
   THROUGHOUT (tight contacts persist), so the durable fix remains the build-side
   minimizer rework.

**Health gate REMOVED — now advisory only (2026-06-25):** The C1'/WC health check
no longer stops an MD run. Trigger: 2hb_noT died at a k=0.01 checkpoint on a C1'
breach despite being fine. `namd_runner.py` (both the main run loop AND the
resume/reconcile path) used to set `job.status = failed` + "Health gate failed…"
on a blocking (C1') breach. Both gates deleted — a not-passed `run_health_check`
now only logs a WARN and the ladder marches to `completed`. Health samples
(`passed`/`blocking`/`reason`) are still recorded per checkpoint; `blocking` is now
display-severity metadata, not control flow. Frontend `md_jobs_panel.js`:
`_isAdvisoryWarning` returns true for ANY `passed===false` (was non-blocking only),
so below-threshold done segments show a ⚠ dot; stage-summary row also shows ⚠ when
any of its segments warned. Test `test_c1_breach_warns_and_continues` (was
`…_still_fails_the_run`) now asserts completed + samples recorded. oxDNA runner
gate (`oxdna_runner.py:948`) left untouched — separate engine, not in scope.

**Relaxation early-stop accelerator — opt-in, default OFF (2026-07-04):** New
`backend/core/md_cutoff.py` = pure multi-criteria plateau decision
(`should_early_stop_stage(frames, wc_per_frame)` → skip only when POTENTIAL(+VOLUME)
AND WC base-pairing are BOTH flat over the trailing window; energy-alone is unsafe at
low restraint on fragile designs — 2hb_noT k=0.01). Consumes
`namd_metrics.parse_namd_log_frames` (new: returns ALL ENERGY frames, resume-seam
deduped, vs `parse_namd_log`'s last-frame-only). `namd_runner.run_job`: after a chunk's
(advisory) health check, if `job.early_stop_relax` and it's a relaxation stage's
non-final chunk (`_stage_base`/`_stage_last_chunk_idx`, `_is_production_segment` excludes
production/qualification), evaluate the plateau on that chunk's log; on a hit, mark the
stage's remaining p50/p100 chunks `done` + jump `current_segment_idx` past them
(`skip_until` guard at loop top). **Skipped-chunk glyph (2026-07-06):** a skipped chunk
also gets `MdSegmentStatus.skipped=True` (status stays `done` so all rollups/counts are
unchanged); the stage timeline renders it as a green **right-arrow `→`** instead of the
solid green circle, with a tooltip explaining the accelerator skipped it because the stage
already satisfied its plateau requirements. Decision is a pure exported helper
`mdSegGlyphKind(status,{skipped,advisory,jobLive})` (unit-tested), consumed by `_segSymbol`.
`MdJob.early_stop_relax: bool=False` (load-setdefault);
`CreateJobRequest.early_stop_relax` field → set on the job in create route. **Default OFF
= zero behavior change to existing runs** (the whole hook is under `if job.early_stop_relax`).
UI (2026-07-04): `#md-jobs-early-stop` checkbox in the MD launch Advanced card (index.html,
under "Fast relaxation"), read into the create payload as `early_stop_relax` in
`md_jobs_panel.js` (mirrors the `fast`/`autostart` toggles); unchecked by default.
Mid-run toggle (2026-07-05): `POST /md/jobs/{id}/early-stop {enabled}` →
`namd_runner.set_early_stop`. A RUNNING job can't have job.json rewritten by the route
(runner is sole writer), so it stashes `_EARLY_STOP_OVERRIDE[job_id]` which `run_job`
consumes+persists at its next chunk boundary; an idle job is written directly. UI: a
"Early-stop settled stages (live)" checkbox in the job detail (`#md-jobs-early-stop-live`,
shown only for a running local job), client `setMdEarlyStop`. **Pending-state fix
(2026-07-05):** a running chunk can be hours long, so `early_stop_relax` on disk lags
the user's intent that whole time; the old UI re-synced the checkbox to that stale flag
on every 3 s WS push → it "toggled back off". Fix: backend surfaces the queued override
as `early_stop_pending` (via `namd_runner.pending_early_stop`) in the WS payload +
`GET /md/jobs[/{id}]`; frontend `mdEarlyStopToggleState(job, busy)` (pure, unit-tested)
derives `{checked, pending}` — while the override differs from persisted (or a POST is
in flight) the toggle is shown in the REQUESTED position, `disabled` (no spam-toggle),
with a `⧗ pending` span (`#md-jobs-early-stop-live-pending`). Clears when the runner
consumes the override at the next boundary. Tests: `test_{set_early_stop_persists_when_idle,
set_early_stop_override_when_running,pending_early_stop_reports_queued_override,
runner_consumes_midrun_override}`; frontend `mdEarlyStopToggleState` (4 cases).
**Threshold recalibration (2026-07-04, from a live fast run) — LOAD-BEARING:** the first
live run (2hb_noT, `early_stop_relax` on, FAST=HMR+4fs) NEVER skipped: the old single
threshold (`eps_pot`=0.1%, `eps_vol`=0.2% for BOTH drift and scatter) sat *below* fast-run
instantaneous thermal noise (measured POT fluct ~0.13%, VOL ~0.24% even when the mean had
settled to ~0.02% drift). Fix in `md_cutoff.CutoffParams`: **separate DRIFT (mean settled —
tight: `eps_pot_drift`=0.05%, `eps_vol_drift`=0.30%) from FLUCT (thermal-noise guard —
loose: `eps_pot_fluct`=0.35%, `eps_vol_fluct`=0.50%; WC drift 0.02 / fluct 0.05)** and raise
`min_frames` 12→20 so a ~13-frame fast `p10` chunk can't trigger on too little data (skips
are judged on the fuller p50 chunk). Validated per-chunk on BOTH the live run (k0.5 p50→skip
settled, k0.1 p50→hold still-relaxing) AND the exp36 bank (18hb: all 8 non-final chunks skip;
2hb: skips settled restrained stages but HOLDS the true-zero k=0/MGHH melt stage — the
safety-critical property). Regression tests `test_{noisy_but_settled_energy_plateaus,
drifting_mean_not_plateaued_even_if_quiet}`. **A running job imports `md_cutoff` at server
start — a recalibration only affects a NEW job after a server restart.**
Motivated + validated offline by `experiments/exp36_relax_cutoff_bank/` (parser + replay on
real reference runs: 2hb 2.45× / 3x6x200 4.9× / 18hb 11.4× / 3x4SQ 29× multi-criteria
speedup; the gate self-holds fragile low-k stages, cuts hard on over-provisioned ladders).
Tests: `tests/test_md_cutoff.py` (10 — pure decision, frame parser, flag round-trip, and a
stubbed-NAMD `run_job` proving skip + flag-off-runs-all). **NOT yet exercised on a live GPU
relax run** — needs one real run with the flag on to confirm the skipped structure matches a
full run's endpoint (owes an MV row). [[md-prep-relaxation-exp29]], [[oxdna-relaxation]].

**Ensemble-replica timestep fix (2026-07-17):** `md_ensemble.build_replica_package`
received `timestep_fs` but never forwarded it to `build_production_conf` — it passed
only `fast=use_fast`, so the conf integrator relied on the `fast`↔4 fs coincidence. A
**manual 2 fs** replica (`fast=False`) therefore silently emitted a **1 fs** conf and ran
HALF its labelled simulated time (steps computed at 2 fs, integrated at 1 fs). Fix: resolve
one `eff_timestep_fs` (4 fs downgrades to 1 fs when no HMR PSF exists, mirroring
`routes_md._append_production_segments`), recompute `length_ns = steps × eff_timestep_fs`
from it, and pass `timestep_fs=eff_timestep_fs` to both the conf and the manifest slots so
the ns label can never diverge from what NAMD actually integrates. The direct-production
path was already correct. Tests: `test_md_ensemble.py::{test_replica_2fs_conf_runs_at_2fs,
test_replica_4fs_conf_runs_at_4fs, test_replica_4fs_without_hmr_parent_downgrades}`.
Surfaced while diagnosing a `24hb_2xT` local job "crash" (a dev-server restart orphaned a
live NAMD run + mislabelled it `failed` — the sim itself was fine; see below).

**Fast production runs — HMR + GPUresident + 4 fs (2026-07-02):** production was
pinned at ~1.3 ns/day because `_conservative_production_conf`/`_seed_production_conf`
in `routes_md.py` never got the fast-relaxation treatment — they ran `rigidBonds
none` + `timestep 1.0` + no GPUresident (CPU-integrated 1 fs). Applied the shipped
fast-relaxation win (`md_protocols.write_hmr_psf` + GPUresident + 4 fs) to the
production path:
- `_production_fast_plan(job, body)` decides eligibility from the manifest: fast is
  the DEFAULT; a **declash / soft-integrator** relaxation (manifest `declash` or any
  segment `soft:true`) falls back to conservative 1 fs (HMR + rigid bonds crash
  those flexible-bond structures). Also `from_seed` → conservative.
- `_production_steps_and_ns(body, timestep_fs)` now takes the timestep so a
  requested `length_ns` maps to 1/4 the steps at 4 fs (same simulated ns, ~4× fewer
  steps). Callers pass the plan's timestep.
- `_append_production_segments(job, plan, …)` (signature changed from `total_steps`
  int → `plan` dict): if fast, reuse `{stem}_hmr.psf` from a fast relaxation ladder
  or build it once via `write_hmr_psf`; write fast confs (HMR PSF + `rigidBonds all`
  + `timestep 4` + `GPUresident on` + `fullElectFrequency 2`). **Electrostatics
  (PME grid 1.0, cutoff 12, barostat coupling) are LEFT IDENTICAL to the
  conservative run** — same production ensemble, only integrator/throughput knobs
  move. Manifest `production_extension` gains `fast_production{…}` + `settings:
  "fast_hmr_gpuresident_4fs"`.
- Runner needs NO change: health check keys off the original `{stem}.psf`/pdb (HMR
  only rewrites masses, not topology/coords/order); resume (`_write_resume_conf`)
  preserves the structure line + GPUresident (neither in `_RESUME_DROP`).
- Compounding win: 4 fs (4×) × GPUresident (~3×) × MTS ≈ ~10× → 1.3 → >16 ns/day.
- Tests: `test_md_milestone1.py` — `test_appended_production_uses_fast_hmr_settings_by_default`,
  `test_declash_job_falls_back_to_conservative_production`, updated steps/ns test.
  Full suite green (3523 passed). NOT yet benchmarked on a real GPU production run —
  the ns/day claim is projected from the fast-relaxation validation, not measured
  on this production path.

**User-selectable production timestep — 1/2/4 fs (2026-07-16):** the Advanced card gained a
**Production timestep** dropdown (`#md-jobs-prod-timestep`, index.html) so the dt is no longer
implied purely by the `fast` checkbox. Wire: dropdown → `CreateJobRequest.production_timestep_fs`
(validated ∈ {1,2,4}) → `manifest["production_timestep_fs"]` (written in `md_protocols`
prepare) → `_production_fast_plan` (manifest value wins; falls back to the old fast?4:1
derivation for pre-existing packages) → `build_production_conf(timestep_fs=…)`. Three integrator
paths: **4 fs** = HMR + `rigidBonds all` + GPUresident (needs the fast relax ladder / HMR PSF);
**2 fs** = `rigidBonds all` + GPUresident on *standard* masses (no HMR — the manual medium path);
**1 fs** = conservative reference (`rigidBonds none`, no GPUresident). A declash design requesting
4 fs is still force-dropped to 1 fs. `require_sanctioned_production_timestep` now takes
`allow_manual_2fs` (2 fs allowed ONLY via the explicit manual selection, never the auto path;
2.5/3/3.5 still banned) — see [[feedback_namd_4fs_production_only]]. A warning appears under the
Fast checkbox (`productionTimestepWarning`, `md_advanced_optimize.js`) when 4/2 fs is picked
without the fast relax ladder. Also fixed the **production-time ETA**: it was hard-coded to
`_PRODUCTION_TIMESTEP_FS = 1.0`, under-reporting every fast run's simulated ns by 4× — now
`productionNsFromSteps(steps, ts)` + `jobProductionTimestepFs(job)` use the real dt, and the
"Total time" readout shows the assumed fs. Tests: `test_md_production_timestep.py` (16),
`md_advanced_optimize.test.js` + `md_jobs_panel.test.js` (pure helpers).

**Disk-space guard + forecast (2026-07-02):** new `backend/core/disk_guard.py`
owns the whole "will this run out of disk" policy for BOTH engines:
- Thresholds: `WARN_MIN_FREE_BYTES=10 GiB` (pre-run popup), `ABORT_MIN_FREE_BYTES=5
  GiB` (in-run kill), `GUARD_POLL_S=15`, sentinel `DISK_ABORT_RC=-99`.
- `free_bytes(path)` (walks to nearest existing ancestor; returns 1<<62 on OSError
  so a stat hiccup never aborts a run). `namd_run_output_bytes(segments, n_atoms)`
  (DCD ≈12·n_atoms+80 B/frame + 48·n_atoms restart/seg, ×1.15 safety);
  `oxdna_run_output_bytes(stages, n_nt)` (~130 B/nt/frame; oxDNA prints ~100
  configs/stage so it's bounded/small — the warn rarely fires for CG, but the
  abort guard still protects a near-full disk). `forecast(dir, predicted)` →
  {free_bytes, predicted_bytes, free_after_bytes, warn, …}.
- `wait_proc_with_disk_guard(proc, dir, kill=…)` wraps `proc.wait()`
  (`asyncio.wait_for` polled): on free<floor it kills the process group and
  returns `DISK_ABORT_RC`. Called from BOTH `_run_namd_async` and
  `_run_oxdna_async` (replacing the bare `await proc.wait()`).
- Runners also do a **pre-launch floor check** before minimization + each
  segment/stage (`namd_runner._disk_floor_ok`; inline in oxdna_runner) and map
  `DISK_ABORT_RC` → `status=failed`, NAMD `failure_kind="disk_full"`, with a
  "free up space then resume" error. In oxDNA the sentinel is handled BEFORE the
  crash-retry block so it doesn't trigger dt-halve / relax-escalation.
- Forecast endpoints: `POST /md/jobs/estimate-disk` (relax; active design +
  `mgh_slow_release_segments` + `estimate_profile_from_design`),
  `POST /md/jobs/{id}/estimate-production-disk` (exact PSF `!NATOM` count),
  `POST /oxdna/jobs/estimate-disk`, `POST /oxdna/jobs/{id}/estimate-run-disk`.
  All best-effort → `skipped:true` / warn=false on any error (never block a launch).
- Frontend: `job_activity.js` gains pure `diskWarningMessage(forecast)` +
  `confirmDiskSpaceOk(forecast)` (reuses `showConfirm`), mirroring
  `confirmNoConcurrentJob`. Wired into 4 launch handlers (MD relax/production,
  oxDNA relax/production) right by the existing concurrent/GPU confirms. Client
  fns: `estimateMdDisk`, `estimateMdProductionDisk`, `estimateOxdnaDisk`,
  `estimateOxdnaRunDisk`. Tests: `tests/test_disk_guard.py` (9),
  `job_activity.test.js` diskWarningMessage block. VERIFIED via curl on a real
  job: 100 ns production → predicted 24.7 GB vs 20.6 GB free → warn:true; 1 ns →
  warn:false. In-browser popup click NOT hand-exercised.

**MD↔oxDNA panel unification + viz radios (2026-07-02):** made the MD job list
mirror the oxDNA panel's indented parent→child hierarchy, and both panels' display
toggles mutually-exclusive radios in a "Visualizations & processing" card.
- `MdJob.parent_job_id` (new field; `new_job(parent_job_id=…)`, load-setdefault).
  `routes_md._spawn_prep_job(parent_job_id=…)`; the **refit** endpoint passes
  `parent_job_id=<old job id>` so a refit/retry-derived job nests under its origin.
  (SUPERSEDED 2026-07-07 — production now ALSO spawns a nested child job, not
  same-job segments; see "Production = child job" below.)
- Frontend: `flattenJobTree`/`descendantIds` moved out of `oxdna_jobs_panel.js` into
  shared `ui/job_tree.js` (re-exported from the oxDNA panel for existing importers;
  `job_tree.test.js`). MD `_renderList` rewritten to flatten + indent by depth via a
  new `_jobRow` (mirrors oxDNA), children labelled `Refit N` (`mdChildRowLabel`,
  global run number). Removed the old flat `slice(0,8)`.
- Radios: `index.html` viz toggles for BOTH panels are `type=radio` sharing a group
  name (`md-viz` / `oxdna-viz`) inside an `.ox-card` titled "Visualizations &
  processing", plus an explicit **Off** radio (`*-viz-off`, checked by default).
  oxDNA views = display/flex/deviation/traj; MD views = display/flex/traj. oxDNA
  "Align to design pose" stays a checkbox (a display modifier, not a view). The
  existing per-view "on" handlers already tore the others down; added an Off-radio
  handler (`_allDisplaysOff` on oxDNA; the three teardowns on MD) and a
  `_syncVizOffRadio()` called from every `_setXOff`/guard-return so the group always
  shows a selection after a programmatic turn-off. Element IDs unchanged, so all the
  intricate display/prewarm `.checked` reads keep working.
- LAYOUT (unified 2026-07-02 follow-up): the viz card is now a **collapsible
  `ox-card` positioned directly below the Jobs list** in BOTH panels (MD: after Jobs,
  before Advanced; oxDNA: between Jobs and Health — pulled OUT of `#oxdna-jobs-detail`
  so it's always visible). Collapse wiring added to each panel's Jobs/Health toggle
  loop (`{md,oxdna}-jobs-viz-toggle`/`-body`/`-arrow`, start open, non-persistent).
  GATING: with no job selected only "Off" is selectable — MD `_updateVizToggles(job=
  _selectedJob())` disables display when `!job` and flex/traj when no trajectory
  (called from `_applyJobState`, `_clearSelectedJob`, and once at init); oxDNA
  `_updateButtons` already gated flex/traj/deviation on `samplingState`/`hasTrajectory`
  (null-job → disabled), and the display radio now also gates on `!!job` (was liveOn
  only, fine when the card was hidden in the detail). `_syncVizOffRadio()` keeps Off
  checked whenever nothing is selectable.
- Verified: `test_md_milestone1.py::TestMdJob` (8, incl. parent_job_id roundtrip),
  full frontend vitest 1853 green, `just smoke` 22/22 (console-error gate), and a
  throwaway Playwright spec against the live app confirming both cards render, the
  radios are grouped/mutually-exclusive, Off is default-checked, and select→Off
  round-trips (spec deleted after).

**Early-stop restart-chain fix (2026-07-05):** The relaxation early-stop
accelerator (`early_stop_relax`; `md_cutoff.should_early_stop_stage`) marks a
plateaued stage's trailing p50/p100 chunks `done` WITHOUT running NAMD, then jumps
to the next stage. But each stage's first chunk conf was packaged to restart from
the *previous stage's LAST chunk* (e.g. `02_p10` reads `01_..p100.{coor,vel,xsc}`).
Skipping that last chunk meant its restart files never existed → NAMD `FATAL ERROR:
Unable to open extended system file` (job `3f4d932cd76c`). Fix:
`namd_runner._alias_skipped_stage_outputs()` copies the last *completed* chunk's
final coords onto every skipped chunk's expected output names (plain + `.restart.`)
so the chain stays intact; called from the skip block in `run_job`. Pinned by
`test_early_stop_skips_remaining_chunks` (asserts the bridge files exist).

**Host-OOM bounded auto-resume (2026-07-07):** A host pinned-memory OOM (`FAILURE_HOST_OOM`,
`cudaHostAlloc` in bonded-CUDA staging — [[water-shell-carve]]) is usually a TRANSIENT host
starvation (the identical alloc succeeded on the previous segment; the supervisor's ~30 s relaunch
cadence lets pressure clear). `run_job`'s `rc!=0` handler now mirrors the cell-shrink block for
`host_oom`: leave the job RUNNING (segment→running, `failure_kind=None`, `auto_resumes++`), bounded by
`MAX_HOST_OOM_RESUMES=3`, past which it fails normally with the host-OOM Fix popup. UNLIKE cell-shrink
it does NOT require a mid-segment checkpoint — a step-0 death (no restart files) re-runs the segment
fresh from the previous segment's coords. Also `_free_host_ram_for_namd` releases NADOC's atomistic
cache before each spawn when RAM is low (see [[md-live-model-cache]]). Tests:
`test_host_oom_auto_resumes_without_a_checkpoint`, `test_host_oom_gives_up_after_resume_cap`.
Diagnosis of the original failure: WSL2 24 GB box, 404k ENM springs; real error was host pinned RAM,
NOT the "3.0 GB / 8.0 GB card" the old classifier misreported.

**Production = child job (mirrors oxDNA `/oxdna/jobs/{id}/run`) — 2026-07-07:** MD
production used to APPEND p10/p50/p100 segments onto the SAME relaxation `MdJob`, so
the relaxation stopped being a distinct entry and you couldn't fan out several
productions. Now the Production button spawns a **child `MdJob`** seeded from the
parent's equilibrated checkpoint, exactly like oxDNA's child runs — the relaxation
stays a selectable root row and each production nests under it.
- **Endpoint** `POST /md/jobs/{parent_id}/production-run` (`routes_md.spawn_md_production`,
  body `ProductionRunRequest{steps,length_ns,autostart}`). Resolves the seed coords via
  `_production_seed_checkpoint(parent)` — a relaxation parent → `_production_ready_checkpoint`;
  a completed production child → `_completed_production_checkpoint` (so selecting a finished
  production and clicking Production **chains** a fresh run off its end state). Reuses
  `md_ensemble.build_replica_package` VERBATIM (single seed) to build the production-only
  child package (reseed conf in the `minimization` slot → one production segment). Child gets
  `parent_job_id=parent`, `run_kind="production"`, a distinct velocity `ensemble_seed`
  (**randomised per run** — see "Velocity seeds are drawn, not fixed" below), takes its
  run target from the request; local + autostart → `start_job` immediately. Parent job is
  NEVER mutated (its segments/manifest untouched) — verified live on `c0e02dadf996` (2hb_noT).
- **Alpine target (fix 2026-07-07):** the Production button must honor the panel's
  Local/Alpine radio (`_currentRunTarget()`), NOT the parent's target — a locally-relaxed
  structure is commonly produced on Alpine. `ProductionRunRequest` gained
  `execution_target`/`cluster_name`; `spawn_md_production` sets `child.execution_target =
  body.execution_target or parent's or "local"` and **only autostarts when target=="local"**
  — an `alpine` child is left `queued` (no `start_job`) for the submit-review card. Frontend
  prodBtn: reads the radio, skips the local disk/concurrent guards for Alpine, passes
  `execution_target`+`autostart:isLocalRun`, and on an Alpine spawn opens
  `_submitReview.open(childId)` (same card the relax/ensemble Alpine paths use → resource
  sizing + SLURM submit; Duo needed). Bug it fixed: the first cut inherited the parent's
  `execution_target`, so selecting Alpine still launched a LOCAL production. Test
  `test_production_alpine_target_queues_without_local_start` (queued alpine child, `start_job`
  never called); verified live (child `queued`, exec=alpine, namd_pid None).

**Ensemble/remote readout UX (2026-07-07, frontend-only):** the detail panel was built for
a single LOCAL job; selecting an ensemble parent or a remote replica mis-behaved. Fixes in
`md_jobs_panel.js`:
- **No local WS for cluster jobs.** `_openDetailForJob` opened `ws://…/ws/md-jobs/{id}` for
  any non-terminal job, but a job handed to SLURM (`slurm_job_id` set) pushes nothing locally.
  Now gated on `!job.slurm_job_id` — a remote job's detail is refreshed by the SLURM poll
  (`_maybePollRemote → _applyJobState`), not a dead WS. (A LOCAL prep of an Alpine relaxation,
  no slurm id yet, still gets its WS for the solvation bar.)
- **Remote in-flight jobs show a note, not a perpetual spinner.** A running Alpine replica has
  0 local health_samples (metrics live on cluster scratch until results fetch), so `mdJobIsActive`
  true + no metrics → the old code span "Waiting for first metrics…" forever. New pure
  `mdHasLocalReadouts(job)` (local always; remote only once `health_samples` present) +
  `mdRemoteReadoutNote(job)`; `_renderMetrics` short-circuits to the note ("Running on Alpine
  (SLURM …) — live metrics aren't streamed for cluster runs…") + `_setHealthSpinner(false)`.
- **Ensemble roll-up in the detail.** New `#md-jobs-ensemble-rollup` + `_renderEnsembleRollup(job)`:
  when a parent OR one of its replicas is selected, lists every replica (`mdReplicaRowLabel` /
  `mdProductionRowLabel`) with its SLURM state (`mdReplicaStateText`), clickable to jump. Header
  reuses `ensembleChildSummary`. Pure `ensembleReplicas(job, jobs)` (sorted by ensemble_index).
  So selecting the "N replicas" parent reads as the ensemble, not just the underlying relaxation.
- Pins: `md_jobs_panel.test.js` (+4 blocks: mdHasLocalReadouts / mdRemoteReadoutNote /
  mdReplicaStateText / ensembleReplicas). VERIFIED LIVE against the 4-replica 6hbx100_1xT
  ensemble (parent roll-up lists 4 RUNNING replicas w/ SLURM ids; replica shows the Alpine note;
  no local WS opened for a cluster job). **Watch:** when a replica finishes, local health/metrics
  populate only if the backend fetches results on SLURM completion — confirm that path once a
  replica completes so the grid fills in (else it stays on the note).
- **New `MdJob.run_kind: Optional[str]=None`** (load-setdefault; `new_job(run_kind=)`).
  `"production"` marks a production child; None = relaxation / refit / Alpine ensemble replica.
- **Old `append_md_production` (`/md/jobs/{id}/production`) endpoint kept** (still client-exported
  + doc-header-tested) but the app no longer calls it.
- **Frontend:** `client.spawnMdProduction`; the prodBtn handler calls it then selects the NEW
  child. `_renderProductionControls` gates on `production_ready || production_continue_available`
  (chain mode) — the old `continue_from_production` checkbox (`#md-jobs-prod-continue`) is GONE,
  replaced by a static hint. New pure helpers `mdIsProductionChild(job)` (run_kind check) +
  `mdProductionRowLabel` ("Production N · seed S"); `_jobRow` branches label/title on it.
  `mdIsEnsembleReplica` still matches production children (ensemble_seed set) so they indent +
  collapse under the parent via `flattenJobTree` — but auto-collapse is now scoped to
  Alpine ensembles ONLY (a production fan-out keeps the just-started child visible).
  `ensembleChildSummary` says "N production runs" vs "N replicas" by child kind.
- **Tests:** `test_md_milestone1.py::TestProductionAppend` (+4: child-created-parent-intact,
  distinct-seeds, autostart-launches-local, refused-while-running); vitest
  `md_jobs_panel.test.js` production-child block (+4). Full backend `just test` green apart
  from 2 pre-existing xdist cross-file ordering flakes in `test_md_executor.py`
  (`test_remote_recommendation_unknown_{profile,partition}` — pass in isolation, unrelated
  cluster-recommendation code). NOT hand-clicked in the browser, but the full backend path +
  rendered data shape were exercised live via curl against a real completed relaxation.
  [[alpine-cluster-submission]] (ensemble replica machinery this reuses).

**Legacy-job migration — revert appended production (2026-07-07):** Jobs created before
the child-model have production p10/p50/p100 segments APPENDED onto the relaxation, so
they show as ONE combined entry. `md_job.revert_appended_production(job, ws)` peels them
back to a clean completed relaxation: drops the production segments from `job.segments` +
`manifest["segments"]`, removes `production_extension`, restores `status=completed` /
`current_segment_idx=len(relax)` / `user_stopped=False` / `error=None`. **Non-destructive**
— the production confs/logs/output are MOVED (`Path.replace`) to
`{job_dir}/_superseded_production/` (preserving the package-relative tree), NOT deleted, so
a stopped-mid-run partial trajectory is recoverable. Dot-prefixed output globs
(`output/{name}.`) so a `_p10` segment never sweeps `_p100` files. Idempotent; refuses a
production child (`run_kind=="production"`) or any derived job (`parent_job_id`) so it can't
nuke a legit run. Helper `segment_is_production(job)` / `_is_production_segment_name`.
Endpoint `POST /md/jobs/{id}/revert-production` (`routes_md.revert_md_production`, 400 if
running / nothing to revert). Frontend: pure `mdHasAppendedProduction(job)` (root relaxation
carrying a production segment) gates a `#md-jobs-revert-prod-btn` "⧉ Separate production into
its own run" button in the production box (`_renderProductionControls`), `client.revertMdProduction`,
`window.confirm` + toast, reselects the now-clean relaxation. Tests: `test_md_milestone1.py`
(+2: restores-clean-relaxation incl. p10/p100 glob + backup-not-deleted + relax-checkpoint-intact;
idempotent-and-guards-children); vitest `mdHasAppendedProduction` (+4). VERIFIED LIVE on
`a0e54cdbf20f` (6hbx100_1xT): 15→12 segs, 80 MB partial production moved to backup, then a
fresh production child spawned off the cleaned relaxation.

**Archived-abandoned remote jobs no longer render as "queued" forever (2026-07-16):**
Symptom — dozens of old 24hb runpod jobs (and a few alpine) showed in the panel as
active "queued" rows (○ badge + spinner) despite being archived + days old. Root cause
was NOT a display bug: `status="queued"` is truthful. A remote job is BORN `queued`
(`md_job.new_job`) and leaves it ONLY via a manual Start (runpod) / submit-review (alpine)
— nothing auto-launches it, and `reconcile_job_status` returned ALL remote jobs untouched
(`execution_target != "local"`), so a prepared-but-never-launched remote job stays `queued`
indefinitely (this is a LEGIT state for a non-archived job — panel "awaiting Start/submit").
Archiving is status-blind (moves the folder, never touches `status`), so an archived job the
user put away kept the active-looking queued row. Fix: `namd_runner._remote_job_abandoned_queued`
— an **archived** remote job at `queued` with **no remote handle** (`runpod_pod_id`/`slurm_job_id`
both None) and `created_at` older than `_ABANDONED_QUEUED_MIN_AGE_S` (1 h, so it can't race an
in-flight CLI archive-from-birth launch that's briefly archived+queued before `run_job_on_pod`
stamps the pod id) is retired to `stopped` + `user_stopped=True` + `error=None` (clean-stop UI,
no resume). Applied inside `reconcile_job_status`'s remote branch, so every panel/list/WS read
heals it and persists to the archive; **no migration needed** — the records flip on the next
`GET /md/jobs`. Save is try/except-guarded (archive drive may be offline → heal next load).
**Deliberately scoped to `queued` only:** a non-archived queued job (awaiting Start/submit),
a recently-created one (launch race), or one carrying a pod/slurm id is PROTECTED. Archived
`running`-with-pod phantoms (e.g. runpod jobs whose launcher died) are left to the pod-aware
`_collect_active` reaper in `routes_jobs.py` (billing safety — needs live-pod verification, not
blind reaping). Tests: `test_md_resume.py::TestReconcileAbandonedRemoteQueued` (5 — runpod/alpine
reap, non-archived protect, launch-race protect, pod-id protect). [[job-archive]].

## ⚡ Implicit-solvent (GBIS) protocol — no-water relaxation for small GPUs (2026-07-11)
Third protocol `implicit_gbis_namd` (`IMPLICIT_GBIS_PROTOCOL`, in `md_protocols.SUPPORTED_PROTOCOLS`).
**Why:** a large single-layer origami (e.g. GT_corner_v2, ~287k DNA atoms) in explicit water balloons to
~1.9M atoms and NAMD dies at `buildTileLists` on an 8 GB GPU (VRAM). GBIS (Generalised Born) drops the
system to DNA-only, so it fits. Trade-off (stated in UI/manifest): **no explicit Mg²⁺** → relaxation/
minimise engine, not a Mg-stability model.
- **Builder:** `backend/core/namd_gbis.py` (NEW module — kept out of the md_protocols god-file).
  `build_namd_gbis_package` reuses `build_charmm_psfgen_topology` (the SAME H-complete dry PSF/PDB the
  explicit strict path builds *before* solvation) → copies forcefield → ENM (`write_aksimentiev_enm_files`)
  → **NVT-only** ladder (`mgh_slow_release_segments(nvt_only=True)`, no barostat in implicit) → GBIS confs.
  `prepare_implicit_gbis_namd` is the protocol entry (accepts+ignores the explicit-solvent kwargs so
  routes_md passes one uniform kwarg set). Salt: `ion_conc_mM`→GBIS Debye `ionConcentration` (M), else 0.15.
- **Conf change:** `md_protocols._common_header(gbis=…)` swaps the periodic-box+PME block for the GBIS block
  (`gbis on / alphaCutoff 14 / ionConcentration / solventDielectric 78.5`, cutoff 16/switch 14/pairlist 18,
  NO cellBasisVector, NO PME, NO wrapWater). Threaded through `_min_conf`/`_segment_conf`; NPT + fast/HMR
  (GPUresident) forced OFF under GBIS.
- **Prep phases:** `build_prep_phases(implicit=True)` drops `solvate`+`assemble` (→ topology·enm·finalize,
  n_phases=3). routes_md also **skips the `auto_water_shell` VRAM preflight** for GBIS (no water box; that
  preflight is SLOW on large designs — builds the full atom model to count).
- **Dispatch:** routes_md `_prepare_job_bg` maps protocol→prepare fn (gbis branch lazy-imports namd_gbis).
- **⚠️ Runs on the CPU NAMD build, NOT CUDA.** GBIS is unsupported on the NAMD 3 CUDA nonbonded kernel
  ("Warning: Always using force tables … unsupported config parameters" → `buildTileLists` illegal-memory
  crash on the FIRST step) EVEN at 445k atoms (so it was never a VRAM problem — atom count is irrelevant
  to that crash). `namd_runner.find_namd(prefer_cpu=True)` returns the first non-CUDA (`…-multicore`) build
  and `run_job` passes `run_devices=""` (no `+devices`) for `implicit_gbis_namd`; raises a clear error if
  only a CUDA build is installed. VERIFIED: same GT_corner_v2 GBIS package → CUDA build crashes at
  buildTileLists; `…Linux-x86_64-multicore` build minimizes fine (clash count falls, GBIS energy finite).
  **Caveat:** CPU GBIS is slow — minimize (4800 steps) is minutes, but the full 12-segment ×2.4M-step
  ladder is impractical on CPU; use it to minimize/declash a seed + short relax (early-stop), not full
  production. See [[LESSONS]] K4.
- **Frontend:** third `<option value="implicit_gbis_namd">` in the Protocol `<select>` (`#md-jobs-preset`,
  index.html) — flows straight into the payload `protocol` + restores via `_maybePrefillDraft`. Pure
  `isImplicitSolventProtocol()` grays the explicit-only knobs (salt/mg/nacl/padding/watershell/fast) via
  `_syncSolventFields()` on preset change.
- **Tests:** `tests/test_md_gbis.py` (7: registered, phases drop solvation, dry PSF has no water/Mg, every
  conf is GBIS-not-PME, NVT-only ladder, ENM present+referenced, salt maps mM→M); vitest
  `isImplicitSolventProtocol` (+1). Backend prep VERIFIED headless (no GROMACS) + live via the API on
  GT_corner_v2 (n_phases=3 confirmed). **App click-through of the dropdown NOT yet exercised live** (option
  is served + payload wiring is unit-tested).
- **Known cosmetic:** GBIS segments inherit the explicit ladder's names (`…_300K_NPT_ENM_…`, `…MGHH_only`)
  from the shared `mgh_slow_release_segments`; the confs are correctly NVT/GBIS but the stage LABELS still
  say NPT/MGHH. Left as-is to avoid touching the shared segment naming (resume/manifest key on it).

## ⚡ Compute: GPU/CPU selector (any protocol can run on the CPU build) — 2026-07-11
Generalised the GBIS CPU routing into a first-class **Compute** choice, because the CUDA `buildTileLists`
crash is NOT memory (K2). PROVEN: the SAME 1.72M-atom explicit shell-solvated GT_corner_v2 that crashes on
the CUDA build **minimizes fine on the `-multicore` build** (real water + Mg²⁺ intact, energy dropping).
So CPU is a valid escape hatch for ANY protocol on a system the GPU can't take.
⚠️ The old "large lateral footprint / too many patches" explanation is **superseded** — see the GPU
pre-flight probe section below and K2. The crash is not a function of the patch grid at all.
- **Encoding:** the job's `devices` string carries the choice — `"cpu"`/`"none"` → CPU build; GPU ids
  (`"0"`, `"0,1"`, empty=auto) → CUDA build. `namd_runner.job_wants_cpu(protocol, devices)` (GBIS always
  True) + `resolve_namd_launch(protocol, devices) → (namd_bin, run_devices)` pick the binary robustly across
  ALL install combos: both builds present (honour choice); CPU-only machine (GPU request degrades to
  multicore, no `+devices`); CUDA-only machine (explicit CPU request best-efforts to GPU; GBIS raises).
  `run_job` calls the resolver.
- **auto_water_shell is now CPU-aware** (`md_vram.py`): `devices="cpu"` → skip VRAM, size the carve to
  **host RAM** (`max_atoms_for_host_ram`) — the carve still helps (fewer atoms = faster CPU). routes_md's
  preflight runs for CPU too (only GBIS skips it entirely — no water box).
- **Frontend:** `#md-jobs-compute` `<select>` (GPU (CUDA) / CPU (multicore)) in the Advanced drawer. Pure
  `deviceStringForCompute(compute, cudaDevices, protocol)` builds the payload `devices`; `computeFromDeviceString`
  restores it for drafts. GBIS forces Compute=CPU + **disables the GPU option** (auto-reverts a prior GPU
  pick) and grays the CUDA-device field, via `_syncSolventFields()` (bound to preset+compute change). The
  GPU-busy confirm is skipped for CPU runs.
- **Tests:** `test_namd_discovery.py` (job_wants_cpu param table + resolve_namd_launch across every build
  combo, incl. degrade/raise); `test_md_vram.py` (CPU sizes to host RAM not VRAM; no-host → full box);
  vitest `deviceStringForCompute`/`computeFromDeviceString`. **Managed CPU explicit run VERIFIED live** end
  to end (job 598… → prep w/ CPU host-RAM shell → `Linux-x86_64-multicore` binary → minimizing, 0 FATAL).
  Compute dropdown served in-app; **the GBIS→force-CPU dropdown INTERACTION not click-verified live** (pure
  logic is unit-tested + served).
- **Benchmarks (RTX 2080 SUPER 8 GB / 8-thread CPU, NAMD 3.0.2):**
  - Small explicit 4hb, **103,745 atoms**, 1200-step min: **GPU 12.0 s vs CPU 115.8 s → GPU ~9.7× faster**.
    → Use GPU whenever the system fits; CPU is the fallback, not the default.
  - GT_corner_v2 explicit shell, **1,716,606 atoms**: GPU **crashes** (footprint); CPU **1.43 s/step**
    (2400-step min ≈ 57 min). GBIS variant (445k atoms) is ~4× lighter on CPU.
  - Takeaway: on this 8 GB card GT_corner is CPU-only either way (explicit=tile-list crash, GBIS=CUDA-
    unsupported). Explicit-CPU gives Mg but is ~4× heavier than GBIS-CPU; the full MD ladder is impractical
    at 1.7M atoms on CPU — use CPU for minimize/declash + short relax. See [[LESSONS]] K2, K4.

## 🧠 GPU-resident needs PINNED host RAM — probe it, and downgrade 4 fs → 2 fs (2026-07-12)
The fast segments (HMR + `rigidBonds all` + 4 fs + **`GPUresident on`**) pin a large host buffer.
**A host's pinned pool is NOT its free RAM**: this WSL box pins only **1.0 GB** with 15 GB free
(`ulimit -l` is 64 MB yet CUDA pins 1 GB → RLIMIT_MEMLOCK is not the constraint; it's the WSL2
driver's pool, unraisable). Above ~800k atoms NAMD dies at segment **start**:
`FATAL ERROR: CUDA error cudaMallocHost(...) in CudaUtils.C, allocate_host_T, line 88`.
Measured ceiling: 380k/541k/756k RUN · **971k FAILS**; GT_corner_v2's 1.44M-atom relax package fails.

- ~~**INVARIANT — `GPUresident off` alone is NOT a valid fallback.**~~ **SUPERSEDED 2026-07-12.** The
  claim that 4 fs survives only under GPU-resident's constraint solver is **false when the HMR PSF is in
  play**: HMR + `rigidBonds all` + 4 fs on the CUDA-**offload** path ran 60k steps (240 ps) from the p10
  checkpoint with T flat at 298–299 K and zero RATTLE failures (18.8 ns/day, carved 6hbx100_90deg). The
  original "instant Constraint failure in RATTLE" was a *strained start*, not the timestep. Carved
  packages are now written at 4 fs + offload **directly** and never pass through the downgrade.
  `downgrade_gpu_resident()` still halves the timestep, but only for the pinned-OOM case below, where it
  is cheap insurance on an already-huge system.
- **A CARVE AND `GPUresident` ARE MUTUALLY EXCLUSIVE** — a second, unrelated failure mode
  ("Low global CUDA exclusion count!", fatal at step 0 on any cell containing vacuum; NOT fixed by the
  K2 patch). `_segment_conf(carved=...)` now refuses to emit `GPUresident` on a carved package.
  See [[LESSONS]] **K2b** and [[project_water_shell_carve]] — read before touching this.
- **What ships:** `namd_runner.gpu_resident_probe()` (one cycle of the first fast conf, ~60 s, cached
  as `.gpu_resident_probe.json`). It **must run AFTER minimisation** and be seeded from the minimisation's
  output (`seed_stem`): from raw build coordinates the ideal-B-DNA clashes blow the integrator up at
  step 1 ("Atoms moving too fast") *before* the GPU-resident checks fire — which is exactly how a
  GPU-resident-incompatible package reached production once. On failure `downgrade_gpu_resident_confs()`
  rewrites every fast conf
  via `md_protocols.downgrade_gpu_resident()`: drop GPUresident, **4→2 fs, and ×2 on `run` +
  `dcdFreq`/`restartfreq`/`xstFreq`/`outputEnergies`** so the segment covers the SAME simulated time and
  writes the SAME frame count. HMR/rigidBonds/PSF/PME/barostat untouched → physics unchanged. Originals
  kept as `<name>.conf.gpuresident`.
- **Probe, don't threshold:** the ceiling is a property of the HOST, so an atom-count cutoff fitted here
  would be wrong on the 3080 Ti box. Tests: `tests/test_md_gpu_resident.py`. See [[LESSONS]] K6.

## 🔬 GPU pre-flight probe — the Compute decision is now PRINCIPLED, not manual (2026-07-11)
Root-caused the CUDA `buildTileLists` crash with `compute-sanitizer` and replaced the blunt manual toggle
with an empirical pre-flight. **Read this before touching GPU/CPU routing.**

**The crash.** NAMD counts tile lists on the CPU (to size the kernel's loop) but fills them on the GPU.
When the CPU count is larger, the tail of `tileLists[]` is never written; the kernel reads those **zeroed**
entries and dereferences them into `boundingBoxes` far out of bounds (measured: index 184,320 into a
13,166-entry array) → `cudaErrorIllegalAddress` on the first step. `boundingBoxes` is unguarded in that kernel.

**INVARIANT — do not re-derive this.** The crash is **NOT a function of the patch grid**, so any
`patch_grid_is_gpu_safe(Px,Py,Pz)` API is unsound. Decisive test: box held byte-identical (grid 26×3×34,
P=2652), only the water shell varied → 0.5 nm/380k atoms **CRASH**, 1.0 nm/611k **RUN**, 1.5 nm/782k **RUN**.
Same geometry, opposite verdicts; *adding* atoms can fix it. The real variable is the tile-list count
≈ `14·P·⌈atoms/(32·P)⌉`, and it fails in **BANDS** (safe <~183k · CRASH ~186k–250k · safe ~251k–333k ·
CRASH ~360k+), not above a threshold. That estimate separates 34/35 measured configs but mispredicts
carved-shell systems (uneven per-patch density) — it can **flag risk but never certify safety**, which is
exactly why routing on a formula was rejected. NAMD 3.1 does **not** fix the bug upstream.

**What ships.** `namd_runner.gpu_tilelist_probe(package_dir, min_name, namd_bin, devices, threads)` runs ONE
minimization cycle on the GPU (NAMD rejects step counts that aren't a multiple of `stepspercycle`, hence one
cycle) with `outputName` diverted to a scratch stem so the real `output/` is never touched. ~5–15 s; verdict
cached in the package as `.gpu_tilelist_probe.json` so a resume never re-pays. `run_job` calls it via
`asyncio.to_thread` (it's a blocking subprocess — calling it directly would stall the API event loop) and,
when unsafe, re-resolves to `find_namd(prefer_cpu=True)` with no `+devices`. Verified 4/4 exact against real
crashing/running packages. **Fails open** (probe error → assume safe; a broken probe must never block a job)
and is skipped entirely for Compute=CPU / GBIS jobs. Diagnostic `_gpu_probe.log` is left in the package.

**Tests:** `tests/test_namd_gpu_probe.py` (conf rewrite, verdict, caching, cleanup, fail-open, devices
wiring); `test_md_runner_proceeds.py::test_gpu_unsafe_geometry_reroutes_to_cpu_build` / `..._safe_geometry_
stays_on_cuda_build` / `..._cpu_job_never_pays_for_the_probe`. See [[LESSONS]] K2.

## ✅ SOLVED — the crash is a ONE-LINE NAMD BUG; patched build now ships (2026-07-12)
Got the real 3.0.2 source. NAMD counts tile-lists twice: host `(n-1)/32+1` vs device `(n+31)/32`. They
differ **only for an EMPTY patch** (host 1, GPU 0), so every compute with an empty i-patch leaves an
uninitialised tile-list entry → the kernel reads it → wild `boundingBoxes[]` index → illegal address.
Empty patches = **vacuum at the box corners** of a solvent-carved origami, which is why this hits us.

- **Fix:** `tools/namd_tilelist_fix/` (1-line patch + `build_patched_namd.sh`) →
  `~/Applications/NAMD_3.0.2p1_Linux-x86_64-multicore-CUDA/`. `find_namd()` prefers it **automatically**
  (reverse-sorts `~/Applications/NAMD_*`; `3.0.2p1` > `3.0.2_`) — **no NADOC code change**.
- **Proof it's causal:** an UNPATCHED rebuild from the same tree + same CUDA 12.6 toolchain still crashes
  13/13; the patched one runs 13/13. Patched GPU matches the CPU build to ~0.02% total energy.
- **⚠️ The other computer still runs stock NAMD** until `build_patched_namd.sh` is run there (needs
  `sudo apt install cuda-toolkit-12-6` and the source tarball; use `sm_86` for the 3080 Ti). Until then its
  GPU jobs are covered by the pre-flight probe above — that's why the probe stays.
- Corrects two earlier claims in this file's history: the crash is **not** a "large lateral footprint"
  (that was correlation), and NAMD 3.1 **does** fix it upstream (dev routes the host count through
  `computeNumTiles()`).
