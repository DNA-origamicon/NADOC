# Standard-part duplex input contracts

Audited October 15, 2026. P4 implementation is pending. Assemblies are deferred.
This extraction preserves molecular formulas, topology decisions and locked
constants; algorithm changes retain the separate molecular authorization gate.

## Six shared native commands

Implement pure builders in `backend/api/part_duplex_commands.py`; route adapters
and native replay must use the same builders. Strict versioned request models
accept inputs and references, never saved topology or sampled geometry. Keep
existing route DTO names as aliases where needed by callers/tests.

| Command | Existing route inputs | Required native additions |
|---|---|---|
| `duplex-create` | Two `{overhang_id,start_bp,end_bp}` ends; driver, bound, binding mode, N wildcard, connection type | Explicit duplex ID and creation time; retain endpoint order |
| `duplex-connect` | Two overhang IDs, attachment ends, optional driver, N wildcard | Stable duplex, child-cluster and ligation identities; retain automatic versus explicit driver choice and existing-binding behavior |
| `duplex-sync-bindings` | No request body | Ordered selected binding IDs and binding-to-duplex identity mapping |
| `duplex-patch` | Optional ends, driver, bound, name | Explicit target; omitted-field semantics; stable identities for driver reapplication |
| `duplex-delete` | Target ID | Preserve existing edge-only deletion semantics |
| `duplex-relax` | Target ID | Pinned algorithm/runtime contract; derive driver/driven from the selected duplex |

`routes_duplex.py` currently publishes all six mutations with `set_design` before
global validation and without a native feature. Move publication into the existing
atomic feature transaction. Builders return the candidate and small response
metadata; ordinary graph edits must not trigger full history regeneration.

## Reuse unchanged calculations

Use `core.duplex.connect_register`, `longest_driver`, synthesis helpers,
`binding_relax.compute_bind_topology` / `apply_bind_topology`, midpoint placement,
`duplex_cluster.materialize_duplex_cluster` and `direct_relax.relax_direct_binding`.
Do not reimplement their formulas in command wrappers.

Preserve inclusive ordered registers, multivalency, disjoint same-overhang
hairpins, Watson–Crick/N validation, attachment-end selection, minimum paired
length and unequal full-overhang lengths. A `bound` flag is existing authored
state; do not invent new relocation behavior for a metadata-only flag edit.

Extract placement validation from `routes_duplex.py` without a route import cycle.
Validate finite bounded native inputs before allocating interval sets, resolve
references uniquely and return typed missing-reference diagnostics. Patch must
validate the replacement model: `model_copy(update=...)` currently bypasses model
validation, permitting invalid nulls or unequal replacement intervals.

## Failure and identity gaps

- `connect_duplex` catches every relocation exception and publishes the graph
  anyway. `routes_overhang_bindings.reapply_binding_driver` similarly hides
  failures. Verified native commands should fail atomically with a diagnostic;
  explicit graph creation remains available through `duplex-create`. Existing
  tests with deliberately absent helices should test graph creation rather than
  concealed relocation failure. Preserve successful native geometry exactly.
- `Duplex` defaults to random ID/current time. Synthesis also creates fresh IDs.
  Record explicit identity and time, retaining source binding time for sync.
- `materialize_duplex_cluster` already accepts `cluster_id`; thread it through
  `relocate_duplex`, preserving an existing driver cluster's identity.
- `compute_bind_topology` creates a random `ForcedLigation` for multidomain driven
  overhangs with affected crossovers, also embedding it in the restoration
  snapshot. Add an optional identity input without changing topology decisions.
  Existing native binding commands need the same regression coverage.
- Sync currently skips unresolved bindings and selects the first binding per
  unordered pair. Capture the intended ordered selection and output IDs; replay
  must reject a missing selected input instead of silently dropping it.
- `direct_relax` reuses an existing child-cluster ID but appends incidental legacy
  history rows. Its adapter should retain incoming history and record one native
  command through the transaction. Use the established isolated work policy for
  costly execution; no new queue or cancellation mechanism.

## Compatibility and direct references

Preserve `target_joint_id`, `locked_angle_deg`, `connection_type`, binding mode,
wildcard policy and source creation time when deriving from a binding. Driver
patches currently propagate to all same-pair bindings and reapply the first;
preserve that selection order until a separately reviewed contract changes it.
Bindingless bound driver edits currently do not relocate geometry.

`prior_driven_topology` is derived restoration state, never a recipe input. Typed
scope mapping currently rejects it. A narrow codec must handle its driver/driven
overhang IDs, saved helix, strand/domain reference, prior domain, prior overhang
helix, saved crossovers and optional forced ligation. Historical saved identities
cannot all be required to exist in the current live model; snapshots may contain
the helix removed by relocation. Unknown fields remain fail-closed.

Delete currently removes only the graph edge; it does not undo relocation.
`revert_duplex_relocation` remains active in nanoparticle connection handling and
must not be pruned as apparently unused route code. Update obsolete model/helper
comments that claim duplex fields have no consumers.

## Producers beyond the six routes

- `routes_connection_versions.py`: direct Apply creates duplexes and sometimes
  relocates them. Integrate deterministic identity and shared helpers inside its
  existing atomic operation.
- `routes_nanoparticles.py`: NP Apply creates and relocates a duplex, then derives
  the live register from the resulting topology. Preserve that order and its
  antiparallel check.
- `crud.py::_derive_duplexes_if_empty` and
  `_materialize_duplex_clusters_on_load`: open/load currently synthesize duplexes
  and child clusters. Do not mutate a newly supported native recipe on reopening;
  legacy migration remains explicitly unverified until represented by inputs.

## Implementation order and completion gates

1. **Graph commands and selected sync.** Shared route/replay builders; cold replay,
   stable identity, omitted/null handling, missing-reference, multivalency and
   failure-atomicity tests. Existing successful route response behavior retained.
2. **Connection and driver reapplication.** Thread cluster/ligation identity;
   compare complete authoring output with unchanged native helpers for realistic
   single- and multidomain fixtures. Missing geometry fails without publication.
3. **Other producers and scope compatibility.** Connection-version and NP Apply
   use the same deterministic contracts; typed restoration snapshots round-trip;
   save/reopen preserves proof. No unlogged automatic migration of native output.
4. **Relax.** Run unchanged solve under existing isolated evaluation admission;
   cancellation/staleness cannot publish, no incidental history rows survive,
   output identity remains stable and independent cold replay reproduces output.

P4 duplex work is complete only after all active producers above are covered,
not when six routes are registered. Root coordinates all validation runs. No
implementation or tests were performed for this audit.
