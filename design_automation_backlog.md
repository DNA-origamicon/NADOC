# design-automation backlog — UI-only / API-less operations → programmatic + validated

**Purpose.** NADOC has many operations a user can *only* perform with the mouse, and many more that
have a REST route but **no programmatic/headless entry point**. That gap blocks two goals at once:
**(1) automated correctness validation** (you can't pin what you can't drive headlessly) and
**(2) eventual text-to-DNA-origami** (an AI/script can only build what's reachable without a canvas).
This loop closes those gaps **one feature per session**, the same disciplined way the god-file carve-ups
(`backend_router_carveup.md`, `main_js_carveup.md`) and the fix loop (`issues_ledger.md`) work:
a ranked backlog, a per-session protocol, a metrics row in `design_automation_log.md`, a living handoff,
and **cross-loop intake** into the bug ledger + manual-validation debt.

It is a *feature-development* loop, so it is governed by **`FEATURE_DEVELOPMENT.md`** (the module-first
anti-backslip law). The carve-ups *shrink* god-files; this loop must not *re-grow* them. Read that file
before writing any feature.

> **⚠ THIS MAP IS SEQUENCING-ONLY.** Line numbers and route names drift. The audit below was taken
> 2026-06-16; before claiming any item, **re-derive its real surface** — does the REST route still exist,
> is it still UI-wired, what's the actual coupling. Fix the entry you touched on your way out.

---

## The two goals, and why validation comes first

The user chose **validation-first ranking**: rank by which missing API most unblocks *automated
correctness checks*, with text-to-DNA enablement as the tiebreaker. The logic: every headless wrapper we
add is only trustworthy if it ships with a way to *prove* it does the right thing. The validation harness
(Tier 0) and the per-feature oracles are therefore the spine — text-to-DNA (Tier 4) is built *on top of*
a validated wrapper library, not before it. A wrapper with no oracle is a liability, not an asset.

Tiers 0–4 pin the **topological + geometric** layers (deterministic — exact fingerprints, analytic
geometry). **Tier 5** extends the spine to the **physical layer**: drive oxDNA headlessly, *measure*
properties of the relaxed structure, and eventually iterate the design until a user constraint is met
("make these two ends 50 nm ± 5 nm apart"). That introduces a new, *stochastic* oracle class — a measured
property within tolerance, **gated by the confidence metric** (frames pooled / RMSF SE), not exact
equality — and is the concrete bridge from Tier 4's text-to-DNA grammar to *constraint-driven* design.

---

## Target shape (where new code lands — NOT the god-files)

Three shapes, and deciding which one an item wants is the first move:

1. **Headless wrapper** — a REST-backed design operation that has no programmatic entry → a thin function
   in **`backend/api/headless_build.py`** (the existing mouse-free construction module — the seed for
   AI-driven design). Mirror its existing wrappers (`create_bundle`, `extrude`, `auto_scaffold`,
   `overhang_extrude`, `full_autostaple`). It runs the *same* service the route runs; it does **not**
   duplicate logic. **Never** add the logic to `crud.py`/`assembly.py`.

2. **New headless module** — when a whole subsystem has no programmatic builder. The flagship case:
   **assembly has no headless builder** → a NEW `backend/api/headless_assembly_build.py` mirroring
   `headless_build.py` (scratch-session context manager + fluent ops). New module, not a god-file block.

3. **Service + oracle push** — when the operation's *logic* (not just its HTTP shell) belongs in a pure,
   testable place → a pure HTTP-free fn in **`backend/core/<area>.py`** + a **validation oracle** that
   pins its contract. `backend/core` may import nothing from `backend/api`.

Whichever shape: the **mandatory deliverable is a validation augment** (next section). A wrapper without
one does not ship.

---

## Improvement metric — the anti-shovel contract (this is the point)

The carve-up's failure mode was *LOC-shoveling*. This loop's failure mode is **passthrough-shipping:**
adding a `headless_build.foo()` that just forwards to `POST /design/foo` and calling it done — when it
added *no new validation power* and can't be trusted by an automated builder. That is not closing the
automation gap; it's lengthening the call chain.

So **"a wrapper exists" is never the pass criterion.** The pass criterion is:

### Primary metric — a reusable **validation augment** shipped with the feature
Every AF item ships **≥1 new automated oracle/pin** that proves the operation is correct, and that is
**reusable** by later items. Acceptable forms (mirror an existing pattern — see `design_automation_log.md`
"Oracle catalog"):
- **Round-trip equality** — build via the new wrapper → export `.nadoc`/`.nass` → import → assert
  `_canonical_topology` equal (the id/order-independent fingerprint from `test_section_router.py`).
- **Inverse-pair invariant** — op then its inverse → topology unchanged (e.g. nick→ligate, add→delete).
- **Geometric oracle** — the result's geometry matches an analytic expectation (mirror
  `derive_periodic_delta`, the circle circularity oracle, the section-router gap-clearance metrics).
- **`validate_design` gate** — the built design passes the topological validator (no unresolved nicks,
  consistent strand positions, correct domain count).
- **JS↔Python parity** — if the op has a frontend preview, its JS logic and the Python build pin to the
  same numeric oracle (mirror `circle_primitive_logic.js` ↔ `core/circle_primitive.py`).

### Secondary metrics (log the ones that moved)
- **Headless coverage** — REST design/assembly routes that now have a headless wrapper, before→after.
  (Tier 0 builds the automated coverage report so this number can't go stale.)
- **God-file LOC Δ** — `crud.py` / `assembly.py` / `main.js` must end **flat or lower**. A rise means
  logic crept into a god-file instead of `headless_build`/`backend/core` — extract before committing.
- **Cohesion** — the new wrapper/module's *one reason to change* in a sentence.

### The required justification line
Every metrics row ends with: **"Validation gained, not just a passthrough: ___"** naming the oracle
shipped and what it now proves that nothing proved before. If you can't write it honestly, you shipped a
passthrough — add the oracle or revert.

---

## Per-session loop protocol

A fresh session keeps token cost low. Per session:

1. **Read** this map (start with `## Next-session handoff`) + `design_automation_log.md` (conventions +
   oracle catalog + lessons + difficulties). Read `FEATURE_DEVELOPMENT.md` (module-first law). Skim the
   relevant `memory/project_*.md` for the area (e.g. `headless_build`, `assembly_overhaul`).
2. **Pick ONE item** — the handoff's `▶ NEXT`, or the topmost unchecked backlog entry, or one the user
   names. One AF item (or one phase of a multi-phase item) per session.
3. **Re-derive the surface (cheap, do it):** confirm the REST route still exists and what it expects
   (`rg "<url-fragment>" backend/api/`), and that it's still UI-wired (`rg "<fn>" frontend/src/api/`).
   A dead route is a *delete* candidate, not a wrap candidate — route it to `issues_ledger.md`.
4. **Decide the shape** (wrapper / new module / service+oracle push) and **pick the validation form**
   from the primary-metric list BEFORE writing code. The oracle is the acceptance test — write it first
   where practical (it should fail until the wrapper works).
5. **Build:** the wrapper in `headless_build.py` (or the new headless module / `backend/core` fn) +
   the validation augment (a direct unit/integration test in `tests/`). No god-file growth.
6. **Gate:** `just test` green — cite pass count, flag any *drop*. `just lint` clean on touched files.
   A feature without its validation augment does not ship.
7. **One item per commit** (`feat(automation): headless <op> + <oracle>`). Commit only when the user asks.
8. **Update the ledgers:** check the box here, add a metrics row to `design_automation_log.md` **with the
   mandatory justification line**, and **overwrite** `## Next-session handoff` (≤8 lines).
9. **Route what you found:** a bug → `issues_ledger.md` dossier. A genuinely UI-only op that can't be
   headless'd (pure pixel-gesture, no coord route) → push an `MV-N` row to `manual_validation_debt.md`
   (it's validated by hand, not automated). A stuck item → the log's difficulties ledger with *why*.

**Don't:** add operation logic to `crud.py`/`assembly.py`/`main.js`. Touch `_PHASE_*` or the mutation
contract (`mutate_and_validate`/`set_design_silent`/`snapshot`). Reason geometrically about crossover
placement (mechanical rules only — `feedback_crossover_no_reasoning`). Change a route URL.

---

## Single-line invocation

- **Slash command:** `/automate-feature` (optionally `/automate-feature AF-3` to name an item).
  Skill at `.claude/skills/automate-feature/SKILL.md` — loads this map + the log, picks the handoff's
  next item, re-derives its surface, and runs the protocol.
- **Plain prompt:** *"Run a design-automation feature loop"* / *"Work the next AF item."*

---

## Next-session handoff

_Living pointer — each session overwrites this (step 8). **AF-13 Phase 3 — declarative constraint spec + pure
REPORTING checker SHIPPED 2026-06-18.** A constraint is now a declarative object a closed loop can branch on:
`parse_constraint_spec(spec)` validates `{measure:"end_to_end", landmarks:[a,b], target_nm, tol_nm,
min_confidence?}` at PARSE time (raises `ConstraintSpecError` before any relaxation) and
`check_relaxed_constraint(constraint, read_flexibility_map_dict)` REPORTS `{met, status∈{met,unmet,inconclusive},
measured_nm, n_frames, min_confidence, confidence}` — both PURE in `backend/core/oxdna_health.py`, reusing P2's
`measure_end_to_end`. The REPORTER counterpart to P2's *asserter* (`assert_relaxed_measurement`). **The
load-bearing invariant: `met` is NEVER True below `min_confidence`** — a within-tolerance value on a 10-frame run
reports `inconclusive`, not `met` (red-tested). Coverage unchanged (no route wrapped — pure core + composition
over the P2 read path). Full suite **2574 passed / 55 skipped** (P2 baseline 2552). Next: **AF-13 Phase 4 —
iterate-until-met loop** (the capstone), which branches on this checker's `status`._

**▶ HARNESS NOW AVAILABLE (AF-13 P3, use it — do NOT rebuild):**
- `from backend.core.oxdna_health import parse_constraint_spec, check_relaxed_constraint, ConstraintSpecError`.
  `parse_constraint_spec(spec)` → normalised `{measure, landmarks:[(hid,bp,dir),…], target_nm, tol_nm,
  min_confidence}` (landmarks → tuples, direction enum→str; **idempotent** on its own output; `min_confidence`
  defaults to `RMSF_PRELIM_FRAMES`=50). `check_relaxed_constraint(constraint, relaxed_output)` takes a RAW or
  parsed constraint (it re-parses) + the dict `hox.read_flexibility_map` returns (`{ready, positions,
  confidence:{n_frames,…}}`) → the verdict dict. **It is PURE — `backend/core` takes the already-read dict and
  never imports `headless_oxdna_build`** (the api read-wrapper); the *caller* fetches the map then hands it in.
- **The three statuses:** `met` (n_frames ≥ min_confidence AND |measured−target| ≤ tol), `unmet` (enough frames,
  out of tol), `inconclusive` (too few frames OR no production mean structure yet). `measured_nm` is still
  reported when positions exist (so a loop watches convergence) but `met` follows `status` strictly.
- **GOTCHAS banked:** (1) the confidence gate is the whole point — AF-13 P4's iterate loop MUST branch on
  `status`, never on `measured_nm` alone, or it will converge on a noisy low-frame estimate. (2) tolerance
  boundary is inclusive (`<=`); float-exact test values (target 4.5/tol 0.5 on a 5.0 nm measurement) avoid the
  `4.6 → 0.40000…036 > 0.4` trap. (3) adding the next `measure_*` kind = add a `measure_*` fn next to
  `measure_end_to_end`, add the name to `_CONSTRAINT_MEASURES`, and add a dispatch arm in `check_relaxed_constraint`
  (currently it calls `measure_end_to_end` directly since parse pins the only measure). (4) the checker is NOT
  wired into `build_spec.py` yet — P4 (or a small grammar-growth pass) lowers a design `constraints` block to it.

**▶ HARNESS NOW AVAILABLE (full-sequencing feature, use it — do NOT rebuild):**
- `from backend.api import headless_build as hb` → `hb.full_sequence(scaffold_name="M13mp18", *, custom_sequence=,
  strand_id=)` fully sequences a **routed single-scaffold** origami (assigns the scaffold sequence to every scaffold
  strand, then WC-complements every staple → zero undefined bases, export/oxDNA ready). `hb.assign_staple_sequences()`
  is the bare WC-complement-staples wrapper (422s without a scaffold sequence). **Needs `auto_scaffold` first** on a
  raw bundle (one scaffold strand per helix won't cover the staples — the staple complement is taken from the single
  *active* scaffold). Coverage **35 → 36** (`assign_staple_sequences` flipped).
- `from tests.automation_harness import assert_fully_sequenced` — `(design, *, require_wc=True) → n_WC_checked`:
  zero undefined bases (the `create_oxdna_job` / export gate) AND every scaffold-paired staple base is the WC
  complement of its scaffold base (checked independently of the assignment code). This is the cleaner way to get a
  sequenced design for the AF-13 oxDNA fixture than the `_sequence_for_oxdna` test helper. Can-go-red: unsequenced →
  "undefined"; wrong base → "WC complement".

**▶ HARNESS NOW AVAILABLE (AF-13 P1, use it — do NOT rebuild):**
- `from backend.api import headless_oxdna_build as hox`. **One-call:** `hox.run_relaxation(design, workspace, *,
  timeout=30.0, min_bp_retained=0.0, backend="CPU", mc_steps/md_relax_steps/equil_steps=100, …) → terminal
  OxdnaJob` (create no-autostart → start → poll). **Lower-level:** `create_job` (returns dict, read `["job_id"]`)
  / `start_relaxation(job_id, ws)` / `append_production(job_id, ws, *, steps)` / `read_relaxed_positions(job_id,
  ws)` (drives the display route → `{ready, positions, n_positions}`) / `wait_for_terminal(job_id, ws, *,
  timeout)`. Each route wrapper temporarily redirects `routes_oxdna._WORKSPACE_DIR` (a `_use_workspace` cm) and
  `create_job` binds the design into a scratch doc (`_scratch_design`) so nothing touches the real workspace /
  active design. Route handlers are `async` → driven via `asyncio.run`.
- `from tests.automation_harness import assert_relaxed_geometry_recovered` — `(job, design, workspace, *,
  expected_count=None)`: status `completed` + display reads back exactly one finite position per design
  nucleotide, every key a real `(helix_id, bp, dir)`. Returns the display dict. Can-go-red: non-completed job →
  "did not reach completed"; wrong count → "expected …".
- **GOTCHAS banked:** (1) **the design must be FULLY SEQUENCED** — `create_oxdna_job` 400s on any undefined base;
  reuse `_sequence_for_oxdna` (M13 + WC complements) from `test_oxdna_relaxation.py`. (2) **The mock binary does
  NOT relax** (it copies conf→last_conf), so pass `min_bp_retained=0.0` or the bp-retention gate fails the job
  (mirrors `test_runner_end_to_end`). Real GPU runs raise it back to ~0.5. (3) `get_oxdna_display` is a **GET**
  (read-only) → correctly absent from the *mutation* coverage audit; it's pinned instead by the
  import-identity test. (4) Reuse the `mock_oxdna` fixture by copying its 6-line body from `_MOCK_OXDNA` (a
  cross-module pytest fixture import trips ruff F811).
- **The Three-Layer Law is the spine of the rest of Tier 5:** oxDNA output is read back as a Physical-layer
  position map and **never written into `Design`**. AF-13 P1 exposes ONLY the read path. Phase 4's iterate loop
  will EDIT topology (a knob) and RE-RELAX — it must never write the relaxed coords back.

**▶ HARNESS NOW AVAILABLE (AF-13 P2, use it — do NOT rebuild):**
- `from backend.core.oxdna_health import measure_end_to_end` — pure `(positions, landmark_a, landmark_b) →
  distance_nm`. `positions` = the per-nucleotide list from `production_rmsf` (mean structure) OR the display
  readback; each landmark = a `(helix_id, bp_index, direction)` tuple (direction may be the `Direction` enum or
  its string value — normalised). Raises on empty map / identical landmarks / absent landmark (no silent 0/NaN).
  This is the reusable `measure_*` primitive — add `measure_radius_of_gyration` / `measure_inter_helix_spacing`
  / `measure_segment_angle` here the same way for the other constraint kinds.
- `from backend.api import headless_oxdna_build as hox` → `hox.read_flexibility_map(job_id, ws)` drives the REAL
  `GET /oxdna/jobs/{id}/rmsf` → `{ready, positions (mean backbone xyz per nuc), confidence:{n_frames, rel_error,
  preliminary}, …}`. **Needs a prior `append_production` run** (returns `{ready:False}` until production frames
  exist). The mean cancels thermal noise; prefer it over `read_relaxed_positions` (single frame) for measurement.
- `from tests.automation_harness import assert_relaxed_measurement` — `(job, measure_spec, target_nm, tol_nm, *,
  workspace, min_confidence=RMSF_PRELIM_FRAMES)`: status-completed + reads the mean structure + **confidence gate**
  (≥ `min_confidence` pooled frames else "INCONCLUSIVE"-raise) + measured ∈ [target±tol]. `measure_spec =
  {"measure":"end_to_end","landmarks":[a,b]}`. Returns `{measured_nm, target_nm, tol_nm, n_frames, confidence}`.
- **GOTCHAS banked:** (1) **The shared `_MOCK_OXDNA` writes NO `trajectory.dat`** → the rmsf route has no frames
  → `{ready:False}`. AF-13 P2's tests use a purpose-built `_MOCK_OXDNA_TRAJ` (in `test_headless_oxdna_build.py`)
  that also emits a multi-frame `trajectory.dat` (frames = `max(1, steps//100)`, the input conf repeated). Reuse
  it for any oxDNA test needing a mean structure. (2) **`ProductionRequest.steps` has a 1000 minimum** — to get a
  *few*-frame (preliminary/low-confidence) run pass `steps=1000` (→10 frames), not <1000 (pydantic 422). (3) The
  mock is identity (last_conf == input conf), so the relaxed mean reproduces the **design's own** end-to-end
  (~0.002 nm gap) — the absolute target in the test is `measure_end_to_end(_geometry_for_design(design), a, b)`;
  a real GPU run moves atoms so the target would be the user's desired distance. (4) `get_oxdna_rmsf` is a GET →
  pinned by `hox._route_get_rmsf is routes_oxdna.get_oxdna_rmsf`, NOT the mutation-coverage count.

**▶ NEXT — AF-13 Phase 4 (the capstone): iterate-until-met loop.** All the pieces now exist — compose them:
given a PARAMETRIC design knob (a bend curvature via `hb.add_bend`, a loop/skip count, a length) + a constraint
spec, loop: build design → relax + production (`hox.run_relaxation` + `append_production`) →
`hox.read_flexibility_map` → `check_relaxed_constraint` → branch on `status` (NEVER on `measured_nm` alone — the
P3 gotcha) → if `unmet`, adjust the knob and re-relax; if `inconclusive`, run a longer production; stop at `met`
or budget exhausted. **Three-Layer Law (ASK-FIRST if any doubt):** vary TOPOLOGY (the knob edits `Design`),
re-derive geometry, relax physics, READ the relaxed measurement — never write relaxed coords back. **Augment:**
on the identity mock the measurement can't move, so a real convergence demo needs either a knob that changes the
*design* end-to-end (a length/bend the geometry kernel reflects, measured pre-relax) or a stub relaxer that
perturbs toward the target; the oracle is "the loop reaches `met` in ≤N iterations AND each step's verdict came
from `check_relaxed_constraint` (confidence-gated)". Likely a NEW `headless_oxdna_build` loop driver +
`assert_converges_to_constraint` harness oracle. Heavier than P3; its own session.

**▶ Stragglers (unchanged):** `polymerize_periodic` (single-part `is_periodic_seam` + `derive_periodic_delta`
Kabsch oracle — needs a periodic-seam fixture); `bind_overhangs` ASSEMBLY spec op (DEFERRED pending
overhang-binding firming — do NOT build yet).

**▶ HARNESS NOW AVAILABLE (AF-16, use it — do NOT rebuild):**
- `from backend.api import headless_build as hb` → `hb.add_cluster(name, helix_ids, *, domain_ids=(), log=False)`.
  `log=True` appends a `ClusterCreateLogEntry` (`feature_type="cluster_create"`, fields `cluster_id`/`name`/
  `helix_ids`/`domain_ids`) to `design.feature_log` with the same cursor-truncation as `update_cluster`'s commit+log.
  Default `log=False` — backward-compatible, so the capstone + all existing cluster tests are unaffected.
- `from tests.automation_harness import assert_cluster_in_feature_log` — `(design, cluster_id, *,
  expect_helix_ids=None)`: exactly one `cluster_create` entry for `cluster_id`, helix set == the live cluster's
  (or `expect_helix_ids`), name matches. **canonical_topology is BLIND to clusters** (the loop/skip / deformation /
  pose blind-spot, 4th time), so this entry is the ONLY proof a grouping persisted — call it on a `roundtrip_nadoc`
  result to pin `.nadoc` survival. Can-go-red: unlogged build → no entry → raises.
- **GOTCHA banked:** `add_cluster` uses `design_state.set_design` (undo-pushing), NOT `mutate_and_validate` — the
  log append rides inside the single `copy_with(...)` that already builds `cluster_transforms`, so it's one undo
  step. The cursor truncation (`feature_log[:cursor+1]`) matters only if a logged `add_cluster` follows an undo;
  mirror `update_cluster` exactly and it's correct.
- **Follow-up (optional):** the capstone `build_parallelogram` clusters its 4 bars with `log=False`; switching to
  `log=True` would make its generated feature log truly complete (the AF-16 motivating use case) — cosmetic, the
  linkage oracle doesn't read the log.

**▶ HARNESS NOW AVAILABLE (AF-14 P3, use it — do NOT rebuild):**
- `from backend.core.cluster_obb import recommend_hinge_joints` — `(design, cluster_id, *, anchor="corner",
  axial_tol_deg=20.0, target_rom_deg=None, …) →` all 12 OBB edges ranked best-first
  (`{edge, edge_length, angle_to_axis_deg, is_axial, rom_deg, axis_origin, axis_direction}`). Priority:
  **non-axial first → longest edge → ROM tiebreak.** `axis_origin` honours `anchor`; axial (`w`) edges demoted
  to the tail but still present (so a caller can see them / a red-test can find one).
- `hull_prism_axis(…, edge=key, anchor="corner")` + `hb.place_cluster_joint(cid, edge=key, anchor="corner")` —
  `anchor` defaults to `"midpoint"` (backward-compatible; the capstone + all existing tests use it). `"corner"`
  stores the edge's `−axis` endpoint as the anchor; **same hinge line** (so `assert_joint_on_hull_corner(…,
  edge=key)` still passes — proven by `test_place_cluster_joint_corner_anchor_stays_on_edge`).
- `from tests.automation_harness import assert_recommended_hinge` — `(design, cluster_id, *,
  recommendations=None, axial_tol_deg=20, tol_nm=0.05, length_tol_nm=0.1)`. Re-measures on the independent OBB
  that the #1 hinge is non-axial + longest-non-axial + corner-anchored; pass `recommendations=` a hand-built
  list to drive the can-go-red guards.
- **GOTCHA banked:** for a real edge a corner and the midpoint are half-an-edge-length apart, so the
  corner-anchor check (`d_corner < tol_nm`) ALSO catches a midpoint anchor (it's far from every corner) — there
  is no separate "is it the midpoint" assertion (it would be unreachable). On a 2×6 SQUARE bar the wide `u`-edge
  (6 cols) is the top hinge; `v` (2 rows) second; the 4 axial `w`-edges last.
- **Follow-up (optional, not blocking):** the capstone's `build_parallelogram` still hinges on the axial
  `w`-edge (`_SIDE_EDGE` in `test_parallelogram_linkage.py`) — a barrel-roll. Re-pointing it at the recommended
  cross-section edge would make the demo use the AF-14-P3 rule, but it's cosmetic (the linkage oracle is
  direction-agnostic).

**▶ AF-16 — headless cluster creation + a loggable `cluster_create` feature-log entry.** `add_cluster` builds the
cluster but emits NO feature-log entry (no `ClusterCreateLogEntry` type exists), so a design's construction
history can't record "create the bars." Needs a NEW Pydantic model (in `models.py`, added to the
`FeatureLogEntry` union) + route wiring + `hb.add_cluster(log=…)`. Heavier than AF-14 P3 (a real model + union
change, not a pure selector). Closes the last gap in the generated 4-bar part's feature log. See the AF-16 entry.

**▶ AF-11 P2 design grammar DONE — the bulk-routing + apply_loop_skips ops are built + validated.** 4 new design
ops in `build_spec.py` (`auto_scaffold {op,seamless}` / `auto_crossover {op}` / `full_autostaple
{op,scaffold_name,custom_sequence,strand_id}` / `apply_loop_skips {op}`, all NON-primordial) + 4 dispatch branches
in `headless_spec_build.py` driving the real `hb.*` wrappers. **Oracle split (the AF-11-P2 lesson again):**
`assert_spec_matches_calls` is LOAD-BEARING for the 3 routing ops (they add strands the fingerprint sees — a dropped
op diverges from the hand build) but BLIND to `apply_loop_skips`' baked marks (outside the strand graph), so that op's
load-bearing pin is the AF-3 per-helix `geometric_nucleotide_count` conservation (`Δgeom == 2 × net marks`).
**GOTCHA banked:** `auto_crossover` ALONE leaves staples nicked at crossovers → `validate_design` FAILS → you cannot
`assert_roundtrip_stable` on a scaffold+crossover-only design; the round-trip target must be the COMPLETE
`full_autostaple` build (which breaks+merges into a valid design). `apply_loop_skips` needs SQUARE + crossovers
(`auto_crossover` provides them); a bare-bundle `apply_loop_skips` 400s (pinned by a red-test).

**▶ NEXT — pick one (validation-first; Tier-2 cluster arc + AF-11 P2 grammar + AF-13 P1/P2/P3 oxDNA are done):**
- **AF-13 Phase 4 — iterate-until-met loop (the capstone)** — the recommended next item (top-of-file NEXT).
  Composes `check_relaxed_constraint` (P3, branch on `status`) + `run_relaxation`/`append_production`/
  `read_flexibility_map` (P1/P2) + a parametric topology knob (`hb.add_bend`/loop_skip/length) into a closed
  build→relax→measure→adjust loop. Three-Layer Law: vary topology, read physics, never write relaxed coords back
  (ASK-FIRST if any frame/sign doubt). Its own session.
- **Stragglers:** `polymerize_periodic` (single-part `is_periodic_seam` + `derive_periodic_delta` Kabsch oracle —
  needs a periodic-seam fixture built via route-for-polymerization); `bind_overhangs` ASSEMBLY spec op (DEFERRED
  pending overhang-binding system firming — see below, do NOT build yet).

**▶ HARNESS NOW AVAILABLE (AF-14 P2, use it — do NOT rebuild):**
- `from backend.core.cluster_obb import obb_sweep_rom, cluster_range_of_motion, rank_joint_candidates`.
  `cluster_range_of_motion(design, cluster_id, axis, *, obstacles=None, min_angle_deg=-180, max_angle_deg=180,
  pad=HELIX_RADIUS, step_deg=2.0) → ROM_deg` — the anchored cluster swings (others static); ROM = total
  two-sided free swing (θ⁺+θ⁻) about the world `axis=(origin,direction)` (use `hull_prism_axis(...,edge=…)`),
  clamped to the limits, OBBs padded by helix radius so contact is rim-to-rim. `obb_sweep_rom(...)` is the pure
  OBB-only core (no design — hand it synthetic `OBB`s). `rank_joint_candidates(design, cluster_id, *,
  target_rom_deg=None)` → the 12 OBB **edges** ranked by ROM desc (door-jamb: interface edge swings least,
  away-facing edge swings free), optional `target_rom_deg` filter.
- `from tests.automation_harness import assert_range_of_motion` — `(design, cluster_id, axis, expected_deg, *,
  tol_deg=2.0, min_angle_deg, max_angle_deg, pad=None, step_deg)`. Direction-AGNOSTIC magnitude; physical-bound
  guard + can-go-red on a wrong angle.
- **GOTCHA banked:** SQUARE bars are LONG+THIN (a 2×3 bar OBB ≈ u-half 2.25 / v-half 1.12 / w-half 5.34 nm).
  Hinging about a vertical `("w",…)` edge sweeps only the small u–v cross-section, so the swing *reach* is ~the
  u-width (~4.5 nm) — an obstacle must be within that to register contact (an 8 nm gap reads 360°). The
  contact-sensitive hinge is the edge **nearest** the neighbour (`_near_w_edge` in the test): one swing sense
  drives A's bulk straight into B, ROM grows monotonically with the gap (≈156°→275° over gaps 1–4 nm).

**▶ NEXT — THE CAPSTONE (its own session): the headless 4-bar parallelogram, the first headless kinematic
mechanism.** All pieces now exist — compose them: extrude 4 rectangular bars (`hb.create_bundle`/`hb.extrude`)
→ `hb.add_cluster` each → `hb.align_cluster_edge` (AF-15 P2) into a parallelogram → 4 revolute joints via
`hb.place_cluster_joint` (AF-14 P1, edge mode at the corners) → assert it's a working 1-DOF mechanism via
`cluster_range_of_motion`/`assert_range_of_motion` (AF-14 P2) at each hinge. **ASK-FIRST** the same body/sense
question per joint if any swing convention is ambiguous, but the ROM magnitude check itself is direction-agnostic.
Mind the GOTCHA above: bars must be rectangular (square footprint → `cluster_obb` raises) and hinge geometry must
keep the swing reach in range. This is the AF-12 linkage-mobility (Grübler) demo the per-joint geometry was built
toward — the validation is "the assembled mechanism has the expected DOF / each joint's ROM is finite-and-nonzero."

**▶ HARNESS (AF-14 P1, use it — do NOT rebuild):**
- `from backend.api import headless_build as hb` → `hb.place_cluster_joint(cluster_id, *, edge=(axis,s1,s2) |
  corner=(su,sv,sw)+face=(axis,sign), name=…, min_angle_deg=…, max_angle_deg=…)` — places a revolute joint
  anchored on a named OBB feature; drives the real `add_joint` route (covered). Read the new id from
  `design.cluster_joints[-1].id`.
- `from backend.core.cluster_obb import hull_prism_axis` — pure `(design, cluster_id, *, edge | corner+face) →
  (origin, direction)`. EDGE mode = hinge along the OBB edge (origin=midpoint, dir=edge line). CORNER mode =
  point pivot at the corner, dir=`OBB.face_normal((axis,sign))` (NEW method on `OBB`). The corner must lie on the
  named face (it validates). REUSES `cluster_obb` so the axis tracks any pose.
- `from tests.automation_harness import assert_joint_on_hull_corner` — `(design, joint_id, *, edge | corner+face,
  tol_nm=0.05, tol_deg=1.0)`. Re-derives the joint's world axis from its cluster-LOCAL storage +
  `_local_to_world_joint` (so it survives the route's world→local→world trip on a POSED cluster — the local-frame
  round-trip test proves this), recomputes the OBB, asserts collinear-with-edge / through-corner.
  Direction-AGNOSTIC. Can-go-red on a different edge/corner.

**▶ NEXT — AF-14 Phase 2: `cluster_range_of_motion` + `rank_joint_candidates` (the geometry-aware selector).**
`cluster_range_of_motion(design, cluster_id, axis, *, obstacles=all_other_clusters) → ROM_deg` via **swept OBB–OBB
SAT bisection** in `cluster_obb.py` (the swept-OBB intersection is the ONE genuinely new geometry to build — the
OBB enumerator + `hull_prism_axis` already exist). `rank_joint_candidates(design, cluster_id, *, target_rom_deg=…)`
enumerates `OBB.edges()`/corners and ranks by ROM. **Oracle:** `assert_range_of_motion(design, cluster_id, axis,
expected_deg, *, tol_deg)` — on a fixture with a known obstacle at a known offset the swing-to-contact matches the
analytic angle, with TWO can-go-red guards (no-obstacle → full angular limit; obstacle moved into the path strictly
reduces it). Magnitude → direction-AGNOSTIC. **ASK-FIRST before building** (per CLAUDE.md): which cluster is the
moving body vs. the static frame, and the swing *sense* (which limit is +/−) — a directionality decision, don't
guess. The ROM magnitude is direction-agnostic; the body/sense choice is not.

**▶ THEN the capstone** (its own session, after Phase 2): build the **4-bar parallelogram** headlessly — extrude 4
bars → `hb.add_cluster` each → `hb.align_cluster_edge` into a parallelogram (already works) → 4 revolute joints via
`hb.place_cluster_joint` (now available) → assert 1-DOF ROM via `cluster_range_of_motion`. First headless kinematic
mechanism.

**▶ GOTCHAS BANKED from AF-14 Phase 1 (read before Phase 2):**
- `cluster_obb` RAISES on a square footprint (ambiguous u/v, in-plane eigenvalue ratio < 1.10) and on < 2 helices —
  ROM fixtures must be **rectangular** (the tests use a 2×6 SQUARE grid; a single bar clustered whole).
- The OBB `half`/`axes`/`center` bound the helix **axis endpoints**, NOT the DNA surface. Phase 2's swept-OBB
  clearance probably wants a **surface pad** (helix radius) so two bars touching rim-to-rim register contact before
  their axis boxes overlap — decide the pad when you build the SAT.
- A `ClusterJoint` does NOT move helices, so `cluster_obb(before) == cluster_obb(after)` across a joint placement —
  the OBB is stable to anchor against. For ROM, the moving body's OBB is *swept*, the obstacle OBBs are static.

**▶ GOTCHAS BANKED from AF-15 Phase 2 (read before AF-14):**
- The OBB cross-section frame uses **PCA**, NOT `deformation._initial_cross_section_frame` (that one snaps u/v to
  WORLD axes by the dominant tangent → not equivariant → edge keys jump after a pose). The PCA frame is
  equivariant; its sign anchor is **positional** (first sorted-id helix with a clear u-projection), NOT an
  argmax over offsets — a value-argmax ties on the 4 symmetric corners and float-rounding flips the frame after a
  rotation (this bit once; the equivariance test catches it). **`cluster_obb` RAISES on a square footprint**
  (ambiguous u/v, in-plane eigenvalue ratio < 1.10) and on < 2 helices — AF-14 fixtures must be **rectangular**
  (the tests use a 2×3 / 2×6 SQUARE grid).
- `OBB.half`/`axes`/`center` bound the helix **axis endpoints** (not the DNA surface) — fine for edge alignment
  and joint placement; AF-14's ROM may want a surface pad (helix radius) for true clearance — decide then.

**▶ DEFERRED — `bind_overhangs` (AF-11 Phase 2 last sub-op): PENDING FURTHER DEVELOPMENT.**
Per user (2026-06-17): **overhang binding still needs work in general** before it's ready to expose to users
through the build-spec grammar — do NOT add the `bind_overhangs` spec op until the underlying overhang-binding
system is firmed up. The relations cluster (`gear`/`belt`/`polymerize`/`bind_overhangs`) is otherwise COMPLETE:
**`gear` + `belt` + `polymerize` SHIPPED**; `bind_overhangs` parked here. When it's revived, the plan below holds.
Drive `hab.bind_overhangs(inst_a, inst_b, *, overhang_a_id, sub_domain_a_id, overhang_b_id, sub_domain_b_id,
binding_mode=…)` (AF-9 overhang-binding wrapper). **Spec shape (proposed):**
`{"op":"bind_overhangs","instance_a":"<ref>","instance_b":"<ref>","overhang_a":…,"sub_domain_a":…,
"overhang_b":…,"sub_domain_b":…,"binding_mode":…}` — it references two prior `add_part` instance `ref`s (the
*instance* namespace `defined`, NOT the joint `ref` namespace gear/belt/polymerize use — bind couples
overhangs, not joints). **The fixture gotcha (TWO traps):** (1) each part design needs `grid_pos` SET on its
helices (the AF-5 `grid_pos=None` TypeError trap) AND an `OverhangSpec` (which auto-populates one sub-domain) —
the inline `_BEAM_SPEC`/`make_6hb_design()` fixtures have NEITHER, so this sub-op needs a NEW part-spec fixture
carrying overhangs (or a `bundle` + an overhang-extrude design op the grammar does NOT have yet — likely a NEW
part-builder fixture in the test, not a new grammar op). (2) the spec must surface the runtime
`(overhang_id, sub_domain_id)` of each part — these are generated at build time, so the driver must look them up
on the built part design, not hard-code them; decide whether the spec names sub-domains by index/label or the
driver resolves "the part's sole overhang". **Oracle:** `assert_binding_resolves(assembly, binding_id, *,
require_cross_part=True)` is the LOAD-BEARING one — `canonical_assembly` (5-tuple, fingerprints `overhang_bindings`)
catches a dropped/rewired binding, but `canonical_topology` is BLIND to a design's overhangs/sub-domains, so a
round-trip that regenerated a sub-domain id while the binding kept its stale ref slips past the fingerprint —
only `assert_binding_resolves` catches that. So pair `assert_spec_matches_calls` (structural) with
`assert_binding_resolves` (referential integrity, the real proof).
**Discipline:** the driver DRIVES the real `hab.*` wrappers — never re-implement — so coverage stays flat
(composition sugar, 32; `test_spec_build_adds_no_coverage` guards it). **PICK THE ORACLE BY WHAT THE OP CHANGES (the
load-bearing AF-11-P2 lesson, confirmed seven times now):** `assert_spec_matches_calls` is the golden pin ONLY when
`canonical_topology`/`canonical_assembly` can see the op's effect — load-bearing for strand-graph ops AND for
fingerprinted top-level assembly relations (gears/belts/joints/instances/polymer-chains/bindings, since AF-9),
VACUOUS for overlays outside it (`loop_skip`→`geometric_nucleotide_count`, `bend`/`twist`→`assert_deformation_angle`).
For relations ALSO pair it with the kinematic/semantic oracle (`assert_gear_ratio` / `assert_polymer_chain` /
`assert_binding_resolves`) — the fingerprint catches a dropped/rewired relation, the semantic oracle catches one
that's present-but-doesn't-work. **NEW lesson from polymerize:** NOT every relations sub-op needs the revolute gate —
polymerize takes a SINGLE seed mate of ANY joint_type, so its referential-integrity branch omits the gate gear/belt
enforce (`test_assembly_spec_polymerize_allows_rigid_seed` pins that). `bind_overhangs` references the *instance*
namespace, not the joint one — a third referential-integrity shape.
**HOW:** mirror this session — `_ASSEMBLY_OP_KEYS` entry + parse branch + referential-integrity (resolve the right
ref namespace) + dispatch branch + grammar-rejection tests + a driver test using the op's own oracle.

**▶ ~~DEFERRED~~ DONE 2026-06-18 — `apply_loop_skips` (design op).** Shipped alongside the `auto_scaffold`/
`auto_crossover`/`full_autostaple` cluster (as planned): `auto_crossover` now produces the cross-helix domain
transitions its route demands, so a SQUARE `bundle → auto_scaffold → auto_crossover → apply_loop_skips` spec bakes
the periodic-skip pattern, pinned by the AF-3 per-helix `geometric_nucleotide_count == 2×net_marks` conservation
check (`test_apply_loop_skips_spec_honors_marks_per_helix`, mirroring
`test_apply_deformations_geometry_honors_marks_per_helix`). A `test_apply_loop_skips_spec_requires_crossovers`
red-test pins that the op runs the real route (400s on a bare bundle).

**▶ STRAGGLER (still open, its own session) — `polymerize_periodic`.** The SINGLE-part `is_periodic_seam` path
with the `derive_periodic_delta` Kabsch oracle was NOT built: it needs a part carrying `is_periodic_seam=True`
forced ligations the inline `make_6hb_design()` fixtures don't have. Build one headlessly via the
route-for-polymerization op first, then assert each copy sits at `T_seed @ derive_periodic_delta(design)^k`.

**▶ HARNESS NOW AVAILABLE (AF-11, use it):** `from tests.automation_harness import assert_spec_matches_calls`.
`assert_spec_matches_calls(build_from_spec, build_by_hand, *, kind="design"|"assembly")` — the faithful-façade /
golden-pin oracle: asserts a spec build produces the SAME `canonical_topology` (design) / `canonical_assembly`
(assembly) as the equivalent hand-call wrapper sequence, with a non-emptiness guard so it can't pass vacuously.
Builders: `from backend.api import headless_spec_build as hs` → `hs.build_design(spec)` / `hs.build_assembly(spec)`
(both parse → drive real wrappers in a scratch session → standalone deep copy; raise `BuildSpecError` at PARSE
time on a malformed spec). Parser: `from backend.core.build_spec import parse_design_spec, parse_assembly_spec,
BuildSpecError` (pure, HTTP-free — test grammar/rejection here without any build). Design helices are referenced
by `grid_pos` `[row,col]`; assembly instances by spec `ref` key; a part = a nested design spec under `parts`.

**▶ STRAGGLER (still open, its own session) — `polymerize_periodic`.** The SINGLE-part `is_periodic_seam` path
with the `derive_periodic_delta` Kabsch oracle was NOT built: it needs a part carrying `is_periodic_seam=True`
forced ligations the inline `make_6hb_design()` fixtures don't have. Build one headlessly via the
route-for-polymerization op first, then assert each copy sits at `T_seed @ derive_periodic_delta(design)^k`.

**▶ HARNESS NOW AVAILABLE (AF-10, use it):** `from tests.automation_harness import assert_instances_on_grid,
assert_instances_on_ring`. `assert_instances_on_grid(assembly, rows, cols, *, pitch, row_pitch=None, plane="XY",
tol_nm=0.01, instance_ids=None)` — reads the placed instance origins and asserts they form the exact rows×cols
lattice (count, even spacing == pitch on each axis, every cell filled), id-independent, with a `pitch>min_pitch`
non-degeneracy guard. `assert_instances_on_ring(assembly, n, *, radius, plane="XY", center=(0,0,0), tol_nm=0.01,
angle_tol_deg=1.0, instance_ids=None)` — every origin at `radius` from `center` + even angular step `360°/n`,
with a load-bearing `radius>min_radius` guard (radius=0 stacks all at centre → vacuous). Builders:
`hab.place_grid(design, rows, cols, *, pitch, row_pitch=None, plane="XY", center=False)` /
`hab.place_ring(design, n, *, radius, plane="XY", start_angle_deg=0.0, center=(0,0,0))` — pure-translation
placement (identity orientation; radial *facing* deferred as an ASK-FIRST orientation convention). Both are
construction sugar over `add_inline_instance` (NO route wrapped → coverage unchanged). Pure math in
`backend/core/instance_layout.py` (`grid_translations` / `ring_translations`, plane in {XY,XZ,YZ}). Keep layout
counts ≤6 if you round-trip (the >6-'full'→cylinders downgrade still applies).

**▶ HARNESS NOW AVAILABLE (AF-9 overhang-bindings, use it):** `from tests.automation_harness import
assert_binding_resolves`. `assert_binding_resolves(assembly, binding_id, *, require_cross_part=True)` — a
referential-integrity oracle for cross-part `AssemblyOverhangBinding`s: loads each endpoint's part design with
the route's own `_load_design_from_source` and asserts both `(overhang_id, sub_domain_id)` refs resolve, plus a
non-degenerate / cross-part guard. Use it AFTER a round-trip too — it catches the gap `canonical_assembly` can't:
`canonical_topology` doesn't fingerprint a design's overhangs/sub-domains, so a round-trip that regenerated a
sub-domain id while the binding kept its stale ref slips past the structure fingerprint. Builders:
`hab.bind_overhangs(inst_a, inst_b, *, overhang_a_id, sub_domain_a_id, overhang_b_id, sub_domain_b_id,
binding_mode=…, allow_n_wildcard=…)` / `hab.patch_binding(binding_id, *, binding_mode=…)` /
`hab.unbind_overhangs(binding_id)`. `canonical_assembly` now returns a **5-tuple** `(instances, joints, gears,
belts, bindings)` — it fingerprints `overhang_bindings`, so a dropped/rewired binding fails the round-trip oracle.
The overhang fixture needs `grid_pos` set on its helices (the AF-5 `grid_pos=None` TypeError trap) and an
`OverhangSpec` (auto-populates one sub-domain).

**▶ HARNESS NOW AVAILABLE (AF-9 polymerize, use it):** `from tests.automation_harness import assert_polymer_chain`.
`assert_polymer_chain(assembly_before, assembly_after, seed_joint_id, *, count, direction="forward", tol_nm=0.01,
min_delta_nm=0.5)` — the geometric oracle for mate-seeded polymerize. Re-derives the seed mate's repeat
`delta = T_B @ inv(T_A)` from the seed pair's world transforms ALONE (NOT the route's chain helpers → independent,
not a tautology) and asserts the `count−2` new instances form the exact `delta`-power multiset (`delta^k @ T_B`
forward / `inv(delta)^k @ T_A` backward), matched id-independently within `tol_nm`, with a can-go-red guard that
`delta`'s translation > `min_delta_nm` (a stacked seed pair → every copy on the seed → vacuous). Returns the 4×4
`delta`. Builder: `hab.polymerize(joint_id, count, *, direction, additional_instance_ids=…)` — needs a seed mate
between **identical** parts (use the SAME `Design` object for both `add_inline_instance` calls so `_sources_match`
is true, else the route 422s). `canonical_assembly` already fingerprints instances+joints, so a polymerized chain
round-trips through `assert_assembly_roundtrip_stable` unchanged with **no** harness extension (polymerize adds no
new top-level relation list — unlike gears/belts).

**▶ HARNESS NOW AVAILABLE (AF-9 belts, use it):** `hab.define_belt(joint_a_id, joint_b_id, *, radius_a, radius_b,
side_a=…, instance_a_id=…, connector_a_label=…)` (the two joints must already be **revolute** mates, like the gear
fixture). The belt's coupling relation surfaces with the synthetic id `f"__belt__{belt.id}"`; pin it by reusing the
gear oracle — `assert_gear_ratio(before, after, f"__belt__{belt.id}", expected_ratio=radius_a/radius_b)` — which now
searches `_coupling_relations` (gears + belt-derived), so the SAME oracle handles both. `canonical_assembly` now
returns a **4-tuple** `(instances, joints, gears, belts)` — it fingerprints belt_paths, so
`assert_assembly_roundtrip_stable` catches a dropped/rewired belt. When you add the next top-level relation list
(rider chains, polymer groups), extend `canonical_assembly` in the same commit (4th time — see the banked lesson).

**▶ HARNESS NOW AVAILABLE (AF-9 gears, use it):** `from tests.automation_harness import assert_gear_ratio`.
`assert_gear_ratio(assembly_before, assembly_after, rel_id, *, expected_ratio, ratio_tol=0.02, min_angle_deg=2.0)` —
the resolve-invariant for any ratio-coupling relation. Drive ONE side with `hab.drive_joint(joint_id, radians)` (its
PATCH auto-propagates the relation — no separate `resolve()` needed), capture `assembly_state.get_or_404()` as
`after`, and the oracle measures the two coupled bodies' real *instance-transform* rotation magnitudes (via the gear
endpoint sides) and asserts driven/driver = `|expected_ratio|`, with a can-go-red "driver actually rotated" guard.
**Direction-agnostic** (magnitude only — `invert` flips sign not magnitude, so no ASK-FIRST). Builders:
`hab.define_gear(joint_a_id, joint_b_id, *, ratio, invert=False, endpoint_*=…)` (the two joints must already be
**revolute** mates) and `hab.drive_joint(joint_id, value_radians, *, endpoint_side=None, silent=False)`.
`canonical_assembly` now returns a **4-tuple** `(instances, joints, gears, belts)` — it fingerprints gear AND belt
relations, so `assert_assembly_roundtrip_stable` catches a dropped/rewired gear or belt.

**▶ HARNESS NOW AVAILABLE (AF-8, use it):** `from tests.automation_harness import assert_mate_coincident`.
`assert_mate_coincident(assembly, joint_id, *, tol_nm=0.01, min_offset_nm=0.5)` — the two mated connectors are
coincident in world space (uses the SAME `_get_connector_world` machinery resolve uses, on the instance-overridden
design) within tol, with a non-triviality guard (the mated part origins must be separated, else the coincidence is
vacuous — place mate connectors at a non-zero LOCAL offset from their part origins). Builders:
`hab.add_connector(inst_id, label, position, normal)` (LOCAL position/normal) then
`hab.define_mate(child_inst_id, parent_inst_id, *, child_label, parent_label, joint_type="rigid", axis_origin=,
axis_direction=, min_limit=, max_limit=)`. The mate SNAPS the child onto the parent connector at create time
(coincident before resolve too); pass `joint_type="revolute"`+`axis_*` for the AF-9 gear mates. `canonical_assembly`
now keys joints by `(type, conn labels, parent-src, child-src, value)` so a dropped/rewired mate fails the
round-trip fingerprint.

**▶ HARNESS NOW AVAILABLE (AF-7, use it):** `from tests.automation_harness import canonical_assembly,
roundtrip_nass, assert_assembly_roundtrip_stable`. `assert_assembly_roundtrip_stable(build_fn)` = one-line
"assembly validates + survives a real `.nass` import unchanged". `canonical_assembly(a)` = id/order-independent
(instances, joints) fingerprint. `roundtrip_nass(a)` = in-memory `to_json`→`POST /assembly/import` (inline parts
travel inside; no disk). Builder: `from backend.api import headless_assembly_build as hab` →
`hab.assembly_scratch_session()` / `hab.new_assembly()` / `hab.add_inline_instance(design, name=, transform=)` /
`hab.add_file_instance(path, …)` / `hab.resolve()` / `hab.translation(x,y,z)`. Keep test assemblies ≤6 full-rep
instances (import auto-downgrades >6 'full' → 'cylinders', which would change the rep field the fingerprint reads).

**▶ KNOWN GOTCHA found in AF-5 (still relevant if you reuse round-trip):** `make_bundle_deformed_continuation`
(`backend/core/lattice.py:1234`) is the **only** bundle builder that does NOT set `grid_pos` on its new
helix — every other (`make_bundle_design`/`_segment`/`_continuation`) does. So a deformed-continuation helix
has `grid_pos=None`, which (a) makes `canonical_topology` raise `TypeError: '<' not supported between NoneType
and tuple` (it sorts on grid_pos) → **`assert_roundtrip_stable` CANNOT be used on a design with a deformed
continuation** (AF-5 used only the deformed-frame oracle for that reason), and (b) may be *intentional* (a
non-None grid_pos could make the straight-geometry path recompute the helix position from the lattice and
clobber the baked deformed axis coords). **Do NOT just add `grid_pos=(row,col)` — it's a three-layer
directionality question; ASK the user.** Logged as `ISSUE-11` in `issues_ledger.md`.

**▶ HARNESS NOW AVAILABLE (use it, don't re-derive):**
`from tests.automation_harness import canonical_topology, roundtrip_nadoc, assert_roundtrip_stable,
assert_inverse_pair, assert_geometric_length_delta, geometric_nucleotide_count, assert_circular_disc,
assert_on_deformed_frame, assert_deformation_angle, headless_coverage_report`.
- `assert_roundtrip_stable(build_fn)` — one-line "build survives save/load".
- `assert_inverse_pair(start, forward, inverse)` (AF-2) — op∘inverse is topology-identity, with a built-in
  "forward must actually mutate" guard. For add↔delete / nick↔ligate pairs.
- **`assert_geometric_length_delta(start, op, expected_bp_delta, *, helix_id=None, strands_per_bp=2)` (NEW,
  AF-3)** — op changes the geometry kernel's nucleotide count by exactly `expected_bp_delta` bp (× strands/bp).
  Direction-AGNOSTIC (counts how many nucs changed, not which way) → safe on bend/twist apply without sign
  reasoning. Pass `helix_id=` for the strong per-helix conservation check. `geometric_nucleotide_count(d, hid=None)`
  is the bare count. **Caveat banked: `canonical_topology` does NOT see loop/skips** (they're on the helix, not
  the strand graph) — so `assert_roundtrip_stable` can't prove a loop/skip persisted; use the geometric count.
- **`assert_circular_disc(design, requested_radius_nm, *, max_spread_nm=0.5, radius_tol_nm=0.5, helix_ids=None)`
  (NEW, AF-4)** — geometric oracle for parametric disc primitives: reads the *placed* helices' axis spans
  (not a stored field), orders by lattice column, asserts `circularity_spread < max_spread_nm` AND `fit_radius`
  within `radius_tol_nm` of the requested R. Pins the whole radius→geometry path. `helix_ids=` filters to the
  disc helices when other DNA is present.
- **`assert_on_deformed_frame(before, after, source_bp, cells, *, ref_helix_id=None, pos_tol_nm=0.02,
  min_deflection_nm=0.5)` (NEW, AF-5)** — geometric oracle for continuations onto a bent/twisted face: reads
  the *placed* helices' `axis_start`, asserts each lies on the independently re-derived deformed cross-section
  frame at `source_bp` AND that the deformed placement is displaced > `min_deflection_nm` from a straight
  extrude (the can-go-red guard, so it won't pass vacuously on an un-deformed design). Direction-agnostic.
  Returns the max deflection observed. **NB: needs a real bend/twist applied first** (now use `hb.add_bend`).
- **`assert_deformation_angle(design_after, plane_a_bp, plane_b_bp, expected_total_deg, *, ref_helix_id=None,
  angle_tol_deg=1.0, step_bp=1, min_angle_deg=5.0)` (NEW, AF-6)** — geometric MAGNITUDE oracle for bend/twist:
  walks the deformed frame in `step_bp` steps and SUMS each step's relative-rotation magnitude (unwraps past
  180°/360° — a 540° twist reads 540°, not folded), asserts total = `κ×(b−a)` (bend) / total twist, plus a
  can-go-red guard (fails on an un-deformed design). **Direction-AGNOSTIC** (no sign/frame reasoning → safe
  per the ASK-FIRST rule; a signed-curvature oracle was deliberately NOT built). `design_after` is the design
  after the deformation is applied.
- `headless_coverage_report()["uncovered_routes"]` IS the live AF backlog (**207 uncovered / 32 covered** after
  AF-9 overhang-bindings; paths carry the `/api` prefix — match with `.endswith()`). Now lists mostly
  `/assembly/*` layout/overhang-connection routes + the design cluster/extension residue (the AF-10+ gap).
- Headless wrappers now exist: `hb.nick/ligate/delete_strand` (AF-2); `hb.loop_skip(h,bp,delta)` +
  `hb.apply_loop_skip_deformations()` (AF-3, delta=0 removes); `hb.circle_segment(radius_nm)` (AF-4, SQUARE);
  `hb.bundle_deformed_continuation(cells, length_bp, *, source_bp, ref_helix_id)` (AF-5);
  `hb.add_bend(a, b, *, curvature_deg_per_bp, direction_deg)` + `hb.add_twist(a, b, *, total_degrees |
  degrees_per_nm)` (AF-6).

**▶ STRUCTURAL FACTS from the audit (don't re-derive these — they're durable):**
- `headless_build.py` exposes ~19 design ops; **`headless_assembly_build.py` now exists (AF-7/8)** with
  create/place/resolve/import + add-connector/define-mate — the AF-9..AF-10 gap is now gears/belts,
  overhang-bindings/polymerize, and layout helpers.
- Remaining design REST routes lacking a wrapper: overhang rotation, cluster ops (`/design/cluster`),
  strand-end-resize, extensions, scaffold-nick — plus the whole `/assembly/*` surface (AF-7+).
- Pixel-drag-only ops (crossover sprite place/move, domain-shift, strand-end-resize, helix-reorder) DO
  have coord-taking REST routes — they're headless-reachable; only the pixel→bp mapping is UI. The *truly*
  UI-only residue (lasso/select state, gizmo intermediate drags) has no coord route → those go to MV, not here.

**Gotchas banked:**
- The `/design/import` route does post-load processing (migrate split-staple domains, autodetect overhangs,
  backfill sub-domains, recompute flexible connections). `roundtrip_nadoc` drives the *real* route, so a
  build that survives the round-trip survives that processing too — but if a future op's output *isn't*
  idempotent under autodetect, `assert_roundtrip_stable` will (correctly) flag it. That's a real bug to fix
  in the op, not a harness false-positive.
- Coverage is matched by **endpoint function identity**, so a wrapper MUST import the exact route handler
  (`create_bundle as _route_create_bundle`), not re-implement it, to register as covered — which is also
  the anti-passthrough discipline. A wrapper that re-implements logic won't show as covered (good signal).

---

## Backlog (ranked, validation-first). Probed status is the 2026-06-16 audit; verify before claiming.

### Tier 0 — validation foundation (everything leans on it)

- [x] **AF-1 — Headless round-trip validation harness + coverage report.** SHIPPED 2026-06-16.
  `tests/automation_harness.py`: `canonical_topology` (promoted from `test_section_router.py`),
  `roundtrip_nadoc` (real `to_json` → `POST /design/import`, scratch-isolated), `assert_roundtrip_stable`
  (validate → round-trip → validate + fingerprint-equal; injectable `roundtrip` seam),
  `headless_coverage_report` (route-vs-wrapper by **function-object identity** → never stale). 8 meta-tests
  in `tests/test_automation_harness.py`, incl. the load-bearing "oracle fires on a corrupted round-trip".
  Coverage at ship: **11 / 239** design+assembly mutation routes wrapped.

### Tier 1 — design-op headless wrappers (REST exists, wrapper missing; small, high validation value)

- [x] **AF-2 — nick / ligate / delete-strand wrappers** in `headless_build.py` (routes `/design/nick`,
  `/design/ligate`, `DELETE /design/strands/{id}`). SHIPPED 2026-06-16. **Augment:** `assert_inverse_pair`
  (new reusable oracle in `automation_harness.py`) — `nick(h,bp,d)` then `ligate(h,bp,d)` → canonical
  topology unchanged, with a built-in "forward must mutate" guard so it can go red; delete pinned by
  canonical strand-set subtraction + round-trip stable. Coverage 11→14.
- [x] **AF-3 — loop/skip insert + apply-all-deformations wrappers** (routes `/design/loop-skip/insert`,
  `/design/loop-skip/apply-deformations`). SHIPPED 2026-06-16. `hb.loop_skip(h,bp,delta)` +
  `hb.apply_loop_skip_deformations()`. **Augment:** `assert_geometric_length_delta` (new reusable oracle in
  `automation_harness.py`) — pins the topology→geometry conservation law: a loop +1 adds 1 bp of geometry
  (1 nuc/strand), a skip −1 removes 1, delta=0 restores; per-helix scoping proves bulk apply honours each
  helix's marks one-for-one even when the global net cancels. Also pins loop survives `.nadoc` round-trip
  (canonical_topology is blind to loop/skips, so the geometric count is what proves persistence). Coverage 14→16.
- [x] **AF-4 — parametric circle (`circle-segment`) wrapper** (route `POST /design/circle-segment`).
  SHIPPED 2026-06-17. `hb.circle_segment(radius_nm, *, plane, offset_nm, …)` — takes the *radius*, runs the
  same `circle_footprint` analytic the UI mirror uses, drives `add_circle_segment`. **Augment:**
  `assert_circular_disc` (new reusable oracle in `automation_harness.py`) — reads the *placed* helices' axis
  spans (not a stored field) so it pins the full path radius→footprint→route→builder→geometry: `circularity_spread
  < 0.5 nm` + `fit_radius` within 0.5 nm of the requested R. Coverage 16→17.
- [x] **AF-5 — deformed-continuation wrapper** (route `/design/bundle-deformed-continuation`).
  SHIPPED 2026-06-17. `hb.bundle_deformed_continuation(cells, length_bp, *, source_bp, ref_helix_id, plane)`
  — samples the deformed frame via `get_deformed_frame` then POSTs *with* `source_bp` (the replayable path,
  mirrors the UI). **Augment:** `assert_on_deformed_frame` (new reusable oracle in `automation_harness.py`) —
  asserts each appended helix's `axis_start` lies on the independently re-derived deformed cross-section frame
  at `source_bp` AND is displaced > 0.5 nm from where a straight extrude would land (the can-go-red guard).
  Coverage 17→18.

### Tier 2 — deformation by constraint (gizmo-only construction → programmatic; known three-layer-bug area)

- [x] **AF-6 — `add_bend` / `add_twist` by constraint** wrapping the `addDeformation` REST path.
  SHIPPED 2026-06-17. `hb.add_bend(a, b, *, curvature_deg_per_bp, direction_deg)` +
  `hb.add_twist(a, b, *, total_degrees | degrees_per_nm)` (import `add_deformation` → covered by identity).
  **Augment:** `assert_deformation_angle` (new reusable oracle) — walks the deformed frame in 1-bp steps
  and SUMS each step's relative-rotation magnitude (unwraps past 180°/360°: a 540° twist reads 540°),
  asserting the total = κ×(b−a) for a bend / the total twist, plus a can-go-red guard (fails on an
  un-deformed design). **Direction-AGNOSTIC** (magnitude only → no ASK-FIRST sign/frame reasoning needed;
  the signed-curvature oracle the backlog floated was *not* built, deliberately). Coverage 18→19.

- [ ] **AF-14 — geometry-aware revolute-joint placement on hull-prism corners/edges** (route
  `POST /design/cluster/{cluster_id}/joint`, handler `add_joint` in `routes_cluster_joints.py`; currently
  gizmo-only — the user clicks a face on the cluster's hull-surface approximation, the frontend computes a
  world axis, the route converts it to the cluster's LOCAL frame). **No headless wrapper exists** → uncovered.
  Three-layer note: a `ClusterJoint` is a **topological/design-layer** intent (which rigid cluster rotates
  about what axis) — placing one is an allowed write; the hull prism, the OBB, and the range-of-motion (ROM)
  math are all **geometric reads** and never write back (clean Three-Layer; mirrors how AF-6 deformation reads
  the frame). Multi-phase — one phase per session.

  **The kinematic-design framing (this is the point — it's why "face corners" is the right primitive).**
  A revolute joint is a hinge: a rigid cluster M swings about an axis line relative to the static rest of the
  design. What a designer actually wants to pick is *which hinge gives the desired free swing without M
  colliding into a neighbouring cluster*. The hull prism **is the cluster's oriented bounding box (OBB)**, so
  its faces/edges/corners are the natural discretised anchor set, and the relevant mechanical principles are:
  - **The hinge axis belongs on the contact interface (the door-jamb principle).** Co-locating the axis with
    the *edge of M's OBB that lies against the neighbour* maximises ROM: M rotates immediately *away* from the
    obstacle instead of swinging *into* it. An axis through M's interior (or the far edge) collides almost
    at once. So the high-value candidates are the OBB **edges on the face adjacent to the obstacle**.
  - **For a revolute joint the primitive is an EDGE (a corner→corner pair); for a ball/point joint it's a
    CORNER.** "Face corners" enumerates both: the 8 corners give point pivots; corner-pairs give the 12
    candidate hinge edges. The axis *direction* is the edge's line (typically perpendicular to the helix axis
    = a fold; parallel = a barrel-roll — usually not what's wanted).
  - **ROM is a swept-collision root-find.** Rotating M about axis a sweeps every point p on a circle of radius
    `r = dist(p, a)`; first contact is driven by the point of M **farthest from a on the obstacle side** (the
    instantaneous-centre / largest-swing-radius point). Because both M and every obstacle are OBBs, the swept
    interference is exact and cheap: **bisect θ on OBB–OBB separation (SAT) to find θ⁺ and θ⁻**, and
    `ROM(a) = θ⁺ + θ⁻` (clamped to the joint's `min/max_angle_deg` limits), checked against **all** other
    clusters, not just the nearest. This is the discretised collision-free workspace of a 1-DOF joint.
  - Connects to the **AF-12 hinge-primitive / 4-bar-linkage** discussion: a multi-joint mechanism's mobility
    (Grübler) and ROM both depend on these corner/edge choices; AF-14 is the per-joint geometry the linkage
    layer will compose.

  **Feasibility blocker to settle first (do this in Phase 1):** the hull-prism OBB is currently computed in
  **JS** (`frontend/src/scene/joint_renderer.js` — `_bundleGeometry`/`_buildExtrusionBoxes`), NOT Python, so a
  headless ROM oracle needs a backend OBB. Build it from the geometry kernel (`_geometry_for_design` →
  per-cluster nucleotide positions → PCA/bundle-frame OBB), as a NEW pure `backend/core/cluster_obb.py`
  (service+oracle shape, rule 3; `backend/core` imports nothing from `backend/api`). Pin it for parity against
  the JS extents on a shared fixture so the headless corner set matches what the user sees.

  - [x] **Phase 1 — `hb.place_cluster_joint` + corner/edge resolver + on-corner oracle. SHIPPED 2026-06-17.**
    Wrapper in `headless_build.py` importing `add_joint` (covered by identity) + `AddJointBody`. The pure helper
    `hull_prism_axis(design, cluster_id, *, edge=(axis,s1,s2) | corner=(su,sv,sw)+face=(axis,sign))
    → (axis_origin, axis_direction)` in `cluster_obb.py` turns a named OBB edge/corner into the world axis the
    route expects (edge = revolute hinge ALONG the edge: origin=midpoint, dir=edge line; corner = point pivot AT
    the corner, dir=face normal). **Augment:** `assert_joint_on_hull_corner(design, joint_id, *, edge|corner,
    face, tol_nm, tol_deg)` — re-derives the joint world axis from its LOCAL storage via `_local_to_world_joint`
    + the cluster's current pose, recomputes the OBB independently, asserts the axis is collinear with the named
    edge / passes through the named corner. Direction-AGNOSTIC. Coverage **34 → 35** (`add_joint` — first flip
    since AF-15 P1). Tests: 7 in `test_cluster_obb.py` + 5 in `test_automation_harness.py` (incl. a posed-cluster
    local-frame round-trip test + 2 load-bearing red-tests).
  - [x] **Phase 2 — `cluster_range_of_motion` + `rank_joint_candidates` (the geometry-aware selector).
    SHIPPED 2026-06-17.** Pure swept OBB–OBB SAT (`_obb_intersect`, Ericson 15-axis) + per-step scan +
    bisection in `cluster_obb.py`: `obb_sweep_rom(moving, obstacles, axis_origin, axis_dir, *, min_deg,
    max_deg, pad, step_deg)` (on OBBs) → `cluster_range_of_motion(design, cluster_id, axis, *, obstacles=None,
    min_angle_deg, max_angle_deg, pad=HELIX_RADIUS, step_deg)` (anchored cluster swings, others static) →
    `rank_joint_candidates(design, cluster_id, *, target_rom_deg=None)` ranks the 12 OBB **edges** (corners are
    3-DOF ball pivots — single swing angle ill-defined — deliberately not ranked). **Augment:**
    `assert_range_of_motion(design, cluster_id, axis, expected_deg, *, tol_deg, …)` in `automation_harness.py`.
    **ASK-FIRST decisions (user, 2026-06-17):** anchored cluster is the moving body / all others static; ROM =
    **total two-sided magnitude** (θ⁺+θ⁻, each clamped to the limit) → direction-AGNOSTIC, no handedness; OBBs
    **padded by the helix radius** (~1 nm) so contact is rim-to-rim. Analytic precision proved on a SYNTHETIC
    rod+double-wall fixture (closed-form `2·(asin(Y0/√(L²+w²))−atan2(w,L))`, an independent derivation, tol 1°);
    the two can-go-red guards proved on real bars (no-obstacle → full 360°/limit; a neighbour in the path
    strictly reduces ROM, monotonic with the gap). Coverage **35 → 35** (composition over the already-covered
    `add_joint`/`update_cluster` — wraps no new route; the oracle is the deliverable). 10 new tests.
  - [x] **Phase 3 — edge-mapping joint recommender (`recommend_hinge_joints`) + corner anchoring.
    SHIPPED 2026-06-18.** `recommend_hinge_joints(design, cluster_id, *, anchor="corner", axial_tol_deg=20,
    target_rom_deg=None)` in `cluster_obb.py` ranks ALL 12 OBB edges by the user-fixed priority below
    (non-axial first → longest edge → ROM tiebreak), returning each annotated `{edge, edge_length,
    angle_to_axis_deg, is_axial, rom_deg, axis_origin, axis_direction}`; `axis_origin` is corner-anchored.
    `hull_prism_axis` + `place_cluster_joint` gained `anchor="midpoint"|"corner"` (default midpoint =
    backward-compatible; corner stores the edge's `−axis` endpoint — same hinge line). **Augment:**
    `assert_recommended_hinge` (new reusable oracle, re-measures on the independent equivariant OBB) — pins the
    #1 hinge is non-axial + the longest non-axial edge + corner-anchored, with 2 load-bearing red-tests
    (axial-on-top, midpoint-anchor). Coverage **35 → 35** (pure selector; the anchor reuses the already-covered
    `add_joint` route). Tests: 7 in `test_cluster_obb.py` + 3 harness meta-tests; full suite **2523 passed /
    55 skipped**. NB the capstone's 4-bar hinged on the axial `w`-edge (a barrel-roll); a follow-up could
    re-point `build_parallelogram` at the recommended cross-section edge.

    <details><summary>original Phase-3 spec</summary>
    Surface
    headlessly the **most-likely hinge-joint candidates** as an edge mapping: for each cluster, enumerate the OBB
    edges and rank them by the **user-fixed hinge-recommendation priority (2026-06-18, takes precedence over the
    Phase-2 ROM-only sort)**:
      1. **Hinge edge = the largest edge that is NOT parallel to the helical axis.** The OBB `w` axis IS the
         helical/bundle axis, so its 4 long edges (`("w", …)`) are *excluded* — hinging about them is a
         barrel-roll, not a fold. Among the remaining cross-section edges (`("u", …)` / `("v", …)`), prefer the
         **longest** (for a 3×6 bar the `u` edge — the wide cross-section — beats the `v` edge). ROM stays a
         secondary tiebreaker (the Phase-2 door-jamb sort), not the primary key.
      2. **Anchor joints at face corners, NOT edge midpoints.** `hull_prism_axis` edge mode currently sets
         `origin = edge midpoint`; the recommender must place the joint's anchor at a **face corner** (an edge
         endpoint) instead. The revolute axis *line* runs along the chosen edge as before — corner vs. midpoint
         only moves the stored anchor point — but the convention is corner-anchored. (Decide whether this is a new
         `anchor="corner"` option on `hull_prism_axis`/`place_cluster_joint`, or the recommender returns the
         corner explicitly; corner mode's `corner=(su,sv,sw)+face` storage may suffice with `direction` overridden
         to the edge line — settle when building.)
    **Augment:** `assert_recommended_hinge(design, cluster_id, …)` — the top recommendation is a non-axial edge
    (angle to `w` > tol), is the longest such edge, and the placed joint is corner-anchored; can-go-red on a
    design where an axial `w`-edge is (wrongly) returned first or the anchor is the midpoint. Reuses the
    equivariant OBB + `rank_joint_candidates`. **NB this revises the capstone's choice** (the 4-bar used the
    axial `w`-edge as the hinge — a barrel-roll); the new rule prefers a cross-section fold edge, so the
    parallelogram builder/oracle may want a follow-up pass to use the recommended edge.
    </details>

- [x] **AF-16 — headless cluster creation + a loggable cluster-create feature-log entry. SHIPPED 2026-06-18.**
  NEW `ClusterCreateLogEntry` Pydantic model in `backend/core/models.py` (mirrors `ClusterOpLogEntry`:
  `cluster_id`/`name`/`helix_ids`/`domain_ids`) added to the `FeatureLogEntry` union; `add_cluster` route gained an
  opt-in `log: bool = False` that appends the entry with the same cursor-truncation discipline `update_cluster`
  uses; `hb.add_cluster(..., log=False)` gained the passthrough (default off — backward-compatible, the capstone +
  all existing tests don't log). **Augment:** `assert_cluster_in_feature_log(design, cluster_id, *,
  expect_helix_ids=None)` — the `cluster_create` entry exists, names the cluster's exact helix set + name; call it
  on a `roundtrip_nadoc` result to prove the grouping survived `.nadoc` save/load (canonical_topology is blind to
  clusters — the entry is the only proof of persistence). Coverage **35 → 35** (`add_cluster` already covered since
  AF-15 P1 — this adds the log path, not a new route). Tests: 3 in `test_headless_build.py` + 3 harness meta-tests
  (incl. 2 load-bearing red-tests: unlogged build leaves no entry; wrong helix set raises). Full suite **2529
  passed / 55 skipped**. The generated 4-bar part's feature log is now completable — the cluster-creation step is
  representable. **The gap (found 2026-06-17 while generating the 4-bar part):** `add_cluster` creates the cluster in
  design state but emits **no feature-log entry** — there is no `ClusterCreateLogEntry` type (the log has
  `cluster_op` for translate/rotate, but nothing for *grouping helices into a bar*). So a design's feature log
  cannot record "create the 4 bars," and the construction history is incomplete: a user replaying the log sees the
  bundle + the transforms + the joints (minor mutations under "Fine Routing") but not the cluster creation. Closing
  this means (a) a NEW `ClusterCreateLogEntry` Pydantic model in `backend/core/models.py` added to the
  `FeatureLogEntry` union (mirror `ClusterOpLogEntry`: `cluster_id`, `name`, `helix_ids`, `domain_ids`), (b) wiring
  `add_cluster`'s route to append it (with the same `commit`/`log` discipline `update_cluster` uses), and (c) the
  `hb.add_cluster` wrapper gaining a `log=` passthrough. **Three-layer note:** creating a cluster is a
  display/geometry-layer grouping (it never touches the strand graph), exactly like `cluster_op` — clean.
  **Augment:** `assert_cluster_in_feature_log(design, cluster_id)` — after a logged `add_cluster`, the feature log
  carries a `cluster_create` entry naming that cluster + its exact helix set, and it survives a `.nadoc`
  round-trip (canonical_topology is blind to clusters, so the feature-log entry is what proves the grouping
  persisted — same shape as the AF-3 loop/skip / AF-6 deformation blind-spot lesson). Can-go-red: a build that
  creates a cluster *without* logging leaves no entry. **This is what makes the generated 4-bar part's feature log
  truly complete** (today its cluster-creation step is unrepresentable).

- [ ] **AF-15 — cluster rigid-transform wrapper + OBB-edge-alignment solver** (routes `POST /design/cluster`
  = `add_cluster`, `PATCH /design/cluster/{cluster_id}` = `update_cluster` in `routes_clusters.py`; both
  uncovered). **Sequences BEFORE AF-14 Phase 2 and the linkage demo** — you arrange the rigid bars, *then*
  hinge them. This is the design-layer analog of the AF-8 assembly connector-mate, but driven by **OBB edges**
  instead of named connectors. Three-layer note (load-bearing, and clean here): a `ClusterRigidTransform` is a
  **DISPLAY/geometric pose — it never mutates topology** (stated at `routes_clusters.py:8`). So aligning two
  bars edge-to-edge *reposes rigid bodies*; the DNA strand graph of each bar is untouched. The articulated
  arrangement (poses) + AF-14 joints (kinematic intent) together describe the mechanism without ever editing
  the bars' topology — the three-layer law made concrete for a mechanism. **Shares `backend/core/cluster_obb.py`
  with AF-14** (whichever lands first builds it; the OBB corner/edge enumerator is the common foundation).

  **What the user wants automated (the parallelogram 4-bar linkage, at the part-design level):** four rigid
  bars → arranged into a parallelogram → hinged at the four corners → a working 1-DOF mechanism, all in ONE
  `Design` (4 clusters + 4 `ClusterJoint`s), no assembly layer. The pieces:
  - **Extrude the bars — ALREADY AUTOMATABLE.** `hb.create_bundle` / `hb.extrude` (and the AF-11 `bundle` /
    `extrude` build-spec ops) build the bar bundles today. AF-15 does NOT re-do this.
  - **Cluster each bar — NEW.** `hb.add_cluster(name, helix_ids, domain_ids=…)` wraps `add_cluster` (covered
    by identity).
  - **Pose each bar — NEW.** `hb.transform_cluster(cluster_id, *, translation, rotation_quat, pivot)` wraps
    `update_cluster` (covered). Low-level; takes an explicit rigid transform.
  - **Align by OBB edge — NEW, the high-value piece.** A pure solver
    `align_edge_transform(design, cluster_id, src_edge, target_edge|target_line) → (R, T, pivot)` in
    `cluster_obb.py` computes the rigid transform that brings cluster M's chosen OBB edge onto a target edge
    (another cluster's OBB edge, or a world line), then drives `transform_cluster`. Composing four of these is
    the parallelogram arrangement.

  **Augment (Phase split — one per session):**
  - [x] **Phase 1 — cluster create/transform wrappers + round-trip pin. SHIPPED 2026-06-17.**
    `hb.add_cluster(name, helix_ids, *, domain_ids=())` + `hb.transform_cluster(cluster_id, *, translation,
    rotation, pivot, commit=True, log=False)` (import `add_cluster`/`update_cluster` → covered by identity).
    **VERIFIED `canonical_topology` IS blind to the cluster pose** (it fingerprints helices by `axis_start` +
    strands; cluster_transforms aren't in it — the AF-3 loop/skip / AF-6 deformation blind-spot confirmed for a
    third overlay), so `assert_roundtrip_stable` is necessary-but-NOT-load-bearing for the pose. The load-bearing
    augment is the NEW geometric oracle `assert_cluster_translated(before, after, cluster_id, *, translation)` —
    it reads the cluster-posed helix axes via `deformed_helix_axes` and asserts (1) every cluster helix's
    `start`/`end` shifted by exactly the translation, (2) only the cluster moved (non-cluster helices unchanged),
    (3) `‖T‖ > min` can-go-red guard. **Direction-AGNOSTIC** (a pure world-space translation, no quaternion/pivot
    convention → ASK-FIRST-safe; **rotation poses deliberately out of scope** — they ARE a directionality question,
    deferred to Phase 2's edge-alignment flip/snap). Coverage **32 → 34** (`add_cluster` + `update_cluster`).
    **`cluster_obb.py` was NOT built** — Phase 1 needs no OBB (a translation oracle reads posed axes directly);
    the OBB enumerator is first needed by Phase 2's `align_edge_transform` + AF-14's ROM.
  - [x] **Phase 2 — `align_edge_transform` solver + alignment oracle. SHIPPED 2026-06-17.**
    NEW pure core `backend/core/cluster_obb.py` (the **equivariant OBB enumerator** — corners/edges keyed
    `(axis, s1, s2)` — built from posed helix axes via a PCA cross-section frame, NOT
    `_initial_cross_section_frame` which snaps to world axes and would not track a posed cluster; + the pure
    `align_edge_transform` solver) + the `hb.align_cluster_edge` wrapper driving `transform_cluster` (coverage
    UNCHANGED 34 — wraps no new route) + the reusable `assert_edges_collinear` oracle. **ASK-FIRST conventions
    confirmed with the user (2026-06-17): minimal rotation / auto-flip (≤90° onto ±target_dir) / midpoint snap
    (endpoints coincide) / roll left free.** The load-bearing pin proved equivariance
    (`OBB(g·design)=g·OBB(design)`) — the property that makes an edge key refer to the same physical edge before
    and after the solve. Tests: `tests/test_cluster_obb.py` (11) + 4 harness meta-tests. **`cluster_obb.py` is now
    the shared foundation AF-14 reuses** (the OBB enumerator + a future swept-OBB SAT for ROM).
    `assert_edges_collinear(design, cluster_id, src_edge, target_edge, *, tol_nm, tol_deg)` — after the solved
    transform the two OBB edges are **collinear** (shared line: angle between directions ≈ 0/180° AND
    perpendicular distance < tol), with a can-go-red guard (the pre-align edges are skew/separated, so a no-op
    solver fails). Collinearity is **direction-AGNOSTIC** (a line, not a ray). **The capstone integration test
    SHIPPED 2026-06-17** (`tests/test_parallelogram_linkage.py` + `grubler_mobility` in `cluster_obb.py` +
    `assert_parallelogram_linkage` in `automation_harness.py`): the **4-bar parallelogram built headlessly** —
    extrude 4 bars, cluster + edge-align into a rhombus (adjacent bars share an OBB corner), place 4 revolute
    joints on the shared side-edges — and assert it's a closed, parallel, Grübler-1-DOF linkage with every hinge
    movable. The first headless **kinematic mechanism** and the AF-12 linkage-mobility demo; the Tier-2 arc is
    complete.

### Tier 3 — headless ASSEMBLY builder (biggest construction gap; multi-phase, `headless_assembly_build.py`)

- [x] **AF-7 (Phase 1) — assembly scratch-session + `add_instance(source, transform)` + save/validate.**
  SHIPPED 2026-06-17. NEW module `backend/api/headless_assembly_build.py` mirroring `headless_build.py`:
  `assembly_scratch_session()` + `new_assembly` + `add_inline_instance` / `add_file_instance` / `add_instance`
  (imports `create_assembly` / `add_instance` / `resolve_assembly` / `import_assembly` route handlers → covered
  by function identity) + `resolve()` + `translation()` helper. **Augment:** `assert_assembly_roundtrip_stable`
  (new reusable oracle) + `canonical_assembly` fingerprint + `roundtrip_nass` in `automation_harness.py` — build
  → `.nass` export (`to_json` v2) → real `POST /assembly/import` → `validate_assembly_report` passes both sides
  AND id/order-independent fingerprint (inline source → embedded design's `canonical_topology`; file → path+sha;
  + per-instance transform/mode/rep/fixed/visible; + joints for AF-8) is unchanged. In-memory (inline parts
  travel inside the payload, no disk) — the assembly analog of `roundtrip_nadoc`'s import path, NOT file save/load.
  Coverage 19→23 (create + add-instance + resolve + import all flip). `headless_coverage_report` now scans both
  `headless_build` AND `headless_assembly_build`.
- [x] **AF-8 (Phase 2) — headless mate/joint by connector labels.** SHIPPED 2026-06-17.
  `hab.add_connector(inst, label, position, normal)` (imports `add_connector` route → covered) +
  `hab.define_mate(child, parent, *, child_label, parent_label, joint_type="rigid")` (imports `create_mate`
  → covered); the route snaps the child so its connector meets the parent's (no FK transform passed — the
  connector-derived snap aligns the parts). **Augment:** `assert_mate_coincident` (new reusable oracle) —
  the two mated connectors are coincident in world space (via the SAME `_get_connector_world` machinery
  resolve uses) within tol, plus a non-triviality guard (mated part origins must be separated, else
  coincidence is vacuous). Also enriched `canonical_assembly`'s joint key with the mated parts' source
  fingerprints (id-independent). Coverage 23→25.
- [ ] **AF-9 (Phase 3) — gears / belts / overhang-bindings / polymerize wrappers.** Multi-op; one sub-op
  per session. **Augment:** each resolve-invariant (gear ratio holds, belt tangent length, polymerized chain
  count + seam geometry via `derive_periodic_delta`).
  - [x] **gears — SHIPPED 2026-06-17.** `hab.define_gear(joint_a_id, joint_b_id, *, ratio, invert=…)`
    (imports `create_gear_relation`) + `hab.drive_joint(joint_id, value, *, endpoint_side=…)` (imports
    `patch_joint`; PATCH auto-propagates the gear, path 1). **Augment:** `assert_gear_ratio(before, after,
    rel_id, *, expected_ratio)` — measures the two coupled bodies' real *instance-transform* rotation
    magnitudes after driving one side, asserts driven/driver = |ratio| (NOT a re-test of `current_value`),
    with a can-go-red "driver actually moved" guard. Direction-agnostic (magnitude only). Also enriched
    `canonical_assembly` to fingerprint `gear_relations` (keyed by the coupled joints' id-independent
    fingerprints + ratio/invert/anchors) so the round-trip oracle now catches a dropped/rewired gear.
    Coverage 25→27.
  - [x] **belts — SHIPPED 2026-06-17.** `hab.define_belt(joint_a_id, joint_b_id, *, radius_a, radius_b, …)`
    (imports `create_belt_path` + `CreateBeltPathRequest`/`BeltPulleyRequest` from `routes_assembly_belts`).
    **Augment:** generalised `assert_gear_ratio` to search `_coupling_relations` (gears + belt-derived) so a
    belt pins with the SAME oracle — pass `rel_id=f"__belt__{belt.id}"` + `expected_ratio = radius_a/radius_b`;
    it proves `_belt_to_relation`'s radius→ratio synthesis actually drives the coupled pulley (NOT a hand-passed
    gear ratio). Also extended `canonical_assembly` to fingerprint `belt_paths` (now a **4-tuple**). Coverage 27→28.
  - [x] **polymerize (mate-seeded) — SHIPPED 2026-06-17.** `hab.polymerize(joint_id, count, *,
    direction="forward", additional_instance_ids=…)` (imports `polymerize_assembly` +
    `PolymerizeAssemblyRequest` from `routes_assembly_polymerize`). **Augment:**
    `assert_polymer_chain(before, after, seed_joint_id, *, count, direction)` — re-derives the seed mate's
    repeat `delta = T_B @ inv(T_A)` from the seed pair ALONE (not the route's chain helpers) and asserts
    the `count−2` new copies form the exact `delta`-power multiset (`delta^k @ T_B` fwd / `inv(delta)^k @ T_A`
    back), id-independent, within tol — plus a can-go-red guard that `delta`'s translation > 0.5 nm (stacked
    seed → vacuous). `canonical_assembly` already fingerprints instances+joints, so the round-trip oracle
    catches a dropped copy/joint with no extension needed. Coverage 28→29.
  - [x] **overhang-bindings — SHIPPED 2026-06-17.** `hab.bind_overhangs` / `hab.patch_binding` /
    `hab.unbind_overhangs` (import `create_/patch_/delete_assembly_overhang_binding` + the two request models
    from `routes_assembly_overhangs` — covered by function identity). **Augment:** `assert_binding_resolves`
    (new reusable oracle) — a cross-part binding's two endpoints each resolve to a real overhang sub-domain on
    their part design (loaded via the route's own `_load_design_from_source`), with a non-degenerate guard
    (distinct endpoints + cross-part). Genuinely new power: `canonical_topology` does NOT fingerprint a design's
    overhangs/sub-domains, so a round-trip that regenerated a sub-domain id while the binding kept its stale ref
    would slip past `canonical_assembly` — only resolving against the actual designs catches it. Also extended
    `canonical_assembly` to fingerprint `overhang_bindings` (now a **5-tuple**). Coverage 29→32.
  - [ ] **periodic polymerize remains** — `polymerize_periodic` (the SINGLE-part `is_periodic_seam` path with
    the `derive_periodic_delta` Kabsch oracle) was NOT built: it needs a heavy fixture (a design carrying
    `is_periodic_seam` forced ligations, e.g. via the route-for-polymerization op) — see handoff.
- [x] **AF-10 — instance layout helpers** (grid / ring placement) for parametric assembly gen.
  SHIPPED 2026-06-17. NEW pure core `backend/core/instance_layout.py` (`grid_translations` /
  `ring_translations` — spec→world translations, identity orientation; mirrors `circle_primitive`) +
  `hab.place_grid` / `hab.place_ring` (construction sugar over the already-covered `add_instance` — they
  wrap NO new route, so headless-coverage is unchanged at 32). **Augment:** `assert_instances_on_grid` /
  `assert_instances_on_ring` (new reusable oracles) — read the *placed* instance origins and assert the
  lattice as PROPERTIES re-derived from the user-facing params (count exact, even spacing == pitch / every
  cell filled; on-ring radius exact + angular step == 360°/n), not by re-running the placement formula, each
  with a non-degeneracy guard (the ring's `radius>0` guard is load-bearing — radius=0 stacks every part where
  `dist==radius==0` passes vacuously). Radial-facing/rotated layouts deferred (orientation convention =
  ASK-FIRST). Coverage 32→32.

### Tier 4 — text-to-DNA-origami groundwork (the eventual goal; built ON the validated wrapper library)

- [x] **AF-11 (Phase 1) — declarative build-spec interpreter.** SHIPPED 2026-06-17. Pure grammar/parser
  `backend/core/build_spec.py` (`parse_design_spec` / `parse_assembly_spec` → ordered `BuildOp` list; full
  grammar + referential-integrity validation, NO execution) + driver `backend/api/headless_spec_build.py`
  (`build_design` / `build_assembly` dispatch each parsed op to the REAL existing wrappers — re-implements
  nothing). Grammar: design `{bundle, extrude, nick, ligate}` (helices referenced by `grid_pos`), assembly
  `{add_part, place_grid, place_ring, mate}` (parts = a named library of nested design specs; instances by
  spec `ref`; nested part designs built via `build_design`). **Augment:** `assert_spec_matches_calls` (new
  reusable oracle) — a spec builds the SAME `canonical_topology`/`canonical_assembly` as the equivalent
  hand-call wrapper sequence (the faithful-façade / golden-pin guarantee), + reuse of
  `assert_roundtrip_stable` / `assert_assembly_roundtrip_stable` per spec. Coverage 32→32 (wraps no new
  route — composition sugar, like AF-10). *Phase 2 grammar growth (one cluster per session): **`bend`/`twist`
  SHIPPED 2026-06-17** (drive `hb.add_bend`/`add_twist`; pinned by `assert_deformation_angle`, NOT
  `assert_spec_matches_calls` — the canonical fingerprint is blind to a deformation overlay). **`loop_skip`
  SHIPPED 2026-06-17** (drive `hb.loop_skip`; helix by `grid_pos`; `delta ∈ {-1,0,+1}` parse gate; pinned by the
  geometric `geometric_nucleotide_count`, NOT `assert_spec_matches_calls` — canonical is blind to a loop/skip mark
  too. Sibling `apply_loop_skips` DEFERRED: its route needs crossovers the grammar can't yet produce → rides with
  the auto-scaffold cluster). **`circle_segment` SHIPPED 2026-06-17** (primordial design op — may be FIRST, builds
  its own helices; requires a `square` lattice, enforced at parse time; drives `hb.circle_segment(radius_nm)`.
  Pinned by BOTH `assert_spec_matches_calls` — LOAD-BEARING here, circle ADDS real strands so canonical_topology
  sees it — AND the geometric `assert_circular_disc` from AF-4 as the radius→geometry pin). **`gear` SHIPPED
  2026-06-17** (assembly relations cluster — first sub-op; drives `hab.define_gear` over two revolute mate-joints
  referenced by a NEW joint-`ref` namespace added to the `mate` op; pinned by BOTH `assert_spec_matches_calls` —
  load-bearing, gears ARE fingerprinted in `canonical_assembly` since AF-9 — AND the kinematic `assert_gear_ratio`,
  which catches the orthogonal failure the fingerprint can't: a gear that's structurally present but fails to
  *drive* its coupled body. Parser also rejects gear-over-rigid + dangling joint refs at parse time). **`belt`
  SHIPPED 2026-06-17** (relations cluster, second sub-op; reuses the gear's joint-`ref` namespace verbatim by
  widening the revolute-ref check to `op in ("gear","belt")`; drives `hab.define_belt`; pinned by BOTH
  `assert_spec_matches_calls` — load-bearing, belts ARE fingerprinted in `canonical_assembly` since AF-9 — AND
  `assert_gear_ratio` handed `f"__belt__{belt.id}"` + `expected_ratio = radius_a/radius_b`, passing the *radii* so it
  pins `_belt_to_relation`'s radius→ratio synthesis distinctly from the gear test). Remaining:
  polymerize/overhang-bindings (assembly, each like gear) + auto-scaffold/full-autostaple (design) — each a
  tiny dispatch entry over an existing wrapper, oracle picked by what the op changes.*

- [ ] **AF-12 — build from primitives (catalog/file-backed parts in the build-spec).** PLACEHOLDER, expand later.
  **The gap (assessed 2026-06-17):** there is no primitive-catalog → automation pipeline. The design-level "Add
  Primitive" catalog is **read-only + UI-only** — `routes_primitives.py` exposes only `GET /primitives` +
  `preview.gif`/`poster.png`; there is **no placement route** (the browser reads `derive_placement_spec` and composes
  the `bundle-segment`/`continuation` calls client-side), and no headless layer references the catalog at all (the
  one parametric primitive with a headless entry is the circle disc, `hb.circle_segment`). At the assembly level,
  `hab.add_file_instance(path)` CAN instance a saved validated `.nadoc` part by workspace path and mate it — but the
  declarative grammar's `add_part`/`parts` accept **inline design specs only** (`parse_design_spec` per part), so a
  spec cannot reference a saved/validated primitive **by name**. **The missing rung** = a catalog/file-backed
  `add_part` (e.g. `"parts": {"hinge": {"from_primitive": "hinge_6hb_120deg"}}` or `{"from_file": "<path>"}`) + a
  headless primitive-instantiation wrapper. **The motivating use case (user, 2026-06-17):** hand-author +
  experimentally validate a hinge's custom scaffold routing (real topology = ground truth), save it as a part, then
  let automation place/articulate copies (display-layer mates/gears — never touching the validated topology; fits the
  three-layer law). A "hinge primitive" is likely an *assembly-level template* (two leaves + a revolute mate), not
  just a design primitive — so consider a parts-library that can carry small mate recipes, not only geometry.
  **Augment (when built):** a round-trip-style oracle asserting the instanced part's `canonical_topology` equals the
  referenced catalog file's `canonical_topology` — i.e. "build from primitive X provably uses *exactly* validated X"
  (so a stale/renamed/edited primitive can't silently substitute). Builds ON AF-11 (the build-spec interpreter) and
  AF-7 (`add_file_instance`). See the chat assessment + the 4-bar/parallelogram linkage discussion for context.
  **NB (2026-06-17): the mechanism layer this item gestured at is now spec'd as AF-14 + AF-15** (Tier 2,
  geometry-aware joint placement + OBB-edge alignment, sharing `backend/core/cluster_obb.py`). The 4-bar
  parallelogram capstone there builds the linkage at the *part-design level* (4 clusters + 4 `ClusterJoint`s in
  one `Design`); AF-12's role is the complementary path — instancing a hand-validated *saved* hinge/bar primitive
  by name — so the two compose (validated primitive geometry ← AF-12; articulation/arrangement ← AF-14/AF-15).

### Tier 5 — physical-layer validation (oxDNA-in-the-loop) + constraint satisfaction (the eventual goal)

**What's different here.** Tiers 0–4 validate the **topological/geometric** layers and are *deterministic*
(`canonical_topology` equality, analytic geometry oracles). Tier 5 validates the **physical** layer: it
drives an oxDNA relaxation/production headlessly, *measures* a property of the relaxed structure (end-to-end
distance, R_g, inter-helix spacing, segment angle), and — the capstone — **iterates the design until a user
constraint is satisfied.** Because MD is stochastic, the oracle class is new: **a measured property within a
tolerance, GATED by the confidence metric** (`oxdna_health.rmsf_confidence` — frames pooled + RMSF standard
error, already built), NOT exact equality. A short run reports *inconclusive*, not pass/fail.

**Eventual goal (user, 2026-06-17):** *"Make sure two ends of a curved structure are 50 nm ± 5 nm apart"* →
NADOC iterates over several oxDNA simulations until the request is met.

**Three-Layer Law (load-bearing here).** The iterate loop EDITS the **topological** layer (a bend op /
loop-skip / length knob), re-derives **geometric** positions, RE-RELAXES the **physical** layer (oxDNA),
then MEASURES the physical result. The edit is topological; the measurement is physical; **oxDNA output is
never written back into `Design`** (it stays a Physical-layer artifact, exactly as the display/RMSF paths do).
Confusion about *which* nucleotide is "an end", or *which* knob bends *which* way, is an ASK-FIRST
directionality question (`feedback_crossover_no_reasoning`, the DNA-topology rule) — do not guess.

**Reuse map (durable — don't re-derive; see `memory/project_oxdna_relaxation.md`):** job lifecycle / resume /
reconcile in `backend/core/oxdna_runner.py`; routes in `backend/api/routes_oxdna.py` (`create_oxdna_job`,
`start_oxdna_job`, `append_oxdna_production`, `/rmsf`, `/trajectory`, `/display`); average-structure + per-base
RMSF in `oxdna_health.production_rmsf`; the confidence metric in `oxdna_health.rmsf_confidence`; relaxed-geometry
readers `read_configuration_unwrapped` / `read_configuration_full` / `oxdna_backbone_site` in
`backend/physics/oxdna_interface.py`. **CI-without-GPU:** the **mock oxDNA binary** (`_MOCK_OXDNA` fixture in
`tests/test_oxdna_relaxation.py`) lets the wrapper + oracles run deterministically; gate real-binary paths with
`skipif find_oxdna() is None`.

- [x] **AF-13 (Phase 1) — headless oxDNA job wrapper. SHIPPED 2026-06-18.** NEW
  `backend/api/headless_oxdna_build.py` drives the REAL routes (`create_oxdna_job` → `start_oxdna_job` → poll →
  optional `append_oxdna_production` → `get_oxdna_display`) from an isolated scratch session, against the mock
  binary (`$OXDNA_BIN`). `hox.run_relaxation(design, workspace, *, min_bp_retained=0.0, …) → terminal OxdnaJob`;
  lower-level `create_job`/`start_relaxation`/`append_production`/`read_relaxed_positions`/`wait_for_terminal`.
  **Augment:** `assert_relaxed_geometry_recovered(job, design, workspace)` — job is `completed` AND its relaxed
  `last_conf` reads back (via the display route's `read_configuration_unwrapped`) into a full per-nucleotide
  position map (exactly one finite position per design nucleotide, every key a real `(helix_id, bp, dir)`).
  Physical-layer only — never written back to topology. NEW separate `oxdna_coverage_report()` (3 `/oxdna`
  mutation routes covered) keeps the design/assembly count untouched at 35.

- [x] **AF-13 (Phase 2) — relaxed-geometry MEASUREMENT oracle (the constraint primitive). SHIPPED 2026-06-18.**
  Landmark convention (ASK-FIRST answered by user): the raw **`(helix_id, bp_index, direction)` tuple** — most
  primitive, indexes the relaxed-display + RMSF maps directly, no strand-polarity resolution. Pure
  `measure_end_to_end(positions, a, b)` in `backend/core/oxdna_health.py` (Euclidean nm between two landmark
  backbone sites; raises on empty/identical/absent). NEW read-wrapper `hox.read_flexibility_map(job_id, ws)`
  drives the REAL `GET /oxdna/jobs/{id}/rmsf` → pooled noise-averaged mean structure + `confidence`. **Augment:**
  `assert_relaxed_measurement(job, measure_spec, target_nm, tol_nm, *, workspace, min_confidence)` — the first
  STOCHASTIC-class oracle: status-completed + reads the mean structure + **confidence gate** (≥ `min_confidence`
  pooled frames else INCONCLUSIVE-raise) + measured ∈ [target±tol]. On the identity-mock 6hb the relaxed mean
  reproduces the design's own end-to-end to ~0.002 nm (pinned at tol 0.1). Coverage unchanged (rmsf is a GET).

- [x] **AF-13 (Phase 3) — declarative constraint spec + checker. SHIPPED 2026-06-18.** `parse_constraint_spec`
  (PURE validate/normalise → `ConstraintSpecError` at parse time) + `check_relaxed_constraint(constraint,
  read_flexibility_map_dict)` REPORTING `{met, status∈{met,unmet,inconclusive}, measured_nm, n_frames,
  min_confidence, confidence}` — both in `backend/core/oxdna_health.py`, reusing P2's `measure_end_to_end`.
  The REPORTER counterpart to P2's *asserter*. **Load-bearing guard pinned:** `met` is NEVER True below
  `min_confidence`, even when the value is within tolerance (the confidence gate, now a returned status). 20 pure
  tests (13 rejection cases + idempotency + tolerance bracket + the low-frame-never-met red-test) + 2 real-run
  integration tests (`_MOCK_OXDNA_TRAJ` → `read_flexibility_map` → checker). Coverage UNCHANGED (no route wrapped).
  Slots into the AF-11 grammar as a design `constraints` block (not yet wired into `build_spec.py` — P4 will).

- [ ] **AF-13 (Phase 4, capstone — the eventual goal) — iterate-until-met loop.** Given a PARAMETRIC design knob
  (a bend curvature via `hb.add_bend`, a loop/skip count, a length) + a constraint: build design → relax (oxDNA) →
  measure → if unmet, adjust the knob → re-relax → … until met or budget exhausted. **Three-Layer Law:** vary
  TOPOLOGY only; never write oxDNA output back. **Augment:** on a fixture where the knob monotonically maps to the
  measurement (mock binary returns a deterministic geometry as a function of the knob → the *search* is testable
  without a GPU), assert the loop converges into the tolerance band in ≤ N iterations. **ASK-FIRST (heavily):**
  which knobs may vary, the search strategy (bisection / gradient / grid), and how stochastic re-run variance is
  separated from knob effect — all design decisions. Large; decompose further when reached. Builds on Phases 1–3 +
  the AF-11 build-spec interpreter + the AF-6 deformation wrappers.

### Tier F — frontend display subsystems (no REST route; JS-controller API + vitest-oracle augment)

**What's different here.** These subsystems are driven entirely client-side (a JS controller exposed on
`window.__*`), so the augment is **vitest oracles reading real Three.js state**, NOT a `headless_build`
wrapper. The anti-shovel rule still bites: assert the setter drove the *object* (a scene-graph light, a
`material.metalness`, a `pass.enabled`, a `camera.fov`), never `getSettings()` (which just echoes stored
intent → a passthrough). Bound by `FEATURE_DEVELOPMENT.md` — lands in the subsystem module + its
`*.test.js`, never a god-file.

- [x] **AF-PHOTO (P-A + P-B) — photomode option-coverage + effect oracles. SHIPPED 2026-06-18.** `frontend/src/scene/photo_renderer.test.js` (39 tests): P-A drives each setter and asserts the REAL object (renderer.toneMapping/exposure, scene-graph lights, `material.metalness`, `camera.fov`, composer `pass.enabled` via the new `getComposerState()`); P-B is the automation contract (getSettings is a copy; a 21-case table proves every option is settable through the API + every key persists). Shipped alongside the R1–R5 render fixes from the audit (tone mapping + exposure, Sun-sole, env re-bake isolation, emissive bloom clamp, Reflector state isolation). Remaining: P-C GPU-truth e2e → `MV-PHOTO-1`/`MV-PHOTO-2` (manual-validation debt). Below is the original intake item.
- [ ] **AF-PHOTO — photomode option-coverage + effect oracles.** Photo mode
  ([frontend/src/scene/photo_renderer.js](frontend/src/scene/photo_renderer.js), ~1588 ln, ~45 setters on
  `window.__photoRenderer`) has **zero test coverage**; no automated proof any option takes effect, nor that
  the full option surface is reachable + persisted programmatically. **Enabling fact:** the controller can be
  built in jsdom with a real scene/camera + fake renderer and `activate({environment:'off'})`; the
  `EffectComposer` + passes *construct* without GL (only `.render()` / PMREM baking need WebGL), so even
  `bloomPass.enabled` / inscatter uniforms are vitest-assertable. **Phases:** (P-A) table-driven per-setter
  effect oracles in a new `photo_renderer.test.js` — see catalogue in `photo_mode_audit_plan.md` Part 3;
  (P-B) automation-contract oracles — setter⇄`getSettings` completeness + full profile round-trip; (P-C,
  MV-debt) GPU-truth e2e incl. the **yellow/purple no-tint regression** that guards the R1–R3 render fixes.
  **Validation gained, not a passthrough:** first proof photomode options reach the GPU-facing objects + the
  whole surface round-trips. Plan + per-setter table + the R1–R5 render-bug remediation in
  **`photo_mode_audit_plan.md`** (repo root, from the 2026-06-18 audit). Two MV rows queued:
  `MV-PHOTO-1` (no-tint regression render), `MV-PHOTO-2` (mid-session env-change garbage-frame guard).

### Appendix — genuinely UI-only (route these to manual-validation debt, NOT here)

Operations with no coord-taking route — they can only be hand-validated. When an AF session confirms one
is un-headless-able, push an `MV-N` row to `manual_validation_debt.md` instead of an AF item:
- Instance/strand **selection + lasso multi-select** (client store state, no backend reflection).
- **Gizmo intermediate drags** (TransformControls partial states; only the *committed* transform has a route).
- Pure **view toggles** (coloring, labels, periodic-boundary view) — no design mutation, nothing to validate.
