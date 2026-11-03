---
name: project_headless_build
description: Mouse-free programmatic bundle/extrude construction API (seed for AI-driven design) + the test-design builders that use it
metadata: 
  node_type: memory
  type: project
  originSessionId: 88f75908-e5a2-4fbf-a999-f8f69e678526
---

# Headless construction — `backend/api/headless_build.py`

## Topic navigation and current boundaries

Reorganized October 17, 2026. Read the retained contracts here, then only the
matching detail below. Dated results and old handoffs are not new verification
or authorization; current user instructions and `CLAUDE.md` take precedence.

Programmatic, mouse-free design construction. The bundle/extrude **endpoints**
already are a "cells + length → bundle" API; this module is the in-process
surface over the same route handlers (`create_bundle`, `add_bundle_continuation`),
so scripted builds carry a real, replayable `feature_log` — indistinguishable
from a design built by clicking. Shipped 2026-06-09.

**Why:** path toward fully programmatic / AI-driven design (very-far-future goal
the user named). Also fixed an immediate gap: test designs built by calling the
core builders directly (`make_bundle_design`) had **empty feature logs**, because
the log is recorded one layer up by `state.mutate_with_feature_log`, which only
the route handlers wrap around the core builders.

**API:** `new_design` / `create_bundle` / `extrude` mirror the endpoints 1:1 on
the active doc; `build_bundle(cells, length_bp, *, lattice, passes=())` is a
one-shot **isolated** build (runs in a throwaway `doc_id` via `doc_context`,
dropped on exit — never disturbs the default session/undo). `passes`: int n →
`cells[:n]`, offset_nm = i×len×rise (the teeth pattern).

**Auto-op wrappers (2026-06-09):** scaffold routing, crossovers, staple
breaking, and overhangs — each a thin driver over the matching route handler,
returning the updated active design; chain them inside `scratch_session` exactly
as a person clicks. `auto_scaffold(seamless=False)`, `auto_crossover()`,
`auto_break(algorithm='basic')`, `auto_merge()`, `assign_scaffold_sequence(name)`,
`auto_break_aksel(**)`, `auto_route_aksel(**)`, `full_autostaple(name, **)`,
`overhang_extrude(helix_id, bp_index, ...)`. Handlers that fail raise
`fastapi.HTTPException` (catch like a status code). Composing
create_bundle→auto_scaffold→auto_crossover→auto_break at 388 bp reproduces a
fully-routed 18hb **deterministically**: `make_18hb_routed_design()` in conftest.

**Strand-edit wrappers (AF-2, 2026-06-16):** `nick(helix_id, bp_index, direction)`,
`ligate(helix_id, bp_index, direction)` (exact inverse — same `NickRequest` shape),
`delete_strand(strand_id)`. Each drives the real route handler (`add_nick` /
`ligate_strand` / `delete_strand`) and mutates the active doc; chain inside
`scratch_session`. Bad input → `HTTPException` (nick a 3′ terminus → 400; ligate
with no nick → 404).

**Loop/skip wrappers (AF-3, 2026-06-16):** `loop_skip(helix_id, bp_index, delta)`
(delta +1 loop / −1 skip / **0 removes** — the mark's own inverse) and
`apply_loop_skip_deformations()` (bake DeformationOps → marks; needs crossovers +
a deformation op, or a SQUARE design). Drive `insert_loop_skip` /
`apply_loop_skips_from_deformations`.

**Parametric circle wrapper (AF-4, 2026-06-17):** `circle_segment(radius_nm, *,
plane='XY', offset_nm=0, strand_filter, ligate_adjacent, min_chord_bp)` — takes the
**radius** (not the route's pre-computed `cells`+`cell_lengths`), runs the SAME
`circle_primitive.circle_footprint` analytic the JS preview mirrors, then drives
`add_circle_segment`. SQUARE-lattice (build in a SQUARE `scratch_session`). Raises
`ValueError` when the radius is below the min-chord floor (no helix qualifies).

**Deformed-continuation wrapper (AF-5, 2026-06-17):** `bundle_deformed_continuation(
cells, length_bp, *, source_bp, ref_helix_id=None, plane='XY')` — samples the deformed
frame (`get_deformed_frame`) then POSTs WITH `source_bp` so the route re-derives it
live (the replayable path). Drives `add_bundle_deformed_continuation`.

**Deformation wrappers (AF-6, 2026-06-17):** `add_bend(plane_a_bp, plane_b_bp, *,
curvature_deg_per_bp, direction_deg=0, affected_helix_ids=(), cluster_ids=())` and
`add_twist(plane_a_bp, plane_b_bp, *, total_degrees | degrees_per_nm, …)` (XOR — pass
exactly one twist spec or `ValueError`). Both drive `add_deformation`; bend/twist is a
geometric overlay (topology never bent). Magnitude pinned by `assert_deformation_angle`
(direction-agnostic — sign/frame is ASK-FIRST, deliberately not pinned).

- [Headless construction — `backend/api/headless_build.py` — continued detail](details/project_headless_build/01-headless-construction--backendapiheadless_buildpy.md)

## Sweep exploration and native inspection (2026-10-10)

`headless_sweep_build.py`, re-exported through `headless_build`, supplies
`sweep(cells, points_nm, **options)`, `preview_sweep(...)`,
`preview_sweep_edit(feature_index, **changes)` and
`edit_sweep(feature_index, **changes)`. All `SweepRequest` fields are accepted
and natively validated, including point orientations, movable/detached origins,
explicit sweep identity, and expected design/revision guards. The former wrapper
accepted only the older fixed-origin subset. No geometry or topology formulas
are implemented in these adapters.

These wrappers return native response dictionaries (the existing `hb.sweep`
contract); read the active Design from `state.get_or_404()`. Preview leaves the
document, revision and history unchanged. Edit patches retain omitted authored
fields and use native history replay, stable identities, downstream attachment
handling and Undo/Redo. `include_geometry=False` selects a lightweight creation
preview. See the [Sweep exploration example](../docs/vr_sweep.md#headless-exploration).
Focused coverage lives in `tests/test_headless_sweep_build.py`: actual handler
parity, evaluated nucleotide geometry, source detachment, roundtrip/history,
preview/commit agreement and atomic stale-guard rejection.

For design exploration, use the existing native inspectors and retained captures:
[inspection workflow](../docs/scrywrite_inspector.md) documents desktop
`window.__nadocInspect.toggle()` and browser inspection; the
[live-agent runbook](../docs/scrywrite_live_agent.md) documents VR
`scrywrite_observe`/`scrywrite_capture`, session discovery and capture provenance.
Load an isolated design copy, inspect the actual rendered shape after each
meaningful operation, and compare preview with committed output. Native preview
metrics are useful feedback but do not substitute for visible geometry or
simulation evidence.

The adjacent extrusion wrappers also forward native options: `extrude` accepts
`source_frame_id`, paired `expected_design_id` / `expected_revision` guards and
`separate_fresh_extrusions`; segment, circle and deformed-continuation wrappers
accept `separate_fresh_extrusions`. Defaults remain native defaults. Explicit
frame selection disambiguates identical cell addresses in independently placed
bundles. Focused geometry/ownership, roundtrip and stale-guard regressions:
`tests/test_headless_extrude_options.py`.

<a id="test-design-builders--testsconftestpy"></a>
- [Test-design builders — `tests/conftest.py`](details/project_headless_build/02-test-design-builders--testsconftestpy.md#test-design-builders--testsconftestpy)

## Overhang placement gate (2026-06-09)

The UI overhang tool only offers a placement where the staple end's **backbone
bead azimuthally faces** a vacant nearest-neighbour cell at that Z (radial
`dot ≥ 0.75` ≈ within 41°), per `frontend/src/scene/overhang_locations.js`. The
bead rotates with bp (helical phase), so a given bp can host an overhang only
toward the cell it faces. The raw extrude path historically enforced NONE of this
(only "a staple end exists here"), so direct-API / headless generation could
create overhangs at positions the UI would never allow (the 6hb_full_auto bug:
cells (0,0)/(1,4)/(−1,2) attached at bead-faces-away bps).

Fix: `overhang_candidate_error(design, orig_helix, bp, direction, nr, nc)` in
`backend/core/lattice.py` reproduces the UI predicate exactly (adjacency +
vacant-at-Z + dot≥0.75), computed on the **straight geometric layer** (NOT
deformed/physical). Enforced at the **endpoint layer** `_build_overhang_extrude`
(crud.py) → raises ValueError → HTTP 400, so UI / direct API / headless all gate;
the core `make_overhang_extrude` primitive stays **ungated** so geometry unit
tests (`test_overhang_geometry`) can probe arbitrary positions. The headless
`overhang_extrude` wrapper therefore raises `HTTPException` on a bad placement —
the generator catches it and skips. Tests:
`test_headless_build.py::test_overhang_extrude_{places_a_valid_candidate,rejects_a_non_candidate_placement}`.
**Nick-pair / end-cap occupancy bug (fixed 2026-06-09):** the cell-occupancy Z
check counted a helix's **axis** span, but a helix axis runs one base-rise past its
last nucleotide (the end-cap). For a short overhang that end-cap landed exactly on
the *adjacent* bp's Z, falsely suppressing the candidate one bp away (a nick-pair
sibling — e.g. placing an overhang at 1_2 bp55 killed the bp56 candidate). Fix:
occupancy uses the **nucleotide extent** `[axis_start.z, axis_end.z − one_rise]`,
via `_helix_nucleotide_z_band` (lattice.py) AND the frontend `cellZMap`
([overhang_locations.js:221]). `make_overhang_extrude` already shared the cell's
helix correctly for the second overhang (extends 8→16 bp, valid topology) — only
the gate was wrong. Regression: `test_adjacent_nick_overhangs_are_independently_placeable`.

`workspace/6hb_full_auto_test.nadoc` = the full demo: seamed scaffold + autostaple
+ **all** main-6hb overhang candidates filled (18 overhangs after the nick-pair fix;
was 14). Key insight: the gate
checks vacancy **at the staple end's Z**, and a short overhang occupies only a thin
Z-slice, so one lattice cell hosts MANY overhangs stacked along Z (the existing
helix is shared — cf. `test_two_overhangs_same_cell_share_helix`). "All candidate
locations" therefore means every (staple-end, facing-vacant-at-its-Z cell) pair, not
one-per-cell — a greedy loop that re-scans after each placement and stops when the
gate refuses all remaining mains (0 candidates left). Generator restricts the FROM
helix to the 6 ring cells so overhangs stem only from the main bundle, never from
overhang tips.

<a id="overhang-test-helpers-consolidated-2026-06-09"></a>
- [Overhang test helpers consolidated (2026-06-09)](details/project_headless_build/03-overhang-test-helpers-consolidated-2026-06-09.md#overhang-test-helpers-consolidated-2026-06-09)

<a id="test-migration-audit-2026-06-09--what-cancant-use-the-builders"></a>
- [Test-migration audit (2026-06-09) — what can/can't use the builders](details/project_headless_build/03-overhang-test-helpers-consolidated-2026-06-09.md#test-migration-audit-2026-06-09--what-cancant-use-the-builders)

## Mandatory agent publication boundary (2026-11-01)

The user's binding [structure/process rule](feedback_structure_requires_process.md)
now applies to every agent-authored deliverable, including diagnostic candidates
and flattened assemblies. Use `scripts.agent_structure_guard.publish`; it checks
serialized/reopened authoring and physical state by executing the complete log
from an empty root, without trusting recovery snapshots. Missing process,
unrecorded atoms, unsupported commands or changed diagnostic implementations
refuse publication with `AGENT_PROCESS_REQUIRED`. A nonempty log is insufficient.

November 2: publication additionally refuses private diagnostic and assembly
commands in part histories, even when they replay. Automated authoring must use
user-facing operations valid for the document host. `experiments.recorded_review_process`
remains an inspector/replayer for retained diagnostic evidence, not an admitted
part-authoring path. Production replay/editing does not execute its private stages;
the normal history slider can still read their recovery states. The old snapshot-only
`terminal_extension_review_nadoc` writer is disabled. Never bypass a refusal by
writing JSON directly. The filesystem itself is not an access-control sandbox;
AGENTS.md and CLAUDE.md require all agents to use this boundary.
