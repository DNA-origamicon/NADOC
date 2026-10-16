# Ordinary nanoparticle application: private route migration

Correctness checkpoint, 2026-10-15. The ordinary application recording adapter
is implemented behind `routes_nanoparticles.OWNED_NP_APPLICATION_ENABLED = False`.
The bounded lifecycle passes focused route and independent input-replay checks.
HTTP/geometry performance and desktop qualification remain open; ordinary
application behavior still uses the existing path. The audit and next benchmark
proposal below are retained as implementation context.
Scientific helpers, numerical pins, command schemas and global budgets stay
unchanged. See the [contract and official CAD references](nanoparticle_connection_contract.md).

## Scope and existing seams

The useful first lifecycle is pending create → Apply → applied rename → Unapply
→ Reapply → applied Delete, plus create-and-apply and switching an exact declared
conflicting version. Admit only the existing pure contract: source-free uncoated
gold, one exact thiol conjugation, at most 16 handles, 128 versions and 4,096
admitted bases, one active connection per selected particle, and closed native
live/restoration ownership. These are eligibility ceilings, not measured latency
guarantees. No coordinates, sampled placement or saved topology become inputs.

Pending alternatives while another version on the particle remains applied need
a separate metadata-ownership contract. Coated/QD/biotin attachment, shortening,
legacy direct binding, bound motion/resize, collective relaxation, generated
multi-anchor construction, assemblies and the shared-host scientific defect are
outside this migration. Unsupported compatibility remains explicitly unverified;
a native suffix does not certify an old or broken prefix.

| Current seam | Narrow change |
| --- | --- |
| `api/part_nanoparticle_connection_commands.py::try_record` | Keep the sole state-lock owner; add a host-only application option and dispatch from actual source/version/intent before pending-only selection. Disabled operation performs no application import or walk. |
| `api/part_np_application_commands.py::build` | Extract common structural selection, native admission and materialization. Standalone replay prepares independently; the route consumes one source-bound private packet. |
| New `api/part_np_application_recording.py` if needed | Cohesive lock-owned application host helper; it must not reacquire the lock or establish another transaction system. |
| `api/routes_nanoparticles.py::{create,patch,delete}_np_connection_version` | Pass the private gate into the existing dispatcher; retain legacy callbacks/defaults and response behavior. |
| `core/nanoparticle_connections.py::set_version_applied` | Unchanged native restoration/register/placement/synchronization, with existing explicit IDs/time/seed. Retain route aliases used by attachment and generators. |
| `api/feature_recording.py::record_feature` | Unchanged one undo copy, PRE/POST encodes, reconciliation/retry, CPD guard, validation, draft retention and atomic publication. |

Paths above are relative to `backend/`. Reuse one original typed inventory and
one admitted selection. Do not call both independently locking adapters, call
pure `build` again after preparation, or invoke proof `execute` in the recorder.
The restored radial graph may legitimately need its own identity index. Existing
private radial restoration and prospective topology checks remain in their
current order; final materialization restores again where the kernel requires
it. Measure those passes; do not remove them as an assumed optimization.

## Exact fallback boundary

Fallback is permitted during **bounded structural classification**, not after
native topology work. The structural phase contains:

1. `_work_admission`, typed grammar/reference allowance and the original index.
2. Exact owner/endpoint/version/conflict selectors and native polarity mapping.
3. Handle/version/active-owner limits and declared restoration scope.
4. `_restoration` inspection of saved shape and live ownership, without restoring.
5. The existing `applying and not restoring` posed-target predicate, moved
   unchanged ahead of the radial restoration loop.

Only explicit scope exclusions return `None`. Unknown saved-topology grammar
remains unsupported legacy; a schema-supported saved graph with a missing or
wrong owner, carrier, duplex or child is a typed failure. Missing selectors,
duplicate identities, polarity/conflict mismatches and output collisions never
become compatibility retries. Do not catch arbitrary `ValueError`,
`CommandContractError` or `NotImplementedError` around the whole pipeline.

Close fallback immediately before the first private
`set_version_applied(radial, old.id, False)`; without restoration, close it before
radial ownership/prospective admission. Applied rename returns its structurally
admitted selection without restoring. After cutover, restored indexing,
`resolve_owned_handles`, incoming/directional checks, `connect_register`,
`compute_bind_topology`, final application and recording all either succeed or
fail explicitly. Even a late `unsupported_thiol_source`/`NotImplementedError`
cannot reopen fallback. Known restoration failures retain `prior_duplex_id`
context; prospective/application failures retain their typed endpoint paths.
Unexpected exceptions fail rather than silently switching implementations.

## Transaction, identity and response contract

Resolve the current document session/source, expected revision and editable
loadout under one uninterrupted lock; the loadout guard precedes the inventory.
Cheap bounded version/particle/owner selection rejects missing or ambiguous
references before UUIDs or snapshots. Perform bounded selection before output
defaults and recovery allocation, without provisional identities; freeze actual
conjugation/strand/ordinary and auxiliary overhang IDs, prior duplex and ordered
conflicts. Allocate each UUID,
time and history seed once. Capture final trimmed/defaulted names, preserving
omitted/null/blank-name compatibility and explicit `applied=false` semantics.
Applied rename omits `applied`, creates no child IDs and leaves duplex name and
topology unchanged; normal reconciliation/retry still run.

Explicit `applied=false` on an already-pending version remains a transition with
one ordinary row. Omitted/null `applied` on an active version is rename-only;
omitted/null/blank `name` retains its current name. Reapplying an active version
restores/reapplies and allocates a new recorded duplex identity. A simultaneous
name-and-application patch updates the version name before the new Duplex is
created; rename-only leaves the old Duplex name untouched.

The callback checks exact session/source identity and consumes only that packet.
No packet crosses a lock release, survives a revision or supplies public bypass
authority. Detach `feature_log` before its append. A successful request produces
one feature row, undo entry and revision; cancellation, encoding/validation or
publication exceptions preserve the established rollback and request markers.
No extra whole-Design clone, complete-root proof or shared mutable cache belongs
on the ordinary route. Keep protected output identities and editable selectors
from the already registered contracts unchanged.

All three routes currently return `_design_response`, without embedded geometry.
`frontend/src/api/client.js` then invokes `getGeometry()` through
`_syncFromDesignResponse`. Preserve that two-request behavior and 201/200 response
semantics; do not claim partial or embedded geometry, or add a separate serializer.
The new row's recovery bodies are intentionally included by the existing response
policy. Response serialization happens after publication: its failure is not
transaction rollback and must not trigger fallback or an automatic re-application.
`_route_eligible` is test-used compatibility code, not a second live
preflight to call; keep generator/attachment helper aliases and existing callers.

## Tests-first implementation and qualification

First add a bounded route dossier, proposed
`tests/test_np_connection_application_routes.py`, with independent legacy
controls before production changes. Reuse the authentic five-row native prefix
in `test_part_pending_np_connections.py` (six cells, 42 bp, 12-base target, two
thiol handles), the pure application oracle and both chemical orientations in
`test_part_np_application_commands.py`, the full postprocessing rename oracle in
`test_part_np_application_rename.py`, and existing applied-ownership/cold-proof
fixtures. Keep model/response fixtures in memory.

- Compare full authored state and actual response for every lifecycle transition,
  conflict switch and create-and-apply. Inject matching output defaults into the
  oracle; preserve unrelated sequence, particle/owner state, drafts and metadata.
  Assert response revision, new-row inputs/recovery body and the existing version
  listing/measurement after application.
- Prove one row/undo/revision, original source/history-list ownership, deterministic
  child IDs and fresh input-only replay while the final connection is applied.
- Trap duplicate original preparation, extra full copies, reentrant locking,
  unexpected geometry during rename and bypassed reconciliation/retry. Check
  stale revision before defaults/snapshots, document/session isolation, protected
  loadouts and source replacement at the callback boundary.
- Missing/mismatched selections and native-stage failures must be atomic and
  never fall back. Cover post-encode/publication/cancellation faults. Disabled and
  structural-unsupported controls prove legacy dispatch without native work.
- Run existing pending, application/admission/rename, applied ownership, native
  proof and thiol pending-motion regressions. Replace stale traps against unused
  `pending.build` in route tests with the actual preparation/materialization seam;
  retain the rename oracle's intentional `try_record=None` legacy control. No
  molecular oracle changes.

After correctness, qualify actual FastAPI mutation responses **and the following
geometry request**, reporting mutation, geometry and combined latency separately.
Use a finite predeclared matrix of 1/16 handles, small/larger admitted DNA
backgrounds and retained authentic history; keep larger ineligible controls.
Compare alternating legacy/native requests, including applied rename, restoration,
reapply and conflict switching. Instrument original selection, private restoration,
native work, one undo copy, both encodes, response construction/serialization,
bytes, summed lock holds/waits and concurrent scalar reads across the whole request.
Cold replay and exact parity checks occur outside timed requests.

Retain compact exact authoring/response digests and release client response graphs
before the next request. Any random-ID normalization must be narrow and explicit,
including references and diagnostic text; retain mismatches rather than broadly
scrubbing warnings. Use natural GC, bounded aggregate sampling with drop counts,
and report in-process client allocation as a limitation. Do not subtract GC time,
retry away tails, raise ceilings or infer browser performance from TestClient.
The gate remains false until parity, lifecycle/cleanup, refusal controls and both
mutation/geometry responsiveness evidence are reviewed. Pure-builder timings or
median improvement alone are insufficient.

Root alone runs serialized checks and benchmarks. Archive is unavailable: no
application lifespan, user files, persistent sessions, simulation, molecular
solver/native scratch or bulk dumps. Use isolated document IDs, failure-safe
session/context cleanup, memory-only fixtures and compact stdout reports. Retain
failed measurements and verify no test-created session/shared-memory/worker
resources remain. VR qualification is explicitly deferred by the user to a
capable machine. App qualification remains pending; these backend results do not
establish browser or desktop behavior.

## Proposed next benchmark matrix — unexecuted

Benchmark authoring and execution are deferred to the next resumed session.
The proposed memory-only script is `scripts/benchmark_np_application_route.py`;
it has not been created. Keep the private application gate false.

| DNA background | Thiol handles | Additional retained native rename rows |
| --- | --- | --- |
| 6 cells × 42 bp | 1 | 0 |
| 6 cells × 42 bp | 16 | 0 |
| 16 cells × 42 bp | 1 | 16 |
| 16 cells × 42 bp | 16 | 16 |

Every fixture starts with the authentic input-defined gold/graft/ordinary-target
prefix and one pending version. Each arm performs Apply → active rename →
reapply → applied Delete → create-and-apply → Unapply. Follow every mutation
with the real geometry GET and report mutation, geometry and combined latency
separately. Alternate legacy/native order; begin with one pair per case, then
31 pairs only after the bounded diagnostic passes. Retain exact normalized
authoring/response digests, not client graphs between requests, and run one
independent cold proof per case on the actual applied create-and-apply result
outside timing. Use the existing lock, bounded GC and concurrent revision-read
probes; report their capacities/drops and clean every owned document in `finally`.
This is a proposed diagnostic matrix, not latency qualification or rollout evidence.


## Implemented stopping checkpoint — October 15

The dispatcher retains the sole document lock and calls the new cohesive
`part_np_application_recording.py` host after checking revision/editability.
The pure builder and host share structural preparation, selection, exact command
binding and materialization. The host prepares one original reference inventory;
only explicitly unsupported structural sources may use compatibility dispatch.
After selection, output collisions and native failures remain typed failures in
the existing atomic recorder, without a second attempt through legacy code.
Output identities and timestamps become recorded command inputs. Source/session
identity, detached history append, reconciliation/retry, undo and publication
remain owned by the existing transaction. No numerical helper or pin changed.

**224 unique cases across eight files pass:** 219 in the first complete focused
run (12.27 s), then all 34 route cases after five additions (6.39 s). Controls
cover disabled dispatch, a real 17-handle structural fallback, selected-reference
and generated-output collisions, conflict switching, exact authoring parity,
one row/undo/revision, cancellation and publication rollback. An independently
spawned replay reconstructs the actual applied result with unusable snapshots.
The two obsolete pending-route traps now target real preparation/materialization.

Seven route cases compare complete authored state with the legacy HTTP oracle;
selected response fields are checked. This is **not** complete validation/geometry
response parity or performance qualification. The standalone pure contracts
retain upstream-edit coverage; a new HTTP-created upstream-edit integration is
not claimed. One harmless first-error precedence difference remains for a doubly
invalid pure create: an omitted conflicting version can be reported before that
new output ID's collision. Valid commands and host selections are unchanged.

The proposed benchmark script has not been created or run. The private gate
stays false. P4–P6, full repair UI and strict automation rollout remain incomplete;
assemblies and VR remain deferred. See
[the compact validation record](validation_np_application_routes.json) for exact
runs, selector/lint debt and artifact cleanup. This is the saved nanoparticle stopping
point. Subsequent user direction prioritizes core geometry; the predeclared
HTTP/geometry benchmark is parked until that higher-priority work is complete.
