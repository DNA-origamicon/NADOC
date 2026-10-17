# Native nanoparticle connection contract — phased status and next scope

Reviewed 2026-10-15. Pending CRUD and pending-version-preserving thiol motion are implemented and checkpointed; their evidence appears below. Applied lifecycle remains the next tests-first proposal. Scientific calculations and assembly behavior are unchanged. The visible overhang panel calls the connection-version routes (`frontend/src/ui/overhang_connections_panel.js:394,401`); the older direct surface-strand bind is exposed by the client/test API but is not this panel's action.

**Checkpoint sequencing refinement:** implement pending create/rename/delete
first, as specified in [the finite closure map](remaining_standard_part_checkpoints.md).
The complete application contract below remains a later increment. Pending
contracts and routes are implemented; their original red dossier is
`tests/test_part_pending_np_connections.py`. The new lifecycle ownership red
target is `tests/test_np_applied_lifecycle_ownership.py` (ISSUE-92).

## Official CAD precedent and the NADOC decision

| Documented behavior | Consequence for this proposal |
|---|---|
| Onshape distinguishes entities in a current modeling context from queries that describe how to resolve a selection. Its historical queries identify geometry by creation history; robust/tracking queries support identity-preserving changes. [Modeling](https://cad.onshape.com/FsDoc/modeling.html), [query library](https://cad.onshape.com/FsDoc/library.html#module-query.fs) | Store the chosen particle/owner/strand/overhang identities and resolve them against the rebuilt prefix. A moved strand retains identity; its current carrier is derived from that owned strand, not guessed from position or an obsolete carrier ID. This is an application-specific analogy, not an implementation of Onshape's topology engine. |
| Onshape warns that UI selection filters and maximum pick counts can cease to hold after upstream edits. Feature execution must check the actual query result. [Feature UI](https://cad.onshape.com/FsDoc/uispec.html#queries) | Validate exact cardinality, ownership, compatible ends and complete referenced resources again during replay; a valid picker result is not enduring proof. |
| Onshape repair exposes a previous healthy state to explain a missing reference and lets the user replace it; replacement can propagate downstream. [Repairing](https://cad.onshape.com/help/Content/Document/repairing.htm) | Keep saved relocation topology as restoration/diagnostic state, distinct from live references. Missing or changed owners produce typed parameter-path diagnostics; do not silently bind the nearest overhang. |
| SOLIDWORKS can retain sketch-based children after deleting a parent, mark the missing plane reference, and offer repair. [Sketch Plane References](https://help.solidworks.com/2021/english/solidworks/sldworks/t_Sketch_Plane_References.htm) | Preserve an invalid definition for repair or explicitly cascade its actual failed dependents. Neither a recoverable old snapshot nor a retained child means the current design regenerated successfully. |
| SOLIDWORKS exposes persistent object references across sessions. [Persistent Reference IDs](https://help.solidworks.com/2023/english/api/sldworksapiprogguide/overview/Persistent_Reference_IDs.htm) | Stable typed identity is appropriate; it must still resolve to a valid current owner. The documentation does not promise survival of every topology change. |
| Onshape represents a feature as a function call with parameters and regeneration as executing the Part Studio build function. Custom feature types use the same mechanism. [FeatureScript introduction](https://cad.onshape.com/FsDoc/intro.html) | Scripts/agents should construct the same input-defined native rows used by the UI. A third-party script is not inherently invalid; geometry supplied without a regeneratable definition is insufficient. |
| SOLIDWORKS macro features store parameters and selections, acquire dependencies on those selections, and rebuild from them. Their output entities require reproducible identification. [Inserting Macro Features](https://help.solidworks.com/2026/english/api/sldworksapiprogguide/Macro_Features/Inserting_Macro_Features.htm), [Rebuild Function](https://help.solidworks.com/2020/English/api/sldworksapiprogguide/Macro_Features/Rebuild_Function.htm) | Native connection rows must record selected resources and stable child identities, not emitted geometry. Runtime creation of arbitrary unrelated features inside a callback is not this contract. |
| Onshape requires uploaded external data for FeatureScript references and distinguishes workspace references from deliberately updated version references. [Imports](https://cad.onshape.com/FsDoc/imports.html) | This source-free gold slice needs no external source. Future coated/catalog variants must retain their existing explicit source/version contracts; no replay-time catalog or filesystem fallback. |

The documentation supports editable, deterministic feature construction and explicit repair. It does **not** establish an Onshape/SOLIDWORKS prohibition on LLMs or whole-model custom features. NADOC's requirement that agents use granular editable operations is a separate product/admission policy. Registering these replay contracts does not automatically expose them in the public batch catalog or establish authentication/trust policy.

## Original audit baseline and concrete gaps

This is the pre-implementation inventory. The pending registration/recording
gaps are closed below; application/ownership gaps remain current unless stated.

- `api/part_proof_commands.py:58` recognizes exact integer `_proof_version == 1`, strips scope wrappers for strict schema admission, and treats unknown contracts as unknown. None of the three NP connection-version kinds or `nanoparticle-strand-bind` belongs to its registered proof families. The strings already exist in `core/models.py:2015`; persistence support is not execution support.
- `api/routes_nanoparticles.py:827,870,894` currently logs IDs without all choices. Creation omits selected strand/overhang, name, variant, creation time and apply choice; patch omits the patch itself. `_set_np_version_applied` at line 596 generates a new Duplex identity/time implicitly, computes register and placement, stores the exact attachment joint, and relocates through the existing duplex builder.
- `core/duplex.py:360` already accepts `identity_seed`, propagating deterministic transient-binding, forced-ligation and duplex-cluster IDs. Its restoration data has the exact typed codec in `core/part_saved_topology.py:52,89`. Reuse these; do not introduce another saved-geometry input format.
- Relocation can remove the old carrier (`core/binding_relax.py:443`), while `_set_np_version_applied` leaves `NanoparticleSurfaceStrand.helix_id` at that old carrier. The strand's domain and auxiliary OverhangSpec have moved. `core/part_scope_references.py:110` treats the surface record's carrier as a live helix reference, and `routes_nanoparticles.py:447` flags its absence. This is a real ownership inconsistency, not a reason to weaken live reference checks.
- `_sync_np_applied_bindings` at line 478 rewrites every surface record using applied versions. It can clear an unrelated legacy direct-bind marker. Native execution must either restrict synchronization to declared affected ownership or reject mixed unsupported ownership before running it.
- The old direct bind at line 959 deletes the radial helix and updates the surface record but does not update/remove the auxiliary OverhangSpec or give the new binder its auxiliary domain tag. It must not be certified unchanged. `two_np_build.py:115` also uses the same old kind for a different snapshot-only “prepare handles” operation. A new contract marker must never promote that receipt.

## Proposed commands and selectors

### First checkpoint: pending metadata only

All three kinds require exact integer `_proof_version=1` and
`nanoparticle_connection_version=1`, plus bounded `nanoparticle_id`,
`conjugation_id`, `strand_id`, `overhang_id` and `version_id`. The first four
selectors must resolve to the exact selected source-free gold/unbound thiol
owner and ordinary target. Patch/delete repeat them and compare them with the
saved version, so replay cannot silently follow a version whose ownership has
changed. Create adds final `name`, finite nonnegative `created_at`,
`connection_type="direct"`, `direct_variant` and strict `applied=false`.
Patch adds a nonempty final `name`; delete adds no other inputs.

No metadata-only operation needs a child namespace: the host records its explicit
version UUID and creation time before publication. A `history_seed` and child
identities become necessary only in the later materialization contract. Creation
protects `version_id`, `created_at` and the discriminator during feature edits;
patch/delete version IDs remain editable consumer references. Native schemas
forbid `duplex_id`, saved topology, coordinates, engine pins and application flags
on rename/delete. The selected stored version must have no applied/relaxed state,
duplex, residual or retained constraint fields.

Use the existing 5'/3' attach and polarity rules unchanged. Pending metadata does
not invoke geometry fitting, duplex placement, or relaxation and does not require
a numerical runtime pin. A metadata deletion removes only its selected version;
it must **not** call `_sync_np_applied_bindings` across all conjugations. That
legacy helper clears unrelated direct-binding markers even for an unapplied
deletion. Preserve unrelated legacy metadata without claiming that its entire
prefix is native or reproducible; complete-root proof still determines that.

The original 49-case dossier uses the already registered bundle, overhang
extrude/sequence, gold and thiol commands to build its owner/target from an empty
root. It covers pending create/rename/delete, both chemical ends and variants,
exact saved roundtrip, fresh-worker replay with poisoned recovery, upstream gold
resize, protected output identity, typed dependency resources/paths, deleted
target cascades, retained materialization-state refusal, strict schemas, actual
visible route recording/undo and the unrelated legacy-binding deletion defect.
One existing-native fixture proof and existing refusal cases act as controls.
Root recorded the red baseline: **31 failed, 18 passed in 3.29 seconds**. Unknown
contracts account for most failures; the actual pending-delete route also
reproduced clearing an unrelated legacy direct-binding marker (ISSUE-90).

The implementation now registers these three strict contracts and records the
eligible visible routes under the existing lock-owned recording transaction.
Selection, current source/revision checks and final identity/time allocation
occur in that same critical section. No candidate survives a lock release before
publication. The route keeps a private history list for the recorder's append;
the common failure-atomic recorder owns undo, revision and recovery. Missing
references in supported scope fail explicitly. Multiple ownership records,
unspecified old endpoint mappings, applied/retained state and opaque reference
families retain unverified compatibility paths before native execution.

Native scope is one exact radial conjugation, at most 128 selected particle
handles, and the existing 10,000-node/256KB operation allowance for reference
inventory work. The preflight uses the shared reference schema's identity,
reference, child and special-codec fields, including unrelated nested surface
rows, cluster membership and saved-topology JSON; it ignores plain atoms,
coordinates and user prose. Each occurrence is charged because the resolver
also visits each occurrence. Oversize/opaque scope returns to the explicitly
unverified compatibility path before native execution; malformed supported
references still fail rather than falling back after evaluation. This is a
conservative work allowance, not authoring capture or a latency guarantee.
The part topology barrier remains because shared
postprocessors still run. Generated compound scopes are explicitly unsupported.
Additional regressions cover stale requests before IDs/time/build, a rejecting
non-reentrant lock, exact one-time defaults, document isolation, rollback after
encoding/publication/cancellation and legacy ownership boundaries. Root's first
corrective run passed **58 cases in 4.30 seconds**. The final pending target,
including nested reference budgets, passed **66 cases in 4.20 seconds**; the
edit-identity target separately passed **7 cases in 2.72 seconds**. The later
editing regression set passed **95 cases in 3.58 seconds**, including those
seven identity cases, for **161 distinct green cases** across pending and
editing targets. See `validation_pending_np_connections_p4.json` for exact
scope. The later applied workflow remains a separate contract; no global limits
have changed.

The initial three-repeat HTTP measurement completed all ten native/compatibility
cases and all fifteen native lifecycles. Four small native cold proofs passed;
the larger fixture's final cold capture refused the unchanged cooperative 25 ms
allowance after valid route samples. This refusal remains in
`benchmark_pending_np_connections_initial.json`. The subsequent thirty-repeat
run completed all ten cases, all 150 native lifecycles and all five independent
cold proofs, with cleanup confirmed; see
`benchmark_pending_np_connections_repeated.json`.

**Correctness passed; latency is not qualified.** In the larger background,
native route medians were 23.38–24.12 ms versus compatibility medians
17.18–17.63 ms. The maximum native request was **88.57 ms**, recording lock
**82.35 ms**, and concurrent lightweight request **86.30 ms**. Compatibility
also showed a 75.41 ms request / 69.48 ms recording-lock maximum. These results
cannot establish the cause of an outlier; no GC callbacks or per-stage timing
were captured. The old report's `qualified` flag tested correctness/cleanup
only, not a latency threshold. The harness now emits separate
`correctness_verified` and `latency_qualified` fields and states that its exit
status tests correctness only. Further optimization/measurement is required
before making a no-regression claim.

The following prepared-context increment removes duplicate `_bounded` and
`typed_ownership_supported` walks from route preflight and pure build. The
ordinary recorder does not call the proof dependency graph or regenerate the
prefix. It now prepares the bounded typed inventory once under the existing
lock and passes it privately to a shared build core, bound to the exact source
object. Standalone/cold build still prepares its own inventory; no public
validation-skip flag, cross-revision cache or proof authority was introduced.
This context is valid only within that locked operation, not a source snapshot.
Root passed **78 cases in 4.55 seconds**, including a **1.12-second real cold
proof**, across pending CRUD, preparation-boundary and benchmark-probe tests.
These overlap the prior 66-case pending target and are not 78 additional cases.

`benchmark_pending_np_connections_prepared.json` records the subsequent
30-repeat diagnostic run: all ten cells completed, all 150 native lifecycles
and five independent cold proofs passed, and cleanup succeeded. Each of the
450 measured native requests called the three inventory leaves exactly once;
no diagnostic events were dropped. In the larger background, native request
medians were **20.10–21.24 ms** versus compatibility **17.26–17.89 ms**. The
earlier native range was 23.38–24.12 ms. These sequential measurements show a
useful improvement; instrumentation and run variability prevent a precise
causal speedup claim. Median native leaf totals were **2.87–2.90 ms**.

**Latency remains unqualified.** Maximum native request/recording-lock/light
request times were **75.79 / 70.13 / 72.57 ms**. Nine native requests and seven
compatibility requests overlapped generation-2 collection. Some long native
samples collected inside `typed_ownership_supported`, others during later
recording work, and the largest native request collected in phase `other`
while its recording lock lasted 15.88 ms. Compatibility likewise reached a
74.94 ms request and 69.47 ms recording lock with collection overlap. These
intervals are correlation, not a counterfactual time saving: do not subtract
them from user-visible latency, disable GC, retry, or raise limits. The report
retains every generation-2 sample, action maxima, all errors and aggregate
correlations while pruning repetitive samples and generated identity maps.

Existing snapshot copying, recovery encoding, reconciliation, ligation retry
and validation remain intact. The next performance step belongs to the shared
source-isolation/publication work: reduce avoidable allocations and measure
actual lock/light-request tails with the reusable bounded runtime probe.
No broader recorder rewrite is justified solely by these leaf measurements.

The initial implementation exposed unnecessary numerical pin coupling:
`feature_identity.py` is a duplex-relax-v1 manifest member for `identity_factory`,
but also contains the unrelated editing protection table. Adding three NP rows
to that table would make all previously pinned duplex-relax features report
`engine_mismatch` without any numerical change. The correction keeps that file
byte-for-byte at its existing SHA-256
`063a5eb49c09c9335775bc6f66c83a24d667b28ad721be739796f29b3a7dc730`.
`part_edit_identity.py` wraps its existing protection base and adds new editing
families; the three editing consumers use the wrapper. No numerical consumer,
manifest, accepted hash, runtime pin or upgrade policy changes. CPD and coating
manifests are also unaffected. An exact source/hash and manifest regression pins
this boundary; future genuine engine changes still require explicit upgrading.

The prepared-context checkpoint leaves an ordinary-workflow seam: dragging or
resizing a particle after creating a pending candidate uses legacy recording.
The following motion increment addresses that seam. Applied/retained state and
other incoming consumers stay outside its native scope. Graft replacement/removal
likewise needs an explicit dependent-version deletion policy; no silent cascade
is introduced.

### Next bounded increment: pending candidates through thiol motion

**Implemented; focused correctness validation passed, latency unqualified.** Extend the
existing `nanoparticle-patch` / `thiol_version: 1` contract with
`pending_connection_version_ids: list[str]`, defaulting to an empty list for
existing no-connection rows. The list is unique, identities retain the existing
1–256-character bound, and the proposed first allowance is 128 versions. It
selects exactly every current connection version on the particle, including
multiple alternatives for the same handle. It does not select unrelated
particles' versions. Omitted, missing, extra or foreign selectors fail with
typed paths rooted at this field; an old row cannot silently accept a newly
introduced consumer.

Each selected version must be unapplied and unrelaxed, with no retained duplex,
residual or constraint state. Validate its exact owned handle, ordinary target,
chemical polarity and recorded endpoint mapping. Legacy nullable endpoint
metadata remains unsupported. Reuse the pending CRUD validators through one
shared identity/reference inventory rather than executing the CRUD builder
once per version. Preserve its existing reference-work ceiling before expensive
traversal; do not add one allowance per selected version. Existing thiol handle
and nucleotide ceilings remain unchanged.

After validating the versions, include their identities in the retained
ownership closure used by the incoming-reference guard. This allows their own
known references while still rejecting external consumers of any selected
resource. Call the unchanged `replace_gold_nanosphere` exactly once; every
version field and every handle identity is preserved. Register explicit version
reads, retain the topology barrier, and add no version writes or imported source
provenance. This does not enable graft replacement/deletion, application,
relaxation, bound motion or compound generated scopes.

The existing live recorder resolves the pending selector inside its locked
callback together with conjugation IDs. Unsupported applied/opaque/oversized
legacy scope is classified before native work; broken references within the
supported scope fail atomically and cannot fall back after evaluation. The
ordinary route must record one native row, one revision and one undo entry for
each drag/resize. Route admission outside the lock is only a hint: the locked
builder rechecks the actual current source and complete selector.

`tests/test_part_thiol_pending_motion.py` is the red target. It covers exact
native math parity for move/pose/resize combinations, complete metadata and
unrelated particle retention, selector/schema failures, applied/retained
refusals, external consumers, missing targets, typed dependencies, native root
cold proof with poisoned recovery, geometry-changing history edits, deletion of
a selected producer, actual ordinary route undo/redo, locked selector capture
and failure atomicity. Root recorded the expected red baseline: **26 failed,
5 passed, 31 cases in 3.18 seconds**. Four added boundary tests cover 128
alternatives with one prepared inventory/backing map/owned-handle resolution,
custom target identity polarity parity, compound-scope refusal and oversized
reference admission before indexing. No tests have been run by the authoring
agent; the parent serializes validation.

Root's combined run passed **204/204 cases in 9.09 seconds** across the new
35-case motion target and eight existing thiol, native proof, pending ownership,
preparation and edit-identity regression files. This includes real spawned
motion replay, a geometry-changing historical edit, ordinary route undo/redo
and compatibility boundaries. These targets overlap prior validation; do not
add all 204 cases to the earlier distinct-test count.

The pure motion builder reuses the pending command's prepared reference table.
Its target map scans domains once; after validating unique backing, it invokes
the unchanged native polarity helper on that target strand. Existing no-version
rows retain their original admission path. A document containing NP versions
uses the bounded reference allowance even when another particle owns them;
this conservative whole-document check avoids unbounded incoming-reference
work. The live route's preliminary compatibility predicate is not a reusable
receipt: its locked builder independently validates the actual source. No
unlocked prepared index survives into publication.

`scripts/benchmark_pending_np_connections.py --motion` retains every existing
baseline cell and adds move/resize lifecycle cells at the same measured scopes.
Each adds two native rows before pending deletion; the unchanged particle
replacement helper supplies the complete authoring oracle outside timing.
Actual revision/undo/row counts, exact pending selectors, geometry, metadata,
fresh worker proof, capture refusal and concurrent lightweight requests remain
separate checks. The whole-run diagnostic cap is unchanged and explicitly
reports any dropped events. No limits, retries or GC policy changes.

The initial root-run motion diagnostic (`benchmark_pending_np_motion_initial.json`,
three repeats) completed all **20 cells**, including 30 native lifecycles and
**10 independently verified cold proofs**. All ordinary captures and cleanup
checks passed; 1,668 GC and 648 native-stage events were retained with no drops.
The five motion-native cold captures took 2.30–9.86 ms; their spawned proofs
took 1.21–1.40 seconds. Maximum recovery across both modes was 673,940 bytes.

For the larger DNA fixture, native move/resize request medians were
24.56/25.37 ms versus compatibility's 18.84/17.48 ms; recording-lock medians were
15.91/16.57 ms versus 12.38/11.75 ms. A native resize reached 59.65 ms, with a
54.84 ms recording lock. Across the whole native lifecycle the maximum request,
lock and concurrent lightweight request were 75.90, 69.89 and 73.62 ms. The
largest delete overlapped a 55.21 ms generation-2 collection, and compatibility
also had collection-overlapping outliers. Correlation is not an isolated cause
and no time is subtracted from user-visible latency. **Correctness is verified;
latency is unqualified.** Three repeats cannot establish a tail guarantee; the
shared mutable recording/copy path remains the appropriate follow-up, without
raising limits, retrying refusals or changing collection policy.

### Later checkpoint: explicit application

**Current tests-first refinement:** preserve the pending-v1 schemas rather than
widening formerly unknown sparse applied receipts. The proposed separate
`nanoparticle_application_version: 1` discriminator uses the same three kind
strings and also requires `_proof_version: 1` and
`nanoparticle_connection_version: 1`. Presence of a malformed application marker
must fail closed. An unmarked pending row keeps exactly its existing semantics.

The application envelope repeats the exact particle/conjugation/strand/target
selectors and adds the explicit `handle_overhang_id`, UUID `history_seed`, exact
nullable `prior_duplex_id` and unique bounded `conflict_version_ids`. Apply owns
an explicit fresh `duplex_id` and finite `duplex_created_at`; deterministic child
cluster/ligation IDs come from the existing `relocate_duplex(identity_seed=...)`
factory. Unapply/delete accept no new output geometry or saved topology. Protect
new output/discriminator slots through `part_edit_identity`, leaving pinned
`feature_identity.py`, `duplex.py` and numerical manifests byte-stable.

Start with one source-free uncoated gold conjugation and at most one applied
version for its particle. Replacing that version with a competing pending
candidate is useful and remains explicit. Another particle's applied conflict,
relaxed state, unclassified ownership, ambiguous endpoint, competing nonselected
binding/duplex, or external consumer of a removed helix/cluster remains outside
this first scope. Pending conflicts are selected exactly; missing/extra entries
must not silently change the deletion set after an upstream edit. Preserve the
existing 10,000-reference-work ceiling and 128-version bound, with an additional
conservative emitted-nucleotide/path-work admission before fitting. Qualify
actual 1/16-handle operations before selecting the live geometry ceiling; the
50,000-base thiol motion bound is not a performance certificate for application.

Use a separate exact bound-ownership validator. It checks the current surface
record, strand/domain and auxiliary OH against the live duplex and typed
`part_saved_topology` restoration owner. Historical helix identities may be
absent live, but restoring them cannot overwrite a foreign live identity.
Unapply must not silently remove an externally referenced duplex child cluster.
Do not weaken the existing unbound radial resolver or treat unknown saved data
as a valid restoration input.

ISSUE-92's eight-case dossier precedes production changes. The actual helper
currently leaves active constraint root/radius after unapply or displacement,
globally synchronizes unrelated legacy direct bindings, and leaves a stale
surface carrier after relocation. Correct only affected version/handle metadata:
clear inactive derived constraints, refresh the carrier from its unique live
strand/domain/OH, and explicitly exclude bound handles in the generator's free
handle selector. These corrections preserve the existing geometry math and
selection intent. Root recorded **eight failures in 2.85 seconds**, matching the
eight targeted defects/transitions. Checkpoint `91756139` records the narrow
metadata/planner correction with **181 distinct passing cases**, including all
eight dossier cases. An old auxiliary-target assertion was updated to the exact
native `422 invalid_selection` diagnostic: the pending adapter and create-route
AST were unchanged from `a24b60b7`, so this was not an application regression.
Only the selected handle and actually displaced applied/retained handles
synchronize; a merely pending alternative cannot erase an unrelated legacy
binding. Ambiguous legacy carriers remain visible rather than guessed.

The first application red run exercised two native-oracle cases plus the real
cold lifecycle: three expected failures (missing adapter/unregistered contract)
in a combined 4.04-second run. After extraction and the pure adapter, root ran
both new targets: **42 passed / 6 failed in 4.36 seconds**. Every geometry oracle,
real cold rebuild, upstream geometry edit and refusal case passed; the six
remaining failures were the intentionally deferred three typed dependency and
three output-identity integrations while the OH checkpoint owned those files.
These results do not qualify the ordinary application route or latency.

The current implementation reuses the existing pending parse/build dispatch
through presence of `nanoparticle_application_version`. The shared kernel has a
local domain exception translated by thin compatibility wrappers, without
importing FastAPI. Pending-only schemas and OH pending integration remain
separate. No model or numerical-manifest files change.

The initial pure scope is at most **16 handles and 4,096 emitted bases**, plus
the existing 10,000-reference-work and 128-version ceilings. These are
conservative admission bounds pending measurement. It refuses residue assets,
protein/coating attachments, extensions, deformations, flexible/Join state and
other unqualified geometry families. Stored historical helices are charged
before parsing/restoring; restoration may not replace a live helix or remove a
child cluster with incoming consumers. Directional residue checks protect
shared target helices, and the unchanged native topology planner checks the
prospective interval before fitting. No sampled geometry is an authored input.

A newly identified coverage limit is explicit: the legacy native planner can
shorten a handle longer than its target to the paired window. The native recipe
adapter refuses that case before geometry if the planned interval changes the
handle nucleotide count. A shorter handle on a longer target retains the exact
native oracle and restoration path. This is unresolved unequal-length
application coverage, not a formula fix or P4 completion; compatibility math
remains unchanged. The dependency/identity additions and two interval tests
passed: all **50 new cases** were green in the root's broader **289 passed /
1 failed in 247.99 seconds** run (35 deprecation warnings). The sole failure
was the existing `generator_connections` platform/HONEYCOMB/3 fit-collision
case. Root reproduced the same collision in 18.64 seconds using all seven
pre-extraction route helpers from `acad1d51` in memory with the same current
generator/core and retained random identity defaults. This is a targeted
historical-helper comparison, not a whole-binary baseline; the evidence is
`np_application_generator_baseline.json`. The generated multi-anchor coverage
debt remains explicit; it does not justify changing the placement algorithm.

Peer review then identified two admission gaps. Root's additional two-case
red run failed as expected in 2.81 seconds: aggregate loop descriptors were
traversed beyond the allowance, and an opposite-direction domain on the target
strand could keep the selected radial carrier live after application. The
narrow correction charges each loop-list length before traversing it, checks
inserted-base work immediately, and requires exclusive strand ownership of
each affected radial/restored carrier regardless of direction. These guards
run before fitting. Root's corrected focused run passed **231 cases across
12 files in 14.26 seconds** (35 deprecation warnings), including all 52 new
cases, admission boundaries, native cold proof, shared edit and legacy NP
attachment regressions. Together with unchanged passing targets from the
earlier broad run, this is **291 distinct green cases**, plus the one retained
historical platform collision failure above.
Ordinary applied-route recording and bounded performance qualification remain
subsequent work.

Proposed cohesive files: new `api/part_np_application_commands.py`; extraction
into existing unpinned `core/nanoparticle_connections.py` with optional explicit
IDs/time/seed; thin existing route wrappers; registry/edit-identity integration;
one explicit bound exclusion in `two_np_generator.py`. Keep scoped composition,
bound particle motion, graft removal and collective relaxation separate. The
following table is the broader original command design, narrowed by the
application discriminator, exact ownership and first-scope conditions above.

Reuse the three existing kind strings, strict schemas with extra fields forbidden, and `_proof_version: 1, nanoparticle_connection_version: 1`. IDs are nonempty bounded strings, names at most 256 characters, booleans/versions strict, and times finite/nonnegative. A UUID `history_seed` belongs to each feature, selected by the host and preserved during historical edits. No coordinates, frames, snapshots, solver outputs or Python are accepted.

| Kind | Authored inputs | Derived output |
|---|---|---|
| `nanoparticle-connection-version-create` | `nanoparticle_id`, `conjugation_id`, `strand_id`, `overhang_id`, `version_id`, final `name`, `created_at`, `direct_variant` (`end-to-root` / `root-to-root`), `applied`; if applied, a host-selected `duplex_id` and `duplex_created_at`; exact `conflict_version_ids` | Candidate/version metadata, canonical attachment-end mapping; optionally the same native application result as the separate apply step. The UI normally creates unapplied. |
| `nanoparticle-connection-version-patch` | `nanoparticle_id`, `version_id`; optional nonempty `name`; optional `applied`; when changing application, exact current `prior_duplex_id` (nullable), exact `conflict_version_ids`, and new `duplex_id` / `duplex_created_at` only for apply | Rename or native restore/apply. Reapplying preserves the legacy restore-then-apply semantics, with a deterministic new child namespace owned by this feature. |
| `nanoparticle-connection-version-delete` | `nanoparticle_id`, `version_id`, exact nullable `prior_duplex_id` | Native unapply if necessary, then remove that version; unrelated versions/particles unchanged. |

`version_id` on create and new duplex IDs are protected outputs; consumer selectors remain editable inputs. Existing `feature_identity.preserve_proof_identity` already protects `history_seed` and `created_at`; add the new discriminator and per-kind output fields, including `duplex_created_at`. Do not protect the selected input `version_id` on patch/delete as though it were a produced identity. `conflict_version_ids` is an explicit bounded exact selector, never silently expanded after a later upstream change.

Initial native scope: one source-free uncoated gold particle's exact thiol ownership, one applied NP connection for that particle, and one ordinary non-auxiliary target with one unambiguous backing domain and no competing binder/duplex/connection. Other particles may remain only if a typed scan proves their resources are untouched. Reject incompatible polarity, partial/mismatched owner graphs, duplicate identities, occupied residues, unknown reference grammars and missing sources with structured references. Preserve existing native sequence/register rules, including the existing `connect_register` behavior; do not add a new complement or geometry algorithm.

The existing thiol ceiling of 128 handles/50,000 bases is an upper work bound, **not** evidence that ordinary connection application is fast enough. Qualify 1/16-handle fixtures first and choose the public live ceiling from measurements before enabling. Whole-design emitted nucleotide spans, loop insertions and retained assets matter because placement helpers consume geometry. Larger/solver-containing operations stay unavailable to this native v1 path or use an explicitly qualified existing job path later; do not silently cap counts or raise global capture limits.

## Ownership correction and compatibility

Recommended canonical invariant: `surface_record.helix_id` names the live backing domain carrier. The same strand ID and auxiliary overhang ID survive relocation. After native apply/unapply, refresh only the declared affected surface records from their uniquely resolved strand/domain/auxiliary endpoint; verify all three agree. The old helix definition remains exclusively in the Duplex's typed `prior_driven_topology` until restored. No current helix definition is invented from a historical ID, and no sampled coordinates become inputs.

Also add an explicit `bound_overhang_id is None` condition to `compatible_particle_handle` (`core/two_np_generator.py:56`) before correcting this metadata: it currently benefits incidentally from the stale carrier mismatch excluding some bound handles. This preserves intended free-handle selection rather than changing placement formulas.

Keep the extraction's legacy call signature and defaults through thin route aliases: `api/nanoparticle_attachment.py` and generated preparation import these helpers. Supply deterministic child identity/time only from the new native adapter. Do not rewrite old logs, infer missing choices from snapshots, normalize all loaded models, or auto-repair a legacy bound carrier during read/verification. A malformed legacy bound selection remains explicitly unsupported until an explicit repair/migration validates its exact current owner and saved topology. Native source admission may accept a fully closed imported/rootless prefix for a suffix, but never turns that prefix into a verified native construction.

The legacy direct-bind endpoint and snapshot-only generator handle preparation remain unverified compatibility paths for this increment. Do not remove them solely because the UI uses versions; document/test callers exist. Applying a replayable version is also not a replacement for the separate viewport `attach-overhang` fit, multi-anchor relaxation or constrained bound-particle motion. Those still require their own source/selection/runtime contracts. Assemblies, coated/QD/biotin attachment and physical-result freshness remain deferred.

## Replay, dependencies and implementation boundaries

1. Extract pure connection helpers to `core/nanoparticle_connections.py`, preserving arithmetic and operation order. Introduce optional deterministic IDs/time/seed; retain the old wrapper defaults. Separate HTTP error translation from geometry. No solver changes.
2. Add `api/part_nanoparticle_connection_commands.py` for schemas, typed reference/ownership checks, native build and thin recording adapters. Reuse `identity_index`, `referenced_resources`, existing unbound thiol checks, and existing duplex register/restore builders. Keep a distinct bound-ownership checker; do not relax `resolve_owned_handles` to accept ambiguous or dangling graphs.
3. Wire `part_proof_commands`, protected identities and capabilities. Use explicit particle/conjugation/strand/overhang/version/child resources for diagnostics, but retain the `PART_TOPOLOGY` read/write barrier: the common executor still reconciles clusters and retries pending ligations (`part_proof_commands.py:373`). Narrower graph edges would currently overstate independence. Source-free commands add no imported-source provenance.
4. Migrate eligible visible version routes. Resolve selectors inside the transaction or capture them with trusted session/source/revision guards and recheck before one publication. Never compute from an unlocked old Design and then apply it to a newer prefix. Native failure cannot fall back after mutation. Existing larger/opaque legacy behavior must remain honestly unverified; strict product-wide mutation policy belongs to P6.
5. Use existing `ReplayPrefix` and `part_recipe_edit.prepare_change`: source proof once, retain the independently rebuilt prefix, regenerate the changed suffix and re-encode recovery. No per-edit background full replay, cache shared across revisions or snapshot-based proof. Deletion preview replays surviving rows and reports actual failed consumers; unavailable evidence is not a reason to cascade-delete geometry.

The current P5 reference-selection catalog does not include thiol/NP connection compound ownership. Initially the existing history/repair API can edit typed fields and rerun the whole repair; do not advertise automatic selector candidates until a dedicated resolver validates these compound owners.

## Required exit evidence

- Native-vs-existing placement parity for both thiol ends and allowed/forbidden direct variants; no numerical formula or constants changed. Account separately for the intentional corrected carrier metadata.
- Current typed closure after apply; restored closure after unapply/delete; equal strand identity, sequence and nucleotide count; auxiliary IDs consistent; historical carrier exists only in typed saved topology while relocated. Scoped remapping must preserve both live and historical IDs without rewriting text.
- Fresh worker proof from an empty native root with poisoned recovery. Edit the upstream graft/target or variant and regenerate downstream; delete each producer and verify actionable dependency/cascade behavior.
- Shared carrier, ambiguous owner, preoccupied target, directional crossover/ligation/transform/CPD/Join/extension dependencies and malformed saved topology fail before any partial publication. Two-particle fixtures prove unrelated authored state survives.
- Existing visible UI lifecycle, legacy API/generator callers, load/save, one undo/revision, same-session stale edits, close/reopen ABA, cancellation and output-identity collision tests. A non-reentrant-lock test must fail immediately on nested lock acquisition.
- Memory-only ordinary route measurements with concurrent lightweight requests, input capture/commit lock durations, recovery/transport sizes, and maximum admitted history. Qualified limits and refusal cases must be reported separately. No global-budget increases.

## Protein import helper cohesion

`api/part_protein_import_recording.py` is currently 327 lines with three coherent boundaries: capture/admission (line 129), private source/build/recovery/response preparation (line 186), and lock-owned publication (line 275). Its size alone does not justify a pre-checkpoint rewrite. The critical recent correction was using the existing lock-owned publisher and guarding actual session identity, not introducing a more abstract transaction framework.

After its checks pass, the smallest useful refactor would separate a private preparation packet (isolated Design, source bytes, authored choices, IDs/time and budget charges) from the host capture envelope (session/source/doc/revision CAS handles). If another import shares this pattern, move preparation into `part_protein_import_preparation.py` while keeping the existing host API/tests stable. That prevents preparation from accidentally reaching live CAS handles. Promote the narrowly reused `_Copier` only when both metadata callers' isolation/budget semantics are reconciled. Avoid a generic importer, another recovery encoder or another transaction implementation.
