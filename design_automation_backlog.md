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

_Living pointer — each session overwrites this (step 8). AF-9 overhang-bindings sub-op shipped 2026-06-17._

**▶ NEXT — AF-10 instance layout helpers (grid / radial / ring placement).** Phase 3 (AF-9) is essentially
done: gears, belts, mate-seeded polymerize, and overhang-bindings all shipped (see metrics rows below). The one
Phase-3 straggler — **`polymerize_periodic`** — is fixture-blocked (the part needs `is_periodic_seam=True`
forced ligations the inline `make_6hb_design()` fixtures don't carry; build one via the route-for-polymerization
op headlessly first, then assert each copy sits at `T_seed @ derive_periodic_delta(design)^k` — likely its own
session). **AF-10 is the cleaner next step:** small pure placement helpers (e.g. `hab.place_grid(design, rows,
cols, *, pitch)` / `place_ring(design, n, *, radius)`) that drive `add_instance` per cell at computed
transforms. **Augment:** a geometric oracle on the placement lattice — assert each instance origin lands on the
exact grid/ring (spacing == pitch, radius exact, count exact, angular step == 2π/n), id-independent. The
placement math is a pure `backend/core` candidate (mirror `circle_primitive`), with the oracle reading the
*placed* instance transforms (not the spec) — the AF-4 "measure the result, not the footprint" pattern.
After AF-10: AF-11 the DSL (Tier 4).

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
- [ ] **AF-10 — instance layout helpers** (grid / radial / ring placement) for parametric assembly gen.
  **Augment:** geometric oracle on the placement lattice (spacing / radius / count exact).

### Tier 4 — text-to-DNA-origami groundwork (the eventual goal; built ON the validated wrapper library)

- [ ] **AF-11 — declarative build-spec interpreter.** A JSON/DSL design spec → a `headless_build` /
  `headless_assembly_build` call sequence. **Augment:** every spec round-trips through
  `assert_roundtrip_stable` (AF-1); a corpus of spec→design golden pins. *Depends on Tiers 1–3 wrappers.*

### Appendix — genuinely UI-only (route these to manual-validation debt, NOT here)

Operations with no coord-taking route — they can only be hand-validated. When an AF session confirms one
is un-headless-able, push an `MV-N` row to `manual_validation_debt.md` instead of an AF item:
- Instance/strand **selection + lasso multi-select** (client store state, no backend reflection).
- **Gizmo intermediate drags** (TransformControls partial states; only the *committed* transform has a route).
- Pure **view toggles** (coloring, labels, periodic-boundary view) — no design mutation, nothing to validate.
