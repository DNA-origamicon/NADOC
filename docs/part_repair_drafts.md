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

Source staging and draft-bound evaluation/apply are the next integration
steps. Existing explicit repair jobs remain available, but this metadata API
does not itself rebuild geometry or certify that a proposal can be applied.
