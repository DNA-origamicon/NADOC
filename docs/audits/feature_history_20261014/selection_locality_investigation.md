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
