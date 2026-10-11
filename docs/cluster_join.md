# Join clusters

Open **Tools → Join…** or the **join** button in the desktop tool row while
editing a part. Join uses the shared draggable tool popup and the native 3D view.

1. Hover near a scaffolded cluster. Diamonds mark available side attachments;
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

Join currently requires disjoint whole-helix clusters. The moving cluster needs
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
