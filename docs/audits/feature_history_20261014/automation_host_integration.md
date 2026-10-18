# Registered part publication: P6b implementation proposal

Read-only architecture review, October 15, 2026. Assemblies remain deferred.
The session policy, permits and baseline cache below are proposals, not deployed
security or replay guarantees. A narrow admitted-operation job guard is being
implemented separately. Unrestricted local Python/process/filesystem access is
outside this HTTP publication contract.

## Evidence and authority

Keep two facts separate:

* **Registered composition:** an independently established source followed by
  registered native execution, with the exact unchanged candidate committed.
* **Independent replay:** a fresh root-to-tip replay reproduces all authoring.

The pure batch's `candidate_replay_verified=False` is accurate. Strict publication
can accept registered composition without repeating an entire solve to stamp a
green status. A server-owned receipt records that evidence class and provenance;
it must not claim cold replay. Scientific validation remains a separate report,
including editable intermediate designs that contain validation warnings/errors.

An internal publication permit should be minted only for a host-admitted operation
and bound to its canonical request digest, source object, captured revision,
session incarnation, policy generation and exact candidate transport digests.
Worker JSON status, proof markers, origin labels and saved receipts grant no
authority. Verify and selection are always nonpublishing. Missing/unknown operation
admission fails closed. A successful commit consumes the permit exactly once;
failure preserves source, stacks, revision and permit retry behavior.

## Server-owned policy

Store effective mode, import permissions, generation and optional baseline evidence
in the document session, outside Design JSON and undo snapshots. Add a session
incarnation token so closing/reopening cannot reset an old permit into validity.
New/restored sessions inherit host configuration, never a loaded file's policy.

The existing `X-NADOC-Doc` header selects a session; it does not authenticate a user
or agent (`doc_context.py`). Do not expose an unauthenticated policy downgrade
endpoint. First expose read-only policy/capability status and configure policy at
the trusted host boundary. A future user policy control needs an actual authority
boundary. State the scope honestly: every client of that session receives the same
policy; unrestricted Python can still access process internals.

Capabilities should distinguish the replay registry, reviewed public command
catalog, policy-permitted inputs, imported provenance, current evidence class and
available UI editors. Computing capabilities must not replay or clone a Design.
The initial public batch has seven kinds and does not expose every replayable
command. In particular, a replayable sampled deformation is not automatically an
admitted automation input.

## Mutation seams that must be covered

| Seam | Current behavior | Required strict behavior |
|---|---|---|
| `state.load_design`, `set_design`, `set_design_branch`, silent/reconciled setters | Accept arbitrary Design replacements | Internal publication permit or a separately admitted rooted creation/load operation |
| `feature_recording.record_feature` / `record_minor` | Arbitrary callbacks; registered kind membership stamps proof markers | Dispatch native inputs through the registered executor; markers cannot authorize callback output |
| `mutate_and_validate`, `mutate_with_reconcile`, `replace_with_reconcile` | Generic mutation callbacks/replacements | Reject unsupported strict calls before callback execution |
| `mutate_display_metadata(fn)` | Arbitrary callback receives the live Design | Replace eligible calls with typed presentation-field assignment; no callable authority shortcut |
| `acknowledge_workspace_save` | Directly replaces `s.design` or modifies metadata/loadouts | Explicit typed save effects and evidence invalidation/transfer |
| Undo/redo, branch navigation, recovery seek/revert | Restore snapshots without construction-policy admission | Trusted prior evidence or explicit regeneration; retain named compatibility paths |
| `snapshot()` plus intermediate silent writes | Multi-step generic publication | Reject unsupported strict use; registered batch publishes once |
| Cluster/deformation previews, metadata, centering | Some canonical writes are unlogged | Isolated drafts or narrow registered contracts |
| Headless `new_design` / `scratch_session` / primitive graft | Plain roots and arbitrary supplied Design objects | Explicit roots; compiled native definitions or separately permitted imported basis |
| Startup restore, close/drop/reopen, workspace/peer loads | Session/model replacement outside ordinary editor paths | Host policy preserved/re-established; baseline and outstanding jobs invalidated |

`crud._ensure_default_cluster` already returns immediately for authored recipe
roots. The earlier audit warning is now confined to compatibility/rootless paths.

Metadata remains entirely authoring in `FIELD_ROLES`. Save path/signoff updates
therefore cannot currently be treated as proof-neutral. Resolve typed metadata
ownership/contracts before advertising strict file workflows; do not silently
reclassify the whole field as presentation.

## Baseline reuse and responsiveness

The initial batch proves its source once per explicit transaction. Preserve that
behavior until write coverage is complete; never add full-history replay to reads,
display changes or ordinary polling.

A future baseline binds source identity, revision, policy generation, session
incarnation, executor generation and construction provenance. Unknown writes
invalidate it by default. Typed presentation/physical effects can transfer it
without authoring replay; arbitrary callbacks cannot. Policy and source checks are
constant-time under the state lock. Candidate digest work already required for
transport checks stays outside the lock and should be reused.

Independent proof ignores saved recovery bytes. A baseline established by plain
verification cannot also certify saved snapshot/diff reuse. Track separately
whether recovery was rebuilt by trusted `ReplayPrefix`/`regenerate` execution. A
first explicit regeneration can establish that evidence; prior native candidate
publication can carry it forward. Do not solve this by treating outputs as proof.

`get_or_404`, `get_design` and `peek_design` return live mutable objects, while
`Design.copy_with` is shallow. Do not add blanket copies to every read. Keep cache
shortcuts disabled until supported strict routes have controlled ownership and
audited read paths. Immutable storage or a narrower read facade can be qualified
separately; do not claim a revision shortcut is sound while aliases can bypass it.

## Load/import distinctions

* Native reload: independent root replay plus policy admission before installation;
  saved markers/receipts are not authority.
* Pinned asset import: explicitly permitted formats and immutable source descriptors,
  with imported provenance retained.
* Opaque imported-part basis: a separate permission, visibly imported and non-native;
  asset permission must not authorize arbitrary whole-model scripts.
* Compatibility loads/recovery remain available. Do not silently invent roots,
  migrate saved recipes or discard snapshots to force strict admission.

## Small reversible checkpoints

1. Integrate pure batch into existing evaluation jobs: unchanged capture/transport/
   recovery limits, one publication and undo, no new queue or solver repetition.
2. Add session context/policy/permit types and complete setter admission. Preserve
   compatibility behavior; strict operation failures identify the unsupported seam.
3. Add strict rooted creation and explicit native load/import admission.
4. Migrate typed presentation, save acknowledgement, metadata, preview and recovery
   paths. Cover rollback and read-only response behavior before broad strict UI use.
5. Enable baseline/prefix reuse only after ownership and invalidation tests pass.
   Measure lock holds and interactive latency against unchanged gates.

Required tests include forged worker-ready results for read operations, unknown
admission, source/revision/policy/incarnation races, stale/cancelled/expired permits,
failure after publication stages, forged proof/private inputs, strict setter and
callback rejection, compatibility parity, save/undo evidence behavior, and repeated
batches without historical replay. Retain independent cold replay as the oracle.

## CAD grounding

Onshape's Features API supplies editable feature definitions; SOLIDWORKS macro
features rebuild from stored parameters/selections and require reproducible entity
identities. These support parameterized registered construction and stable IDs.
Both also permit custom features that construct bodies, so NADOC's decomposition
allowlist is its own policy, not a universal CAD prohibition on scripted geometry.

* [Onshape Features API](https://onshape-public.github.io/docs/api-adv/featureaccess/)
* [Onshape feature types](https://cad.onshape.com/FsDoc/feature-types.html)
* [SOLIDWORKS macro feature insertion](https://help.solidworks.com/2021/english/api/sldworksapiprogguide/Macro_Features/Inserting_Macro_Features.htm)
* [SOLIDWORKS rebuild callbacks](https://help.solidworks.com/2020/English/api/sldworksapiprogguide/Macro_Features/Rebuild_Function.htm)
