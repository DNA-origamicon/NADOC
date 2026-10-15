# Saved part repair proposals

`GET /api/design/features/repair-draft` retrieves the current bounded proposal.
`POST /api/design/features/repair-draft` creates, updates, explicitly rebases or
discards it. Both use the normal `X-NADOC-Doc` document context. Assemblies are
outside this API's scope.

Every mutation requires `draft_version: 1`, `expected_design_id`,
`expected_revision`, `expected_draft_id` and `expected_generation`. Creation
requires the last two to be null; the server allocates the draft ID and starts
generation zero. Update/rebase retain the ID and increment its generation.
Create/update supply the existing typed repair `actions`. Rebase optionally
supplies replacement actions; without them, the saved original-value
expectations must still hold. Discard supplies no actions. Client-provided
readiness, candidate geometry, source blobs and draft IDs are rejected.

```json
{
  "draft_version": 1,
  "operation": "create",
  "expected_design_id": "part-id",
  "expected_revision": 42,
  "expected_draft_id": null,
  "expected_generation": null,
  "actions": [{
    "action": "set_input",
    "feature_id": "resize-feature-id",
    "parameter_path": ["nanoparticle_id"],
    "expected_old": "missing-particle-id",
    "value": "existing-particle-id"
  }]
}
```

The response contains `design_id`, the assigned `revision`, the full `draft`,
and a compact `repair_draft` summary. Its `pending` / `unchecked` status is not
a proof result. Ordinary geometry responses expose only that compact summary;
the explicit GET is how an editor retrieves actions. GET neither hashes the
base nor runs a builder. Protected simulation loadouts allow inspection but
reject proposal mutations with the existing read-only branch conflict.

Mutations capture only bounded definitions and named source records under the
document lock. Fingerprinting and schema checks run after releasing it. The
final publication compares session/source identity, document context, Design
ID, revision and draft generation. Closing/reopening the document also
invalidates preparation. Publication assigns one revision for autosave and
client ordering without copying geometry, adding a feature row or creating an
undo entry. Failures restore the exact source and request revision markers.

Definition/source changes require explicit rebase; rebase never guesses a new
`expected_old` value. Discard only reads proposal metadata, so oversized or
broken geometry/history cannot prevent it. Capture/structure refusals return
413; stale base or identity conflicts return 409; invalid actions return 422
with structured feature/path diagnostics. No limit is increased on retry.

Whole-document persistence retains drafts. Within one part/loadout, geometry
undo preserves the current proposal, including its explicit removal. Navigating
between parts/loadouts restores the destination proposal. Per-feature recovery
and reproducibility inputs exclude drafts. See the
[document boundary audit](audits/feature_history_20261014/draft_document_boundary.md).

## Evaluate and apply a saved proposal

`POST /api/design/features/repair-draft/evaluate` accepts only the saved proposal
guards, without replacement actions or candidate output:

```json
{
  "draft_version": 1,
  "expected_design_id": "part-id",
  "expected_revision": 43,
  "expected_draft_id": "server-assigned-proposal-id",
  "expected_generation": 0
}
```

The host checks the saved published-base fingerprint outside the state lock,
then starts the existing isolated repair job with the stored actions. A changed
part/root/feature definition or published source requires explicit rebase.
No old expectation is replaced automatically. A close/reopen or intervening
edit between fingerprinting and worker capture rejects before copying geometry.

The 202 response contains the existing `job_id`, status, source revision and
deadline, plus `repair_draft: {draft_id, generation}`. Use the existing
`/api/design/features/evaluation/jobs/{job_id}` GET/DELETE and `/commit` POST.
Polling exposes compact diagnostics; the candidate stays private. Commit
publishes once with one geometry undo entry and retains the saved proposal.
The changed recipe makes the old proposal base stale, so evaluating again
requires explicit rebase. Discard remains a separate metadata operation.
Neither a matching fingerprint nor a saved `pending` proposal is a proof.

## Stage or restore original source bytes

Source mutation is separate from draft-action JSON, whose existing 256 KB/
10,000-node limit is unchanged:

| Endpoint | Input / effect |
| --- | --- |
| `POST /api/design/features/repair-draft/source/inspect` | Explicit named source selection; returns an exact prior-byte receipt without mutation |
| `POST /api/design/features/repair-draft/source` | Original `application/octet-stream` bytes; metadata from inspection in `X-NADOC-Repair-Source` |

Inspection requires `source_repair_version:1`, `operation`, the same four
expected part/revision/draft/generation guards, `feature_id`, optional `child_id`,
the source `parameter` name and exact `source` descriptor from that command.
The two operations have different authority:

- `stage_proposed`: the saved draft must explicitly select that descriptor in
  a known native input. If the digest appears in any published feature, use
  `restore_published` instead; staging cannot silently heal published evidence.
- `restore_published`: select the published binding explicitly. The upload must
  match the descriptor's original byte length and SHA. A different file needs
  a new descriptor in an explicit draft input edit, not replacement under the
  old digest.

The inspection response adds `expected_blob` identifying missing bytes or the
exact existing encoded string's size/hash, including corruption. Send that
complete response as ASCII JSON in the upload header (at most 8,192 bytes),
alongside the original raw file. Content-Length, if supplied, must match the
descriptor. Compression and multipart uploads are unsupported here. One upload
is admitted at a time; its read deadline is 15 seconds. Busy requests are not
queued. Identical existing bytes return `source_unchanged` without a revision.

Uploads have a global 350,000-byte ceiling and retain each command's smaller
format/size contract: protein 250 KB, aptamer 150 KB, caDNAno 100 KB, quantum-dot
catalog 65,536 bytes, coating coverage 4,096 bytes. Coating PDB still requires
the exact pinned complete 1STP source. Existing source-table count/cumulative
encoded-byte limits also apply. Unknown commands and arbitrary stored model
output cannot become native construction through this endpoint.

Successful source mutation adds one revision without a feature row or geometry
undo entry. The proposal/base/generation remains unchanged. Published-source
restoration reports `base_status:"rebase_required"`; proposed-only staging
does not change the published base. Regeneration and commit are still explicit.
Protected branches allow inspection and refuse source mutation/evaluation.

See the [source contract](audits/feature_history_20261014/repair_source_staging.md)
and [evaluation audit](audits/feature_history_20261014/draft_evaluation.md) for
ownership, budget and regression-test boundaries. Replacement-picker UI and
on-demand visual comparison remain separate work.
