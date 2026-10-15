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
| `POST /api/design/features/evaluation/jobs` | Evaluate `verify`, `append`, `edit` or `delete` |
| `GET /api/design/features/evaluation/jobs/{job_id}` | Poll compact status/diagnostics; candidate bytes stay private |
| `DELETE /api/design/features/evaluation/jobs/{job_id}` | Cancel and discard a publishable candidate |
| `POST /api/design/features/evaluation/jobs/{job_id}/commit` | Publish the exact evaluated candidate once |

For example, start verification with `{"operation":"verify"}`. An edit supplies
`operation`, feature `index`, optional routing `sub_index` and partial `params`.
A delete supplies the index and optional `cascade`. Delete analysis can return a
preview requiring a separate request with `cascade:true`. Ordinary edits still
require the existing source to reproduce; repair of broken definitions is P5.

`expected_revision` is optional at start. Every result is bound internally to the
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

## CPD source and execution contract

Append currently supports `photoproduct-create` and `photoproduct-relax`.
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
