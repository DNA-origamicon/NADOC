---
name: project_oxdna_efield
description: PLAN ONLY (2026-06-18) — electric-field forces in oxDNA via per-nucleotide string forces + overhang/cluster anchor traps; new field-production stage; deflection-map + field-arrow viz in the Dynamics panel.
metadata: 
  node_type: memory
  type: project
  originSessionId: 04f374be-7bd2-410d-9aa3-d95baabd5f73
---

# oxDNA Electric-Field Forces — PLAN ONLY (2026-06-18)

## ⚡ Field direction: rotation RINGS + Az/El inputs (replaces tip-drag + xyz boxes) — 2026-07-16 (out-of-session work)

- **`scene/efield_gizmo.js` rewritten.** Direction is set by dragging three great-circle rotation rings
  — "Match the cluster rotation tool exactly: TransformControls in rotate-only, world-space mode,
  attached to a dummy at the field origin." The draggable tip `_handle` + the `rayPlaneVector` drag path
  are DELETED. **Dragging no longer changes magnitude.** New API: `setDirection`, `setArrowLength`,
  `setControlsVisible`, `setOffset`.
  - **BREAKING: `getVector()` now returns a UNIT direction, not dir×length** (`setVector` splits the
    magnitude into `_arrowLength`).
  - Far-zoom cap via an override of `_helper.updateMatrixWorld`: TransformControls keeps rings a
    constant SCREEN size, which at large camera distance makes them enormous in world units — its
    screen-size setting is reduced only once a ring would exceed 25 nm diameter (geometry has unit
    radius, scaled by `factor*size/4`, so diameter = `factor*size/2`). Arrow capped at
    `_MAX_ARROW_LENGTH_NM = 25`.
- **`ui/forces_card.js`: Az/El degrees (5° steps)** replace the x/y/z boxes. The DOM is REUSED, not
  replaced — the legacy three Cartesian boxes become a spherical editor and `dirZ` is hidden
  (`display:none`, pinned `'0'`) but still in the DOM. Elevation clamps to ±90°; `_dirFromAngles` snaps
  |v|<1e-12 to 0 so payloads stay exact (`[0,0,1]`).
- **Collapsible "Arrow offset (nm)" is COSMETIC and must never reach the payload** — pinned by
  `expect(api.getFieldSpec()).not.toHaveProperty('offset')`. Plus a "Show rotation controls" checkbox
  (default on) that hides the rings while keeping the arrow.
- Magnitude/direction split is now strict: "Ring drag changes direction only. Magnitude remains
  exclusively controlled by the force input" (the `pnForArrowLen` import is gone; `setOnChange` no
  longer writes `_pN`).

Sibling of [[project_oxdna_relaxation]]. Goal: subject a relaxed DNA-origami model to a
(quasi-static) electric field in oxDNA, holding part of the structure with anchors so the
rest deflects, then visualize the deflection. Three-Layer Law holds throughout: field results
are **Physical-layer display only**, never written back to topology.

## 1. Physics & the load-bearing gotchas

- **oxDNA has NO native E-field force.** Force types: string, mutual_trap, trap, twist,
  repulsion_plane(+moving), attraction_plane, sphere/yukawa_sphere, com, LJ_wall, sawtooth,
  hard_wall, repulsive_sphere_moving, repulsive_kepler_poinsot. The one we use is **`string`**
  = a constant (or linearly-ramping) force `F = F0·dir` (+`rate`·t) on selected `particle`s.
- **Uniform field ⇒ equal constant force on every nucleotide.** DNA backbone carries ~1 charge
  per phosphate (≈1 per nucleotide bead in oxDNA's 1-bead-per-nt model). A uniform E pushes every
  bead with the same `F0` along the same `dir`. So an "E-field" = N identical `string` blocks
  (or one block with `particle = all`, same `dir`).
- **GOTCHA 1 — COM drift (the big one).** Equal force on all beads = net force on the
  center of mass ⇒ a free structure just streams across the periodic box. **Anchors are
  physically required, not a convenience.** Pin part of the structure; the anchored beads
  absorb the net force and the rest deflects against them (the Kopperger 2018 tethered-arm
  regime — *A self-assembled nanoscale robotic arm controlled by electric fields*, Science 359:296).
  **POLICY — WARN-ONLY, ALL ENGINES, STANDING (ratified 2026-07-11; supersedes any "requires an
  anchor / →400" language anywhere below or in the ledgers).** A missing anchor NEVER blocks a run
  on ANY engine (mrDNA / oxDNA / NAMD / LAMMPS), in ANY layer (REST, runner, live session,
  chain-stage, AND every UI launch button). An unanchored field runs; the user gets a non-blocking
  COM-drift *warning* only. The shared predicate is `field_anchor.field_needs_strand_anchor`
  (advisory — decides whether to SHOW the warning, it does NOT gate a 400). Currently ACTIVE in
  code: verified no backend path 400s/raises on missing-anchor, and the last UI hold (the mrDNA
  panel launch) was changed to warn-and-proceed on 2026-07-11. Any future field/anchor work MUST
  stay warn-only. See "Anchor requirement relaxed to a warning" below.
- **GOTCHA 2 — quasi-static only.** oxDNA models no explicit ions/screening and no
  hydrodynamics, and its timestep can't reach kHz AC fields. This captures the **mechanical
  deflection of a tethered structure under a steady field**, NOT free-solution electrophoretic
  mobility or gel migration. Document this prominently; don't let it be read as a mobility predictor.
- **GOTCHA 3 — effective charge is contested.** Manning counterion condensation drops the
  effective backbone charge to ~0.25 e/phosphate, and it's salt-dependent. So a V/m→force
  conversion has a soft fudge factor. → We make **force-per-nucleotide the canonical stored
  value** (honest about what oxDNA applies); a V/m helper fills it in via an *editable*
  effective-charge constant.
- **Sign convention.** Force on the (negative) backbone is antiparallel to E. With force
  canonical, the user effectively sets the *force arrow* (where DNA is pushed); the V/m helper
  points force opposite to the entered field.
- **Unit conversion:** 1 oxDNA force unit ≈ **48.63 pN**. `F0_oxdna = F_pN / 48.63`. V/m helper:
  `F_pN = q_eff · e · E(V/m) · 1e12` with `q_eff≈0.25` (editable), `e=1.602e-19 C`.
- **Stage interaction.** Existing relaxation uses mutual traps (pairing) in stages 1–2, dropped
  for equil/production. The field is a **new production-like stage**: `external_forces=True`,
  but the forces file holds **field string-forces + anchor traps**, NOT the pairing mutual_traps.
  → forces-file generation must become *composable* (sources: pairing | anchors | field).
- **Optional:** a `repulsion_plane` at the anchor surface models the substrate the origami is
  tethered to (stops it passing through). Defer to a later phase.

## 2. Anchors (decision: clusters / domains / overhangs; overhangs recommended)

- Anchor = a set of nucleotides pinned to their **starting positions** via `type=trap`,
  `pos0 = current pos`, high `stiff`, `rate=0`. (Distinct from mutual_trap; new writer.)
- Selectable scopes only: **cluster**, **domain**, **overhang**. Overhang is the recommended/
  default path — pin the overhang **free-tip** nucleotides (see [[feedback_overhang_definition]]),
  reproducing surface-tethered origami.
- Need an entity→particle-index resolver: reuse the `_strand_nucleotide_order` ordering that
  already drives `.top`/`.dat`, building the reverse map `(helix,bp,dir,copy)→particle idx`.
- NADOC-side an anchor is a display-layer annotation (like `Cluster.fixed`); it never edits
  topology. Store the chosen anchor selection on the job request, not on the Design.

## 3. Backend changes (headless-first, per FEATURE_DEVELOPMENT)

- `backend/physics/oxdna_interface.py`
  - New `write_string_forces(order, particles, F0, dir, rate=0)` and
    `write_anchor_traps(order, positions, particles, stiff)`.
  - Refactor forces-file writing to **compose** sources into one `forces.txt`
    (pairing / anchors / field) — keep `write_mutual_traps` as the pairing source.
  - Add `OXDNA_FORCE_PN = 48.63` + `pN_to_oxdna()` helper.
- `backend/core/oxdna_protocol.py`
  - Extend `OxdnaStageSpec` with `efield: {dir:[x,y,z], F0_oxdna, rate} | None` and
    `anchors: [particle_idx] | None`.
  - `build_field_stage(...)`: production-like MD, standard FENE, `external_forces=True`,
    field+anchors (no pairing traps).
  - `render_stage_input`: emit the field/anchor blocks when present.
- `backend/core/oxdna_runner.py` — `prepare_oxdna_job` writes the field forces file; `run_job`
  renders the field stage with it. Reuse resume/health-gate machinery unchanged.
- `backend/api/routes_oxdna.py` — new `POST /oxdna/jobs/{id}/field` (append a field stage),
  body = `{field_pN, dir[3], anchors:{scope, ids[]}, ramp?}`; resolve anchors→particles
  server-side. Plus `GET /oxdna/jobs/{id}/deflection` (see §5).
- `backend/api/headless_oxdna_build.py` — `run_field(design, workspace, field_pN, dir, anchors)`
  one-call wrapper, mirroring `run_relaxation`.

## 4. Validation oracle (anti-shovel — assert a property, not HTTP 200)

- `backend/core/oxdna_health.py`: `measure_field_response(positions, reference, field_dir, anchor_keys)`
  → returns `{anchored_max_drift_nm, free_mean_displacement_nm, free_projection_along_field_nm,
  aligned: bool}`. **Oracle asserts:** anchored beads stayed within trap tolerance of start AND
  free beads displaced *along the field direction* (positive projection) beyond a threshold.
- Also a per-nucleotide **displacement map** vs field-off reference (mirror the RMSF map
  structure) → feeds the deflection-map viz.
- Pin the **unit conversion** (`pN_to_oxdna`, V/m helper) and **forces-file generation**
  (correct # blocks, dir normalized, anchors at start pos) with unit tests; the mock oxDNA
  binary in `tests/test_oxdna_relaxation.py` can't deflect, so test the oracle on a synthetic
  displaced frame.

## 5. Frontend UX (decisions: extend Dynamics panel; viz = deflection-map + field arrows)

- **Home:** new "E-field" sub-section in `frontend/src/ui/oxdna_jobs_panel.js`.
  - Field magnitude box in **pN/nt (canonical)** + collapsible "from V/m" helper (E field +
    editable q_eff → fills pN). Direction = numeric vector OR set by the scene gizmo.
  - Anchor picker: scope dropdown (Overhang ⭐ / Cluster / Domain) + list/selection → chips of
    anchored entities. **Disable "Run field" until ≥1 anchor** (GOTCHA 1).
  - "Run field" appends the field stage to the current job (or creates one).
- **Field gizmo** — new `frontend/src/scene/efield_gizmo.js`: a single draggable 3D arrow
  showing field direction + magnitude (length∝pN); drag to set `dir`, two-way bound to the panel
  vector box. Display-only scene object, named group for testing.
- **Anchor glyphs:** render anchored nucleotides/overhang tips with a distinct lock/pin glyph
  + color, reusing the selection→highlight path.
- **Deflection map** — extend `frontend/src/ui/oxdna_display.js` with `deflectionColorMap(resp)`
  (mirror `rmsfColorMap`): color each nt by displacement magnitude from the field-off reference
  (viridis), via `applyScalarColors`, while `applyFemPositions` shows the deflected structure.
  Toggle in the panel alongside the existing Relaxed / Flexibility toggles.
- `frontend/src/api/client.js`: `appendOxdnaField(id, body)`, `getOxdnaDeflection(id)`.
- NOT building (per answers): trajectory-scrub-of-bend, per-bead force arrows (only the single
  field gizmo arrow). Could add later.

## 6. Phasing

NOTE (2026-06-18): building **frontend-first** at the user's request — the field-setup UI +
gizmo + automatable tests land before the backend force model. Run-wiring (the POST that
consumes `getFieldSpec()`) waits for the backend stage (was Phase 1).

- **Phase F1 (IN PROGRESS, frontend, no backend):** field-setup UI + direction/magnitude gizmo +
  anchor picker, all display-layer. Modules:
  - `scene/efield_math.js` — PURE: `pnToOxdna`/`oxdnaToPn` (`OXDNA_FORCE_PN=48.63`),
    `fieldVpmToPn`/`pnToFieldVpm` (`DEFAULT_Q_EFF=0.25`, editable), vector helpers,
    `rayPlaneVector` (drag math), `arrowLenForPn`/`pnForArrowLen` (display length scale),
    `resolveSelectionAnchors`/`anchorKey`/`addAnchors`/`removeAnchor` (overhang/domain/cluster),
    `buildFieldSpec`/`fieldSpecReady`. Fully vitest-pinned — the automatable core.
  - `scene/efield_gizmo.js` — factory `initEfieldGizmo(scene,camera,canvas,controls)`: ArrowHelper
    + draggable tip handle in named group `efield-gizmo`; `setVector`/`getVector`/`setOnChange`
    drive it programmatically (automation needs no mouse). Drag = raycast handle → `rayPlaneVector`
    on a camera-facing plane → `setVector`. Disables OrbitControls during drag (overhang_gizmo pattern).
  - `ui/efield_setup.js` — factory `initEfieldSetup({store,gizmo,getSelection})`: the "Electric field"
    collapsible sub-section INSIDE `#oxdna-jobs-body` (`efield-*` ids). pN canonical + V/m helper
    (editable q_eff) + dir inputs ⇄ gizmo + anchor chips (Add selected / remove) + ≥1-anchor ready
    gate. Exposes `getFieldSpec()` (→ `buildFieldSpec`) for the run wiring. Attaches/detaches the
    gizmo on section open/close + on `nadoc:left-tab-change` away from dynamics.
  - main.js wiring: 2 imports + `initEfieldGizmo` + `initEfieldSetup` near the oxdna panel init
    (~L1774); `if (import.meta.env.DEV) window.__nadocEfield = {setup,gizmo}` for e2e.
  - Gate: `just test-frontend` green (math + gizmo + setup specs); drag gesture → MV-EFIELD row.
- **Phase 1 (backend) — DONE 2026-06-18.** Implemented:
  - `oxdna_interface.py`: `OXDNA_FORCE_PN=48.63` + `pn_to_oxdna_force`; `_strand_nucleotide_provenance`
    (enriched mirror of `_strand_nucleotide_order` — same traversal, tagged with strand/domain/overhang
    so anchor resolution doesn't re-derive topology); `resolve_anchor_particles(design, anchors)`
    (overhang→`domain.overhang_id`, cluster→`cluster_transforms[].helix_ids`, domain→strand+index;
    unknown→drop); `read_cm_positions_oxdna` (raw CM in oxDNA units for trap pos0);
    `field_string_block` (`particle=-1` uniform force), `anchor_trap_block` (static `trap`, rate=0),
    `write_field_forces(...)` (composes the field forces file from the conf the stage starts from;
    ~~raises if no anchor resolves~~ **warn-only since 2026-07-10 — an unanchored field composes
    fine (0 traps) and just warns; see the WARN-ONLY policy in §1**).
  - `oxdna_protocol.py`: `OxdnaStageSpec` += `forces_file` (per-stage external-forces filename) +
    `efield` record; `build_field_stage(...)` (kind=`field`, MD, standard FENE, external_forces, no bp gate).
  - `oxdna_runner.py`: `run_job` now uses `spec.forces_file or "forces.txt"` (relax stages keep the
    mutual-trap file; the field stage uses its own `field_forces_N.txt`).
  - `routes_oxdna.py`: `POST /oxdna/jobs/{id}/field` (AnchorRef/FieldRequest; mirrors append-production:
    unique `N_field` stage, continues from latest relaxed `last_conf`, resolves anchors + writes the
    field forces file server-side; ~~requires ≥1 anchor → 400~~ **warn-only since 2026-07-10 — no
    anchor is accepted, the UI warns of COM drift; see the WARN-ONLY policy in §1**).
  - `oxdna_health.py`: `measure_field_response(field_pos, ref_pos, field_dir, anchor_keys)` — the
    anti-shovel oracle: `passed` iff anchored beads held (≤tol) AND free beads displaced ALONG the
    field (≥min proj). Returns drift/displacement/projection metrics.
  - `headless_oxdna_build.py`: `append_field` + `run_field` (one-call relax→field→poll) — the
    automatable path (mock binary, no GPU). Auto-covered by `oxdna_coverage_report`.
  - Tests: `test_oxdna_relaxation.py` +5 (conversion, resolve domain/cluster/unknown, write_field_forces
    + no-anchor raise, build_field_stage+render, oracle pass/fail×3); `test_headless_oxdna_build.py` +3
    (run_field e2e via mock, no-anchor 400, route-identity + coverage). Full suite 2582 passed.
- **Phase 2 (frontend run wiring + full automatability) — DONE 2026-06-18.**
  - `client.js`: `appendOxdnaField(id, body)`.
  - `oxdna_jobs_panel.js`: returns `getSelectedJob` (the panel↔efield handoff).
  - `efield_setup.js`: "⚡ Run field" button — enabled only when the spec is ready AND the panel's
    selected job is `completed`; POSTs `{field_pN, dir, anchors, steps}`; `onRan` refreshes the panel.
    Deps grew: `getSelectedJob`, `onRan`. `efield-steps` + `efield-run-btn` added to index.html.
    main.js captures `oxdnaPanel` + passes the handoff (LOC 7149, +5 net wiring).
  - Tests: `efield_setup.test.js` +4 (run disabled until ready+completed-job; posts spec; no-op when
    not ready). Frontend 1356 green; smoke clean.
  - **Automatability (all ops headless):** `oxdna_health.field_response_from_confs(...)` (oracle straight
    from two confs) + `headless_oxdna_build.run_field_validation(...)` (relax→field→measure, returns
    `{job, response}`). Validation pinned with a **field-deflecting mock oxDNA** (`_FIELD_MOCK_OXDNA`):
    parses the forces file, shifts non-trapped particles ∝F0 along the field, holds trapped (anchor)
    particles → the full pipeline + oracle run on CPU with no GPU. Tests: oracle PASSES (anchor held,
    rest deflected along field) + deflection scales with field magnitude (monotonic proxy for
    "aligns faster at higher field"). Backend 2584 green.
- **Eventual validation target (toward the user's goal):** a single duplex with a ssDNA overhang end
  pinned as the anchor; the overhang should rotate to ALIGN with the field within a characteristic time
  that scales with field magnitude. The anchor kind (`overhang`) + oracle are already exercised
  (a 6hb staple domain tagged `overhang_id` stands in for the duplex topology — building the real
  single-duplex+overhang fixture is **topology work → build via the headless design API / ask first**,
  not hand-rolled). The time-vs-magnitude law needs a real GPU run; the monotonic-deflection direction
  is the automatable proxy pinned now.
- **Phase 2b (UX: magnitude warning + field branches) — DONE 2026-06-18.**
  - **Magnitude colour grading:** `efield_math.fieldColorHex(pN)` + `fieldZone(pN)` (thresholds
    `EFIELD_PN_LOW=0.5`, `EFIELD_PN_GOOD=10`, `EFIELD_PN_DISRUPT=40` pN/nt — heuristic: bp rupture
    ~10–20 pN, B→S overstretch ~65 pN). Arrow + tip recolour blue (too small) → green (good) → red
    (disrupts DNA) via new `efield_gizmo.setColor`; the panel readout shows "⚠ field strong enough to
    disrupt the DNA" in the `disrupt` zone.
  - **Field runs are CHILD jobs (branches), not appended stages.** `POST …/field` now spawns a child
    job seeded from the parent's relaxed `last_conf` (`OxdnaJob.parent_job_id` + `efield` metadata;
    copies topology/design.json, conf.dat = relaxed structure, single `1_field` stage). One relaxed
    job → many independent field runs. A field child cannot itself be branched (400). `run_field` /
    `run_field_validation` now target/return the child; reference = child's `conf.dat`.
  - **Panel nesting:** `groupJobsByParent(jobs)` + `fieldChildTitle(job)` (pure); children render as
    indented numbered sub-rows. Run-field button gates on a completed PARENT (not a child).
    **UPDATE 2026-06-20:** the row label is now `runRowLabel(job,index)` = "Run N" + element
    indicators `[A]`nchors / `[H]`ard surface / `[E]`-field (order A,H,E) via pure `runElements`/
    `runIndicatorTags`; the **lightning bolt was removed** (the `[E]` tag denotes the field instead).
    Hover title = `runChildTitle(job)` (field runs → `fieldChildTitle`, else "Production run · …").
    Starting a consolidated run now **auto-selects the new child** (`_selectJob(r.job_id)` after the
    POST), and the E-field arrow follows the selected job (cleared on deselect via `_clearRunCards`),
    so it shows only when a field has been applied to the current job.
  - Tests: `efield_math.test.js` (+2 colour/zone), `efield_setup.test.js` (+2 child-gate + colour/warn),
    `oxdna_jobs_panel.test.js` (+groupJobsByParent/fieldChildTitle), `test_headless_oxdna_build.py`
    (child spawn + multiple children + child-cannot-branch). All suites green.
- **Cascade delete (2026-06-18).** `DELETE /oxdna/jobs/{id}` on a relaxed parent now also deletes
  ALL its field children (else orphaned, design-detached jobs); refuses (400) if the parent or any
  child is still running. Frontend: a `showConfirm` warning before any delete — `deleteConfirmMessage`
  (pure) spells out the cascade ("…has N field runs… deleting removes all N", confirm "Delete all (N+1)").
  Display teardown uses the route's returned `deleted` id list. Tests: backend cascade + running-child
  block; frontend `deleteConfirmMessage` pure test.
- **Anchor physics check on `1hb_efield_test.nadoc` (2026-06-18).** Overhang anchor (10 ssDNA nt)
  resolves to particles [42..51]; a real short oxDNA run shows anchored beads stay put (drift
  ~0.26–0.48 nm) while free beads move 8–80 nm — i.e. **the traps DO hold the selected nucleotides**.
  CAVEAT: short-relaxation runs gave bp_retained≈0 (structure under-formed in 3k–400k MD steps vs the
  1e6 protocol), so whether a strong field melts a *properly relaxed* duplex needs the full GPU relax.
  Anchoring only the floppy ssDNA overhang holds the overhang but lets the duplex swing far; pinning a
  duplex domain/cluster (or a few bp near the tether) holds the body more rigidly. Realistic lab fields
  are ~0.01–0.1 pN/nt — note the per-nt colour thresholds don't account for CUMULATIVE load funneled
  through an anchor (N_downstream × F0), which can strain a large structure even when green per-nt.
- **Display-toggle + metrics integration for field children (2026-06-18).** A field run is a normal
  job so most paths already worked; audited + fixed the production-only assumptions:
  - **OxDNA display** ✓ (latest `last_conf` = field result) and **View trajectory** ✓ (the `/trajectory`
    route already includes any stage that wrote a trajectory, incl. `field`) — both worked already.
  - **Flexibility map (RMSF)** was production-only → now pools `kind in ("production","field")` in the
    `/rmsf` (and `/rmsd`) routes, and the panel gates the flex toggle on a new pure `samplingState(job)`
    (production OR field) instead of `productionState`. So selecting a completed field child + toggling
    Flexibility map shows its field-deflected mean + per-base RMSF.
  - **ETA** ✓ (`job_progress` is kind-agnostic — single-stage field job gets stage_fraction + eta) and
    **health metrics** ✓ (`run_job` appends a health sample for the `field` stage; `min_bp_retained=0`
    gate passes). The progress step-label was production-only → now shows "Field: X / Y steps" for a
    running field stage too.
  - Tests: backend `test_rmsf_route_works_for_a_field_run`; frontend `samplingState` pure test (+ updated
    two reason-string assertions). All suites green.
- **Run-button reactivity to job selection (2026-06-18).** The backend always allowed branching a
  field off a completed parent; the gap was UI reactivity — `efield_setup`'s Run button only
  re-evaluated on its own interactions (or button hover), so clicking a parent in the list didn't
  light it up. Fix: `oxdna_jobs_panel` dispatches `nadoc:oxdna-job-selected` (from `_renderDetail` +
  the selection-clear paths); `efield_setup` listens → `_renderReady`, so selecting a completed
  relaxed job (or a watched relaxation completing) enables "Run field" immediately, no hover. `runField`
  also defensively refuses a field child (`job.parent_job_id`). Tests: consumer reactivity
  (`efield_setup.test.js`) + producer dispatch (`oxdna_jobs_panel.test.js`).
- **Anchors effectively immobile (2026-06-18).** Anchor traps were soft (`stiff=5`) → ~0.35 nm
  thermal jitter (⟨dx²⟩≈kT/stiff). Raised `DEFAULT_ANCHOR_STIFF` 5 → **1000** (single source in
  `oxdna_interface`; `FieldRequest.anchor_stiff` + headless `append_field` default reference it). At
  1000 the anchored beads pin to **~0.027 nm RMS** (≈10× below normal bead motion = effectively
  immobile) and the field stage stays MD-stable (`dt·√stiff≈0.16 ≪ 2`; run completes). Empirically
  swept on `1hb_efield_test` (0.35→0.11→0.027 nm at stiff 5/100/1000, all completed). No UI control —
  immobile by default; `anchor_stiff` still overridable via the API/headless. Test asserts the default
  is the immobile value in the forces file.
- **"Anchor lets the strand move" diagnosis (2026-06-18).** User reported a field run drifting 10s of
  nm despite an overhang anchor. Investigation (real binary, on `1hb_efield_test`):
  - Anchors ARE correctly applied at creation (verified the live job's `field_forces.txt`: 10 traps,
    `stiff=1000`) and ARE immobile — anchored beads drift **0.022–0.026 nm** in the raw sim frame.
  - What moves 10s of nm is the **un-anchored** part. Demo: overhang anchor (10 nt) → anchored 0.022 nm,
    free duplex 15.7 nm; **cluster anchor (all 94 nt) → everything 0.026 nm, nothing free**. A
    single-stranded overhang is a flexible HINGE, so anchoring it can't constrain the rigid duplex's
    swing. Fix is anchor-SELECTION: anchor the duplex/cluster to hold the whole structure.
  - The ~2 nm extra wobble the display adds is the whole-structure Kabsch alignment (it doesn't treat the
    anchor as the fixed frame) — not the dominant effect here.
  - GOTCHA for future: oxDNA's `ConstantRateForce` (type=string) **rejects dash-range particle specs**
    ("couldn't get from particle 0 to particle 41"), so excluding anchors from the field via
    `particle = 0-41,...` is NOT viable — keep `particle = -1` (field on all); the stiff trap holds
    anchors regardless. (Attempted + reverted.)
- **Field-run display: anchor = positional-only reference (2026-06-18).** Clicking "OxDNA display"
  on a field run flung the structure to distant positions because the display Kabsch-aligned the WHOLE
  structure (rotation+translation, all beads) — the swung duplex dominated the fit, rotating away the
  very reorientation being studied and throwing the anchor. Fix: `unwrap_align_to_reference` gained
  `align_keys` (alignment subset) + `rotate` flag. For a field run the display now PBC-unwraps (keeps
  the structure whole) then does a **translation-only** fit on the ANCHORED beads — anchor → its design
  position, NO rotation — so the field-induced swing stays visible. Anchor keys are stored on
  `child.efield["anchor_keys"]` at creation (`write_field_forces` returns them); `get_oxdna_display`
  passes `align_keys=…, rotate=False` when present. Verified on a fresh run: anchored offset ~0.8 nm
  (CM pinned; residual is the anchor's free orientation = "positional not rotational"), free swing 8.8 nm
  preserved, max coord 16 nm (not flung). CAVEAT: only NEW field jobs store `anchor_keys` (old jobs fall
  back to whole-structure Kabsch). Tests: `test_unwrap_anchor_positional_no_rotation` +
  `test_write_field_forces_returns_anchor_keys`. (Flex-map/trajectory still use whole-structure Kabsch —
  a follow-up could thread `align_keys` through `production_rmsf`/`composite_trajectory` too.)
  - **FOLLOW-UP root cause (structure STILL showed tens of nm off-origin):** the field child's
    `conf.dat` IS the parent's relaxed `last_conf`, which the relaxation MD diffuses far off-origin (no
    positional anchor during relaxation). Measured on `1hb`: design geom 6.7 nm from origin, relaxed
    seed 14.2 nm, field last_conf 22.5 nm — so anchoring onto the seed displayed everything ~14 nm out.
    FIX: align the field display to a regenerated origin-frame DESIGN geometry (`_design_ref_conf` →
    cached `design_ref.dat` via `_geometry_for_design`+`write_configuration`), NOT the job's `conf.dat`.
    After fix: displayed anchor 0.13 nm from its design position, structure COM 8.8 nm from origin (was
    22.5). Test `test_field_display_aligns_to_design_not_drifted_seed` (a +30-ox-drifted seed still
    displays at the design position). Works for OLD field jobs too (ref regenerated from the design
    snapshot) — though old jobs still lack `anchor_keys` so they fall back to whole-structure Kabsch;
    re-run to get the positional display.
- **Live mode composes any element set (2026-06-23, follow-up).** Live now mirrors the consolidated
  run: it composes E-field / hard surface / anchors independently (only a field requires ≥1 anchor;
  anchors-only / surface-only / nothing=free dynamics all allowed). Backend: `LiveStartRequest` carries
  `field`/`surface`/`anchors` (like `RunRequest`); `routes_oxdna_live._prepare_live_rundir` uses
  `write_run_forces` + `build_run_stage`; `_OxpyStepper` tolerates a fieldless run (`self._field=None` →
  `set_field` no-ops). Frontend: the Live controller takes `getRunElements` (the SAME closure the panel's
  Full Sim run uses) and only blocks field-without-anchor. The **"Start Production" button is renamed
  "Full Sim"**. Verified on real oxpy (field+anchor / anchors-only / free dynamics all step + stop +
  clean up). Tests: `test_oxdna_live_session.py` 14 + `oxdna_live_controller.test.js` updated.
- **Display-toggle protection during Live (2026-06-23, follow-up).** While a live session runs, the
  panel's **OxDNA display / Flexibility map / View trajectory** toggles are DISABLED (they share the one
  bead overlay) so a click can't fight Live. `oxdna_jobs_panel._updateButtons` computes `liveOn =
  oxdnaLive.isOn()` and locks all three (display had no gate before); the controller dispatches
  `nadoc:oxdna-live-start` AFTER `_on=true` (so `isOn()` is true when the panel locks) and
  `nadoc:oxdna-live-stop` on teardown (panel re-runs `_updateButtons` → unlock). Pinned in
  `oxdna_jobs_panel.test.js` (toggles flip disabled on start / enabled on stop) + controller event tests.
- **Phase 3 (not built):** Deflection-map viz (`/deflection` route via `measure_field_response`'s
  displacement + a frontend `deflectionColorMap`). → MV-EFIELD.

## Field+anchor setup viz (2026-06-19, SHIPPED)
While configuring a field run, the field direction + the pinned elements are now made obvious:
- **Thick 3D arrow**: `scene/efield_gizmo.js` arrow is a solid **cylinder shaft + cone head**
  mesh (`MeshStandardMaterial`, emissive) instead of `THREE.ArrowHelper`'s 1-px line. Same API
  (setVector/getVector/setColor/handle at origin+dir·len); group `efield-gizmo`, arrow subgroup
  `efield-gizmo-arrow`. Shows whenever the E-field card is open **OR a selected oxDNA job
  applied/is applying a field** (2026-06-19): `efield_setup` decouples arrow visibility from the
  card via `_jobFieldActive` (set by `applyConfig`) + `_syncGizmo()` (arrow on if `_open ||
  _jobFieldActive`); `applyRunConfig` no longer force-opens the card; leaving the Dynamics tab still
  drops the arrow. Tests in `efield_setup.test.js` (collapsed-card arrow / null hides it / tab-change drops it).
- **Purple anchor glow**: `scene/anchor_glow.js` (`initAnchorGlow({designRenderer, store})` +
  pure `resolveAnchorEntries`) maps anchor descriptors → backbone entries (overhang→`nuc.overhang_id`,
  domain→`strand_id`+`domain_index`, cluster→`clusterMemberFilter`) → `designRenderer.setAnchorGlow`
  (new purple `createGlowLayer(scene, 0xb14aff, 3.6, 'anchorGlow')`, cleared on rebuild, refreshed in
  `refreshAllGlow`). **UPDATED 2026-07-16 — the field gate is GONE.** It used to show only when
  **field enabled (`efieldSetup.isEnabled()`) AND ≥1 anchor**, which meant an added anchor stayed dark
  until something turned a field on (clicking a job row restored the job's field first — the reported
  bug). An anchor is pinned regardless of any field, so main.js `_refreshAnchorGlow` now shows the
  ACTIVE ENGINE's anchors, full stop. Every engine's card fires `nadoc:anchors-change {engine,
  anchors}` (one `_emit()` per mutation, never at construction → no TDZ on the main.js consts); main.js
  caches per engine and `engineSelector.onSelect` re-refreshes. `efield_setup.onChange` no longer
  touches the glow. Cleared on leaving the Dynamics tab, restored on return. See
  [[project_simulate_panel_overhaul]] for the full entry. Tests: `anchor_glow.test.js` (9) + gizmo tests still
  green. Live-verified the arrow is a solid cyl+cone mesh + the anchorGlow layer is wired (throwaway
  e2e introspection). Live purple-on-actual-beads = human-eye → MV-ANCHGLOW.

## Live (ephemeral, re-aimable) field mode (2026-06-23, SHIPPED)
A **"Live" toggle** (`#oxdna-jobs-live-btn`, between ▶ Relax and Start Production) runs an
**ephemeral in-process oxpy field session** that stores NOTHING — no `OxdnaJob`, no jobs-list
entry, no persisted frames, just a temp rundir removed on stop. It reuses the batch field
physics wholesale (`backend.physics.oxdna_live.LiveOxdnaSession` + `_OxpyStepper`, the AF-21
engine driven by `headless_oxdna_build._prepare_field_rundir`); the live re-aim mutates
`force.F0`/`force.dir` between bursts (needs the [[oxpy-binding-patch]]).
- **Backend.** `backend/core/oxdna_live_runner.py` — an in-memory `LiveSession` registry + a
  background-thread worker (`with session: set_field → loop{apply pending field; run(burst);
  capture frame}`), single-active-session policy (`stop_all()` before each start), thread-safe
  latest-frame + pending-field. `backend/api/routes_oxdna_live.py` (mounted in `main.py`):
  `GET /oxdna/live/available` (probes `oxpy.forces.BaseForce` has F0/dir), `POST /oxdna/live/start`
  (seeds from a completed relaxed job's `_latest_relaxed_conf` via `_prepare_field_rundir`, ≥1
  anchor required), `POST …/{id}/field` (live re-aim), `GET …/{id}/frame` (current config as an
  applyFemPositions payload — `read_configuration_unwrapped` against an origin-frame design_ref,
  anchor-keys positional/no-rotation, true backbone site), `POST …/{id}/stop` (teardown + rmtree).
- **Frontend.** `ui/oxdna_live_controller.js` `initOxdnaLive({oxdnaDisplay, getSelectedJob,
  getFieldSpec, getAnchors})` owns the toggle: on start it POSTs, polls `…/frame` every 500 ms →
  `oxdnaDisplay.displayLiveFrame(positions)` (a NEW `'live'` mode in `oxdna_display.js`, CG-only —
  no heavy rep, no jobId), and pushes field re-aims (throttled 150 ms) when the efield gizmo/inputs
  change (main.js wires `efieldSetup.onChange → oxdnaLive.onElementsChanged()`; the anchor halo no
  longer keys off the field, so it is NOT refreshed from here — 2026-07-16).
  Mutual exclusion: starting Live dispatches `nadoc:oxdna-live-start` → panel `_allDisplaysOff()`;
  the panel calls `oxdnaLive.stop()` from the Relax/Production buttons + the display/flex/traj
  toggles. Leaving the Dynamics tab / switching design / selecting another job stops Live. main.js:
  +1 import + factory init + the panel `oxdnaLive` dep + the onChange wrap (wiring only).
- **Verified.** Backend `test_oxdna_live_session.py` (12, GPU-free fakes; full suite 3066). Frontend
  `oxdna_live_controller.test.js` + `displayLiveFrame` in `oxdna_display.test.js` (suite 1654);
  vite build + smoke clean. **REAL oxpy route verified end-to-end on this box** (RTX 2080 + patched
  ~/oxDNA): start → 504-position frame → live re-aim advances bursts → stop → rundir cleaned. The
  in-browser button→gizmo-drag→structure-follows + Relax/Production-stops-Live gesture is human-eye
  only → **MV-OXLIVEFIELD** (distinct from MV-OXLIVE, which is the display-follow-a-running-job item).

## Live latency speedups — CUDA + in-memory readout (2026-06-23)
Profiled the live loop (`set_field → run(burst) → capture_frame → poll`) for "immediate visual
feedback" while playing with field/surface/anchors. Three physics-preserving wins shipped:
- **#1 Live steps on CUDA (was hardcoded CPU).** `_prepare_live_rundir` built the stage
  `backend="CPU"`; flipped to `"CUDA"`. Benchmarked oxpy steps/sec on THIS box (RTX 2080 SUPER,
  WSL2) over real jobs — CPU vs CUDA: N=94 5472/6531 (1.2×), **N=1076 241/3677 (15×)**,
  **N=6012 43/4114 (96×)**, **N=14774 15/2391 (163×)**. CPU is only competitive below ~200 nt; a
  6k-nt design is ~12 s/500-step-burst on CPU vs ~0.12 s on CUDA. CUDA has a per-burst floor
  ~75–210 ms (launch+sync) so tiny systems stay snappy too. **Live field steering VERIFIED on CUDA**
  (mutating `force.F0`/`force.dir` between bursts propagates to the GPU: free beads swing 21.8 nm on
  a +x→−x re-aim, anchors hold 0.014 nm — same as CPU). Decision (user): **always CUDA**, matching
  the relaxation jobs. CUDA works fine under WSL — the "may be worse on WSL" worry did NOT
  materialize, so NO automation-ledger handoff was filed.
- **#2 In-memory readout (no per-frame file round-trip).** The frame builder did
  `print_configuration()` (write `last_conf.dat`) + `read_configuration_full` (parse) + the parse was
  THEN re-done inside `read_configuration_unwrapped` (which also re-parsed the constant design_ref) —
  3 full-config parses + 1 disk write per frame, one fully redundant. New
  `oxdna_interface.configuration_full_from_particles(particles, design)` builds the identical
  `(h,bp,dir)→{pos_nm,a1,a3}` map straight from oxpy `config_info().particles()`: **a1 = orientation
  col 0, a3 = col 2** (verified equal to the `.dat` a1/a3 to 1e-14), `pos_nm = p.pos × OXDNA_LENGTH_UNIT`.
  `_OxpyStepper.configuration_map()` + `.box_nm()` expose it; the redundant `.configuration()` call in
  `_make_frame_builder` is gone. End-to-end the in-memory display frame == the old file frame to
  **7e-13 nm** (real 1076-nt crossover design, 300 live steps) — the BFS-unwrap+box-shift+Kabsch
  absorbs the in-memory-pos box-image offset.
- **#3 Cache the constant per-frame work.** `unwrap_align_to_reference` grew an optional `adj=` param
  (the bond-adjacency, factored into `_build_unwrap_adjacency`); `_make_frame_builder` parses the
  origin-frame `design_ref` ONCE and builds the graph ONCE, reusing both every frame. Per-frame cost
  now: in-memory particle read + BFS + Kabsch (no file I/O, no graph rebuild, no ref re-parse).
- **NOT yet done (further levers, deferred):** push frames over WebSocket (mirror `ws/md-jobs`) instead
  of the 500 ms REST poll; adaptive/smaller burst size now that per-frame overhead dropped; binary/typed
  frame transport. The CUDA-burst floor + poll interval are the remaining latency, not the readout.
- **Tests.** GPU-free: `test_configuration_full_from_particles_matches_file_readout`,
  `test_unwrap_precomputed_adj_matches_builtin` (test_oxdna_relaxation). Real-oxpy gated (CPU, convention
  lock): `test_configuration_map_matches_file_readout_real_oxpy` (test_oxdna_live_session). Existing live
  + headless oxdna suites green; ruff clean. **Live in-browser snappiness on a big design is human-eye →
  owes MV-OXLIVE-CUDA** (steering responsiveness + structure-follows at CUDA speed, not yet app-verified).

## Live reconfigure — toggle floor / E-field / anchors mid-session (2026-06-23)
Before this, a live session composed its element set ONCE at start and only the field's
magnitude/direction could be re-aimed in place; toggling the floor or E-field ON after starting did
nothing (the floor card's `onChange` wasn't even wired to the live controller, and the field card's
re-aim path no-ops when the session started fieldless — the engine has no `string` force to mutate).
Now any composition change recomposes the running engine **seamlessly from the current pose** (user
chose seamless over restart-from-relaxed).
- **Backend.** `LiveSession.reconfigure(rebuild_fn, field_oxdna, field_dir)` queues a recomposition;
  the worker loop (`_apply_pending_reconfig`, now using **manual `__enter__`/`__exit__`** instead of
  `with self._session:` so it can swap engines mid-loop) snapshots the current pose
  (`_OxpyStepper.snapshot_seed()` → `reconfig_seed.dat`), tears down the old engine, calls the
  route-supplied `rebuild_fn()` → `(new_session, new_frame_builder)` seeded from that pose, enters the
  new engine, sets the field, and keeps stepping. `POST /oxdna/live/{id}/reconfigure`
  (`LiveReconfigureRequest`, same field/surface/anchors/anchor_stiff as start) resolves elements via the
  shared `_resolve_live_elements` + `_build_live_engine` helpers (extracted from `start_oxdna_live`, so
  start and reconfigure run identical setup), pre-validates field-needs-≥1-anchor on the request thread
  (`resolve_anchor_particles` needs only the design, not the conf), and queues the rebuild. `LiveSession`
  gained `design`/`design_ref` attrs + `rundir`/`burst_steps` properties so the route can rebuild.
- **Frontend.** `oxdna_live_controller` replaced `onFieldChanged` with **`onElementsChanged`** (kept as
  an alias) driven by a pure **`reconfigSig(el)`** = a composition signature that EXCLUDES field
  magnitude/dir (those stay the in-place re-aim) but includes field on/off, surface on/off+params, and
  anchors. Same sig → field re-aim (`updateOxdnaLiveField`); changed sig → debounced (350 ms, engine
  rebuild is heavy) `reconfigureOxdnaLive` POST, gated on field-needs-anchor. `main.js` wires the floor
  card's `onChange` (was unwired) and the anchors card's `onChange` to `onElementsChanged` too. `client.js`
  `reconfigureOxdnaLive`.
- **Verified.** Backend `test_oxdna_live_session.py` +3 (GPU-free worker engine-swap: old snapshotted+closed,
  new entered+field-set, keeps stepping; reconfigure 404 + field-needs-anchor 400). Frontend
  `oxdna_live_controller.test.js` +8 (`reconfigSig` stability/sensitivity; floor-toggle→reconfigure,
  field-enable-after-fieldless-start→reconfigure, magnitude-change→re-aim-not-reconfigure,
  field-without-anchor→warn-no-POST). Backend 3074 / frontend 1666 / smoke 23 green. **REAL oxpy
  end-to-end probe on this box:** start free-dynamics from a relaxed seed → reconfigure adds a hard floor
  → stays `running`, keeps stepping, new forces file has `repulsion_plane`, structure moved only 0.27 nm
  median between pre/post frames (SEAMLESS, no teleport). The in-browser toggle-floor/field-mid-Live
  gesture is human-eye → folded into **MV-OXLIVE-CUDA**.

## Out-of-date job guard — design edited after a relax (2026-06-23)
Editing the design after running a job then starting live/production resolved the CURRENT design's
anchor selections against the job's FROZEN snapshot topology → particle indices out of range →
internal-server-error (the rundir prep runs synchronously in the request handler). Now guarded:
- **Fingerprint.** `backend/core/oxdna_staleness.py`: `oxdna_design_fingerprint(design)` = sha256 of the
  oxDNA-build-relevant fields (`helices, strands, crossovers, deformations, extensions, overhangs,
  overhang_connections, forced_ligations, photoproduct_junctions`) — topology + sequence + geometry
  SOURCES. EXCLUDES display layers (cluster transforms/joints — Three-Layer display, never in
  `_geometry_for_design`; camera, metadata, feature log, proteins). So a cluster drag / camera move does
  NOT mark jobs stale; only a structural/sequence/geometry edit does. `OxdnaJob` gained
  `design_fingerprint` + `feature_log_position` (set at creation; children inherit the parent's). Survives
  the design.json round-trip (verified).
- **out_of_date flag.** `GET /oxdna/jobs` (+ `/{id}`) compute the current design's fingerprint once and
  tag each job `out_of_date` (= job fp ≠ current fp; old jobs derive their fp from the frozen snapshot,
  cached by job_id). Frontend shows a ⚠ on stale rows (`oxdna_jobs_panel.jobOutOfDate`); `main.js`
  refetches the list on every `currentDesign` change so the markers appear immediately.
- **Guard (the crash fix).** `routes_oxdna._assert_job_current(job)` raises **409** when the active design
  fingerprint ≠ the job's, called in `append_oxdna_production` / `_field` / `_run` + `start_oxdna_live`
  (before any rundir prep). The frontend turns the 409 into the popup; it's also the backend safety net.
- **Roll = SEEK the feature-log cursor to the job's position (FINAL, 2026-06-23).** Evolution:
  (1) first cut = `_seek_feature_log` — but the ⚠ never cleared because sequence assignment wasn't logged
  (it was `set_design_silent_reconciled`, undo-only), so seeking back dropped the sequences (64/64 → 0/64);
  (2) second cut = restore the job's exact `design.json` snapshot byte-for-byte — cleared the ⚠ but did NOT
  move the feature-log cursor (the Feature Log tab showed the snapshot's own short log, and a post-job
  overhang stayed visible). User wanted a REAL seek visible in the tab. **Final fix has two parts:**
  - **Sequence assignment is now a feature-log op.** `/design/assign-scaffold-sequence` +
    `/design/assign-staple-sequences` (`routes_assign_sequences.py`) switched from `snapshot()` +
    `set_design_silent_reconciled` → `mutate_with_feature_log(op_kind='assign-scaffold-sequence' /
    'assign-staple-sequences', ...)`. Added both kinds to `SnapshotOpKind` (models.py). Now a seek
    reproduces the sequenced state, so the seek-based roll clears the ⚠. (Full suite green — no test asserted
    the old no-log behavior.)
  - **`crud.roll_active_to_job_state(snapshot, feature_log_position, return_name)`** seeks the cursor to the
    job's `feature_log_position` via `_seek_feature_log` (FULL log kept, later entries inactive/forward, the
    model reverts — a post-job overhang disappears, exactly like sliding the Feature Log rail; the cursor is
    visible in the tab). If the seeked fingerprint == the job's it's used directly (new jobs); else (OLD
    jobs with no recorded position / pre-logging) it falls back to overlaying the job's exact snapshot
    topology onto the seeked log+cursor so it still runs. The roll endpoints pass `job.feature_log_position`.
  - Non-destructive return path unchanged: saves the pre-roll work as a **loadout** branch
    (`return_loadout_id`); "↩ Return to latest" = `selectLoadout(id, {saveCurrent:false})` (the
    `save_current=false` query stops `select_loadout` clobbering the branch). The user can ALSO seek forward
    via the Feature Log tab (the full log is preserved). The duplicate `/design/feature-log/seek` route was
    removed (pre-existing `routes_feature_log.py /design/features/seek` already exists). Per the user's
    choice: Display / View-trajectory / Flexibility stay usable on stale jobs; only Production + Live are gated.
  - **CLIENT-SYNC BUG (the "nothing rolls back / seeker doesn't move" report) — fixed.**
    `client.rollOxdnaJobDesign` / `rollMdJobDesign` used `_request(...)` directly, but **`_request` does NOT
    auto-sync the design response** (it just `return json`) — so the server seeked the design (the ⚠ cleared
    via the job-list refetch) but the CLIENT never applied it: no scene rebuild, no feature-log cursor move.
    This silently affected even the earlier snapshot-restore version. Fix: both roll calls now
    `await _syncFromDesignResponse(json)` (like `selectLoadout`) → `currentDesign` (seeked cursor) +
    `currentGeometry` (reverted topology) update → the scene rebuilds AND `feature_log_panel`'s
    `subscribeSlice('design')` moves the rail thumb. Verified on `workspace/6hb_sim_tests.nadoc` (7-entry log,
    cursor -1 → eff-pos 6): real job→edit→roll returns `feature_log_cursor 6`, full 8-entry log kept, ⚠
    cleared. Regression test `roll_design_sync.test.js` (stubs fetch, asserts the store's
    `currentDesign.feature_log_cursor` actually moves).
  - **MANUAL-seek doesn't clear the ⚠ (the inverse report) — fixed (2026-06-24).** When the user manually
    seeks the Feature Log back to a job's run position, the job's ⚠ should clear (the backend DOES clear it —
    a manual seek to the job's `feature_log_position` re-matches the fingerprint, verified on
    `6hb_sim_tests`). The gap was the in-page refetch trigger: the oxDNA panel relied on main.js's
    `store.subscribe(currentDesign)` calling `oxdnaPanel.refresh()`, but the panels' 1.5 s poll is PAUSED off
    the Dynamics tab (`nadoc:left-tab-change`), and a manual seek happens on the Feature Log tab — so the
    only signal was that store subscription, which was an indirect/fragile chain. **Fix:** the client now
    emits a single reliable `nadoc:design-changed` window event on EVERY design sync (`_signalDesignChanged()`
    replaces the 4 `nadocBroadcast.emit('design-changed')` sites in `_syncFromDesignResponse` /
    `_syncPositionsOnlyDiff` / `_syncClusterOnlyDiff` — `currentDesign` content only ever changes via the
    client, verified). BOTH job panels now self-listen (`window.addEventListener('nadoc:design-changed', _fetchJobs)`
    — the MD panel already did) and refetch regardless of tab/poll state; main.js's `store.subscribe` for this
    was removed (the client is now the single source). Regression: `roll_design_sync.test.js` asserts
    `seekFeatures` dispatches `nadoc:design-changed`.
- **Shared oxDNA+MD guard + MD parity (2026-06-23).** The fingerprint module gained
  `design_build_fingerprint` (neutral alias of `oxdna_design_fingerprint`) + `current_active_design_fingerprint()`
  (catches ALL exceptions → None; staleness is advisory and must never 500 the job list). **MD jobs now mirror
  oxDNA:** `MdJob` gained `design_fingerprint` + `feature_log_position`; `_prepare_job_bg` writes
  `design.json` + the fingerprint from the design it prepared (covers seeded + non-seeded); `routes_md`
  list/get add `out_of_date`, `append_md_production` gets `_assert_md_job_current` (409), and
  `/md/jobs/{id}/roll-design` restores the snapshot. Frontend: shared **`ui/job_staleness.js`**
  (`jobOutOfDate` + `ensureJobCurrent({job, rollFn, refetch, isStale, actionLabel})`) drives BOTH panels;
  the oxDNA panel + live controller + MD panel all delegate to it. `main.js` dispatches `nadoc:design-changed`
  on each `currentDesign` change → both panels refetch so ⚠ appears immediately. The fingerprint EXCLUDES
  display layers (cluster transforms/joints, camera) so a cluster drag doesn't false-flag.
- **Headless gotcha (regression fixed).** The guard reads the active design; the headless oxDNA wrappers
  (`headless_oxdna_build.append_field` / `append_production`) drove the routes against the DEFAULT doc, so
  in the shared-process test suite (randomized order) a prior test's leftover design tripped the guard →
  39 spurious 409s. Fix: `_scratch_job_design(job_id, workspace)` scopes the job's OWN snapshot as the
  active design for the call (mirrors how `create` is scoped) — the field/production run logically operates
  on the job's design, so the fingerprint matches and the guard passes. `test_oxdna_staleness.py` also
  drops the default doc after each test (it sets it for the TestClient routes).
- **Tests.** `test_oxdna_staleness.py`: fingerprint sensitivity/insensitivity, guard 409, list flag,
  `test_assign_sequences_are_feature_log_steps` (the new logged entries), **`test_roll_seeks_feature_log_cursor_and_keeps_full_log`**
  (the reported fix — roll seeks the cursor to the job position, FULL log kept, model reverts, ⚠ clears,
  forward-seek returns to latest), + the old-job snapshot-overlay fallback. `test_md_staleness.py` (MD parity).
  Both fixtures reset the doc-context contextvar to the default doc; both import the app at MODULE level so
  `test_md_milestone1`'s fake-fastapi `sys.modules` swap can't poison `include_router`. Frontend
  `job_staleness.test.js` + panel/controller pins. The in-app ⚠ + roll-seeks-the-tab + return-to-latest
  gesture is human-eye → **MV-OXSTALE** (covers oxDNA + MD).

## Trajectory arrow follows the on-screen run's field (2026-07-06, SHIPPED)
Viewing the composite trajectory of a field lineage (relax → field1 → field2 → …, a
chain of child runs each with its own `dir`/`field_pN`) now re-aims the E-field arrow
per frame to whichever run is on screen — so a chain with DIFFERENT field directions
shows the direction used at each point in the scrub, and the arrow HIDES during the
relaxation stages (no field).
- **Backend.** `routes_oxdna._job_field(job)` → `{dir, field_pN}|None` (run_config.field
  first, else the older `efield {force_pN, dir}`). `_composite_inputs` tags each stage
  tuple with a 5th element = the owning job's field; `oxdna_health._aligned_downsampled_frames`
  + `composite_trajectory_meta` read `item[4]` and surface it as `stages[].field` in BOTH
  the full `/trajectory` payload and the lightweight `/trajectory-meta`. Backward-compatible:
  3/4-tuples still work (field defaults None).
- **Frontend.** Pure `stageAtFrame(stages, i)` / `fieldAtFrame(stages, i)` in
  `oxdna_trajectory_player.js` map a composite frame → its contiguous stage → field. The
  panel stores `r.stages` as `_trajStages`; the player's `onSeek` calls `_applyTrajField(i)`
  which fires a new `onTrajectoryField(field)` dep ONLY at stage boundaries (memoized by
  `_lastTrajField` object identity, so no per-frame DOM churn). main.js wires
  `onTrajectoryField → efieldSetup.applyConfig(field)` (reuses the same arrow path the
  run-config echo uses; `applyConfig` does NOT fire onChange, so no live re-aim side-effect).
  Toggling trajectory OFF restores the SELECTED job's own field via `runConfigForJob`.
- Tests: backend `test_job_field_prefers_run_config_falls_back_to_efield` +
  `test_composite_trajectory_carries_per_stage_field` (field flows through full + meta);
  frontend `stageAtFrame`/`fieldAtFrame` pure specs in `oxdna_trajectory_player.test.js`.
  Backend 4067 / frontend 2207 green; vite build clean. **NOT app-exercised** — needs a real
  chained-field-run lineage with a completed trajectory (GPU runs) to eyeball the arrow
  flipping direction mid-scrub → owes an MV row.

## Anchor requirement relaxed to a warning (2026-07-10, SHIPPED)
The hard "a uniform field needs ≥1 anchor" restriction is GONE on every engine — a field
with no anchor (and no opposing surface) is now allowed, with the UI showing a non-blocking
warning notice about the resulting centre-of-mass drift. User decision; scope = all engines,
warning surfaced frontend-only.
- **Backend (all 400/raise guards removed → allow + warn/log):** oxDNA `/field` + `/run`
  (`routes_oxdna.py`), oxDNA live `/start` + `/reconfigure` + the `n_anchored==0` start guard
  (`routes_oxdna_live.py`), NAMD single-job create + chain create (`routes_md.py`), NAMD prep
  (`md_protocols.py` → `logger.warning`), mrDNA create (`routes_mrdna.py`) + runner
  (`mrdna_runner.py` → `logger.warning`, the `n_held==0` raise softened), LAMMPS
  (`lammps_runner.py` → `logger.warning`). `oxdna_interface.write_field_forces` no longer raises
  on empty anchors — it writes the field `string` block with no traps. CanDo/FEM already fell
  back to a centroid pin (unchanged). The shared predicate `field_anchor.field_needs_strand_anchor`
  + its tests are KEPT (still a valid physics helper) but no backend caller blocks on it anymore.
- **Frontend (warning notice, no block):** `forces_card.js` apply-style ready line now reads
  "⚠ no anchor — the whole structure will drift down-field…" (conditioned on a new `getAnchorCount`
  dep wired for oxDNA/CanDo/NAMD; clears once an anchor is added). The launch/POST blocks were
  removed from `oxdna_jobs_panel.js`, `md_jobs_panel.js`, `cando_jobs_panel.js`, and
  `oxdna_live_controller.js` (start + reconfigure). `chain_sim_model.stagePreflight` ALREADY
  treated this as a `warn` (unchanged) — now aligned with the backend that no longer 400s the chain.
- **Tests flipped** (were asserting the block): backend — `test_oxdna_relaxation` (write_field_forces
  writes field-only), `test_oxdna_surface`, `test_headless_oxdna_build`, `test_namd_efield` (×2),
  `test_mrdna_field`, `test_lammps_routes` + `test_lammps_runner`, `test_oxdna_live_session` (×2),
  `test_chain_completion_e2e`; frontend — `forces_card.test`, `oxdna_live_controller.test` (×2).
  Full backend suite 4665 pass (2 flipped after the FULL run); frontend 2614 pass.

## 7. Open questions to resolve before/within Phase 1

- Default anchor `stiff` and field-stage length/`dt` (start from the equil stage's values).
- Ramp the field (`rate>0`) to avoid a startup kick, or step it on? (Lean: short linear ramp.)
- Box size / PBC: a deflecting tethered arm needs head-room; may need a larger box than relax.
- Substrate `repulsion_plane` at the anchor face — Phase 3+ / ask.
