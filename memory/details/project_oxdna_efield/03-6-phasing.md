# 6. Phasing — supporting detail

[Topic head](../../project_oxdna_efield.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

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
