# Registered part batches

The first batch adapter is implemented behind the server-owned
`REGISTERED_BATCH_ENABLED = False` qualification gate. Public submission returns
HTTP 422 with `registered_batch_unavailable` until the complete job lifecycle has
passed its performance qualification. Requests cannot override this gate. This
checkpoint adds no frontend flow, document policy, baseline cache or OS sandbox.

Once admitted, a batch uses the existing
`POST /api/design/features/evaluation/jobs` endpoint and its existing poll,
cancel and commit endpoints. For example:

```json
{
  "operation": "batch",
  "batch": {
    "batch_version": 1,
    "expected_design_id": "the-current-part-id",
    "expected_revision": 42,
    "commands": [
      {
        "kind": "nanoparticle-create",
        "version": 1,
        "label": "Gold support",
        "params": {
          "nanoparticle_id": "00000000-0000-0000-0000-000000000004",
          "diameter_nm": 10.0
        }
      },
      {
        "kind": "nanoparticle-patch",
        "version": 1,
        "params": {
          "nanoparticle_id": "00000000-0000-0000-0000-000000000004",
          "diameter_nm": 12.0
        }
      }
    ]
  }
}
```

The nested part ID and revision are required. An optional outer
`expected_revision` must agree. The host checks both against the live source
before capture and again against the worker's trusted capture header. Active
document selection still uses `X-NADOC-Doc`.

## Initial command catalog

| Kind | Authored controls | Normal history form |
| --- | --- | --- |
| `helix-add` | Explicit helix UUID, endpoints, base-pair length, phase | Routing child |
| `strand-add` | Explicit strand UUID, indexed domains, scaffold/staple type, optional sequence | Routing child |
| `nanoparticle-create` | Explicit particle UUID and uncoated gold diameter | Snapshot feature |
| `nanoparticle-patch` | Uncoated gold target, diameter and/or native gizmo move | Snapshot feature |
| `nanoparticle-delete` | Uncoated gold target | Snapshot feature |
| `cluster_create` | Explicit cluster UUID, name, whole-helix members | Native grouping feature |
| `cluster_op` | Existing cluster, translation, rotation, pivot | Native pose feature |

Grouping rejects duplicate or conflicting ownership. Pose accepts uniquely
resolved existing clusters, including domain-scoped clusters, and changes no
membership. Optional feature labels apply to snapshot and routing-child kinds;
grouping/pose use their existing cluster names and reject a separate label.

Producer UUIDs are explicit typed declarations, so later commands can reference
earlier outputs without recursive aliases. The host creates stable feature and
child IDs and proof markers. Inputs cannot supply complete designs, recovery
snapshots, diffs, executable code, private generated scopes, sampled sweep
geometry, imported assets or numerical solver payloads. This is an explicit
public allowlist, not every command in the internal replay registry.

## Evaluation and publication

The worker proves the captured source once, then executes the ordered commands
through the existing registry. It builds ordinary editable rows and their
recovery data with the existing regeneration mechanism. A command failure
returns its stable feature/child IDs and command index, completed commands and
later commands not evaluated. No partially completed candidate is publishable.
Unsupported or unreproducible source histories remain rejected; imported roots
retain their distinct `reproduced_import` basis. The ordinary executor still
refuses prefixes requiring a separately admitted long native operation.

A ready result contains validation, source assessment and bounded authoring
field/count changes. `batch.candidate_replay_verified` remains `false`: the new
candidate was composed by registered commands and has not received an additional
independent cold replay. Validation and reproducibility are separate results;
neither is a scientific qualification or visual approval. Cold replay remains
an independent regression oracle.

Polling omits the candidate and recovery bytes. Commit checks the host-admitted
operation, source object, revision, expiry and exact decoded authoring/recipe
content. It publishes the retained candidate once, creating one undo entry for
the entire batch. Commit performs no solver or source-proof repeat. Cancellation,
reload, an intervening edit or an expired result prevents publication.

## Fixed bounds

The initial catalog permits 1–32 commands, at most 50,000 prospective total helix
base pairs and 50,000 authored strand residues. The existing shared request
budget is 256,000 bytes/10,000 JSON nodes; the worker envelope also pays that
budget. Producer collisions and prospective work are checked before native
execution.

Batch capture always uses the ordinary 30,000-node/2,000,000-byte/25 ms cooperative
profile. It cannot inherit the larger coating profile. Existing worker input
(2 MB), candidate output (16 MB), cumulative recovery (8 MB) and 2,000-entry
history budget, including routing-group headers, remain unchanged. The existing shared admission slot, 180-second
evaluation deadline, two retained job results, 15-minute result expiry and
cancel/reap behavior also apply. These are workload and transport bounds, not a
hard process heap guarantee. Latency qualification remains required before the
public gate can be enabled.
