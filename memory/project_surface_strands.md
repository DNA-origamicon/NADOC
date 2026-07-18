# Surface capture strands (oxDNA immobilization) — plan + status

**Goal.** Simulate immobilization of a DNA origami on a functionalized surface: the hard
surface (repulsion plane) carries a random dispersion of ssDNA **capture strands**
complementary to the origami's overhangs. The origami's overhangs hybridize to these,
tethering it to the surface. An optional E-field drifts the origami toward the surface so
compute isn't wasted waiting for first contact — with a toggle to **exclude** the capture
strands from that field (else a downward drift field presses them flat against the plane).

**Scope guard.** oxDNA engine ONLY. Under the existing "Hard surface" card.

**Three-Layer note.** Capture strands are new *topological* entities (real oxDNA strands
the origami must be able to bond to). They are NOT a display overlay and NOT a
production-only force. They change the built topology → change the design fingerprint →
require the system they live in to be present from the build/relax stage, not bolted onto
a relaxed origami-only structure. This is the crux of Phase 2.

---

## Phases

### Phase 1 — UI + pure placement math + plumbing (DONE, decision-free)
Frontend-only, no topology decisions, no backend. Everything here is either display wiring
or pure deterministic math with unit tests.

- **Pure math** `frontend/src/scene/surface_strands_math.js` (+ `.test.js`):
  - `mulberry32(seed)` — deterministic PRNG, chosen to be trivially re-implementable in
    Python so a seed reproduces the *same* dispersion in the eventual backend generator.
  - `surfaceStrandArea`, `surfaceStrandCount` (density/µm² × area → N), `surfaceStrandPlacements`
    (seeded in-plane (u,v) points; area-uniform for circle, uniform for square, centred on
    the X/Y offset), `surfaceStrandsSpec` (normalize raw UI fields → clean spec + count).
- **UI card** `frontend/src/ui/oxdna_surface_strands_setup.js` (factory
  `initOxdnaSurfaceStrandsSetup({onChange, ids}) → {getStrandsSpec, isEnabled, applyConfig, refresh}`)
  mounted in the Hard-surface card body (`index.html`, inside `#oxdna-floor-body`). Fields:
  sequence, attach end (5′/3′), density (/µm²), shape (circle/square), radius|side (nm),
  X/Y offset (nm), seed, and the **"Subject surface strands to the E-field"** toggle. Live
  preview shows the resulting strand count.
- **Wiring** `main.js`: import + one-line factory init + `surfaceStrands` added to
  `_oxdnaRunElements()` and echoed in `_oxdnaApplyConfig()`. The spec is carried but NOT yet
  injected into the submit payload — the production/relax payload builders in
  `oxdna_jobs_panel.js` still read only `dir/offsetNm/stiff` from `surface`, so nothing about
  job submission changes yet.

### Phase 2 — DNA-topology + geometry decisions (ANSWERED 2026-07-17)
The "ask first" questions, now resolved by the user (JJ):

1. **Build, not overlay.** ✅ Capture strands are baked into the built system and present
   through relaxation — a dedicated immobilization build. NOT a production-time force on a
   relaxed origami-only `.dat`.
2. **Geometry = ssDNA coil.** ✅ Random-walk coil (not a rigid standing rod). Seed backbone
   spacing inside the FENE-safe window (0.506–1.006 units, r0=0.7564); `SSDNA_CONTOUR_PER_NT
   = 0.68 nm`. Reuse the strand-extensions anchor-outward frame solve, anchored at the
   attach-end backbone site and coiling outward.
3. **Tether = C-C-covalent-stiff trap.** ✅ One `trap` per strand at its attach-end backbone
   site, stiffness ≈ a covalent C-C bond (~400 N/m). Converts to **≈ 7000 oxDNA stiff
   units** (stiff unit = ε/σ² = 48.63 pN / 0.8518 nm ≈ 57.1 pN/nm; 400 N/m = 4e5 pN/nm →
   ~7005). ~7× `DEFAULT_ANCHOR_STIFF`. Verify MD stability (`dt·√stiff` vs the RATTLE/FENE
   budget) — may need the smaller production `dt`. Absolute coords → **`fix_diffusion=false`**.
4. **Sequence = verbatim + a "Gen" button.** ✅ Take the entered sequence 5′→3′ verbatim.
   ALSO add a **Gen** button that designs a sequence via the **Johnson et al. algorithm**.
   ⚠ OPEN: need the reference / spec for that algorithm before building Gen (see Open items).
5. **E-field exclusion — worth it, but LAST.** ✅ Ship field-on-ALL first (capture strands
   feel the field); implement the per-particle exclusion (origami-only `string` blocks) as
   the final phase so field-on-all is testable meanwhile. The UI toggle already exists and
   defaults on; wire its `false` branch last.
6. **Placement = 2 nm min spacing, no origami avoidance.** ✅ 2 nm min centre-to-centre baked
   into placement (`MIN_SPACING_NM`, rejection sampling — DONE in Phase 1 math). Do NOT
   exclude the origami footprint. Default coverage diameter/width **100 nm**
   (`DEFAULT_COVERAGE_NM`, HTML default — DONE).
7. **Synthetic key + filter audit.** New capture-strand nucleotides need a `__`-prefixed key
   and an audit of every `isinstance(k[1], int)` / `__`-guard filter (`oxdna_health`,
   `atomistic_to_nadoc`, `*_shape_source`, `skip_twist`). Add the field to
   `oxdna_design_fingerprint`.
8. **Viz.** 3D overlay of the coverage patch + placed strands (anchor-glow `_anchorsByEngine`
   pattern; placement points already available from the Phase 1 math).

**Seed-geometry decision (2026-07-17, user):**
- **B-form geometry** for the standing capture strand (reuse NADOC's B-DNA helical frames —
  the locked `_PHASE_*` convention — NOT a hand-rolled straight ssDNA rod). B-DNA backbone-to-
  backbone spacing ≈ 0.68 nm → FENE-safe, consistent with the origami build.
- **Clash → WARN, never block.** Compute min capture-bead↔origami-bead distance; surface a
  non-blocking warning (like the field-anchor warn-only policy). Do NOT auto-raise clearance.
- **Absolute surface placement, trust the user.** Strands attach at the user's absolute surface
  position; the user is responsible for setting the surface offset so there's no t=0 clash.
  (Ties into the "surface position is absolute across simulations" work — `position_nm`.)

**Phase ordering going forward:** (2a) revise builder to B-form frames + clash warning; wire
into `prepare_oxdna_job` (relax build) so strands are present through relax + C-C-stiff attach-
end traps + `fix_diffusion=false`; thread `surface_strands` through the relax/RunRequest payload
+ persist in `run_config`; pytest coverage. (2b) 3D viz overlay. (2c — LAST) E-field exclusion
toggle → per-particle origami-only field blocks. (2d — DONE) the "Gen" sequence button.

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
- Downstream consumers (oxdna_health `_cg_beads_from_frame`, shape_source `_rmsf_profile`) are
  safe-by-omission: they iterate the (now-correct) design-keyed frame, so capture beads are simply
  absent, not misindexed. No §4 guard edits needed.
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

**Native render integration — CG reps (2026-07-17, user: "full integration into renders"):**
Capture strands now render in the actual representation system (beads/slab/cylinders/hull), not a
separate overlay. Mechanism: overlay emits world-nm bead chains (`onStrands`) → `main` converts via
`captureNucleotidesFromChains` (surface_strands_math) → `designRenderer.setExtraNucleotides(nucs, color)`
merges them into the geometry `_rebuild` consumes + colours them (cyan `_eff[strand_id]`). Synthetic
`cap<i>` helix/strand ids (no `__` → unfiltered), unique bp_index ≥ 1e6 (no slab collision), FORWARD-only.
Overlay keeps ONLY the coverage patch + centre gizmo; highlight→emit chains or []; colour→patch tint +
strand `_eff`. `displayJob` reordered: `onSurfaceStrands` (rebuild) BEFORE `_applyFem` (in-place origami
move) so the rebuild doesn't clobber the FEM overlay. 26 math + 3016 frontend tests green; injection path
error-free on enable/highlight/colour.
**VERIFIED IN APP (2026-07-17, Playwright + loaded design):** strands render as real beads+slabs in
the CG reps (capBeads==extraNucs), selection works (filters apply). FIXES from user feedback:
- **Colour was black** — `_eff[strand_id]` needs an INT but I passed a `'#hex'` string → `setHex`
  rendered black. `setExtraNucleotides` now `parseInt`s it. Verified colour changes apply to the beads.
- **Slabs oriented wrong** — my crude a1/a3 (chain tangent) → the overlay now emits proper B-form frames
  (a3 = surface normal = helix axis; a1 = inward radial = backbone→base). `captureNucleotidesFromChains`
  uses supplied `{p,a1,a3}` (results fall back to chain-tangent). Verified capSlabAxis == surface normal.
- **Highlight toggle** works (emit chains / []; capBeads 568→0→568).
- **Colour control** = hex text box + wheel, synced both ways (`oxdna-surfstrand-color-hex`); wheel is
  canonical. Selection of cap beads works per selection filters (user confirmed).
- Debug hook `designRenderer.debugCaptureRender()` + DEV `window.__nadocDR` (used for validation).
  Gotcha: caps only render when a DESIGN is OPEN in the editor (currentGeometry non-empty) — the file
  browser landing page has no geometry, so `capBeads==0` there is expected, not a bug.
**Heavy reps (surface, vdw/ballstick) STILL NOT covered** — backend meshes (`/design/surface`,
`/design/atomistic` + oxDNA job reconstruction) must emit capture strands (next, larger piece).

**Bbox feedback-loop fix (2026-07-17):** native injection put cap beads into `getBackboneEntries()`,
and BOTH `main._oxdnaStructureBounds` (patch centre) and `view_tool_buttons._designBBox` (surface grid)
built the design bbox from ALL entries → the strands fed their own placement frame. Symptoms: changing
sequence/seed/colour moved the coverage patch; the gizmo moved it randomly (its `_baseCenter` reference
jumped each rebuild). FIX: both bbox loops now exclude `strand_id.startsWith('cap')`. Verified: patch
centre stable across seq 4→16→2 nt; offset mapping round-trips; gizmo reference stable. When ANY code
consumes `getBackboneEntries()` for a design-extent/measurement purpose, it must exclude `cap<i>`.

**Display box-shift clip artifact (diagnosed 2026-07-17, run killed):** an UN-anchored origami in a
surface relax (`fix_diffusion=false`, only capture strands trap-pinned) diffuses freely; on the killed
run it drifted ≈180 nm ≈ one box length. The align=False PBC box-shift (`unwrap_align_to_reference`
snapping to the nearest reference image) then wrapped it by one box vector → rendered it straddling the
plane (false "clipping"; 0 beads physically on the forbidden side). ROOT = the drift. FIX (proposed, not
yet built): auto-anchor the origami (light COM/tether) when a hard surface is enabled for a relax, so it
can't diffuse a box away; the production E-field does the real drive-down. Also revisit box size.

**Display controls DONE (2026-07-17):** card has **Highlight strands** (bead/chain visibility),
**Coverage shape** (patch visibility; centre gizmo tied to it), and a **Colour** picker defaulting to
**cyan #00ffff** (applied to beads+chains+patch). Defaults ON when the options are first enabled
(setup); OFF when a job entry is selected (`applyConfig` unchecks both — toggle on to emphasise for
figures). Overlay: `setHighlight/setShapePreview/setColor`, independent per-mesh visibility in `_draw`
(patch shown in results too, overlaying the coverage area on real strands). Wired via
`main._refreshStrandsOverlay`. NOTE: strands render as the BEAD rep (spheres + backbone lines);
matching the structure's slab/surface/atomistic reps for strands is a FUTURE enhancement.
2. **2b — pre-run 3D viz overlay** of the coverage patch + placed strands (placement points already
   available from `surface_strands_math.surfaceStrandPlacements`; follow anchor-glow pattern).
3. **2c (LAST) — E-field exclusion toggle** → per-particle origami-only `string` blocks (the
   `subjectToField=false` branch); UI toggle already wired + persisted.

### Phase 3 — backend generation + tests (after Phase 2 answers)
Inject strands into the topology/config walk, compose the tether anchors into the forces
file, wire the payload + fingerprint, pytest scratch-session coverage. Verify only via
pytest (never mutate the live server).

---

## Key facts (from the codebase, for whoever picks this up)
- Hard surface UI: `ui/oxdna_floor_setup.js` (+ pure `scene/oxdna_floor_math.js`); DOM in
  `index.html` `#oxdna-floor-*`; payload `body.surface = {dir, offset_nm, stiff}` built in
  `oxdna_jobs_panel.js` (~1099 relax, ~1599 production); echo via `runConfigForJob`.
- Backend surface: `oxdna_interface.repulsion_plane_block` / `wall_position_from_extent` /
  `surface_anchor_forces_text` / `write_run_forces`. Plane `dir·r + position = 0`,
  `particle=-1`. `NM_TO_OXDNA = 1/0.8518`. Absolute forces ⇒ `fix_diffusion=false`.
- Backend E-field: `field_string_block` (`type=string`, `particle=-1`, `F0`), `OXDNA_FORCE_PN
  = 48.63` pN/unit. Anchors = `type=trap`, `DEFAULT_ANCHOR_STIFF = 1000`.
- Topology/config gen: `_walk_strand_nucleotides` (single source of particle order),
  `topology_rows` / `write_topology`, `write_configuration` / `nuc_conf_line`. Extension
  tails: `_EXT_PREFIX="__ext_"`, `strand_extension_tails`, tail beads emitted before first /
  after last domain so n3/n5 threading bonds them automatically — the precedent for adding
  new strands to the walk.
- See also: [[project_oxdna_efield]], [[project_strand_extensions_sim]],
  [[project_oxdna_relaxation]], [[project_simulate_panel_overhaul]],
  [[feedback_no_live_server_mutation_for_verify]].
