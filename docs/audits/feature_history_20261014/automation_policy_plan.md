# Standard-part automation policy plan

Read-only implementation audit, October 15, 2026. This is a proposed P6 sequence,
not implemented enforcement or test evidence. Assemblies remain deferred.

## Findings

The input-based replay architecture is sound. Enforcement needs a publication
boundary: a proof version on a history row is not authority to change a document.

| Boundary | Current gap |
|---|---|
| `backend/api/state.py` setters | Loadout and CPD checks exist; arbitrary authoring replacements are accepted. `get_or_404` returns live mutable state. |
| `backend/api/feature_recording.py` | Registered kind membership stamps `_proof_version`; arbitrary callback output is not compared with native execution. Independent proof detects a false receipt afterward. |
| `backend/api/crud.py` load/import | Full designs can be installed. Loading a file does not authenticate its recipe or create native provenance. |
| `crud._design_response` / `_ensure_default_cluster` | Response formatting can repair/create authoring clusters and silently advance canonical state. |
| `backend/api/routes_clusters.py` | Creation defaults to `log=False`; deletion is unlogged. `commit=False` pose previews silently modify canonical state. |
| `backend/api/routes_deformation.py` | Preview operations similarly use silent canonical writes. |
| `backend/api/headless_build.py` | `new_design` and `scratch_session` create plain `Design` objects without explicit roots. `place_primitive` accepts an arbitrary `Design` and grafts it without construction entries. |
| Metadata/centering routes | Metadata is currently classified as authoring, yet metadata updates and centering are unlogged. |
| `backend/api/main.py`, `doc_context.py` | No general authenticated UI/agent principal. A document header selects a session, not permission. Peer synchronization has a separate limited authentication mechanism. |

No general HTTP endpoint executing arbitrary Python was found in this audit.
The practical bypasses are ordinary mutation/import APIs and unrestricted local
access. Workspace uploads and opening a file must not become a way to import
unlogged geometry into a strict session.

## Minimal registered transaction

Add a bounded atomic batch request containing required `expected_design_id`,
`expected_revision`, and ordered `{kind, version, params, label}` commands.
Commands retain ordinary individually editable history entries; a batch has one
publication and one undo step. Allocate required identities before execution and
return resulting feature/resource identities. A reference to a preceding command
can initially use explicitly allocated identities; a general recursive alias
language is not required for the first increment.

Requests must not accept full designs, saved output snapshots/diffs, serialized
history, code, or client-created verification receipts. The public command input
adapter must distinguish legitimate explicit identity fields from private
`_generated_scope`/`_generator` metadata. Reuse each registered builder/schema;
do not create a second execution dispatch that drifts from proof replay.

Extend the existing isolated `part_evaluation`/worker/job path rather than adding
another queue. Execute `part_proof_commands.execute` directly, construct the normal
snapshot/minor/overlay entries from those executions, validate the candidate, and
publish with the captured source object and revision. Ordinary batches retain
ordinary budgets; expensive supported calculations use their explicit longer job
contract. Encoding and native computation stay outside the document lock.

`part_evaluation_jobs.commit` already supplies a useful candidate-publication
shape. Add a captured policy generation to the source/revision conditions.
Publication must remain failure-atomic even if validation, encoding, cancellation,
logging or response preparation fails.

## Trust policy and provenance

Keep effective policy in the server-owned document session, independent of saved
or imported `Design` JSON. Initial modes can be `compatibility` and
`registered_only`, with pinned-import permission separate. Strict sessions reject
arbitrary authoring setters, unlogged callbacks, raw design replacement and
unsupported preview writes. A narrow internal publication capability permits the
evaluated candidate; it is not a client-controlled JSON switch.

The policy applies to every admitted client of that session. A caller-provided
`agent=true`, origin label, user agent or custom header is not authentication and
must not confer permission or disable strict mode. Optional transaction/source
labels are provenance, not proof. True agent-specific access control requires
authenticated capabilities or a separately restricted service. The existing
single-user localhost application cannot honestly promise isolation from code
with unrestricted access to its process, backend modules or filesystem.

Replayability and permitted construction are different tests. Generic
`deformation` currently accepts sampled sweep `bp_positions_nm`/`bp_frames`;
strict automation should require ordinary sweep control points or the registered
fork/joined/connectivity input contracts instead. Individual authored helix and
strand primitives can remain legitimate features. `cluster-paste` selects
existing clusters and derives a copy, so it is not equivalent to accepting an
arbitrary design blob. Explicit external imports must remain visibly imported,
content-pinned and non-native; no import exception may silently certify an opaque
whole-model script as native editable construction.

## Performance and compatibility

Establish a verified baseline once when entering strict mode. Subsequent admitted
batches extend that server-owned baseline. Invalidate it after load, branch
navigation, legacy recovery publication, policy changes or compatibility writes.
Revision/source identity is a valid shortcut only while every supported write
respects the publication boundary. Mutable live aliases must not be presented as
a sandbox guarantee. Retain independent cold replay as the oracle; do not replay
the whole history on every appended command, read, scrub or display operation.

Existing files and unsupported histories remain usable in compatibility mode.
Do not silently assign import roots, delete snapshot seek/revert, or route proof
through recovery outputs. Strict previews need isolated draft state. Legacy
preview behavior can remain until its adapter is migrated. Response-time cluster
repair belongs to explicit legacy loading/recovery, never an implicit write to a
strict native document. Native builders must author required default clusters.

## Proposed checkpoints and tests

1. **P6a:** Registered batch evaluator, ordinary row construction, atomic
   revision-bound publication and explicitly rooted headless creation.
2. **P6b:** Server-owned session policy and setter admission. Reject strict
   bypasses with structured diagnostics identifying the unsupported operation.
3. **P6c:** Convert metadata, centering, cluster deletion/repair and preview
   publication. Compile headless primitives into native features or use an
   explicit pinned import. Preserve scientific builders and placement formulas.
4. **P6d:** Prune obsolete native-path flags/callback duplication only after caller
   coverage; retain named legacy recovery adapters.

Required tests:

- Mixed snapshot/minor/overlay batches, cold replay, parameter editing and one
  undo step, with separate visible editable rows.
- Failure/cancellation at each command and during validation/encoding/publication;
  unchanged design, undo/redo, revision and request metadata.
- Concurrent edit, stale source, closed/reopened document and policy changes.
- Forged proof markers, saved outputs/history, private scope metadata and sampled
  sweep injection; valid explicit identity inputs still work.
- Strict load/import, silent setters, unlogged grouping and arbitrary primitive
  graft rejection; compatibility load/recovery remains usable.
- Read/response formatting causes no canonical authoring or revision changes.
- Repeated admitted batches avoid historical replay; compare lock duration and
  interactive latency against existing unchanged regression gates.

## Primary CAD precedents and limits

Onshape's authenticated Features API creates parameterized features that remain
editable in the GUI and exposes feature updates. Its authentication guide
distinguishes application credentials from user authorization. These support a
registered feature API with an explicit authority boundary, not trusting an
actor label. [Features API](https://onshape-public.github.io/docs/api-adv/featureaccess/),
[Authentication](https://onshape-public.github.io/docs/auth/).

Onshape explicitly permits a custom feature to generate an entire part and runs
the feature again when upstream definitions change. Thus NADOC's requirement for
individually editable construction steps is its own product policy; this audit
does not claim that Onshape or SOLIDWORKS prohibit LLM-generated custom features.
[Defining feature types](https://cad.onshape.com/FsDoc/feature-types.html).

Queries describe selection criteria and are reevaluated against the current
modeling context. This supports preserving typed, repairable reference intent
inside command inputs rather than accepting arbitrary output geometry as a
replacement for dependencies. [Modeling](https://cad.onshape.com/FsDoc/modeling.html).
