---
name: assembly-feature-parity
description: "Binding architecture and acceptance rule: assembly mode matches individual-part behavior comprehensively, with only explicit ownership, assembly-semantic, or measured scale adaptations."
type: project
status: active
authority: canonical
review_after: 2027-02-28
---

# Assembly Feature Parity

## Ownership correction and input editor work — November 27, 2026

[Source-part ownership](feedback_assembly_part_ownership.md) supersedes the
embedded-part editing goals below. Assemblies position, connect and repeat whole
parts; source definitions are edited separately and all instances updated.

Input editor work combines HEAD 662fc1fd with the pattern implementation from
75d33dac in `/home/joshua/NADOC-assembly-editors`, on branch
`codex/assembly-editors-and-colors`. No merge into the shared branch is included. See [the input inventory](../docs/audits/assembly_feature_inputs_20261127.md)
for current capabilities and verification. New assembly patterns use versioned
command inputs and the independent evaluation/replay host. Old pattern logs keep
their explicitly legacy recovery-based path; they are not silently certified.

## Binding product rule

Assembly mode is a different host and scaling regime, **not a reduced product tier**. Unless the user
explicitly narrows scope, requests such as “port X to assemblies,” “make the assembly X tab the same,”
or “support X in `.nass`” mean comprehensive parity with individual `.nadoc` editing.

“Same” covers the entire behavior, not just the visible panel:

- controls, ordering, labels, help, defaults, presets, advanced options, and enable/disable rules;
- target selection, validation, warnings, confirmations, errors, and recovery;
- start/stop/cancel/resume/retry flows, progress, status, logs, results, and stale-result handling;
- visualization, coloring, overlays, selection, camera interaction, and representation behavior;
- mutations, undo/redo, feature history/seek/delete, autosave, save/reload, and session recovery;
- export and downstream consumers, including simulation preparation, job identity, archives, and cleanup;
- keyboard/menu entry points, accessibility-relevant state, and empty/loading/failure states.

A narrow port of the obvious buttons does not satisfy a parity request. Begin with an inventory of the
existing part behavior and trace every frontend, API, state, persistence, worker/job, visualization,
and test path it uses. The parity inventory is the implementation checklist and acceptance contract.

## Architecture: one capability, two hosts

Prefer this dependency shape:

```text
shared feature/domain logic
        |
        +-- design host: active Design -> design mutation/job API -> design refresh
        |
        `-- assembly host: selected target(s) -> instance/source or assembly API -> source/instance refresh
```

Do not fork business logic merely because `assemblyActive` differs. Extract or reuse a shared domain,
controller, panel model, job builder, validation function, or renderer primitive, then supply thin host
adapters for target lookup, API commit, cache invalidation, and layout. Frontend layout may differ to
accommodate instance/source selection or assembly controls, but capabilities and semantics remain equal.

An existing `if (assemblyActive) return`, disabled control, absent assembly endpoint, stub, or “part-only”
memory statement means **unported work by default**, not a durable product restriction. Remove or replace
the guard when implementing parity. Historical project notes yield to this canonical rule unless they
record a still-valid concrete exception.

## Mutation ownership

Edit part definitions only in their source part editor, then update all source
instances. Assembly-owned changes include whole-part transforms, joints,
connections, groups, patterns and configurations. The historical instance-edit
infrastructure described below is not an approved assembly authoring workflow.

## Permitted differences and required handling

Parity may be adapted only for a concrete reason:

- **Scale/performance:** molecule or instance count makes the part implementation prohibitively slow or
  memory-heavy. Use batching, shared GPU instancing, level of detail, streaming, aggregation, background
  jobs, target subsets, or explicit limits while preserving the same scientific meaning and workflow.
  Prefer measured thresholds; do not infer “assemblies are large” from the file type alone.
- **Different ownership:** behavior must target a source, one instance, selected instances, or the whole
  assembly. Add a clear target control and deterministic default.
- **Assembly semantics:** cross-part topology, joints, transforms, periodicity, or combined export require
  additional interpretation. Extend the behavior; do not silently drop the difficult parts.
- **Layout:** controls may move or condense, but remain discoverable and functionally equivalent.

For every exception, the implementation and completion report must state the concrete constraint, the
observed or expected failure without adaptation, the chosen closest-equivalent behavior, and any residual
gap. A silent no-op, hidden control, generic “unsupported in assembly mode,” or partial result is not an
acceptable adaptation.

## Example: “make the Simulate tab the same for assemblies”

This means auditing and carrying over every engine and engine-specific option; availability checks;
system/target selection; preparation and validation; advanced parameters; run/stop/resume/retry;
local, cluster, and remote submission where applicable; progress, logs, metrics, trajectory controls,
staleness, visualization, downloads/archives, deletion, and session recovery. It also requires checking
the generated scientific input and provenance—not merely rendering matching cards.

Assembly-specific design work may include choosing one part, selected parts, or the assembled system;
namespacing cross-part topology; estimating atom/bead counts before launch; streaming large outputs; and
using scalable renderers. Those are adaptations within the parity request. If a whole-assembly engine is
scientifically undefined or exceeds a measured resource boundary, preserve part-target execution where
valid, explain the boundary, and expose the closest meaningful workflow instead of omitting the engine.

## Verification contract

Parity work requires tests at the shared core and both host seams. Add at least one comparison test that
drives equivalent part and assembly targets and compares the relevant normalized result. For visual or
interactive behavior, exercise both modes in the running app. For simulation/export, compare generated
inputs, resolved options, provenance, lifecycle state, and result loading—not just API status or DOM
presence. Scale adaptations also need a representative large assembly check and an explicit threshold or
benchmark when performance is the reason for divergence.

Completion reports must include a parity inventory marked complete/adapted/deferred. “Deferred” is allowed
only when the user narrowed scope or a concrete blocker remains; it must not be used to quietly redefine a
comprehensive parity request.

## Related current architecture

- `project_assembly_part_context.md` — selected-instance design fetch/patch patterns.
- `project_path_to_thousands.md` — shared-renderer and large-assembly constraints.
- `project_assembly_configurations.md` — assembly-owned poses/configurations/overrides.
- `frontend/src/ui/file_io.js::savePartToAssembly` — existing design-to-instance save-back seam.
- `backend/api/assembly.py::patch_instance_design` — source replacement, cache invalidation, mate resolve.

## Feature-log parity goal — November 27, 2026

User authorized completing all high-priority findings from the assembly audit;
the persistent goal is active. Required outcomes remain: earlier-feature edit
and downstream regeneration; suppression/reordering/dependency inspection;
repair inputs and references, saved proposals, comparison and explicit commit;
independent verification and revision-bound cancellable evaluation; comprehensive
replay for surgical deletion. Include both assembly history and selected-instance
part history. Source versions and truthful recording are prerequisites, not
optional follow-ups. No high-priority item is complete yet.

First prerequisite implemented: `assembly_history_transaction.apply_history_change`
runs edit/delete recovery evaluation in a context-local assembly session excluded
from the autosave registry. `assembly_state.publish_candidate` checks revision
and captured source equality under the state lock, then publishes one undo step.
Failed replay cannot leave the live document at an intermediate prefix or pollute
its undo/redo stacks. This is recovery-snapshot evaluation, **not** an independent
process certificate. Source-file writes are not made transactional by this seam;
do not route source-mutating commands through it without a versioned source policy.

Focused validation: 44 tests passed in `test_assembly_feature_log_actions.py` and
`test_assembly_history_transaction.py`, covering existing seek/diff snapshots,
edit/delete rollback, concurrent-reader isolation, stale publication refusal,
and one-step undo. No running-app validation or parity completion claimed.

Command rollout now underway in `assembly_command_replay.py`: versioned complete
request inputs and output IDs for joint/mate creation, gear create/patch/delete/
resolve and group create/patch/ungroup/duplicate/delete. Replay calls the same
user-facing route in an isolated session and refuses incomplete/unknown contracts.
Group clone output slots are keyed by original object identity, not incidental
set iteration order. Gear patch and resolve previously changed state silently;
they now record actual operations. `assembly_history_edit.py` edits these
versioned body inputs at earlier positions and regenerates the suffix, preserving
feature IDs, attributing failures and publishing once. Desktop edit controls are
not yet wired for these added families. Existing four legacy editors retain their
old limits. ISSUE-274 tracks the remaining debt.

Saved/reopened command tests compare complete normalized assembly state without
consulting recovery payloads, including nested groups, stable duplicates, mate
connector/pose creation, gears and downstream regeneration. This qualifies those
command paths, not arbitrary source files or a full document certificate. Current
focused results: 98 passing command/group/gear/history tests before the earlier-edit
addition, then 53 passing command/history tests including that addition; seven
feature-label tests pass. The browser test now passes with animation enabled:
rendered gear rows, earlier input edit, downstream pose and one-step undo/redo.
Its initial failure exposed stale silent joint writes reverse-driving an edited
gear. ISSUE-275 is fixed by authority-bound ticker revisions and isolated atomic
silent publication (`assembly_playback_publication.py`). Stale playback returns
the current source without mutation. Another 45 backend tests (command replay,
transaction and gear behavior) and six frontend authority/ticker tests pass.
Playback now also binds the assembly ID, preventing a matching revision in a
different document from accepting old poses. Its three focused backend cases,
six frontend tests and the final browser rerun pass (5.8-second test body).
The isolated launcher verified all browser scratch roots absent after completion.
This exercises client/API integration, not the as-yet-unbuilt new input editors.
`just lint` passes. Required smoke: 28 checks passed initially; the assembly-exit
check exposed an existing helper waiting for an absent popup. ISSUE-276 corrects
that optional-overlay query; the focused exit rerun passes (14.5 s). No timeout
or validation guard changed, and all scratch roots were verified absent.

Next prerequisites remain: complete the remaining command inputs and stable output
identities. Newly recorded mate-seeded and periodic polymerization now retain
semantic output slots (direction, source object, repeat step); strict replay
preserves primary/pattern instance and joint IDs. Older summary-only polymer
records lack that mapping and are explicitly refused by the new command replay
path rather than silently regenerating IDs. Inspection/recovery remains available.
Group transform now evaluates privately, completes solver/gear follow-ups, then
records one complete operation and publishes one undo step. The later source
revision increment below removes direct source-file writes from replacement;
legacy admission and the complete editor/source-publication workflow remain open.
Do not manufacture missing historical inputs from recovery snapshots or certify
legacy records as independently replayable. Preserve the legacy inspection path
with explicit qualification while new user-facing commands record full contracts.

Worktree contains extensive unrelated changes predating this goal. This task also
touches group/joint/gear routes, group cloning, SnapshotOpKind (two new gear kinds),
feature labels, dedicated tests and the history test config's assembly selector.
Preserve other edits in models.py, feature_labels.js, the test config and ledgers.
This goal's `frontend/src/main.js` delta remains 0; its existing diff is unrelated.


Continuation: explicit input edits now capture the actual re-executed command's
parameters, including generated output slots. An edited polymer count may grow
or shrink while retaining surviving slot IDs; downstream commands replay strictly
and fail atomically with the affected feature ID when a selection disappears.
A no-op input edit currently refuses with guidance to delete the feature instead.
Downstream duplicate-group output changes are still strict failures; generalized
dependency/repair policy is pending. This does not complete the high-priority goal.

Validation for this increment: 123 focused command/group/polymer route/core tests
passed, followed by added length-edit/dangling-selection and recorded periodic
part-history checks. The periodic fixture uses bundle → nick → periodic seam via
real APIs and independently verifies its part recipe before assembly replay.
No molecular algorithms, polymerization-to-extension handling, phase constants,
or simulation semantics changed. Browser group-edit verification recorded below.

Final increment checks: the expanded 70-test command/history/transaction run had
69 passes and one obsolete assertion that earlier polymer edits must be rejected.
Replaced that assertion with downstream identity, count and undo checks; all 39
history-action tests then passed. All 26 command cases and five transaction cases
passed in the preceding run. Lint and diff whitespace checks pass. Running-app
gear + group-transform/history edit/undo flow passed (6.8-second body); isolated
root `/tmp/__e2e__history-bttlceuf` was removed by the launcher and independently
verified absent. UI input editors for additional operation families remain pending.

Next work: remaining joint/connector/overhang/belt/relax command contracts and
complete final-state recording; versioned external source ownership; shared
assembly/instance dependency/suppression/reorder and repair/evaluation workflows.
The persistent goal is active, with substantial verified progress but no claim
that all five high-priority items are complete.


Joint-command continuation (2026-11-27): normal joint patches and mate refreshes
now record `assembly-patch-joint` / `assembly-refresh-mate` after the complete
kinematic update. `assembly_recorded_mutation.py` evaluates a private working
copy, restores the untouched source for recording, and publishes once. Delete
joint now uses the versioned user route during replay, including gear cascade
removal (the legacy dispatcher only removed the joint). New joint/mate history
rows have their corresponding display families.

`command_params` now retains `input_fields_set` as well as full defaulted inputs.
Replay validates consistency and reconstructs the request's supplied-field set;
this is essential for patch limits (omitted = retain, explicit null = clear).
Earlier edits union newly supplied fields and capture the real command's outputs.
Joint patch recordings strip playback transport fields, and replay/edit refuses
attempts to author silent/revision-bound playback as a command. Existing silent
playback compatibility remains; this does not certify all animation paths or
solve independent full-document verification.

Validation: 169 focused tests (assembly API, command replay, history actions,
gears) passed; eight feature-label tests passed; lint passed. Browser flow passed
(7.5-second body): visible joint-update row, edited value driving the coupled gear,
and two undo steps restoring both the original patch and pre-patch state. Also
retains prior gear/group coverage. Disposable root
`/tmp/__e2e__history-3z7qyjdk` was cleaned and independently verified absent.
No main.js changes. Full goal remains active. Next route gaps include connector
contracts, belt patch (currently silent), belt/rider stable outputs, overhang
commands and source-backed instance mutations; then the remaining dependency,
repair, proof/job and selected-instance/UI parity work.


Connector/belt continuation (2026-11-27): connector add/delete and all six belt
operations now use versioned command replay. Connector outputs retain their
resolved labels even when deleting an earlier auto-labelled connector; explicit
label edits capture the new output and fail atomically on downstream selections
that still require the old label. Command path arguments can now be tuples
(instance + label). Belt/rider creation and belt polymerization preserve generated
identities and full placement inputs; output collision checks include belt paths
and riders. Belt patches record history/undo; deleting a belt detaches its rider
records while retaining cargo instances. Other deletion cascades (e.g. a joint
or group owning a belt pulley) still require a full dependency audit.

Validation: initial 172 focused assembly/command/history/belt checks passed;
expanded 32 command tests pass. Nine frontend feature-label tests and lint pass.
Browser testing caught a stale belt-patch response: it returned the unrecorded
intermediate object although the live state had the feature. Corrected it to
return the recorded state and replaced the old silent-patch HTTP test with
response-log and undo assertions; all 25 belt tests pass. App gear/group/joint/belt
edit/undo flow passes (7.5-second body). Both failed and successful browser roots
(`/tmp/__e2e__history-86wezkdw`, `/tmp/__e2e__history-3ni4uiqe`) were removed and
independently verified absent. No new general-purpose input editor UI yet.

Next: overhang binding/connection/duplex command contracts and numerical relaxation
inputs; source-backed instance mutation ownership and full dependency audit.
Full five-item persistent goal remains incomplete and active.


Overhang/source-identity continuation (2026-11-27): all binding, connection and
assembly-duplex CRUD/sync commands plus linker Relax now record versioned inputs
and stable outputs. Created-at values are captured and replayed for binding,
connection and duplex creation; malformed/missing times are refused rather than
invented. Duplex sync allocates committed outputs by the canonical source pair;
its geometry/register algorithm is unchanged. Tests construct source parts via
bundle + valid overhang-extrude APIs and independently prove their part histories.
They replay saved/reopened commands through binding/sync/edit/delete/connect,
explicit-register creation and linker creation/patch/relax/delete, comparing
complete source state and materialized assembly topology.

Those tests exposed a serious source identity bug: v2 serialization and wire
responses keyed inline sources only by design ID. Two revisions of one part
collapsed into the first during saved/reopened history edits. New
`assembly_source_identity.py` hashes complete source content including provenance;
model serialization and API responses share it. Equal content still deduplicates;
shared source objects are hashed once per serialization call. Geometry cache keys
also include this content identity so different revisions cannot reuse each
other's geometry. This preserves inline revisions, NOT external file pinning or
recoverable writes, which remain unresolved. Scale review remains needed for
repeated full-source hashing in geometry-key callers; avoid a long-lived cache
keyed only by mutable object identity.

201 focused API/command/overhang/duplex/relax/cache checks passed, as did lint and
diff checks. App flow passed (7.5-second body), including separate inline source
revisions sharing a document ID and the prior gear/group/joint/belt edit/undo
checks. `/tmp/__e2e__history-7oa600jy` was cleaned and independently verified absent.
This app check covers source transport; overhang command lifecycle is backend
verified, not a newly built UI editor. No molecular placement/routing algorithm,
phase constants, or simulation semantics changed. Full goal stays active.

Next priorities: versioned instance/source changes and external-file ownership,
remaining assembly state mutations/resolve/animation/configuration provenance,
complete dependency cleanup and reusable evaluation/repair/suppress/reorder/job
hosts for assembly and selected instances. No high-priority item is certified
complete solely because the supported-command registry has expanded.


Pinned-source continuation (2026-11-27): `PartSourceFile` now optionally carries
an embedded `revision` and `revision_sha256`, validated on deserialization and
by both API/core source readers. Newly added file instances pin the resolved
part and record it in a versioned add-instance command with stable output ID.
`assembly-replace-instance-source` records the real source-replacement operation,
preserving the supplied part history and resolving mates before one publication.
`_replace_instance_design` now keeps inline designs inline and updates file-source
revision contents without writing the external .nadoc; the original path stays
as origin metadata. No generated standalone part is published by that route.

Readers, geometry identity, readiness and simulation-fact deduplication honor
pinned revisions. Polymer seed matching compares pinned source structures, so
same-path/different-shape revisions cannot silently form an identical-part chain.
Frontend base-design caches and both renderers distinguish pinned revisions;
legacy file grouping remains compatible. Path-prefetched geometry is not applied
to pinned instances. Assembly refresh invalidates the selected pinned instance,
not every instance sharing its original path. Inline renderer keys now also
respect revision content rather than only document ID.

Validation: 179 focused backend checks passed (API, source versions, replay,
flatten reader, geometry cache and readiness); final source tests also pass after
schema digest validation and polymer matching changes. File fixtures use the
real bundle API and `agent_structure_guard.publish`, not direct history-free
writes. Tests verify external bytes unchanged, source replay after the original
file moves, complete undo/redo and digest corruption rejection. Frontend initial
60-case run had four shared-renderer key expectation failures; preserving legacy
file grouping fixed these (27 relevant cache/reuse checks passed). Added a real
shared-renderer two-pinned-revision case; all 19 reuse tests pass. The other six
frontend files passed initially. Lint/diff checks pass. App source replacement
row, unchanged sibling source and undo pass, alongside prior assembly history
flows (7.7-second body). `/tmp/__e2e__history-ir8szarn` was cleaned and independently
verified absent. This goal's main.js delta remains zero.

Unfinished source work: legacy unpinned source admission before history edits,
explicit source reload/update UI, complete part-editor save/publication ownership
audit (other save paths may still write files), and native replayable instance
part mutations. The old `_apply_part_mutation_with_feature_log` still creates a
payload-free assembly row and needs replacement by the shared part-command host.
Do not claim all source-version or selected-instance parity complete. Also keep
full-source hashing scale review, dependency cleanup, suppress/reorder/repair,
independent proof/jobs and expanded input-editor UI in the active goal.


Instance-command continuation (2026-11-27): authored instance property updates
(name, fixed/mode, internal-joint state/overrides) now record a full
`assembly-patch-instance` request. Combined property + pose changes retain all
inputs in versioned `assembly-transform-instance` records; private evaluation
and one publication prevent partial state/display leaks on validation failure.
Visibility/representation-only updates keep their existing lightweight history-
independent behavior and display preferences are remembered only after success.
Cluster transforms now capture the full override, optional joint state and
propagated world delta. Duplicate-instance commands capture inputs and stable
output IDs. Explicit FK propagation has its own `assembly-propagate-fk` command
contract because its semantics differ from direct transform patch gear syncing;
it still renders in Move/Rotate. Legacy unversioned transform/duplicate readers
retain compatibility, without acquiring independent proof qualification.

174 focused API/command/history/gear tests passed, plus the added real bundle
cluster/mated-child replay test. Tests verify metadata + transforms, earlier
edits with stable downstream duplicate identities, whole-operation undo and
failure atomicity. Eleven feature-label tests and lint pass. App instance-property
history/edit/two-step undo passed along with previous flows (7.8-second body).
`/tmp/__e2e__history-rxw1c3jw` was removed and independently verified absent.
No main.js edits. General input-editor UI, source admission/update/save workflow,
instance native part mutation hosts, full dependency cleanup, suppress/reorder,
repair and proof/jobs remain unfinished under the active five-item goal.

Deletion-closure continuation (2026-11-27): added shared core assembly_removal
for instance/group/joint/connection deletion. It removes affected joints, gears,
belts/rider attachments, cross-part bindings/connections/duplexes, generated
linker topology (using the existing domain removal operation), and instance-
anchored proteins. Surviving cargo/parts keep poses and source histories.
Configurations and animation snapshots deliberately remain historical records;
the existing configuration contract restores only objects that still exist.
Instance deletion now has a versioned real-command replay contract. Old
unversioned deletion retains its legacy recovery reader, not proof qualification.

160 focused API/history/command/overhang tests pass after fixing a missing local
command_params import found by the first run. New cases cover instance/group/
joint cascades, real authored overhang/linker source histories, saved/reopened
command-only replay, whole-operation undo/redo, and surgical deletion followed
by replay of a later instance-deletion command. Lint/diff checks pass. App
instance delete removes its gear and belt; undo restores the full prior assembly
(11.1-second test body, prior flows included). Browser scratch
/tmp/__e2e__history-5vj_0ax7 was removed and independently verified absent.
No main.js edits. This is structural deletion cleanup, not completion of the
five-item goal: native selected-instance mutation hosts, remaining command
contracts, source update/admission/save paths, suppression/reorder/dependency UI,
repair drafts, independent proof/jobs, input editors and scale review remain.

Shared-regeneration continuation (2026-11-27): assembly_history_regeneration
now supplies the single suffix executor used by versioned input editing and
surgical deletion. It accepts an explicit recovery/root prefix and proposed
rows, executes actual commands, preserves authored IDs/timestamps/group tags,
records fresh recovery payloads with the normal recorder, skips suppressed rows
without losing their definitions, rejects duplicate IDs, and attributes failed
references to the exact feature/index. Checkpoints before/after commands and
before return allow cancellation without publication through the existing
isolated transaction. Deletion now rejects a non-tail cursor. Removed the
obsolete separate replay allowlist; the actual dispatcher determines support.

83 existing command/history/transaction checks and four new regeneration checks
pass. New checks cover suppression/resumption with reopened recovery, proposed
reordering, invalid-order reference attribution, cancellation after a completed
command preserving live revision/redo, and duplicate feature IDs. Lint/diff
checks pass. Existing app editing/deletion/undo flow passes (11.1-second body);
/tmp/__e2e__history-ton_tcma was cleaned and independently verified absent.
No main.js edits.

This is execution infrastructure, not delivered suppression/reorder controls.
Independent assembly recipe-root/source proof must precede their publication
contract (parts currently verify source and candidate recipes). The current
Assembly model still lacks an explicit recipe root; create_assembly constructs
an ordinary empty Assembly. Never infer/capture a root from recovery geometry.
Next work should establish that explicit creation/proof boundary, then expose
shared suppression/reorder/dependencies/repair/jobs and selected-instance hosts.
All remaining scope listed above stays active.

Independent-proof continuation (2026-11-27): added explicit AssemblyRecipeRoot
(empty origin, initial name, strict version) only at real new-document creation
and lazy get-or-create. Legacy loads retain recipe_root=None; no snapshot/root
migration. Root survives .nass v2/API/snapshot serialization. Core
assembly_history_contract classifies every Assembly field, failing closed on
future unclassified fields. Authoring comparison includes configurations and
all source/constraint/topology state; presentation and document identity are
excluded, with visible/representation excluded per instance and workspace
identity signoff excluded from metadata like part proof.

assembly_history_proof plus API assembly_history_verification independently
validate/replay versioned definitions from the empty root, never decoding
recovery payloads. Source revisions introduced by add/replace are independently
part-verified, including suppressed definitions and parts later deleted. File
sources must be pinned before execution; source proofs are content-digest cached
within one evaluation. Native versus reproduced-import status propagates from
sources. Exact recipe/authoring fingerprints and feature-attributed failures are
returned. Cancellation checkpoints propagate; no result is published. Command
schema validation extracted from the replay executor is reused for suppressed
rows, and boolean command versions are rejected. Source/assembly metadata or
pose changes without commands fail proof. This is authoring reproducibility,
not a molecular geometry or comprehensive assembly reference-validity verdict.

165 focused existing/new checks passed; all 12 proof tests passed after strict
root/version additions and the pinned-file/dedup checks. Lint/diff checks pass.
App File > New Assembly preserves creation inputs and existing edit/delete/undo
flow passes (10.6-second body). /tmp/__e2e__history-klbv0g6i cleanup independently
verified. No main.js edits.

Remaining: expose verification through revision-bound bounded/cancellable jobs,
add dependency contracts and assembly structural/reference assessment, wire
suppression/reordering through verified source/candidate regeneration, then
repair drafts/comparison/commit and selected-instance command hosts. Valid
presentation-checkpoint commands still need proof-adapter support. Legacy root
admission must never silently claim reconstructed provenance. No publication
guard for authored assembly artifacts is supplied by this internal verifier yet.
All five high-priority requirements remain active.

Reference-validation continuation (2026-11-27): assembly_structure.assess_references
adds bounded, cancellable live-relation checks without flattening, geometry
construction, disk reads or source hashing. It checks collection identity
uniqueness; both joint endpoints (ground parent allowed), cluster and connector
selections; gear/belt revolute-joint and endpoint-side consistency; rider refs;
overhang/subdomain/duplex/connection refs; protein asset/anchor refs; internal
joint/cluster overrides; and group partition/cycles. Historical configuration/
animation selections retain their restore-only-if-present semantics. Source
indexes use only embedded inline/pinned revisions. Unavailable source content,
item/issue exhaustion return incomplete, never valid. The checked scope is
explicitly assembly_relation_references, not molecular integrity, duplex register
validity, generated strand closure, or source-part topology proof.

Independent assembly proof now reports final reference status separately and
checks each executed intermediate assembly. A recorded joint with a missing
cluster followed by joint deletion is rejected at the originating feature even
though final references are valid. Source integrity/provenance still belongs to
the separate upstream proof step. The ordinary add-joint route currently accepts
that missing-cluster input; this test documents the gap for later command/input
validation and repair work, rather than claiming the authoring route is fixed.

18 proof/reference checks passed after correcting the cluster identity field
(id, not cluster_id); all seven reference checks passed after adding internal-
joint/override and no-disk-read coverage (20 unique checks in total). Lint/diff
checks pass. Internal verification only; no new frontend behavior, browser run
or main.js change. Next: revision-bound verification/evaluation jobs, dependencies,
verified suppression/reorder public controls, repair and selected-instance hosts.
The complete five-item goal remains active.

Verification-job continuation (2026-11-27): added assembly_verification_jobs,
assembly_verification_worker and routes_assembly_history with POST/GET/DELETE
/api/assembly/features/verification/jobs[/{id}]. Uses the existing part worker
shared-memory transport, native thread limit and supervisor lifecycle. Supervisor
now accepts a host source-matching callback; part defaults are unchanged.
Assembly jobs bind document, source object, session object and revision, including
close/reopen at equal revision. They share the existing global work-admission
slot and retain it until child termination/reaping AND shared-buffer cleanup.
Cancellation, deadline, stale source or busy final check prevent a verified
result. Verification cannot publish a candidate. Registry is bounded to eight
results, expires terminal results after 900 seconds, and checks document scope.

Capture owns the assembly lock, strips only outer assembly recovery payloads,
and bounds graph nodes/bytes/cooperative capture time before copying. Complete
source-part histories and pinned-source content remain intact for digest proof.
Input cap currently 16 MB/150k nodes, worker result cap 2 MB, time cap 180 seconds.
These explicit fail-closed bounds need assembly scale review; they are not a
permanent feature exclusion. Worker termination supplies the hard execution
limit. Mutable-source matching follows the existing part host's object/session/
revision contract; all authoring paths must continue honoring revision updates.

36 focused assembly/shared-supervisor/worker checks passed, then 20 assembly/
part-evaluation checks after admission/expiry additions (48 unique tests).
Actual spawned-worker test verifies named shared memory is absent after cleanup.
Lint/diff pass. App HTTP start/poll/cancel from File > New Assembly passes along
with existing edit/delete/undo flow (10.3-second body); isolated root
/tmp/__e2e__history-9p62olqn removed and independently verified absent. No main.js
changes. This exercises live endpoints, not a new verification button/progress UI.

Next: evaluation requests/candidate jobs and explicit atomic commit through the
same lifecycle; verified suppression/reorder, dependency inspection, repair
comparison/commit, and shared selected-instance hosts. Verification UI/status/
progress wiring and large-source admission remain unfinished. Full goal active.

Evaluation-job continuation (2026-11-27): added strict assembly evaluation
requests keyed by document/revision/feature ID for suppress/unsuppress, reorder,
input edit and surgical delete. Evaluator independently verifies source, replays
proposed history from explicit root using shared regeneration, checks candidate
proof/references, preserves presentation preferences, and returns a private
candidate. Existing input-edit parsing is shared with the synchronous edit route.
Fixed-target spawned worker uses the shared bounded transport/supervisor. Public
POST/GET/DELETE /assembly/features/evaluation/jobs[/{id}] and POST .../{id}/commit
are registered. Polling never returns candidate data. Registry retains at most
two candidates with 900-second expiry; cancellation/staleness prevent commit.

Explicit commit validates request binding, full candidate digest before/after
schema decoding, live document/session/revision, and a lock-owned capture digest
of source content (also detects in-place changes without revision increments).
Publication is one undo step, repeated commit is idempotent within its session,
and committed revision is the known source revision + 1 (not a later racing read).
No source/candidate geometry or history is published before explicit commit.
Limits remain 16 MB input/result and 180 seconds; source capture is bounded.

App found ISSUE-277: POST /assembly/save silently changed inline sources to
unpinned external files and invalidated running jobs. Fixed save to persist the
captured .nass with source revisions/history intact, creating no implicit part
files and changing no live state/revision/undo. The saved/reopened document
independently verifies. This also resolves that specific autosave ownership gap;
other source update/editor save paths and legacy unpinned admission remain open.

56 focused command/evaluation/transaction checks passed; then 16 evaluation/source
checks passed after the autosave regression (60 unique checks). Lint/diff pass.
App verification plus private evaluation/explicit suppression commit/two-step
undo and prior history flows pass (14.6-second body). Failed roots
/tmp/__e2e__history-ct574h7m and /tmp/__e2e__history-1wcz88lx and passing root
/tmp/__e2e__history-6glp7cy_ removed and independently verified absent. No main.js
changes. Current browser coverage drives live API jobs, not new history menu/
progress controls. UI host adapters, dependency contracts/inspection, repair
selection/drafts/comparison/commit, selected-instance native hosts, remaining
command contracts/source admission and scale review all remain in active goal.

Desktop-controls continuation (2026-11-27): assembly feature rows now expose
Suppress/Unsuppress and Move through the existing shared context menu/dialogs.
A small history_dialog_host resolves part versus assembly context; the shared
modal owns progress, cancel, regeneration errors, commit, private refresh and
adoption. Assembly transport binds captured feature IDs and confirmed response
revision, rejects mismatched receipts/refreshes, and never applies private job
results before explicit commit. Source replacement/document switches retire the
dialog and cancel late work. Polling includes stopping state. Suppressed assembly
rows show the same badge as part rows. Repeated backend commit receipts now retain
their assembly ID so checked refresh is also valid after an idempotent response.

31 focused frontend tests and 13 backend evaluation tests pass. Real app right-
click Suppress/Unsuppress/Move dialogs, visible badges, verified jobs, commit and
undo pass (20.3-second body). Initial browser attempts left File's dropdown
focused and blocked row clicks; ordinary click in the empty scene dismisses it,
with no forced click or raised timeout. Focused `just smoke` boot/assembly-exit
selection passes all seven checks. Lint/diff pass. Scratch roots
/tmp/__e2e__history-9y3erhj8, /tmp/__e2e__history-qtvylp2m,
/tmp/__e2e__history-okbu9r2k and /tmp/__e2e__smoke-jwladt9p all removed and
independently verified absent. This increment's main.js delta is zero.

Still incomplete: assembly suppression currently requires return to latest
history (part suppression can regenerate from a historical prefix). Need verify
that displayed prefix independently, then reconstruct the full source for that
workflow; do not silently trust snapshots. Verification jobs still need UI,
dependencies need contracts/inspection, and repair drafts/reference selection/
comparison/commit and selected-instance native hosts remain outstanding. General
input editing UI, source admission/update and scale work also remain. The full
five-item goal stays active.

Dependency-inspection continuation (2026-11-27): added reviewed dependency
contracts for all registered assembly commands, using the shared typed dependency
index. Local instance property/connector and creation operations carry instance
resources; pose propagation, grouping, automatic pairing and cascading deletion
remain conservative global barriers. Unknown/legacy contracts remain unknown;
independent proof refuses unreviewed commands. This graph explains ordering but
does not replace replay validation of a proposed move.

Read-only bounded GET /assembly/features/dependencies returns document/revision
and row parents/dependents. Assembly View dependencies reuses the part dialog,
rejects stale revisions, and closes on assembly changes or mode exit. It performs
no source traversal, snapshot decoding, geometry or mutation.

31 focused backend checks and 14 frontend checks passed. Actual app dependencies,
suppression/unsuppression/move and undo pass (19.4-second body). Initial browser
failure was an ambiguous Close test locator, fixed by selecting the footer button.
Roots /tmp/__e2e__history-l3qbn5ec and /tmp/__e2e__history-do6bbm8f removed and
independently verified absent. Focused assembly-exit smoke passed (1 test,22.1s);
/tmp/__e2e__smoke-fhfbew0p removed and independently verified absent. An earlier
smoke invocation's output was truncated; no result is claimed for that invocation.
Lint/diff pass. No task changes to main.js. Remaining full-goal items above still
apply, except assembly-level dependency inspection is now implemented.

User priority correction (2026-11-27): verification is rarely used directly by
the user but is critical for internal testing. Defer dedicated verification UI;
it is not a completion requirement for the active parity goal. Retain independent
process verification, source proof, revision-bound cancellable backend jobs and
internal regression/app coverage as high-priority requirements. Prioritize actual
editing/regeneration, repair drafts/reference selection/comparison/commit,
historical-prefix suppression, selected-instance histories and deletion replay.
This supersedes earlier entries listing verification UI as required outstanding
work; it does not defer the ordinary editing or repair UI. Removed the unfinished,
untested verification dialog/menu/transport increment. Existing backend verification
and tested dependency/history controls are preserved. The persistent goal remains
active; its tool supports status changes only, so this file records the user's
scope correction without falsely completing or replacing the unfinished goal.

Further user scope correction (2026-11-27): "Same for repair workflows. focus on
editing and downstream replay." Dedicated repair drafts, reference-selection
workflows, comparison and repair-specific publication UI/backend extensions are
deferred and are not completion gates for the active goal. This supersedes the
previous paragraph's repair priority and the original five-item objective where
they conflict. Focus remaining work on ordinary earlier-feature input editing,
complete downstream regeneration after edits/suppression/reorder/deletion, and
selected-instance history parity. Preserve source revisions and truthful command
recording, atomic changes/undo, useful failure attribution, and independent
saved/reopened replay tests. Existing internal verification/evaluation jobs remain
supporting infrastructure; no dedicated repair workflow is needed to qualify
ordinary editing. Do not remove existing repair functionality or weaken validation.
Goal stays active with this revised completion scope.

Ordinary-editing continuation (2026-11-27): assembly rows now expose earlier
recorded-input editing through the existing form and shared cancellable
regeneration/commit dialog. The context menu also offers Edit inputs. Supported
forms include existing polymerization/linker fields plus gear ratio, recorded
non-null joint values/limits and instance/group names. Values come from versioned
inputs, not summary fields. Changed documents reject stale drafts. Apply privately
verifies/replays the full recipe, commits once and adopts only a matching refresh;
regeneration refusal leaves the published assembly unchanged. Legacy summary-only
editing retains its old latest-row restriction and gains no proof certification.

22 focused frontend checks pass, including earlier edits, stale inputs and failed
downstream replay. Actual app editing of F6 gear ratio with a later resolve command
changes downstream joint pose; undo/redo and existing history flows pass (22.3s
body). Root /tmp/__e2e__history-2ts37ez_ independently confirmed absent. Initial
exit smoke failed with Failed to fetch during fixture setup; an editor-module edit
during that run could have caused Vite reload (not confirmed). Frozen-source retry
passes (1 check,25.3s total); both /tmp/__e2e__smoke-0hrfq4ge and
/tmp/__e2e__smoke-mmepby03 independently confirmed absent. Lint/diff pass. No
main.js edits in this increment. Remaining: richer typed/reference/optional input
forms, selected-instance native command/history host (assembly.py still records
payload-free rows via _apply_part_mutation_with_feature_log), historical-prefix
suppression, remaining command/source admission and complete replay qualification.
Dedicated verification UI and repair workflows remain deferred by user direction.

Selected-instance recording continuation (2026-11-27): replaced the manual
_apply_part_mutation_with_feature_log path for instance overhang extrusion and
patching. Both now use the shared real part feature recorder on a detached
session/context, preserving open-part state and request stamps. Assembly wrappers
record complete versioned inputs, target IDs, stable part-feature identity/time
and real recovery state in one atomic assembly undo step. Extrusion uses the
ordinary native builder/candidate gate, identity seed and cluster-origin report;
patch uses the ordinary complete patch builder, including label synchronization
and targeted dependent sequence updates. No geometry algorithms/constants changed.

Part recorder accepts explicit output identity/time for these replayed commands.
Recovery gzip uses mtime=0 so replayed pinned source revisions do not differ merely
because compression ran at another wall-clock time. Existing source provenance
is retained; file-backed sources remain pinned revisions and no source file is
rewritten. New commands have dependency contracts and independent replay support.
Earlier extrusion length and recorded sequence/label fields are available through
the ordinary assembly history editor; omitted patch fields remain omitted.

87 unique backend checks pass across focused runs (5 instance,5 dependencies,
13 assembly proof,62 shared recorder,2 existing API), plus 15 frontend checks.
Tests reopen serialized histories, independently prove assembly and nested part,
edit upstream extrusion through downstream part patch/assembly rename, reject
dependent deletion atomically, replay rotation patch, and preserve unselected
sources/pinned file ownership. Real app instance extrusion edit + downstream label
and undo passes (16.4s body); existing gear/history flow also passes (24.8s body).
Two initial app attempts used a source part in the assembly tab, causing the normal
New Assembly multi-tab behavior; corrected fixture creates source through the
ordinary bundle endpoint in a separate owned document. No production workaround.
Roots /tmp/__e2e__history-d_xwhtgj, /tmp/__e2e__history-l8i6id26,
/tmp/__e2e__history-oh8o01vo independently confirmed absent. Assembly-exit smoke
passes (1 check,23.7s total), root /tmp/__e2e__smoke-b1iowlhg independently absent.
Lint/diff pass; no task changes to main.js.

Still unfinished: general selected-instance native history editing/suppression/
reorder/dependencies, richer input/reference forms, historical-prefix suppression,
remaining recording/source-update paths and complete downstream replay coverage.
The old payload-free overhang path is removed; legacy existing rows are not
retroactively certified. Full revised goal remains active.

Historical-prefix suppression continuation (2026-11-27): assembly suppression
and unsuppression now work from F0 and intermediate history positions through
the shared dialog/jobs. Internal proof can explicitly assess the displayed
prefix while validating every saved command definition/source; its result is
labelled displayed_prefix_reproducibility, not full-history proof. Ordinary
verification retains its latest-history requirement. Evaluation independently
regenerates and verifies the unchanged full recipe before evaluating the toggle;
no recovery snapshots are consulted. A corrupted displayed prefix or invalid
unseen command/reference refuses publication. Commit retains the original
displayed source/revision binding, returns to the history end and adds one undo
step; undo restores the original cursor and model. Remembered representation/
visibility choices survive even when F0 omitted those instances entirely.

35 unique focused backend checks pass (22 evaluation/jobs,13 proof), plus 17
frontend checks. Tests cover suppression/unsuppression at -2,0,1; snapshot decoding
is forbidden during evaluation; saved candidate independently verifies. Browser
F0 suppression/undo/redo passes (8.5s body). Root
/tmp/__e2e__history-pyjtwp24 independently confirmed absent. Assembly-exit smoke
passes (1 check,24.4s total); /tmp/__e2e__smoke-kfenked3 independently absent.
Lint/diff pass; no main.js edits. Historical-prefix suppression is no longer an
outstanding item. General selected-instance history controls, broader input forms,
remaining recording/source-update paths and full replay qualification remain.
Verification UI and dedicated repair workflows stay deferred by user direction.


Selected-instance checkpoint (2026-11-27): ordinary selected-part edit, suppression,
reorder and deletion now use native part evaluation inside an isolated assembly
transaction. A recorded assembly-instance-history-change preserves the original
source revisions and regenerates the part suffix and dependent assembly constraints;
later assembly history edits can replay this command. Publication remains revision
bound, independently verified and one undo step. The selected-part menu shares the
existing dialogs, including dependency inspection; supported native snapshot inputs
use the ordinary field editor. Removed the unreachable metadata-only deletion branch
in the assembly target handler. No main.js task changes (LOC delta 0).

Checkpoint validation: 52 focused backend tests pass against an isolated export of
the staged commit (including native selected-instance changes, evaluation and
verification jobs, shared part dependencies). This check caught an initially omitted
shared supervisor adapter; it was included and the complete selection passed.
Running-app selected-part edit/downstream label, dependency view, delete and two
undos pass (50.2s body). Assembly-exit smoke passes (17.6s body). Scratch roots
/tmp/__e2e__history-oiwrggms and /tmp/__e2e__smoke-qjmvoiee independently absent.
All 38 focused frontend tests also pass against the staged export.
Lint passes. Full-suite watermark unchanged.

Still unfinished: broader typed/reference/optional input forms, selected-part
historical-prefix and child controls, legacy embedded part-context paths, remaining
silent recording/source admission/update paths, scale qualification and complete
replay coverage. Dedicated verification UI and repair workflows remain deferred;
internal verification remains critical. Persistent goal is paused, not complete.
