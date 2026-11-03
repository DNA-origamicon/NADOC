
# Surface capture strands (oxDNA immobilization) — plan + status

## Topic navigation and current boundaries

Reorganized October 17, 2026. Read the retained contracts here, then only the
matching detail below. Dated results and old handoffs are not new verification
or authorization; current user instructions and `CLAUDE.md` take precedence.

**PEG setup review (2026-09-11):** The experimental PEG sidebar now uses shared
numeric-input colors and offers an engine-independent `POST /api/oxdna/peg/setup`
review. It returns requested counts, a job-request fragment and explicit barriers;
it does not certify launch readiness. Real-input Playwright checks cover review
and wizard payload propagation. Persistence ordering, half-integer count rounding,
NAMD mapping and validation gaps are catalogued in [PEG coating setup](../docs/peg_coating_setup.md).

**Rank:** P3 — SHIPPED & tested end-to-end (build → relax/run → E-field exclusion → display →
UI/overlay/math + pytest/vitest, live-job verified 2026-07-17). Only residuals: (1) `oxdna_design_fingerprint`
does **not** include capture-strand state → toggling capture strands won't invalidate a cached job
(Phase-2 item 7, never wired — low impact, staleness only); (2) `validate_capture_build` oracle is
called from tests only, not the production `append_capture_strands` build path. Do both when convenient;
(3) every setup edit costs ONE full `designRenderer._rebuild` (see "Setup card froze" below) — a real
design (~14k nt) is ~1–3 s per edit. Incremental injection instead of a full rebuild is the fix if it
ever becomes intolerable.

**Relax killed by a FALSE FENE alarm — FIXED 2026-08-18.** Job `1d509398c348`
(VoltronCoreScad, 664 capture strands / 13,944 beads, 130 nm patch @ 50,000/µm²) failed
`2_md_relax` with *"574 bond(s) over-stretched, longest 149.434 units vs the 1.006 cliff"*
after 3 escalating retries. **The structure was fine** — measured on the rejected
`last_conf.dat` with the topology's own n3/n5 links and oxDNA backbone sites: 29,207 bonds,
**0 over the cliff, max 0.9393 units, median 0.7453** (r0 = 0.7564). Nothing to do with the
hard surface or the strands sitting next to it.
- ROOT CAUSE: `run_oxdna_health_check` called `read_configuration_full(conf, design)` with no
  `n_trailing_extra`. `_protein_lead_offset` infers a LEADING protein block from
  `len(conf) - len(walk)`, so 30,077 − 16,133 = 13,944 → it read every origami nucleotide off a
  **capture-bead line**. The reported bonds were random pairs in a 242-unit box (mean pair
  distance ≈ 160 units — hence the ~149 and the constant 574 across all four health samples).
  This is the SAME bug fixed for the display readers on 2026-07-17/18; the health/relax gate was
  never included.
- WHY IT HID: HBList retention is index-independent, so it read 100% while the geometric
  retention in the very same result was **0%**. Without `dnanalysis` on PATH the job would have
  failed the bp gate instead, for the same reason.
- FIX: `run_oxdna_health_check(..., n_trailing_extra=)` threaded into `read_configuration_full`;
  `oxdna_runner` passes `capture_bead_count(job)`. That helper is now canonical in
  `backend/physics/oxdna_surface_strands.py` (`routes_oxdna._capture_bead_count` delegates to it) —
  **use it for every new reader**.
- VERIFIED on the real failed job: max FENE 149.434 → **0.933** units, 574 → **0** over-cliff,
  max backbone 126.8 nm/575 clashes → **1.46 nm/0**, geometric retention 0% → **97.3%**.
  Regression: `test_health_check_measures_the_origami_not_the_capture_beads`.
- NOTE the build also warned `min_dist_to_origami_nm = 0.10` (clash warning, non-blocking by
  design). That is a genuine seeding clash at 50,000/µm² with a 12 nm surface position and is
  worth raising the offset for — but it is NOT what failed this run.

**Production Run silently dropped the capture strands — FIXED 2026-08-18.** Enabling
"Add surface strands" and pressing **Run** launched a strand-free production run and then flipped
the card's own toggle off, so the user got neither the strands nor a reason.
- ROOT CAUSE (two halves): (a) the `prodBtn` handler composed the run body from `field` / `surface` /
  `anchors` and **never read `el.surfaceStrands`** — `RunRequest` had no field for it either;
  (b) `_selectJob(childId)` right after launch echoes the child's `run_config` back through
  `applyConfig`, and with no `surface_strands` on the child that unchecks the box.
- **Capture strands are TOPOLOGY, not a production-time force.** A run branches off the relaxed
  parent by copying its topology/conf, so it can only INHERIT the beads and re-pin their traps —
  it can never add them to an origami-only structure (the Phase-2 "build, not overlay" decision;
  they must be present through relaxation for the origami to hybridise as it settles). So the fix
  is emphatically NOT "build them at run time".
- FIX: pure `oxdna_jobs_panel.captureStrandRunPlan(parentJob, spec)` → `none` / `inherit` / `unbuilt`.
  `inherit` puts `surface_strands: {enabled, subjectToField}` on the run body (INTENT, not a build
  request); `unbuilt` shows a modal explaining that capture strands are built before relaxation and
  **cancels the launch** instead of running without them. Backend: `RunRequest.surface_strands` +
  pure `routes_oxdna.capture_run_decision(parent_run_config, requested)` → 409 when the parent has
  no `built.trap_particles`, and `subjectToField` from the REQUEST overrides the parent's (it is a
  genuine production-time force choice); the child's `run_config.surface_strands` is stamped with
  the exclusion that run actually applied, so the card echoes the run's setting, not the parent's.
- ALSO: `oxdna_floor_setup.applyConfig` does not fire its `onChange`, so the strands card's
  prerequisite gate went stale on every job select — `main._oxdnaApplyConfig` now calls
  `setSurfaceEnabled(floor.isEnabled())` **before** the strands echo (after it, `setSurfaceEnabled`
  would force the just-echoed toggle back off). The card also paints its gate at init.
- Tests: `test_capture_run_decision_*`, `test_run_request_carries_surface_strand_intent`,
  `test_capture_strands_survive_into_a_production_run` (build → decision → one covalent-stiff trap
  per strand, all indices ≥ n_origami); `captureStrandRunPlan` unit tests; new
  `oxdna_surface_strands_setup.test.js` (gate, submit spec, echo-back on/off, debounce, throwing
  onChange). `just test-smart` FAST 7120 pass; 5766 vitest.

**Live continuation parity — FIXED 2026-09-03.** The Live button now submits the
currently selected job together with every current continuation card: field, absolute hard-surface
position, ordinary anchors, surface-deposition anchors, and inherited capture-strand field
participation. The live backend uses the same `capture_run_decision` contract as persisted runs,
re-pins inherited attach ends, excludes trailing capture beads from the field when requested, and
retains that parent metadata for mid-session recomposition. The selected job is re-read after a
stale-job roll/refetch so the launch cannot use the pre-dialog selection snapshot.

**Every card edit reverted the user's visualization — FIXED 2026-08-18.** With a simulation
frame displayed, changing any surface-strand setting snapped the structure back to NADOC native
positions (plus: flexibility map back to strand colours, anchor/selection/clash halos gone).
- ROOT CAUSE: `setExtraNucleotides` reaches its rebuild through the ordinary `_rebuild`, and a
  rebuild means "the design changed" to everything downstream — it disposes the backbone entries
  every overlay holds and clears every glow layer. Owners re-resolve from a `currentGeometry`
  **store subscription** (`anchor_glow`, `clash_overlay`, `selection_manager` all follow that
  pattern). The injection rebuild changes NO store state, so not one of those subscriptions fired,
  and `_rebuild` itself never re-applied `_activeFemUpdates`.
- FIX: `design_renderer._restoreDisplayOverlays(renderer)`, called right after the injection
  rebuild. It re-applies what the renderer owns (`_activeFemUpdates` + the new `_activeScalarColors`
  cache) and then dispatches **`nadoc:display-rebuilt`**; `anchor_glow` and `selection_manager`
  re-resolve on it with their existing paths, and `clash_overlay` gained `_repaint()` so it
  re-resolves its STANDING report instead of re-fetching `/design/clashes` per keystroke.
  `selection_manager`'s rebuild body is now the named `_reresolveAfterRebuild(state)`, shared by
  the store subscription and the event. `_glowLayer` gained the name `'selectionGlow'` so e2e can
  find it.
- GENERATION GATE: `applyFemPositions`/`applyScalarColors` stamp `_rebuildSerial`; the restore
  only fires when that stamp equals `_rebuildSerial - 1`, i.e. the overlay was live on the root
  this very rebuild replaced. Without it, a frame the user had already dismissed with a real
  design edit would be resurrected by the next strand edit. Pinned both ways in e2e.
- **If you add another display-state cache to design_renderer, restore it here too** —
  `design_renderer.test.js` asserts every cache named in the closure appears in the restore.

- [Surface capture strands (oxDNA immobilization) — plan + status — continued detail](details/project_surface_strands/01-surface-capture-strands-oxdna-immobilization--plan--status.md)

<a id="phases"></a>
- [Phases](details/project_surface_strands/01-surface-capture-strands-oxdna-immobilization--plan--status.md#phases)

<a id="phase-1--ui--pure-placement-math--plumbing-done-decision-free"></a>
- [Phase 1 — UI + pure placement math + plumbing (DONE, decision-free)](details/project_surface_strands/01-surface-capture-strands-oxdna-immobilization--plan--status.md#phase-1--ui--pure-placement-math--plumbing-done-decision-free)

<a id="phase-2--dna-topology--geometry-decisions-answered-2026-07-17"></a>
- [Phase 2 — DNA-topology + geometry decisions (ANSWERED 2026-07-17)](details/project_surface_strands/01-surface-capture-strands-oxdna-immobilization--plan--status.md#phase-2--dna-topology--geometry-decisions-answered-2026-07-17)

- [Phase 2 — DNA-topology + geometry decisions (ANSWERED 2026-07-17) — continued detail](details/project_surface_strands/02-phase-2--dna-topology--geometry-decisions-answered-2026-07-17.md)

- [Phase 2 — DNA-topology + geometry decisions (ANSWERED 2026-07-17) — continued detail](details/project_surface_strands/03-phase-2--dna-topology--geometry-decisions-answered-2026-07-17.md)

<a id="phase-3--backend-generation--tests-after-phase-2-answers"></a>
- [Phase 3 — backend generation + tests (after Phase 2 answers)](details/project_surface_strands/03-phase-2--dna-topology--geometry-decisions-answered-2026-07-17.md#phase-3--backend-generation--tests-after-phase-2-answers)

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
