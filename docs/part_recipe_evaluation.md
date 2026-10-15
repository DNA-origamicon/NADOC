# Standard-part recipe evaluation

Native part recipes execute registered feature inputs from an explicit empty or
imported root. Recovery snapshots and diffs serve undo/scrubbing; they are never
inputs to proof, regeneration or native CPD placement. Assemblies are separate.

Reproducibility is distinct from reference integrity, scientific validation,
editable construction and physical-result freshness. A reproduced imported
basis does not become native editable construction. Missing references, output
mismatches, unsupported contracts, unavailable engines and resource limits have
different diagnostics.

## Ordinary and long operations

Ordinary verification jobs have a five-second deadline. Synchronous checks and
recipe edits retain their existing cooperative limits. Neither rendering nor
history scrubbing starts proof work. Expensive numerical evaluation uses an
explicit spawned job with a 180-second deadline, single-thread numerical runtime
and shared admission with ordinary checks. Cancellation terminates/reaps the
child before another worker can run. Busy document locks do not prevent the
supervisor from observing cancellation or its deadline.

The long-job API is available before the repair UI:

| Request | Purpose |
|---|---|
| `POST /api/design/features/evaluation/jobs` | Evaluate `verify`, `append`, `edit`, `delete`, `repair` or a nonpublishing `selection` |
| `GET /api/design/features/evaluation/jobs/{job_id}` | Poll compact status/diagnostics; candidate bytes stay private |
| `DELETE /api/design/features/evaluation/jobs/{job_id}` | Cancel and discard a publishable candidate |
| `POST /api/design/features/evaluation/jobs/{job_id}/commit` | Publish the exact evaluated candidate once |

For example, start verification with `{"operation":"verify"}`. An edit supplies
`operation`, feature `index`, optional routing `sub_index` and partial `params`.
A delete supplies the index and optional `cascade`. Delete analysis can return a
preview requiring a separate request with `cascade:true`. Ordinary edits still
require the existing source to reproduce. Explicit repair can rebuild broken definitions.

`expected_revision` is optional for ordinary jobs; repair and selection require both document
identity and revision in their nested requests. Every result is bound internally to the
captured document session, exact source object and revision. A ready result is
not automatically installed. Commit rechecks those identities, cancellation,
expiry and exact authoring after transport decoding, then publishes one undoable
operation. Repeated commit returns its original committed revision. It never
reruns the solver. Presentation and physical fields are preserved from the
unchanged live source, without certifying physical freshness.

Captured input is capped at 2 MB/30,000 visited nodes with a cooperative 25 ms
capture allowance. Operation inputs are capped at 256 KB/10,000 nodes; regenerated
recovery has an 8 MB cumulative encoding-work allowance, including discarded
cascade attempts. Candidate transport is capped at 16 MB. At most two long jobs
are retained, and uncommitted results expire after 15 minutes. These are input,
work and transport bounds, not a hard process-heap guarantee. Oversized work is
unverified or rejected without publication; interaction limits are not enlarged.

## Coating append qualification

The strict `kind:"streptavidin-coating"` append schema and worker compiler are
implemented, but public submission currently returns
`coating_append_unavailable`. A server-owned gate remains closed pending capture
performance qualification. Existing explicit verification, edit and repair jobs
are unchanged. Ordinary nanoparticle routes and drag handlers do not use this
append path.

The request requires an outer `expected_revision` and input-only `params`:

```json
{
  "operation": "append",
  "kind": "streptavidin-coating",
  "expected_revision": 12,
  "params": {
    "action": "create",
    "diameter_nm": 20,
    "coating": {"mode": "adsorption", "count_override": 1, "seed": 1}
  }
}
```

| Action | Inputs and resulting feature definitions |
|---|---|
| `create` | Diameter and optional `coating` settings; gold-create followed by coating-set |
| `set` | `nanoparticle_id`, optional `coating` settings and optional replacement diameter; coating-set |
| `repack` | Target and required diameter; coating-set preserving the active set feature's recorded settings and source descriptors |
| `move` | Target and explicit `pose` and/or `gizmo_move`; coating-move using existing native precedence |
| `remove` | Target with an active coating; coating-remove |
| `delete` | Target; coating-remove followed by gold-delete, or one gold-delete when already uncoated |

Settings retain native defaults: adsorption, 40 nm² footprint, seed 1, no count
override or publication selection, and spacer 0.3 nm for adsorption or 4 nm for
biotin tethering. The compiler records resolved defaults. Requested sites are
limited to 64 without silently reducing the count. Public inputs cannot contain
engine/version pins, source bytes, filesystem paths, URLs, output identities or
sampled geometry. The host derives stable feature and new particle identities;
the scientific random seed remains a separate authored choice.

The existing recipe must independently reproduce before any new source is read
or merged. New `create`/`set` preparation reads the fixed verified PDB and optional
bounded publication JSON inside the existing worker, outside document locks.
Publication bytes are selected and pinned at evaluation time, and commit retains
that exact evaluated closure. Repack uses the prior feature's pinned sources;
motion, removal, deletion and historical replay never reread installed assets.
Appending cannot repair missing old bytes or silently upgrade an old engine.

All new steps share one prefix replay, cumulative recovery budget, candidate and
undoable commit. A failed second step cannot publish the first. Polling includes
only compact `append` metadata (action, feature IDs and particle ID), alongside
the normal validation result; candidate geometry stays private.

Qualification is limited to an explicit empty root, zero or one unowned gold
particle, at most 32 flat gold/coating definitions, and default physical and
presentation state. Its fixed server capture profile is 100,000 nodes/4 MB with
a cooperative 100 ms allowance; ordinary 30,000-node/2 MB/25 ms capture,
2 MB worker input, 256 KB operation input and recovery/candidate limits are
unchanged. Initial live qualification refused 14 of 120 active-coating captures
and measured capture-lock p95 of 111–118 ms (maximum 133 ms). The timer is not a
hard latency ceiling. This evidence keeps public append disabled while capture
cost is addressed, rather than increasing the allowance.

## Explicit repair

Repair addresses a stable feature ID, an optional routing-child ID and an exact
existing input path. For example, replace a missing particle selection:

```json
{
  "operation": "repair",
  "repair": {
    "repair_version": 1,
    "expected_design_id": "current-part-id",
    "expected_revision": 12,
    "actions": [{
      "action": "set_input",
      "feature_id": "dependent-feature-id",
      "parameter_path": ["nanoparticle_id"],
      "expected_old": "missing-particle-id",
      "value": "replacement-particle-id"
    }]
  }
}
```

The replacement must exist in the independently rebuilt prefix at that feature.
Objects visible only in the saved model or produced by later rows cannot satisfy
the selection. Up to 64 actions may patch nonoverlapping paths, each at most 16
tokens deep. Output IDs, versions, identity namespaces and closed generated
scopes remain protected. This version edits snapshot definitions or explicitly
selected routing children; unchanged overlay features replay normally.

Repair starts from the declared root and never reads saved recovery as input.
A failed result includes the first failure, successfully executed prefix and
later rows as `not_evaluated`; it contains no partial publishable candidate.
A ready result reports changed authored fields/counts relative to the captured
materialized state, explicitly without claiming that prior state was verified.
The normal explicit job commit publishes once and is undoable.

`upgrade_numerical_contract` is a separate action for native CPD v1, native
duplex relaxation v1 or native streptavidin packing v1. Supply the stable target and its exact `expected_engine`
(plus `expected_template` for CPD). The server selects current pins within the
same recognized family, rebuilds the complete recipe and reports old/new pins.
It never certifies the older engine's output or silently refreshes ordinary edits.

Repair drafts, replacement picker UI and on-demand visual comparison remain
pending. Current job results expire after 15 minutes. The changed-field/count
summary is neither a geometry preview nor scientific qualification.

## Replacement reference selection

The same job endpoint can suggest references from the independently rebuilt
state immediately before a selected feature:

```json
{
  "operation": "selection",
  "selection": {
    "selection_version": 1,
    "expected_design_id": "current-part-id",
    "expected_revision": 12,
    "feature_id": "dependent-feature-id",
    "parameter_path": ["nanoparticle_id"],
    "expected_old": "missing-particle-id",
    "limit": 100
  }
}
```

The request requires an exact current reference value and stable feature ID;
array indices are integer path tokens, for example `["protein_ids", 0]`.
An optional outer `expected_revision` must agree with the nested value. The
server checks the captured part and revision before submission and again inside
the worker. It does not require proof of the old displayed state. Saved recovery
and objects created after the target feature do not supply replacement choices.

Successful polling returns `result.status: "preview"` and `result.selection`
with `resource_kind`, `candidates`, `eligible_count`, `limit`, and `truncated`.
Each descriptor contains only `kind`, `identity`, and a bounded `label`; at most
100 are returned in source collection order. `completed_prefix` and
`not_evaluated` identify the evaluated boundary. Prefix failures retain the
first structured failure and return no choices.

The initial slot catalog admits unscoped undecorated gold/QD patch/delete
`nanoparticle_id`, free protein attachment `asset_id`, free protein patch/delete
`attachment_id`, and rigid copy `protein_ids`/`nanoparticle_ids` list entries.
Ownership and explicit atom references filter choices without running the target
command or a solver for each candidate. Scoped, compound, output, engine,
coating, thiol, and owned-conjugate selections remain explicitly unsupported.
The request supports a stable `child_id`, but no currently admitted selector
command is a routing-child kind; those child slots remain unsupported.

Selection is a nonpublishing preview: it returns no `Design`, geometry, candidate
or final validation. Its job cannot be committed. Use a separate explicit
`repair` action with the chosen ID to validate the complete command and recipe.
An offered reference does not guarantee that the other inputs or later features
will succeed. Stale, busy or cancelled polling hides the choice list and marks
it invalidated; request a new selection against the current revision.

Selection uses the existing job admission, cancellation, 180-second deadline,
15-minute expiry, input bounds and cumulative recovery budget. Prefix replay
currently reuses recovery encoding; avoiding that work requires a shared replay
visitor and measured evidence, not a larger interaction budget.

## CPD source and execution contract

CPD append supports `photoproduct-create` and `photoproduct-relax`; the same job
API also admits the separately pinned `duplex-relax` contract.
Conversion inputs are:

```json
{
  "operation": "append",
  "kind": "photoproduct-create",
  "params": {
    "source": {"kind": "native"},
    "base_keys": ["__xb__:crossover-id:0", "__xb__:crossover-id:1"]
  }
}
```

The host allocates feature/output identity. The worker records explicit contract
version, TT cis-syn product, qualified coordinate-template digest, audited
implementation digest and concrete single-thread numerical-runtime digest.
Relaxation uses `kind:"photoproduct-relax"`, the same source selector and an
existing `photoproduct_id`. Replay never refreshes pins or reads cached physical
coordinates. Missing targets fail before placement. Changed/unavailable code,
runtime or template produces a distinct unverified result and requires an
explicit upgrade workflow; NADOC does not yet ship old engine installations.

The initial contract admits ordinary native DNA and canonical CPD output, with
a conservative 50,000-atom source estimate. Protein/NP/overhang/linker assets and
imported physical coordinate sources require P4 provenance contracts. Existing
conversion routes/receipts without these explicit pins remain unverified; this
API does not silently reinterpret their source selection. The scientific
conversion and relaxation algorithms are unchanged.

## Generated construction

New branch, joined-section and connectivity generation records separate native
seed, numeric path, constraint, routing, Join, curvature, budget and sequencing
steps. Plans retain chosen endpoints/frames and other numeric authoring inputs;
sampled path arrays and a planner's completed Design are not recipe inputs.
Native cluster creation/placement uses ordinary overlay entries. Typed scopes
preserve user text and independent geometry, with stable output identities.

For safe terminal budget fitting, existing native trim output is accepted only
when Join anchor/bead sites, adjacent backbone sites and rigid owners remain
unchanged. Other attachment guards stay conservative. Legacy aggregate histories
remain available for recovery and explicitly unverified.

P4 asset/import contracts, P5 repair drafts/UI and P6 registered automation policy
are tracked in the [architecture review](audits/feature_history_20261014/architecture_review.md)
and its linked plans. This API alone does not enforce an agent-only trust policy.

## Current-part rigid copy

`POST /api/design/features/copy-elements` records a copy from references to the
current part. Supply the part's `design.id` and current response `revision`:

```json
{
  "expected_design_id": "current-part-id",
  "expected_revision": 12,
  "protein_ids": [],
  "nanoparticle_ids": ["source-particle-id"],
  "paste_index": 1
}
```

The host allocates new identities and returns `pasted_refs` with the ordinary
design/validation/revision response. The complete batch is one undoable feature.
An upstream source edit regenerates the copy; editing its source selection
preserves the copy's output identity. Later ordinary placement/particle features
can edit or remove the copies. A missing source is a typed dependency failure,
never a request to recover its saved coordinates.

The initial contract admits 16 elements: undecorated gold/catalog particles and
free proteins with an explicit selected atom and no owned binder. Each protein
asset is bounded at 1,000 atoms/4,000 bonds, with 4,000 selected atoms total across
placements. Whole-document capture limits apply independently. Current import
provenance remains imported when a copied object depends on an imported source.

This endpoint accepts source IDs, not a client `Design` or output identities.
Frozen clipboard paste retains its existing endpoint and snapshot semantics;
it remains unverified until a separate pinned-source contract is implemented.

## Pinned caDNAno import

`POST /api/design/features/import/cadnano` accepts the original UTF-8 caDNAno v2
JSON bytes as `application/json`. Supply required query parameters
`expected_design_id` and `expected_revision`, plus optional `name_override`.
Create a fresh empty part/tab first. This endpoint rejects retained history,
sources, presentation and physical data so its undo snapshot remains small.
The existing `/api/design/import/cadnano` upload keeps ordinary file replacement.

The new endpoint incrementally admits at most 100,000 bytes, prepares a new
empty-root recipe and one Import feature outside the state lock, then publishes
with both source-object and revision guards. It returns the full ordinary
design/validation/revision response; undo restores the empty host. No failed
native import falls back to saved output.

The initial contract supports at most 32 helices, 8,192 source array slots,
16,384 declared nucleotides, 128 strands and a conservative 512-domain bound.
Multiple module scaffolds remain unsupported. Imported topology is
`reproduced_import`, with the source bytes embedded by digest. Name edits retain
output IDs; replacing the source bytes changes their identity namespace and
requires explicit repair of downstream selections. This does not reconstruct
the external file's original design history.
