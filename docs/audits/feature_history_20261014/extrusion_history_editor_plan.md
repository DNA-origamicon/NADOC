# Ordinary extrusion history editor — U16 / FH-21

October 16, 2026. Implementation contract and closure assessment; final validation
results belong in the checkpoint evidence. This document does not change the
[fixed milestone ledger](remaining_standard_part_checkpoints.md). Final software acceptance closes FH-21;
the ledger is **19/38 complete**, with desktop/performance acceptance still open.

## Complete ordinary input controls

The native editor supports these seven top-level snapshot families. Cells are
editable row/column pairs; `separate_fresh_extrusions` is an authored control,
not an immutable implementation detail.

| Family | Editable inputs |
|---|---|
| `bundle-create` | Cells, signed length, plane, name, strand filter, lattice type, adjacent ligation, separate fresh extrusions. |
| `extrude-segment` | Cells, signed length, plane, offset, strand filter, adjacent ligation, separate fresh extrusions. |
| `extrude-continuation` | Segment inputs plus source frame and extend-in-place. |
| `extrude-deformed-continuation` | Cells, signed length, plane, source helix, optional source bp, saved grid origin/axis/right/up, separate fresh extrusions. Source-bp mode derives the frame through existing native behavior; saved-frame mode exposes its vectors. |
| `extrude-frame` | Cells, signed length, plane, name, independent translation/quaternion or source-frame/legacy-frame mode, separate fresh extrusions. Source modes require identity local pose. |
| `circle-segment` | Cells and matching positive per-cell lengths, plane, offset, strand filter, adjacent ligation, separate fresh extrusions. |
| `overhang-extrude` | Source helix/bp, direction, end, neighbor row/column, positive length, reuse-existing-helix choice. |

The form edits a private draft and retains it on refused or failed Save. It uses
the existing feature edit endpoint with explicit document, revision and feature
identity. A document reset retires the editor; late responses cannot adopt into
another document. Complete candidate geometry travels with the response, so
adoption does not fetch geometry from a later revision.

## Shared owned transaction

The implementation uses the existing publication and worker lifecycle:

- [Input normalization](../../../backend/api/part_extrusion_edit_inputs.py)
  closes the editable field inventory and uses existing native request schemas.
  `normalize(kind, previous, patch)` returns independent complete inputs.
- [Shared recording](../../../backend/api/part_ordinary_recipe_recording.py)
  serves native pattern operations and extrusion edits; the extrusion wrapper
  and [route adapter](../../../backend/api/part_extrusion_feature_route.py) do
  not create a second session, worker registry or undo system.
- The selected row must be an ordinary top-level native snapshot with strict
  proof version 1 and a stable UUID seed. `_generator` and `_generated_scope`
  rows are excluded. Unknown saved fields refuse rather than being discarded.
- Admission requires compatibility policy, the latest history cursor, exact
  source design/revision/feature identity, supported recipe contracts and an
  independently reproducible source. Protected loadout checks remain in force.
- One bounded owned capture goes to the existing isolated evaluation worker.
  It proves the original source, rebuilds the edited row and downstream recipe,
  and validates the candidate. Missing references or native failures do not
  trigger a legacy fallback or consume undo/redo.
- Final publication rechecks source/session/policy/deadline/cancellation and
  publishes once through the existing transaction. Organized candidates require
  the exact candidate-bound organized-recipe permit. Response formatting uses
  the published candidate without legacy group inference.

`history_seed`, `_proof_version`, existing transport expectations and private
source receipts cannot be changed through form fields. Stable command identity
does not promise that every topology-changing input preserves all output objects;
the unchanged native builders determine output topology from the retained seed.

## Continuation source receipt

Changing cells or source frame must not retain an obsolete `_source_helix_ids`
dependency receipt. The private `bind_prefix(kind, params, prefix)` hook runs
after proof-identity preservation and before regeneration, using the independently
proved design immediately before the selected feature. For the edited
`extrude-continuation` row only, it replaces the receipt with the sorted actual
native continuation sources; fresh cells may correctly produce an empty list.

Untouched rows are not rebound. The pinned identity helper and legacy replay
semantics are unchanged. Frame/source-helix/overhang-helix references receive
typed missing/ambiguous diagnostics at their authored input paths. Native
execution still owns occupancy, endpoint and numerical frame validation.

## Bounds and compatibility

- Existing operation admission: 256 KB, 10,000 nodes and depth 64; strict finite
  numbers and exact integer/boolean fields reject coercible malformed input.
- At most 512 unique cells and 50,000 base-pair-cell work. Circle lengths match
  cells and are positive; overhang length is positive; other supported native
  lengths are signed and nonzero. Source inventory inspection is bounded.
- Existing capture, worker transport, recovery and publication limits remain.
  The five-second host budget covers capture/proof/publication, **not** subsequent
  response geometry formatting or end-to-end browser latency.
- Existing saved rows keep their meaning. The new owned path is selected by
  explicit editor expectations or active organization; unrelated legacy editors
  retain their existing contracts.
- The organization rollout gate remains **false**. Ordinary legacy sources can
  use the owned editor without enabling organization. Organized acceptance tests
  may enable the gate explicitly; this is not production rollout.
- Organized overhang coverage edits an eligible overhang feature authored before
  conversion. It does not admit new overhang creation after conversion.
- No molecular calculations, pinned source manifests, model schemas or numerical
  policy changes are part of this editor implementation. Assemblies and VR
  validation remain outside this checkpoint.

## Acceptance and remaining work

FH-21's fixed exit is: “eligible earlier edits through downstream features,
stable identities, complete ordinary controls and validation.” The implemented
boundary addresses that exit without reducing it to length-only controls or
latest-feature-only edits. Final software acceptance passed **401 distinct backend cases** and **8,874
frontend tests / one existing skip across 748 files**. The seven-family route
matrix covers poisoned/evicted recovery, later-feature rebuild, exact identities,
undo/redo and cold reload proof. Eleven source-context cases additionally cover
changed continuation cells/frame, explicit frame pose geometry, typed missing
source refusal, broken downstream nick dependency and real spawned transport.
Source-bound frontend integration covers exact guards, complete response adoption,
no follow-up GET, no protected retry and retained/retired drafts.

See [the checkpoint evidence](validation_extrusion_history_editor.json) for red
runs, corrected expectations, final scopes and limits. This satisfies FH-21's
fixed implementation exit; it does not close the qualification work below.

Actual desktop workflows and representative latency/memory measurements remain
FH-27 work. No Archive-backed app qualification was performed for this plan.
Existing capture/undo cost and response geometry work are not qualified merely
by keeping their bounds. Gate enablement and any proven-unused legacy cleanup
need their existing acceptance process; tests or documentation alone earn no
additional milestone credit.

FH-18 remains open independently. Arbitrary new named-group movement cannot be
implemented by assigning an existing placement or applying a delta once to each
overlapping placement: placement order, deformation arm/frame selection and
extended-domain handling affect the result. That work requires an explicit
visible motion contract and demonstrated native geometry equivalence before
molecular changes. Remaining generated/branch/section consumers also retain
their declared obligations. This editor neither implements nor removes those
exits, and this plan adds no completion credit for their audit.
