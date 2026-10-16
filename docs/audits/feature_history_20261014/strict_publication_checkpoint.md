# First strict part-publication checkpoint

Audit and implementation record, October 15, 2026. The private host foundation
and closed strict route table are implemented; public batch publication remains gated. This is not
an authentication system or baseline cache. Assemblies remain out of scope.
Function names below are the stable inventory; line anchors describe the reviewed
checkout and will move as the state facade is extended.

## Current checkpoint

The host configuration, opaque admissions and one-use publication permits are in
`part_publication_policy.py`, `part_publication_permit.py` and
`part_publication_host.py`. State and direct publishers reject generic strict
writes before callbacks or snapshotting. Jobs bind their original canonical
request digest, source object/revision, session incarnation and policy generation;
commit consumes an exact private candidate permit only after successful
publication. Cancellation and publication share the job lock. Compatibility
batch jobs also recheck the measured publication scope under the state lock.

Explicit host empty-root creation is implemented. The public batch gate remains
false while capture performance is qualified. Independent cold proof remains
separate from registered composition; no baseline cache or repeated commit solve
was added. Parent-run focused checks passed 34 permit, 39 state, 24 job and 14
legacy route guard tests, plus the existing admission and job regressions.

Known early guards now cover legacy create/bundle/load/install, server-side save,
undo/redo preparation and all five loadout mutation handlers. This does not close
the entire HTTP surface: broader imports, filesystem endpoints, WebSocket
handlers and read helpers still require the closed route boundary below.

## Recommendation

Ship an opt-in **registered-only document session** whose initial authoring path
is the reviewed batch evaluator. Preserve the existing default compatibility
mode. Unknown writes fail before callbacks or external writes, even if their
feature kind has a replay contract. Other P4 families can gain explicit host
admission individually; completing every recipe is not a prerequisite for this
small strict slice.

The current architecture supports this: native execution, recovery rebuilding,
independent proof, candidate transport, publication and scientific validation are
separate. Evaluation jobs already bind a server-admitted operation to the source
object, revision and same-lock session incarnation. The missing layer is host
construction policy and a narrow authority to publish its evaluated candidate.
Do not add a second builder dispatcher or repeat a solve at commit.

Keep baseline/prefix caching disabled. `registered composition` is evidence from
the trusted evaluator; `independent cold replay` is a different assessment. The
current batch proves its source once and does not claim it cold-replayed the new
candidate. Validation failures can remain editable warnings/results, separately
from invalid references or failure to reproduce the construction.

## Trusted policy selection

Use a frozen server configuration object supplied when the host/application is
constructed, with a default profile and optional trusted document bindings. A
session inherits its effective mode/profile and a policy generation from that
host resolver. A startup option or private embedding API can select strict mode;
there is no public downgrade route or request-level `strict`, `agent`, `origin`
or `trusted` switch. Tests inject a host configuration, not an HTTP authority flag.

The resolver must outlive `_DesignSession`: `DELETE /documents/{doc_id}` drops the
session, and `_session` lazily recreates it on a later request. If the only strict
flag lives in the dropped object, close/reopen becomes a downgrade. Keep trusted
bindings in host configuration or an explicit host-owned registry; a newly
created session resolves the same policy again. Session-cache files and Design
JSON never restore policy or permits. Revoking/changing a binding increments its
generation and invalidates outstanding admissions and permits.

`X-NADOC-Doc`/`?doc=` selects a context and is not authorization
([doc_context.py](../../../backend/api/doc_context.py#L143)); document creation
just returns a random ID ([documents.py](../../../backend/api/documents.py#L55)).
If an agent can choose among unrestricted compatibility sessions, policy only
protects the strict target documents. To enforce registered-only behavior for all
agent traffic without changing manual users, use a host configured with a strict
default for that traffic and a restricted endpoint surface, or add authenticated
principal/capability separation later. A caller label cannot distinguish a user
from an LLM. Unrestricted local Python/filesystem access remains outside this API
contract.

First expose read-only capability fields for effective policy/profile/generation,
the reviewed public catalog, explicit import permissions and source-scope
availability. Do not expose the internal session token or publication permit.
Capabilities are constant-size metadata and never clone or replay a design.

## Complete publication-seam inventory

| Current seam | First strict disposition and reason |
| --- | --- |
| `state._session`, `_DesignSession`, `restore_doc_design` | Resolve host policy on creation/restore. Native saved files need explicit admission before becoming editable; never accept saved policy or receipts. |
| `state.load_design` | Reject arbitrary replacement. Add a separate bounded `create_empty_part` host transaction using validated name/lattice; initial strict creation has no supplied Design. Load/import remain compatibility-only until admitted. |
| `state.set_design` | Require a host publication permit for strict authoring. Preserve existing source/revision/session checks, CPD/loadout gates, one undo and assigned revision. |
| `state.set_design_branch` | Strict rejection until branch target replay/provenance admission exists. Branch/loadout snapshots are not construction evidence. |
| `state.set_design_silent` | Reject strict calls before assignment. A silent setter is not an internal authority exemption. The unused `set_design_silent_reconciled` seam was removed in G1 after caller review. |
| `state.mutate_and_validate`, `mutate_with_reconcile`, `replace_with_reconcile` | Reject generic strict callbacks/replacements before invocation, snapshotting or reconciliation. |
| `state.mutate_display_metadata` | Reject arbitrary callbacks in strict mode. Migrate only explicit typed presentation assignments later; this callback currently receives the entire live Design. |
| `state.mutate_with_feature_log`, `mutate_with_minor_log` | Registered kind membership cannot authorize arbitrary callback output. Reject strict generic recording before initial-design installation/callback; migrate eligible callers to a registered execution host. |
| `feature_recording.record_feature`, `record_minor`, `_run`, `_publish` | Guard direct lock-owned use too. These functions assign `session.design` and stamp proof markers; they do not establish that callback output equals registered execution. |
| `part_replacement_transaction.publish_replacement` | Enforce the permit at the lock-owned replacement primitive as well as its public facade. Direct publisher callers otherwise bypass `state.set_design`. Preserve failure rollback and consume permits only after successful publication. |
| `part_protein_import_recording.publish_import` | Direct replacement plus library publication and optional initial-source assignment. Require explicit pinned-import permission and a typed native-import receipt before strict use; do not grant authority just because it calls the replacement primitive. |
| `part_repair_draft_transaction.publish_draft`, `publish_sources` | Separate typed metadata/source effects. Neither grants geometry publication. Source staging must obey strict import/format permissions before retaining bytes; repair proposals can be retained as unexecuted metadata under a bounded policy. |
| `state.undo`, `redo`, `_restore_edit_snapshot` | Do not treat saved snapshot bodies as permitted construction. Initially reject strict recovery, or admit only host-owned records made under the current strict policy with no surviving mutable aliases. Prefer explicit root regeneration until ownership is proven. |
| `state.snapshot`, `clear_history` | Guard strict use: these mutate recovery/evidence state without an ordinary publication. Multi-step `snapshot` + silent writes must become one registered transaction. |
| `state.acknowledge_workspace_save` | Directly replaces the Design or merges metadata/loadouts. Require a typed save effect. Metadata is currently entirely authoring, so path/signoff updates are not automatically proof-neutral. |
| `state.copy_for_workspace_save`, `copy_for_persist`, `copy_doc_for_persist` | Read-only snapshots, but potentially expensive; preserve their independent performance scope. They do not mint permits or evidence. |
| `state.restore_workspace_heads` | Host persistence cursor metadata only; cannot authorize source/branch installation or restore strict policy. |
| `state.close_session`, `drop_doc` | Invalidate jobs/permits and any future evidence, retain the trusted host binding for future recreation. A close must not downgrade later opens. |
| `state.set_pdb_atomistic`, shared protein-library add/remove/get/list | Auxiliary mutable state is not an admitted authored input. Strict imported commands resolve captured pinned sources/assets; library mutation cannot confer native provenance. |

The state inventory is concentrated in
[state.py](../../../backend/api/state.py#L100), but direct publishers also exist in
[feature_recording.py](../../../backend/api/feature_recording.py#L41),
[part_replacement_transaction.py](../../../backend/api/part_replacement_transaction.py#L11),
[part_protein_import_recording.py](../../../backend/api/part_protein_import_recording.py#L275)
and [part_repair_draft_transaction.py](../../../backend/api/part_repair_draft_transaction.py#L40).
Guarding `set_design` alone is insufficient.

### Route and headless paths reached by those seams

* Creation/load/interchange: `crud.create_design`, `create_bundle`, `load_design`
  and import helpers install full models. Bundle creation first installs an empty
  model and then invokes a callback; it needs an atomic admitted rewrite before
  strict use. Existing pinned protein/caDNAno import and rigid-copy routes have
  sound native contracts but need their own host permission/receipt integration.
* History: ordinary `part_recipe_edit.change_recipe`, evaluation jobs,
  `routes_feature_log.seek_features`, and legacy `crud` delete/edit/revert/roll-to
  loadout paths publish via different facades. Initial strict admission can use
  jobs only; route membership or `_proof_version` never substitutes for a permit.
* Cluster/deformation create, delete and `commit=False` previews call ordinary or
  silent setters. Reject strict preview writes; isolated preview results may be
  admitted later. Rooted response formatting already skips implicit default
  cluster creation in `crud._ensure_default_cluster`.
* Display/metadata: `routes_display_metadata` has generic callbacks, and staple
  groups remain authoring despite that module's name. `crud.update_metadata` and
  centering are also authoring changes; field-role classification controls them.
* Loadouts: `routes_design_loadouts` creates, selects, renames and deletes branch
  snapshots through ordinary replacement. Keep these compatibility-only until
  target construction and typed save metadata have contracts.
* Saves: the part `/design/save-workspace` route lives in
  `routes_assembly_workspace.py`. It writes the file/project revisions **before**
  `acknowledge_workspace_save`. Reject an unsupported strict save before disk I/O,
  not merely at the later state setter. Peer/project upload similarly creates
  stored bytes, not authority to load those bytes into a strict part.
* Startup: `session_cache.restore` loads cached full Designs through
  `restore_doc_design`. A strict host must reject/quarantine unsupported cached
  parts or explicitly prove/admit them; compatibility restore stays unchanged.
* Headless: `headless_build.scratch_session` calls `set_design(Design(...))`;
  `new_design` calls `load_design(Design(...))`. Both are rootless today.
  `place_primitive` accepts an arbitrary Design and uses `snapshot` + silent set.
  Headless spec builders call those helpers. Root these via the explicit host
  creation path and compile supported inputs; do not exempt scratch contexts.
  Scientific headless scratch loaders remain outside the initial strict authoring
  profile, and assemblies remain deferred.

## Narrow permit design

Put cohesive types and checks in new small `api/part_publication_policy.py` and
`api/part_publication_permit.py` modules; state remains the lock-owning facade.
Avoid a global ContextVar that temporarily allows all writes: nested legacy
callbacks could inherit it and publish unrelated changes.

Suggested private frozen records:

```text
SessionPolicy(mode, profile_id, generation, permitted_input_families)
EvaluationAdmission(doc_id, session_identity, source_weakref, source_revision,
                    policy_generation, operation, canonical_request_sha256)
PublicationPermit(admission, candidate_handle, authoring_sha256, recipe_sha256,
                  evidence_class, provenance, expiry, one_use_nonce)
```

Only trusted host adapters mint permits from their admitted evaluator result.
Permits are private Python capabilities held in a bounded host registry, never
Pydantic/request/Design models. The registry verifies object identity/nonce; a
similarly shaped object or worker `ready`/`verified` label cannot mint authority.
The first issuer accepts only the reviewed batch dispatch on an admitted empty
root/source scope. Repair, native import and expensive append receive their own
issuer rules later; overlapping internal replay kinds do not widen policy.

Reuse the existing candidate decode and exact authoring/recipe digest checks.
Bind the permit to the privately owned decoded candidate, not caller-supplied
replacement data. At the lock-owned publication boundary check operation/evidence
class, document, session, policy generation, source identity/revision, expiry and
cancellation, then publish exactly that candidate. No new solver or builder runs.
Keep the complete candidate private until publication. The existing worker and
host code are trusted; saved JSON labels and untrusted HTTP clients are not.

Consume the nonce only after replacement and revision assignment succeed. A
publication exception restores source/stacks/revision/request context and leaves
the evaluated candidate retryable while its guards still match. A repeated
successful commit returns its original revision only in the same session and
policy generation. A policy change invalidates pending work even if the Design
object/revision are unchanged. Verify and selection can never obtain a permit.

## Mutable aliases and minimum ownership rule

`get_design`, `get_design_with_revision`, `peek_design`, `get_or_404` and library
getters return live mutable objects. `Design.copy_with` is explicitly shallow
([models.py](../../../backend/core/models.py#L3623)). A copied list still shares its
items; frozen Pydantic envelopes still contain mutable nested action/parameter
JSON. `preserve_document_state` deliberately shares current physical/presentation
objects, and recovery restoration preserves selected current metadata. A revision
comparison cannot detect a write through an already-held alias.

For the first strict surface:

1. Reject unreviewed handlers before they receive a live Design or perform I/O.
   Use a route-identity allowlist, not HTTP verb or a loose path prefix; some POSTs
   read and some helpers called by reads normalize data. State/transaction guards
   remain mandatory for direct/internal calls.
2. Admit a small audited read surface: policy/capabilities, revision, bounded
   canonical serialization and isolated verification/evaluation polling. Do not
   grant every GET implicit read-only trust. Add renderer/export paths only after
   mutation/alias tests; rooted default-cluster suppression is necessary but not
   a blanket proof of purity.
3. Transfer ownership of fresh privately decoded candidates at publication; do
   not retain writable caller references to authored nested objects. Copy public
   JSON at admission once, use existing isolated capture for worker inputs, and
   serialize outputs into owned dictionaries/bytes. Copy only changed typed
   presentation fields when those paths are introduced.
4. Do not globally deep-copy every getter or freeze every existing Design model.
   That would regress reads, break existing builders and alter numerical pins.
   Keep legacy getters in compatibility mode and introduce a narrow strict read
   facade/private capture path. Full immutable storage is a later measured change.
5. Keep construction-baseline/recovery-prefix cache shortcuts off until all strict
   writers and admitted readers respect this ownership rule. Independently proven
   authoring does not certify saved recovery; a future cache needs a separate
   `recovery_rebuilt` evidence field.

The first strict release can reject unsupported undo/preview/save/import rather
than weaken these rules. That is a limited new automation API, not a regression
to manual compatibility workflows. Its capability response must make the limits
explicit; it must not claim every visible UI edit is already supported in strict mode.

## Incoming recovery and publication cost

All three candidate producers need the same bounded incoming-recovery envelope.
The initial audit found coating and batch admission omitted old recovery bytes;
the outgoing 8 MB `RecoveryBudget` does not bound old snapshots retained by undo.
The shared `retained_recovery_bytes` helper and coating/batch checks now address
that omission without decoding old payloads. Protein import has its own bounded
history admission; sharing accounting must preserve that profile.

The checked helper first caps top-level rows and total child
count, then sums `len` of each supported pre/post/snapshot/diff payload against
the unchanged 8 MB allowance. `len(str)` is constant-time per payload; never decode,
hash or serialize recovery during this preflight. Fail on unknown payload/schema
shapes rather than recursively walking arbitrary hidden state. Use bounded
incoming accounting before copying. Keep the respective fixed
row/source/time profiles; sharing a helper must not silently broaden a profile.

Physical/presentation/draft and source-table retention require the separately
measured full-source envelope in `batch_publication_qualification.md`. Bounded
history depth is not a cumulative heap bound. No permit or policy should claim
latency safety solely because authoring capture or worker transport was small.

The retained-protein diagnostic supplies a concrete remaining cause rather than
a reason to raise budgets: with 1,000 retained and 1,000 added atoms, 29 of 30
attempts completed; one source capture refused at 47.67 ms, including an observed
generation-2 collection lasting 45.08 ms during capture. The subsequent cold
capture also refused. Private admission completed all 29 attempted cases with
5.47 ms p95, while publication was 2.79 ms p95 and 2.91 ms maximum. A smaller
128-retained/256-added diagnostic completed all nine attempts. These measurements
do not qualify the public gate or prove a hard latency limit. No GC policy change
is proposed. Evidence is retained in
`protein_free_import_benchmark_admission_gc_p4.json`.

After closing strict route and read-alias access, evaluate immutable authoritative
revision handles for that strict scope. The handle must own all nested authored
objects before readers or workers may retain it outside the global lock. Use
copy-on-write replacement through the admitted host transaction, with typed
presentation/physical ownership kept separate. Existing mutable Designs cannot
be moved outside the lock merely to relocate their copy cost; a concurrent alias
would make the captured revision untrustworthy. Keep ordinary compatibility
builders unchanged while measuring a small strict prototype, including retained
history/source ownership and undo cost.

## Remaining HTTP closure: closed strict application

The implementation is prepared in `part_strict_http.py` and
`part_strict_reads.py`, with `tests/test_part_strict_http.py` as its focused target.
After pushed checkpoint `cec8aa55`, it is wired as the outermost user middleware
in `main.py`, before compatibility CORS/preflight and route middleware. The policy
default remains compatibility. Parent-run checks passed 61 strict HTTP and five
scalar revision cases; broader regressions and HTTP measurement are separate
qualification steps. The strict paths are
`POST /api/design/registered-empty`, `GET /api/design/construction-policy`,
`GET /api/design/revision`, and the existing evaluation-job start, inspect, cancel
and commit paths. The four job handlers are reused directly, without mounting
their containing router. The strict capability projection reports the existing
batch gate; it cannot enable it.

Known JSON input is UTF-8 `application/json`, with at most 8,192 raw bytes for
empty creation or 256,000 for evaluation. Acquisition has a five-second total
deadline and stops on disconnect or policy-generation change. Duplicate framing
headers, unsupported encodings/media and declared oversize are rejected before
body reads; streamed oversize is rejected before appending the excess chunk.
Malformed/nonfinite/duplicate-key JSON and unsupported evaluation operations fail
before shared handlers. Existing structural, command, capture, worker and
publication limits still apply independently. Unknown paths/methods and strict
WebSockets are refused without reading their body or invoking compatibility.

The implementation reuses the exact canonical document resolver and binds it via
the existing document middleware. Scalar reads use `_sessions.get` under the
state lock, so absent-session reads do not create a session. No live Design or
legacy geometry response helper leaves that read boundary. Empty creation holds
the same lock through host publication and returns owned scalar metadata only.
Policy generation is rechecked after acquisition, before handler entry, and by
the existing shared admission/final-publication guards. The original application
alone receives lifespan events. A compatibility-context request to the known
`/api/documents/{doc_id}` close path is also refused when the path target is strict;
this closes the concrete header/path-target mismatch, not global authorization.

The same owned scalar revision projection is exposed to compatibility clients
through `part_revision_status.py` and `GET /api/design/revision`. It returns only
document ID, design ID or null, revision and presence; strict reads add the host
policy generation. It does not acknowledge geometry, create absent sessions or
perform history validation. This supports explicit post-commit UI refresh without
introducing a new full-Design status response.

Use a small ASGI application selected by trusted host policy before invoking any
compatibility handler, dependency or body reader. Preserve the existing
application for compatibility documents. Reuse the existing document-context
resolution for both HTTP and WebSocket traffic, then dispatch strict requests to
an explicit route table with no compatibility fallback on 404, 405 or validation
failure. A strict default is needed for an agent-facing host that lets callers
choose new document IDs; a strict binding alone cannot restrict access to another
compatibility document.

The initial route table should contain only host-owned empty-root creation,
constant-size policy/capability and revision reads, and the exact evaluation
start/inspect/cancel/commit handlers. Evaluation admission still permits only
batch and nonpublishing verify in strict mode. Do not mount the whole feature-log
router: it includes other recovery and mutation operations. Do not permit every
GET or a path prefix. Initially reject strict WebSockets and unknown uploads
before multipart parsing or file acquisition. Add a bounded canonical read
serializer only after its ownership and size contract is reviewed.

FastAPI supports independent subapplications with their own route definitions;
a pure ASGI host dispatcher can choose which reviewed application receives a
resolved document context. This use of a policy-selected dispatcher is NADOC's
design choice, not a built-in FastAPI authorization guarantee.
[Subapplications](https://fastapi.tiangolo.com/advanced/sub-applications/)
A custom `APIRoute.get_route_handler` can also wrap handler execution, but applying
it across existing routers is sensitive to registration and does not inherently
cover non-HTTP endpoints. A closed application has a smaller initial audit surface.
[Custom route handlers](https://fastapi.tiangolo.com/how-to/custom-request-and-route/)

The concrete remaining seams are:

| Surface | Why it is not automatically admitted |
| --- | --- |
| `state.get_design`, `get_design_with_revision`, `peek_design`, `get_or_404` | Return live mutable Design references. Revision checks cannot detect an in-place alias write. Keep them inside reviewed host code; do not globally deep-copy ordinary getters. |
| `crud.get_active_design`, `_design_response`, `_design_for_export`, geometry/export handlers | Helpers can receive the source itself or shallow copies. The rooted default-cluster fix prevents one known normalization; it does not establish purity or bounded cost for the full helper graph. |
| `crud.get_full_feature_log` | Serializes the whole Design before selecting history. A GET does not imply bounded work or retained-memory safety. |
| `routes_display_geometry.get_atomistic` | Can invoke substantial native geometry work on a live Design. It needs an independent read/ownership/job contract, not an implicit GET exemption. |
| `crud.open_library_part`, import/download routes | Some perform file or network acquisition before reaching the guarded installation seam. Refuse before those handlers in strict mode. |
| `routes_fs`, workspace upload/move/trash/save routes | Some perform filesystem effects without an authored Design replacement. State publication guards cannot authorize or prevent those effects. |
| `documents.close_document` | Addresses a document by path and also drops assembly context. Any strict close route must bind the actual current document and avoid unrelated shared state. Policy bindings must survive closure. |
| `ws.py` handlers | Mix reads and mutation with live Design access. No blanket WebSocket admission until exact handlers have typed contracts. |

The dispatcher should not create another production lifespan, workspace writer or
worker queue. Keep existing state/job guards as defense for direct Python callers.
Do not expose candidates or live nested authored objects to response callbacks;
strict reads return separately owned bounded dictionaries or bytes. Admitted
request byte limits must precede expensive decoding, independently of command
schema limits.

Acceptance for this next increment: an unregistered GET, POST, multipart upload
and WebSocket never reaches its handler or body reader; exact permitted handlers
work without compatibility fallback; header/query document resolution agrees;
client policy/origin labels cannot downgrade the host; policy/session races still
fail at final publication; cross-document close is refused; read alias canaries
show no authored mutation; compatibility behavior remains unchanged. Performance
checks must include admission/read overhead and lightweight requests, with no
hidden full-history replay. Until these pass, describe this checkpoint as a
private host policy foundation, not complete enforcement against agent traffic.

## Reversible implementation order and acceptance

1. **Policy foundation, still compatibility default:** host resolver and immutable
   profiles; sticky recreation; generation changes; read-only capabilities. Add
   negative HTTP tests for forged policy/token/origin and delete/recreate downgrade.
2. **Permit + complete state guard coverage:** apply the inventory above, including
   direct publishers and pre-I/O route admission. Strict mode may remain disabled
   until the guarded surface is complete. Verify every denied callback is never
   called and design, stacks, revision, library and filesystem remain unchanged.
3. **Useful strict slice:** explicit empty-root creation plus qualified registered
   batches and audited reads; one publication/undo snapshot, with unsupported
   recovery clearly refused until separately admitted. Prove existing compatibility
   tests unchanged and independent cold replay of strict-built candidates.
4. **Typed additions:** draft metadata/repair jobs, pinned imports, native ordinary
   edits, isolated previews, undo/redo, presentation and save acknowledgement. Each
   needs a host issuer/effect contract, not a new global bypass flag.
5. **Cache only after closure:** typed effect invalidation/transfer, recovery trust,
   policy/session generation and ownership tests; then compare interactive latency.

Cross-cutting tests: wrong permit/candidate/operation; forged worker/saved labels;
source, session and policy-generation races during capture/decode/publication;
expiry/cancellation; interruption after snapshot/revision with retry; missing
context never creates a session; stale committed handles; nested mutable JSON
alias poisoning; no canonical change from admitted read routes; old recovery and
excluded-state bounds before copy; unchanged busy-first admission and lightweight
HTTP lock contention. No ordinary read triggers full-history replay.

## Official CAD grounding and limits

Onshape's Features API creates feature definitions that remain editable in the
GUI and updates them by feature ID. This supports the registered command surface
and stable identities. [Features API](https://onshape-public.github.io/docs/api-adv/featureaccess/)

Onshape distinguishes application API keys from user authorization; OAuth scopes
represent delegated access. This supports a real host authority boundary, not
trusting an LLM/client label. NADOC does not currently implement that equivalent
principal separation. [Authentication](https://onshape-public.github.io/docs/auth/),
[OAuth2](https://onshape-public.github.io/docs/auth/oauth/)

Onshape explicitly allows a custom feature to construct an entire part and reruns
features when inputs or upstream features change. Requiring individually editable
NADOC steps is therefore NADOC's product policy, not a claimed CAD-wide ban on
scripts or LLMs. No special LLM authentication or construction exemption is inferred
from these sources. [Feature types](https://cad.onshape.com/FsDoc/feature-types.html)


## Closed dispatch validation checkpoint

The exact HTTP slice above is mounted as outermost user middleware, with no
compatibility fallback for selected strict requests. Root-run focused checks pass
61 strict HTTP and five scalar revision cases plus 132 publication/evaluation
regressions (198 total). They cover pre-body rejection, generation races, absent
session noncreation, nonreentrant-lock safety and path-target close refusal.

The 500-request in-memory probe passes with cleanup: strict revision median
1.076 ms/p95 1.362 ms, compatibility paired median overhead -0.006 ms (noise).
It does not qualify model capture or public batch enablement. The known mutable
source/undo alias issue is addressed next through exclusive immutable revisions;
no getter-wide copying or baseline cache was introduced. Cache identifier safety
is a prerequisite to expanding persistence. See [evidence](strict_http_benchmark_p6.json).
