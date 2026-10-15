# Architecture review and completion sequence — October 15, 2026

The existing foundation is sound, but it is not a finished dependency or repair
system. Independent input replay, explicit empty/import roots, deterministic
identities, complete authoring-state comparison, failure-atomic recording and
revision-bound publication should be retained. Recovery snapshots remain useful
for undo/scrubbing and must never become evidence of native reproducibility.

The persistent implementation goal covers standard-part P3–P6. Assemblies remain
in `assembly_deferred.md`; part-local proteins, nanoparticles and duplexes do not.
The checkpoint before this review is `a8bc9fc9` (pushed).

## Findings that change the order of work

1. Dependency edges are mostly conservative whole-part barriers. They identify
   possible impact, not an exact missing reference or a proven blocked child.
   Several permissive native batch builders silently skip absent targets. Proof
   needs explicit reference preconditions so a reproducible no-op cannot conceal
   a dangling selection. Keep permissive historical recovery separate.
2. The native editor requires an already reproducible source. That protects
   unlogged work, but cannot repair a broken recipe. Add an explicit repair
   transaction, separate from ordinary edits, with a revision-bound candidate,
   precise diagnostics and an explicit decision about displaced geometry.
3. A thread deadline checked between commands cannot interrupt one long solver.
   Cancellation must stop isolated expensive evaluation before the admission
   slot is released. Keep ordinary recording, rendering and scrubbing free of
   full proof work; do not increase concurrency or relax existing test budgets.
4. Command availability is spread among recovery dispatch, proof dispatch and
   capability declarations. Consolidate versioned command metadata as contracts
   mature, keeping legacy decoders until persisted compatibility tests pass.
   Do not attempt a broad unmeasured rewrite of working native algorithms.
5. P3 also includes opaque `connectivity-core` generation. Compound branch
   construction/routing/budget work and CPD conversion remain incomplete.
   A generator must emit native commands and their actual inputs. A copied
   candidate Design is not an executable construction recipe.
6. Reproducibility, reference integrity and scientific validation are separate
   results. Existing `integrity_checked: false` is truthful; a verified replay
   alone must not become a general valid-design badge. Physical results remain
   display-only and require their own freshness provenance.

## Research and decisions

[Onshape's FeatureScript introduction](https://cad.onshape.com/FsDoc/intro.html)
documents the feature tree as calls with parameters, geometry as build output,
and regeneration as execution. Determinism excludes external input, time and
randomness. NADOC's registered inputs and chosen identity namespaces follow this
model; arbitrary Python may orchestrate those commands but is not itself a
native feature contract.

[Onshape feature errors](https://cad.onshape.com/FsDoc/output.html) roll back the
failing feature's effects. [Reference repair](https://cad.onshape.com/help/Content/Document/repairing.htm)
retains editable definitions and uses a prior healthy view to identify and
replace references, with optional downstream propagation. For NADOC, keep a
failed definition, its diagnostics and clearly labelled last-good geometry
distinct. Never silently drop failed features to make a badge green.

These are architectural precedents, not claims that those vendors enforce an
LLM-specific policy. A process with authority to rewrite NADOC's server or files
is outside application-level enforcement. Strict policy must live at the trusted
mutation boundary and cannot be downgraded by an agent's request fields.

## Implementation checkpoints and acceptance

| Checkpoint | Scope | Required evidence |
|---|---|---|
| P3 hardening | Explicit reference failures; process-bounded expensive evaluation; remaining branch/connectivity and CPD contracts | Missing/partial targets cannot certify; cancellation frees resources; all native inputs replay without saved outputs; no scientific algorithm changes |
| P4 standard-part assets | Pinned content and availability checks; protein/NP/duplex creation and attachment commands; imported-source labels; physical-result freshness | Offline deterministic replay from declared assets; source/parameter tampering fails; undo and persistence work |
| P5 repair | Structured failure/blocked/independent status; reference replacement; keep-broken drafts; same candidate for preview/commit; passive desktop and part-VR diagnostics | Repair from an invalid source, cancel/race/undo/reload tests, running-app checks, no hidden geometry or modal spam |
| P6 policy and cleanup | Atomic registered command batches; trusted strict policy; generic setter/import/headless bypass checks; retire superseded dispatch only with compatibility evidence | Editable native output from agent batches; unsupported/injected state rejected; human drafts and explicit imports preserved |

Cheap checks belong at the command boundary. Full cold replay is the oracle and
an explicit/background operation. Reuse an independently verified prefix first;
only reuse independent suffixes once declared reads/writes and equivalence tests
justify it. Record cold/warm latency and memory for representative small and
large documents; a microbenchmark is not evidence of interactive responsiveness.

Each checkpoint updates tests and the implementation ledger, runs required
validation, records existing regression debt separately, and is committed before
the next consequential choice. No bulk user-document migration or assembly
implementation is authorized by this sequence.
