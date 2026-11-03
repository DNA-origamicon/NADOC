# Force-mapping REST/UI wiring — SHIPPED 2026-07-06 (field + anchors + gizmo, live-verified) — supporting detail

[Topic head](../../project_lammps_oxdna.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Force-mapping REST/UI wiring — SHIPPED 2026-07-06 (field + anchors + gizmo, live-verified)
The headless force primitive is now driveable from the app.
- **Backend.** `CreateLammpsJobRequest` += `field`/`wall`/`anchors`/`anchor_stiff`;
  `create_lammps_job` passes them to `prepare_lammps_job`, **400s on a field-without-
  anchor** (`LammpsError`), and stores the `forces` meta on the job. `LammpsJob` +=
  `forces: dict|None` (persisted). Tests: `test_lammps_routes` (+ field-without-anchor
  400 fast; + real steered create records forces meta / fixes in `in.lammps`, slow).
- **Frontend — three separate collapsible cards** in the LAMMPS section, mirroring the
  oxDNA panel (updated 2026-07-07 from the original single combined card): **Electric
  field** (`lammps-field-*`), **Anchors** (`lammps-anchors-*`), **Surface**
  (`lammps-surface-*`) — one module `ui/lammps_forces_setup.js`
  (`initLammpsForcesSetup({gizmo,getSelection,getBaseCount,onChange})→{getForces,
  fieldNeedsAnchor,detachGizmo,refresh}`) manages all three via a small `_card()`
  collapse helper (each collapses independently). `getForces()→{field,anchors,wall}`.
  **Reuses `scene/efield_math.js`** (field+anchor helpers: `resolveSelectionAnchors`,
  `addAnchors`/`removeAnchor`, `arrowLenForPn`, `fieldColorHex`/`fieldZone`,
  `EFIELD_PN_LOW`) **and `scene/oxdna_floor_math.js`** (`floorSurfaceSpec`/
  `formatOffsetNm` → the surface `wall={dir,offset_nm,stiff}` payload, six-axis side
  dropdown) + the **same `efield_gizmo`** (a SECOND instance —
  `initEfieldGizmo(...,name)` gained an optional group-name arg, default unchanged;
  LAMMPS uses `'lammps-efield-gizmo'`). Field = pN/nt + x/y/z dir (drag the scene arrow),
  anchors = "Add selected" from the scene selection (overhang/strand/domain/cluster/base)
  → chips. Gizmo attaches only when the card is open AND the field is enabled.
  - **Jobs card now follows the oxDNA example:** filters to the **current design** via
    the shared `filterJobsForPart(_jobs, getWorkspacePath(), showAll)` (job
    `design_source_path` ↔ loaded design path) + a **"show all designs"** toggle
    (`lammps-jobs-show-all`, localStorage-persisted); statuses already render via
    `statusBadge`/`statusKeyFor('lammps',…)`. Create now sends `design_source_path` +
    the forces; a field-without-anchor is blocked client-side with a toast.
  - `buildCreatePayload` gained `designSourcePath`/`field`/`anchors` (attaches only
    non-empty). `initLammpsJobsPanel` gained `getWorkspacePath` + `forcesSetup` deps.
  - **main.js Δ = +9** (import + `initLammpsForcesSetup` factory + the LAMMPS gizmo
    instance + the two new panel deps — wiring only, no cohesive logic).
  - **Surface (wall) UI** (2026-07-07): the Surface card's enable/axis/offset/stiff →
    `wall` payload; the backend `wall=` path (axis-aligned `fix wall/harmonic`, non-
    periodic boundary) was already there. `buildCreatePayload` + the panel now also
    forward `wall`. **`_card` gotcha:** the field card's `onClose:_syncGizmo` runs during
    init before the card handle exists → `fieldCard` is a hoisted `let` (null-guarded in
    `_syncGizmo`), NOT a `const` (a `const` TDZ throws even through `?.`).
  - **Anchor glow + surface grid = same as oxDNA** (2026-07-07): LAMMPS anchors drive the
    SAME purple `anchorGlow` instance (`designRenderer.setAnchorGlow`, InstancedMesh named
    `'anchorGlow'`, count>0 = glowing) via `lammps_forces_setup.getAnchors()` +
    `onChange → main._refreshLammpsAnchorGlow` (glows whenever ≥1 anchor is marked — not
    gated on the field, unlike oxDNA's `fieldOn && anchors`). The Surface toggle drives the
    shared View grid via a new `setSurfaceGrid` dep → `_viewToolButtons.setSurfaceGrid({
    enabled,axis,offsetNm})` (identical to `oxdna_floor_setup`). **TDZ pattern:** onChange /
    setSurfaceGrid reference main.js consts created after the factory, so the module GATES
    them behind a `_ready` flag (`_notify`/`_pushGrid` no-op until construction settles) —
    the same "never fire onChange during construction" rule the oxDNA glow relies on. The
    LAMMPS panel+forces init was MOVED in main.js to AFTER the anchorGlow/`_viewToolButtons`
    setup so it can share them. The existing `nadoc:left-tab-change` handler clears the glow
    for both engines.
  - Tests: `lammps_forces_setup.test.js` (field null-until-enabled, weak-field warning,
    anchors-from-selection, fieldNeedsAnchor, gizmo attach-gating, **surface wall spec**,
    **cards collapse independently**); `lammps_jobs_logic.test.js` (+payload path/forces/
    **wall** attach+omit); `lammps_jobs_panel.test.js` (+current-design filtering, show-all,
    forces payload, field-without-anchor blocked). Frontend suite 2269 green.
- **Verified:** frontend vitest 2266 green; backend lammps suite 57 green (incl. slow
  real steered run); vite build clean; smoke boot-clean (the 2 teardown-gate fails were
  an auto-scaffold timing flake in a test helper — passed on isolated retry, unrelated).
  **LIVE app-exercised** (throwaway Playwright on the running app, then deleted): loaded
  a scaffolded part → Dynamics → LAMMPS → External forces card renders + opens, enabling
  a field shows the graded "⚠ strong field — 25 pN/nt — add ≥1 anchor" ready line, the
  scene gizmo attaches, the "show all designs" toggle is present, **zero console errors**.
