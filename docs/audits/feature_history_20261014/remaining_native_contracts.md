# Remaining native contracts — October 15, 2026

Implementation guide for the next P3 checkpoint, following
[the architecture review](architecture_review.md). This is a read-only code audit
and proposed decomposition, not completed implementation or test evidence.
Preserve existing scientific builders, phase constants and geometry. Assemblies
remain deferred; part-local nanoparticles, proteins and duplexes belong to P4.

## Confirmed recording gaps

- [`branch_seed`](../../../backend/core/branched_generator.py#L27) combines sparse
  track creation, path deformations and crossover constraints.
  [`route_branches`](../../../backend/core/branched_generator.py#L70) requires an
  explicit partition and splice restrictions. The corresponding
  [`two_np_build.materialize`](../../../backend/api/two_np_build.py#L378) entries
  do not retain those inputs.
- [`joined_seed`](../../../backend/core/joined_branches.py#L148) builds independent
  sections with canonical physical axes and separated lattice addresses.
  [`route_joined_branches`](../../../backend/core/joined_branches.py#L397) routes
  each section with the bounded router, then performs native Joins. Its scaffold
  record is not equivalent to the ordinary whole-part scaffold command; recorded
  Join bodies also lack `bridge_identity_seed`.
- [`materialize_connectivity`](../../../backend/api/connectivity_build.py#L159)
  copies `candidate.design` and records an incomplete `bundle-create` receipt.
  [`_prepare`](../../../backend/api/connectivity_build.py#L16) contains the actual
  construction, routing, curvature encoding, stapling and sequencing pipeline.
- Joined/connectivity summaries retain evaluated per-base positions and frames,
  but not complete source path recipes. Certifying those arrays as inputs would
  accept stored generated geometry. Planning must retain the authoring inputs.
- `CrossoverConstraint` has a random default ID. Native replay needs explicit
  deterministic identity. Constraints with no allowed intervals intentionally
  prohibit links and must not be dropped.
- `section-profile` already becomes ordinary `strand-end-resize` in
  [`ordinary_entries`](../../../backend/api/generated_commands.py#L57). Retain it.

## Proposed command boundaries

Names below describe contracts, not final public API names. Each command requires
a version, strict bounded schema, reference checks, deterministic identity policy,
and normal edit/repair support. Generated groups should expose their construction
steps, rather than becoming an opaque all-model feature.

| Step | Input contract | Existing builder to preserve |
|---|---|---|
| Sparse lattice tracks | `history_seed`, `nominal_length_bp`, `tracks: [{track_key, cell: [r,c], intervals: [{interval_key, lo_bp, hi_bp}]}]` | Construction-only portion of `branch_seed`, using `make_bundle_design` and the same polarity/phase conventions |
| Independent Join section | `section_id`, `history_seed`, `cells`, `length_bp`, `lattice_address_offset` | Per-section construction in `joined_seed`; preserve canonical axes and its even-column address separation |
| Section grouping/placement | Existing cluster creation, membership and pose inputs | Registered cluster-create/cluster-op overlay commands; keep placement separate from construction |
| Fork path | Path identity, target helices, `radius_nm`, `stem_bp`, `arc_bp`, `tail_bp`, `double`, `mirror`, origin placement | [`_path`](../../../backend/core/curved_branches.py#L72) and [`apply_fork_geometry`](../../../backend/core/curved_branches.py#L126); retain selected source inputs during planning |
| Joined crossbar path | Path identity, target section, endpoint/junction positions or source references, `tail_bp`, `central_bp`, `gap_nm`, additional left/right tail bases, existing strain policy/version | Path portion of [`crossbar_summary`](../../../backend/core/join_crossbars.py#L92), unchanged `_curve`, `_line`, `_frames` and tail-extension math |
| Connectivity path section | Path identity, section/group key, authored segment endpoint/frame inputs; optional parent path reference, shared interval and lattice offset | [`segment`](../../../backend/core/connectivity_generator.py#L62); copy shared stations from the regenerated parent path, then append the child's authored segments |
| Junction restriction | `constraint_id`, `helix_ids_a`, `helix_ids_b`, `allowed_bp_intervals` | `CrossoverConstraint`; normal create/edit/delete commands, preserving empty restrictions |
| Partitioned scaffold route | `history_seed`, `trunk: [{helix_id,lo_bp,hi_bp}]`, `windows: [{window_id,tracks,splice_interval,parent_helix_ids}]`, routing mode | [`route_sections`](../../../backend/core/section_router.py#L407) and existing branch validation; fail explicitly for missing targets or an unsuccessful/`None` result |
| Independent bounded scaffold route | `history_seed`, target cluster/helix references, `mode: bounded-seamed` | `auto_scaffold_seamed_bounded` with the same section extraction/merge as `route_joined_branches`; one feature per independently editable section |
| Native Join | Existing Join body plus `bridge_identity_seed` | `part_join_command.build` / `propose_free_cluster_join`; choose the seed before preview and application |
| Curvature encoding | Selected sweep/deformation IDs and contract version | [`encode_sweep`](../../../backend/core/generated_sweep.py#L58), restricted to selected operations; recompute after path/routing edits |
| Safe terminal budget fit | `scaffold_id`, `target_nt`, optionally selected terminal, contract identity/version | [`trim_to_budget`](../../../backend/core/branch_optimizer.py#L392); preserve its existing trim limit, anchoring, precursor removal and crossover-clearance checks |
| Stapling and sequencing | Existing complete parameters and seeds | Registered full-autostaple and scaffold/staple sequence commands |

The sparse-track command constructs only declared occupied lattice intervals.
Paths, constraints, routing, budget fitting and sequencing remain separate.
Per-track or per-section children can expose independent edits without cluttering
the collapsed feature list. Do not build each sparse interval with a fresh
extrusion unless equivalence is demonstrated: the current model may share one
helix across disjoint intervals, with a common extent and lattice registration.

Fixed loop/skip entries are appropriate when their positions are authored. A
generator step whose intent is to recompute curvature compensation needs the
semantic encoding command; replaying old mark positions after a path edit is not
the same operation. Keep scientific validity separate from replay certification.

## Identity, composition and planner handoff

Allocate a generation UUID and stable section/track/interval keys before building.
Derive child identities from those keys, not editable dimensions, list position or
discovery order. Preserve routing `identity_scope`, explicitly seed constraints
and Join bridges, and retain the namespace during edits. Existing local ID rules
may remain behind the generated namespace when proven deterministic.

`_generated_scope` currently selects all objects belonging to the generation
group. Per-section routing therefore needs explicit target selection and safe
merge; another group scope alone does not isolate one section. Preserve all
unrelated DNA, assets, deformations and constraints, and reject missing inputs.

Planners may search geometry and select retreat, junction, section-size or tail
settings. Persist those selected input choices and regenerate the command sequence
from them. For connectivity, retain `ConnectivityInput`, chosen
`junction_retreat_nm`, chosen `junction_bp` and duplex clearance. Compile these
into editable section/path/constraint/routing steps instead of invoking a new
whole-model generator command or decoding the cached candidate.

Execute each candidate sequence independently and compare all authoring fields
before stamping proof. Account explicitly for canonical ordering and identity
changes; do not weaken comparison to geometry counts or strand-only equality.
Keep the existing algorithms and sampled-path evaluation unchanged during this
refactor. Replacing indexed paths with an approximate ordinary spline would be a
geometry change, not merely a history migration.

## Suggested checkpoint sequence and evidence

1. **Planar lattice branches:** sparse seed, explicit partition route, existing
   stapling/sequencing. Verify real gaps, complete coverage and both lattices.
2. **Curved forks:** retain source path recipes, add explicit junction restrictions,
   curvature encoding and terminal fitting. Verify shared frames and restrictions.
3. **Joined branches:** independent sections, bounded routes, exact crossbar path
   recipes, individually seeded Joins. Preserve cargo and junction stations.
4. **Connectivity:** replace the candidate copy with compilation into the above
   contracts. Retain the distinction between assumed blunt-end clearance and an
   actual applied attachment.

Existing regression anchors: `test_branched_generator.py` and
`test_section_router.py` (gaps/coverage/polarity); `test_curved_branches.py`
(junction restrictions); `test_branch_optimizer.py` (safe trim and physical
budgets); `test_joined_branches.py` and `test_join_crossbars.py` (section separation,
fixed cargo and unchanged junction stations); `test_connectivity_generator.py`
(reviewed trees, stale sources and shared frames); `test_generated_native_proof.py`
and `test_generated_commands.py` (input-only replay, preserved independent work,
full-state comparison, ordinary editing and scrub/revert).

For each supported family add focused cold replay, parameter edit, missing
reference and delete/repair tests with poisoned recovery outputs. Use retained
input fixtures for routine tests instead of repeating the planner's expensive
search. Keep existing scientific guards and avoid automatic physical simulation.
Benchmark command count, capture size, cold replay and suffix-edit costs before
declaring performance acceptable. Do not relabel unsupported cases as verified.

CPD conversion remains a separate unfinished P3 contract; this decomposition does
not resolve it. Admission hardening and a process boundary do not by themselves
prove deterministic CPD input replay or establish an acceptable execution budget.
P4 must separately cover immutable asset provenance, proteins/NPs/duplexes and
attachments. This document does not claim a completed inventory of those paths.
