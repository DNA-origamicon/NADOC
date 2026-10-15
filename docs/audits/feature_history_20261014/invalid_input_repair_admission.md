# Repairing a recognized feature with invalid inputs

Research and implementation review, 2026-10-15. The narrow gold recognition adapter described below is implemented; 393 parent-run corrective and related regressions pass. The separately discovered inert-annotation execution inconsistency is fixed. Numerical pins, source policy and scientific models are unchanged.

A failed feature must remain identifiable and editable even when its current inputs cannot execute. The minimum safe change is to separate **recognized authored contract** from **valid executable inputs**, while retaining full candidate regeneration as the publication gate. Do not replace the old-input check with command-name membership alone.

## CAD precedent

Onshape documents invalid/incomplete feature inputs in the feature dialog and prevents committing the broken feature until those inputs are corrected. Its feature dialog also preserves missing references as visible red entries. This supports editing a recognized definition separately from accepting the resulting geometry; it does not imply accepting arbitrary unknown feature types. [Onshape Feature Basics](https://cad.onshape.com/help/Content/PartStudio/feature_basics.htm).

SOLIDWORKS explicitly lists an oversized fillet as a rebuild error and offers Edit Feature/Edit Sketch links from the error report. The failed feature remains an editable definition; an error does not produce valid new model geometry. [SOLIDWORKS 2026 What's Wrong?](https://help.solidworks.com/2026/english/SolidWorks/sldworks/HIDD_NEW_WHATS_WRONG.htm?id=2.8.28).

Neither source specifies NADOC's trust/version schema. The envelope policy below is our inference and product decision, not a claimed vendor implementation.

## Current gates and the concrete gap

- `core/part_repair_planning.py:102` requires `dependencies(kind, previous).known` before applying any action. Gold `diameter_nm=-1` fails the complete native Pydantic schema and is therefore rejected as an unknown/legacy contract before it can be corrected.
- `api/part_proof_commands.dependencies` combines several meanings: strict schema admission for recent asset/numerical families, coarse dependency barriers for some older native families, and exact proof-version/output-namespace checks. It is not a universal field-editor schema. Leave its execution semantics unchanged.
- `_at` requires existing paths, `same_input` checks original expectations, `preserve_proof_identity` protects existing top-level namespaces/output IDs/versions, and `validate_target` checks final inputs. `part_recipe_repair` then regenerates every row from the explicit root with the native executor. Keep all these stages.
- `api/part_repair_input_metadata.describe_inputs` repeats the initial complete-schema check and calls full parsers again inside each family adapter. Removing only the first check would still hide invalid scalar inputs. `reference_slot` and `prepare_selection` likewise require the current complete schema.

## Recommended first increment

Add an explicit, shared recognition resolver beside the API-owned command contracts. Core planning receives it as a callback; draft preparation, worker repair and source-proposal planning receive the same resolver. Capture-only discovery still performs no admission, hashing or execution. Keep the existing known-contract behavior; extend only previously rejected definitions covered by a reviewed recognition adapter.

Start with unscoped source-free gold create/patch/delete, where identity and values are easy to separate. Extend to protein/free placement and rigid copy only after their own envelope tests, rather than announcing a generic repair capability for every registered kind.

The gold adapter requires:

1. A plain bounded parameter dictionary, exact integer `_proof_version=1` and `nanoparticle_version=1`, and a registered gold operation. Reject alternate/coexisting coating, thiol and quantum-dot discriminator markers even if malformed. `_generator` is inert metadata and cannot define editor authority.
2. Only fields admitted by that native command's schema, apart from explicitly ignored generator metadata. Do not synthesize defaults or missing fields.
3. For create, a valid existing `nanoparticle_id` output identity. For patch/delete it is a consumer reference, not an output identity; initially require its existing bounded string shape while allowing a missing live target. The distinction must be explicit per operation.
4. Existing editable values may violate numeric range/type/pose constraints. They remain editable inputs, not executable commands. Finite JSON and existing capture/operation bounds still apply. A malformed nonfinite/opaque value is outside the present JSON repair transport.
5. Keep exact expectations and protected-input comparison after every action, then final full schema/dependency admission and whole regeneration. No numerical/source I/O or model build occurs during recognition.

Return recognition separately from validity: e.g. recognized family/model plus `inputs_valid` and bounded input issues. A recognized-invalid result never means `Dependencies.known`, verified geometry, valid references or a publishable candidate.

For metadata, use that same recognition adapter and field declarations to show the **actual existing invalid value**, its supported constraints and a repairable-input diagnostic. Never replace it with a default. Avoid a later full `parse_command` call that rejects the same value again. The first increment can expose scalar/pose correction while explicitly withholding reference-candidate search until its current complete-schema gate passes; do not advertise a reference-selection action that will necessarily fail. A later reviewed gold selector can separate its own reference/ownership requirements from unrelated numeric values. Protein selection needs atom serial and ownership context, so it cannot inherit that relaxation automatically.

## Protections that block a generic shortcut

**Nested output IDs.** `crossover-place-batch` requires `placements[*].crossover_id` in dependency admission. Replacing an existing `placements` list can add missing output IDs; `_at` alone does not stop this, and `preserve_proof_identity` does not freeze those nested IDs. Therefore registered-kind plus proof-version recognition is insufficient. A broader adapter must validate and preserve an explicit output-identity projection, including nested containers/cardinality. Rigid copy already freezes its entire `protein_output_ids` and `nanoparticle_output_ids` arrays; require those arrays to be present, valid and complete before allowing invalid-value repair.

**Generated scopes.** Dependency admission strips `_generated_scope`, while actual scope execution validates its exact shape, v1/v2, UUID namespace, reference closure and legacy equivalence. Preserve the entire scope unchanged. Keep newly recognized-invalid scoped definitions unsupported in this first increment; a future adapter must recognize the scope envelope separately and cannot infer missing namespace/input IDs. Existing valid scoped repairs retain their current behavior.

**Numerical families.** Engine/template fields are protected; explicit upgrade parsing enforces recognized families and unchanged semantic versions, then server-selected current pins. Invalid-input recognition must never call `contract_defaults`, refresh stale pins or accept unknown engine/template families. Retain the existing numerical path initially. A future adapter must recognize the complete old pin shape independently of editable numerical parameters; actual runtime/template checks remain in execution.

**Source-bearing families.** Source descriptors are editable imported inputs, not output identities. Recognition is not source verification: retain named source-binding policy, exact byte identity/format/size bounds and native parsing. `part_repair_sources` currently also requires full old schema for restoring published bytes, and source binding extraction can reject malformed descriptors. Do not relax this incidentally when fixing gold scalars. A combined source repair still uses explicit staged bytes and final schema/regeneration; no implicit source healing, filesystem fallback or source reconstruction from atoms. Coating's fixed PDB identity remains fixed.

## Browser expectation transport issue discovered in the review

`same_input` intentionally distinguishes `12` from `12.0` by canonical JSON text. The actual browser path cannot preserve that distinction: input metadata JSON `12.0` becomes a JavaScript Number, `part_repair_fields.js` copies it into `expected_old`, and `client.js:470` uses `JSON.stringify`, yielding `12`. Consequently an unchanged server-authored integer-valued float can report `repair_conflict`; Python HTTP fixtures that encode `12.0` and JS fixtures using integers/strings miss this seam.

Resolve this before claiming scalar UI completion. Prefer a server-produced bounded typed expectation or canonical-JSON text receipt for the selected existing value, checked against the captured definition/path/revision. That preserves current strict comparison, including nested values, without trusting a client-supplied type conversion. A deliberately specified JSON-number equivalence policy is an alternative, but would change existing semantics/tests; boolean/integer distinction and strict version/identity admission must remain intact. Keep this transport decision separate from contract recognition. Nonfinite legacy numbers remain unsupported unless a separately versioned expectation representation is designed.

**Authorized transport decision, 2026-10-15:** optional `expected_old_json` contains the server's canonical JSON for the existing value. A bounded codec rejects duplicate keys, nonfinite/overflowing numbers, excess depth and noncanonical encodings. The displayed old value must match the decoded structure, allowing only finite integer/float representation differences; booleans remain distinct. The decoder restores the exact old value before constructing `SetInput`, retains the encoding for subsequent browser/persistence roundtrips, and charges both values within the existing aggregate request/draft envelope. `same_input` is unchanged and still compares against the captured original definition. The receipt is an encoding, not an authorization token. No-receipt actions retain their existing semantics and omit the optional null field on serialization.

The actual Node action builder plus HTTP submission reproduced both diameter and pose failures before implementation: two failed in 2.71 seconds, both HTTP 409 `repair_conflict`. The codec, metadata emission, frontend forwarding and persistence/native-evaluation regressions are now implemented; all 43 codec and eight actual transport cases now pass, plus 229 related repair regressions. Track this separately as fixed ISSUE-86.

## Narrow gold implementation status

`api/part_repair_contracts.py` recognizes only the exact reviewed unscoped source-free gold v1 envelope. It checks bounded JSON, required identity/version fields and an explicit native-schema field inventory, then masks only existing diameter/pose values in a private classification probe. No probe/default value becomes authored input or output. A future native field addition requires a new recognition review rather than gaining repair authority automatically.

The optional recognition callback is shared by worker repair, draft preparation/rebase and combined source-proposal planning. Final patched schema/dependencies, protected identities, exact expectations and full native regeneration remain mandatory. Metadata reports `inputs_valid: false`, the actual invalid old input and its exact transport receipt; reference selection stays unavailable until the current complete schema passes. Source restoration's own admission is unchanged.

The original 45-case target reproduced 23 failures with 22 existing protection cases passing in 2.81 seconds before production changes (root-run evidence, checkpoint `7d02a5f2`). Three additional regressions cover schema expansion, missing required editable inputs, and real HTTP combined gold/source draft inspection. The initial 48-case integration run passed 44 and failed four in 2.73 seconds: three assertions compared a native `Mat4x4` with a raw list and are corrected; the fourth exposed ISSUE-89 below. Corrective validation now passes all 48 cases in 2.71 seconds. The old metadata parameter case grouping a negative gold diameter with unknown contracts was pruned; genuinely unknown/owned/version cases remain.

ISSUE-89 is a separate pre-existing execution inconsistency: dependency/scoped admission ignores `_generator`, but ordinary strict builders received it as an extra input. A new valid-gold dossier independently reproduced five failures and 11 passing scope/identity controls in 3.68 seconds, including fresh-worker proof. The shared executor now strips only that inert annotation after scoped handoff and before reference/native validation, preserving the logged value. Native schemas and generated scope admission are unchanged; recognition does not confer authority through annotations.

## Implementation and regression map

Primary targets: new API recognition adapter; `core/part_repair_planning.py`, `part_repair_proposal.py`, `part_repair_draft_host.py`, `part_repair_sources.py` for resolver injection; `api/part_recipe_repair.py`, `part_repair_drafts.py`, `part_repair_source_host.py` for host wiring; `part_repair_input_metadata.py` for reviewed invalid-input discovery. Reference selection need not broaden in the first increment. Keep `part_proof_commands.dependencies`, numerical manifests and scientific code unchanged.

Tests should include real registered gold invalid-create/invalid-patch correction from an empty root, poisoned recovery/materialized output, unchanged output identity, a later dependent row, cold proof and one atomic publication. Cover draft save/rebase/evaluate and direct repair parity, invalid-final refusal, expectation conflicts, bool/string/unknown/missing versions, missing/invalid output IDs, unknown fields/families, ambiguous marker combinations, nested output-ID addition attempts, protected engine/scope mutations and zero execution on rejection. Update the current metadata test that groups `diameter_nm=-1` with unknown contracts; preserve all its truly unknown/owned/version cases. Add an actual browser-number transport round trip for integer-valued floats, nested poses and booleans. Existing numerical/source/identity tests remain regression gates.
