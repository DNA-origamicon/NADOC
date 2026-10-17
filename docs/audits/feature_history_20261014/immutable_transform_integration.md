# Native transform integration — U54

**21/38 milestones complete; 17 remaining (8 core, 9 parked).** U54 is engineering
checkpoint 54 since B1. FH-28 remains open after ten checkpoints, task-growth
flagged. Delta +0 completed/+0 total. No exit criteria were narrowed.

## Integrated behavior

The existing geometry catalog now routes five transform forms through the same
immutable append/edit/save/history/recovery lifecycle:

- Typed single-owner `cluster_op` poses, including their existing coauthored fields.
- `placement-poses`, retaining the complete explicit owner/frame/authoring contract.
- Single and batch nucleotide transforms.
- Nucleotide transform reset, with its target receipt derived from the prefix.

Normalization and reference binding reuse `part_transform_inputs` and
`part_placement_pose_commands`. The host assigns new output seeds; creation
cannot supply proof versions, history seeds, inherited host provenance or a reset
target receipt. Native placement references validate the recorded frame against
the proved prefix. Missing residue slots are diagnosed through the existing
reference adapter. No new mover, constraint solver, worker or transaction host
was added.

Single-owner poses append typed `ClusterOpLogEntry` rows; other forms retain their
existing native snapshot schemas. The additive private storage envelope admits
`nucleotide_transforms`; all source/identity/schema, proof and preserved-state
requirements remain. Storage remains distinct from proof/publication authority.
Named-group organization and linked-constraint source families are still outside
this private envelope and remain required follow-up work, not removed scope.

## Regression corrected

The first reset-retarget test failed because the adapter expanded an omitted
reset receipt into the old saved target. The existing prefix-aware editor then
correctly refused that stale explicit target. Normalization now validates inputs
while retaining which reset fields the caller actually supplied. The editor
re-derives the new target from the selected native transform. This matches the
existing ordinary history regression without weakening its mismatch check or
changing native reset semantics.

## Validation

**274 unique focused cases pass**, with no warnings in the final runs:

- Transform lifecycle (13), ordinary transform history (11), input rules (56),
  reference checks (59): **139 passed in 8.49 s**.
- Immutable scope (22), worker (23), host (37), HTTP (19), Bend/Twist (23), Sweep
  (11): **135 passed in 29.12 s**.

The initial transform/deformation run was 35 passed/1 failed in 12.63 s; its reset
retarget case passes after the correction above. No failing expectation was
removed or relaxed.

All five forms exercise append, edit through a later extrusion, independent
replay, stable feature/output identities, file save, exact-handle undo/redo and
cold recovery. Reset edits move between two distinct native transforms and
verify the new target receipt. A real subprocess workflow appends a placement
and edits its upstream extrusion. Negative cases cover missing residue/owner
references, malformed quaternions, coercible booleans, injected output seeds and
host metadata. Existing workers execute the native geometry algorithms unchanged.

Changed-file Ruff and diff checks pass. Memory lint remains at baseline six
errors/59 warnings; the project head is 200 lines. `main.js` stays 7350 lines,
delta zero. No native builder, molecular constant or golden changed.

`test-smart --dry-run` selects FULL from accumulated changes with FAST fallback;
zero broad tests ran. Literal notice (the dry run itself did not execute FAST):

```
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
Only request `just test-session` when a broad/full sweep is actually needed.
```

## Remaining requirements

**NOT VERIFIED IN APP.** Public gates remain off. This establishes private native
transform history plumbing, not arbitrary organizational-group movement,
constraint-solving coverage or scientific qualification. FH-18/FH-23 movement
cases, ISSUE-135, linked sources, named-group organization, Fine Routing,
preserved-state coverage, preview/editor integration and measured resource/
desktop acceptance remain open. Ordinary capture GC risk is unchanged.

The next integration should admit the existing organization/lineage contract and
routing parent/child history into this same host. Do not introduce a new parallel
host or treat the now-ten-checkpoint FH-28 effort as completed milestones.
Assemblies, machine-specific VR and parked assets remain deferred as agreed.

Cleanup removed 639 completed pytest entries including 97 owned
`.partcache` files (787,070 bytes). No readable same-user process referenced
them; PIDs 435/436 remained uninspectable. Pytest scratch/shared memory are empty.
User designs, existing caches and managed jobs were preserved.
