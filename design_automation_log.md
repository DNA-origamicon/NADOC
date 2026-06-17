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

## Difficulties ledger (genuinely-stuck items + why)

_(none yet.)_
