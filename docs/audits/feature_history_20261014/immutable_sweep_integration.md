# Sweep integration and remaining core-tool adapters — U52

**21/38 milestones complete; 17 remaining (8 core, 9 parked).** U52 is engineering
checkpoint 52 since B1; FH-28 remains open after eight checkpoints, task-growth
flagged. Delta +0 completed/+0 total; the original exits remain unchanged.

## Integrated behavior

A small closed geometry-input adapter now selects the existing extrusion and
Sweep normalization/reference-binding contracts. The immutable worker, host,
HTTP endpoints and append evaluator use this adapter. Sweep creation receives a
host-generated stable sweep identity. Edits retain that identity; references are
resolved on the independently rebuilt prefix. Full source proof, suffix rebuild,
append candidate proof and publication guards remain in their existing owners.

Storage admission now includes native Sweep snapshots and the `deformations`
authoring field needed by their native spline overlay. The existing private
`native_extrusion_v1` label is retained for byte/storage compatibility: this is an
explicit additive catalog admission, not a new saved format or reinterpretation
of old extrusion inputs. No file migration or tag-driven proof is introduced.
The gate remains disabled. The original source envelope, absent import tables,
no generated scopes, preserved-state checks and bounded history remain intact.
Sweep admission requires a native proof version and stable UUID; actual geometry
and full command semantics are still independently evaluated, never inferred
from a storage seal. Registered batch scope remains separate.

No new worker, queue, transaction host or geometry builder was added. Existing
Sweep spline, attachment, loop/skip and scientific algorithms are unchanged.

## Remaining core-tool map

| Tool | Existing implementation to reuse | Required host integration |
|---|---|---|
| Extrude | `part_extrusion_edit_inputs`, native builders | Seven-family append/edit implemented privately; full editor, preserved-state and desktop/resource qualification remain. |
| Sweep | `part_sweep_preview.normalize` / `_source`, native command replay | Snapshot append/edit now integrated privately, including attached start/end and downstream extrusion. Existing preview/UI still needs immutable-host wiring and qualification. |
| Bend/Twist | `part_deformation_preview`, `DeformationLogEntry`, overlay command input/edit helpers | Admit and bind typed deformation entries; preserve operation identity and native target inputs; connect creation/edit/preview to the shared host. Named-group recipes need their existing organization/lineage contract admitted too. |
| Move/Rotate | `part_transform_inputs.normalize`, `edit_transform_entry`, owned preview/computation | Bind typed `ClusterOpLogEntry` and reviewed placement snapshots; preserve full pose/member inputs. Existing arbitrary new-group movement and ISSUE-135 qualification remain unresolved, not made valid by storage admission. |
| Fine Routing | `part_routing_edit_inputs`, `part_routing_edit_evaluation`, prefix inventory | Bind exact routing parent/child identities and allocate new output slots in the host; preserve ordered add/remove/reorder and original-source proof. Storage must count parent and child rows and admit each reviewed authoring field. |

Typed and nested entries must not be coerced into snapshot-only inputs simply to
fit this first adapter. Keep one shared lifecycle, with tool-specific selection
and normalization. Full dependency repair and public automation remain FH-26/
FH-29; this table does not silently close those exits.

## Validation and responsiveness finding

**133 unique focused cases have passing results.**

- Initial 10 Sweep + 22 scope tests: 31 passed/1 failed. A fresh-worker upstream
  edit exceeded the unchanged 25 ms capture budget.
- After correcting storage admission: 73 passed in 23.97 s across Sweep (10),
  scope (22), geometry worker (23) and extrusion append (18).
- Final Sweep (11), fast append (17), existing Sweep preview (40), geometry HTTP
  (19): 87 passed/1 deselected in 12.12 s; no per-test budget violations.
- The exact slow full lifecycle passed separately via
  `just test-focused tests/test_part_immutable_geometry_append.py -m slow`:
  1 passed/17 deselected in 8.11 s, 5.19 s call time.

The initial storage check called the Sweep editor normalizer while inside the
worker's capture deadline, introducing a cold editor import there. It now uses
only lightweight UUID/version admission and leaves semantic checks to evaluation.
A regression test forbids editor normalization during storage admission. Fresh
worker creation/upstream editing passes after this correction; no limit was
raised and this does not establish general interactive latency.

New lifecycle cases cover standalone and attached Sweep at either source end,
Sweep edits through a later extrusion, stable sweep/feature identities, exact
file recovery, undo/redo, poisoned recovery bytes, missing-source diagnostics,
protected inputs, coercible booleans and invalid coordinates. A real subprocess
workflow builds Sweep then edits an earlier extrusion. No visual/scientific
qualification is inferred from these software tests.

The repository `triage-slow-tests` skill classified the full four-process
extrusion lifecycle after its 5.31 s budget violation. Only that named case moves
to the existing slow/headless registry; source selection routes geometry changes
to headless debt. It was run explicitly after classification. Thresholds/guards
and test expectations are unchanged. No broad fast sweep was run; the relevant focused fast run had no budget
violations. Broader regression debt remains explicit below.

Changed-file Ruff and whitespace checks pass. Memory lint retains baseline six
errors/59 warnings; the project head remains 200 lines. `main.js` remains 7350
lines, delta zero. No molecular constants, native builders, locks or goldens changed.

`test-smart --dry-run` selects FULL from accumulated changes and FAST fallback;
zero broad tests ran. Literal notice (the dry run did not execute FAST):

```
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
Only request `just test-session` when a broad/full sweep is actually needed.
```

**NOT VERIFIED IN APP.** Public gates remain off. Full preserved state, editor
wiring, typed core tools, near-limit latency/memory, desktop and broad regression
acceptance remain open. Ordinary mutable capture's GC issue is not resolved by
this cold-import correction. Assemblies, machine-specific VR and parked assets
remain deferred as agreed.

Cleanup removed 414 completed pytest entries including 72 owned
`.partcache` files (504,779 bytes). No readable same-user process referenced
them; PIDs 435/436 remained uninspectable. Pytest scratch/shared memory are empty.
User designs, existing caches and managed jobs were preserved.
