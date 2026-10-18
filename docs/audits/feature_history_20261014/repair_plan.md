# Standard-part repair implementation plan

Audited October 15, 2026. P5a backend repair evaluation/publication and its
numerical integration regressions pass. P5b has a bounded direct-ID selection
catalog and isolated nonpublishing job API. P5c has shared schemas and a durable
definition/source fingerprint; Design persistence and host lifecycle remain open.
P5d remains pending.
Assemblies are deferred; desktop
and part-mode VR should share the standard-part repair contract.

## Existing foundation and exact gaps

| Area | Reusable implementation | Missing behavior |
|---|---|---|
| Regeneration | `backend/api/part_recipe_edit.py::regenerate` executes native definitions and replaces recovery data; `part_recipe_repair.prepare_repair` reuses it for broken inputs | Typed replacement discovery and persistent drafts remain open; ordinary editing retains its old-source proof gate |
| Isolated work | `part_evaluation.py`, `part_evaluation_worker.py`, `part_evaluation_jobs.py` provide repair alongside bounded candidates, cancellation, revision checks and one-time commit | On-demand visual comparison and numerical-upgrade UX remain open |
| Diagnostics | `ReferenceResolutionError` supplies typed identities and parameter paths; proof reports the first failure and possible dependents | No replacement-selection API or persistent repair draft |
| Dependencies | `part_dependencies.DependencyIndex` incrementally builds a conservative graph | Most topology commands remain barriers; graph descendants are possible dependents, not proven failed commands |
| Successful state | Failed edits preserve the live document; `ReplayPrefix` retains one independently rebuilt prefix per request | No separately identified healthy comparison state or draft lifecycle |
| UI | Timeline, specialized editors and cascade/revert dialog | No verification controls or native repair badges; legacy later-snapshot/eviction restrictions remain |
| Error transport | Backend issues contain structured reference information | `frontend/src/api/client.js::_request` stores only a formatted `lastError.message` |

`feature_evaluation.py` optimizes recovery/scrubbing using recorded state. Its
analysis is not evidence of native regeneration and must not become the repair
executor. Existing snapshots may support a labelled comparison view; they must
never provide command inputs or prove a repaired model.

## P5a — repair transactions

Extend the existing evaluation job with an explicit repair operation. Retain the
ordinary edit requirement that its source reproduce; repair has a different
purpose and must not silently relax that gate.

- Address features and routing children by stable IDs, with expected revision.
- Accept a bounded batch of definition patches or typed reference replacements.
  Each replacement includes its parameter path and expected old value.
- Validate the explicit root and patched command contracts, then derive the
  candidate solely from those inputs. The old materialized model need not match.
- Preserve output identities, contract versions and identity namespaces. Missing
  roots, unsupported legacy contracts and geometry injection remain unsupported.
- Publish only after the complete patched recipe executes, using the existing
  revision-bound commit. Keep integrity findings separate from reproducibility;
  successful replay alone is not scientific or geometric qualification.
- Retain the ordinary work budget. Expensive supported recipes use the explicit
  long-operation policy; repair must not create a second worker/queue lifecycle.

**Completion gate:** a saved native recipe with a missing reference can be
repaired; poisoned snapshots/diffs have no effect; cold replay reproduces the
result; stale, cancelled, failed and oversized work leaves model/undo/redo intact.

### Explicit numerical-contract upgrade

P4 numerical commands pin implementation and runtime identity. This deliberately
makes an older recipe unverified when covered code or its numerical environment
changes; ordinary parameter editing must not silently replace those pins.
The current manifests conservatively include shared model code, so an unrelated
schema addition can also require an upgrade. Old executable engines are not yet
bundled. Reproducibility on another installation is therefore conditional on
availability of the recorded contract, not a permanent archival guarantee.

Add a separate, explicit repair-draft action for upgrading a supported numerical
contract. The server chooses current pins for the same recognized source/solver
family; callers cannot inject an arbitrary digest or relax source admission.
Regenerate from the explicit root and authored definitions in the existing
bounded worker. Show changed numerical provenance and compare resulting geometry
before revision-bound publication. Preserve stable output identities. Keep the
old revision and pins available for reversal; never label the new evaluation as
proof that the older engine produced the same output. Unknown algorithms or
unsupported source families remain unverified. This is required P5 repair work,
not an automatic load migration. Longer-term executable-version retention can be
added independently, following Onshape's explicit versioned FeatureScript imports.

## P5b — reference selection and diagnostics

Report the first failed feature, its structured references, the successfully
replayed prefix and later rows as **not evaluated**. Preserve the distinction
between possible dependents and failures established by native execution.

Resolve replacement candidates against the rebuilt state immediately before the
target feature. Final-state geometry can contain future or stale objects and is
not a valid selection context. Begin with exact typed replacements and existing
builder checks; defer geometric similarity matching. Future propagation must
enumerate reviewed reference paths, never recursively replace matching strings.

`preserve_proof_identity` deliberately protects `_generated_scope`. Initially,
reject replacements outside that closed scope. A later scope-aware contract can
update retained input references while preserving group identity and rechecking
closure; unrestricted scope editing is not a repair mechanism.

**Completion gate:** wrong-family, future, ambiguous and invalid-domain targets
are rejected; output identities and scope boundaries cannot be overwritten;
multi-reference repair reports exact affected features without silent deletion.

## P5c — drafts and comparison state

Persist unresolved definitions/proposed changes in a versioned, bounded repair
draft containing command inputs and a base fingerprint. Preserve the published
model until regeneration succeeds. A pending draft must be visible and cannot
inherit the published model's verification status.

Distinguish the last successfully regenerated model, a freshly replayed prefix,
and saved geometry of unknown validity. A broken loaded document does not become
"last good" merely because geometry exists. Reuse immutable project revisions
for historical comparison where available; do not duplicate full design payloads
for every diagnostic row.

**Completion gate:** failed definitions survive draft save/reload; source changes
invalidate or explicitly rebase the draft; successful repair is one undoable
publication; pending/unverified geometry is never presented as verified output.

## P5d — desktop and part-mode VR

Preserve structured API errors. Add explicit Check/Rebuild, cancellation,
revision-bound status, feature badges and a repair panel with a typed replacement
picker. Enable native history editing using server capabilities even when later
snapshots exist or recovery bytes were evicted; preserve legacy restrictions for
unsupported history. Use a small shared controller/view module instead of adding
another workflow to `main.js`.

Poll compact status only. Fetch comparison/preview geometry on demand. Capture
the originating document identity so tab switching, closure and late responses
cannot update another document. Keep assemblies outside this increment.

**Completion gate:** UI tests cover structured diagnostics, unevaluated rows,
stale/cancelled results, preserved geometry and no automatic full-geometry polling;
running-app desktop and available part-mode VR checks are recorded explicitly.

## Performance boundaries

Reuse one independently replayed prefix inside an evaluation, then rebuild its
suffix. Defer independent-suffix reuse until complete effect contracts and
equivalence tests justify it. The current conservative graph does not establish
that later topology commands can be skipped.

Keep replay, full hashing and graph construction off rendering, hovering,
scrubbing and ordinary publication paths. Compact diagnostic caches, if needed,
must be bounded and keyed by exact document/session revision and contract/runtime
manifest. Invalidate cheaply on revision changes; do not rehash the model while
polling. Reuse existing worker admission, result size limits and expiration.

**Completion gate:** measured capture, prefix/suffix execution and retained-memory
costs for small/representative large recipes; no added proof/graph calls on ordinary
edit or scrub paths; cancellation reaps the worker before admission is released.

## Primary CAD precedents

These are documented product behaviors, not claims about vendor internals.

- Onshape shows a healthy historical comparison, highlights missing references,
  recommends repairing from the first failure downward, and supports one-to-one
  replacement with optional downstream propagation. This supports a deliberate
  reference-repair workflow rather than mandatory cascade deletion.
  [Repairing](https://cad.onshape.com/help/Content/Document/repairing.htm)
- SOLIDWORKS presents feature-specific errors and edit links; warnings and rebuild
  failures have distinct meanings. [What's Wrong](https://help.solidworks.com/2023/english/SolidWorks/sldworks/HIDD_NEW_WHATS_WRONG.htm?format=P&value=)
- SOLIDWORKS fillet repair highlights missing references and attempts replacement
  where suitable physical geometry exists. Its sketch relation editor rejects
  inappropriate replacements and limits automatic repair to supported cases.
  [Missing fillet references](https://help.solidworks.com/2021/english/Solidworks/sldworks/t_reparing_missing_references_fillets.htm),
  [Relation replacement](https://help.solidworks.com/2025/english/Solidworks/sldworks/HIDD_DVE_SK_EDIT_RELATIONS.htm)
- Onshape documents regeneration of the changed feature and subsequent features,
  and exposes regeneration timing. Prefix reuse plus suffix regeneration is a
  reasonable first performance strategy; a general incremental solver is not a
  prerequisite for this repair increment.
  [FeatureScript regeneration and profiling](https://cad.onshape.com/FsDoc/debugging-in-feature-studios.html),
  [Feature list controls](https://cad.onshape.com/help/Content/PartStudio/features_and_parts_lists.htm)

The original audit was read-only. Subsequent implementation and focused results
are recorded in `implementation.md` and its validation records. The completion
gates above remain the overall plan; the initial selection catalog does not yet
cover topology-domain, compound, generated-scope or ownership-aware selectors.
