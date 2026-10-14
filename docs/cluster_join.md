# Join clusters

For the native headset workflow, see [VR Join clusters](vr_join.md).

Open **Tools → Join…** or the **join** button in the desktop tool row while
editing a part. Join uses the shared draggable tool popup and the native 3D view.

1. Hover near a cluster. Diamonds mark available side attachments;
   spheres mark end attachments. Click the point that should stay fixed.
2. Hover over a different cluster and click its moving attachment. Join previews
   a rigid transform of that entire cluster, shown in translucent cyan. Amber
   and green arrows show the two directed scaffold connections.
3. Adjust **Gap**, **Roll**, and **Tilt** and inspect the proposed placement.
   **Apply join** becomes available only after the current proposal passes its
   routing and placement checks. Applying creates one undoable history entry.

The first cluster stays fixed. The second cluster moves and rotates to face the
first attachment. End-to-side, side-to-end, end-to-end, and side-to-side
attachments use the same operation. Attachment sites come from usable edges in
the actual scaffold path, so they occur at discrete nucleotide positions.
Gap accepts 0.3–10 nm, roll ±180°, and tilt ±60°.

**Escape** first drops the second pick, then resets the first pick, then closes
the tool. **Reset picks** starts another selection; **Refresh sites** reloads
the available attachments. Orbiting over empty space remains available. Changing
the native design or switching documents retires the preview. Routine autosave
metadata updates preserve the picks and refresh their preview. An uncertain
network outcome requires **Refresh design** before another attempt.

## Scaffold construction

Join opens the selected directed edges `a → b` and `c → d` and splices their
paths using `a → d` and `c → b`. The moving scaffold's adjacent, same-helix nick
is closed; the fixed scaffold's termini remain. The result is one linear
scaffold instead of two. The two bridges contain explicit, counted ssDNA bases
and native flexible-segment marks, which are included in simulation exports.
They are not merely drawn connections.

Existing nucleotide occupancy, staples, and routing away from the splice are
preserved. Existing flexible-segment references are remapped to the merged
strand. The merged scaffold sequence and custom-source length are cleared
because the old sequence cannot describe the new route. Assign a scaffold of
the exact new length, reassess staple complementarity, and run readiness checks
before treating the design as ready to fold.

This directed splice follows the same useful construction principle as
MagicDNA's end-to-side DSCC operation; it operates on NADOC's native open
scaffolds and history. See the [original MagicDNA implementation](https://github.com/cmhuang2011/MagicDNA/blob/fd09b660b542e03a6d3f87dc2f5ff871219c8eab/class/hyperbundle.m#L6146)
and [publication](https://doi.org/10.1038/s41563-021-00978-5).
The separate [Help preview gallery](t_junction_previews.md) illustrates related
constructions without editing a part.

## Checks and current limits

The preview checks native domain order, occupancy, junction records, exact
nucleotide accounting, scaffold merging, and occupied backbone clearance.
It rejects rigid DNA separations below 0.65 nm and hard overlaps below 0.30 nm
between new connector beads and nonbonded DNA, including the other connector.
Directly bonded neighbors are excluded from the connector overlap check.
Apply recomputes the result atomically against the document, revision, and
preview token. Rejected or stale requests do not move a cluster or alter routing.
Undo, redo, history navigation, reverting/deleting Join, and save/reload restore
the pose and scaffold together.

Join currently requires disjoint whole-helix clusters. For immediate routed joins, the moving cluster needs
one scaffold with a closable adjacent nick and no existing external routing
connections or kinematic joint. Joined structures can stay fixed while further
independent clusters are attached. Hierarchical, domain-only, overlapping,
imported-residue, reference, individually posed nucleotide, and overhang-driven
clusters are excluded; moving overhang-bearing clusters are also rejected.
The popup reports eligibility or a specific reason when a proposed pair fails.

Clearance checks reject obvious backbone collisions; they do not predict
folding yield or molecular relaxation. A single pair of flexible bridges does
not constrain a mechanically rigid angle. Simulation and additional structural
constraints may be needed for the intended shape.

## Focused verification

Backend coverage is in `tests/test_cluster_join_core.py`,
`tests/test_cluster_join_api.py`, and `tests/test_cluster_join_history.py`.
It includes real routed bundles, both attachment directions, repeated joins,
bent geometry, loops/skips, fine routing edits, stale requests, native export
accounting, and history restoration. Frontend controller coverage is in
`frontend/src/scene/cluster_join_tool.test.js`. The isolated browser workflow in
`frontend/e2e/cluster_join.spec.js` uses actual hover/click selection, preview,
Apply, undo, redo, and both tool entry points.

## Free movement and multiple connections

The **Selection** box has independently clearable **Fixed** and **Moving**
fields. In point-picking mode, clearing either field keeps the other selection
and invalidates its old preview. Click a field to replace that selection.

Choose **Free movement**, then click a cluster body. A cyan preview
and translate gizmo appear. Use **Translate** / **Rotate**, or **Tab** while the
canvas is focused, to change gizmo modes. The authored design stays unchanged
until **Apply join**. Cancel, closing the tool, changing documents, or clearing
the moving selection discards the temporary pose.

Leave Fixed empty to search nearby eligible clusters, or click its field and
choose a particular fixed cluster. **Connection reach** sets the maximum
attachment-center separation (0.3–10 nm). While dragging, dashed gray lines
provide immediate proximity feedback. Colored, directed bridges and the
connection count appear when the current pose passes backend routing and
clearance checks. Gray hints are not promises of valid connections.

**Apply join** preserves the exact previewed position and rotation and commits
all colored connections as one undoable edit. There is no alignment snap and no
fixed connection-count limit. Each attachment pair creates two native ssDNA
bridges. Undo/redo restores the whole pose and route together.

The search examines every usable side edge and exposed end attachment within
reach across eligible fixed clusters. An integer optimizer selects the maximum
number of connections that can coexist, preferring shorter connections among
maximum sets. It enforces nucleotide attachment capacity, connector clearance,
and (for already routed clusters) complete linear scaffold paths. Conflicting
alternatives are excluded; compatible joins are not thinned to a sparse sample
or restricted to one fixed scaffold.

### Unrouted clusters

Scaffold precursors do not need a completed route before Join. Preview checks
all proposed nicks and ligations against the existing scaffold strands. **Apply
join** immediately creates every previewed connection as real ssDNA connector
domains and scaffold ligations, preserving the exact pose. The connectors render
as native DNA and are included in simulation exports; no later routing command
is needed to make the joins.

All original nucleotides, staples, and unaffected strands are preserved. If a
connection set closes a cycle, an ordinary native backbone edge receives a nick
so every scaffold remains linear. Several scaffold paths may remain: Join makes
the selected inter-cluster connections without completing unrelated internal
routing. Changed scaffold sequences are cleared. The pose, nicks, connectors,
and ligations form one undoable edit and survive save/reload.

After joining, select either rigid cluster in **Move/Rotate** and choose
**Constrained (tethers)**. All Join-created flexible ssDNA bridges participate
in the free-until-taut motion constraint, including connectors that belong to
neither rigid cluster. Unmarked rigid connections still block this option.

After Join, **Tools → Routing → Autoscaffold** completes the internal scaffold
routing. Both Seamed and Seamless routing preserve the actual Join ligations,
connector nucleotides, cluster poses, staples, and assigned nucleotide sequences.
Each connected joined component becomes one linear scaffold. Constrained movement
remains available because flexible marks follow their nucleotides into the new
route. Autoscaffold is a separate undoable operation.

The joined-component router protects bonds rather than freezing entire scaffold
strands. It uses lattice-valid crossovers, reciprocal interior seams in Seamed
mode, and end turns with at least three bases of ssDNA clearance from staples.
If no complete route is found within the bounded search, the original design is
retained; a fragmented partial result is not reported as successful. Whole-helix
clusters are supported; domain-level cluster membership requires a separate
membership remapping workflow.

Legacy saved join constraints remain readable and can still be realized by an
explicit Auto scaffold operation.

The distance-ranking and non-reuse behavior is informed
by MagicDNA's `SortDist` assembly workflow in
[`class/hyperbundle.m`](https://github.com/cmhuang2011/MagicDNA/blob/0c574bad121c260c04589fc050db63ab90250a36/class/hyperbundle.m#L7645).

Run `uv run pytest tests/test_cluster_join_free.py tests/test_cluster_join_constraints.py tests/test_join_scaffold_router.py` for multi-connection routing,
export, exact-pose and undo/redo checks. Run
`cd frontend && npx playwright test --config playwright.join.config.js` for the
isolated point-picking, free-movement gizmo and T-junction browser workflows.

To check a local saved design without changing it, set
`NADOC_JOIN_VERIFY_DESIGN=/absolute/path/T-junction.nadoc` when running
`tests/test_join_scaffold_router.py` or the Playwright `cluster_join_document.spec.js`
tests. Both workflows open temporary copies; no user design is committed.
