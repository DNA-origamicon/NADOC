# FH-25 ordinary DNA connection completion contract

U28 source audit and native characterization, October 16, 2026, against
`2ad8b7a9`. **Not a completed connection implementation or rollout.** Progress
remains **21/38 complete,17 remaining (8 core,9 parked)**. This checkpoint adds
no milestone and does not narrow the FH-25 exit. Existing scientific placement
rules, assembly deferral and nanoparticle priority remain unchanged.

## Current authority and finite remaining matrix

| Path | Existing input authority | Required remaining acceptance |
|---|---|---|
| Pending ordinary version create/patch/delete | Closed `connection-version-*` metadata commands and ordinary recorder | Preserve naming, ordering, sequences and endpoint selection; integrate with the complete applied lifecycle below. |
| Finite Apply/reapply | Eight attachment/material combinations in `connection-version-apply-linker` v1; private ordinary route gate false | Keep native parity and exact output/conflict IDs; resolve existing source eligibility, organized ownership and correctness/latency exits before enabling. |
| First-time Connect | Legacy callback creates version and topology in one undo; receipt stores only version ID/type | One closed editable compound definition containing version inputs, stable version ID/time and all materialized output/conflict identities. Independent original-input replay; retain one undo and one postprocessing pass. |
| Zero-length indirect | Two types, root-to-root and end-to-end; legacy callback | Native continuous complement strand, no bridge helix/domain; actual typed output footprint, replacement/removal parity, cold replay and upstream editing. Do not weaken finite v1's saved meaning to admit zero. |
| Direct equal-length | Two types, root-to-root and end-to-root; legacy binding, restored prior topology, midpoint placement, child duplex cluster and display Duplex | Freeze complete allocated ownership and exact reversible source contract; reuse existing native helpers in their actual order. Qualify replacement with third-endpoint conflicts and all binding/duplex/cluster references. |
| Direct unequal-length | Same two types, native Duplex paired window/toehold relocation without equal-length binding | Separate explicit branch and ownership proof; no fabricated binding or equal-length substitution. |
| Applied version patch/delete/flag changes | Falls back to `mutate_and_validate`; metadata may change without rebuilding/removing materialized geometry | Record actual metadata semantics; distinguish deleting a saved alternative from disconnecting topology. Do not treat `applied=false` as proof of geometric removal. Review consistency/repair with explicit user-visible state. |
| Explicit linker add/patch/delete | Existing `part_linker_commands` and registered `linker-*` recipes | Preserve their distinct compatibility checks, response and lifecycle. They are not a drop-in replacement for version Apply. Include in cross-family replacement and replay regressions. |
| History/repair/automation | General recipe and repair foundations | Editable complete inputs, exact failing references, downstream regeneration, save/reload/undo, public policy boundary. FH-26 owns integrated repair UI; FH-29 owns public automation release, not missing connection builders. |

Cross-cutting source profiles are part of this fixed matrix: selected and unrelated
poses/groups, shared or partially occupied overhang hosts, replacement across a
third endpoint, dangling incoming references, retained user sequences, pending
ligation reconciliation, protected loadouts and source/reset/policy changes.
A refusal must be explicit and preserve the design. Bounded eligibility can
remain provisional, but cannot silently count ordinary unimplemented paths as
completed or park them with nanoparticles.

Two existing correctness debts remain within FH-25: the shared-host sequence
patch can resize an entire helix and invalidate another overhang; ISSUE-126
records duplicate DS bridge occupancy for a mixed-polarity application. Native
output parity is not valid-geometry certification. Keep these failures visible;
any changed molecular placement/polarity needs the existing scientific review.
No automatic kernel fix or relaxed validation follows from this plan.

## Compound feature architecture

Onshape treats a custom feature as an editable definition regenerated with the
Part Studio; its standard features may wrap multiple underlying operations.
That supports a fixed composed Connect feature with meaningful inputs, rather
than requiring two separately published user operations. This is an engineering
inference for NADOC, not a vendor rule about Python or LLMs. See
[feature types](https://cad.onshape.com/FsDoc/feature-types.html) and
[slot tutorial](https://cad.onshape.com/FsDoc/tutorials/create-a-slot-feature.html).
Onshape also warns that upstream edits can change what a selected query resolves
to; replay must validate current prefix references even when UI selection was
valid when authored: [Feature UI](https://cad.onshape.com/FsDoc/uispec.html).

Implement a closed compound action under the existing snapshot literal, with a
separate action/version contract. Reuse strict pending-definition construction
and application preparation/materialization, not two calls to public endpoints,
an arbitrary callback/batch, or a saved Design. The feature must expose version
name/type, endpoint and bridge sequences/length plus endpoint references. Stable
version/time/output identities are protected; references stay editable. Original
finite v1 replay remains unchanged. Creation writes the new version resource;
it must not claim to read an already-existing producer for that new identity.

Capture source and validate endpoints/loadout/policy before allocating IDs.
Prepare metadata and one source index within existing ownership, then build and
postprocess once. No whole-history proof on an ordinary click, no second undo
snapshot, no per-frame replay. Exact old conflict sets are declared; newly
appearing conflicts refuse rather than silently deleting extra geometry.
Admission failure may select an explicit compatibility path before native work;
a failure after admission must never retry through legacy.

U28's native test confirms all eight finite compositions reproduce the existing
combined callback's complete authoring state and mutation report, including
sequence truncation/N-padding. Naming earlier blank alternatives also matches.
This is a useful reuse result, **not** evidence that a combined command is already
registered or that its UI/HTTP/undo lifecycle is implemented.

The same test confirms both indirect types emit exactly one complement strand
and no virtual helix. The legacy mutation report still names a nonexistent bridge
helix. Future dependency/output declarations must use actual emitted ownership;
do not copy the finite contract's unconditional helix write/removal grammar.

## Implementation order and containment

1. Closed finite compound Connect: strict definition/identities, native parity,
   exact source admission, one recorded transaction and cold proof. Tests must
   cover failed publication, one undo/redo, later reapply, upstream edits and
   public request acquisition. Keep rollout off pending qualification.
2. Indirect Apply/Connect/replacement: explicit zero-bridge output grammar and
   bounds, both types, no virtual-helix assumptions, full suffix/undo/reload.
3. Direct equal/unequal contracts: first characterize actual restoration and
   allocation paths; preserve numerical helpers and isolate any scientific
   uncertainty. Complete both types and cross-family replacements.
4. Applied metadata lifecycle and organized ownership integration, core defect
   admission/repair, complete supported matrix; prune duplicated legacy
   orchestration only after parity and persisted compatibility are proven.
5. Measure complete requests, lock wait/hold, serialization, retained history,
   memory and concurrent reads, then desktop/rollout acceptance. Existing
   same-process compact benchmarks do not replace this qualification.

These are substeps of FH-25, not extra milestones. No partial subset closes it.
At three unfinished checkpoints, trigger the existing task-growth review.
FH-18/FH-23 full movement remains open with its own existing growth flags.

## U28 validation and ownership correction

`tests/test_connection_composition_contract.py` uses the authentic native
bundle/extrusion prefix and unchanged molecular helpers, with no solver, disk
scratch, server lifespan or synthetic coordinates. Initial 10/12 failures came
from a fixture bypassing the public route's sequence cleaning; the fixture now
uses that actual cleaning contract, without weakening complete-output comparison.
The next run exposed two real source-alias failures during default naming.

Pydantic `model_copy(deep=True, update=...)` does not deep-copy objects supplied
in `update`. The combined callback reused the original version records, then
`assign_default_names` mutated them. Its existing transaction correctly restores
a snapshot on failure, but other holders of the original source could observe
those mutations. ISSUE-139 explicitly copies only the version records supplied
in the update before naming; the existing whole-model copy and molecular order
remain unchanged. A real recorder failure test verifies both canonical rollback
and the held source, revision, undo and redo. An initial assertion demanding
source object identity on rollback was corrected to the established snapshot
restoration contract; the held-source mutation still failed independently.


Final focused command:
`just test-affected tests/test_connection_composition_contract.py tests/test_connection_version_owned_apply_route.py tests/test_connection_versions.py tests/test_part_pending_connection_versions.py --tb=short`
passed **111 cases,14 warnings,5.96s** (13 new characterization/ownership cases).
The held-source failed-publication regression was observed red independently in
2.76s before the production fix; all final cases pass. `just lint` retains the
same5 pre-existing F401 errors, no new finding; memory lint retains6 errors and
59 warnings, with the current project head199 lines. `git diff --check` passes.
`main.js` remains7,350 lines,delta0; no frontend behavior changed or frontend run
claimed. No broad, desktop, scientific or performance qualification is claimed.

`just test-smart --dry-run` selected FAST from a would-be FULL historical diff:
**zero broad tests ran**. Archive is absent, so no broad disk-scratch writer was
started. The selector's literal notice below says “ran,” but is dry-run wording:

> DEFERRED: this change would have needed the FULL suite, but no test-dedicated
> session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
> This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
> Only request `just test-session` when a broad/full sweep is actually needed.

Cleanup: the task began with an empty `/tmp/pytest-of-joshua`. After completed
checks, its exact `pytest-2`, `pytest-3`, `pytest-4`, `pytest-current` inventory had
116 empty directories,4 symlinks and0 regular-file bytes. No readable same-user
cwd/fd/maps references or shared-memory remnants remained; persistent systemd/PAM
435/436 denied inspection, as in the prior checkpoint. Removed those empty task
paths and verified the root empty. Workspace designs/jobs, historical artifacts
and shared caches are preserved. No browser/solver/bulk capture was launched.


## U29 — closed finite compound Connect

Based on `e253be13`. `part_connection_composition_commands` implements the fixed
`connection-version-connect-linker` action/version1 under `overhang-bulk`.
It inherits the strict pending-definition grammar, restricts the existing eight
finite types, declares both stable outputs and exact old conflicts, and calls the
same admitted native materializer. A new version is a dependency write, not a
read of a nonexistent producer. Apply v1 is unchanged. Generated scopes, unknown
fields, incorrect versions and malformed/conflicting IDs remain unregistered.
Creator version ID/time and connection ID are protected during history editing;
endpoint/sequence/bridge/name inputs remain editable. No copied output geometry
is part of the definition.

The ordinary adapter selects metadata/loadout/latest cursor before allocation,
stages a private version table, indexes the bounded source once, selects actual
conflicts and records one callback. It performs one materialization, undo copy,
reconciliation and pending-ligation retry, with the existing two recovery encodes.
No full proof runs on ordinary Connect. Complete HTTP source capture occurs
before bounded JSON reading through the existing shared SourceBoundRoute. Even
an explicit unsupported-scope fallback checks that same source inside its legacy
recording callback. The public `OWNED_COMBINED_CONNECTION_APPLY_ENABLED` switch
is false; caller fields cannot enable it. Existing disabled-route behavior stays
available and finite Apply has its independent unchanged false gate.

Qualification tests cover all eight finite native output/report comparisons,
actual registered cold replay with poisoned recovery, selected bridge and earlier
overhang-length edits, protected output IDs, exact dependency declarations,
missing/version-collision inputs, one postprocessing pass, actual ordinary route
one-undo/redo, failed materialization/publication, two successive Connects with
exact replacement conflicts, real ASGI requests, held-body source revision change,
compatibility fallback revision change, protected loadout/latest-cursor admission
before UUID allocation, one source index/materialization and a spawned native
verification worker. No molecular algorithm or numerical pin changed.

The first20-case run observed13 failed/7 passed in3.00s (missing new contract).
After implementation20 passed3.03s; with initial route tests24 passed3.06s.
The seven-file regression first passed215/14 warnings in9.60s. Final review then
observed a real held-request fallback failure (201 instead of409) in2.80s;
checking captured ownership inside the legacy callback fixed it without altering
uncaptured legacy operations. The final seven-file run passed218/14 warnings in
10.54s. Two added pre-allocation guard cases then passed with the complete
compound file:37 passed4.34s. This yields220 distinct passing cases, not a sum of
reruns. A test's initial recipe-edit invocation was corrected to the established
`prepare_change(source,capture,index,checkpoint,params=...)` signature before its
first successful execution; no production API was invented for the test.

Final command:
`just test-affected tests/test_part_connection_compose.py tests/test_connection_composition_contract.py tests/test_connection_version_owned_apply_route.py tests/test_native_connection_application_proof.py tests/test_part_connection_application_commands.py tests/test_connection_versions.py tests/test_part_pending_connection_versions.py --tb=short`
Final added-guard command:
`just test-affected tests/test_part_connection_compose.py --tb=short`.

This is FH-25 checkpoint2, not closure. Indirect/direct application, applied
metadata, organized group ownership, full user-facing history controls and
performance/desktop qualification remain in the original matrix. Existing DS
occupancy and shared-host defects are not resolved by reproducibility. The native
proof can reproduce a warning-bearing design; it does not declare its molecular
geometry valid. Both public gates remain off. Next implement the separate
zero-bridge output/removal grammar, preserving finite v1 and all other exits.


Final module-boundary review moved the compound dependency description into its
own module; the large proof dispatcher gains only thin calls. The same37-case
compound file passed again in4.65s after that extraction. Small bounded metadata
selection occurs twice (initial endpoints then staged definition); the full typed
source index and native materialization occur once. This is structural evidence,
not a measured latency claim. `main.js` is unchanged at7,350 lines,delta0.
`just lint` retains5 baseline F401 findings; memory lint retains6 errors/59 warnings.
No frontend behavior changed or frontend/app run is claimed.

The initial selector dry-run request was correctly refused while a focused run
was live; after waiting for that exact process to finish, the retry completed.
`just test-smart --dry-run` again selected FAST from a would-be FULL historical
diff and executed zero tests. The literal DEFERRED notice remains the U28 notice
above; neither broad FAST nor FULL passed. Archive remains absent, so no broad
scratch, browser capture, scientific run or native build was launched. Public
rollout requires the existing desktop/performance exits.

Cleanup: final task-owned `/tmp/pytest-of-joshua/pytest-5`, `pytest-6`, `pytest-7`
and `pytest-current` contained295 empty directories,4 symlinks,0 regular-file bytes.
No readable same-user cwd/fd/maps references or shared-memory remnants remained;
only persistent systemd/PAM435/436 denied inspection. Removed those empty task
paths and verified the root empty. Workspace designs/jobs and shared caches are
preserved. Retained evidence is this compact report and reusable source/tests.


## U30 — native linker v2 and FH-25 containment

Based on `b9cf6681`. Apply and Connect retain their action names and strict v1
models; explicit version2 models admit the eight finite and two indirect types.
Saved v1 remains finite-only and retains its old replacement grammar. No v1
recipe is silently migrated. New private recorder arguments select the host's
contract version; request bodies cannot enable the rollout switch.

Version2 indirect work uses the same native materializer with bridge length zero.
Dependencies expose the actual single complement strand and connection, without
a fictional helix. Removal requires exactly that strand, exact native ordered
complement domains, no reference-strand flag, no matching-prefix helix/extra
strand and exact endpoint ownership. The native `_zero_bridge_side_order` and
`_make_complement_domain` supply the oracle; no routing/polarity algorithm changes.
The existing full output namespace reservation remains conservative even without
an emitted helix, preventing adoption of dangling/retained virtual-helix owners.
Native mutation reports retain their legacy prospective-helix entry for parity;
they are not used as the dependency output inventory.

Version2 can replace finite with indirect, indirect with finite, and indirect with
indirect. It shares the existing bounded source index, work limits, materializer,
one recording transaction, undo and native reconciliation/retry. The Apply
route now captures source/session/revision/policy before dispatch and rejects
body inputs; its selected saved version is the input. Connect retains bounded
JSON/source acquisition. Disabled v1 routes retain their original behavior.
`NATIVE_LINKER_V2_ENABLED`, `OWNED_FINITE_CONNECTION_APPLY_ENABLED` and
`OWNED_COMBINED_CONNECTION_APPLY_ENABLED` all remain false.

The fixed native matrix checks both indirect types for Apply/Connect complete
output/report parity, exact dependency writes, v1 rejection, eight cross-family
replacement cases, poisoned-recovery input proof, domain-order/extra-domain/
extra-owner refusal, ordinary HTTP Connect/reapply, one undo per action and redo,
held-request revision changes, exact version markers, body refusal, dangling
virtual-helix references, protected loadouts/latest cursor before source
preparation, and two actual isolated workers after earlier overhang-length edits.

Initial17 cases:15 failed/2 passed in2.97s because v2 was unimplemented.
After core implementation17 passed2.92s. Expanded shared run:164 passed/2 failed
in9.43s; one callback fixture needed the new trusted `contract_version` argument,
and one old unknown-version test still used the newly implemented2. Unknown
version controls now use3; explicit v1-indirect refusal and exact v2 marker tests
remain. Another run passed258 with one fixture error in13.94s: a dangling pose
fixture omitted its required `kind=base`. This was corrected without altering
production validation. Final regression: **261 passed,22 warnings,13.27s**, including
41 new indirect cases. The additional warning locations are existing FastAPI
ORJSON deprecations now passing through the thin Apply wrapper.

Final command:
`just test-affected tests/test_part_connection_indirect.py tests/test_part_connection_compose.py tests/test_connection_version_owned_apply_route.py tests/test_native_connection_application_proof.py tests/test_part_connection_application_commands.py tests/test_connection_composition_contract.py tests/test_connection_versions.py tests/test_part_pending_connection_versions.py --tb=short`.

**FH-25 task growth is flagged after three checkpoints.** The ledger counts one
audit/source-isolation checkpoint and two implementation checkpoints; no milestone
has closed. Containment is the original finite matrix, not additional variants:
next direct equal/unequal contracts for both authored types, then applied-version
metadata and organized ownership, then actual history controls/desktop/latency
qualification. Direct work must first map binding, Duplex and cluster output
identities and restored prior topology against the existing native helpers.
Existing shared-host sequence and ISSUE-126 duplicate DS occupancy debts remain
required; replay parity does not certify scientific validity. No molecular
correction, new scope, parked ordinary family or denominator change is authorized
by these passing tests. Public rollout and the full objective remain incomplete.


U30 hygiene: `just lint` retains5 baseline F401 findings; `just lint-memory`
retains6 errors/59 warnings with the project head at200 lines. Changed Python
files pass targeted Ruff and `git diff --check` passes. `main.js` remains7,350
lines,delta0. No frontend behavior changed or frontend/app pass is claimed.
`just test-smart --dry-run` selected FAST from a would-be FULL historical diff,
executing zero tests; its literal DEFERRED notice is retained above. Broad debt
is not cleared. Archive is still absent, so no browser/bulk/scientific writer or
native build was launched. All numerical algorithms/models/pins remain unchanged.

Final task-owned `/tmp/pytest-of-joshua/pytest-2`, `pytest-3`, `pytest-4` and
`pytest-current` contained689 empty directories,4 symlinks and0 file bytes.
No readable same-user cwd/fd/maps references or shared-memory remnants remained;
persistent systemd/PAM435/436 denied inspection. Removed those empty paths and
verified the root empty. User designs/jobs, runtimes, historical artifacts and
shared caches remain untouched. Only compact documentation and reusable source/
tests are retained.


## U31 — direct replacement restoration

Native input-built equal/unequal prefixes exposed a pre-existing ordinary Apply
bug: teardown removed bindings but retained display Duplex records, and never
restored unequal-length Duplex-owned relocation. Eight corrected characterization
cases failed on retained Duplex records before the fix (an earlier fixture run
used incorrect direct type strings; that run is not bug evidence).

`connection_version_teardown.remove_conflicts` now owns existing linker teardown,
equal-length binding restoration, unequal-length Duplex restoration and conflicting
record removal. The callback calls it before sequence patching, avoiding writes
to a still-relocated shared driver host. Existing native restoration helpers,
placement algorithms, constants, models, source pins and goldens are unchanged.
This removes30 lines from the route file and centralizes replacement cleanup.

Twenty new regression cases use real independently verified bundle/extrusion
recipes, with equal12/12 and unequal12/8 endpoints: both direct types, finite SS
and indirect replacements, blank and explicit sequences, direct type switching,
complete original topology restoration and held-source immutability. Comparison
uses all authoring fields except saved alternative metadata, sorting identity
record collections because native restoration may append the original helix.

`just test-affected tests/test_connection_direct_replacement.py tests/test_connection_composition_contract.py tests/test_direct_connection_unified.py tests/test_connection_versions.py tests/test_part_connection_application_commands.py tests/test_part_connection_indirect.py --tb=short`
passed157 tests/25 existing FastAPI warnings in7.89s. Changed-file Ruff passes;
full lint retains5 baseline F401 findings. `main.js`7350lines,delta0.

`just test-smart --dry-run` selected FAST after deferring the historical
foundational FULL diff (5754files); **zero broad tests ran**. Literal notice:

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
Only request `just test-session` when a broad/full sweep is actually needed.
```

NOT VERIFIED IN APP: Archive is absent, so no bulk browser/native artifacts or
visual qualification were attempted. This is a correction to the ordinary legacy
callback, not a newly registered direct recipe. Deterministic direct identities,
typed dependencies, complete replacement admission, applied metadata, organized
ownership and qualification remain within FH-25. The direct audit found existing
identity seams in `compute_bind_topology`, `materialize_duplex_cluster` and
`relocate_duplex`; use those instead of replacing native molecular calculations.
Counts remain21/38complete,17remaining;+0total,+0completed;31engineering checkpoints
since B1. FH-25 remains task-growth flagged at4; no new milestone or narrower exit.

Hygiene: memory lint retains6 baseline errors/59warnings; current project head
remains200lines. Task-created `/tmp/pytest-of-joshua/pytest-{1,2,3}` and current
link contained176empty directories,4symlinks,0regular files/bytes. No readable
same-user cwd/fd/maps references were present; persistent systemd/PAM435/436
remain uninspectable. Removed only those empty directories/links; pytest root
and `/dev/shm` are empty. No user designs, managed jobs, caches or scientific
artifacts were removed. No bulk artifacts were created.


## U32 — deterministic shared direct materialization

`connection_version_direct` extracts existing equal-length binding construction
and display Duplex creation into one shared native materializer. Ordinary Apply
calls it; the old `_cv_create_bound_binding` import remains a compatibility alias
for existing headless callers. This removes143net lines from the route, preserving
its one-recording transaction. No placement arithmetic, numerical kernel, model,
source pin, phase constant or golden changed.

An optional UUID seed plus explicit finite nonnegative creation time supplies
binding and Duplex identities/times, native forced-ligation identity and child
cluster identity. Both must be supplied together. Unequal-length construction
passes the seed into existing `relocate_duplex`; equal construction passes the
same output namespace into existing `compute_bind_topology` and
`materialize_duplex_cluster`. Common cluster/ligation/Duplex identities therefore
survive equal-to-unequal edits and either endpoint becoming the longer driver.
No global UUID/time monkeypatch or output-snapshot replay is used.

Nine initial tests failed on the absent module. The first three-file pass was
41cases in4.12s. After strict identity/time and length-edit controls, the nine-file
run passed175cases. Expanding native prefix inputs to12/12,12/8 and12/16 tests
both unequal driver choices; the final run passed188cases/33existing FastAPI
warnings in9.00s. Command:

`just test-affected tests/test_connection_direct_identity.py tests/test_connection_direct_replacement.py tests/test_direct_connection_unified.py tests/test_duplex_length_preserve.py tests/test_overhang_binder_rotation.py tests/test_connection_composition_contract.py tests/test_connection_versions.py tests/test_part_connection_application_commands.py tests/test_part_connection_indirect.py --tb=short`.

New identity tests compare complete authored output to ordinary construction,
normalizing only generated identities/creation times and excluding the separately
created saved alternative. They assert repeated exact output, complete native
restoration, held-source immutability and stable common identities across length/
attachment edits. Existing visual-geometry numerical regressions remain green.
Changed Python Ruff passes; full lint retains5baseline F401 findings. `main.js`
remains7350lines,delta0; no frontend changes or frontend rerun.

`just test-smart --dry-run` selects FAST after deferring the historical
foundational FULL diff (5756files); **zero broad tests ran**. Literal notice:

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
Only request `just test-session` when a broad/full sweep is actually needed.
```

NOT VERIFIED IN APP: Archive mount is still absent; no visual/latency acceptance
or bulk artifacts. This helper deliberately is not a registered command and does
not certify source admission, collision/incoming-reference safety or generated
scopes. Next, wrap this native construction in the bounded complete direct
selection/ownership/dependency contract and shared recorder; retain both driver
branches, restoration and all fixed replacement exits. Applied metadata,
organization and qualification remain. All public gates stay false. Counts are
21/38complete,17remaining;+0total,+0completed;32engineering checkpoints since B1.
FH-25 remains task-growth flagged after5; original exit/estimate unchanged.

Hygiene: memory lint retains6baseline errors/59warnings; current project head
remains200lines. Completed task pytest roots1/2/3 contained407empty directories,
4symlinks and0regular files/bytes. No readable same-user cwd/fd/maps references
were found; persistent systemd/PAM435/436 remain uninspectable. Removed only
those task-created empty directories/links; pytest root and `/dev/shm` are empty.
No user designs, managed jobs, historical evidence or caches were removed.


## U33 — registered direct Apply and owned recording

`connection-version-apply-direct` v1 is now registered under `overhang-bulk`.
Strict inputs contain the saved version/endpoint selection, both direct types,
UUID namespace, creation time and exact ordered connection/binding/Duplex/version
conflict IDs. No authoring geometry or saved restoration state is accepted as a
command input. Dependency reads name selected owners; writes reserve common and
conditional output slots plus a whole-topology barrier for prefix-derived
relocation. Conditional binding/ligation slots remain reserved across upstream
length edits. Generated scopes are explicitly unqualified. History edits preserve
contract, seed and creation time while allowing consumer reference/input edits.

Admission reuses existing4096base,10k-node and256k-byte limits. The shared bounded
source walker accepts explicit extra collections only for this new contract;
finite/indirect v1/v2 defaults remain unchanged. Direct admission classifies live
references and native saved-topology ownership, protects historical output IDs,
requires exact conflicts, rejects edited/missing ligation or placement ownership,
checks driver/driven consistency and retained references after restoration, and
uses existing dedicated-host/complement ownership checks before geometry. Unknown
organization integration remains refused, not removed from the exit. No full
feature proof runs in ordinary Apply or viewport frames.

`part_connection_direct_recording` prepares under the existing document lock,
then invokes the shared materializer inside one recording callback. Source,
session/policy and revision acquisition use the existing owned Apply route.
Protected loadout/latest-cursor guards precede preparation. One native build,
one reconciliation/retry, one undo and detached source history are retained.
Only unsupported source profiles may fall back before recording; admitted
failures never retry legacy. `NATIVE_DIRECT_APPLY_ENABLED` defaults false.

Coverage: equal12/12, A-longer12/8 and B-longer12/16; both direct types; complete
ordinary-callback authoring parity; direct-to-direct and finite/indirect-to-direct
replacement; poisoned recovery bodies; exact conflict/collision/stale-owner
refusal; repairable missing endpoint paths; input identity preservation; an
upstream edit switching the native driver followed by a spawned verification
worker; actual HTTP Apply/reapply, undo/redo, failed publication/materialization,
body refusal and source-change acquisition. Documented limits remain important:
first-time combined direct Connect and direct-to-linker registered replay are not
yet implemented. Shared-host, applied metadata and organization integration,
ISSUE-126 scientific correctness and full qualification remain in the fixed exit.

Validation progression:23tests first failed on the absent contract/protection.
The first implementation passed17 with6 test-expectation failures comparing raw
builder output against reconciled executor output; corrected to apply existing
canonical postprocessing. Expanded35passed. A worker-edit fixture initially used
an incorrect `prepare_change` signature; corrected to the existing index/checkpoint
API, yielding41passed. Recording added6cases, yielding47passed. Added driver/
length ownership corruption and stale HTTP acquisition coverage. Final command:

`just test-affected tests/test_part_connection_direct.py tests/test_connection_direct_recording.py tests/test_connection_direct_identity.py tests/test_connection_direct_replacement.py tests/test_direct_connection_unified.py tests/test_duplex_length_preserve.py tests/test_overhang_binder_rotation.py tests/test_connection_composition_contract.py tests/test_connection_versions.py tests/test_part_connection_application_commands.py tests/test_part_connection_indirect.py tests/test_part_connection_compose.py tests/test_native_connection_application_proof.py tests/test_part_pending_connection_versions.py tests/test_connection_version_owned_apply_route.py --tb=short`

**374passed,33existing FastAPI warnings,18.07s**, including50new direct contract/
recording cases. Changed Python Ruff passes; full lint retains5baseline F401
findings. `main.js`7350lines,delta0. No molecular kernel/model/constants/pins/golden
changes; no frontend behavior or frontend test rerun.

`just test-smart --dry-run` selected FAST after deferring the historical
foundational FULL diff (5758files); **zero broad tests ran**. Literal notice:

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
Only request `just test-session` when a broad/full sweep is actually needed.
```

NOT VERIFIED IN APP: Archive mount absent; no browser/visual/latency acceptance or
bulk artifacts. Existing source/work limits are admission bounds, not a measured
latency claim. All rollout gates remain false. Counts21/38complete,17remaining;
+0total,+0completed;33engineering checkpoints since B1. FH-25 remains growth-flagged
after6. No narrowed exit, new milestone or estimate change.

Hygiene: memory lint retains6baseline errors/59warnings; current project head
remains200lines. Task pytest roots4/5/6 contained465empty directories,4symlinks
and0regular files/bytes. No readable same-user cwd/fd/maps references were found;
persistent systemd/PAM435/436 remain uninspectable. Removed only those completed
task directories/links; pytest root and `/dev/shm` are empty. No user designs,
managed jobs, historical evidence or caches were removed.


## U34 — closed first-time direct Connect

`connection-version-connect-direct` v1 is registered as one closed compound
recipe under `overhang-bulk`. It carries the strict pending-definition inputs,
creator version ID/time, identity namespace and exact prior conflict selections.
Pending version creation and native direct application share one candidate and
one canonical reconciliation/retry. No arbitrary nested command batch or output
snapshot is accepted. The strict `DirectSelection` fields/validators and bounded
conflict-table extraction are now shared with Apply; its saved v1 meaning stays
unchanged. The new version is a dependency write, not an impossible prefix read.
Generated scopes remain explicitly unqualified. History edits protect all creator
identity/time/contract slots while retaining editable sequence/type/reference inputs.

The ordinary adapter stages against an exact locked source and records once;
source/session/policy/revision acquisition reuses ConnectRoute. Loadout/latest
cursor guards precede preparation. Unsupported source scope may fall back only
before materialization; admitted failures never retry legacy. The separate
`NATIVE_DIRECT_CONNECT_ENABLED` flag defaults false, as does direct Apply rollout.
This adds no full proof to an ordinary edit or viewport frame. Native scientific
helpers, work/metadata limits, model pins, constants and goldens are unchanged.

Evidence: all six direct type/length cases (12/12,12/8,12/16) match separate
pending+Apply execution and the actual ordinary legacy callback's complete
authoring output. Compound replacement checks exact prior ownership. Tests cover
one postprocessing pass, malformed definitions, protected creator identities,
sequence/type history edits followed by a spawned verifier, HTTP Connect, one
undo/redo, source isolation, validation/materialization rollback without retry,
source-change acquisition and loadout/cursor guards. Eight initial cases failed
on the unimplemented composition; the first paired contract run passed51cases.
Expanded contract/recording validation passed82. Final17-file run:

`just test-affected tests/test_part_connection_direct_compose.py tests/test_connection_direct_connect_route.py tests/test_part_connection_direct.py tests/test_connection_direct_recording.py tests/test_connection_direct_identity.py tests/test_connection_direct_replacement.py tests/test_direct_connection_unified.py tests/test_duplex_length_preserve.py tests/test_overhang_binder_rotation.py tests/test_connection_composition_contract.py tests/test_connection_versions.py tests/test_part_connection_application_commands.py tests/test_part_connection_indirect.py tests/test_part_connection_compose.py tests/test_native_connection_application_proof.py tests/test_part_pending_connection_versions.py tests/test_connection_version_owned_apply_route.py --tb=short`

**408passed,33existing FastAPI warnings,20.98s**, including34new compound/route
cases. Changed Python Ruff passes; full lint retains5baseline F401 findings.
`main.js`7350lines,delta0; no frontend change or frontend rerun.

`just test-smart --dry-run` selects FAST after deferring the historical
foundational FULL diff (5763files); **zero broad tests ran**. Literal notice:

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
Only request `just test-session` when a broad/full sweep is actually needed.
```

NOT VERIFIED IN APP: Archive remains absent; no visual/latency qualification or
bulk artifacts. Direct-to-linker registered replay remains the next gap in the
fixed replacement matrix. Applied metadata, organized integration, history/repair
controls and full qualification remain open; shared-host and ISSUE-126 scientific
correctness debts are unchanged. This is not FH-25 closure or a rollout. Counts
21/38complete,17remaining;+0total,+0completed;34engineering checkpoints since B1.
FH-25 remains growth-flagged after7; no exit or denominator change.

Hygiene: memory lint retains6baseline errors/59warnings; current project head
remains200lines. Task pytest roots1/2/3 contained544empty directories,4symlinks,
0regular files/bytes. No readable same-user cwd/fd/maps references were present;
persistent systemd/PAM435/436 remain uninspectable. Removed only those completed
task directories/links. Pytest root and `/dev/shm` are empty. No user designs,
managed jobs, historical evidence or caches were removed.
