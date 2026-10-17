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
