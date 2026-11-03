# Phase 2 — DNA-topology + geometry decisions (ANSWERED 2026-07-17) — supporting detail

[Topic head](../../project_surface_strands.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

**E-field exclusion toggle (Phase 2c, the LAST deferred piece) DONE (2026-07-17).** The
"Subject surface strands to the E-field" checkbox now actually does something when OFF.
Before: the flag reached `CaptureSpec.subject_to_field` and was dropped — the field's
`particle = -1` block always swept the capture beads. Now the production `/run` handler
reads `run_config.surface_strands.subjectToField` (default true); when false AND capture
beads exist AND a field is applied, it passes `field_exclude_trailing = n_beads` to
`write_run_forces`, which fields only origami particles `[0, n_total − n_beads)`.
- **Mechanism = comma LIST, NOT per-particle blocks and NOT a dash range.** `field_string_block`
  gained `n_particles=K` → `particle = 0,1,…,K-1`. Capture beads are always appended last so
  origami is exactly the leading block. **Dash range `0-K` is WRONG for DNA** — oxDNA's
  `Utils::get_particles_from_string` reads `a-b` as a 5'→3' topology walk and throws "couldn't
  get from particle a to b" (the old reverted attempt; see [[project_oxdna_efield]]). A comma
  list is a plain index set and the forces file has no line-length cap (`getdelim`), so ~14k
  indices on one line is safe. ON (default) keeps `particle = -1`.
- Only wired on the consolidated `/run` path (the real surface+field production path that also
  re-pins caps). The legacy `/field`-only child + live paths don't build capture strands, so no
  exclusion needed there. Relax build has no field.
- Tests: `test_field_string_block_particle_selection` + `test_write_run_forces_field_excludes_trailing_caps`
  (ON→`-1`, OFF→origami-only list, degenerate exclude ≥ n_total → falls back to `-1`) in
  `test_oxdna_relaxation.py`. `just test-smart`: 5241 pass (4 failures pre-existing + unrelated —
  `/mnt/c` PermissionError in disk_guard/run_dir, atomistic geometry-hash locks). NOT app-verified
  (needs a GPU surface+field run to eyeball caps staying upright vs pressed flat).

**Status (2026-07-17): build + run path DONE & tested.**
- Phase 1 UI: `frontend/src/ui/oxdna_surface_strands_setup.js` + pure `scene/surface_strands_math.js`
  (19 vitest). Card in `#oxdna-floor-body`; Gen button reuses `POST /design/random-sequence`.
- Builder: `backend/physics/oxdna_surface_strands.py` — B-form helical seed replicating
  `geometry.py`'s FORWARD nucleotide with LOCKED B-DNA constants (bond ≈0.813 nm, FENE-safe);
  mulberry32 ported from JS; 2 nm min spacing; append-only (origami byte-preserved). 12 pytest
  (`tests/test_oxdna_surface_strands.py`) incl. full `prepare_oxdna_job` integration.
- Relax build (`oxdna_runner.prepare_oxdna_job`, `surface_strands=`): wall computed from
  origami-ONLY conf, then capture strands appended at that plane (avoids double-offset); held by
  ~7000-stiff traps in `forces.txt` + `equil_forces.txt`; `absolute_forces` via `surface_present`.
  `job.n_nucleotides += n_beads`; clash → non-blocking `run_config.surface_strands.built.clash_warning`.
- Production `/run` (routes_oxdna): inherits capture beads via copied top/conf, re-pins them
  (`cap_particles` from parent `run_config`), field-on-all; `absolute_forces` includes caps.
- Payload: `CreateOxdnaJobRequest.surface_strands`; frontend sends it in the relax body (with
  surface); echo-back via `runConfigForJob.surfaceStrands` → `applyConfig`.
- Verified: `just test-smart` 5193 pass; `test_oxdna_surface*` 30 pass; frontend 19 + card/Gen smoke.

**UX + 3D preview (2b) DONE (2026-07-17):**
- Prerequisite gate: hard-surface toggle must be ON to enable capture strands
  (`setSurfaceEnabled`, wired from the floor card's onChange; checkbox disabled + gate hint otherwise).
- **New seed** button re-scatters the preview (`_newSeed`, Math.random seed).
- 3D overlay `frontend/src/scene/surface_strands_overlay.js`: translucent coverage patch
  (circle/square) + anchor dots (InstancedMesh) coplanar with the hard surface, using a
  frontend port of backend `plane_basis` so dots land where strands build; a plane-constrained
  **TransformControls centre gizmo** whose drag pushes the new X/Y offset back via
  `onCenterMove → setOffset`. Driven by the floor grid push (`setPlane`) + strands onChange
  (`update`). Verified in-app: patch + 24 dots for 100 nm ⌀ @ 3000/µm², New-seed re-scatters,
  surface-off hides overlay + disables checkbox, 0 console errors. (Gizmo drag not smoke-scriptable
  — follows the cluster_gizmo TransformControls pattern.)

**Headless automation + validation DONE (2026-07-17):**
- Setup+build headless via `prepare_oxdna_job(..., surface_strands=)` (and `POST /oxdna/jobs`).
- **Oracle** `oxdna_surface_strands.validate_capture_build(top, conf, n_origami_strands, trap_particles)`
  — reads the built files (independent of build code), checks count consistency, capture threading,
  FENE-safe backbone bonds, ≥2 nm attach spacing, finite coords, trap-index range. Reusable by the
  coverage/automation loop. `tests/test_oxdna_surface_strands.py` (14 pytest) incl.
  `test_headless_setup_build_validate` (full entry) + `test_oracle_catches_a_broken_bond` (proves it goes red).

**Display correctness fix DONE (2026-07-17) — capture jobs now render the origami correctly:**
- ROOT CAUSE (found via first live job `28f1e2ed5fe2`): the whole results-display pipeline is
  design-walk-driven (`read_configuration_full` iterates `_strand_nucleotide_order` = origami only).
  Two bugs for capture jobs: (a) `assert_topology_matches_design` 409'd (n_top=16222 vs walk=14774);
  (b) `_protein_lead_offset = max(0, len-order)` treated the 1448 TRAILING capture beads as LEADING
  protein → offset 1448 → **every origami nucleotide misindexed onto a capture-bead line (garbage)**.
- FIX: `assert_topology_matches_design(..., extra_trailing=)` allowance; `read_configuration_full`/
  `read_configuration_unwrapped` gained `n_trailing_extra=` → `_protein_lead_offset(...,n_trailing_extra)`
  subtracts trailing extras (offset 0 for capture jobs, origami read from the front). `_relaxed_full_map`
  (routes_oxdna) reads `cap_beads` from `run_config.surface_strands.built.n_beads` and threads both.
  Verified on the LIVE job: guard OK, 14774 origami keys read correctly (first nuc [1.98,4.97,43.45]
  vs buggy [20.1,4.2,34.49]). Regression test `test_display_reader_skips_trailing_capture_beads`.
- Correction (2026-07-18): only the relaxed configuration reader received that trailing count.
  Production RMSF and composite-trajectory readers independently inferred a leading protein offset,
  so their origami identities were still shifted by all 948 capture particles. Those paths now accept
  and cache by `n_trailing_extra`, and every RMSF/trajectory route (including atomistic/surface frames)
  supplies the job's built capture-bead count.
- **First live job verdict:** capture strands FENE-safe throughout relax (bonds 0.513–0.769 nm, 0
  over cliff); md_relax auto-retry was normal ORIGAMI escalation, not capture-caused. GPU confirmed
  (MC=CPU-only by design; md_relax/equil=CUDA).

**Alignment disallowed for surface jobs DONE (2026-07-17, user request):** Kabsch-superposing a
relaxed structure back to the design pose fights the settling that keeps it above the plane → looks
like it clips through the surface. `_relaxed_full_map` now forces `align=False` when `_job_has_surface(job)`
(run_config.surface or surface_strands) — covers /display, /display-surface, /display-atomistic(+frames,
+bin), /shape-source. `unwrap_align_to_reference(align=False)` still unwraps + box-shifts to the
reference (structure stays whole + near the plane; docstring literally cites the hard-surface case),
only the misleading superpose is dropped — and it spares aligning the capture beads. Frontend:
`_applyRunControls` disables + unchecks the "Align to design pose" toggle for surface jobs (tooltip).
Test `test_surface_jobs_disallow_alignment`. (Not applied to rmsf/deviation — align there is the
analysis reference, not the clip view.)

**Visualization of the strands DONE (2026-07-17) — preview + real results, with mode switch:**
- Preview overlay (`surface_strands_overlay`) renders the actual B-form standing strands (beads +
  backbone polylines) at the seed placements, using a JS port of the locked B-DNA constants
  (`captureStrandLocalBeads` in surface_strands_math) — what you see is what's built. Patch +
  plane-locked centre gizmo + New-seed. Shown while SETTING UP a job.
- Results: backend `/display` now returns `surface_strands` (per-strand world-nm bead lists) via
  `_capture_display_strands` (routes_oxdna) — reads the trailing [N_orig..N_total) lines, single
  group box-shift onto the origami's display image (align=False → same raw frame, no Kabsch/
  rotation needed; the `extra_points` path would scatter a 100 nm patch so it's avoided).
- Frontend: `oxdna_display.displayJob` → `onSurfaceStrands(resp.surface_strands)` →
  `overlay.setResults()` → RESULTS mode: patch + gizmo hidden, real simulated beads/chains drawn.
  Display off / no frame → `setResults(null)` → back to the seed preview. So once a job begins the
  preview is replaced by the real anchored strands at their simulated positions, tied to the display.
- **Verified LIVE** (job b8e322137d6f, fresh server): `/display` → 14774 origami + 181×14 capture
  beads, finite; overlay mode-switch smoke (preview↔results) clean. Backend chain confirmed on the
  running md_relax last_conf.
