# Reviewed repair input metadata

`POST /api/design/features/repair-inputs` explicitly inspects one feature definition.
The body contains `expected_design_id`, `expected_revision`, `feature_id` and optional
`child_id`. The existing document header scopes the request. There is no caller-supplied
definition, source bytes, script, geometry or policy override.

The response carries the same part/revision/feature context, `assessment: inputs_only`,
`references_checked: false`, `definition_supported`, an explanatory `reason` when
unsupported, and bounded `fields`. Each field has its exact `parameter_path`,
`expected_old`, label, input type and applicable finite-size/value constraints.
Only existing authored slots are exposed; absent defaults are not invented.

Current scalar/pose adapters cover unowned gold/catalog particles, free proteins
and same-part rigid copy inputs. References expose an explicit selection-job
resource kind. Named original-source fields reuse the existing upload policy and
return the published descriptor, byte ceiling, replacement availability and a
requirement to inspect for an exact upload receipt. Fixed coating PDB identity
allows restoration only. Other admitted source-owning definitions expose their
source binding without gaining arbitrary parameter editors.

Inspection is not evidence that a reference exists, the part reproduces, or a
proposal may publish. Save/rebase/evaluate/apply retain their existing contracts.
Generated scopes, unknown/legacy definitions, owned attachment editors and
schema-invalid current definitions remain unsupported in this initial catalog.
Repairing schema-invalid scalar inputs requires a separate recognition contract
that preserves output identities and version markers; a known kind alone is
insufficient. Existing ordinary feature editor gates are unchanged.

The host checks revision and scans at most 2,000 feature/child identities under
the state lock, then copies only the selected input within 10,000 nodes, 256 KB
and a 25 ms cooperative allowance. Schema/field discovery runs outside the lock.
Recovery bodies, source bytes and geometry are never copied, decoded or hashed.
Rendering should not repeatedly call this endpoint; fetch on explicit feature
selection and discard results when document/revision context changes.
