# Single-nucleotide Move/Rotate locality investigation

October 20, 2026. User contract: moving one nucleotide changes only that nucleotide.
A tail moves only when its residues are selected. Connected material must not follow
implicitly, and a stretched covalent junction does not authorize expanding selection.
This is consistent with `memory/project_nucleotide_transform.md`'s original final-pass
residue transform and explicitly allowed strained-junction contract.

## Confirmed failures and origin

| Path | Failure | Introducing history / mechanism |
|---|---|---|
| Atomistic tail transform | Selecting an anchor also matched tail atoms; selecting the tail's actual synthetic identity matched none. | `76f27284` (July 14) supplied tail anchor metadata; `a3c94e4d` (August 9, independent nucleotide transforms) treated those raw fields as residue identity. `9274776e9` was later formatting, not the origin. |
| Atomistic live preview | Ordinary anchor matching also included tail and crossover-insert aliases. | Matcher added in `a3c94e4d`; now uses canonical `atomBaseKey` identities. |
| Crossover reconstruction | Moving one endpoint rebuilt unselected inserts and adjusted linker atoms at the opposite endpoint. | Measured endpoint construction added in `08b189cc` (August 9) consumed geometry retaining residue poses. Four initial native cases moved inserts up to 0.659 nm and opposite endpoint atoms up to 0.200 nm; unchanged rebuild controls were exact. |
| Full bridge reconstruction | One individually posed anchor moved 16 unselected bridge records. | `42d6d6ce` (August 9) applied individual poses before bridge emission. |
| Atomistic bridge reconstruction | Existing virtual bridge placement consumed individually posed anchors. | `29046524` (October 6) routed the anchor through native Full placement including saved residue overrides. |
| Terminal UI gesture | An end-resize arrow stole the Move drag, called strand-end-resize, and changed selection from bp 5 to bp -54. | Capture handler in `84590b40` (March 25) deliberately intercepted before OrbitControls. The later nucleotide tool did not publish an active selection lock; resize arrows also ignored the ordinary Move/Rotate lock. |

The Full helper `abstractResidueInfo` also ignored native `copy_k`; it now preserves it.
This is a helper defect, not evidence that the current live Full renderer moved loop
copies: the live renderer uses a separate identity map.

## Why previous audits passed

- The original synthetic transform test used a neighbor at a different bp and omitted
  extension/insert alias metadata. It never challenged the identity collision.
- Insert coverage moved a selected insert rather than an anchor with unselected inserts.
- Agreement with the same native implementation cannot prove the selection contract.
- The October 16 investigation did expose the tail discrepancy as ISSUE-135. Its four
  passing characterization tests recorded the bug; they were not acceptance tests.
- More seriously, `test_bridge_uses_final_individually_transformed_anchors_once`
  explicitly expected a bridge to follow individually transformed anchors. The related
  native-anchor comment described that ordering. That test was replaced by
  `test_existing_bridge_does_not_follow_individually_transformed_anchors`.
- The earlier recommendation to make Full tails follow atomistic tails was wrong:
  avoiding a stretched bond is not the user's criterion. Representation parity must
  be checked together with exact selection locality.

There is no general project instruction authorizing unselected tails or neighbors to
follow. One separate explicit exception exists in `cpd_selection.js`: “A converted CPD
is indivisible at Base and Crossover selection levels.” It expands selection to a pair.
This is a source finding only; experimental CPD campaigns were neither run nor changed.
It must not become an implicit exception for ordinary nucleotides.

## Repair and verification

Canonical tail identity is used in native atom transforms and preview; actual tail
selection is accepted and resolved through its extension owner. Existing inserts and
bridges are reconstructed before individual residue poses. Those poses then apply once
to selected material. Prospective placement of newly created material is a separate
contract and is not claimed settled by this repair.

The nucleotide tool now publishes its active state to selection controls. End-resize
handles disappear while either Move/Rotate tool owns selection, refuse stale pointer
captures, and return when the tool closes. Activating a transform cancels an existing
end-resize drag without a resize commit.

- Native locality: 20 passing cases, including selected one/whole tails, anchor/alias
  controls, ds-bridge Move/Rotate with nonzero pivot, and both crossover endpoints with
  one/two inserts through display/default atom builders. Every unselected atom/Full
  record is compared, along with bond topology.
- Terminal rotation characterization rewritten as locality acceptance: 4 pass across
  both ends/directions. Native bridge-placement file: 28 pass.
- Related nucleotide API 17, tail audit 4, overhang 67, and reference-resolution 59 pass.
- Focused UI lock/gesture files: 141 pass. Real browser drag: 1 pass, including exact
  unselected bead positions, unchanged selected identity, bead/slab registration, and
  zero strand-end-resize requests. The test waits for successful saved Apply and the
  adopted pose, not merely a closed preview. Disposable design/session/playback paths
  and test project snapshots are absent.
- Backend test-smart decision FAST: 19228 passed, 19 skipped, 84 failed. Failure-set
  comparison found the same 83 earlier failures plus the now-corrected bridge-following
  oracle; its complete file subsequently passed. The broad suite is not green.

```
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
```

Final full frontend verification after the gesture repair: 781 files, 9432 passed,
1 skipped (352.67 seconds). Logs are under
`.development-artifacts/feature-history-focus/locality-*`.

The obsolete bridge test generated a placement-review incident. It was reviewed and
acknowledged through the normal review mechanism with native visual evidence
`locality-bridge-review.png`/`.json`/`.nadoc`; the journal and original evidence remain.
The rotated native example preserves all 131 unselected Full records, including 16
bridge residues, exactly. No placement locks, goldens, constants, or guards changed.

This does not certify every representation, VR gesture, molecular attachment, or
later-material ancestry rule. `crossover_geometry_diagnostics` still calls virtual
bridge placement with the posed design and needs separate consistency review; it is
not the atom builder or a mutation path. The full named-motion acceptance matrix and
Move/Rotate rollout gates remain open. Four of six primary tools are complete.

## Follow-up: a residue command widened an existing partial owner

The next partial/shared-frame case exposed another independent path. A legacy
placement owner covered only the forward bp 0–3 domain of a nicked 2HB. Recording
or replaying a later single-nucleotide pose ran generic topology reconciliation.
Its bp-overlap membership reconstruction ignores strand direction and added the
whole opposite strand to that already-posed owner. Eight unselected nucleotides
therefore moved, even though the residue transform itself matched correctly.

The recording path entered this generic postprocessor in `c4b98ff1` (August 9,
“Unify transform geometry and history”), when the route switched from `set_design`
to `mutate_with_feature_log`. Replay inherited unconditional reconciliation in
`a8bc9fc9` (October 15, “expand native part recipe replay and regeneration”). The
reconciler documents largest-bp-overlap membership assignment; it is a topology
repair policy, not authorization to rewrite owners during a residue pose.
Previous locality fixtures had no nontrivially posed partial owner, so this
indirect movement mechanism was absent from their controls.

Single/batch/delete residue commands now preserve topology and membership in both
recording and replay. Reference validation, dependency checks, occupancy checks,
transaction rollback and undo remain active. A first repair returned before organized-group
admission and detached lineage handling; five broad-suite regressions caught this. The final
repair skips only reconciliation/retry and retains the complete surrounding pipeline; all 16
organized-group tests pass. Native/HTTP regressions cover both
directions, replacement, deletion, undo and independent cold proof: 10 pass. The
browser test now covers both the original 2HB and a committed native partial-owner
fixture: 2 pass through saved Apply, with owner metadata and every unselected bead
unchanged. All disposable workspace/session/playback/project artifacts were absent.

Visual evidence `locality-owner-review.png` and `.json` compares native before,
old postprocessing and repaired output in the same XY/XZ coordinates. It was
inspected: old output moves 8 unselected records; repaired unselected displacement
is exactly 0 nm. The native fixture is
`frontend/e2e/fixtures/nucleotide_partial_owner.nadoc`. Final backend FAST: 19251 passed, 19 skipped, 84 failed: the same 83 retained
baseline failures plus a synchronous-verification timeout in the native branch test.
That complete branch file passed both tests in isolation. The broad suite is not green.
The selector deferred FULL to `.nadoc-slow-pending` because no test-dedicated session
was open. One real-worker readiness Apply case exceeded five seconds twice (5.21/5.23s);
only that parameter is now marked slow/headless, with collection verified. The fast
suite was not rerun after classification; aggregate timing debt remains (412s).
The earlier frontend 9432-pass result remains applicable because this follow-up changes
backend behavior and browser coverage, not frontend production code.


## Attached construction follow-up

The same ownership mechanism affects attached Sweep after a partial placement.
The direction-blind overlap policy and its explanatory comment originated in
`d8693fc45` (May 2); Sweep's reverse-site frame preference originated in
`aee9100d8` (October 8). These are separate policies: new-domain inheritance does
not justify reassigning existing, unselected domains.
The isolated candidate preserves exact surviving domain ownership, refuses split/
merge ancestry guesses, and leaves native new-material placement untouched.
Its phase review is generated by `tools/member_motion_birth_audit.py`; it is not
imported by ordinary rendering, persistence, export, or simulation. The later October 21 decision rejects attached Sweep when occupied source frames
separate; the ownership-preserving diagnostic candidate remains unpromoted.

The phase-coverage audit found a second verification gap: earlier ordering,
chronology and tail diagnostic generators varied stored `phase_offset` on lattice
helices, but canonical lattice preparation re-derived that value. Comparing all
artifact atom arrays confirmed one unique geometry per direction/control case,
not36 phases. Their index pages now explicitly withdraw phase-coverage claims;
the individual counterexamples and the user's selected-only decision remain valid.
The corrected shared diagnostic helper uses an authored native axial rotation and
checks evaluated coordinates against an independent rigid oracle. No locked phase
constant or production geometry code changes.


## Explicit unpairing exploration — October 21, 2026
- Handoff audit: `f87cffc9` correctly supersedes earlier next tasks; `57b1f613` contains attached-Sweep refusal, and `TRANSFORM_HISTORY_EDITOR_ENABLED` remains false. The memory head's open-C8/stop-loss claims are historical, not current instructions. Latest unrelated commit `a1eae56c` does not change these conclusions.
- Native pairing is inferred from opposite occupied `(helix, bp, direction, copy)` slots in `mrdna_bridge._build_nt_arrays`; `Domain` has no ordinary-pair exclusion field. `flexible_segments.unpaired_bead_keys` also infers occupancy and does not implement unpairing. An individual pose leaves pairing intact.
- `tools/unpair_topology_probe.py` removes symmetric pair edges only in a detached array and reports affected native chains. It returns no Design, coordinates, simulation seed or apply operation. Native indices are capture-local; they are not persistent IDs.
- Both former partners become unpaired; only explicitly selected residues remain selected. Maximal resulting ssDNA runs have zero paired flanks (free strand), one (overhang), or two (linker, including same-body loops). Adjacent pre-existing ssDNA joins the run without joining the movement selection.
- Identity, authored bases, backbone order, positions and orientations remain exact in the native controls. No nick, ligation, sequence reassignment, new nucleotide, overhang conversion or automatic relaxation is implied. Already-unpaired selection is a no-op; stale/empty selection refuses.
- Native array enumeration is reused, including its metadata, rather than inventing strand traversal. Explicit overhang pairing and forced ligations refuse pending a complete inventory; special insert/copy/tail and cross-domain unpair qualification remains open. Ordinary two-direction terminal/interior cases are covered.
- Representation choice remains open: pair-edge exclusions preserve existing native keys but require every pairing consumer to honor them; moving domains onto synthetic helices reuses occupancy semantics but changes keys, frames and downstream references. Neither choice is implemented in production by this probe.
- Movement must continue to use explicit residue membership. A two-ended linker retains both covalent junctions; its classification alone is not permission to move its anchors, relax geometry, create a constraint, or expand a named group. Free/one-ended runs similarly do not authorize moving former partners.
- Reattachment must be a separate explicit operation with resolved target identities/register, pair exclusivity and sequence reporting. Restoring a pair edge does not align displaced atoms or repair stretched backbone bonds; any such placement requires the isolated A/B authorization workflow.
- History integration requires one source-bound command on the existing host, native prefix identity resolution, symmetric pair-state replay, downstream reference failure attribution, one undo, exact Cancel and cold save/reopen proof. Suppression/reorder must re-evaluate at the proposed prefix. No new host or saved pose authority is needed for this exploration.
- Export assessment: oxDNA `topology_rows` stores strand/base/n3/n5, not a Watson–Crick partner column; unpairing must preserve those rows, while seed generation and complementarity reporting need explicit pair-state support. mrDNA explicitly consumes the partner array. Atomistic placement and CAD exports need separate representation/round-trip qualification; no export capability is claimed here.
- Existing native birth A/B JSON was inspected for invariants/junction evidence, not visually requalified: `phase-000-forward-end.json` retains all bonds/new atoms but displaces 160 atoms when restoring old ownership. That is an attached-construction counterexample, not evidence for any unpair placement. No new geometry candidate or phase sweep was generated.
- Validation: `just test-focused tests/test_unpair_topology_probe.py` — 14 passed; targeted Ruff and `git diff --check` pass. Diagnostic-only change: no production/backend/frontend behavior or `main.js` LOC change; no browser artifacts or simulation launched. Broad baseline debt remains as recorded in the handoff.


### User-directed staple relocation — October 21, 2026
- New instruction resolves representation direction: scaffold stays on its creation helix; staple is assigned a newly generated lattice location at matching bp indices after manual separation. This supersedes the earlier open pair-exclusion versus helix-relocation choice.
- Added `staple_relocation_inventory` in the isolated probe: deterministic destination identity by source helix/staple, preserved bp/direction/copy, scaffold retained even when it was the moved partner. No geometric placement or persisted topology is produced yet.
- Seven native tests pass: either moved partner, loop-copy identity/register, input-order determinism, and refusal for unsupported same-role/linker/binder pairs. Targeted Ruff passes.
- At this earlier probe checkpoint, user choices were pending (resolved by the next section): relocate only separated segments versus entire staple; preserve exact moved geometry versus snap to an original-lattice cell; automatic Move Apply versus explicit Unpair. These change domain/reference rewrites and placement behavior, so dependent mutation code waits.
- Same-role pairs remain explicit refusals pending a future rule; no scaffold/staple role is guessed from strand direction. Existing production behavior is unchanged.


### Cadnano-only reclassification contract and implementation — October 21, 2026
- User clarified: move only the separated staple segment to a new **cadnano layout** location, retaining bp indices and exact moved 3D geometry. The scaffold keeps its creation helix. A partial detached staple segment becomes an overhang. Move Apply must offer Cancel/Continue before committing.
- `backend/core/unpair_reclassification.py` reuses the virtual-linker cell allocator and dedicated-overhang stored-pose mechanism. It copies the evaluated rest axis/phase, splits selected domain ranges, retains strand/sequence/backbone, remaps residue poses and placement-domain indices, and preserves destination cell parity. It does not bake displayed or simulated coordinates into topology.
- The first reference-remapping matrix exposed dormant domain references whose helices were absent from their placement owner's helix list. Adding those helices would have applied an extra pose. The builder now preserves the original effective owner scope. Twelve direction/terminal/interior/whole-domain/owner cases preserve Full frames, atom coordinates and bonds within 1e-12 nm.
- Authored affine residue poses determine separation; equal transforms on both partners remain duplex. The rule is symmetric with respect to which partner was moved, but only the staple changes address. Already-unpaired material does not create another row. Special copy/domain consumers that cannot yet be remapped refuse explicitly.
- The read-only batch reclassification check returns a confirmation fingerprint bound to the exact design and Move inputs. Continue rechecks it inside the existing feature transaction and records reclassification in the same command. Cancel writes nothing. One undo restores both pose and topology. No new host, lease, storage format or molecular placement rule is introduced.
- Desktop nucleotide/domain/strand Move and its VR residue confirmation call the shared popup. Existing cluster/named-member and owned history Move integration remain separate work; this slice does not claim those paths reclassify.
- Current admission is deliberately limited to ordinary, undecorated domains with supported owners: deformations, crossovers/forced ligations, extensions, explicit duplex bindings, flexible marks, CPD and organized groups refuse reclassification. Loop/skip domains refuse, including individually selected loop copies. No silent fallback commits a separated duplex when that check fails.
- Native HTTP tests: 8 pass, covering read-only check, either moved partner, common duplex motion, stale source/input refusal, undo/redo, serialized reload/cold proof and unsupported-owner/copy refusal. Geometry matrix: 12 pass; earlier probes: 21 pass. Entirely detached staples use existing auxiliary endpoints for free ssDNA; custom labels remain intact. Independently posed domain owners refuse because residue affines alone cannot establish pairing.
- Browser: 1 pass through a real gizmo drag, exact Cancel, selected live delta/unselected geometry preservation, one feature, matching bp/new cadnano row, save/reopen and verified cold proof. Both 3D and cadnano screenshots were inspected; the third cadnano row is visible. The initial reopen mismatch was fixture-only: its renamed metadata was outside native history; creating the named native root fixes the fixture and an initial proof assertion prevents recurrence. Scratch roots `5py79zzv` and earlier failed `4f2zjhgu` independently absent.
- Full frontend: 786 files, 9452 passed, 1 skipped. Backend FAST: 19358 passed, 19 skipped, 83 failures with exactly the same failed node IDs as the preceding baseline; aggregate 405s exceeded the guard, with no individual slow-test violators. The triage-slow-tests skill found no justified test reclassification. FULL remains deferred per handoff. Final targeted Ruff and diff whitespace checks pass; `main.js` LOC delta is zero. Logs and reviewed screenshots: `.development-artifacts/feature-history-focus/unpair-*`. No transform gate or completion count changed.

- Final general app smoke: 23 passed (2.5m); disposable `/tmp/__e2e__smoke-_5ew1_du` independently verified absent. All application fixture roots and saved review documents were cleaned.
