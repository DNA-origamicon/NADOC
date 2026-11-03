# 2. Anchors (decision: clusters / domains / overhangs; overhangs recommended) — supporting detail

[Topic head](../../project_oxdna_efield.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

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
