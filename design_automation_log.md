# design-automation extraction log — metrics, oracle catalog, lessons, difficulties

Sibling of `backend_router_extraction_log.md` / `issues_fix_log.md`. The backlog + protocol + handoff live
in **`design_automation_backlog.md`**; this file carries the durable state a cold session needs: the
**oracle catalog** (validation building blocks to mirror), the **metrics rows** (one per shipped AF item,
with the mandatory justification line), the **lessons** (anti-patterns banked), and the **difficulties
ledger** (genuinely-stuck items + why).

---

## Conventions

- One AF item (or one phase) per session, per commit. Commit message: `feat(automation): <op> + <oracle>`.
- The pass criterion is the **validation augment**, never "a wrapper exists" (see the backlog's anti-shovel
  contract). Every row below ends with **"Validation gained, not just a passthrough: ___."**
- New code lands in `headless_build.py` / a new `headless_*_build.py` / `backend/core`. **Never** in
  `crud.py` / `assembly.py` / `main.js`. Cite the god-file LOC Δ (must be flat-or-lower) in the row.
- `backend/core` imports nothing from `backend/api`. Wrappers run the *same* service the route runs — they
  do not re-implement it.

## How to check headless coverage (the probe)

Before picking an item, see what's already wrapped vs. what has only a route:

```bash
# routes defined in the backend:
rg -n '@router\.(get|post|patch|put|delete)\("' backend/api/ | rg -o '"/[^"]+"' | sort -u
# wrappers that exist today:
rg -n '^def |^    def ' backend/api/headless_build.py
# is a given op UI-wired (worth wrapping) or dead (delete candidate)?
rg "<url-fragment>" frontend/src/api/
```

(AF-1 turns this into `headless_coverage_report()` so it stops being a manual grep.)

---

## Oracle catalog — the validation building blocks (MIRROR THESE; don't reinvent)

Every AF item must ship a validation augment that is one of these forms or a faithful new instance of one.
Pulled from the 2026-06-16 audit; each is a *proven* pattern already green in the suite.

| Oracle / pattern | Pins | File(s) | Reuse for |
|---|---|---|---|
| `_canonical_topology(design)` | id/order-independent design fingerprint (helices by grid_pos; strands by grid_pos+bp-range+direction) | `tests/test_section_router.py` | round-trip equality for ANY headless build (AF-1 promotes it shared) |
| `validate_design(design)→ValidationReport` | no unresolved nicks, strand-position consistency, domain count | `backend/core/validator.py` | a "build is well-formed" gate on every wrapper |
| `derive_periodic_delta(design)` | rigid repeat transform (Kabsch on axis geom; pure axial translate, no spiral); `det(R)=+1` | `backend/core/periodic_polymer.py`; `tests/test_periodic_polymer.py` | polymerize / periodic / belt seam geometry (AF-9) |
| `solve_closing_curvature` / `closure_residual` | κ that closes an N-copy ring to <0.5°/<0.5 nm | `tests/test_periodic_polymer.py` | bend-by-curvature oracles (AF-6) |
| circle circularity oracle (`circularity_spread`, `column_lengths`, `fit_radius`) | disc profile spread <0.5 nm; even symmetric trim; ≥16 bp floor | `backend/core/circle_primitive.py`; `tests/test_circle_primitive.py` | parametric primitives (AF-4) |
| `derive_placement_spec(design)` | footprint cells + per-cell bp + anchor from feature log | `backend/core/primitive_catalog.py`; `tests/test_primitive_placement.py` | placement / continuation specs (AF-5) |
| section-router gap metrics (`intertooth_gap_extension`, `min_per_gap_clearance`, `_scaffold_coverage`) | multi-section routing geometric clearance | `tests/test_section_router.py`; `backend/core/seamed_router.py` | multi-section / irregular design routing |
| scaffold invariants (`_active_scaffolds`, matched-ends far-translate, seamless N−1 crossovers) | single active scaffold; polymerization-ready junctions | `tests/test_seamed_router.py`, `test_seamless_router.py` | any scaffold-routing wrapper |
| cadnano round-trip (`import_cadnano` ↔ export; helix-id encodes row/col) | external-format parity | `backend/core/cadnano.py`; `tests/test_cadnano.py` | import/export wrappers |
| atomistic round-trip (CG↔all-atom, RMSD<0.005 Å) | coarse→atom fidelity | `tests/test_atomistic_round_trip.py` | structural-export wrappers |
| feature-log round-trip | log entry shape/params/revertability survive JSON | `tests/test_feature_log_*` | any feature-logged (revertable) op |
| conftest builders (`make_teeth/6hb/18hb/mini_hinge_design`) | feature-log replay reconstructs a fixture's canonical topology | `tests/conftest.py`; `tests/test_section_router.py` | the build_fn input to `assert_roundtrip_stable` |
| `overhang_candidate_error` / `valid_overhang_sites` | geometric feasibility of an overhang placement | `backend/core/lattice.py`; `tests/conftest.py` | overhang wrappers |
| design-geometry kernel (`_geometry_for_design`, `_strand_nucleotide_info`) | nucleotide position + 5′/3′ terminus convention | `backend/core/design_geometry.py`; `tests/test_design_geometry_core.py` | geometry-level assertions |
| `assert_binding_resolves` (AF-9) | a metadata-only cross-part relation's endpoints resolve to live targets (survives round-trip; the gap `canonical_assembly` can't see) | `tests/automation_harness.py` | any metadata-only cross-part relation (overhang connections next) |
| `assert_instances_on_grid` / `assert_instances_on_ring` (AF-10) | placed instance origins form an exact regular lattice (grid: count + even pitch + every cell; ring: on-radius + even `360°/n` step), measured on placed transforms, non-degeneracy guard | `tests/automation_harness.py` | any parametric instance-layout (radial-facing layouts, AF-11 DSL layout specs) |
| `assert_spec_matches_calls` (AF-11) | a declarative build-spec is lowered to the SAME canonical structure as the equivalent hand-call wrapper sequence (`canonical_topology` design / `canonical_assembly` assembly), non-emptiness guard; doubles as the spec→fingerprint golden pin | `tests/automation_harness.py` | any interpreter/DSL/codegen that claims to be sugar over existing ops (AF-11 grammar growth) |

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

---

## Lessons (anti-patterns banked — read before building)

_(none yet — first session. Candidates the audit already suggests:)_
- **Passthrough smell.** If your wrapper's body is one `requests`/service call and your "test" only asserts
  HTTP 200, you shipped a passthrough. The oracle must assert a *property of the result*, not that the call
  returned.
- **The route may be dead.** The audit found routes with no live frontend caller (e.g. parts of `/md/*`).
  Re-derive UI-wiring (protocol step 3) before wrapping — a dead route is a `issues_ledger.md` delete
  candidate, not an AF item.
- **Deformation is a three-layer minefield.** AF-6 touches bend/twist sign + frame conventions — `CLAUDE.md`
  says ASK FIRST on topology/geometry/directionality. Don't reason it out; confirm with the user.

### Banked from AF-2
- **An inverse-pair oracle needs a "forward really happened" guard or it passes vacuously.** If `forward`
  silently no-ops, then `forward∘inverse` trivially equals `start` and the oracle is green while proving
  nothing. `assert_inverse_pair` asserts the *mid*-state topology `!=` start before checking the round-trip —
  that guard is what makes it able to go red, and it's covered by a dedicated red-test.
- **Shipping a covered route invalidates the "this route is uncovered" meta-tests.** AF-1's
  `test_coverage_report_lists_real_backlog_routes` hard-coded `/design/nick` as uncovered; AF-2 covered it,
  so the test had to repoint to a *still*-uncovered backlog route (`/design/circle-segment`). Each AF session
  that flips a route must re-point any coverage meta-test that named it. (Coverage paths carry the `/api`
  prefix — match with `.endswith()`.)

### Banked from AF-3
- **`canonical_topology` ignores loop/skips — round-trip stability can't prove they persist.** Loop/skip
  marks live on `Helix.loop_skips`, not in the strand graph, so the fingerprint (and therefore
  `assert_roundtrip_stable` / `assert_inverse_pair`) is blind to them: a build with a loop and a build without
  it have identical canonical topology. To pin a length-changing op you need a *geometric* oracle that counts
  the kernel's emitted nucleotides (`geometric_nucleotide_count`). If a future op also lives outside the strand
  graph (cluster transforms, deformation ops, plate layout), the same blind-spot applies — pick the oracle form
  by what the op actually changes, not by reflex reaching for round-trip.
- **A global conservation check can cancel to zero — scope it.** apply-deformations places balanced
  loops+skips (twist) or near-balanced patterns (gentle bend), so the *global* net delta is ~0 and a
  whole-design count check passes vacuously. The real assertion is **per-helix**: each helix's geometric count
  must move by twice its own net mark delta. `assert_geometric_length_delta(..., helix_id=h.id)` is the strong
  form; loop over helices for bulk ops.
- **Geometry emits both strands per bp regardless of strand coverage.** `nucleotide_positions(helix)` emits
  forward+reverse for every effective bp of the helix span, joining strand metadata only as a lookup (default
  `_missing` when no strand covers). So a loop/skip's effect on the geometric count is a deterministic `2×δ`,
  independent of how the strands are routed — which is why the count oracle is robust on bare bundles and fully
  routed designs alike.

### Banked from AF-1
- **Drive the real route, don't reconstruct it.** `roundtrip_nadoc` round-trips through the actual
  `POST /design/import` handler (`Design.from_json` + migrate/autodetect/backfill), not a bare
  `Design.from_json`. A wrapper/oracle that re-implements the route's processing tests a *different* thing
  than what the user gets — always run the same service the route runs.
- **Match coverage by function identity, not strings.** `headless_coverage_report` maps routes→wrappers by
  the endpoint *function object* a wrapper imports. This is unstaleable (rename a route URL and nothing
  rots) AND enforces the anti-passthrough rule for free: a wrapper only counts as covered if it imports the
  real handler, so a re-implementation never shows as covered.
- **Make the oracle's seam injectable so you can prove it fails.** `assert_roundtrip_stable` takes a
  `roundtrip=` kwarg purely so the meta-test can feed it a *corrupting* round-trip and assert it raises. An
  oracle you've never seen go red is unproven — bake the negative test in from the start.

### Banked from AF-4
- **A pre-existing pure oracle does NOT cover the wrapper — measure the placed geometry, not the footprint.**
  `circle_footprint`/`circularity_spread` were already green in `test_circle_primitive.py`, so it was tempting
  to "reuse the oracle" by asserting on the footprint the wrapper computes. But that re-proves the pure math and
  proves *nothing* about the route/builder — a builder that mis-centred or dropped a helix would still pass.
  The validation augment must read the **result's geometry** (here: the placed helices' axis spans), closing the
  radius→footprint→route→builder→geometry loop. "Reuse the circularity *functions*" ≠ "reuse the circularity
  *test*"; the new oracle calls the former on data extracted from the built `Design`.
- **Wrapper-takes-the-parameter, not the pre-computed payload.** The route's `CircleSegmentRequest` wants
  `cells` + `cell_lengths` (the UI derives them in JS). A faithful headless wrapper takes the *radius* and runs
  the same `circle_footprint` the JS mirror runs, so the scripted disc is byte-identical to a clicked one — and
  the wrapper's surface is the user-meaningful knob (radius), not the route's internal payload. Mirror this for
  any op whose REST body is "pre-chewed" by a frontend: the wrapper re-chews from the high-level parameter.

### Banked from AF-5
- **`canonical_topology` / `assert_roundtrip_stable` cannot handle a `grid_pos=None` helix.** The fingerprint
  sorts helices on `grid_pos`, so any design containing a helix with `grid_pos=None` raises `TypeError: '<'
  not supported between NoneType and tuple`. `make_bundle_deformed_continuation` is the *only* bundle builder
  that omits `grid_pos` on its new helix (all others set `grid_pos=(row,col)`), so the round-trip oracle is
  unusable on a deformed-continuation build — AF-5 pinned it with the geometric `assert_on_deformed_frame`
  instead. Don't reflexively reach for `assert_roundtrip_stable`; if the op can emit a grid_pos-less helix,
  use a geometry oracle. (Whether the omission is a bug or intentional-to-preserve-baked-coords is a
  three-layer question logged as `ISSUE-11` — do NOT just add grid_pos without asking the user.)
- **The "differs from straight" guard is the deformed-placement analog of the inverse-pair mutate-guard.**
  Re-deriving the deformed frame and asserting the helices land on it is *near-tautological* (the oracle and
  the route call the same `deformed_frame_at_bp`), so on its own it would pass even if the deformation did
  nothing. The load-bearing assertion is that the deformed placement is displaced from the *straight* frame
  placement (recomputed on a deformations-stripped copy) — that is what makes the oracle go red on an
  un-deformed design and what proves the deformation actually drove the placement.
- **Sample-then-post with `source_bp` to mirror the replayable UI path.** The route accepts a baked frame
  (grid_origin/axis_dir/…) OR re-derives it server-side when `source_bp` is present. The wrapper fetches the
  frame via `get_deformed_frame` (to fill the required request fields) *and* passes `source_bp` — so a scripted
  continuation is replayable (survives delete/edit of the upstream bend) exactly like a clicked one, not frozen
  to a baked pose. Mirror this for any op whose route has a "trust the payload OR recompute live" fork.

### Banked from AF-6
- **A single endpoint-to-endpoint frame-rotation angle FOLDS past 180°/360° — sum per-step magnitudes to
  unwrap.** The naive oracle (`arccos((tr(R_b·R_aᵀ)−1)/2)` between the two plane frames) is only valid for a
  total rotation < 180°: a 200° bend reads 160°, a 400.8° twist reads 40.8°, a 540° twist reads 180°. Walking
  the frame in 1-bp steps and SUMMING each step's magnitude unwraps it (each step is ≪180°). This stays exact
  because bend/twist (and their superhelix composition) are constant-axis screw motions, so the SO(3) path
  length equals the geodesic — no over-counting. Confirmed empirically (bend 80/200, twist 90/540/400.8 all
  matched to the requested θ).
- **The deformed frame `R` already composes bend AND twist, so one magnitude oracle covers both.** `_frame_at_bp`
  integrates the combined screw motion (overlapping bend+twist → superhelix), and `deformed_frame_at_bp` exposes
  it as `[frame_right|frame_up|axis_dir]`. A bend tilts the axis; a twist spins right/up about the axis; both
  show up as the rotation-angle magnitude of the relative frame rotation. No need for a tangent-angle oracle for
  bend + a separate spin oracle for twist — the frame-rotation magnitude is the unified, direction-agnostic pin.
- **Staying direction-agnostic let AF-6 ship without the ASK-FIRST round-trip.** `CLAUDE.md` reserves bend/twist
  SIGN + frame conventions for the user. By pinning only the *magnitude* (κ·Δbp / total twist) — never which way
  it bends — the oracle is provably correct without needing the user to adjudicate sign/handedness. The backlog's
  floated signed-curvature/closure oracle (`solve_closing_curvature`) would have needed that conversation; it was
  deliberately not built. If a future item needs a *signed* curvature pin, that's the moment to ask.

### Banked from AF-7
- **A second headless module needs the coverage report taught about it, or its wrappers don't count.**
  `headless_coverage_report` matched routes against `vars(headless_build)` only. The new
  `headless_assembly_build.py` wrappers import real route handlers (so they ARE covered in spirit), but until the
  report scanned that module too, the `/assembly` routes stayed listed as uncovered — the wrapper existed yet the
  metric didn't move. When you add a `headless_*_build.py`, extend the report's module list in the same commit
  (it now iterates `(headless_build, headless_assembly_build)`), or the coverage Δ silently lies.
- **Round-trip via `import`, not `save`, to keep it in-memory and inline-preserving.** The backlog said "build →
  save → load", but `POST /assembly/save` auto-converts inline part designs to on-disk `.nadoc` files (changing the
  sources AND writing to the workspace). The faithful analog of `roundtrip_nadoc` is `to_json` → `POST
  /assembly/import` (`roundtrip_nass`): it exercises the real import handler, stays in memory, and keeps inline
  sources inline — so a self-contained scripted assembly round-trips with zero disk side effects. Use the file
  save/load path only when the test is specifically about the inline→file conversion.
- **Keep test assemblies ≤6 'full'-rep instances.** `import_assembly` runs `_maybe_auto_downgrade_for_memory`,
  which silently rewrites >6 `representation='full'` instances to `'cylinders'`. `canonical_assembly` reads the
  rep field, so an oversized assembly would fail the round-trip fingerprint check for a *non*-bug reason. The real
  threshold is a UI/memory guard, not a topology fact — small fixtures sidestep it.
- **`canonical_assembly` keys inline sources by the design's `canonical_topology`, NOT `design.id`.** The id is a
  uuid that *is* preserved across round-trip, so keying on it would pass — but it wouldn't be order/id-independent
  the way the design fingerprint is, and it would miss a builder that swapped one part's design for a
  topologically-different one carrying the same id. Reusing `canonical_topology` makes the assembly fingerprint
  inherit the design fingerprint's robustness for free (and composes cleanly when AF-8 adds joints).

### Banked from AF-8
- **The mate snaps at create time — you don't need `resolve()` to get coincidence, but pin both.** `create_mate`
  → `_compose_add_joint` derives the snap from the LIVE connector world positions (`ca_world − cb_world`) and
  applies it to the child instance immediately, so connectors are coincident the moment `define_mate` returns.
  `resolve_assembly` re-applies the same constraint. The handoff framed the oracle as "post-`resolve`", but the
  faithful pin is "coincident after the mate AND still coincident after an explicit resolve" — test both (a resolve
  that *broke* coincidence would be a real bug the create-time-only check would miss).
- **No FK transform needed for a connector mate — let the connector-derived snap align the parts.** The UI's
  `create_mate` also accepts `moved_instance_id`+`transform` (the live drag pose), but `_compose_add_joint`
  recomputes the snap from the connectors regardless ("safety net — frontend pre-aligns, backend recomputes to
  guarantee coincidence"). So a headless `define_mate` can omit the FK move entirely and still land coincident —
  simpler and it exercises the same guarantee the route promises. The connector LOCAL `position`/`normal` (set via
  `add_connector`) are what drive the alignment.
- **A coincidence oracle passes vacuously on stacked parts — guard on part-origin separation.** If both mated
  parts sit at the same world origin with connectors at their part origins, "connectors coincident" is trivially
  true with no snap. The non-triviality guard asserts the two mated instances' *origins* are separated (the snap
  moved the child to a distinct place yet the connectors still meet) — place mate connectors at a non-zero LOCAL
  offset from their part origins so this holds. Same shape as AF-5's "differs from straight" and AF-2's "forward
  really mutated" guards: an oracle you can't make go red is unproven.
- **Enrich the joint fingerprint with the mated parts' SOURCE keys, not their instance ids.** `canonical_assembly`
  keyed joints by `(type, conn_a_label, conn_b_label, value)` — blind to *which parts* a mate joins, so a mate
  rewired to a different instance with the same labels would pass the round-trip fingerprint. Keying additionally on
  the two instances' source fingerprints (`canonical_topology` for inline, path+sha for file — the same id-
  independent keys the instance fingerprint uses) makes the joint key inherit that robustness. Use `("world",)` for
  a World mate's absent parent so the sort doesn't trip over `None` vs. tuple.

### Banked from AF-9
- **A resolve-invariant oracle must measure the moved GEOMETRY, not the stored joint value.** The gear route
  computes `θ_b = anchor_b + sign·(θ_a − anchor_a)·ratio` and writes it to `joint_b.current_value`. An oracle that
  reads `current_value` back and checks the same formula is testing the route's arithmetic against itself —
  tautological, proves nothing about whether the *part* actually rotated. `assert_gear_ratio` instead measures each
  coupled instance's **transform rotation magnitude** (the `_apply_revolute_value_to_gear_endpoint` + FK actually
  moved it) and asserts the ratio on that — so a gear that set the value but failed to drive the body (an FK bug)
  fails. Same shape as AF-4's "measure the placed geometry, not the footprint."
- **Driving via PATCH auto-propagates the relation — no separate `resolve()` needed (path 1).** `patch_joint`
  calls `_propagate_gear_relations_from(assembly, joint_id)` after applying the revolute, so a single
  `drive_joint(joint_a, θ)` moves joint_a's body AND every gear/belt-coupled body in one call. The handoff framed
  the oracle as "drive then resolve"; the faithful (and simpler) path is just `drive_joint` — the same auto-apply
  insight as AF-8's "the mate snaps at create time." `resolve()` re-applies all constraints and is the right tool
  only when you didn't get there through a driving PATCH.
- **`canonical_assembly` ignored `gear_relations` — extend the fingerprint when a new relation type ships.** The
  fingerprint keyed instances + joints but not gears, so a round-trip that dropped a gear would have passed
  `assert_assembly_roundtrip_stable` silently. Keying each gear by its two coupled joints' *id-independent
  fingerprints* (not joint ids) + ratio/invert/anchors makes the round-trip oracle catch it — the direct analog of
  AF-8 enriching the joint key with part-source fingerprints and AF-7 teaching the coverage report about a second
  module. **When you add a new top-level assembly relation list (belts next), extend `canonical_assembly` in the
  same commit or the round-trip oracle silently under-pins it.** (The return is now a 3-tuple; callers index
  `[0]`/`[1]` and compare equality, so adding `[2]` was backward-safe.)
- **Magnitude-only kept AF-9 clear of ASK-FIRST, same as AF-6.** The gear's `ratio` magnitude is the core promise
  and is direction-agnostic; `invert` only flips the driven body's rotation *sign*. Pinning the magnitude ratio
  (an `arccos`, always ≥ 0) needs no handedness/frame-sign reasoning, so no user adjudication was required. The
  invert *direction* is verified at the cheap `current_value`-sign level inside a test (pure scalar arithmetic, not
  a geometric convention), never in the oracle.

### Banked from AF-9 belts
- **Generalise the existing resolve-invariant oracle, don't fork a near-clone.** The belt's coupling promise is
  the SAME shape as the gear's (drive one body, the other rotates by the ratio), and `_belt_to_relation` already
  expresses a `BeltPath` AS a `GearRelation`. The temptation is a second `assert_belt_ratio` that copy-pastes 90%
  of `assert_gear_ratio`. The clean move was a one-line generalisation: make the oracle look the relation up in
  `_coupling_relations(assembly, joint_by_id)` (gears + belt-derived) instead of `assembly.gear_relations`, and
  hand it the belt's synthetic id `f"__belt__{belt.id}"`. Backward-safe because gears are first in that list — no
  existing gear test moved. One oracle now pins both coupling types; a future relation that also lowers to a
  `GearRelation` (a chain/sprocket) reuses it for free.
- **The belt's `radius` is the kinematic knob even though the model calls it "advisory geometry".** `BeltPulley.radius`
  is documented as frontend-computed advisory metadata (the *rendered* belt geometry — tangent line, centres — is
  computed in JS and not re-derived on the backend). But `_belt_to_relation` reads `radius_a`/`radius_b` to set the
  coupling ratio, so the radius IS load-bearing for kinematics. The validation gain is pinning that ratio
  derivation, NOT the rendered belt-path geometry. The **tangent length** the handoff floated as a second oracle
  is a *frontend* computation with no backend invariant to pin headlessly — pinning it would need porting that JS
  math (a future JS↔Python-parity item or an MV row), not an AF backend oracle. Don't try to oracle a quantity the
  backend doesn't actually compute.
- **A new top-level relation list → extend `canonical_assembly` in the same commit (third time this rule fired).**
  Same as AF-7 (teach the coverage report about a 2nd module), AF-8 (enrich joint key with part sources), AF-9 gears
  (fingerprint `gear_relations`): the round-trip oracle silently under-pins a list it doesn't fingerprint. Added
  `belt_paths` keyed by the two pulley joints' id-independent fingerprints + radii/sides/anchors. The return grew
  from a 3-tuple to a 4-tuple; every caller compares the whole tuple for equality, so the widening was backward-safe
  (verify with `rg 'canonical_assembly'` that nothing indexes a fixed position before widening).

### Banked from AF-9 polymerize
- **Re-derive the lattice from the SEED, not the route's chain helper, or the oracle is a tautology.** The
  obvious move is to import `compute_chain_transforms` and compare the placed copies to its output — but that
  re-runs the exact code under test, so a bug in the helper passes. `assert_polymer_chain` re-derives
  `delta = T_B @ inv(T_A)` and the `delta`-power progression from the seed pair's two world transforms ALONE
  (numpy, ~6 lines), independent of the implementation. Same shape as AF-9 gears' "measure the moved geometry,
  not `current_value`" and AF-4's "measure the placed geometry, not the footprint": the oracle must stand
  outside the implementation it pins.
- **Polymerize needs source-identical seed parts — share ONE `Design` object across both inline instances.**
  `/assembly/polymerize` 422s unless `_sources_match(inst_a.source, inst_b.source)` — for inline parts that's a
  structural-dump equality that includes nested helix/strand ids. Two separate `make_6hb_design()` calls can
  carry different nested ids → the dumps differ → 422. Passing the SAME `Design` object to both
  `add_inline_instance` calls makes both embed the identical dict, so the dumps match. (AF-8's mate fixtures
  used two *separate* designs because mates don't require source identity; polymerize does.)
- **No `canonical_assembly` extension this time — polymerize adds no new top-level relation list.** AF-7/8/9
  gears/belts each had to extend the fingerprint (coverage-module list / joint-source key / gear list / belt
  list). Polymerize only appends to the EXISTING `instances` + `joints` lists, which `canonical_assembly`
  already fingerprints, so a polymerized chain round-trips through `assert_assembly_roundtrip_stable` and a
  dropped copy/joint is caught with zero harness change. The "extend the fingerprint in the same commit" rule
  fires only when you add a new *top-level list* on `Assembly`, not when you grow an existing one.

### Banked from AF-9 overhang-bindings
- **For a metadata-only relation, pin referential INTEGRITY, not geometry — and know what the structure
  fingerprint is blind to.** An `AssemblyOverhangBinding` applies no geometry (no snap, no transform), so there's
  no placed position to measure the way the mate/gear/polymerize oracles do. The right property is that the
  binding's refs *resolve* to live overhang sub-domains. The non-passthrough punch is that `canonical_assembly`
  (the round-trip structure oracle) is BLIND here: it keys inline instances by `canonical_topology`, which
  fingerprints only helices + strands — NOT overhangs or sub-domains. So a round-trip that regenerated a
  sub-domain id while the binding kept its stale ref would pass `assert_assembly_roundtrip_stable` silently.
  Resolving the endpoints against the actual part designs is the only thing that catches that — genuinely
  orthogonal validation power, not a re-check of the route's create-time 404.
- **Extend `canonical_assembly` for the new top-level list AND ship a semantic oracle — they cover different
  failures.** The "new top-level relation list → extend the fingerprint in the same commit" rule fired a **5th
  time** (after AF-7 coverage-module, AF-8 joint-source key, AF-9 gears, AF-9 belts): added `overhang_bindings`
  as the 5-tuple's `[4]`. But fingerprinting alone is insufficient for bindings — it catches a *dropped/rewired*
  binding (structure change) but not a *broken ref* (the sub-domain-id-regenerated case above, which doesn't
  change the structure fingerprint). The pair (`canonical_assembly` extension + `assert_binding_resolves`) is
  what fully pins it; for a geometry-bearing relation (mate/gear) the fingerprint + the geometric oracle play
  the same complementary roles.
- **`model_copy(update=…)` bypasses the model validator — use it to construct the "impossible" red-test state.**
  `AssemblyOverhangBinding` has a field validator that rejects a self-binding at construction. The degenerate
  self-pair red-test needs exactly that forbidden state to feed the oracle. Pydantic v2 `model_copy` does NOT
  revalidate, so `binding.model_copy(update={"instance_b_id": …, "sub_domain_b_id": …})` builds the degenerate
  object without tripping the validator — the clean way to manufacture a corrupt state a constructor would
  refuse. (Same trick the gear/belt/polymerize red-tests use to shove a body off its lattice.)

### Banked from AF-10
- **A construction-sugar item moves the ORACLE count, not the coverage count — and that's fine, but say so.**
  Coverage is matched by route-handler function identity (AF-1). `place_grid`/`place_ring` wrap no new route —
  they compose the already-covered `add_instance` — so the coverage Δ is **0** by construction. That is NOT a
  passthrough smell: the loop's pass criterion was always the *oracle* (a property of the result), never a
  coverage flip. Most AF items happen to flip a route too, so the two move together; AF-10 is the case where they
  don't, which makes explicit that "validation gained" — not "coverage moved" — is the real bar. Log it plainly
  so a future reader doesn't mistake the flat coverage for a shovel.
- **A lattice oracle must check PROPERTIES of the placed result, not re-run the placement formula.** The trap
  (same family as AF-4's "measure the placed geometry, not the footprint" and AF-9's "measure the moved geometry,
  not `current_value`"): import `grid_translations`, recompute the expected origins, and `np.allclose` them to the
  placed ones — that re-runs the code under test, so a bug in the formula passes. Instead the oracle re-derives the
  lattice from the *user-facing params* as invariants: grid → "the origins occupy exactly `cols` evenly-spaced
  columns × `rows` rows with every cell filled"; ring → "every origin at `radius`, consecutive angular steps ==
  `360°/n`". These hold for the canonical lattice regardless of construction order and catch a transposed-axes /
  wrong-pitch / dropped-slot bug the formula-replay would mirror.
- **The ring's `radius>0` guard is genuinely load-bearing (unlike the grid's pitch guard).** For a grid, stacking
  all parts at the origin already fails the count-of-distinct-columns check, so the `pitch>min_pitch` guard is
  belt-and-suspenders. For a ring, `radius=0` puts every origin AT the centre where `dist==radius==0` is trivially
  true AND all angles collapse — the on-ring + step checks both pass vacuously. So the `radius>min_radius` guard is
  the only thing that can make the ring oracle go red on a degenerate request; its red-test (build 6 stacked
  instances, ask the oracle to pass with radius=0) is the one that proves the guard fires.
- **Orientation is an ASK-FIRST convention — ship translation-only, defer facing.** A common ring want is parts
  *rotated* to face the centre / tangent, but "which local axis points at the centre" is exactly the
  geometry/directionality question `CLAUDE.md` reserves for the user. AF-10 places origins only (identity rotation)
  — fully pinnable by a direction-agnostic origin oracle — and defers radial facing to a future item that opens
  with the orientation-convention conversation. Same discipline as AF-6 staying magnitude-only to avoid the
  bend/twist sign ASK-FIRST.

### Banked from AF-11
- **The faithfulness oracle (`spec ≡ hand-call`) IS the anti-passthrough proof for an interpreter.** A spec
  interpreter's whole risk is that it quietly re-implements an op (different default, dropped/mis-ordered step,
  mistranslated param) instead of driving the real wrapper. You cannot catch that with round-trip stability alone
  (a re-implemented build can still round-trip). The catch is `assert_spec_matches_calls`: build the spec AND the
  equivalent hand-call sequence, assert equal `canonical_topology`/`canonical_assembly`. This is the AF-4 lesson
  ("measure the placed geometry, not the footprint") applied to a whole pipeline — the oracle stands outside the
  interpreter and compares it to the thing it claims to be sugar over. Bonus: because the hand-call is
  deterministic, this same oracle IS the "spec → fixed canonical fingerprint" golden pin (no separate stored hash).
- **Split the interpreter pure-parser ⟂ driver so the grammar is testable HTTP-free and the driver re-implements
  nothing.** `backend/core/build_spec.py` (parse → ordered `BuildOp` list, validate, NO execution) imports nothing
  from `backend.api`; the driver `backend/api/headless_spec_build.py` only dispatches `BuildOp`s to real wrappers.
  This let 25 grammar/rejection pins run as pure unit tests (no build, no scratch session) AND kept the driver a
  thin dispatch table — the parser does all the validating, the driver does all the driving, neither does both.
- **A declarative spec must reference runtime ids by STABLE keys, not generated ids.** A nick can't name a helix by
  its uuid (the spec is written before the build runs). The fix: reference helices by lattice `grid_pos`
  `[row,col]` and resolve to the runtime id in the driver; reference assembly instances by a spec-assigned `ref`
  key the driver maps to the created instance id. The parser validates `ref` integrity (every `mate` endpoint was
  defined by a prior `add_part`, with the named connector label) so a dangling reference fails at parse time.
- **Build nested part designs BEFORE entering the assembly scratch session — don't nest scratch sessions.** An
  assembly spec's parts are nested design specs; `build_assembly` builds each via `build_design` (its own design
  scratch) FIRST, collecting standalone `Design` copies, THEN opens the assembly scratch and places them. Building
  a part inside the assembly scratch would nest two `doc_context` bindings — works (different state modules) but is
  needless; build-then-place is cleaner and each part is a detached deep copy by the time it's embedded inline.
- **Composition-sugar items keep coverage flat — same as AF-10, say so explicitly.** The interpreter wraps no
  route (it composes the already-covered `hb.*`/`hab.*`), so `headless_coverage_report()["covered"]` stays 32. That
  is NOT a passthrough smell: the pass criterion was always the oracle. Pinned with an explicit
  `test_spec_build_adds_no_coverage` so a future reader doesn't mistake the flat coverage for a shovel.

### Banked from AF-11 Phase 2 (grammar growth — bend/twist)
- **`assert_spec_matches_calls` is VACUOUS for any op `canonical_topology` can't see — pick the oracle by what the
  op changes, not by reflex.** A `bend`/`twist` op adds a geometric `DeformationOp` overlay that lives OUTSIDE the
  strand graph (exactly like a loop/skip — the AF-3 blind-spot, now confirmed for deformations). So the spec-built
  and hand-built designs have *identical* canonical topology whether the bend is applied, dropped, or mistranslated
  — `assert_spec_matches_calls` passes regardless and proves only the bundle plumbing. The load-bearing pin for a
  deformation cluster is the geometric `assert_deformation_angle` on the spec-built design (it realises κ×Δbp / θ).
  General rule for Phase-2 grammar growth: before reaching for the AF-11 golden pin, ask "does the canonical
  fingerprint see this op's effect?" If not (deformations, loop/skips, cluster transforms, plate layout), the
  faithfulness oracle is necessary-but-insufficient — add the op's own geometric/count oracle as the real augment.
- **Grammar growth that drives an already-validated wrapper is NOT an ASK-FIRST geometry decision.** Bend/twist is
  a three-layer minefield, but the sign/frame conventions were settled (ASK-FIRST) back in AF-6, and both the
  wrappers (`hb.add_bend`/`add_twist`) and the oracle (`assert_deformation_angle`) are direction-agnostic. Adding a
  spec op that plumbs `plane_a_bp`/`plane_b_bp`/`curvature`/`total_degrees` straight into that wrapper introduces
  ZERO new geometric reasoning — it's parameter routing. The discipline holds: drive the real wrapper, never
  re-derive a convention. (Mirror the parser's XOR validation of `total_degrees`/`degrees_per_nm` so a malformed
  twist fails at parse time, before the wrapper's own ValueError.)

### Banked from AF-11 Phase 2 (grammar growth — loop_skip)
- **A spec op can depend on a not-yet-grammared op — check the wrapper's runtime preconditions before scoping the
  cluster.** `loop_skip` and `apply_loop_skips` were listed as one cluster, but `apply_loop_skips_from_deformations`
  raises 400 unless the design has **crossovers placed** (cross-helix domain transitions), and NO current grammar op
  produces them (`bundle`/`extrude`/`ligate_adjacent` only ligate collinear fragments along one helix). So the
  sibling op was undriveable — and therefore unvalidatable — this session; it was deferred to ride with the
  `auto_scaffold`/`auto_crossover` cluster that generates its precondition. Lesson: when a handoff groups ops,
  re-derive each op's runtime guard (read the route handler) before committing to ship both — split the cluster at
  the dependency boundary rather than shipping an op you can't exercise.
- **Mirror the route's input domain in the parser, not just the type.** The loop/skip route constrains `delta` to
  `{-1, 0, +1}` (an HTTPException otherwise). The parser gates on that exact set, so a `delta: 2` spec fails at
  PARSE time with a precise message — before any build — rather than surfacing as a 400 deep in the driver. Pushing
  a known finite domain up into the pure grammar is free, reusable validation power (the `circle_segment` radius and
  the assembly layout counts are the same shape).

### Banked from AF-11 Phase 2 (grammar growth — circle_segment)
- **`assert_spec_matches_calls` is load-bearing again the moment the op touches the strand graph.** The bend/twist
  and loop_skip lessons established the faithful-façade oracle is VACUOUS for an overlay outside the strand graph.
  `circle_segment` is the inverse case: it ADDS real helices + strands, so `canonical_topology` sees it and the
  oracle becomes a genuine pin (a silently-dropped disc fails it). The rule isn't "Phase-2 ops need a geometric
  oracle" — it's "the oracle's power tracks whether `canonical_topology`/`canonical_assembly` can see the op's
  effect." Strand-graph ops (bundle/extrude/nick/ligate/circle_segment) → `assert_spec_matches_calls` is real;
  overlay ops (loop_skip/bend/twist) → it's vacuous and you need the geometric oracle. Pair both when in doubt.
- **A primordial op needs the `_PRIMORDIAL_DESIGN_OPS` set, not a special case.** `circle_segment` builds its own
  helices (like `bundle`), so it must be allowed as the FIRST op. Generalising the old `ops[0].op != "bundle"`
  check to a membership test (`not in _PRIMORDIAL_DESIGN_OPS`) keeps the "first op must be 'bundle'" substring in
  the message (so the existing extrude/nick/loop_skip/bend "can't-be-first" rejection tests still match) while
  admitting the new op. Future scratch-creating ops (auto-built rings, imported parts) drop into the same set.
- **A geometry-assumption baked into a wrapper is grammar-level validation when the spec carries the lattice.** The
  circle chord profile assumes the SQUARE column pitch — the AF-4 wrapper just documents "build in a SQUARE session"
  and nothing rejects a honeycomb build (it silently produces a non-circular profile). Because the *spec* names the
  lattice, the pure parser can reject `circle_segment` + non-square at parse time — free validation power no
  individual wrapper enforces. When an op's correctness depends on a session-level fact the spec also declares,
  cross-check them in the parser.

### Banked from AF-11 Phase 2 (grammar growth — gear)
- **A spec op that couples the OUTPUTS of two prior ops needs its own ref namespace — don't overload the instance
  refs.** A gear references two *joints*, which are created by `mate` ops, not by `add_part`. The instance `ref`
  namespace (`defined`) names parts, not joints, so a gear can't reuse it. The clean move: give `mate` an optional
  `ref` (a joint key), track it in a parallel `defined_joints: dict[ref→joint_type]` in the parser, and a parallel
  `joint_refs: dict[ref→runtime joint id]` in the driver (captured as `assembly_state.get_or_404().joints[-1].id`
  right after `define_mate` returns — the mate appends exactly one joint). This is the first grammar construct where
  one op references the runtime output of two prior ops; `belt` (two joints) and `polymerize` (one joint) reuse it
  verbatim. General rule: when a new op references something a prior op *created at runtime*, add a ref namespace for
  that thing, mirroring the existing instance-ref pattern — don't try to address it positionally.
- **For a fingerprinted top-level assembly relation, `assert_spec_matches_calls` is load-bearing AGAIN — but still
  insufficient alone.** The "pick the oracle by what canonical sees" rule (banked from bend/twist, then inverted for
  circle_segment) holds: a gear IS a `GearRelation` that `canonical_assembly` has fingerprinted since AF-9, so the
  faithful-façade oracle is a real pin (catches a dropped/rewired gear), unlike the deformation/loop overlays where
  it's vacuous. BUT — new wrinkle for *relations* specifically — the structure fingerprint catches a *structurally*
  dropped gear, not a gear that's present but fails to *propagate* (an FK/coupling bug). So pair it with the
  kinematic `assert_gear_ratio` (drive one side, measure the other body's real rotation). Same complementary split
  as AF-9 overhang-bindings (fingerprint catches dropped binding; `assert_binding_resolves` catches a broken ref).
  The refined rule: fingerprinted relation → `assert_spec_matches_calls` (structure) + the relation's own
  semantic/kinematic oracle (behaviour); the two cover different failures.
- **Push the route's relation precondition up into the parser via the ref's tracked metadata.** The gear route 400s
  unless both joints are revolute. Because the parser already tracks each mate ref's `joint_type` (for the new joint
  namespace), checking "gear joints are revolute" at parse time is nearly free — and it rejects gear-over-rigid
  before any build, with a precise message instead of a deep 400. Same shape as the loop_skip `delta∈{-1,0,+1}` and
  circle_segment square-lattice gates: when the spec already carries the fact a downstream guard needs, cross-check
  it in the pure grammar.

## Difficulties ledger (genuinely-stuck items + why)

_(none yet.)_
