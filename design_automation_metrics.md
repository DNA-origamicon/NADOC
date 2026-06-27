# design-automation metrics + data archive

Archive split out of `design_automation_log.md` (2026-06-25) to keep that file readable in one pass.
**Read on demand only** — a per-loop session does NOT need this. It holds the per-item **metrics rows**
(one per shipped AF item, with the mandatory justification line) and the **data summaries** (plots + fits).
The oracle catalog, lessons, and difficulties ledger stay in `design_automation_log.md`.

---

## Metrics rows (one per shipped AF item)

_Format: **AF-N — <op>** · shape (wrapper/new-module/service) · headless-coverage Δ · god-file LOC Δ ·
oracle shipped · tests (pass count) · **"Validation gained, not just a passthrough: ___."**_

**AF-1 — round-trip validation harness + coverage report** · _shape:_ new shared test module
`tests/automation_harness.py` (NOT a god-file; `crud.py`/`assembly.py`/`main.js` LOC Δ = **0**;
`test_section_router.py` net **−21** lines, its `_canonical_topology` deduped into the harness) ·
_headless-coverage Δ:_ first measurement — **11 / 239** design+assembly mutation routes wrapped (the audit
is now `headless_coverage_report()`, automated, so this number self-updates) · _oracles shipped:_
`canonical_topology` (promoted), `roundtrip_nadoc` (real `to_json`→`POST /design/import`, scratch-isolated),
`assert_roundtrip_stable` (validate→round-trip→validate + fingerprint-equal, injectable `roundtrip` seam),
`headless_coverage_report` (route↔wrapper by **function-object identity**) · _tests:_ 8 new in
`test_automation_harness.py` (full suite **2206 passed / 55 skipped**, no drop) ·
**"Validation gained, not just a passthrough:** before AF-1 there was *no* reusable way to assert a headless
build is correct — now any wrapper pins itself with one line (`assert_roundtrip_stable(build_fn)`) proving
its output validates AND survives a real `.nadoc` save/load unchanged, and the load-bearing meta-test proves
that oracle actually *raises* on a corrupted round-trip (a green that can go red). The coverage report turns
the manual route-vs-wrapper grep into a function-identity audit that can't go stale.**"

---

**AF-2 — nick / ligate / delete-strand wrappers** · _shape:_ 3 wrappers in `backend/api/headless_build.py`
(each imports the exact route handler — `add_nick` / `ligate_strand` / `delete_strand` — so they register as
covered by function identity, NOT re-implemented) + 1 reusable oracle `assert_inverse_pair` in
`tests/automation_harness.py`; `crud.py`/`assembly.py`/`main.js` LOC Δ = **0** · _headless-coverage Δ:_
**11 → 14 / 239** (nick + ligate + delete-strand flipped to covered) · _oracle shipped:_ `assert_inverse_pair(
start, forward, inverse)` — op∘inverse is canonical-topology-identity AND the mid-state must differ from start
(the "forward really mutated" guard that lets it go red); delete additionally pinned by canonical strand-set
subtraction (exactly one entry removed, helices untouched) + `assert_roundtrip_stable` reuse · _tests:_ 5 new
in `test_headless_build.py` + 4 new in `test_automation_harness.py` (incl. two red-tests proving
`assert_inverse_pair` raises on a non-restoring inverse and on a vacuous no-op forward); full suite **2215
passed / 55 skipped**, no drop · **"Validation gained, not just a passthrough:** nick/ligate now carry a
*proven* inverse-pair invariant (nick a strand, ligate it back, the topology fingerprint is byte-identical) —
nothing previously asserted that the two ops compose to identity, and the oracle's mutate-guard means a
wrapper that silently no-ops fails. The oracle is reusable for every future +δ↔−δ / add↔delete pair (AF-3
loop/skip is the next consumer).**"

**AF-3 — loop/skip insert + apply-deformations wrappers** · _shape:_ 2 wrappers in
`backend/api/headless_build.py` (`loop_skip` imports `insert_loop_skip`; `apply_loop_skip_deformations`
imports `apply_loop_skips_from_deformations` — exact route handlers, so they register as covered by function
identity) + 1 reusable oracle `assert_geometric_length_delta` (+ `geometric_nucleotide_count`) in
`tests/automation_harness.py`; `crud.py`/`assembly.py`/`main.js` LOC Δ = **0** · _headless-coverage Δ:_
**14 → 16 / 239** (loop-skip/insert + loop-skip/apply-deformations flipped to covered) · _oracle shipped:_
`assert_geometric_length_delta(start, op, expected_bp_delta, *, helix_id=None, strands_per_bp=2)` — asserts the
geometry kernel's (`_geometry_for_design`) nucleotide count changes by exactly the declared bp delta × 2
strands; **direction-agnostic** (counts magnitude, not bend sign → no three-layer sign reasoning, stays clear
of the ASK-FIRST rule); per-`helix_id` scoping gives the strong conservation check for bulk apply · _tests:_ 6
new in `test_headless_build.py` (loop +1 → +1 bp, skip −1 → −1, delta=0 restores, loop survives `.nadoc`
round-trip, SQUARE apply-deformations per-helix conservation, coverage flip) + 2 new in
`test_automation_harness.py` (oracle passes on a real loop; **load-bearing red-test**: claiming +2 for a +1
loop raises); full suite **2223 passed / 55 skipped**, no drop · **"Validation gained, not just a passthrough:**
loop/skip now carries a *proven* topology→geometry conservation law — a loop adds exactly one bp of rendered
geometry per strand, a skip removes one, delta=0 restores, and bulk apply-deformations is honoured helix-by-helix
(no mark leaks or is dropped). Nothing previously asserted that the geometry layer faithfully reflects loop/skip
marks; critically, `canonical_topology` is *blind* to loop/skips, so the round-trip oracle alone could never have
caught a dropped mark — the geometric count is the only thing that proves persistence, and the red-test proves
the oracle can fail.**"

**AF-4 — parametric circle (`circle-segment`) wrapper** · _shape:_ 1 wrapper in `backend/api/headless_build.py`
(`circle_segment` imports `add_circle_segment as _route_circle_segment` — exact route handler, registers as
covered by function identity; computes the footprint via `circle_primitive.circle_footprint`, the SAME analytic
the JS preview mirror uses, then drives the route) + 1 reusable oracle `assert_circular_disc` in
`tests/automation_harness.py`; `crud.py`/`assembly.py`/`main.js` LOC Δ = **0** · _headless-coverage Δ:_
**16 → 17 / 239** (circle-segment flipped to covered) · _oracle shipped:_ `assert_circular_disc(design,
requested_radius_nm, *, max_spread_nm=0.5, radius_tol_nm=0.5, helix_ids=None)` — a **geometric** oracle (not a
count/round-trip one): it reads the *placed* helices' axis-endpoint spans (Euclidean, plane-agnostic), orders
them by lattice column, and feeds them to the existing circularity functions (`circularity_spread`, `fit_radius`
from `core/circle_primitive`) — asserting the built disc's per-column implied radii agree to <0.5 nm AND that
asking for radius R lands a disc of radius ≈R (within 0.5 nm). Empirically the generated discs hold
spread ≤0.29 nm and fit error ≤0.1 nm across R∈{6,8,10.6,14,20} · _tests:_ 6 new in `test_headless_build.py`
(parametrized circularity over 5 radii, round-trip stable, radius-too-small→ValueError-no-mutation,
additive-over-existing-DNA, coverage flip, + a **load-bearing red-test**: stretching the centre helix's axis
makes `assert_circular_disc` raise "not circular") + repointed the AF-1 coverage meta-test from circle-segment
(now covered) to `bundle-deformed-continuation` (AF-5, still uncovered); full suite **2233 passed / 55 skipped**,
no drop · **"Validation gained, not just a passthrough:** before AF-4, `tests/test_circle_primitive.py` pinned
the footprint *math* (pure `circle_footprint`) and the route *separately* (with hand-passed cells) — nothing
asserted that handing a builder a **radius** yields placed geometry that is actually circular *of that radius*.
`assert_circular_disc` closes that gap by measuring the real axis geometry the route laid down (so a builder that
silently dropped a column, mis-centred a helix, or used the wrong column pitch would fail), and the red-test
proves the oracle goes red on a mangled disc. It's reusable for any future parametric-shape primitive whose
spec is 'a profile of per-column lengths.'**"

**AF-5 — deformed-continuation wrapper** · _shape:_ 1 wrapper in `backend/api/headless_build.py`
(`bundle_deformed_continuation` imports `add_bundle_deformed_continuation as _route_deformed_continuation` —
exact route handler, registers as covered by function identity — and `get_deformed_frame as
_route_deformed_frame` to sample the frame; it POSTs *with* `source_bp` so the route re-derives the frame
server-side, the replayable path, exactly mirroring the UI's `getDeformedFrame`→`addBundleDeformedContinuation`)
+ 1 reusable oracle `assert_on_deformed_frame` in `tests/automation_harness.py`; `crud.py`/`assembly.py`/
`main.js` LOC Δ = **0** · _headless-coverage Δ:_ **17 → 18 / 239** (bundle-deformed-continuation flipped to
covered) · _oracle shipped:_ `assert_on_deformed_frame(before, after, source_bp, cells, *, ref_helix_id=None,
pos_tol_nm=0.02, min_deflection_nm=0.5)` — a **geometric** oracle: it independently re-derives the deformed
cross-section frame (`deformed_frame_at_bp` on the pre-continuation design, the same input the route uses when
`source_bp` is set) and the per-cell placement `grid_origin + frame_right·lx + frame_up·ly`, asserts every
appended helix's `axis_start` lands there (< 0.02 nm), AND — the can-go-red guard — that the deformed placement
is displaced > 0.5 nm from the straight-frame placement (frame recomputed on a deformations-stripped copy), so
the oracle goes red on an un-deformed design instead of passing vacuously. Direction-agnostic (measures *that*
it moved + *where* it landed, never bend sign → stays clear of the ASK-FIRST rule) · _tests:_ 2 new in
`test_headless_build.py` (lands-on-deformed-frame green, coverage flip) + 3 new in `test_automation_harness.py`
(oracle passes on a real bent continuation; **two load-bearing red-tests**: a helix dragged off the frame
raises "did not land on the deformed", and a straight (un-bent) continuation raises the "had no geometric
effect" deflection guard) + repointed the AF-1 coverage meta-test from bundle-deformed-continuation (now
covered) to `/design/deformation` (AF-6, still uncovered); full suite **2238 passed / 55 skipped**, no drop ·
**"Validation gained, not just a passthrough:** before AF-5, `test_deformed_continuation_replace.py` checked
only that the appended helix's axis *direction* was non-axial (a coarse "looks bent" sign) and that
delete/edit of the bend re-placed it. Nothing asserted the placed helix *origins* match the analytically
re-derived deformed cross-section frame, nor quantified that they are displaced from a straight extrude.
`assert_on_deformed_frame` closes that by measuring the real placed geometry against an independent frame
derivation (so a builder that swapped frame_right/up, used the wrong lattice pitch, or silently fell back to
the straight blunt-end would fail) with a deflection guard proving it can't pass on a non-deformed build. It's
reusable for any future op that places geometry on a sampled deformed frame.**"

**AF-6 — bend / twist by constraint** · _shape:_ 2 wrappers in `backend/api/headless_build.py`
(`add_bend` / `add_twist` import `add_deformation as _route_add_deformation` + `AddDeformationBody` from
`routes_deformation` — exact route handler, registers as covered by function identity; `add_twist` validates
the `total_degrees` XOR `degrees_per_nm` mutual exclusion before the call) + 1 reusable oracle
`assert_deformation_angle` in `tests/automation_harness.py`; `crud.py`/`assembly.py`/`main.js` LOC Δ = **0** ·
_headless-coverage Δ:_ **18 → 19 / 239** (`POST /design/deformation` flipped to covered) · _oracle shipped:_
`assert_deformation_angle(design_after, plane_a_bp, plane_b_bp, expected_total_deg, *, ref_helix_id=None,
angle_tol_deg=1.0, step_bp=1, min_angle_deg=5.0)` — a **geometric MAGNITUDE** oracle: it samples the deformed
cross-section frame (`deformed_frame_at_bp`, the orthonormal `[frame_right|frame_up|axis_dir]`) at each bp from
`plane_a` to `plane_b` and SUMS the magnitude of each step's relative frame rotation
(`arccos((tr(R₁R₀ᵀ)−1)/2)`). Summing per-step magnitudes — not the single endpoint-to-endpoint relative
rotation — **unwraps** angles past 180°/360° (the single-rotation form folded a 400.8° twist to 40.8°; a 540°
twist to 180°). Asserts the total = the requested θ (κ×(b−a) for a bend; total twist for a twist) within
`angle_tol_deg`, plus a can-go-red guard `total > min_angle_deg` (fails on an un-deformed design). **Direction
-AGNOSTIC** (an `arccos` magnitude, never sign/handedness) → no ASK-FIRST violation; the signed-curvature/
closure oracle the backlog floated (`solve_closing_curvature`) was **deliberately not built** · _tests:_ 7 new
in `test_headless_build.py` (bend realises κ×Δbp; bend 200° unwraps past 180; twist `total_degrees`; twist
540° unwraps past 360; twist `degrees_per_nm` rate; `add_twist` XOR-spec ValueError-no-mutation; coverage
flip) + 4 new in `test_automation_harness.py` (af6-covered + oracle passes on a real bend + **two load-bearing
red-tests**: wrong expected θ raises "does not match the request", and a straight bundle raises the
"un-deformed" vacuity guard) + repointed the AF-1 coverage meta-test from `/design/deformation` (now covered)
to `/design/cluster` (still uncovered); full suite **2249 passed / 55 skipped**, no drop ·
**"Validation gained, not just a passthrough:** before AF-6 nothing pinned that asking for a bend of curvature
κ over an N-bp window actually rotates the geometry by κ·N degrees — `test_deformed_continuation_replace.py`
only checked a bend was "non-axial" (a coarse looks-bent sign). `assert_deformation_angle` closes that by
measuring the realised frame rotation against the user-meaningful request (so a builder that mis-scaled κ,
ignored the planes, or dropped the op fails), works for both bend and twist via one frame-rotation metric, and
its per-step summation correctly handles large angles the naive relative-rotation form silently folds. The
two red-tests prove it goes red on a wrong angle and on a non-deformed build.**"

**AF-7 — headless ASSEMBLY builder (Phase 1: place + resolve + round-trip)** · _shape:_ **NEW module**
`backend/api/headless_assembly_build.py` (the first assembly-layer headless builder — mirrors `headless_build.py`:
`assembly_scratch_session` + `new_assembly` + `add_inline_instance`/`add_file_instance`/`add_instance` +
`resolve` + `import_assembly`, each importing the exact route handler — `create_assembly` / `add_instance` /
`resolve_assembly` / `import_assembly` — so they register as covered by function identity, NOT re-implemented)
+ 3 reusable oracles (`canonical_assembly`, `roundtrip_nass`, `assert_assembly_roundtrip_stable`) in
`tests/automation_harness.py`; `headless_coverage_report` extended to scan BOTH `headless_build` and the new
module; `crud.py`/`assembly.py`/`main.js` LOC Δ = **0** (zero god-file growth — all new code is a new module +
the test harness) · _headless-coverage Δ:_ **19 → 23 / 239** (create + add-instance + resolve + import all flip) ·
_oracle shipped:_ `assert_assembly_roundtrip_stable(build_fn, *, roundtrip=roundtrip_nass)` — the assembly analog
of `assert_roundtrip_stable`: validates the built assembly (`validate_assembly_report` — file sources resolve,
joint refs/limits hold, ids unique, flatten ok), round-trips it through the **real** `POST /assembly/import`
(`roundtrip_nass`: `to_json` v2 → import, **in-memory**, inline part designs travel inside the payload — no
workspace files), re-validates, and asserts the **id/order-independent** `canonical_assembly` fingerprint is
unchanged (instances keyed by source fingerprint — inline → the embedded design's `canonical_topology`, file →
path+sha — plus the world transform + mode/rep/fixed/visible; joints keyed by type+connector-labels+value for
AF-8). Injectable `roundtrip=` seam so the meta-test feeds a part-dropping round-trip and proves it raises ·
_tests:_ 7 new in `test_headless_assembly_build.py` (inline two-part round-trip stable, placement transform
survives, canonical order-independent + placement-sensitive, resolve no-op without joints, file-source structural,
coverage flip) + 4 new in `test_automation_harness.py` (af7-covered + oracle passes on a real build + **two
load-bearing red-tests**: a dropped-part round-trip raises "changed the assembly structure", a missing-file source
raises "did not validate before round-trip"); full suite **2260 passed / 55 skipped**, no drop ·
**"Validation gained, not just a passthrough:** before AF-7 there was *no way at all* to build an assembly without
a browser, and therefore no way to pin assembly construction — `headless_build` stopped at the design layer.
`assert_assembly_roundtrip_stable` is the first assembly correctness oracle: it proves a scripted multi-part
placement validates AND that every part, at its exact world transform, survives a real `.nass` save/load with an
identical id-independent fingerprint (so a builder that dropped a part, garbled a transform, or lost an inline
design would fail), with a red-test proving the green can go red. It is the spine the AF-8+ mate/joint, gear/belt,
and layout wrappers pin themselves against — the assembly analog of what AF-1 did for designs.**"

**AF-8 — headless mate/joint by connector labels** · _shape:_ 2 wrappers in
`backend/api/headless_assembly_build.py` (`add_connector` imports the `add_connector` route handler from
`routes_assembly_connectors`; `define_mate` imports `create_mate` + `CreateMateRequest`/`MateConnectorSpec` from
`routes_assembly_joints` — exact route handlers, registers covered by function identity, NOT re-implemented) + 1
reusable oracle `assert_mate_coincident` in `tests/automation_harness.py` + enriched `canonical_assembly`'s joint
key; `crud.py`/`assembly.py`/`main.js` LOC Δ = **0** (all new code is the existing new module + the harness) ·
_headless-coverage Δ:_ **23 → 25 / 239** (`POST /assembly/instances/{id}/connectors` + `POST
/assembly/joints/create-mate` flip to covered) · _oracle shipped:_ `assert_mate_coincident(assembly, joint_id, *,
tol_nm=0.01, min_offset_nm=0.5)` — a **geometric** oracle: it resolves the two mated connectors' world positions
with the SAME `_get_connector_world` machinery `resolve_assembly` uses (on the instance-overridden design, so it's
the real resolve definition of "where the connector is", not a re-derivation) and asserts they coincide within
`tol_nm`, plus a non-triviality guard that the two mated part *origins* are separated by > `min_offset_nm` (so the
coincidence is genuine alignment work on offset parts, not the vacuous both-stacked-at-origin case — the mate analog
of `assert_inverse_pair`'s "forward really mutated" guard). Also enriched `canonical_assembly`'s joint key from
`(type, conn_a, conn_b, value)` to additionally carry the two mated instances' *source fingerprints*
(id-independent), so the round-trip fingerprint detects a mate rewired to a different part · _tests:_ 5 new in
`test_headless_assembly_build.py` (mate makes connectors coincident, coincidence survives `resolve()`, mated
assembly round-trips stable WITH its joint + still coincident after re-import, dropping the mate changes the
fingerprint, + a **load-bearing red-test**: shoving the child +30 nm after the mate makes the oracle raise "not
coincident") + 4 new in `test_automation_harness.py` (af8-covered + oracle passes on a real mate + **two
load-bearing red-tests**: separated connectors raise "not coincident", stacked-at-origin parts raise the "trivial"
vacuity guard); full suite **2269 passed / 55 skipped**, no drop · **"Validation gained, not just a passthrough:**
before AF-8 there was no way to mate parts headlessly, and nothing pinned that a mate actually snaps its two
connectors together — `assert_assembly_roundtrip_stable` (AF-7) checks the assembly *structure* survives save/load
but is blind to whether the joint's geometric promise (connector coincidence) holds. `assert_mate_coincident`
closes that by measuring the real connector world positions the resolver computes and asserting they coincide on an
offset pair of parts (so a builder that registered the joint but failed to snap, or snapped to the wrong connector,
fails), with a vacuity guard + red-tests proving the green can go red. It's the resolve-invariant spine the AF-9
gear/belt/polymerize wrappers pin themselves against (each is 'after resolve, this relation holds').**"

**AF-9 — gears (Tier 3 Phase 3, gear sub-op): `define_gear` + `drive_joint` + ratio oracle** · _shape:_ 2 wrappers
in `backend/api/headless_assembly_build.py` (`define_gear` imports `create_gear_relation` + `CreateGearRelationRequest`
from `routes_assembly_gears`; `drive_joint` imports `patch_joint` + `PatchJointRequest` from `routes_assembly_joints`
— exact route handlers, registers covered by function identity) + 1 reusable oracle `assert_gear_ratio` in
`tests/automation_harness.py` + enriched `canonical_assembly` to fingerprint `gear_relations` (now returns a 3-tuple
`(instances, joints, gears)`); `crud.py`/`assembly.py`/`main.js` LOC Δ = **0** (all new code is the existing new
module + the harness) · _headless-coverage Δ:_ **25 → 27 / 239** (`POST /assembly/gear-relations` + `PATCH
/assembly/joints/{id}` flip to covered) · _oracle shipped:_ `assert_gear_ratio(assembly_before, assembly_after,
rel_id, *, expected_ratio, ratio_tol=0.02, min_angle_deg=2.0)` — a **geometric resolve-invariant** oracle: after
driving one side of the gear (`drive_joint`, whose PATCH auto-propagates the relation), it measures the two coupled
bodies' real **instance-transform rotation magnitudes** (relative rotation `arccos((tr(R₁R₀ᵀ)−1)/2)` of each gear-
endpoint instance, picked via `_gear_endpoint_side`) and asserts driven/driver = `|expected_ratio|`, with a can-go-red
"driver actually rotated > min_angle" guard (a no-op gear makes the ratio `0/0`). Measures the placed geometry, NOT
`joint.current_value` — so it is not a re-test of the route's own `θ_b = ratio·θ_a` arithmetic. **Direction-agnostic**
(magnitude only → no ASK-FIRST sign/handedness reasoning; `invert` flips the driven body's direction but not the
magnitude ratio). Also enriched `canonical_assembly` to key each `GearRelation` by its two coupled joints' id-
independent fingerprints + ratio/invert/anchors, so `assert_assembly_roundtrip_stable` now catches a dropped/rewired
gear · _tests:_ 6 new in `test_headless_assembly_build.py` (gear drives coupled wheel at ratio 2, fractional ratio
0.5, invert flips sign not magnitude, gear-over-rigid-mates 400s, geared assembly round-trips stable WITH its gear,
canonical distinguishes a gear) + 4 new in `test_automation_harness.py` (af9-covered + oracle passes on a real gear +
**two load-bearing red-tests**: reverting the driven wheel's transform raises "did not propagate", and an undriven
assembly raises the "nothing was driven" guard); full suite **2279 passed / 55 skipped**, no drop ·
**"Validation gained, not just a passthrough:** before AF-9 there was no way to couple parts headlessly, and nothing
pinned that a gear relation actually *drives* its coupled body — `assert_assembly_roundtrip_stable` (AF-7/8) checks the
gear's structure survives save/load but is blind to whether its kinematic promise (the angular ratio) holds when you
spin one wheel. `assert_gear_ratio` closes that by driving one side and measuring the *other body's real rotation*
against the promised ratio (so a builder that registered the gear but failed to propagate, or used the wrong ratio,
fails), with a can-go-red guard + two red-tests proving the green can go red. It's the resolve-invariant spine the
belt/polymerize sub-ops pin themselves against — a belt IS a gear-equivalent coupling (`_belt_to_relation`), so it
should reuse this same oracle with `expected_ratio = r_a/r_b`.**"

**AF-9 — belts (Tier 3 Phase 3, belt sub-op): `define_belt` + generalised ratio oracle** · _shape:_ 1 wrapper
in `backend/api/headless_assembly_build.py` (`define_belt` imports `create_belt_path` +
`CreateBeltPathRequest`/`BeltPulleyRequest` from `routes_assembly_belts` — exact route handler, registers
covered by function identity) + **generalised** the existing `assert_gear_ratio` oracle (now searches
`_coupling_relations`, which folds belt-derived relations in, instead of only `assembly.gear_relations`) +
extended `canonical_assembly` to fingerprint `belt_paths` (return is now a **4-tuple**
`(instances, joints, gears, belts)`); `crud.py`/`assembly.py`/`main.js` LOC Δ = **0** (all new code is the
existing new module + the harness) · _headless-coverage Δ:_ **27 → 28 / 239** (`POST /assembly/belt-paths`
flips to covered) · _oracle shipped:_ reused `assert_gear_ratio(before, after, rel_id, *, expected_ratio)` with
the belt's synthetic relation id `f"__belt__{belt.id}"` and `expected_ratio = radius_a/radius_b` — it measures the
two coupled pulleys' real **instance-transform rotation magnitudes** after driving one side and asserts
driven/driver = `|r_a/r_b|`, with the same can-go-red "driver actually moved" guard. The generalisation
(search `_coupling_relations`, not just stored gears) is backward-safe: gears are first in that list, so every
existing gear test is unchanged · _tests:_ 5 new in `test_headless_assembly_build.py` (belt drives pulley at
radius ratio 2, 3:1 ratio, belt-over-rigid-mates 400s, belted assembly round-trips stable WITH its belt,
canonical distinguishes a belt) + 3 new in `test_automation_harness.py` (af9-belt-covered + oracle passes on a
real belt + a **load-bearing red-test**: reverting the belt-driven pulley's transform raises "did not
propagate"); full suite **2287 passed / 55 skipped**, no drop · **"Validation gained, not just a passthrough:**
before this, nothing proved that defining a belt with rim radii `r_a`/`r_b` actually couples its two pulleys at
angular ratio `r_a/r_b` — the belt→`GearRelation` synthesis (`_belt_to_relation`, which derives the ratio AND the
world-sense `invert` from the radii/sides/axes and folds the belt into propagation) was untested via a headless
build. The gear test (AF-9 gears) hand-passes a literal ratio; the belt test passes *radii* and asserts the
*derived* ratio drives the coupled body — so if `_belt_to_relation` computed `r_b/r_a`, dropped the belt from
`_coupling_relations`, or got the sign wrong, the belt test goes red while the gear test stays green. That is
distinct, new validation power, and the red-test proves the green can go red. `canonical_assembly` now also
catches a dropped/rewired belt in the round-trip fingerprint.**"

**AF-9 — polymerize (Tier 3 Phase 3, mate-seeded sub-op): `polymerize` + chain-lattice oracle** · _shape:_ 1
wrapper in `backend/api/headless_assembly_build.py` (`polymerize` imports `polymerize_assembly` +
`PolymerizeAssemblyRequest` from `routes_assembly_polymerize` — exact route handler, registers covered by
function identity) + 1 reusable oracle `assert_polymer_chain` in `tests/automation_harness.py`;
`canonical_assembly` **unchanged** (it already fingerprints instances+joints, and polymerize adds NO new
top-level relation list — so the round-trip oracle catches a dropped copy/joint with no extension, unlike
gears/belts); `crud.py`/`assembly.py`/`main.js` LOC Δ = **0** (all new code is the existing new module + the
harness) · _headless-coverage Δ:_ **28 → 29 / 239** (`POST /assembly/polymerize` flips to covered) · _oracle
shipped:_ `assert_polymer_chain(before, after, seed_joint_id, *, count, direction="forward", tol_nm=0.01,
min_delta_nm=0.5)` — a **geometric** oracle: re-derives the seed mate's repeat `delta = T_B @ inv(T_A)` from the
seed pair's world transforms ALONE (NOT the route's `compute_chain_transforms` — an independent derivation, so it
is not a tautology re-running the implementation), then asserts the `count−2` new instances form the exact
`delta`-power multiset (`delta^k @ T_B` forward / `inv(delta)^k @ T_A` backward) matched id-independently within
`tol_nm`, plus a can-go-red guard that `‖delta translation‖ > min_delta_nm` (stacked seed pair → every copy lands
on the seed → the oracle would pass vacuously; the analog of `assert_mate_coincident`'s separation guard).
Direction-agnostic on handedness (re-derives the documented fwd/back split, checks placed geometry, never a
bend/twist sign) · _tests:_ 5 new in `test_headless_assembly_build.py` (length-4 chain on the +10 nm delta
lattice, length-6 chain, count-2 no-op, 422-on-non-identical-parts, polymerized chain round-trips stable WITH its
2 replicated joints, + the coverage-flip assertion extended) + 4 new in `test_automation_harness.py`
(af9-polymerize-covered + oracle passes on a real chain + **two load-bearing red-tests**: a copy shoved off the
lattice raises "repeat", and a stacked seed pair raises the "~identity" vacuity guard); full suite **2296 passed
/ 55 skipped**, no drop · **"Validation gained, not just a passthrough:** before this, nothing pinned that
mate-seeded polymerize lays its copies on a geometric progression — `test_polymerize.py` checked the pure chain
*math* (`compute_chain_transforms` with hand-fed matrices) and the route's *count*, but nothing asserted that a
**headless** build places `count−2` real instances at the seed mate's actual `delta`-power transforms. `assert_
polymer_chain` closes that by measuring the placed instance transforms against a `delta` re-derived solely from
the seed pair (so a builder that dropped a copy, used the wrong repeat, or mis-ordered the chain fails), with a
vacuity guard + two red-tests proving the green can go red. It's the resolve-invariant for any repeat-lattice
construction; `polymerize_periodic` will reuse the same 'each copy = `T_seed @ delta^k`' shape with `delta` from
`derive_periodic_delta` instead of the seed mate.**"

**AF-9 — overhang-bindings (Tier 3 Phase 3, binding sub-op): `bind/patch/unbind_overhangs` + integrity oracle**
· _shape:_ 3 wrappers in `backend/api/headless_assembly_build.py` (`bind_overhangs` imports
`create_assembly_overhang_binding`; `patch_binding` imports `patch_assembly_overhang_binding`;
`unbind_overhangs` imports `delete_assembly_overhang_binding` — all + their request models from
`routes_assembly_overhangs`, exact route handlers, registers covered by function identity) + 1 reusable oracle
`assert_binding_resolves` in `tests/automation_harness.py` + extended `canonical_assembly` to fingerprint
`overhang_bindings` (now returns a **5-tuple** `(instances, joints, gears, belts, bindings)`);
`crud.py`/`assembly.py`/`main.js` LOC Δ = **0** (all new code is the existing new module + the harness) ·
_headless-coverage Δ:_ **29 → 32 / 239** (`POST` + `PATCH` + `DELETE /assembly/overhang-bindings` flip to
covered) · _oracle shipped:_ `assert_binding_resolves(assembly, binding_id, *, require_cross_part=True)` — a
**referential-integrity** oracle: it loads each endpoint's part design with the route's OWN
`_load_design_from_source` and asserts both `(overhang_id, sub_domain_id)` refs resolve to a live overhang
sub-domain, plus a non-degenerate guard (the two endpoints are distinct `(instance, sub-domain)` pairs and, by
default, cross-part). The binding is pure topology metadata (no geometry to measure), so the property to pin is
ref validity — and crucially that it survives a `.nass` round-trip · _tests:_ 6 new in
`test_headless_assembly_build.py` (bind resolves; bound assembly round-trips stable WITH its binding AND still
resolves after re-import; unbind restores the pre-bind fingerprint; canonical distinguishes a binding; patch
changes mode + fingerprint; unknown-sub-domain 404) + 4 new in `test_automation_harness.py`
(af9-overhang-binding-covered + oracle passes on a real binding + **two load-bearing red-tests**: a binding
pointing at a dropped sub-domain raises "dropped sub-domain", and a degenerate self-pair binding raises
"sub-domain with itself"); full suite **2306 passed / 55 skipped**, no drop · **"Validation gained, not just a
passthrough:** before this, nothing pinned that a cross-part overhang binding's references stay valid — and
`assert_assembly_roundtrip_stable` *cannot* pin it, because `canonical_topology` (the inline-source fingerprint
`canonical_assembly` keys on) does NOT fingerprint a design's overhangs or sub-domains. So a round-trip that
regenerated a sub-domain id inside a part while the binding kept its stale id would slip past the structure
fingerprint entirely; `assert_binding_resolves` is the only thing that catches it, by resolving the binding's
endpoints against the actual round-tripped part designs. The two red-tests prove the green can go red. It's the
referential-integrity spine for any future metadata-only cross-part relation (assembly overhang *connections*
next).**"

**`polymerize_periodic` straggler — `polymerize_periodic` wrapper + seamless-tiling oracle** · _shape:_ 1 wrapper
in `backend/api/headless_assembly_build.py` (`polymerize_periodic` imports `polymerize_periodic_assembly` +
`PolymerizePeriodicRequest` from `routes_assembly_polymerize` — exact route handler, registers covered by function
identity) + 1 reusable oracle `assert_periodic_chain_tiles` in `tests/automation_harness.py`;
`crud.py`/`assembly.py`/`main.js` LOC Δ = **0** (all new code is the existing new module + the harness) ·
_headless-coverage Δ:_ **36 → 37** (`POST /assembly/polymerize-periodic` flips to covered) · _oracle shipped:_
`assert_periodic_chain_tiles(assembly, *, tol_nm=0.05, step_tol_nm=0.05, angle_tol_deg=0.5, min_step_nm=0.5)` —
a **geometric resolve-invariant** oracle over the chain's synthesized rigid `seam0:*` junctions: ≥1 junction
(non-emptiness) + **seamless tiling** (copy-k `seam0:3p` world ≈ copy-(k+1) `seam0:5p` world via the resolver's
OWN `_get_connector_world` on the instance-overridden design) + **single repeat unit** (every junction's
`T_high@inv(T_low)` shares one translation length + rotation angle — magnitudes-only → direction-agnostic, holds
for `both`) + step>`min_step_nm` non-vacuity guard. This is the PERIODIC (auto-derived-delta, single-seed) analog
distinct from `assert_polymer_chain` (mate-seeded, delta re-derived from two instances). Fixture turned out light:
a 2-helix HC bundle + two `_seam_for` `is_periodic_seam` ligations (mirrors `test_periodic_polymer.py`). **NO
ASK-FIRST** — coincidence + magnitude comparisons only, no bend/twist sign · _tests:_ 5 new in
`test_headless_assembly_build.py` (forward chain tiles + 3 junctions + ~0° rotation; `both`-direction tiles;
periodic chain round-trips stable; no-seam part 422s; coverage flip) + 4 new in `test_automation_harness.py`
(periodic-route-covered + oracle passes on a real chain + **two load-bearing red-tests**: a copy shoved off the
chain raises "open", a lone un-polymerized seed raises "nothing was polymerized") + bumped the hardcoded coverage
count 36→37 in 3 pre-existing `adds_no_coverage`/`oxdna_coverage` tests; full suite **3002 passed / 55 skipped**,
no drop · **"Validation gained, not just a passthrough:** before this, the SINGLE-part periodic chain had a route
but no headless entry and no reusable oracle — and `assert_assembly_roundtrip_stable`/`canonical_assembly` (AF-7)
prove the chain's *structure* survives `.nass` but are BLIND to whether the AUTO-DERIVED repeat transform actually
*tiles* (a wrong delta — e.g. the historical spiral bug — would round-trip fine while the seams gape).
`assert_periodic_chain_tiles` closes that by measuring real seam-connector coincidence at EVERY junction (not just
the seam the delta was fit on) plus the single-repeat-unit invariant that makes a chain *periodic* rather than a
bag of mates, with two red-tests proving the green can go red. It's the seam-tiling spine for any future
auto-derived repeating chain (belt-seam closure, ring-closure checks).**"

**AF-10 — instance layout helpers (grid / ring): `place_grid` + `place_ring` + lattice oracles** · _shape:_
**NEW pure core** `backend/core/instance_layout.py` (`grid_translations` / `ring_translations` — spec→world
translations, plane in {XY,XZ,YZ}, identity orientation; mirrors `circle_primitive`) + 2 construction-sugar
wrappers in `backend/api/headless_assembly_build.py` (`place_grid` / `place_ring` — compute the per-slot
translations then drive the existing `add_inline_instance` once per slot) + 2 reusable oracles
(`assert_instances_on_grid`, `assert_instances_on_ring`) in `tests/automation_harness.py`;
`crud.py`/`assembly.py`/`main.js` LOC Δ = **0** (all new code is a new core module + the existing headless module
+ the harness) · _headless-coverage Δ:_ **32 → 32** (UNCHANGED — the layout helpers wrap NO new route; they
compose the already-covered `add_instance`, so this item moves the oracle count, not the coverage count — a
construction-sugar item, not a route-wrapper item) · _oracles shipped:_ `assert_instances_on_grid(assembly,
rows, cols, *, pitch, row_pitch=None, plane="XY")` + `assert_instances_on_ring(assembly, n, *, radius,
plane="XY", center=…)` — both **geometric** oracles reading the *placed* instance origins (not the layout spec):
grid asserts the origins occupy exactly `cols` distinct columns × `rows` distinct rows, evenly spaced by
`pitch`/`row_pitch`, with every cell filled; ring asserts every origin is at `radius` from `center` with an even
`360°/n` angular step. The expected lattice is re-derived from the user-facing params as *properties* of the
result, never by re-running the placement formula, so a builder bug (wrong pitch, dropped slot, transposed axes)
is caught not mirrored. Each carries a non-degeneracy guard; the ring's `radius>min_radius` guard is
load-bearing (radius=0 stacks every part at `center` where `dist==radius==0` passes vacuously) · _tests:_ 17 new
in `test_instance_layout.py` (pure formula: grid count/spacing/centring/plane/reject + ring radius/step/
start-angle/center/plane/reject) + 4 new in `test_headless_assembly_build.py` (grid lands + rectangular grid
round-trips, ring lands + offset-centre XZ-plane ring round-trips) + 9 new in `test_automation_harness.py`
(helpers-compose + grid passes/off-lattice-fires/vacuity-guard + ring passes/off-ring-fires/vacuity-guard); full
suite **2334 passed / 55 skipped**, no drop · **"Validation gained, not just a passthrough:** before AF-10 there
was no way to lay out a parametric pattern of parts headlessly, and nothing pinned that a programmatic layout
places copies on a *regular* lattice. `assert_instances_on_grid` / `assert_instances_on_ring` close that by
measuring the real placed instance origins against the lattice the user asked for (so a builder that mis-scaled
the pitch, dropped a slot, used the wrong radius, or transposed the axes fails), with non-degeneracy guards +
red-tests (shoving one part off the grid/ring raises) proving the green can go red. The oracles are the
geometric spine the AF-11 DSL's layout specs will pin themselves against. NB: this is a construction-sugar item
(it wraps no route), so coverage is unchanged by design — the pass criterion was always the oracle, not a
coverage flip, and here that distinction is explicit.**"

**AF-11 — declarative build-spec interpreter (Phase 1): `build_design` / `build_assembly` + faithfulness oracle**
· _shape:_ **NEW pure core** `backend/core/build_spec.py` (`parse_design_spec` / `parse_assembly_spec` → ordered
`BuildOp` list; full grammar validation + assembly referential-integrity, NO execution, imports nothing from
`backend.api`) + **NEW driver** `backend/api/headless_spec_build.py` (`build_design` / `build_assembly` —
dispatch each parsed op to the REAL existing `hb.*` / `hab.*` wrappers; helices resolved by `grid_pos`, instances
by spec `ref`; nested part designs built via `build_design`) + 1 reusable oracle `assert_spec_matches_calls` in
`tests/automation_harness.py`; `crud.py`/`assembly.py`/`main.js` LOC Δ = **0** (all new code is two new modules +
the harness) · _headless-coverage Δ:_ **32 → 32** (UNCHANGED — the interpreter wraps NO new route; it composes
the already-covered design/assembly wrappers, so like AF-10 it moves the oracle count, not the coverage count) ·
_oracle shipped:_ `assert_spec_matches_calls(build_from_spec, build_by_hand, *, kind="design"|"assembly")` — the
**faithful-façade / golden-pin** oracle: it asserts a spec build produces the SAME id/order-independent fingerprint
(`canonical_topology` for design, `canonical_assembly` for assembly) as the equivalent hand-call wrapper sequence,
with a non-emptiness guard so it can't pass vacuously on a spec that builds nothing. Because the hand-call
reference is deterministic, "the spec matches the calls" IS the spec→canonical-fingerprint golden pin the backlog
asked for · _tests:_ 25 new in `test_build_spec.py` (pure grammar: design/assembly normalisation + ~20 parametrized
rejections — unknown op, typo'd key, bad types, dangling part/mate/connector refs, degenerate layout, propagated
bad part spec) + 15 new in `test_headless_spec_build.py` (6hb spec ≡ `make_6hb_design`; teeth spec ≡
`build_bundle` passes; round-trip stable; nick→ligate declarative identity; nick-alone mutates; unknown-grid_pos
raises; isolation; grid/ring/mate spec ≡ hand-call; mate coincident; mate round-trips; coverage stays 32) + 4 new
in `test_automation_harness.py` (oracle passes on a faithful build + **load-bearing red-tests**: a divergent build
raises "did not produce the same canonical", an empty build trips the vacuity guard, + assembly-kind); full suite
**2378 passed / 55 skipped**, no drop · **"Validation gained, not just a passthrough:** before AF-11 there was no
way to drive a build from a declarative spec, and — the real point — nothing proved that a spec is lowered to the
*same* build a person's clicks produce. `assert_spec_matches_calls` closes that: it pins that a JSON spec builds a
byte-identical canonical structure to the equivalent hand-call wrapper sequence, so the interpreter is provably a
faithful façade (it drives the real wrappers; it does NOT re-implement an op) — the exact guarantee the
text-to-DNA goal rests on. Separately, the PURE parser is itself new validation power: it rejects a malformed spec
(unknown op, typo'd field, a `mate` referencing an instance never added or a connector label that doesn't exist) at
parse time with a precise error, before any build runs — 20+ rejection pins. The red-tests prove the green can go
red. This is the Tier-4 capstone, and it's deliberately composition-only (coverage flat) — the pass criterion was
always the oracle.**"

**AF-11 — build-spec grammar growth (Phase 2): `bend` / `twist` design ops** · _shape:_ grammar growth only — 2
new design ops in the PURE parser `backend/core/build_spec.py` (`bend`/`twist` allowed-key sets + a parse branch
that validates the two bp planes, bend's required curvature, and twist's `total_degrees` XOR `degrees_per_nm`)
+ 2 dispatch branches in the driver `backend/api/headless_spec_build.py` driving the REAL AF-6 wrappers
(`hb.add_bend` / `hb.add_twist` — re-implements nothing); `crud.py`/`assembly.py`/`main.js` LOC Δ = **0** ·
_headless-coverage Δ:_ **32 → 32** (UNCHANGED — composition sugar over already-covered wrappers, wraps no new
route; like AF-10/AF-11-Phase-1 it moves the oracle count, not coverage) · _oracle shipped:_ **no new oracle —
reused `assert_deformation_angle` (AF-6) as the LOAD-BEARING augment** + `assert_spec_matches_calls` (AF-11) as a
secondary pin. The deciding fact: `canonical_topology` is **blind to a deformation overlay** (it lives outside the
strand graph — the AF-3 loop/skip lesson, now confirmed for deformations too), so `assert_spec_matches_calls`
*passes even if the bend were dropped* — it only proves the underlying bundle topology is faithful. What proves the
deformation actually flowed spec→parser→`hb.add_bend`→DeformationOp is the geometric `assert_deformation_angle` on
the spec-built design (κ×Δbp for a bend; θ for a twist; magnitude-only, direction-agnostic) · _tests:_ 1 grammar
normalisation + 5 grammar rejections (bend missing curvature, planes out of order, twist neither/both rate,
bend-can't-be-first) in `test_build_spec.py` + 4 driver tests in `test_headless_spec_build.py` (bend spec ≡
hand-calls, bend realises κ×Δbp, twist `total_degrees` realises θ, twist `degrees_per_nm` realises rate); full
suite **2388 passed / 55 skipped**, no drop · **"Validation gained, not just a passthrough:** the grammar now lowers
a declarative `{op:bend|twist}` to the real AF-6 deformation wrappers, and the spec-built bend/twist is *proven to
realise the requested angle* (`assert_deformation_angle`) — not merely structurally equal to the hand build. The
genuinely-new validation power is the recognition (and pinning) that `assert_spec_matches_calls` ALONE is vacuous
for a deformation cluster because the canonical fingerprint can't see the overlay; the geometric angle oracle is the
only thing that catches a dropped/mistranslated bend. No ASK-FIRST violation: the wrappers + oracle are AF-6's
direction-agnostic, already-cleared machinery; this layer adds zero new geometric/sign/frame reasoning, only
parameter plumbing.**"

**AF-11 — build-spec grammar growth (Phase 2): `loop_skip` design op** · _shape:_ grammar growth only — 1 new
design op in the PURE parser `backend/core/build_spec.py` (`loop_skip` allowed-key set `{op,helix,bp_index,delta}`
+ a parse branch validating the helix cell, a non-negative `bp_index`, and a route-faithful `delta ∈ {-1,0,+1}`
gate) + 1 dispatch branch in the driver `backend/api/headless_spec_build.py` driving the REAL AF-3 wrapper
`hb.loop_skip` (re-implements nothing; helix resolved by `grid_pos` like nick/ligate);
`crud.py`/`assembly.py`/`main.js` LOC Δ = **0** · _headless-coverage Δ:_ **32 → 32** (UNCHANGED — composition sugar
over the already-covered `insert_loop_skip` route; wraps no new route, moves the oracle count not coverage —
verified by the passing `test_spec_build_adds_no_coverage`) · _oracle shipped:_ **no new oracle — reused
`geometric_nucleotide_count` / `assert_geometric_length_delta` (AF-3) as the LOAD-BEARING augment** +
`assert_spec_matches_calls` (AF-11) as a secondary pin. Same deciding fact as the bend/twist cluster: a loop/skip
mark lives on `Helix.loop_skips`, OUTSIDE the strand graph, so `canonical_topology` (and thus
`assert_spec_matches_calls`) is **blind to it** (the original AF-3 lesson) — a spec whose loop was silently dropped
would still match the hand-call canonical fingerprint. What proves the mark flowed spec→parser→`hb.loop_skip`→
geometry is the geometric nucleotide count on the spec-built design (a loop +1 adds exactly 1 bp = 2 nucleotides on
its helix; a skip −1 removes 2) · _tests:_ 1 grammar normalisation (loop/skip/remove deltas) + 4 grammar rejections
(delta out of {-1,0,+1}, missing delta, negative bp_index, loop_skip-can't-be-first) in `test_build_spec.py` + 4
driver tests in `test_headless_spec_build.py` (loop_skip spec ≡ bundle topology of hand-calls; loop +1 adds 2
nucleotides; skip −1 removes 2; loop survives a `.nadoc` round-trip via the geometric count) ; full suite **2397
passed / 55 skipped**, no drop · **"Validation gained, not just a passthrough:** the grammar now lowers a
declarative `{op:loop_skip}` to the real AF-3 wrapper, and the spec-built loop/skip is *proven to change the
geometry by the requested amount* (geometric nucleotide count) and to *persist through a save/load* — neither of
which `assert_spec_matches_calls` can pin, because the canonical fingerprint can't see a loop/skip mark. The
genuinely-new validation power is the geometric length-delta pin on a declarative length-changing op (a bundle
clicked-then-looped vs. a spec-looped build are now proven byte-identical in *emitted geometry*, not just
topology). The `delta ∈ {-1,0,+1}` parse-time gate also rejects a malformed length op before any build runs.
**Scope note:** `apply_loop_skips` (the AF-3 sibling) is deferred — its route requires crossovers placed
(cross-helix domain transitions), which the spec grammar has no op to produce yet; it rides with the
`auto_scaffold`/`auto_crossover` cluster that generates those crossovers. No ASK-FIRST violation: `hb.loop_skip` +
the count oracle are AF-3's direction-agnostic machinery; this layer adds only parameter plumbing.**"

**AF-11 — build-spec grammar growth (Phase 2): `circle_segment` design op** · _shape:_ grammar growth only — 1 new
PRIMORDIAL design op in the PURE parser `backend/core/build_spec.py` (`circle_segment` allowed-key set
`{op,radius_nm,plane,offset_nm,strand_filter,ligate_adjacent,min_chord_bp}` + a parse branch validating a positive
`radius_nm`; added to `_PRIMORDIAL_DESIGN_OPS` so it may be the FIRST op like `bundle`; + a spec-level guard that a
spec containing a `circle_segment` op MUST be `square` lattice — the chord profile assumes the SQUARE column pitch)
+ 1 dispatch branch in the driver `backend/api/headless_spec_build.py` driving the REAL AF-4 wrapper
`hb.circle_segment` (re-implements nothing — the wrapper itself runs the same `circle_footprint` analytic the UI
mirror uses); `crud.py`/`assembly.py`/`main.js` LOC Δ = **0** · _headless-coverage Δ:_ **32 → 32** (UNCHANGED —
composition sugar over the already-covered `add_circle_segment` route; wraps no new route, moves the oracle count
not coverage — verified by the still-passing `test_spec_build_adds_no_coverage`) · _oracle shipped:_ **no new oracle
— reused BOTH `assert_spec_matches_calls` (AF-11, LOAD-BEARING here) AND the geometric `assert_circular_disc`
(AF-4)**. The deciding fact, and what makes this cluster DIFFERENT from loop_skip/bend/twist: a circle ADDS real
helices + strands to the strand graph, so `canonical_topology` *can* see it → `assert_spec_matches_calls` is a real,
load-bearing faithfulness pin (a spec whose disc was silently dropped would fail it, unlike the deformation/loop
overlays where it's vacuous). `assert_circular_disc` additionally pins the radius→footprint→route→placed-geometry
path end-to-end (spread <0.5 nm, fit_radius within 0.5 nm of R) · _tests:_ 1 grammar normalisation (primordial,
defaults filled) + 4 grammar rejections (missing radius_nm, non-positive radius, non-square lattice, typo'd field)
in `test_build_spec.py` + 5 driver tests in `test_headless_spec_build.py` (circle spec ≡ hand-call canonical; disc
of requested radius over R∈{8,10.6,14}; round-trip stable); full suite **2407 passed / 55 skipped**, no drop ·
**"Validation gained, not just a passthrough:** the grammar now lowers a declarative `{op:circle_segment,radius_nm}`
to the real AF-4 parametric-disc wrapper, and — distinctively for this cluster — the spec-built disc is pinned by the
faithful-façade oracle (`assert_spec_matches_calls` is load-bearing because the circle is *visible* in canonical
topology, the first Phase-2 op for which it is) AND by the geometric `assert_circular_disc` (the placed helices
actually trace a circle of the requested radius). The genuinely-new validation power is the parse-time SQUARE-lattice
guard: a `circle_segment` on a honeycomb lattice would silently produce a non-circular profile (the chord math
assumes the SQUARE pitch), and nothing else in the stack rejects it — the parser now catches it before any build
runs, alongside the positive-radius and primordial-first-op gates. No ASK-FIRST violation: `hb.circle_segment` +
`assert_circular_disc` are AF-4's already-cleared machinery; this layer adds only parameter plumbing + the lattice
guard.**"

**AF-11 — build-spec grammar growth (Phase 2): `gear` assembly op (relations cluster, sub-op 1)** · _shape:_
grammar growth only — 1 new assembly op in the PURE parser `backend/core/build_spec.py` (`gear` allowed-key set
`{op,joint_a,joint_b,ratio,invert,name}` + a parse branch validating a non-zero `ratio`) **plus a NEW joint-`ref`
namespace**: the `mate` op grew an optional `ref` key, and the referential-integrity pass now tracks
`defined_joints: dict[ref→joint_type]` so a `gear` `joint_*` must name a prior mate `ref` **that is `revolute`**
(rejecting gear-over-rigid + dangling/duplicate joint refs at parse time) + 1 dispatch branch in the driver
`backend/api/headless_spec_build.py` driving the REAL AF-9 wrapper `hab.define_gear` (the driver tracks
`joint_refs: dict[ref→runtime joint id]`, capturing `joints[-1].id` after each `define_mate`; re-implements
nothing); `crud.py`/`assembly.py`/`main.js` LOC Δ = **0** · _headless-coverage Δ:_ **32 → 32** (UNCHANGED —
composition sugar over the already-covered `create_gear_relation` route; wraps no new route, moves the oracle count
not coverage — verified by the still-passing `test_spec_build_adds_no_coverage`) · _oracle shipped:_ **no new oracle
— reused BOTH `assert_gear_ratio` (AF-9, LOAD-BEARING) AND `assert_spec_matches_calls` (AF-11, also load-bearing
here)**. The deciding fact: a gear is a top-level `GearRelation` that `canonical_assembly` HAS fingerprinted since
AF-9, so `assert_spec_matches_calls` is a real faithfulness pin (a dropped/rewired gear fails it — like
`circle_segment`, unlike the bend/twist/loop_skip overlays). But it's necessary-not-sufficient: the fingerprint
catches a *structurally* dropped gear, NOT a gear that's present but fails to *propagate* (drive its coupled body).
`assert_gear_ratio` is the orthogonal kinematic pin — drive `rel.joint_a_id` 30°, measure the coupled wheel's real
instance-transform rotation, assert driven/driver = `|ratio|` (parametrized 2.0 + 0.5) — the same complementary
roles as AF-9 overhang-bindings (fingerprint + resolve oracle) · _tests:_ 7 new in `test_build_spec.py` (gear
normalisation incl. defaults; **5 rejections**: dangling joint ref, gear-over-rigid → "must be 'revolute'",
zero ratio, duplicate joint ref, missing `joint_b`) + 4 new in `test_headless_spec_build.py` (gear spec ≡ hand-call
canonical assembly; drives coupled wheel at ratio 2.0 + 0.5; geared assembly round-trips stable WITH its gear); full
suite **2418 passed / 55 skipped**, no drop · **"Validation gained, not just a passthrough:** the grammar now lowers
a declarative `{op:gear,joint_a,joint_b,ratio}` to the real AF-9 wrapper, and the spec-built gear is pinned BOTH
structurally (`assert_spec_matches_calls` — load-bearing because gears live in `canonical_assembly`) AND kinematically
(`assert_gear_ratio` — driving one joint of the *spec-built* assembly actually rotates the coupled wheel by the ratio,
so a gear that's registered but doesn't propagate fails). The genuinely-new validation power is two-fold: (1) the
parse-time `revolute` gate — a gear over a rigid mate is rejected before any build, mirroring the route's 400 up into
the pure grammar by tracking each mate ref's joint_type; (2) the joint-`ref` namespace itself, the first grammar
construct that lets one op reference the runtime output of two prior ops, which `belt`/`polymerize` now reuse. No
ASK-FIRST violation: `define_gear` + `assert_gear_ratio` are AF-9's direction-agnostic (magnitude-only) machinery;
this layer adds only parameter plumbing + the ref resolution.**"

**AF-11 — build-spec grammar growth (Phase 2): `belt` assembly op (relations cluster, sub-op 2)** · _shape:_
grammar growth only — 1 new assembly op in the PURE parser `backend/core/build_spec.py` (`belt` allowed-key set
`{op,joint_a,joint_b,radius_a,radius_b,name}` + a parse branch validating positive `radius_a`/`radius_b`) **reusing
the gear's joint-`ref` namespace verbatim**: the referential-integrity pass's revolute-joint-ref check was widened
from `op == "gear"` to `op in ("gear","belt")` (so a belt `joint_*` must name a prior mate `ref` that is `revolute`,
rejecting belt-over-rigid + dangling joint refs at parse time) + 1 dispatch branch in the driver
`backend/api/headless_spec_build.py` driving the REAL AF-9 wrapper `hab.define_belt` (re-implements nothing — drives
the same `create_belt_path` route the gear-sibling drove for gears); `crud.py`/`assembly.py`/`main.js` LOC Δ = **0** ·
_headless-coverage Δ:_ **32 → 32** (UNCHANGED — composition sugar over the already-covered `create_belt_path` route;
wraps no new route, moves the oracle count not coverage — verified by the still-passing
`test_spec_build_adds_no_coverage`) · _oracle shipped:_ **no new oracle — reused BOTH `assert_gear_ratio` (AF-9,
LOAD-BEARING — handed the belt's synthetic relation id `f"__belt__{belt.id}"` + `expected_ratio = radius_a/radius_b`)
AND `assert_spec_matches_calls` (AF-11, also load-bearing here)**. Same deciding fact as gear: a belt is a top-level
`BeltPath` that `canonical_assembly` HAS fingerprinted since AF-9 (the 5-tuple), so `assert_spec_matches_calls` is a
real faithfulness pin (a dropped/rewired belt fails it) — but necessary-not-sufficient: the fingerprint catches a
*structurally* dropped belt, NOT a belt that's present but fails to *propagate*. `assert_gear_ratio` is the orthogonal
kinematic pin — drive `belt.pulley_a.joint_id` 30°, measure the coupled pulley's real instance-transform rotation,
assert driven/driver = `|radius_a/radius_b|` (parametrized 2:1 + 3:1) — which crucially passes the *radii* (not a
literal ratio) so it pins `_belt_to_relation`'s radius→ratio synthesis, distinct from the gear test · _tests:_ 8 new
in `test_build_spec.py` (belt normalisation incl. name; **5 rejections**: dangling joint ref, belt-over-rigid →
"must be 'revolute'", radius_a≤0, radius_b<0, missing `radius_b`) + 4 new in `test_headless_spec_build.py` (belt spec
≡ hand-call canonical assembly; drives coupled pulley at radius ratio 2:1 + 3:1; belted assembly round-trips stable
WITH its belt); full suite **2428 passed / 55 skipped**, no drop · **"Validation gained, not just a passthrough:** the
grammar now lowers a declarative `{op:belt,joint_a,joint_b,radius_a,radius_b}` to the real AF-9 wrapper, and the
spec-built belt is pinned BOTH structurally (`assert_spec_matches_calls` — load-bearing because belts live in
`canonical_assembly`) AND kinematically (`assert_gear_ratio` — driving one pulley of the *spec-built* assembly
actually rotates the coupled pulley by the *rim-radius* ratio, so a belt that's registered but fails to propagate, or
whose radius→ratio synthesis is wrong, fails). The genuinely-new validation power over the gear sub-op is that the
spec passes pulley *radii* and the oracle asserts the *derived* `radius_a/radius_b` drives the coupling — if the
parser dropped a radius or the driver swapped `radius_a`/`radius_b`, the belt test goes red while the gear test stays
green. No ASK-FIRST violation: `define_belt` + `assert_gear_ratio` are AF-9's direction-agnostic (magnitude-only)
machinery; this layer adds only parameter plumbing, reusing the gear's revolute-ref gate by widening one condition.**"

**AF-11 — build-spec grammar growth (Phase 2): `polymerize` assembly op (relations cluster, sub-op 3)** ·
_shape:_ grammar growth only — 1 new assembly op in the PURE parser `backend/core/build_spec.py`
(`polymerize` allowed-key set `{op,joint,count,direction}` + a parse branch validating `count ≥ 2` and
`direction ∈ {forward,backward,both}`) **reusing the gear/belt joint-`ref` namespace** but referencing a
SINGLE seed mate (`joint`, not a pair) — and crucially **without** the revolute gate (polymerize replicates
the seed mate, it does not couple two revolute joints, so a referential-integrity branch checks only that
`joint` names a prior mate `ref` of ANY joint_type) + 1 dispatch branch in the driver
`backend/api/headless_spec_build.py` driving the REAL AF-9 wrapper `hab.polymerize` (re-implements nothing —
the driver resolves `joint_refs[p["joint"]]` and passes `count`/`direction`); `crud.py`/`assembly.py`/`main.js`
LOC Δ = **0** · _headless-coverage Δ:_ **32 → 32** (UNCHANGED — composition sugar over the already-covered
`polymerize_assembly` route; wraps no new route, moves the oracle count not coverage — verified by the
still-passing `test_spec_build_adds_no_coverage`) · _oracle shipped:_ **no new oracle — reused BOTH
`assert_spec_matches_calls` (AF-11, LOAD-BEARING) AND the geometric `assert_polymer_chain` (AF-9)**. Same
deciding fact as gear/belt: polymerize's new copies + replicated seam joints are top-level
instances/joints that `canonical_assembly` HAS fingerprinted since AF-7/8, so `assert_spec_matches_calls` is
a real faithfulness pin (a dropped copy or chain joint fails it) — but necessary-not-sufficient: the
fingerprint sees that N instances exist, NOT that they march along the seed's repeat. `assert_polymer_chain`
is the orthogonal geometric pin — it re-derives the seed mate's repeat `delta = T_B @ inv(T_A)` from the seed
pair alone (a synthetic seed-pair-only `before` projection of the spec-built assembly) and asserts the
`count−2` copies form the exact `delta`-power multiset, with the assertion that the +10 nm-X repeat the
connector snap produced is realised (parametrized count 4 + 6) · _tests:_ 7 new in `test_build_spec.py`
(polymerize normalisation incl. `both`; defaults direction→forward; **allows a rigid seed** — the no-revolute-gate
distinction from gear/belt; **3 rejections**: dangling joint ref, count<2, bad direction; missing `count`) + 4 new
in `test_headless_spec_build.py` (polymerize spec ≡ hand-call canonical assembly; lays count−2 copies on the
+10 nm delta lattice for count 4 + 6; polymerized assembly round-trips stable WITH its 2 replicated joints);
full suite **2444 passed / 55 skipped**, no drop · **"Validation gained, not just a passthrough:** the grammar
now lowers a declarative `{op:polymerize,joint,count,direction}` to the real AF-9 wrapper, and the spec-built
chain is pinned BOTH structurally (`assert_spec_matches_calls` — load-bearing because the copies + seam joints
live in `canonical_assembly`) AND geometrically (`assert_polymer_chain` — the copies actually sit on the seed
mate's `delta`-power lattice, so a chain that's structurally present but laid off the repeat fails). The
genuinely-new validation power over the gear/belt sub-ops is the recognition (and pinning) that polymerize
takes a SINGLE seed `ref` and accepts ANY joint_type — the referential-integrity branch deliberately omits the
revolute gate gear/belt enforce, and `test_assembly_spec_polymerize_allows_rigid_seed` pins that distinction so
a future refactor can't silently over-constrain it. No ASK-FIRST violation: `hab.polymerize` +
`assert_polymer_chain` are AF-9's direction-agnostic (re-derives the documented fwd/back split, measures placed
geometry) machinery; this layer adds only parameter plumbing + the single-ref resolution.**"

**AF-15 — cluster rigid-transform wrappers (Phase 1): `add_cluster` / `transform_cluster` + translation oracle** ·
_shape:_ 2 wrappers in `backend/api/headless_build.py` (`add_cluster` imports `add_cluster` +
`AddClusterBody`; `transform_cluster` imports `update_cluster` + `PatchClusterBody` from `routes_clusters` —
exact route handlers, registers covered by function identity, NOT re-implemented) + 1 NEW reusable oracle
`assert_cluster_translated` in `tests/automation_harness.py`; `crud.py`/`assembly.py`/`main.js` LOC Δ = **0**
(all new code is the existing headless module + the harness) · _headless-coverage Δ:_ **32 → 34** (`POST
/design/cluster` + `PATCH /design/cluster/{id}` flip to covered — the FIRST coverage gain since AF-9; AF-10/AF-11
were all composition-sugar) · _oracle shipped:_ `assert_cluster_translated(design_before, design_after,
cluster_id, *, translation, tol_nm=0.02, min_translation_nm=0.5)` — a **geometric** oracle: it reads the
cluster-posed helix axes from `deformed_helix_axes` (the geometry kernel's posed output — clusters apply at
geometry-compute time via `_apply_cluster_transforms_domain_aware`, never to the strand graph) on both designs and
asserts (1) every helix in the cluster has its posed `start`/`end` displaced by exactly the requested translation,
(2) every non-cluster helix is unchanged (the cluster-scoping property — the default catch-all cluster stays put),
(3) `‖translation‖ > min_translation_nm` (can-go-red guard — a zero translation makes every helix trivially
"unchanged" and the oracle pass vacuously). **Direction-AGNOSTIC** (a world-space translation is unambiguous — no
quaternion sign / pivot / frame convention to reason about → stays clear of the ASK-FIRST DNA-directionality rule;
**rotation poses deliberately out of scope**, they belong with Phase 2's edge-alignment flip/snap which IS a
directionality decision) · _tests:_ 5 new in `test_headless_build.py` (add_cluster creates a named non-default
identity-pose cluster; transform translates ONLY the cluster's 2 helices, parametrized over 2 vectors; clustered
pose survives a `.nadoc` round-trip AND still drives geometry after reload — the persistence pin
`canonical_topology` can't give; coverage flip) + 3 new in `test_automation_harness.py` (oracle passes on a real
translation + **two load-bearing red-tests**: claiming a translation the kernel didn't apply raises "did not
translate", and a zero translation trips the "vacuously" guard); repointed the AF-1 backlog-route coverage
meta-test from `/design/cluster` (now covered) to `/design/strand-end-resize` (still uncovered), and bumped
`test_spec_build_adds_no_coverage`'s expected count 32 → 34; full suite **2452 passed / 55 skipped**, no drop ·
**"Validation gained, not just a passthrough:** before AF-15 there was no way to group + pose a rigid cluster
headlessly, and — the deciding point — nothing could prove a cluster pose *flows into the geometry* or *persists*,
because `canonical_topology` is BLIND to the cluster-transform overlay (it lives outside the strand graph, the
third confirmed instance of that blind-spot after loop/skip and bend/twist), so `assert_roundtrip_stable` alone is
vacuous for the pose. `assert_cluster_translated` closes that by measuring the real posed helix axes the geometry
kernel emits (so a kernel that ignored the pose, mis-scaled it, applied it to the wrong frame, or leaked it onto
non-cluster helices fails), with a can-go-red guard + two red-tests. It's the geometric spine Phase 2's
`align_edge_transform` solver (and the 4-bar parallelogram capstone) pins itself against. The three-layer law is
honoured exactly: the wrappers pose a DISPLAY-layer rigid body, the oracle reads DISPLAY-layer geometry, and the
strand topology is never touched.**"

---

**AF-15 — cluster OBB enumerator + edge-alignment solver (Phase 2): `align_edge_transform` + `assert_edges_collinear`** ·
_shape:_ **NEW pure core** `backend/core/cluster_obb.py` (the `OBB` dataclass + `cluster_obb(design, cluster_id)`
equivariant enumerator with `edge_endpoints`/`corner`/`edges`, + the pure `align_edge_transform` solver — imports
`deformation.deformed_helix_axes` + scipy `Rotation`, NOTHING from `backend.api`) + 1 wrapper
`hb.align_cluster_edge` in `backend/api/headless_build.py` (calls the pure solver, then drives the already-covered
`transform_cluster`) + 1 NEW reusable oracle `assert_edges_collinear` in `tests/automation_harness.py`;
`crud.py`/`assembly.py`/`main.js` LOC Δ = **0** (new code is one new core module + the existing headless module +
the harness) · _headless-coverage Δ:_ **34 → 34** (UNCHANGED — `align_cluster_edge` wraps NO new route; it composes
`transform_cluster`, so like AF-10/AF-11 it's a construction-sugar/solver item, the oracle is the deliverable, not a
coverage flip — guarded by `test_align_cluster_edge_adds_no_coverage`) · _oracle shipped:_
`assert_edges_collinear(design, cluster_id, src_edge, *, target_edge|target_line, tol_nm=0.05, tol_deg=1.0,
min_len_nm=0.5)` — a **geometric** oracle: it recomputes the cluster's OBB on the POSED design and asserts the named
src edge is collinear with the target — (1) directions parallel-or-antiparallel within `tol_deg`, (2) both src
endpoints within `tol_nm` of the target line — with a non-degeneracy guard (edges longer than `min_len_nm`).
**Direction-AGNOSTIC** (a line, not a ray — both senses pass → no ASK-FIRST violation). The deeper deliverable is the
**equivariant OBB** itself, pinned by `test_obb_is_equivariant` (`OBB(g·design)=g·OBB(design)`): that property is what
makes a named edge refer to the same physical edge before/after the solve, so the oracle measures the edge the solver
intended · **ASK-FIRST conventions confirmed with the user (2026-06-17), NOT reasoned out:** minimal rotation /
auto-flip (≤90° onto ±target_dir) / midpoint snap (endpoints coincide) / roll left free · _tests:_ 11 new in
`test_cluster_obb.py` (OBB contains-snugly + right-handed-orthonormal + rejects degenerate/square footprints;
**equivariance parametrized over translation / Z-rotation / general screw**; solver: two-bar edge-snap, angled
world-line rotate+snap, align-to-rotated-bar 90°, auto-flip-to-minimal; coverage-unchanged guard) + 4 new in
`test_automation_harness.py` (oracle passes on a real alignment + **three red-tests**: edges left skew raise "off the
target line", wrong-angle raises "not collinear", and the equivariance pin doubles as the can-go-red proof); full
suite **2466 passed / 55 skipped**, no drop · _cohesion:_ `cluster_obb.py`'s one reason to change = the cluster OBB
geometry + edge-alignment math; dep surface = `deformed_helix_axes` + scipy `Rotation`, nothing from `backend.api` ·
**"Validation gained, not just a passthrough:** before this, nothing could align two rigid clusters by their OBB edges
headlessly, and — the load-bearing point — there was no Python OBB at all (it lived only in JS `joint_renderer.js`),
so no headless geometry could pin a kinematic-cluster arrangement. `assert_edges_collinear` proves the solved pose
actually lands the chosen edge on the target line (so a solver that mis-rotated, snapped to the wrong point, or
left the edges skew fails), recomputed on the real posed geometry. The genuinely-new, reusable validation power is the
**equivariant OBB** (`OBB(g·design)=g·OBB(design)`, proved) — the foundation AF-14's joint-axis placement and the 4-bar
parallelogram capstone both build on; without provable equivariance a named edge/corner picker is untrustworthy under
a pose. A subtle bug the equivariance test caught and banked: a value-argmax sign anchor ties on a rectangle's 4
symmetric corners and float-rounding flips the frame after a rotation — fixed with a positional (sorted-id) anchor.
Three-layer law honoured: the OBB READS the geometric layer (posed axes), the solver returns a DISPLAY-layer pose, the
strand topology is never touched.**"

---

**AF-14 — geometry-aware revolute-joint placement (Phase 1): `place_cluster_joint` + `hull_prism_axis` +
`assert_joint_on_hull_corner`** · _shape:_ 1 wrapper `hb.place_cluster_joint` in `backend/api/headless_build.py`
(imports the exact `add_joint` route handler + `AddJointBody` from `routes_cluster_joints` → covered by function
identity) + 1 pure helper `hull_prism_axis` (+ a new `OBB.face_normal` method) in the existing
`backend/core/cluster_obb.py` + 1 NEW reusable oracle `assert_joint_on_hull_corner` in `tests/automation_harness.py`;
`crud.py`/`assembly.py`/`main.js` LOC Δ = **0** (new code is the existing headless module + the existing core module +
the harness — NO god-file growth, NO new module) · _headless-coverage Δ:_ **34 → 35** (`POST
/design/cluster/{id}/joint` = `add_joint` flips to covered — a REAL route-wrapper item, the first coverage flip since
AF-15 Phase 1; the AF-15-P2 / AF-10 / AF-11 items in between were all construction-sugar) · _oracle shipped:_
`assert_joint_on_hull_corner(design, joint_id, *, edge=(axis,s1,s2) | corner=(su,sv,sw)+face=(axis,sign),
tol_nm=0.05, tol_deg=1.0)` — a **geometric** oracle: re-derives the placed joint's world axis from its cluster-LOCAL
storage + the cluster's current pose via `_local_to_world_joint` (so it measures where the axis really is after the
route's world→local→world conversion, honoring the local-frame round-trip on a *posed* cluster), recomputes the OBB
independently with the equivariant `cluster_obb`, and asserts — EDGE mode: the joint axis line is collinear with the
named edge (direction ∥/anti-∥ within `tol_deg` AND both edge endpoints within `tol_nm` of the joint line);
CORNER mode: the joint axis passes through the named corner (perp dist < `tol_nm`) AND its direction ∥/anti-∥ the
named face normal. **Direction-AGNOSTIC** (a line, not a ray — both senses pass → no ASK-FIRST sign/handedness
reasoning; the *swing sense* is Phase 2's ROM). Non-degeneracy guard (OBB edge longer than `min_len_nm`) · _tests:_
7 new in `test_cluster_obb.py` (`hull_prism_axis` edge-runs-along-edge / corner-pivots-along-face-normal / 4
rejections; `place_cluster_joint` lands-on-edge, passes-through-corner, **posed-cluster local-frame round-trip**,
coverage flip) + 5 new in `test_automation_harness.py` (oracle passes on a real edge + a real corner placement +
**two load-bearing red-tests**: a joint on edge (w,+1,+1) checked against the parallel-but-offset edge (w,−1,+1)
raises "off the joint axis line"; a joint at corner (+1,+1,+1) checked against corner (−1,+1,+1) raises "from
corner"; + af14-covered) + repointed the two coverage-count assertions (`test_align_cluster_edge_adds_no_coverage`,
`test_spec_build_adds_no_coverage`) 34 → 35; full suite **2478 passed / 55 skipped**, no drop · _cohesion:_
`hull_prism_axis` adds ONE reason to change to `cluster_obb.py` (named-OBB-feature → world axis), same dep surface
(the existing `cluster_obb` + numpy); `place_cluster_joint` is a thin route-driver · **"Validation gained, not just a
passthrough:** before AF-14 a revolute joint could only be placed by clicking a face of the hull approximation in the
gizmo — there was no headless entry, so no automated way to pin that a joint lands where you asked. `place_cluster_joint`
gives the entry and `assert_joint_on_hull_corner` proves the geometric promise: the placed joint's *real world axis*
(re-derived from its LOCAL storage, so it also exercises the world→local→world round-trip the route performs) lies on
the named OBB edge / passes through the named corner of an independently recomputed OBB — so a placer that snapped to
the wrong edge, mangled the world→local conversion, or used the wrong face normal fails. The posed-cluster test is the
sharp one: it places the joint on a translated+rotated cluster and the oracle still finds the axis on the edge,
proving the local-frame storage is drift-free (the whole point of storing the axis in local coords). Two red-tests
prove the green can go red. It's the per-joint geometry the AF-14 Phase-2 ROM selector and the 4-bar-parallelogram
capstone compose. Three-layer law honoured: placing a `ClusterJoint` is a topological/design-layer write, but the
hull-prism OBB it anchors to is a pure geometric *read* that never writes back.**"

**AF-14 — geometry-aware revolute-joint ROM (Phase 2): `cluster_range_of_motion` + `rank_joint_candidates` +
`assert_range_of_motion`** · _shape:_ pure swept-collision geometry added to the existing
`backend/core/cluster_obb.py` (`_obb_intersect` = Ericson 15-axis SAT; `_padded`/`_rotate_obb` helpers;
`obb_sweep_rom` = OBB-only per-step scan + 40-iter bisection of first contact in each sense; `cluster_range_of_motion`
= the design-level wrapper, anchored cluster swings vs. all others static; `rank_joint_candidates` = the 12 OBB edges
ranked by ROM) + 1 NEW reusable oracle `assert_range_of_motion` in `tests/automation_harness.py`;
`crud.py`/`assembly.py`/`main.js` LOC Δ = **0** (all new code is the existing core module + the harness — NO god-file
growth, NO new module) · _headless-coverage Δ:_ **35 → 35** (UNCHANGED — a construction/analysis item: it wraps NO new
route, it *reads* geometry; the deliverable is the oracle, not a coverage flip — like AF-10/AF-11/AF-15-P2) · _oracle
shipped:_ `assert_range_of_motion(design, cluster_id, axis, expected_deg, *, tol_deg=2.0, min_angle_deg=-180,
max_angle_deg=180, pad=HELIX_RADIUS, step_deg=2.0)` — a **geometric** oracle: computes the swept-OBB total two-sided
free swing about `axis` and asserts it == `expected_deg ± tol_deg`, with a physical-bound guard (`0 ≤ ROM ≤ max−min`).
**ASK-FIRST decisions confirmed by the user (2026-06-17):** (1) the *anchored* cluster is the moving body, every
other cluster a static obstacle; (2) ROM is the **total two-sided magnitude** θ⁺+θ⁻ (each clamped to the angular
limit) — direction-AGNOSTIC, no handedness, so it stays clear of the ASK-FIRST DNA-directionality rule the way AF-6
did; (3) each OBB is **padded by the helix radius** (~1 nm) so two bundles register contact rim-to-rim rather than
when their axis boxes overlap · _tests:_ 7 new in `test_cluster_obb.py` (SAT overlap/separation; **synthetic
rod+double-wall analytic** ROM = `2·(asin(Y0/√(L²+w²))−atan2(w,L))` to <1°, an independent closed-form derivation NOT
the SAT sweep; no-obstacle full-limit for 360° and a custom ±90°; lone-cluster full swing; **obstacle-reduces +
monotonic** on real bars; `rank_joint_candidates` sorted-by-ROM + door-jamb variation + target filter; oracle pass +
wrong-angle red) + 3 new in `test_automation_harness.py` (oracle passes on a lone cluster's full swing + **two
load-bearing red-tests**: a free 360° swing checked against 180° raises; a neighbour-blocked joint checked against
360° raises while the true reduced value passes) ; full suite **2488 passed / 55 skipped**, no drop · _cohesion:_ the
ROM block adds ONE reason to change to `cluster_obb.py` (swept-OBB clearance of a cluster about an axis), small dep
surface (the existing `cluster_obb`/`hull_prism_axis` + numpy/scipy `Rotation`) · **"Validation gained, not just a
passthrough:** before AF-14 P2 nothing could compute — let alone pin — how far a revolute-jointed cluster can swing
before it collides with a neighbour. `assert_range_of_motion` gives that, and its trustworthiness rests on TWO
independent legs: the analytic precision is proved on a synthetic rod-and-wall fixture whose contact angle is a
closed-form `asin`/`atan2` expression (so a bug in the SAT or the bisection would diverge from the trig), and the two
can-go-red guards are proved on real DNA bars (a lone cluster swings the full limit; pushing a neighbour into the
swing path strictly and monotonically shrinks the ROM). So a ROM that over-/under-counted contact, ignored the helix
pad, or escaped its angular limits fails. This is the swept-clearance spine the 4-bar-parallelogram capstone and the
AF-12 linkage-mobility check compose; `rank_joint_candidates` makes the door-jamb principle quantitative (the
interface hinge swings least, the away-facing hinge swings free). NB construction-sugar item: coverage flat by design
— the pass criterion was always the oracle.**"

---

**CAPSTONE — the headless 4-bar parallelogram (first headless kinematic mechanism)** · _shape:_ 1 new pure helper
`grubler_mobility(n_links, *, revolute, prismatic, higher)` in `backend/core/cluster_obb.py` (planar Kutzbach DOF —
`3(n−1)−2·lower−higher`, pure combinatorics, no geometry) + 1 reusable oracle `assert_parallelogram_linkage` in
`tests/automation_harness.py` + a reusable builder + integration test in NEW `tests/test_parallelogram_linkage.py`;
`crud.py`/`assembly.py`/`main.js` LOC Δ = **0** (all new code is `backend/core` + the harness + a new test module) ·
_headless-coverage Δ:_ **35 → 35** (UNCHANGED — pure composition of already-covered wrappers `create_bundle` /
`add_cluster` / `update_cluster` (via `align_cluster_edge`) / `add_joint` (via `place_cluster_joint`); wraps no new
route, so like AF-10/AF-11/AF-15-P2 it moves the oracle count, not coverage — `test_parallelogram_wraps_no_new_route`
pins it) · _oracle shipped:_ `assert_parallelogram_linkage(design, bar_ids, *, joint_ids, tol_nm=0.1, tol_deg=2.0,
expected_dof=1, min_area_nm2=1.0, require_movable=True)` — a **composed geometric + kinematic** oracle measured on the
*posed* OBBs (recomputed, never trusting the solver's claimed transform): (1) **closed quadrilateral** — adjacent bars
share an OBB corner (the hinge point), the 4 shared corners enclose area > `min_area_nm2` (the non-degeneracy guard:
four collinear/collapsed bars fail); (2) **parallelogram** — opposite bars' long axes parallel-or-antiparallel within
`tol_deg` AND equal-length within `tol_nm`; (3) **mobility** — `grubler_mobility(4, revolute=len(joint_ids))` ==
`expected_dof`; (4) **each hinge movable** — each joint's world axis (re-derived from cluster-LOCAL storage via
`_local_to_world_joint`, the placed axis) admits a nonzero swept-OBB ROM vs. the non-adjacent (non-pinned) bars.
Direction-AGNOSTIC throughout · _tests:_ 4 in `test_parallelogram_linkage.py` (full capstone is 1-DOF + each hinge on
its shared-corner edge + adjacent bars share exact corners + wraps-no-route) + 3 grübler unit tests in
`test_cluster_obb.py` (four-bar=1, textbook cases, bad-input reject) + 3 harness meta-tests in
`test_automation_harness.py` (oracle passes on a real mechanism + **two load-bearing red-tests**: 3 joints → mobility 3
≠ 1 raises, one bar shoved away → closure raises); full suite **2498 passed / 55 skipped**, no drop ·
**"Validation gained, not just a passthrough:** before the capstone, every kinematic-cluster oracle pinned ONE
construction step in isolation (`assert_edges_collinear` = one alignment, `assert_joint_on_hull_corner` = one joint,
`assert_range_of_motion` = one swing); nothing validated that *composing* them with the headless wrappers yields a
working mechanism. `assert_parallelogram_linkage` is the first **assembled-mechanism** oracle: it proves four bars
edge-aligned + hinged headlessly form a genuine closed, parallel, 1-DOF four-bar linkage (so a build that mis-aligned a
bar, dropped a joint, or collapsed the loop fails), and `grubler_mobility` makes the DOF claim a rigorous combinatorial
statement reusable for any planar linkage (the AF-12 layer). The two red-tests prove the green can go red on a wrong
joint count and a broken loop. This is the AF-12 linkage-mobility (Grübler) demo the AF-14/AF-15 geometry was built
toward — the validation is 'the assembled mechanism has the expected DOF and every hinge is movable.' NB
composition-only (coverage flat by design): the pass criterion was always the oracle.**"

---

**AF-11 — build-spec grammar growth (Phase 2): `auto_scaffold` / `auto_crossover` / `full_autostaple` / `apply_loop_skips`
design ops** · _shape:_ grammar growth only — 4 new design ops in the PURE parser `backend/core/build_spec.py`
(`auto_scaffold` allowed-keys `{op, seamless}`; `auto_crossover` / `apply_loop_skips` `{op}` only; `full_autostaple`
`{op, scaffold_name, custom_sequence, strand_id}` — all NON-primordial, so none may be the first op) + 4 dispatch
branches in the driver `backend/api/headless_spec_build.py` driving the REAL existing wrappers
(`hb.auto_scaffold` / `hb.auto_crossover` / `hb.full_autostaple` / `hb.apply_loop_skip_deformations` — re-implements
nothing); `crud.py`/`assembly.py`/`main.js` LOC Δ = **0** · _headless-coverage Δ:_ **35 → 35** (UNCHANGED — composition
sugar over already-covered wrappers, wraps no new route; `test_spec_build_adds_no_coverage` still green at 35) ·
_oracle shipped:_ **no new oracle — reused `assert_spec_matches_calls` (AF-11) as the LOAD-BEARING augment for the three
routing ops** (`auto_scaffold`/`auto_crossover`/`full_autostaple` ADD a scaffold strand / crossover domain-transitions /
broken-merged staples that `canonical_topology` SEES — so the golden pin is genuinely load-bearing: the hand reference
runs the real auto ops, so a driver that silently dropped one would diverge and fail; a non-vacuity test confirms the
routed topology ≠ a bare bundle) **+ reused the AF-3 per-helix `geometric_nucleotide_count` conservation check as the
LOAD-BEARING augment for `apply_loop_skips`** (its baked marks live on `Helix.loop_skips`, OUTSIDE the strand graph, so
`assert_spec_matches_calls` is BLIND to them — the same AF-3/loop_skip lesson; the geometric per-helix law
`Δgeometry == 2 × net marks` is the only thing that proves the marks flowed spec → parser → wrapper → geometry
helix-by-helix). The session's keystone: `apply_loop_skips` was DEFERRED until a spec op could place crossovers — its
route 400s without them — and `auto_crossover` now produces exactly those, so both landed together (a
`test_apply_loop_skips_spec_requires_crossovers` red-test proves the route really runs by 400ing on a bare bundle) ·
_tests:_ 2 grammar normalisation (routing-ops defaults + fields) + 7 grammar rejections (4× can't-be-first, seamless
non-bool, full_autostaple typo'd field, auto_crossover extra field) in `test_build_spec.py` + 7 driver tests in
`test_headless_spec_build.py` (auto_scaffold+crossover spec ≡ hand-calls; routed-topology ≠ bare bundle non-vacuity;
full_autostaple spec ≡ hand-calls; full_autostaple round-trips stable; apply_loop_skips per-helix conservation;
apply_loop_skips requires-crossovers 400); full suite **2513 passed / 55 skipped**, no drop ·
**"Validation gained, not just a passthrough:** the grammar now lowers declarative bulk-routing ops to the real
scaffold/crossover/autostaple wrappers, and a spec-routed design is *proven byte-identical in canonical topology* to the
equivalent hand-clicked routing (`assert_spec_matches_calls` is load-bearing here — unlike bend/twist/loop_skip — because
the routing ADDS strands the fingerprint sees). Separately, `apply_loop_skips` — finally reachable now that
`auto_crossover` can place the crossovers its route demands — is proven to bake the SQUARE periodic-skip pattern with the
per-helix conservation law `Δgeometry == 2 × net marks` (no mark leaks between helices or is dropped), the only pin that
catches a dropped overlay the canonical fingerprint can't see. This closes the last DEFERRED design-op in the AF-11
Phase-2 grammar. No ASK-FIRST violation: every wrapper + oracle is already-cleared direction-agnostic machinery; this
layer adds only parameter plumbing + the parse-time grammar gates.**"

**AF-14 — Phase 3 hinge-joint recommender (`recommend_hinge_joints`) + corner anchoring** · _shape:_ pure
selector in `backend/core/cluster_obb.py` (`recommend_hinge_joints` — reuses the equivariant OBB +
`obb_sweep_rom`; imports nothing from `backend.api`) + an `anchor="midpoint"|"corner"` option threaded through
`hull_prism_axis` and the `hb.place_cluster_joint` wrapper (`headless_build.py`) + 1 reusable oracle
`assert_recommended_hinge` in `tests/automation_harness.py`; `crud.py`/`assembly.py`/`main.js` LOC Δ = **0** ·
_headless-coverage Δ:_ **35 → 35** (UNCHANGED — `recommend_hinge_joints` wraps NO route; the `anchor` option
drives the SAME already-covered `add_joint` route, so like AF-10/AF-15-P2 this moves the oracle count, not
coverage — verified by `test_recommend_hinge_adds_no_coverage`) · _oracle shipped:_
`assert_recommended_hinge(design, cluster_id, *, recommendations=None, axial_tol_deg=20, tol_nm=0.05,
length_tol_nm=0.1)` — re-measures on the **independently recomputed** equivariant OBB that the #1 recommendation
(1) is non-axial (edge angle to the helical `w` axis > `axial_tol_deg` — a fold, not a barrel-roll), (2) is the
**longest** non-axial edge (within `length_tol_nm`), and (3) is **corner-anchored** (stored `axis_origin`
within `tol_nm` of an edge endpoint, not the midpoint). Direction-AGNOSTIC (edge length + angle-to-axis are
magnitudes; ROM is the two-sided total). Injectable `recommendations=` seam so the red-tests feed a mangled
list · _tests:_ 7 new in `test_cluster_obb.py` (top is the wide `u`-edge non-axial corner-anchored; axial
`w`-edges demoted to the last 4 + flagged; corner-vs-midpoint anchor differ by half the edge length on the same
line; `target_rom_deg` filter; corner-anchored joint still passes `assert_joint_on_hull_corner` edge mode;
bad-anchor `ValueError`; no-coverage) + 3 harness meta-tests (passes on a real bar + **two load-bearing
red-tests**: an axial edge hand-ranked #1 raises "axial", a midpoint-anchored top raises "corner-anchored");
full suite **2523 passed / 55 skipped**, no drop · **"Validation gained, not just a passthrough:** before AF-14
P3 the only hinge ranker was `rank_joint_candidates`, which sorts by ROM ALONE — it would happily return an
axial `w`-edge (a barrel-roll about the bundle axis, kinematically useless) as #1 if that edge happened to swing
freest, and it anchored every joint at the edge midpoint. `recommend_hinge_joints` encodes the user's actual
design intent (the hinge is the longest cross-section *fold* edge, anchored at a face corner) and
`assert_recommended_hinge` *proves* the ranker honours it — that the top pick is a fold not a barrel-roll, is
the widest such edge, and is corner-anchored — none of which the ROM-only sort or any prior oracle asserted. The
two red-tests prove the green can go red on the exact two ways the recommendation can be wrong (axial-on-top,
midpoint-anchor). The corner-vs-midpoint anchor check is reusable for any 'named point on a named edge'
placement. No ASK-FIRST violation: all magnitudes (length, angle-to-axis, two-sided ROM), zero sign/handedness
reasoning.**"

**AF-16 — loggable cluster creation (`cluster_create` feature-log entry)** · _shape:_ NEW `ClusterCreateLogEntry`
Pydantic model in `backend/core/models.py` (mirrors `ClusterOpLogEntry`: `feature_type='cluster_create'`,
`cluster_id`/`name`/`helix_ids`/`domain_ids: List[DomainRef]`) added to the `FeatureLogEntry` discriminated union +
opt-in `log: bool = False` on the `add_cluster` route (appends the entry inside the same `copy_with(...)`, with the
cursor-truncation `update_cluster`'s commit+log path uses) + a `log=` passthrough on the `hb.add_cluster` wrapper
(default OFF — backward-compatible) + 1 reusable oracle `assert_cluster_in_feature_log` in
`tests/automation_harness.py`; `crud.py`/`assembly.py`/`main.js` LOC Δ = **0** (model in `core`, wiring in the
already-extracted `routes_clusters.py` sub-router, wrapper in `headless_build.py`) · _headless-coverage Δ:_ **35 →
35** (UNCHANGED — `add_cluster` was already covered since AF-15 P1; AF-16 adds the *log path* on an existing route,
wraps no new route — like AF-10/AF-11 it moves the oracle count, not coverage) · _oracle shipped:_
`assert_cluster_in_feature_log(design, cluster_id, *, expect_helix_ids=None)` — a **feature-log integrity** oracle:
asserts exactly one `cluster_create` entry carries `cluster_id`, its `helix_ids` are exactly the live cluster's set
(or `expect_helix_ids`), and its `name` matches. The deciding fact (4th confirmation of the blind-spot lesson):
`canonical_topology` does NOT fingerprint clusters (they're a display/geometry-layer grouping outside the strand
graph — same as loop/skip marks, deformation overlays, cluster poses), so `assert_roundtrip_stable` *cannot* prove
the grouping persisted — only the feature-log entry can; call the oracle on a `roundtrip_nadoc` result to pin
`.nadoc` survival · _tests:_ 3 new in `test_headless_build.py` (log=True records the entry with the right helices;
the entry survives a `.nadoc` round-trip; the default log=False appends NO entry — backward-compat + can-go-red) +
3 new in `test_automation_harness.py` (oracle passes on a logged creation + **two load-bearing red-tests**: an
unlogged build raises "created without logging", a mismatched `expect_helix_ids` raises "does not match the
cluster"); full suite **2529 passed / 55 skipped**, no drop · **"Validation gained, not just a passthrough:** before
AF-16 there was no `ClusterCreateLogEntry` type at all — `add_cluster` built the cluster in design state but emitted
nothing to the feature log, so a generated multi-bar part's construction history could record the bars' *poses*
(`cluster_op`) and *joints* but never the *grouping* that created them; a user replaying the log saw bars appear
fully-formed with no creation step. AF-16 makes the grouping loggable AND `assert_cluster_in_feature_log` proves
the entry names the right cluster + exact helices AND survives a round-trip — none of which any prior oracle could
assert (canonical_topology is structurally blind to clusters). The two red-tests prove the green can go red on the
two real failure modes (unlogged build, wrong helix set). It's the feature-log-integrity spine for any future
display-layer grouping/overlay that needs a loggable, round-trip-durable construction step. No ASK-FIRST violation:
creating a cluster is a pure grouping, never a topology or directionality edit.**"

---

**Full-sequencing automation — `full_sequence` + `assign_staple_sequences` wrappers + `assert_fully_sequenced`**
· _shape:_ 2 wrappers in `backend/api/headless_build.py` (`assign_staple_sequences` imports the exact
`assign_staple_sequences_endpoint` route handler → covered by function identity; `full_sequence` is composition
sugar that assigns the scaffold sequence to every scaffold strand then drives `assign_staple_sequences`) + 1 reusable
oracle `assert_fully_sequenced` in `tests/automation_harness.py`; `crud.py`/`assembly.py`/`main.js` LOC Δ = **0** ·
_headless-coverage Δ:_ design/assembly **35 → 36** (`/design/assign-staple-sequences` flips to covered — the WC-
complement-every-staple op had no headless entry; `full_sequence` itself wraps no new route, it composes the
already-covered scaffold + the newly-covered staple wrappers) · _oracle shipped:_ `assert_fully_sequenced(design, *,
require_wc=True)` — asserts zero undefined bases (the `count_undefined_bases` gate every export / `create_oxdna_job`
path uses) AND that every scaffold-paired staple base is the Watson-Crick complement of its scaffold base, walked
*independently* of the assignment code; returns the count of WC positions verified, with non-vacuity guards on both
checks · _tests:_ 4 new in `test_headless_build.py` (full_sequence leaves no undefined base on a routed single-
scaffold 6hb; `assign_staple_sequences` alone 422s without a scaffold sequence; full sequencing survives a `.nadoc`
round-trip; coverage flip) + 3 new in `test_automation_harness.py` (oracle passes on a sequenced design + **two
load-bearing red-tests**: an unsequenced design raises "undefined", a corrupted staple base raises "WC complement");
full suite **2544 passed / 55 skipped**, no drop · **"Validation gained, not just a passthrough:** the headless
surface could route a design (`auto_scaffold`/`auto_crossover`/`auto_break`) and assign a *scaffold* sequence, but
there was no programmatic way to finish the job — WC-complement the staples — so a headless-built design could not be
made export / oxDNA ready without borrowing a test helper (`_sequence_for_oxdna`, exactly the gap AF-13 P1 hit).
`full_sequence` closes that, and `assert_fully_sequenced` proves the result is *complete AND correct* (no `'N'` AND
genuinely complementary, checked against the scaffold independently of the assignment code) — so a builder that left
positions undefined, or filled them with the wrong base, fails. The two red-tests prove the green can go red. NB:
the staple complement comes from the single active scaffold, so `full_sequence` needs a routed single-scaffold
origami (`auto_scaffold` first) — documented on the wrapper.**"

---

**AF-13 — headless oxDNA relaxation (Phase 1: drive + recover)** · _shape:_ **NEW module**
`backend/api/headless_oxdna_build.py` (the first *physical-layer* headless builder — distinct lifecycle subsystem,
rule 2; mirrors `headless_assembly_build.py`): `run_relaxation` (one-call: create-no-autostart → start → poll to
terminal) + `create_job`/`start_relaxation`/`append_production`/`read_relaxed_positions`/`wait_for_terminal`, each
importing the exact route handler — `create_oxdna_job`/`start_oxdna_job`/`append_oxdna_production`/`get_oxdna_display`
— so they register covered by function identity, NOT re-implemented. Two isolation context managers
(`_use_workspace` redirects the routes' module-global `routes_oxdna._WORKSPACE_DIR`; `_scratch_design` binds the
design into a throwaway doc) so a scripted relaxation never touches the real workspace / active design. The route
handlers are `async` → driven via `asyncio.run`. + 1 reusable oracle `assert_relaxed_geometry_recovered` in
`tests/automation_harness.py` + NEW **separate** `oxdna_coverage_report()` (refactored the existing report into a
shared `_coverage_report(modules, path_predicate)` core so `headless_coverage_report()`'s output is byte-identical —
still 35); `crud.py`/`assembly.py`/`main.js` LOC Δ = **0** (all new code is a new module + the harness) ·
_headless-coverage Δ:_ design/assembly **35 → 35** (untouched — oxDNA is a separate surface); NEW oxDNA audit shows
**3 `/oxdna` mutation routes covered** (`create_oxdna_job` + `start_oxdna_job` + `append_oxdna_production`;
`get_oxdna_display` is a read-only GET, correctly absent from the mutation audit, pinned by an import-identity test) ·
_oracle shipped:_ `assert_relaxed_geometry_recovered(job, design, workspace, *, expected_count=None)` — a
**physical-layer recovery** oracle: asserts (1) the terminal `OxdnaJob` reached `completed`; (2) the display route
reads the relaxed `last_conf` back (`ready`) via `read_configuration_unwrapped` (PBC-unwrapped + Kabsch-aligned);
(3) the recovered map has exactly one **finite** position per design nucleotide AND every recovered
`(helix_id, bp, direction)` key is a real key of the design's geometry (set-equal, so a dropped/truncated/mis-keyed
conf is caught). **Physical-layer only** — it reads the relaxed geometry, never asserts it was written into `Design`
(the Three-Layer Law) · _tests:_ 7 new in `test_headless_oxdna_build.py` (run_relaxation completes + recovers
geometry; create→start two-step; append-production extends a completed job + still recovers; coverage flip;
import-identity; + **two load-bearing red-tests**: a non-completed job raises "did not reach completed", a wrong
expected_count raises "expected …") + 1 new in `test_automation_harness.py` (oxDNA audit is separate + design/assembly
stays 35 + the 3 routes covered); runs against the mock binary (`$OXDNA_BIN`), `min_bp_retained=0.0` since the mock
copies conf→last_conf rather than relaxing; full suite **2537 passed / 55 skipped**, no drop ·
**"Validation gained, not just a passthrough:** before AF-13 the physical layer was browser-only — there was *no way
at all* to relax a design and recover the result without the Dynamics panel, and therefore nothing pinned that a
headless relaxation runs to completion and yields readable relaxed geometry. `assert_relaxed_geometry_recovered` is
the first physical-layer oracle: it drives a real oxDNA job to `completed` and proves the relaxed last frame reads
back as a full per-nucleotide position map (count + finiteness + key-coverage), so a builder that failed silently,
dropped nucleotides, or returned an unreadable conf fails — with two red-tests proving the green can go red. It is
the spine the AF-13 P2+ measurement/constraint oracles (the stochastic measured-property-within-tolerance class) pin
themselves against — the physical-layer analog of what AF-1 did for designs and AF-7 for assemblies. No ASK-FIRST
violation: Phase 1 exposes ONLY the read path and asserts a count/coverage property, no geometry/directionality
reasoning (the landmark-direction question is deferred to Phase 2, where the backlog flags it ASK-FIRST).**"

---

**AF-13 — relaxed-geometry MEASUREMENT oracle (Phase 2: the constraint primitive)** · _shape:_ **service + oracle
push** — pure `measure_end_to_end(positions, a, b)` in `backend/core/oxdna_health.py` (the reusable `measure_*`
primitive; Euclidean nm between two landmark backbone sites; raises on empty/identical/absent) + 1 read-wrapper
`read_flexibility_map(job_id, ws)` in `backend/api/headless_oxdna_build.py` (drives the REAL `get_oxdna_rmsf`
route handler — registers covered by function identity — for the pooled noise-averaged mean structure +
`confidence`) + 1 reusable oracle `assert_relaxed_measurement` in `tests/automation_harness.py`;
`crud.py`/`assembly.py`/`main.js` LOC Δ = **0** (all new code is a pure core fn + the existing headless module +
the harness) · _headless-coverage Δ:_ **UNCHANGED** (oxDNA mutation routes still 3; `get_oxdna_rmsf` is a
read-only GET, like `get_oxdna_display` — excluded from the *mutation* audit, pinned instead by the
import-identity test `hox._route_get_rmsf is routes_oxdna.get_oxdna_rmsf`) · _landmark convention (ASK-FIRST,
answered by user):_ the raw **`(helix_id, bp_index, direction)` tuple** — most primitive, indexes the
relaxed-display + RMSF maps directly, no strand-polarity/terminus resolution (a strand-terminus convenience layer
can sit on top later) · _oracle shipped:_ `assert_relaxed_measurement(job, measure_spec, target_nm, tol_nm, *,
workspace, min_confidence=RMSF_PRELIM_FRAMES)` — the **first STOCHASTIC-class oracle**: status-completed guard +
reads the production mean structure (preferred over a single frame — the mean cancels thermal noise) + **the
confidence gate** (≥ `min_confidence` pooled frames, else INCONCLUSIVE-raise — a too-short run cannot certify a
target; the load-bearing guard AF-13 P3 formalises) + measured ∈ [target ± tol]. `measure_spec =
{"measure":"end_to_end","landmarks":[a,b]}` · _tests:_ 3 pure in `test_oxdna_relaxation.py` (exact distance +
order-independence; Direction-enum/str normalisation; rejects empty/identical/absent) + 5 in
`test_headless_oxdna_build.py` driving a purpose-built trajectory-writing mock (mean+confidence readback;
end-to-end matches the design's own e2e to ~0.002 nm at tol 0.1; **3 load-bearing red-tests**: wrong target raises
"not within", 10 pooled frames < 50 raises "INCONCLUSIVE", no production run raises "no production mean
structure") + 1 import-identity assert; full suite **2552 passed / 55 skipped**, no drop ·
**"Validation gained, not just a passthrough:** before AF-13 P2 there was no way to *measure* a property of a
relaxed structure headlessly, and AF-13 P1 only proved geometry reads back — nothing asserted a
user-meaningful physical quantity (an end-to-end distance) is correct *and trustworthy*. `assert_relaxed_measurement`
closes that: it measures the noise-averaged mean structure (not a single noisy frame) and asserts the value within
tolerance ONLY when enough frames are pooled — the confidence gate is genuinely new validation power, because a
measured-property oracle without it would certify a target from a 1-frame run that's pure thermal noise. On the
identity-mock fixture the relaxed mean reproduces the design's own end-to-end to ~0.002 nm (a 0.1 nm pin), proving
the whole physical-layer measurement pipeline (drive production → pool → mean → address two landmarks → Euclidean
distance) is faithful; the 3 red-tests prove the green can go red on a wrong target, too-few frames, and a missing
production run. It is the stochastic-oracle spine AF-13 P3's declarative constraint checker + P4's iterate-until-met
loop both build on. No ASK-FIRST violation: the landmark convention was asked + answered (raw tuple), and the
measurement is a direction-agnostic Euclidean magnitude — no bend/sign/frame reasoning.**"

**AF-13 Phase 3 — declarative constraint spec + pure REPORTING checker** · _shape:_ **service + oracle push** —
2 pure HTTP-free fns in `backend/core/oxdna_health.py` (`parse_constraint_spec` validates+normalises a
`{measure, landmarks, target_nm, tol_nm, min_confidence}` spec, raising `ConstraintSpecError` at parse time;
`check_relaxed_constraint(constraint, relaxed_output)` REPORTS `{met, status, measured_nm, target_nm, tol_nm,
n_frames, min_confidence, confidence}` by reusing the P2 `measure_end_to_end` primitive over the
`read_flexibility_map` mean-structure dict) — NO route wrapped, `backend/api`/`backend/core` boundary respected
(the checker takes the already-read relaxed dict, never imports the api read-wrapper);
`crud.py`/`assembly.py`/`main.js` LOC Δ = **0** · _headless-coverage Δ:_ **UNCHANGED** (composition over P2's
already-pinned read path + pure core math; wraps no new route — like AF-10/AF-11 it moves the oracle/primitive
count, not coverage) · _oracle/augment shipped:_ the **confidence-gated constraint REPORTER** itself
(`check_relaxed_constraint`) + its can-go-red test set — distinct from P2's *asserter* (`assert_relaxed_measurement`,
which raises in a test): the checker returns a verdict an automated loop branches on, with `status ∈
{met, unmet, inconclusive}` and the **load-bearing invariant `met` is NEVER True below `min_confidence`**. Pinned
by (a) 13 parametrized `parse_constraint_spec` rejections (bad dict/key/measure/landmark-count/identical/bp_index/
triple/target/tol/min_confidence) + idempotency + default-min_confidence; (b) the met/unmet tolerance bracket
(target 4.5 tol 0.5 → met at |Δ|=0.5; target 4.4 → unmet at 0.6); (c) **the confidence-gate red-test** — a value
squarely within tolerance but only 10 frames pooled reports `inconclusive`/`met=False` (flip the guard and it goes
red); (d) two integration tests driving a REAL `_MOCK_OXDNA_TRAJ` run → `read_flexibility_map` → checker (60-frame
→ met; 1000-step/10-frame → inconclusive-not-met), proving the checker consumes the actual relaxed-output dict
shape and the gate fires on a genuine under-sampled production · _tests:_ 20 new in `test_oxdna_relaxation.py`
(pure) + 2 new in `test_headless_oxdna_build.py` (real-run integration); full suite **2574 passed / 55 skipped**,
no drop (P2 baseline was 2552) · **"Validation gained, not just a passthrough:** before P3 there was only the
*asserting* oracle (P2's `assert_relaxed_measurement`, which raises inside a test); nothing gave a closed-loop
builder a *verdict to branch on* with the safety guarantee that it cannot certify `met` from an under-sampled
run. `check_relaxed_constraint` is that contract — a pure, tested decision function whose load-bearing,
red-tested invariant is "never report met below `min_confidence`, even when the value is within tolerance." That
is the exact guard AF-13 P4's iterate-until-met loop needs to avoid converging on thermal noise, and the
`parse_constraint_spec` rejection set is itself new validation power (a malformed constraint fails at parse time,
before any expensive relaxation runs). It slots into the AF-11 build-spec grammar as a design `constraints`
block. No ASK-FIRST: reuses P2's already-cleared landmark convention + direction-agnostic Euclidean measure;
this layer adds only spec validation + the confidence-gated met/unmet/inconclusive decision.**"

---

**AF-17 — headless simulation Benchmark access + relaxation auto-tune bridge** · _shape:_ **service + headless
wrappers** — 1 pure fn in `backend/core/benchmark.py` (`resolve_oxdna_relax_config(hw)` maps a stored
`HardwareBenchmark` → the `{backend, device}` a relaxation should use, CPU/"0" fallback when none; PURE, no I/O /
no hostname lookup — the caller selects the slot) + 3 wrappers in `backend/api/headless_oxdna_build.py`
(`run_oxdna_benchmark` drives the REAL `benchmark_runner.run_oxdna_trials` sweep inline against a size-matched
synthetic proxy, injectable `runner=`/`configs=` so the CUDA branch is exercisable GPU-free; `apply_oxdna_benchmark`
writes a recommendation into a COPY of the design's `metadata.hardware_defaults[hostname]`, mirroring the apply
route on a passed design; `run_relaxation_tuned` resolves that default → backend/device → `run_relaxation`, the
bridge for the iterate-until-met loop) + 1 reusable oracle `assert_relax_honors_hardware_default` in
`tests/automation_harness.py`; `crud.py`/`assembly.py`/`main.js` LOC Δ = **0** · _headless-coverage Δ:_ **UNCHANGED**
(the benchmark routes are `/benchmark/*`, outside the design/assembly mutation audit; the sweep wrapper drives the
runner functions directly, not a route handler — like AF-10/AF-11 this moves the oracle count, not coverage) ·
_oracle shipped:_ `assert_relax_honors_hardware_default(design, workspace, *, backend, device="0", **params)` — a
**physical-layer bridge** oracle: (1) baseline — `run_relaxation_tuned` on a design with NO benchmarked default must
complete on the CPU/"0" fallback (also proving the non-CPU result below comes from the stored default, not a
constant); (2) tuned — apply `{backend, device}`, relax again, assert the terminal `OxdnaJob` carries that exact
backend/device (the metadata flowed benchmark→`hardware_defaults`→relaxation config, read straight off
`OxdnaJob.backend`/`.device`); (3) non-vacuity — the requested config must differ from the CPU fallback, so the
oracle is only meaningful for a non-default config (`backend="CUDA"`, `device="1"`). GPU-free: the mock binary
ignores the declared backend · _tests:_ 7 new in `test_headless_oxdna_build.py` (pure resolve+fallback; headless
sweep produces a well-formed recommendation; injected 2-config grid drives the real pick-best → CUDA wins;
the bridge oracle green; full producer→apply→relax chain; **two load-bearing red-tests**: a bridge that hard-codes
CPU raises "did not honour the benchmarked default", and a vacuous CPU/0 request is rejected); full suite **2678
passed / 55 skipped**, no drop · **"Validation gained, not just a passthrough:** before AF-17 the Benchmark button's
auto-tuned config was written to `metadata.hardware_defaults` and read ONLY by the frontend to pre-fill the panel —
**no backend path consumed it into a run**, so nothing proved the discovered device ever reaches oxDNA, and an
automated loop had no way to run a benchmark or relax on its result. `assert_relax_honors_hardware_default` closes
that end-to-end: it proves a stored hardware default flows benchmark→metadata→relaxation backend/device (CUDA:1
lands in the oxDNA job; an un-tuned design falls back to CPU), with a non-vacuity guard + a red-test proving a
bridge that ignored the default goes red. That is the exact capability AF-13 P4's iterate-until-met loop needs to
relax on the fastest discovered backend instead of a hard-coded CPU default. No ASK-FIRST: this is hardware-config
plumbing (backend/device strings), not DNA topology/geometry — zero sign/frame reasoning.**"

---

**AF-13 Phase 4 — iterate-until-met loop (the Tier-5 CAPSTONE)** · _shape:_ **composition driver** — 1 loop driver
`iterate_to_constraint` + 1 helper `_pool_until_conclusive` in `backend/api/headless_oxdna_build.py` (composes the
already-covered `run_relaxation`/`run_relaxation_tuned` + `append_production` + `read_flexibility_map` wrappers +
the pure `parse_constraint_spec`/`check_relaxed_constraint`; re-implements NOTHING) + 1 reusable oracle
`assert_converges_to_constraint` in `tests/automation_harness.py`; `crud.py`/`assembly.py`/`main.js` LOC Δ = **0** ·
_oxDNA-coverage Δ:_ **UNCHANGED** (wraps no new route — composition-sugar over covered wrappers + a pure-core
reporter, like AF-10/AF-11; moves the oracle count, not the coverage count) · _oracle shipped:_
`assert_converges_to_constraint(result, *, target_nm, tol_nm, min_confidence=RMSF_PRELIM_FRAMES)` — asserts the loop
reached `status=="met"` within budget, the **winning** verdict is `met` AND pooled from ≥`min_confidence` frames, NO
intermediate iteration flipped `met` below the gate, the final measured value is within `tol_nm`, and — the
non-vacuity guard — the FIRST attempt was NOT already met (so the adjust loop was actually exercised). The driver
branches on the P3 verdict **status**, never the raw `measured_nm`; on `inconclusive` it appends MORE production to
the same job (the rmsf route pools every production stage → frames accumulate) until the gate clears, NOT a knob
change · _tests:_ 5 new in `test_headless_oxdna_build.py` (bend-curvature knob + bisection converges + oracle passes;
inconclusive→grow-production with the knob held on-target so the adjust_fn must never fire; **two load-bearing
red-tests**: an unreachable target exhausts and the oracle raises "did not converge"; an attempt-0 win raises the
non-vacuity guard; + a fail-fast `ConstraintSpecError` on a malformed constraint before any run); full suite **2732
passed / 55 skipped**, no drop · **"Validation gained, not just a passthrough:** before P4 the pieces existed
(P1 relax, P2 measure, P3 confidence-gated checker, AF-6 deformation knobs, AF-17 tuned relax) but nothing proved
they COMPOSE into a closed constraint-driven design loop that actually converges. `assert_converges_to_constraint` is
the first proof that a build→relax→measure→adjust loop drives a parametric topology knob into a relaxed-structure
tolerance band — AND that it never cheats the confidence gate on ANY step (the load-bearing P3 property, now enforced
across a closed loop instead of a single read), with red-tests proving an unreachable target exhausts rather than
falsely declaring met and that an already-on-target start is rejected as vacuous. The augment's key trick (reusable):
the identity mock can't move atoms, so a real TOPOLOGY knob (a bend) is what moves the measured geometry, making the
SEARCH testable GPU-free; a bend keeps landmark keys stable (it's a deformation overlay, not a topology change). No
ASK-FIRST: the driver + fixture are direction-AGNOSTIC end-to-end (curvature magnitude + Euclidean distance + AF-6's
already-cleared bend wrapper) — zero new sign/frame reasoning. This closes the Tier-5 physical-layer spine: the
text-to-DNA goal's constraint-driven-design capstone.**"

**measure_* growth — `radius_of_gyration` (whole-structure constraint kind)** · _shape:_ **service + oracle growth**
— 1 new pure measure `measure_radius_of_gyration(positions)` next to `measure_end_to_end` in
`backend/core/oxdna_health.py` + the grammar generalised to **measure-dependent landmark arity**
(`_MEASURE_LANDMARK_COUNT = {end_to_end:2, radius_of_gyration:0}`; `parse_constraint_spec` now accepts a
landmark-less whole-structure measure and REJECTS landmarks passed to one) + a `_dispatch_measure` arm wired into
`check_relaxed_constraint` + `assert_relaxed_measurement` (harness) branched to dispatch on the measure kind;
`crud.py`/`assembly.py`/`main.js` LOC Δ = **0** · _oxDNA-coverage Δ:_ **UNCHANGED** (wraps no new route — a pure-core
measure + grammar growth; moves the oracle count, not the coverage count) · _oracle shipped:_
`measure_radius_of_gyration(positions)` — the pure reusable primitive: `sqrt(mean_i |r_i − r_cm|²)` over ALL
nucleotide backbone sites (no landmarks), pinned to closed-form values (two points at ±5 nm → R_g 5.0; cube corners →
sqrt(3)·a) and raising on an empty map; it now flows through the EXISTING `check_relaxed_constraint` (confidence gate +
tolerance bracket unchanged) and `assert_relaxed_measurement` (status guard + confidence gate) — so the AF-13 P4
iterate loop + the AF-11 `constraints` block get R_g **for free** the moment they target it · _tests:_ 5 new in
`test_oxdna_relaxation.py` (analytic R_g; empty-raises; parse no-landmarks normalises + idempotent; parse rejects
landmarks-on-rg; `check_relaxed_constraint` dispatches rg with the confidence gate + tolerance bracket) + 2 new in
`test_headless_oxdna_build.py` (rg through the harness oracle on a real run; **load-bearing red-test**: a wrong R_g
target raises "not within"); full suite **2739 passed / 55 skipped**, no drop · **"Validation gained, not just a
passthrough:** before this, the ONLY relaxed-structure constraint was a two-landmark end-to-end distance — nothing
could certify a structure's *overall* size/compactness, which a point-pair distance is blind to (a structure can hold
its end-to-end while its bulk swells or collapses). `measure_radius_of_gyration` adds that whole-structure measure, and
— the genuinely-new structural power — the constraint grammar now supports **measure-dependent landmark arity** (a
landmark-less measure parses; landmarks passed to one are rejected), so every future `measure_*` kind (inter-helix
spacing, segment angle) slots in by adding a name + arity + one dispatch arm rather than rewriting the parser. The
red-test proves the oracle goes red on a wrong target. No ASK-FIRST: R_g is a translation/rotation-invariant scalar
magnitude — zero sign/frame/handedness reasoning.**"

**measure_* growth — `segment_angle` (the first 3-landmark / non-length constraint kind)** · _shape:_ **service +
oracle growth** — 1 new pure measure `measure_segment_angle(positions, a, b, c)` next to `measure_end_to_end` /
`measure_radius_of_gyration` in `backend/core/oxdna_health.py` (the interior bend angle in DEGREES at the middle
landmark `b` of the chain a–b–c, `arccos((a−b)·(c−b)/(|a−b||c−b|))`, arccos-domain-clamped) + the name added to
`_CONSTRAINT_MEASURES` + `_MEASURE_LANDMARK_COUNT["segment_angle"]=3` (exercising the **3-landmark arity** for the
first time — `{0,2}`→`{0,2,3}`; the AF-13-P3 arity generalisation accepted it with zero parser changes) + a
`_dispatch_measure` arm + an `assert_relaxed_measurement` (harness) branch that reports the right **unit** (`deg`,
not `nm`, in the failure message); `crud.py`/`assembly.py`/`main.js` LOC Δ = **0** · _oxDNA-coverage Δ:_ **UNCHANGED**
(wraps no new route — a pure-core measure + grammar growth; moves the oracle count, not the coverage count) · _oracle
shipped:_ `measure_segment_angle` — the pure reusable primitive: pinned to closed-form angles (right angle → 90°,
collinear → 180°, 60° wedge → 60°; leg-order-about-the-vertex-invariant) + raising on empty map / coincident pair /
absent landmark / zero-length leg; it flows through the EXISTING `check_relaxed_constraint` (confidence gate +
tolerance bracket unchanged, now in degrees) and `assert_relaxed_measurement`. **The LOAD-BEARING augment is
`test_segment_angle_captures_bend`** — three collinear landmarks along a STRAIGHT bundle read ~175° and the SAME
landmarks on a bundle bent at the middle read strictly < (here 119°, a >55° drop): the geometric proof the measure
actually tracks curvature, not a constant · _tests:_ 6 new in `test_oxdna_relaxation.py` (analytic 90/180/60 +
leg-swap invariance; rejects empty/coincident/absent; parse 3-landmarks normalises + idempotent; parse rejects
2-landmarks-for-segment_angle [parametrized]; `check_relaxed_constraint` dispatches segment_angle with the confidence
gate + tolerance bracket) + 3 new in `test_headless_oxdna_build.py` (segment_angle through the harness oracle on a
real run, certified against the design's own angle with a 3° tol absorbing the oxDNA-vs-design backbone-site
convention; **load-bearing geometric augment** `captures_bend` straight-vs-bent; **red-test**: a wrong angle target
raises "not within"); full suite **2747 passed / 55 skipped**, no drop · **"Validation gained, not just a
passthrough:** before this every relaxed-structure constraint was a *length* (`end_to_end` nm, `radius_of_gyration`
nm) — nothing could certify a structure's *shape/curvature*, which a distance scalar is blind to (a bundle can hold
its end-to-end while kinking sharply at the middle). `measure_segment_angle` adds the first ANGULAR measure, and —
the genuinely-new structural power — `captures_bend` proves the angle actually responds to a topology bend
(straight ~175° → bent 119° on the SAME landmarks) rather than reading a constant; the red-test proves it goes red
on a wrong target. It also exercises the 3-landmark arity (the arity generalisation's first non-{0,2} consumer,
proving that path was real, not speculative), so segment angle slots into the iterate loop + the AF-11 `constraints`
block for free. No ASK-FIRST: an `arccos` is a magnitude — zero sign/frame/handedness reasoning.**"

**measure_* growth — `inter_helix_spacing` (the first axis-grouping constraint kind)** · _shape:_ **service +
oracle growth** — 1 new pure measure `measure_inter_helix_spacing(positions, a, b)` + a private `_fit_helix_axis`
helper in `backend/core/oxdna_health.py` + the name added to `_CONSTRAINT_MEASURES` + `_MEASURE_LANDMARK_COUNT
["inter_helix_spacing"]=2` (reuses the existing 2-landmark arity) + a `_dispatch_measure` arm + an
`assert_relaxed_measurement` (harness) branch (unit stays **nm** — no degrees wart); `crud.py`/`assembly.py`/`main.js`
LOC Δ = **0** · _oxDNA-coverage Δ:_ **UNCHANGED** (wraps no new route — a pure-core measure + dispatch growth; moves
the oracle count, not the coverage count) · _oracle shipped:_ `measure_inter_helix_spacing` — the first measure that
**groups by helix and fits an axis**: each landmark only NAMES a helix (via `helix_id`), ALL of that helix's backbone
sites are gathered, `_fit_helix_axis` fits a centroid + PCA principal direction, and the spacing is the centroid
separation projected *perpendicular to the common (mean) axis* (PCA sign aligned). Deliberately NOT the minimal
infinite-line distance — that collapses to ~0 for near-parallel tilted axes (the fragile regime spacing means); this
form is exact for parallel helices and robust to relaxed-bundle tilt. Pinned to analytic parallel/axially-staggered/
slightly-tilted values + raising on empty / same-helix / absent-landmark / single-site-helix; flows through the
EXISTING `check_relaxed_constraint` + `assert_relaxed_measurement` unchanged · _tests:_ 5 new in
`test_oxdna_relaxation.py` (analytic parallel 2.5 nm + symmetry; axial-stagger + tilt-robustness; rejects
empty/same-helix/absent/single-site; parse 2-landmarks normalises + idempotent; `check_relaxed_constraint` dispatches
it with the confidence gate + tolerance bracket) + 3 new in `test_headless_oxdna_build.py` (**load-bearing geometric
augment** `captures_separation`: a straight 3-in-a-row SQUARE bundle reads equal adjacent gaps ~2.25 nm and a skip-one
gap ~2×; the measure through the harness oracle on a real run; **red-test**: a wrong spacing target raises "not
within"); full suite **2755 passed / 55 skipped**, no drop · **"Validation gained, not just a passthrough:** before
this every relaxed-structure measure was either a point-to-point quantity (`end_to_end`, `segment_angle`) or a
whole-structure scalar (`radius_of_gyration`) — nothing could certify the *radial packing* of a bundle, the property
that says whether helices relaxed to their lattice spacing or splayed/collapsed. `measure_inter_helix_spacing` adds
that, and — the genuinely-new structural power — it introduces the **axis-grouping pattern** (group sites by helix →
fit an axis → relate two axes), which no prior measure needed; the `captures_separation` augment proves it tracks real
separation (adjacent vs skip-one, ~2× on a straight row) rather than a constant, and the red-test proves it goes red on
a wrong target. The design note that the infinite-line distance is fragile near-parallel (and is rejected in favour of
the perpendicular-to-mean-axis projection) is itself banked validation knowledge. No ASK-FIRST: a length magnitude with
sign-aligned axes — zero handedness/frame reasoning.**"

**AF-13 P5 — design `constraints` block wired into the AF-11 grammar (attach + report, no knob)** · _shape:_
**grammar growth + composition driver** — the pure parser `backend/core/build_spec.py` gains an optional top-level
`constraints` list on a design spec (`DesignSpec.constraints`; each constraint a `{measure, landmarks, target_nm,
tol_nm, min_confidence}` whose landmarks name a helix by **grid_pos** `{helix:[r,c], bp_index, direction}`), validated
at parse time by handing the cell-normalised constraint to the AF-13 P3 `parse_constraint_spec` (so a malformed
constraint fails BEFORE any build/relax) + 2 driver fns in `backend/api/headless_spec_build.py`
(`build_and_check_design(spec, ws, *, steps, tuned, **relax_params) → {design, verdicts}` and the lower-level
`check_design_constraints` — resolve each landmark's grid_pos → runtime id up front (fail-fast), relax ONCE +
production, then `check_relaxed_constraint` per constraint; drives the already-covered `hox.run_relaxation`/
`append_production`/`read_flexibility_map`, re-implements nothing) + 1 reusable oracle
`assert_spec_constraints_reported` in `tests/automation_harness.py`; `crud.py`/`assembly.py`/`main.js` LOC Δ = **0** ·
_oxDNA-coverage Δ:_ **UNCHANGED, 36** (wraps no new route — composition sugar over covered wrappers + a pure-core
reporter, like AF-10/AF-11/P4; `test_spec_build_adds_no_coverage` still asserts 36) · _oracle shipped:_
`assert_spec_constraints_reported(spec_result, hand_verdicts, *, measured_tol=1e-6)` — asserts the grammar's
`constraints` path reports the SAME per-constraint verdict (status + `met` + `measured_nm` within tol; `None` only
matches `None`) a hand-driven `check_relaxed_constraint` does, with a non-vacuity guard (≥1 verdict) + count-mismatch
guard. **It is load-bearing because `assert_spec_matches_calls` is BLIND to a physical-layer verdict** — the
canonical-topology fingerprint cannot see whether a constraint was attached, its landmark resolved to the right helix,
or it was reported at all; only verdict-equality proves the lowering is faithful · _tests:_ 2 grammar-normalisation +
7 grammar rejections (unknown measure, wrong landmark arity, landmarks-on-`radius_of_gyration`, non-positive tol,
landmark missing a field, typo'd field, constraints-not-a-list) in `test_build_spec.py` + 4 driver tests in
`test_headless_spec_build.py` (no-constraints → empty verdicts + no oxDNA run; `radius_of_gyration` reports == hand;
`end_to_end` grid_pos landmarks RESOLVE + report == hand; unknown grid_pos fails fast before any relaxation) + 5
oracle tests in `test_automation_harness.py` (passes on matching verdicts + **four load-bearing red-tests**: status
mismatch, measured divergence (wrong-helix), count mismatch, empty-list vacuity); full suite **2920 passed / 55
skipped**, no drop · **"Validation gained, not just a passthrough:** before this the AF-13 P3 `check_relaxed_constraint`
reporter existed but was un-wired — a design spec could not carry a relaxed-structure constraint, so nothing proved a
*declarative* constraint is lowered to the same verdict a hand call yields. `assert_spec_constraints_reported` closes
that: it proves the grammar resolves each grid_pos landmark to the correct runtime helix, runs the right measure, and
applies the confidence gate identically to a hand-driven check — the exact guarantee text-to-DNA's constraint clauses
rest on, and the property `assert_spec_matches_calls` is structurally blind to. All four `measure_*` kinds get the
grammar path for free (the parser dispatches on the measure name). The four red-tests prove the green can go red. No
ASK-FIRST: grid_pos→id resolution is a lookup, the measures are magnitudes — zero frame/sign reasoning.**"

---

**AF-13 P6 — design `optimize` block (knob → `iterate_to_constraint`)** · _shape:_ **grammar growth + composition
driver** — the pure parser `backend/core/build_spec.py` gains an optional top-level `optimize` block on a design spec
(`DesignSpec.optimize`; `_parse_optimize`/`_parse_knob`): a parametric `knob` (`{op:<ops index>, param:<numeric param
name>, lo, hi, initial, response:"increasing"|"decreasing"}`) + a single AF-13 P3 `constraint`. Validated at parse time
— knob index in range, `param` present on that op AND numeric, `lo<hi`, `initial∈[lo,hi]`, `response` in the enum,
constraint via `parse_constraint_spec` — so a malformed optimize block raises `BuildSpecError` BEFORE any build/relax +
1 driver fn `hs.build_and_optimize_design(spec, ws, *, max_iterations, production_steps, tuned, **relax_params)` + 2
helpers (`_ops_with_knob` clones the op list overriding the knob param; `_synth_bisection` lowers the declared
`response` to a bisection `adjust_fn` direction) in `backend/api/headless_spec_build.py` — it synthesises `build_fn`
(rebuild with the knob) + `adjust_fn`, resolves the constraint's grid_pos landmarks → runtime ids on ONE probe build
(ids deterministic → stable across rebuilds), and drives the already-covered `hox.iterate_to_constraint`, re-implements
nothing; `crud.py`/`assembly.py`/`main.js` LOC Δ = **0** · _oxDNA-coverage Δ:_ **UNCHANGED, 36** (wraps no new route —
composition sugar over covered wrappers + a closed loop, like P4/P5; `test_spec_build_adds_no_coverage` still asserts
36) · _oracle shipped:_ **REUSES `assert_converges_to_constraint`** (the AF-13 P4 capstone oracle — status `met` +
winning verdict confidence-gated + every step's gate held + final within tol + **non-vacuity**), now driven entirely
from a declarative spec. **Load-bearing because `assert_spec_matches_calls` is BLIND both to the bend overlay AND to a
physical-layer convergence** — the canonical-topology fingerprint cannot see whether the knob moved the relaxed
end-to-end onto target; only the convergence oracle proves the optimize block lowered to a real, converging loop ·
_tests:_ 3 grammar-normalisation (knob+constraint normalise; `initial` defaults to bracket midpoint; defaults to no
optimize) + 10 grammar rejections (op index out of range, param not on the op, param non-numeric, `lo≥hi`, `initial`
outside bracket, bad `response`, typo'd knob field, missing knob, missing constraint, malformed inner constraint
propagates) in `test_build_spec.py` + 4 driver tests in `test_headless_spec_build.py` (the augment: spec converges a
bend-curvature knob to the target, bisecting `2.0→3.0→2.5` deterministically; **two load-bearing red-tests**:
unreachable target → exhausted → oracle raises "did not converge", initial knob on-target → vacuous → oracle raises;
+ no-optimize-block → `BuildSpecError`); full suite **2975 passed / 55 skipped**, no drop · **"Validation gained, not just a
passthrough:** before this the AF-13 P4 `iterate_to_constraint` loop existed but had to be hand-wired (a Python
`build_fn`/`adjust_fn` per design); a *declarative* spec could attach+report a constraint (P5) but not DRIVE a knob to
satisfy it. `build_and_optimize_design` closes that: a JSON spec now says 'vary this op's parameter until the relaxed
structure meets this constraint', and `assert_converges_to_constraint` proves the grammar synthesises a faithful
build/adjust pair that actually converges — confidence-gated and non-vacuous — the constraint-DRIVEN text-to-design
rung the whole Tier-5 spine was built toward, and the property `assert_spec_matches_calls` is structurally blind to.
The deterministic `2.0→3.0→2.5` bisection pins that the declared monotone `response` lowered to the correct direction;
the two red-tests prove the green can go red. No ASK-FIRST: the knob magnitude is direction-agnostic and the monotone
sense is a spec-author declaration the grammar lowers, never an inferred bend sign.**"

---

**AF-12 P1 — build from a saved validated primitive (`from_file` in the assembly build-spec)** · _shape:_ **grammar
growth + composition driver** — the pure parser `backend/core/build_spec.py` gains a `FilePart` marker + `_parse_part`:
an assembly spec's `parts` library entry may now be `{"from_file": "<path>"}` (referencing a saved validated `.nadoc` by
path) instead of an inline design spec. Discriminated by the `from_file` key; validated (non-empty string path, no extra
keys) so a malformed file part raises `BuildSpecError` at parse time, and restricted to `add_part` placement
(place_grid/place_ring instance an inline design per slot → rejected). The interpreter
`backend/api/headless_spec_build.py` (`_build_assembly_from_parsed`/`_run_assembly_op`) lowers a file part to the
already-covered `hab.add_file_instance(path)` — the validated design travels as a REFERENCE, never an embedded copy;
re-implements nothing; `crud.py`/`assembly.py`/`main.js` LOC Δ = **0** · _coverage Δ:_ **UNCHANGED, 36** (wraps no new
route — `add_file_instance` already existed; `test_spec_build_adds_no_coverage` still asserts 36) · _oracle shipped:_
**NEW `assert_part_from_file(assembly, instance_id, expected_topology)`** in `tests/automation_harness.py` — loads the
design the file instance actually references (via the assembly route's `_load_design_from_source`) and asserts its
`canonical_topology` equals the saved primitive's, after asserting the instance is genuinely file-backed (an inline copy
defeats the point). **Load-bearing because `canonical_assembly` keys a *file* source by `("file", path, sha256)` ONLY —
it NEVER loads the design behind the path** — so `assert_spec_matches_calls` catches a dropped/wrong-path `from_file` but
is structurally blind to whether the path resolves to the INTENDED validated topology · _tests:_ +10 — `test_build_spec`
(1 parse: file part → FilePart, inline still DesignSpec; 5 reject: empty path, non-string path, extra keys, place_grid on
file part, place_ring on file part) + `test_headless_spec_build` (1 augment: a `from_file` part mated to an inline beam
resolves to exactly the saved 6hb's topology; 2 can-go-red: wrong-topology substitute → "DIFFERENT topology", oracle
pointed at the inline beam → "not file-backed"; 1 roundtrip: the file source survives a `.nass` round-trip); full suite
**2985 passed / 55 skipped**, no drop · **"Validation gained, not just a passthrough:** before this, an assembly spec
could ONLY embed parts inline — a JSON spec re-declared a primitive's full topology every time, so there was no way to
say 'instance the hinge I hand-authored and experimentally validated'. `from_file` adds that reference-by-path rung, and
`assert_part_from_file` proves the grammar wired the right path through to a real, loadable, topology-bearing instance —
i.e. 'build from primitive X provably uses *exactly* validated X', so a stale/renamed/edited primitive can't silently
substitute. That referential-integrity-against-the-loaded-design property is precisely what `canonical_assembly` (which
only fingerprints the path string) is blind to, exactly as `assert_binding_resolves` covers the overhang-binding blind
spot. The two can-go-red tests prove the green can go red.**"

---

**AF-12 follow-up — file-backed `place_grid`/`place_ring` (parametric layout by reference)** · _shape:_ **2 new
wrappers + grammar un-gate + interpreter dispatch** — `backend/api/headless_assembly_build.py` gains
`place_file_grid(path, rows, cols, …)` / `place_file_ring(path, n, …)`, the file-backed twins of the AF-10
`place_grid`/`place_ring`: identical per-slot `grid_translations`/`ring_translations`, but each slot drives the existing
`add_file_instance(path)` instead of `add_inline_instance(design)` — so the validated saved `.nadoc` travels as ONE path
reference per copy, not rows·cols embedded designs. `build_spec.parse_assembly_spec` drops its parse-time rejection of a
file part under `place_grid`/`place_ring`; `headless_spec_build._run_assembly_op` dispatches on `part in file_paths`.
Re-implements no operation; `crud.py`/`assembly.py`/`main.js` LOC Δ = **0** · _coverage Δ:_ **UNCHANGED** (the
`place_file_*` wrappers loop the already-covered `add_file_instance` — no new route) · _oracle shipped:_ **NEW
`assert_instances_from_file(assembly, expected_topology, *, instance_ids=None)`** in `tests/automation_harness.py` — the
layout-AGNOSTIC source pin: it LOADS the design behind EVERY selected slot and asserts each is file-backed and resolves
to the saved primitive's `canonical_topology`, with a non-vacuity guard. The plural of `assert_part_from_file`; it
composes with `assert_instances_on_grid`/`_on_ring` (which pin the lattice but never load the design) for the full
file-backed-layout proof · _tests:_ **net +9 (suite 2985 → 2994)** — `test_build_spec` (2 accept: file part now parses
under place_grid + place_ring, REPLACING the 2 deleted reject cases → net 0 here) + `test_headless_assembly_build` (3
wrapper: file grid lands-on-lattice + every slot file-backed, file grid roundtrips stable, file ring lands-on-ring) +
`test_headless_spec_build` (3 spec: file place_grid / place_ring / grid-roundtrip via the grammar; 3 can-go-red:
wrong-topology → "DIFFERENT topology", a mixed layout with one inline slot → "not file-backed", empty selection →
"selected no instances") · **"Validation gained, not just a
passthrough:** before this a file-backed part could only be placed ONE at a time by `add_part`, and a parametric layout
could only EMBED inline copies — so there was no way to stamp N references to a validated primitive on a grid/ring, and
no way to prove a layout's every slot is a genuine reference (not silently embedded copies, not just slot 0). The lattice
oracles (`assert_instances_on_grid`/`_on_ring`) never load the design, and a single `assert_part_from_file` only checks
one slot — so a builder that file-backed slot 0 and embedded the rest, or substituted a wrong path mid-layout, would pass
both. `assert_instances_from_file` closes that by loading EVERY slot and asserting it resolves to the saved primitive's
exact topology; the three can-go-red tests (inline slot / wrong topology / empty selection) prove the green can go red.
It's reusable for any future bulk file-instancing layout (radial-facing, lattice-of-primitives).**"

---

**AF-ATOM P1 — atomistic-display validation oracle + queryable route + `/validate-atomistic` skill** · _shape:_
**new `backend/core` validation module + sub-router route + CLI + skill** — `backend/core/atomistic_validation.py`
(`audit_bonds`, `audit_oxdna_job`, `latest_job_for_design`, `relaxed_frame_for_job`), route
`POST /oxdna/jobs/{id}/display-atomistic-audit` in `routes_oxdna.py` (a sub-router, not a god-file), CLI
`scripts/audit_atomistic.py` + `just audit-atomistic`, skill `.claude/skills/validate-atomistic/`; `crud.py`/
`assembly.py`/`main.js` LOC Δ = **0** · _what it validates:_ every bond + atom the oxDNA-display **atomistic** rep
draws — reconstructs with the SAME `build_atomistic_model(frame_override=…)` the renderer uses (audited bonds ARE
rendered bonds, identical serial pairs), classifies `rigid|linker|backbone|bridge`, flags rigid-stamp violations
(frame-invariant bonds ≠ template = placer bug), over-stretched bonds, renderer-hidden bonds (>1 nm), clashes,
non-finite atoms · _oracle shipped:_ `audit_bonds` + the `rigid_stamp_max_dev_nm`/`n_rigid_stamp_violations`
invariant; _tests:_ `tests/test_atomistic_validation.py` (8) — stamp-invariance under an arbitrary frame, over-
stretch+hidden/clash/non-finite detectors, class partition, job entry point, route · _real-job result_ (6hb_sim_tests
job c1299e0b07b5): stamp clean (18 279 rigid bonds, max Δ 0.0000 Å, 0 violations) but 1005 backbone O3'→P bonds at
mean 1.0 nm/max 3.16 nm (CG→atomistic backbone discontinuity, the screenshot) · full suite green, ruff clean ·
**"Validation gained, not just a passthrough:** before this nothing could say WHICH atomistic bonds are real vs
over-stretched vs renderer-hidden, nor prove the rigid-frame stamp is frame-invariant — the audit is a property of
the reconstructed geometry, not an HTTP-200. It cleanly separates a placer bug (rigid-stamp violation) from inherent
relaxation geometry (backbone stretch), which is the distinction the screenshot couldn't give. No ASK-FIRST: all
measurements are bond-length magnitudes + a template-equality check — zero frame/sign/polarity reasoning. Deferred
to AF-ATOM P2 (renderer↔audit parity) + AF-ATOM-CLOSURE (the backbone-closure fix, which is ASK-FIRST geometry).**"

---

**AF-ATOM P2 + AF-ATOM-CLOSURE — renderer↔audit parity + the backbone-closure fix** · _shape:_ **vitest parity
oracle + display-only geometry fix** (no god-file; `atomistic.py` + `atomistic_renderer.test.js`) · _P2:_
`frontend/src/scene/atomistic_renderer.test.js` (+1) decomposes each bond InstancedMesh instance matrix and asserts
the renderer hides EXACTLY the >`_MAX_BOND_NM` bonds (== the backend audit's `hidden_by_renderer`, same 1 nm cutoff)
and draws every other at its true atom distance · _CLOSURE:_ root cause measured (sequential O3'→P gaps relaxed
**median 0.91 nm** vs ideal 0.166 — systematic, oxDNA CG frames don't enforce all-atom backbone continuity);
`atomistic._close_sequential_backbone` (gated `frame_override` + `close_backbone=True`, DISPLAY-only, design/PDB/
NAMD byte-identical) re-seats only the phosphate linker between rigid C3'/C5' anchors via the validated
`_interpolate_backbone_bridge` · _oracle result (the audit IS the acceptance test):_ backbone mean 1.005→0.185 nm,
max 3.155→**0.806 nm**, **hidden-by-renderer 266→0**, rigid-stamp still 0 violations · _tests:_
`test_atomistic_validation.py::test_backbone_closure_connects_and_preserves_rigid` (closure shortens the worst
backbone stick, rigid ring/base atoms byte-identical, design path unaffected by the flag) + the previous stamp
test now uses `close_backbone=False` to isolate the pure stamp; full backend **2946 passed / 55 skipped**, frontend
**1623**, ruff clean · **"Validation gained, not just a passthrough:** P2 ties the on-screen sticks to the audited
model bond-for-bond (a renderer regression is now caught, not invisible); CLOSURE is a *fix* whose acceptance test
IS the P1 audit — it shipped only because the audit showed hidden-bonds 266→0 and backbone max 3.16→0.81 nm with the
rigid stamp still clean. ASK-FIRST was satisfied: the user authorized the geometry fix, the root cause was MEASURED
(not reasoned), and the fix reuses validated bridge geometry + moves only linker atoms (rigid invariant preserved,
oracle-checked).**"

---

**AF-ATOM P1b — inter-base geometry in the audit + base-collapse FIX (rigid placer → axis-derived)** · _what it
caught:_ P1's audit checked bond lengths + intra-residue rigidity but NOT whether nucleotides are correctly POSITIONED
relative to each other, so it was blind to the rigid-frame placer (AF first-cut) CRUSHING base pairs on real relaxed
frames (WC C1'-C1' median **0.48** vs 0.94 nm; raw oxDNA CG is a perfect duplex → a reconstruction bug) · _root
cause:_ oxDNA's relaxed a1 doesn't map onto the all-atom base direction the rigid calibration assumed — measured: on
the SAME frame the axis-derived path AND the NAMD-seed spline both give 0.94 (correct), the rigid placer 0.48 ·
_fix:_ `oxdna_health.build_display_model` (axis-derived + display-only `close_backbone`) is now the ONE builder for
the atomistic/surface display sinks AND the audit; the rigid placer (`frame_override`) is kept as an
exact-on-ideal capability, marked SUPERSEDED FOR DISPLAY · _oracle added:_ `_base_geometry` (WC + stacking C1'-C1' +
`wc_collapsed`, factored into `ok`) — the metric that would have caught it · _audit after fix:_ WC 0.48→**0.94 (OK)**,
stacking 0.47, hidden 266→4, stamp 0 violations · _tests:_ `test_base_geometry_detects_collapse` + 3 updated; backend
**2947**, frontend **1623** · **"Validation gained, not just a passthrough:** the audit now measures INTER-nucleotide
geometry, not just bond lengths — it catches the 'internally-rigid but mis-placed nucleotide' class the length checks
miss, and it was the load-bearing tool that isolated the collapse (raw-CG-correct vs reconstruction-wrong, and WHICH
path) and proved the fix. No ASK-FIRST: C1'-C1' are magnitudes; the path was chosen by MEASUREMENT (0.48 vs 0.94), not
by reasoning about a1/polarity.**"

---

**AF-12 Phase 2 — `from_primitive` (catalog-by-name, static primitives)** · _shape:_ grammar + interpreter, no new
module — `PrimitivePart` dataclass + `_PRIMITIVE_PART_KEYS` + a `_parse_part` branch in `backend/core/build_spec.py`;
`_resolve_primitive_path` + `_default_primitives_dir` + `primitives_dir` threading in
`backend/api/headless_spec_build.py`; new oracle in `tests/automation_harness.py`. `crud.py`/`assembly.py`/`main.js`
LOC Δ = **0** · _headless-coverage Δ:_ **37 → 37** (FLAT — reuses `add_file_instance`/`place_file_*`, wraps no new
route; like the AF-10 layout helpers + AF-12 follow-up, it moves the oracle count not the coverage count) · _oracle
shipped:_ `assert_part_from_primitive(assembly, instance_id, primitive_name, primitives_dir)` — independently
re-resolves the catalog NAME → its `.nadoc` via `primitive_catalog.design_path`, loads it, and delegates to
`assert_part_from_file`; the new load-bearing piece over `from_file` is the name→catalog-path RESOLVER · _tests:_ 6 new
in `test_headless_spec_build.py` (augment: name resolves to catalog topology; 2 can-go-red on the oracle — wrong name →
"DIFFERENT topology", unknown name → "catalog has no primitive"; unknown name fails the BUILD → `BuildSpecError`;
`.nass` round-trip stable; `place_grid` layout resolves all slots via `assert_instances_from_file`); full suite **3008
passed / 55 skipped**, no drop · _cohesion:_ the resolver has ONE reason to change — how a catalog name maps to a saved
`.nadoc` path. NO ASK-FIRST needed at build time (the user made the one architecture call up front: static beams only,
reuse `from_file`; resolution is pure name→path, no topology/directionality reasoning) ·
**"Validation gained, not just a passthrough:** before this, an assembly spec could only reference a saved part by raw
PATH (`from_file`) — there was no way to reference a curated catalog primitive **by the name the UI shows**, and nothing
proved a name resolves to the *right* primitive. `assert_part_from_primitive` closes that by independently re-resolving
the name through the catalog and proving the placed instance is that exact primitive's validated topology (so a resolver
that mapped `6hb_primitive` to the wrong/renamed `.nadoc` fails) — a mapping `canonical_assembly` is blind to (it keys a
file source by path only and never loads the design, and certainly never re-checks the name). It's the text-to-design
rung: a natural-language 'place a 6hb beam' lowers to `{"from_primitive": "6hb_primitive"}` and is pinned to resolve
correctly.**"

**AF-12 Phase 2b — `from_primitive` for the PARAMETRIC circle disc (generative, by-name + params)** · _shape:_ grammar
+ interpreter, no new module — `PrimitivePart.params` field + `_PRIMITIVE_PART_KEYS += {"params"}` + a `_parse_part`
params branch in `backend/core/build_spec.py`; `_resolve_primitive_part` + `_build_circle_primitive` in
`backend/api/headless_spec_build.py` (the static branch reuses the AF-12 P2 `_resolve_primitive_path`); new oracle in
`tests/automation_harness.py`. `crud.py`/`assembly.py`/`main.js` LOC Δ = **0** · _headless-coverage Δ:_ **37 → 37**
(FLAT — the parametric disc is built by lowering to a single `circle_segment` op through `build_design`, both already
covered; wraps no new route) · _oracle shipped:_ `assert_part_is_circular_disc(assembly, instance_id,
requested_radius_nm)` — the parametric counterpart to `assert_part_from_primitive`: asserts the instance is INLINE-backed
(a parametric primitive that resolved to a *file* would be the wrong path — the saved default-radius disc, not the
requested one), loads the embedded design, and delegates to the AF-4 `assert_circular_disc` geometric oracle (placed
helices trace a circle of the requested radius). **ASK-FIRST honoured** (the user made both calls up front: generic
`params` dict grammar `{"from_primitive":"<circle>","params":{"radius_nm":R}}`; `radius_nm` REQUIRED for a circle kind —
no silent catalog-default fallback). Radius is a magnitude — no topology/directionality reasoning entered · _tests:_ 11
new (6 parser cases in `test_build_spec.py`: static `from_primitive` parses to empty-params `PrimitivePart`; parametric
parses its params; a 4-case reject parametrize — empty name / non-object params / non-number param value / extra key; 7
build in `test_headless_spec_build.py`: augment green — radius 14 disc built+circular; radius is the knob NOT the default — 10 nm
catalog default instanced at 20 nm yields a 20 nm disc; 2 can-go-red — wrong radius 30 → circularity/radius fail,
file-backed instance → inline guard; `radius_nm` omitted → build raises "requires a 'radius_nm' param"; params on a
static primitive → "takes no params"; inline disc `.nass` round-trip stable); full suite **3041 → 3054 passed / 55
skipped** (+13: 6 parser cases incl. the 4-case reject parametrize + 7 build), no drop · _cohesion:_
`_resolve_primitive_part` has ONE reason to change — how a catalog `primitive_kind`
maps to (static-file-reference | generative-inline-build) ·
**"Validation gained, not just a passthrough:** before this, a `from_primitive` part could ONLY be a static file
reference at the primitive's saved geometry — there was no way to instance a *parametric* catalog primitive at a
spec-chosen size, and nothing proved a generatively-built part lands the requested geometry. `assert_part_is_circular_disc`
closes that by loading the design the assembly instance embeds and proving (via the AF-4 circularity oracle) the placed
helices trace a circle of the **requested** radius — pinning the `params.radius_nm → footprint → circle_segment → placed
geometry` path *through the assembly layer*, which `canonical_assembly` (keys an inline source by its embedded topology
fingerprint, blind to whether that geometry is circular *of radius R*) cannot see. The inline guard additionally proves
the driver took the generative branch, not the wrong file-reference path. It's the parametric text-to-design rung: 'place
a 12 nm disc' lowers to `{"from_primitive":"small_circle","params":{"radius_nm":12}}` and is pinned to build the right
disc.**"

**AF-18 — full-pipeline anchored field-specimen builder (Tier 6, first loop)** · _shape:_ 1 composite wrapper
`build_field_specimen` in `backend/api/headless_oxdna_build.py` (composes the ALREADY-COVERED wrappers
`hs.build_design` / `hb.overhang_extrude` / `hb.full_sequence` / `run_relaxation` + `resolve_anchor_particles` — runs
the design ops in `hb.scratch_session`, resolves the anchor on the final design, relaxes) + 1 composite oracle
`assert_field_ready_specimen` in `tests/automation_harness.py`. `crud.py`/`assembly.py`/`main.js` LOC Δ = **0** ·
_headless-coverage Δ:_ **37 → 37** (FLAT — pure COMPOSITION of covered wrappers, wraps no new route; the value is the
chain + the composite oracle, not a new route) · _oracle shipped:_ `assert_field_ready_specimen(result, design, ws)` —
composes three independently-proven properties into one "ready to run a field experiment" verdict: (1) fully sequenced
(`assert_fully_sequenced`), (2) relaxed geometry recovered (`assert_relaxed_geometry_recovered`), (3) anchorable — the
anchor resolved to real nucleotides AND a SHORT PROBE field child (branched off the relaxed parent) holds the anchored
beads while the free part deflects ALONG the field (`measure_field_response`, `passed`) · _tests:_ 6 new in
`test_headless_oxdna_build.py` (full oracle green on the dense 6hb fixture; sequence=True branch genuinely sequences a
stripped routed design; build-spec dict branch dispatches via `build_design`→same `canonical_topology`; unresolvable
anchor raises at build; **2 can-go-red** — clause-1 fires on an unsequenced design, clause-3 fires on an empty anchor
list); full suite **3014 passed / 55 skipped**, no drop · _cohesion:_ ONE reason to change — the build→field-ready
sequence of steps. **ASK-FIRST honoured:** which nucleotides are the overhang/anchor is a caller-supplied spec input
(`overhang`/`anchor` descriptors), never inferred geometrically; the probe oracle measures magnitudes/projection only
(direction-agnostic) · **"Validation gained, not just a passthrough:** before AF-18 each piece — sequence, relax, anchor
resolution, field response — was pinned ALONE, but nothing proved they **compose** into a single runnable, anchorable
specimen (the user's "build → … → set as anchor → run a field" chain). `assert_field_ready_specimen` closes that by
running the WHOLE chain end-to-end and proving a probe field actually holds the designated anchor while the body
deflects — so a builder that produced an unsequenced, unrelaxed, or un-anchorable specimen fails the matching clause.
It is the Tier-6 specimen spine AF-19 (equilibration τ) / AF-20 (field sweep) / AF-23 (campaign) build their field
experiments on.**"

---

**AF-19 — field equilibration-timeline τ + non-melt oracle (Tier 6, time-resolved)** · _shape:_ 1 PURE measure
`measure_field_equilibration` in `backend/core/oxdna_health.py` + 1 oracle `assert_equilibration_timeline` in
`tests/automation_harness.py` + 1 new test mock (`_FIELD_TRAJ_MOCK_OXDNA`/`mock_oxdna_field_traj`, a field binary that
emits a multi-frame `trajectory.dat` with a saturating alignment ramp). `crud.py`/`assembly.py`/`main.js` LOC Δ = **0**;
`backend/core` imports nothing from `backend/api` (the measure takes the already-read trajectory frames + the design) ·
_headless-coverage Δ:_ **37 → 37** (FLAT — reads the field `trajectory.dat` the ALREADY-SHIPPED field child-job writes;
wraps no new route) · _oracle shipped:_ `measure_field_equilibration(frames, field_dir, anchor_keys, *, design,
steps_per_frame, melt_floor, …)` — per-frame free-body alignment projection (the `measure_field_response` projection vs
frame 0) + per-frame `base_pair_retention`; fits the monotone approach to a plateau (tail mean) and extracts τ = time to
`1−1/e` of plateau; `converged` = non-vacuous rise + monotone-within-noise + actual plateau (late slope ≤ 0.3·early
slope); `melted` = bp below floor at ANY frame. `assert_equilibration_timeline(job, ws, field_dir, anchor_keys, *,
design, melt_floor=0.5, min_confidence=10)` locates the field stage's trajectory, confidence-gates frame count, asserts
converged + finite positive τ + not melted · _tests:_ 6 new in `test_headless_oxdna_build.py` (end-to-end relax→field→
oracle finds finite τ + no melt on the deflecting trajectory mock; confidence-gate fires on a 10-frame run at
`min_confidence=15`; **3 pure-measure pins on hand-built frames** — saturating ramp converges with τ≈k, LINEAR ramp →
`converged=False`/`tau=None` (never-plateau can-go-red), bp yanked apart mid-swing → `melted=True` (transient-melt
can-go-red); <2-frames raises) · full suite **3020 passed / 55 skipped**, no drop · _cohesion:_ ONE reason to change —
how a field trajectory's equilibration timeline is measured. **ASK-FIRST honoured:** field direction is a caller input;
the measure reports projection MAGNITUDES along it (direction-agnostic, no sign/handedness reasoning) · **"Validation
gained, not just a passthrough:** before AF-19 `measure_field_response` proved only the ENDPOINT (the final field pose vs
the field-off reference) — it was blind to *how long* equilibration took and to any *transient* base-pair melt during the
swing. `measure_field_equilibration` closes both gaps by reading the whole field trajectory: it extracts a finite τ (and
refuses one for a run that never plateaus) and watches bp retention at EVERY frame (catching a structure that aligns by
ripping apart and re-forming) — neither of which the endpoint oracle can see. The two can-go-red pure tests prove the
green can go red on a non-converging run and on a transient melt. It is the per-`(|E|,direction)`-cell measure the AF-20
sweep + AF-23 campaign assemble into a field↔τ response surface.**"

**AF-20 — field sweep driver + (|E|,direction)→response surface + field↔τ correlation oracle (Tier 6, multi-config)** ·
_shape:_ 1 orchestration wrapper `hox.sweep_field_response` (+ a private `_measure_field_cell` reducer) in
`backend/api/headless_oxdna_build.py` + 1 oracle `assert_field_sweep_map` in `tests/automation_harness.py` + 1 new test
mock (`_FIELD_SWEEP_MOCK_OXDNA`/`mock_oxdna_field_sweep`, a field binary whose time constant DECREASES with |E| and which
melts above a threshold). `crud.py`/`assembly.py`/`main.js` LOC Δ = **0**; the wrapper reuses the shipped `append_field`
child-job spawn + the AF-19 `measure_field_equilibration` (no logic re-implemented) · _headless-coverage Δ:_ **37 → 37**
(FLAT — branches child field jobs via the already-covered `append_field`; wraps no new route) · _oracle shipped:_
`assert_field_sweep_map(sweep, *, benign_range, destructive_range, melt_floor=0.5, tau_tol_steps=1e-6,
min_tau_drop_steps=1.0)` — four clauses over a `(pN,dir)→cell` map: (1) no skipped cells + every grid cell present (no
silent truncation); (2) a non-destructive operating window in `benign_range`, **recomputed from the raw measured
`aligned`/`bp_min`** not the wrapper's stored flag (anti-echo); (3) `destructive_range` covers ≥1 cell and ALL of them
melted (a real upper bound, non-vacuity-guarded); (4) **τ non-increasing AND actually falls with |E|** in each direction's
responsive band (≥2 cells — the field↔equilibration correlation) · _tests:_ 4 new in `test_headless_oxdna_build.py`
(end-to-end build→sweep 5 |E|×2 dir → complete map, safe window, 32 pN melts / 2 pN holds, τ strictly decreasing; **3
can-go-red**: flat τ on a HAND-BUILT equal-τ map with one melted cell, a destructive range over un-melted cells →
"window not bounded above", a dropped grid cell → "no verdict for cell"). The specimen is the CORRECT experimental setup —
anchored on a REAL extruded ssDNA overhang (the whole 12-nt overhang domain pinned via `conftest.extrude_valid_overhang`
→ the `overhang_candidate_error` geometry oracle), NOT a regular bundle domain tagged as an overhang; overhang bases are a
fixed-seed random splice (the multi-scaffold 6hb is sequenced by `_sequence_for_oxdna`, not `full_sequence`) · targeted files **290 passed**
(`test_headless_oxdna_build` + `test_automation_harness` + `test_oxdna_relaxation`); full suite not run this session (user
declined the long run); net **+4 tests (suite 3020→3024)** · _cohesion:_ ONE reason to change — how a single specimen's
field response surface is swept + reduced to per-cell verdicts. **ASK-FIRST honoured:** intensities + directions are caller
inputs; cells measure magnitudes (τ, alignment projection, bp retention) · **"Validation gained, not just a passthrough:**
before AF-20 every physical oracle (AF-13/18/19) measured ONE structure at ONE condition. `assert_field_sweep_map` is the
first MULTI-config physical oracle: it proves a *response surface* — that the specimen has a bounded non-destructive
operating window (aligns without melting below a field, melts above it) AND that its equilibration time τ correlates with
field strength (stronger field → faster equilibration), the exact `(|E|,direction)↔τ` map the user wants. Nothing before
asserted a property ACROSS conditions; the τ-monotonicity + bounded-window clauses can only be tested on a swept grid. The
three can-go-red tests prove the green goes red on a flat (field-independent) τ, an unbounded destructive window, and a
gap in the grid. It is the per-design sweep the AF-23 cross-design campaign runs on each specimen.**"

**AF-23 — CAPSTONE: cross-design automated field-response campaign (Tier 6, multi-design study)** · _shape:_ 1 wrapper
`run_field_campaign` in `backend/api/headless_oxdna_build.py` (composes the de-risked AF-18 `build_field_specimen` +
AF-20 `sweep_field_response` per design, each in its own `ws/campaign/<i>_<name>` subdir; wraps NO new route) + 1 reusable
oracle `assert_field_campaign` (+ helper `_campaign_tau_signature`) in `tests/automation_harness.py`;
`crud.py`/`assembly.py`/`main.js` LOC Δ = **0** · _headless-coverage Δ:_ **FLAT 37** (campaign is pure composition of two
already-covered wrappers — no route flips) · _oracle shipped:_ `assert_field_campaign(campaign, *, benign_range,
destructive_range, expect_distinguishable=True, melt_floor=0.5, min_tau_separation_steps=1.0, repro=None, tau_tol_steps=1e-6,
min_tau_drop_steps=1.0)` — the FIRST multi-DESIGN physical oracle: (1) no dropped design (skipped empty + sweeps non-empty),
(2) every design passes `assert_field_sweep_map` (a reported non-destructive window per design), (3) **DISTINGUISHABILITY** —
≥2 designs differ at a shared responsive `(|E|,dir)` cell by ≥`min_tau_separation_steps` τ, recomputed from raw
`aligned ∧ bp_min ≥ melt_floor` (anti-echo), (4) **reproducible** — `repro` 2nd run reproduces every shared design+cell τ
within `tau_tol_steps`. Direction-agnostic; Three-Layer-clean · _tests:_ 4 new in `test_headless_oxdna_build.py`
(6hb-vs-18hb distinguishes + 18hb faster at 2 pN; reproducible re-run; **two load-bearing red-tests**: two identical 6hb →
"INDISTINGUISHABLE", an unresolvable anchor → recorded in `skipped` → "skipped" fires) + a NEW design-dependent campaign mock
(`_FIELD_CAMPAIGN_MOCK_OXDNA`/`mock_oxdna_field_campaign`: `k = clamp((4.5−12·F0)·(540/N))` → τ scales with particle count N,
melt threshold design-independent); full suite **3028 passed / 55 skipped** (3024→3028), no drop · **"Validation gained, not
just a passthrough:** before AF-23 every physical oracle (AF-13/18/19/20) measured ONE structure — AF-20 at many conditions,
but still one design. `assert_field_campaign` is the first oracle that proves the campaign produces design-DISCRIMINATING
response surfaces: it runs the SAME `(|E|,direction)` sweep across multiple designs and asserts ≥2 are distinguishable by
their measured equilibration timescale (a bigger/longer-lever 18hb equilibrates faster than a 6hb at the same field) AND that
the study reproduces exactly. Nothing before asserted a property ACROSS designs — the distinguishability + reproducibility
clauses can only be tested on a multi-design campaign, and the AF-20 sweep mock's design-independent τ literally cannot
exercise them (it took a new N-dependent mock). The two red-tests prove the green goes red on indistinguishable designs and a
dropped design. This is the capstone the user asked for: 'automatic exploration of E-field intensities and directions that
correlate with DNA alignment equilibration timelines, without ripping it apart, for various designs.'**"

**AF-21 — oxpy persistent interactive engine + equilibrium-parity / live-mutation oracle** · _shape:_ NEW module
`backend/physics/oxdna_live.py` (`LiveOxdnaSession` + `_OxpyStepper`, lazy `import oxpy`, injectable stepper seam) + pure
`field_equilibrium_observables`/`field_equilibrium_from_confs` in `backend/core/oxdna_health.py` + `run_live_field` /
`_prepare_field_rundir` in `backend/api/headless_oxdna_build.py`; `crud.py`/`assembly.py`/`main.js` LOC Δ = **0** ·
_headless-coverage Δ:_ **FLAT 37** (`run_live_field` wraps NO route — pure composition + a second engine path) · _oracle
shipped:_ `assert_oxpy_equilibrium_parity(live_result, batch_result, *, tol_nm=0.5, bp_tol=0.05, min_confidence=2,
require_mutation=True)` — confidence gate + live≈batch equilibrium (alignment + R_g within `tol_nm`, bp within `bp_tol`) +
the live field re-aim steered the body (`mutation.followed`) · _ENGINE/BINDING work:_ the chosen `subscribe("end_of_step")`
mechanism was EMPIRICALLY REFUTED (oxDNA's MD backend fires no per-step event → callback never runs → a +z field gave −z
thermal drift) and stock oxpy exposed no live knob for a `string`/`ConstantRateForce` field's magnitude/direction; FIX
(user-approved) added two `def_readwrite("F0"/"dir", &BaseForce::_F0/_direction)` lines in
`~/oxDNA/src/oxpy/bindings_includes/Forces/BaseForce.h` + `make` (editable install auto-picks-up `core.so`) → per-burst
`force.F0`/`force.dir` is an exact re-aimable uniform field, validated live (real oxpy: +z field → +z drift; re-aim →
follows) · _tests:_ 6 new — 4 GPU-free oracle unit tests in `test_automation_harness.py` (pass + 3 red: divergence /
dead-field / low-confidence) + 1 GPU-free pipeline parity (`_MockFieldStepper` mirrors `_FIELD_MOCK_OXDNA`; live re-aim
`+z→+x` vs batch directly `+x` → same final equilibrium + `followed`) + 1 **gated real-oxpy** live-steer
(`pytest.importorskip("oxpy")` + `find_oxdna()`; it RAN here — real relaxation + real field re-aim steered the 6hb) in
`test_headless_oxdna_build.py`; full suite **3034 passed / 55 skipped** (3028→3034), no drop · **"Validation gained, not just
a passthrough:** before AF-21 every physical oracle drove the batch CLI binary one-shot — there was no interactive engine and
no way to trust that a 'real-time' burst-stepped run reaches the SAME physics, nor that live field control actually steers a
structure. `assert_oxpy_equilibrium_parity` proves both: the persistent oxpy session's equilibrium (alignment + R_g + bp)
matches the validated batch engine's within tolerance (engine-equivalence — equilibrium-property parity, the honest claim
under a stochastic thermostat), AND a mid-run field re-aim genuinely moves the free body toward the new vector
(`mutation.followed`, the substance behind 'drag the field and it follows'). The parity clause is provable GPU-free (a mock
stepper mirrors the binary's position-based deflection, so the burst-vs-one-shot claim holds without the engine); the
live-mutation clause runs on the real oxpy build the loop just patched. Three red-tests prove the green can go red. This is
the interactive ENGINE the AF-22 live-steering timeline builds directly on.**"

**AF-22 — multi-waypoint live field steering + field-following oracle (Tier 6, interactive control loop)** · _shape:_ 1
function `steer_field_session` in `backend/api/headless_oxdna_build.py` (pure composition over the AF-21 `LiveOxdnaSession`:
`set_field`/`run`/`equilibrium_observables` in a waypoint loop) + 1 reusable oracle `assert_live_field_following` in
`tests/automation_harness.py`; `crud.py`/`assembly.py`/`main.js` LOC Δ = **0** · _headless-coverage Δ:_ **FLAT 37**
(`steer_field_session` wraps NO route — pure composition over the shipped session) · _oracle shipped:_
`assert_live_field_following(timeline, *, melt_floor=0.5, min_following_nm=0.5)` — (1) non-vacuity (≥2 waypoints + ≥1
substantial follow-move), (2) field-following (EVERY waypoint's deflection along its OWN leg vector rose,
`proj_after>proj_before`), (3) no melt (bp_retention ≥ melt_floor at EVERY waypoint); over the `steer_field_session`
timeline (`{timeline:[{field_dir, proj_before_nm, proj_after_nm, alignment_nm, bp_retention, radius_of_gyration_nm,
followed}, …], n_waypoints}`) · _ASK-FIRST:_ none needed — field dirs/|E| are inputs, the oracle measures signed
projections along each leg's own vector (direction-agnostic, no handedness/frame reasoning) · _tests:_ 7 new in
`test_headless_oxdna_build.py` — 2 GPU-free pipeline over `_MockFieldStepper` (3 orthogonal waypoints all follow without
melt; per-leg `field_pN` magnitude honoured: 8 pN leg deflects >2× the 2 pN leg) + 4 hand-built red-path (ignored-waypoint
"did NOT follow" / melt "MELTED" / stationary "vacuous" / single-waypoint "needs >= 2 waypoints") + 1 empty-waypoints
ValueError; full suite **3041 passed / 55 skipped** (3034→3041), no drop · **"Validation gained, not just a passthrough:**
before AF-22 the interactive engine was proven for a SINGLE field re-aim (AF-21's `mutation.followed`), but nothing proved
the interactive control LOOP — a *path* of many field changes, the substance behind dragging the gizmo through a sequence —
produces sustained field-following without the structure melting somewhere along the way. `assert_live_field_following`
closes that: it walks the whole steered timeline and asserts the body chased EVERY re-aim (each leg's along-vector
projection rose) AND held together at EVERY waypoint (bp ≥ melt_floor), with a non-vacuity guard so a stationary timeline
can't pass and four red-tests proving each clause goes red. It's the headless, automatable form of the user's 'play with
the field in real time' goal — and the per-step-response pattern is reusable for any interactive control sequence (steered
salt/temperature ramps, gizmo-driven deformation paths). This COMPLETES Tier 6.**"

**AF-24 — real-engine Tier-6 equilibration-τ validation (the relaxation-step-count FIX)** · _shape:_ NO new wrapper
— a `STANDARD_RELAX_PARAMS` preset + corrected docstrings in `backend/api/headless_oxdna_build.py`, a corrected
`write_mutual_traps` docstring in `backend/physics/oxdna_interface.py`, a `tests/fixtures/test343.nadoc` fixture, and
a gated real-engine test; `crud.py`/`assembly.py`/`main.js` LOC Δ = **0** · _headless-coverage Δ:_ **FLAT 37** (no
route wrapped) · _oracle shipped:_ reuse `assert_equilibration_timeline` UNCHANGED, now driven on the REAL engine —
the augment is the gated test `test_field_specimen_reanneals_and_equilibrates_real_engine` (opt-in
`NADOC_RUN_OXDNA_SLOW=1`, `@pytest.mark.slow`): build `test343` with `**STANDARD_RELAX_PARAMS` → assert re-anneal
(retention ≥ 0.9) → anchored field (pN=2, 20k steps) → converged + finite τ + not melted. **PASSED on real CUDA,
~250 s** (run twice green) · _tests:_ +1 gated real test (skips in the default suite → +1 skip); clean full suite
**3054 passed / 56 skipped / 0 failed** (a first run had a cross-file flake `test_iterate_oracle_fires_on_vacuous_
convergence` while a GPU re-verify ran concurrently — green in isolation, in-file, and on a clean re-run; my changes
are inert w.r.t. it — an import + a constant + docstrings) · **"Validation gained, not just a passthrough:** the Tier-6 physical claims (the duplex
RE-ANNEALS, then an anchored field aligns it to a stable τ WITHOUT melting — τ_align < τ_melt) are now ENGINE-confirmed
on real oxDNA, retiring the mock-only caveat for the τ path; and the ROOT CAUSE is fixed — the AF Tier-6 builders had
silently inherited mock-tuned relaxation defaults (mc=100/md=100/equil=100, 10⁴× too few md_relax steps) so the duplex
never re-annealed; `STANDARD_RELAX_PARAMS` (md≈1e6) re-anneals a real specimen to 42/42 by oxDNA's own HBList ground
truth. The `base_pair_retention` metric and the geometry export were both EXONERATED (export is 42/42 at t=0).**"

---

**AF-27 P1 — `hb.connect_overhangs` overhang-linker tie** · _shape:_ wrapper in `backend/api/headless_build.py`
(imports `create_overhang_connection` + `OverhangConnectionCreateRequest`; no god-file growth — `crud.py`/
`assembly.py`/`main.js` LOC Δ = **0**) · _headless-coverage Δ:_ **41 → 42** (`create_overhang_connection` flips by
function identity) · _oracle shipped:_ `assert_linker_connects(design, conn_id, *, overhang_a, overhang_b,
bridge_bp=None)` — connection exists + joins the two overhangs (order-independent set) + bridge bp == expected
(route's own `_length_value_to_bp` lowering, so nm pins through B-DNA rise), re-checked after `roundtrip_nadoc` ·
_tests:_ 3 in `test_headless_build.py` (ds tie + nm-length lowering + invalid-polarity 400 rejection) + 4 in
`test_automation_harness.py` (1 green + 3 can-go-red: no connection / wrong partner / wrong bridge_bp); 3 coverage-
count meta-tests bumped 41→42; full suite **3189 passed / 60 skipped** (was 3186+3 count-mismatch failures, all the
expected +1 coverage bump) · **"Validation gained, not just a passthrough:** before AF-27 a script could extrude an
overhang on each of two leaves but had NO way to tie them with a length-defined linker — the very tie whose contour
length confines a hinge angle. The wrapper closes that gap AND its oracle proves the tie wires the right two
overhangs at the right bridge length AND *persists across a `.nadoc` round-trip* — a property `canonical_topology`
literally cannot see (it does not fingerprint `overhang_connections`), so a build that dropped or rewired the linker
while keeping its strands would have slipped past every prior structure check. This is the hinge-confinement
keystone: AF-28's angle-confined hinges build on a tie this oracle certifies correct.**"

---

**AF-29 — hinge ssDNA flexible-segment relax (headless + JS↔Python parity)** · _shape:_ NEW pure core
`backend/core/flexible_relax.py` (`relax_cluster_pose` solver + `compute_relax_transforms` orchestration; imports
only `_geometry_for_design` + models + scipy — `backend/core` imports nothing from `backend/api`) + `hb.relax_flexible_
segments` wrapper (commits via the real `flexible_relax` route) + NEW pure JS module `frontend/src/scene/flexible_relax_
solver.js`. No god-file growth (`crud.py`/`assembly.py`/`main.js` LOC Δ = **0**; `cluster_gizmo.js` UNTOUCHED) ·
_headless-coverage Δ:_ **42 → 43** (`flexible_relax` route flips by function identity) · _oracles shipped:_ (1)
`assert_flexible_segments_relaxed` (contour-constraint on posed geometry + pose-moved guard + `canonical_topology`
three-layer pin) — the solver-independent correctness pin; (2) JS↔Python parity (`relax_cluster_pose` ↔
`flexible_relax_solver.js` golden, pos+rotation to 1e-6) · _tests:_ 4 in `test_flexible_relax.py` (solver + parity +
pivot + no-op) + 2 in `test_headless_build.py` (taut-pull + no-op-no-entry) + 4 oracle red-tests in
`test_automation_harness.py` + 3 vitest in `flexible_relax_solver.test.js`; 3 coverage-count meta-tests bumped 42→43 ·
**"Validation gained, not just a passthrough:** before AF-29 the hinge ssDNA rest-pose minimisation was JS-ONLY (the PBD
solver lived in `cluster_gizmo.js`; the backend route only *applied* pre-computed transforms) — a headless script or AI
pipeline could not COMPUTE a relax, so automated hinge-angle testing was blocked. AF-29 ports the exact solver to Python
(parity-pinned to the in-app JS, so headless == app) AND its oracle proves the *result* satisfies the contour-length
constraint (every tether taut, not just 'the route returned') WHILE asserting topology is untouched (the Three-Layer Law
made into a pin). This is the hinge rest-pose keystone — the ssDNA-scaffold counterpart to AF-27's linker tie: together
they confine a hinge's angle, the prerequisite for AF-28's automated hinge-angle exploration.**"

---

**AF-31 — manual crossover PLACE + DELETE wrappers** · _shape:_ 2 wrappers in `backend/api/headless_build.py`
(`place_crossover` imports the route handler `place_crossover`; `delete_crossover` imports `delete_crossover` —
covered by function identity, NOT re-implemented) + 1 reusable oracle `assert_crossover_joins` in
`tests/automation_harness.py`; `crud.py`/`assembly.py`/`main.js` LOC Δ = **0** · _headless-coverage Δ:_
**43 → 45 / 239** (`place_crossover` + `delete_crossover` flip to covered) · _oracle shipped:_
`assert_crossover_joins(design, xover_id, *, half_a, half_b, expect_ligated=True)` — the record exists + joins
the two named half-sites (order-independent) + **the ligated outcome actually merged the backbone** (a single
strand spans both half-sites — load-bearing via `_strand_spans_both`, which catches a "record appended but
ligate silently failed" build that the same-strand `unligated_crossover_ids` set would NOT) + `validate_design`
gate (ligated only); the `expect_ligated=False` branch accepts the documented recorded-but-unligated
(cycle-avoidance) outcome and skips the validate gate (the validator flags the terminus-on-crossover state by
design). PLUS the AF-2 `assert_inverse_pair` REUSED as **delete→place** (NB not place→place: place introduces
nicks a desplice does not undo, so the inverse runs from a design that already carries the crossover) ·
_tests:_ 2 in `test_headless_build.py` (ligated join + delete→place inverse) + 5 in `test_automation_harness.py`
(ligated pass, unligated-branch pass + red, missing-id red, wrong-half-site red, AF-31 coverage) + the
coverage-count meta-test bumped 43→45 · **"Validation gained, not just a passthrough:** before AF-31 a script
could bulk-route (`auto_crossover`) but could not place a SINGLE named crossover, and nothing pinned that a
manual placement actually crossed the backbone — `assert_crossover_joins` proves the place merged the two
fragments at the named sites (not merely appended a record), distinguishes the ligated from the deliberate
cycle-avoidance-unligated outcome the route can produce, and the reused inverse-pair proves delete is the exact
desplice inverse of place. The manual counterpart to AF-2's nick/ligate, completing the fine-routing wrapper
set.**"

---

**AF-32 — forced-ligation `force_ligate` + delete inverse (the AF-33 hinge prereq)** · _shape:_ 2 wrappers in
`backend/api/headless_build.py` (`force_ligate` imports the route handler `forced_ligation`;
`delete_forced_ligation` imports `delete_forced_ligation` — covered by function identity, NOT re-implemented;
documented as the **scripted-manual** entry, NOT an autorouting hook, per the route's manual-only contract) + 1
reusable oracle `assert_forced_ligation` in `tests/automation_harness.py`; `crud.py`/`assembly.py`/`main.js` LOC
Δ = **0** · _headless-coverage Δ:_ **45 → 47 / 239** (`forced_ligation` + `delete_forced_ligation` flip to
covered) · _oracle shipped:_ `assert_forced_ligation(before, after, fl_id, *, three_prime_strand_id,
five_prime_strand_id)` — the `ForcedLigation` record exists carrying the right 3'/5' endpoints (re-derived from
`before`'s strands exactly as the route does: 3' = last domain of the 3' strand, 5' = first domain of the 5'
strand → catches a swap or wrong helix/bp) + **the two strands merged into one** (strand count −1 AND a single
strand spans both endpoints via the AF-31 `_strand_spans_both` — the backbone-merge pin, not just a record
appended) + **the record survives a `.nadoc` round-trip** (the load-bearing pin: the FL record lives on
`design.forced_ligations`, OFF the strand graph, so `canonical_topology` is blind to it — only re-reading after
export→import proves persistence; same blind-spot as clusters / overhang-connections). PLUS the AF-2
`assert_inverse_pair` REUSED as **force-ligate→delete** (a CLEAN forward/inverse here — unlike AF-31's crossover
place, forced ligation introduces NO nicks, so ligate→delete splits straight back to `canonical_topology`) ·
_tests:_ 2 in `test_headless_build.py` (merge+record+round-trip via the oracle; ligate→delete inverse) + 5 in
`test_automation_harness.py` (oracle pass, missing-record red, swapped-endpoints red, not-merged/clause-3 red,
AF-32 coverage) + the coverage-count meta-test bumped 45→47 · **"Validation gained, not just a passthrough:**
before AF-32 a script could not replay a manual forced ligation at all, and nothing pinned that one wired the
named 3'/5' endpoints, actually merged the backbone, OR that its off-strand-graph record persists across save/load
(the canonical-topology blind-spot). `assert_forced_ligation` proves all three, and the reused inverse-pair proves
delete is the exact split-back inverse. This is the **AF-33 prerequisite** — the hinge builder places 2N cross-gap
FL links, each now driveable + pinnable.**"

---

**AF-30 — strand end-resize `resize_strand_end` (the last Tier-1 fine-routing wrapper)** · _shape:_ 1 wrapper in
`backend/api/headless_build.py` (`resize_strand_end` imports the route handler `strand_end_resize` +
`StrandEndResizeRequest`/`StrandEndResizeEntry` — covered by function identity, NOT re-implemented; a single-entry
mechanical pass-through, the caller supplies the explicit end + signed delta) + **NO new oracle** (two proven ones
REUSED); `crud.py`/`assembly.py`/`main.js` LOC Δ = **0** · _headless-coverage Δ:_ **47 → 48 / 239**
(`strand_end_resize` flips to covered) · _oracles reused:_ (1) `assert_geometric_length_delta` (AF-3) — the
load-bearing pin: a `+δ` resize of a scaffold whose terminal domain DEFINES its helix extent grows that helix's
emitted geometry by exactly `δ` bp (one nuc/strand → `δ×2`); catches a silent clamp / no-op / wrong-helix / dropped
inline-overhang split. (2) `assert_inverse_pair` (AF-2) — `+δ` then `−δ` at the same end restores
`canonical_topology` (forward-must-mutate guard intact), proving `−δ` exactly undoes `+δ` on the strand bp-range ·
_finding:_ **ISSUE-13** — `resize_strand_ends`' axis re-trim uses `(max_index−min_index)·rise` while `create_bundle`
uses `length_bp·rise` (one rise longer), so the FIRST resize off a raw bundle shifts the helix `axis_end` convention
and `canonical_topology` (fingerprints axis floats) never restores; the inverse-pair test captures `start` AFTER one
settling resize so both ±δ runs share the re-trim convention. The resize DOES change the nucleotide count (that is
the property `assert_geometric_length_delta` pins); only the ISSUE-13 *axis-endpoint* off-by-one leaves the count
untouched (it shifts the axis-line endpoint float, not `length_bp`), so the geometric oracle stays clean while the
inverse pair breaks · _tests:_ 3 in `test_headless_build.py` (geometry length-delta; +δ/−δ inverse from
a settled start; coverage flip) + 1 coverage meta-test in `test_automation_harness.py`; coverage-count assertions
bumped 47→48 across 3 files (`test_automation_harness`, `test_cluster_obb`, `test_headless_spec_build`); full suite
**3231 passed / 61 skipped** · **"Validation gained, not just a passthrough:** before AF-30 a script could not drive
the cadnano drag-arrow resize and nothing pinned that a resize moves exactly the requested bp of geometry on exactly
the named helix, nor that a `−δ` is the exact inverse of a `+δ`. The length-delta count proves the first; the inverse
pair proves the second — and the discrepancy that blocked the naive inverse pair surfaced a real latent geometry-
convention bug (ISSUE-13) that nothing else exercised. Tier-1 fine-routing set is now COMPLETE.**"

---

**AF-33 P1 — headless hinge-primitive BUILDER `build_hinge_primitive` (2x2_single) + golden-equality oracle** ·
_shape:_ NEW focused module `backend/api/headless_hinge_build.py` (`build_hinge_primitive` — composes the shipped
`hb.create_bundle` + `hb.resize_strand_end` (AF-30) + `hb.force_ligate` (AF-32) wrappers; introduces NO new route,
re-implements nothing) + 1 reusable oracle `assert_matches_primitive` (+ helper `_fl_endpoint_set`) in
`tests/automation_harness.py`; `crud.py`/`assembly.py`/`main.js`/`headless_build.py` LOC Δ = **0** · _headless-coverage
Δ:_ **48 → 48 / 239** (FLAT — the builder drives only already-covered routes; the deliverable is the oracle, as the
spec predicted) · _oracle shipped:_ `assert_matches_primitive(design, primitive_name, *, primitives_dir)` — the
GOLDEN-EQUALITY pin: loads `workspace/Primitives/<name>.nadoc` (resolved via `primitive_catalog.design_path`) and
asserts `canonical_topology` == golden AND **`_fl_endpoint_set` == golden** (LOAD-BEARING — `canonical_topology` is
blind to `forced_ligations`, the 5th instance of that off-strand-graph blind-spot after clusters/loop-skips/
overhang-connections/FL-record, so a dropped/extra/mis-wired cross-gap link slips past the topology clause entirely)
AND `roundtrip_nadoc`-stable (topology + FL-set) AND `validate_design` · _recipe:_ replays the golden's OWN feature
log — `create_bundle(len=40, ligate_adjacent=True)` → `_shift_duplexes(+8)` (resize every helix's low-bp end into bp
8…39, derived mechanically from live domain directions) → 2 asymmetric gap-bridge `(resize_strand_end, force_ligate)`
pairs (the bridge geometry a hand-authored per-primitive constant, NOT geometrically re-derived — ASK-FIRST); replaying
create-at-40-then-shift rather than create-at-32 is load-bearing because AF-30 ISSUE-13 axis re-trim makes only the
same op sequence reproduce the golden's axis floats · _tests:_ 5 in `test_headless_hinge_build.py` (shape, replayable
feature-log, isolation, unknown-name `KeyError`, golden-match) + 4 in `test_automation_harness.py` (oracle pass +
dropped-link red + wrong-topology red + unknown-name red), full suite **3240 passed / 61 skipped / 2 xfailed** (+9, no
drops) · **"Validation gained, not just a passthrough:** before AF-33 the standard hinges existed only as hand-built
`.nadoc` files with no programmatic builder, and nothing proved a code-built hinge reproduces one. `build_hinge_primitive`
constructs the 2x2 hinge from base ops, and `assert_matches_primitive` proves it is byte-for-byte the validated golden —
topology AND the off-strand-graph FL links AND save/load persistence — so a builder that drifted (wrong duplex shift,
dropped/mis-wired link, altered leaf layout) fails. **Unblocks AF-34** (drive this hinge through `auto_scaffold` + a
routing-compliance oracle).**"

---

**AF-34 — reusable autoscaffold routing-COMPLIANCE oracle + headless hinge autoscaffold validation** ·
_shape:_ 1 reusable oracle `assert_scaffold_routing_compliant` in `tests/automation_harness.py` (wraps the existing
`backend/core/scaffold_invariants.scaffold_routing_invariants` self-gate — re-implements nothing) + an end-to-end
build→route→validate driver in `tests/test_headless_hinge_build.py`; `crud.py`/`assembly.py`/`main.js`/`headless_build.py`/
`headless_hinge_build.py` LOC Δ = **0** (no production code touched — the gate + builder + wrapper all already shipped;
this is the validation-augment leg) · _headless-coverage Δ:_ **48 → 48 / 239** (FLAT — composition over the
already-covered `auto_scaffold`; the oracle is the deliverable, as the spec predicted) · _oracle shipped:_
`assert_scaffold_routing_compliant(design, *, require_seams=True)` — (1) **non-vacuity** (design HAS a non-reference
scaffold strand — else the invariant checker returns `[]` vacuously on an un-routed design and the oracle would pass on a
silently-failed route) + (2) **compliant** (`scaffold_routing_invariants` returns no violations: seam crossovers present
when `require_seams` + every non-seam end/turn scaffold crossover ≥3 bp clear of staples) · _driven end-to-end:_
`build_hinge_primitive("2x2_single_hinge_link")` (builds from scratch — **no golden file needed**, runs in a clean
checkout) → `hb.auto_scaffold()` (the seamed entry dispatches to `hinge_router` on `forced_ligations`) → single seamed
invariant-clean scaffold + `validate_design`; the FIRST fully-headless hinge build→route→validate win · _gotcha banked:_
a plain `create_bundle` routed seamed is NOT compliant (its blunt full-length staples bury the end crossovers → 2 bp
margin), so the non-hinge GREEN meta-test uses a SEAMLESS route at `require_seams=False` (end crossovers land in extended
ssDNA) and the SAME seamless route at `require_seams=True` is the load-bearing RED (the exact LESSONS H8 regression — a
seamless raster passed off as seamed); the genuine seamed-green is the hinge end-to-end · _tests:_ 1 end-to-end in
`test_headless_hinge_build.py` + 3 oracle red/green in `test_automation_harness.py` (seamless green at False; seamless red
at True; no-scaffold non-vacuity red); 2x2 GREEN, 2x4/2x6 ride the existing `test_hinge_router` xfail (G6, untouched) ·
full suite **3244 passed / 61 skipped / 2 xfailed** (+4, no drops) · **"Validation gained, not just a passthrough:**
before AF-34 the routing-compliance gate (`scaffold_routing_invariants`) was asserted only INSIDE
`test_scaffold_invariants.py` over a few fixed entry points — no AF build could pin its OWN autoscaffold output as real
routable origami rather than a seamless raster with buried crossovers (the exact regression that previously shipped green,
LESSONS H8). `assert_scaffold_routing_compliant` exposes it as a reusable, non-vacuity-guarded oracle, and the hinge
end-to-end proves the first headless build→route→validate chain produces a compliant single scaffold.**"

---

## Data summaries (plots + fits)

### AF-24 — field-driven equilibration time τ on the REAL oxDNA engine (2026-06-23)

**Artifacts** (committed): `design_automation_analysis/field_equilibration_tau.png` (annotated 4-panel) +
`field_equilibration_data.csv` (30 cells) + `fit_field_tau.py` (reproducible fit/plot). Generated by scratchpad
`af24_dataset.py` on CUDA. **Dataset:** an anchored E-field swept over field strength {1.0, 1.5, 2.0, 2.5, 3.0 pN}
× direction {axis_z, perp_x, perp_y} × design {test343 = 1 duplex, N_free=84; 6hb = 6-helix bundle, N_free=462};
each cell is a 30 k-step field stage branched off ONE STANDARD-relaxed (re-annealed) parent, with τ / plateau Δ₀ /
bp_min from `measure_field_equilibration`.

**Findings (real physics, not mock):**
- **τ vs field strength: ~FLAT** — test343 τ̄ = **3705 ± 599 steps**; linear slope 248 steps/pN, **R²=0.08** (field
  explains ~8% of τ → drag-limited, NOT field-limited). The overdamped signature: the field sets the swing
  *amplitude*, not the *rate*.
- **Δ₀ (initial alignment difference = plateau A∞) ∝ field, LINEAR**, per direction: axis_z Δ₀≈3.67·pN+1.98
  (R²=0.89), perp_x 4.07·pN−1.12 (R²=0.83), perp_y 3.45·pN−2.20 (R²=0.94). Direction shifts the baseline — the body
  swings farther along the duplex axis (anisotropic).
- **Non-destructive window:** bp_min falls 0.93–1.0 (1 pN) → 0.52–0.64 (3 pN); benign ≲ 2.5 pN at 30 k steps before
  approaching the 0.5 melt floor (so "aligns WITHOUT ripping apart" up to ~2.5 pN here).
- **Cross-section sets the REGIME:** test343 TETHERS (finite τ); the 6hb (5.5× the free beads, SAME single-domain
  anchor) **STREAMS** — alignment grows ~linearly (0 → 1043 nm over 200 k steps), no plateau, no finite τ. The
  transition is `anchor_stiff·N_anchored` vs `field·N_free`. (The 6hb DID re-anneal under `STANDARD_RELAX_PARAMS` —
  the fix generalizes to a 6-helix bundle.)

**General equation attempted** (overdamped anchor-tethered body, real-engine fit):
> A(t) = Δ₀·(1 − e^(−t/τ)) — tethered regime, when `anchor·N_anchored ≳ E·N_free`
> Δ₀ ≈ c·E·N_free  (c ≈ 3.4–4.1 nm/pN here; linear in field × cross-section)
> τ ≈ γ/k ≈ 3700 steps  (drag/stiffness; ~independent of E and Δ₀)
> else → STREAMING: A(t) ≈ v·t, no finite τ (under-anchored).

**Caveat / next:** τ's *cross-section* exponent is UNDER-DETERMINED — only one design tethered (the 6hb streamed),
so τ(N_free) is a regime observation, not a fitted power law. AF-24 P2/P3 should add a body-SCALED anchor + ≥2
tethered cross-sections (and repeats per cell — each oxDNA run has a fresh RNG seed, hence the ±599 scatter) to pin
τ(N_free) and the field-strength↔τ law across the response surface.

### AF-25 — headless feature-log SEEK wrapper + non-destructive-scrub oracle (2026-06-24)

**Shape:** headless wrapper (`backend/api/headless_build.py::seek_features(position, sub_position=None)`) over the
existing `POST /design/features/seek` route — the single primitive behind "scrub the build timeline" / "roll a job
back to its run state". Runs the same route service mouse-free; no logic in `crud.py`.

**Primary metric — validation augment:** `tests/automation_harness.py::assert_feature_seek(seek_fn, checkpoints)`
pins the five scrub invariants: (1) non-destructive (log length unchanged — unlike revert, which truncates),
(2) cursor lands at the requested position, (3) faithful reconstruction (`design_build_fingerprint` at P equals the
forward-recorded fingerprint), (4) reversible (`seek(P)` then `seek(-1)` returns to latest exactly), (5) effect
removal via optional structural probes. Pin: `test_headless_build.py::test_af25_feature_seek_scrubs_timeline_
faithfully` (bundle → auto-scaffold → assign-scaffold-sequence → overhang, fingerprints recorded forward).

**Secondary metrics:** headless coverage **37 → 38** (`/design/features/seek` now wrapped — the three
`*_adds_no_coverage` pins bumped 37→38). God-files flat (logic stayed in the route service; only a thin wrapper added).
Cohesion: one reason to change — the seek-then-serialise contract.

**REAL BUG FOUND + FIXED (the point of the loop).** The oracle went RED first run, not green: `crud._topology_
substitute` restored every topology-bearing field from the seek snapshot **except `overhangs`**. The downstream seek
loop only re-applies overhang *rotations* (a display delta) — it never adds/removes overhangs — so seeking before an
overhang-extrude (or to empty) dropped the overhang's helix + strands but left a **dangling `overhangs` entry**.
Because `overhangs` is in `design_build_fingerprint`, the seeked state's fingerprint was wrong → in
`roll_active_to_job_state` the `design_build_fingerprint(seeked) == design_build_fingerprint(snapshot)` clean-path
check failed and fell through to the snapshot-overlay fallback; the manual feature-log seek left a stale fingerprint,
which is consistent with the reported "⚠ out-of-date doesn't clear after a back-seek". **Fix:** add
`overhangs=snap_design.overhangs` to `_topology_substitute` (snapshot is ground-truth membership; rotation deltas
still overwrite per-overhang afterward, so display layer is preserved). Full suite **3119 → confirm green**.

**Validation gained, not just a passthrough:** first programmatic proof the timeline scrub reconstructs + reverses
faithfully and non-destructively — AND it immediately caught a real reconstruction bug (stale overhang membership)
that the existing per-slice backend tests missed. This is the missing primitive AF-26 composes for the job roll.

**FOLLOW-UP (2026-06-24, real-app repro on `workspace/6hb_sim_tests.nadoc`): the overhang-membership fix above was
necessary but NOT sufficient — the "⚠ doesn't clear after a back-seek" symptom had a SECOND, independent cause.**
A *manually-assigned overhang sequence* (`PATCH /design/overhang/{id}` with a `sequence`, or
`POST /design/overhang/{id}/generate-random`) wrote a build-fingerprint field but recorded **no feature-log entry** —
those two paths called `replace_with_reconcile` / `set_design` directly while every sibling op
(`overhang-extrude`, `overhang-bulk`, `assign-*-sequences`) used `mutate_with_feature_log`. So the live design and the
timeline silently diverged: a relax froze the live (sequenced) overhang, but the entry's stored snapshot had the
overhang sequence as `None`/`NNNN…`, and seeking back faithfully restored the snapshot → fingerprint never re-matched →
⚠ never cleared. In `6hb_sim_tests` the overhang `ovhg_h_XY_1_1_83_5p` was live `ATACTCGCTC` (frozen by the job) but the
position-7 snapshot held `None`. **Fix:** route both sequence-write paths through `mutate_with_feature_log(op_kind=
'overhang-sequence', …)` (new `SnapshotOpKind` literal); a concurrent rotation is captured by that snapshot so the
rotation-only delta path is unchanged. Pins: `test_oxdna_staleness.py::test_overhang_sequence_patch_is_feature_log_
step_and_clears_stale` (full stale→roll→clear repro, can-go-red proven: revert the crud change → no log entry → RED) +
`::test_generate_random_overhang_sequence_is_feature_log_step`. Full suite **3131 → 3133 green**. **MIGRATION: none** —
files already in the broken state (incl. `6hb_sim_tests`) are repaired by re-applying the overhang sequence once after
the fix (which writes the proper log entry); that job's ⚠ then clears on seek. Audit confirmed the bulk-generate,
sub-domain split/merge/patch, and generate-binder paths already log, so only these two leaked.

### AF-26 — job-staleness ROLL/RETURN lifecycle wrapper + oracle (BACKEND leg, 2026-06-24)

**Shape:** two headless wrappers — `headless_oxdna_build.roll_job_to_run_state(job_id, workspace)` (wraps
`POST /oxdna/jobs/{id}/roll-design`, operating on the LIVE active design) + `headless_build.return_to_latest(loadout_id)`
(wraps `POST /design/loadouts/{id}/select?save_current=false`). They compose the existing relax/edit/seek primitives.

**Primary metric — validation augment:** `automation_harness.assert_roll_return_lifecycle(...)` drives the whole
**simulate → edit → roll → return** loop through the wrappers and asserts each leg: precondition stale; a production
attempt on the stale job refused **409** (the crash-guard); roll keeps the full log + seeks the cursor to the job
position + banks a `return_loadout_id`; rolled fingerprint == run state + sequences survive + edit's topology gone;
**the out-of-date flag clears**; return-to-latest restores the edits. Pin:
`test_oxdna_staleness.py::test_af26_roll_return_lifecycle_overhang_edit` — uses the OVERHANG edit (the membership case
AF-25 fixed) the per-slice tests never drove.

**Secondary metrics:** headless coverage **38 → 39** (`/design/loadouts/{id}/select` now wrapped); oxDNA coverage
**4 → 5** (`roll-design`). God-files flat (logic stayed in the routes). Cohesion: roll/return wrappers each have one
reason to change (their route's contract).

**KEY FINDING (matches the spec's prediction).** The AF-26 BACKEND oracle **passes even with the AF-25 fix reverted** —
because `roll_active_to_job_state`'s snapshot-overlay *fallback* already restores the run-state topology and clears the
flag at the backend level (verified: revert the `_topology_substitute` one-liner → AF-25 goes RED, AF-26 stays GREEN).
So the backend lifecycle is sound; the live "⚠ doesn't clear / cursor doesn't roll" bug the user reports lives in the
**frontend** (panel refetch on `nadoc:design-changed`, Feature Log rail-thumb, scene rebuild). **AF-26 is therefore
NOT complete with the backend leg alone** — per the backlog it needs a REAL end-to-end Playwright leg over the actual
oxDNA/MD panel + Feature Log rail, made to go RED on the running app first. That leg is the remaining deliverable.

**Validation gained, not a passthrough:** first single driven proof of the staleness→roll→return contract incl. the
409 guard, exercising the headless wrappers end-to-end; AND it localized the live bug to the frontend by proving the
backend lifecycle correct under fix-revert.

### AF-26 — the real end-to-end Playwright leg (2026-06-24) — TIER 7 COMPLETE

**Deliverable:** `frontend/e2e/job_log_sync.spec.js` drives the GENUINE path — the real oxDNA jobs panel, a real
overhang edit (`extrudeOverhang`), a real feature-log seek (`seekFeatures`) — and asserts the RENDERED DOM: the
seeded job's row has no `.oxdna-job-stale-warn` initially, gains it after the edit, and **loses it after the manual
seek back** while the store's design rolls (overhangs → 0, `feature_log_cursor` → run position). GPU-free seed
`tests/e2e_seed_af26.py` (a completed job + matching .nadoc, self-cleaning by a marker name + seed signature). Two
minimal panel testability hooks: `row.dataset.jobId` + the `.oxdna-job-stale-warn` class.

**Can-go-red PROVEN in the browser** (the backlog's hard requirement): reverting the one-line `_topology_substitute`
fix makes the spec fail at the post-seek assertion (the ⚠ stays) — the exact user-reported symptom; restoring →
green. So the e2e exercises the real failure mode the green unit tests missed, and pins the AF-25 backend fix
end-to-end through a browser.

**Why the unit tests missed it (the lesson):** `roll_design_sync.test.js` / `job_staleness.test.js` pinned the client
functions in isolation (roll applies the design; seek fires `nadoc:design-changed`) and all passed — but the bug was
the BACKEND seek reconstruction returning a wrong fingerprint, invisible to any frontend-only or backend-slice test.
Only a test that drives real backend seek → real refetch → real DOM catches it.

**Infra finding:** the running dev backend was on STALE code (its `OxdnaJob` predated `design_fingerprint`), so it
silently dropped every fingerprinted job from the list (the per-job loader swallows exceptions) — the staleness
feature was effectively dead in that server. Restarted it. Worth checking the dev server is current when a
staleness/job feature "doesn't work in the app but passes tests".

---

