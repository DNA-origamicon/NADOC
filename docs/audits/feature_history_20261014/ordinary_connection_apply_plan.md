# Ordinary overhang Apply: next native contract

Read-only audit, 2026-10-15. Pending CRUD is implemented at `acad1d51`; its
measured refusal/recording regression must be addressed before expanding live
admission. This document does not enable Apply, change a scientific algorithm or
claim performance qualification. Assemblies remain deferred.

Tests-first pure slice is prepared in
`tests/test_part_connection_application_commands.py` (36 cases, not yet run).
Its proposed `build(design, params) -> (Design, MutationReport)` uses the closed
schema below. Two controls capture the existing route's actual callback against
the authentic native bundle/extrusion prefix, injecting only the random output
connection ID. The remaining cases compare complete authoring parity or require
strict input/ownership/budget refusal. No route admission, dispatcher, model,
identity policy or numerical source has changed for this new slice. Combined
Connect and registered cold proof remain subsequent integration gates.

## Existing authority and behavior

`backend/api/routes_connection_versions.py::_apply_connection_version_impl`
records only `version_id` and `connection_type`. That is not enough to regenerate
its output: the callback can allocate a connection, binding, duplex and child
cluster, revert saved topology from existing bindings, and modify sequences.
`create_and_apply_connection_version` additionally creates a version inside the
same mutation. Preserve its one-undo behavior.

The actual callback, rather than its stale resize docstring, defines parity:

1. Clean each selected version sequence and truncate/N-pad it to the **live**
   backing-domain length before `_build_overhang_patch`. A stale version does
   not resize an overhang back to its old length.
2. Remove every materialized connection and binding sharing **either** endpoint,
   including connections to a third endpoint. Bound bindings can restore
   `prior_driven_topology` before removal.
3. Direct types create a bound binding for equal selected lengths and a display
   duplex; different lengths can instead use `relocate_duplex`. Linker types
   create `OverhangConnection`, assign its name, then call the existing
   `generate_linker_topology`. Indirect types use zero bridge length; finite
   types use at least one base pair.
4. Run existing targeted dependent-strand reassignment against the complete
   source design; update the selected version's padded sequences; mark it
   applied and clear all versions sharing either endpoint.
5. Run established recording/reconciliation/CPD validation. Return the existing
   occupancy-derived partial geometry/axes response. Full rendering previously
   caused a large local-Apply UI regression, documented at that response seam.

`part_linker_commands.create` is **not** an equivalent replacement: it adds
polarity/attachment compatibility and per-end uniqueness gates that this Apply
route does not use. Do not silently substitute that algorithm or manufacture
isolated two-overhang geometry lacking scaffold/cluster context.

## Smallest useful contract

Start with finite ordinary ssDNA/dsDNA linker Apply (the existing eight attach
type combinations) and existing-linker replacement. Defer direct bound/duplex
relocation and its saved-topology restoration to a separate contract. Admit
zero-length indirect types only after their distinct no-virtual-helix path has
its own parity and dependency tests.

Use a new closed action under existing `overhang-bulk`, for example
`connection-version-apply-linker`, with `connection_application_version=1`.
Do not edit `models.py` merely to add an operation literal: that would invalidate
unrelated numerical manifests. Record:

- Selected `version_id`, exact ordered `overhang_a_id` / `overhang_b_id` and the
  authored type. Length/sequence come from the selected pending version; an
  upstream version edit then intentionally regenerates the linker.
- Exact ordered conflict connection IDs and all overlapping version IDs whose
  applied flags will be changed. Recompute the conflict set and require exact
  agreement; never remove newly appeared topology silently.
- Stable output connection ID allocated once. Native generated ownership is
  already deterministic: helix `__lnk__{id}`, single-strand `__lnk__{id}__s`, or
  double-strand `__lnk__{id}__a` / `__lnk__{id}__b`.
- For combined Connect, a separate closed action carrying the strict pending
  version definition, its stable ID/time and connection ID. This retains one
  command/undo without accepting an arbitrary output design or snapshot.

Initial eligibility requires unique ordinary endpoint owners and backing
domains with consistent subdomain coverage. Refuse overlapping bindings,
duplexes, auxiliary NP owners and unreviewed incoming owners of removed linker
topology. Keep exact missing-reference diagnostics; no fallback follows an
admitted builder failure. Existing unsupported compatibility cases retain their
old route and unknown-history status.

Two ownership traps need explicit tests before replacement is admitted:

- `lattice.remove_linker_topology` removes IDs by prefix. A connection ID that
  prefixes another connection's generated ID can consume unrelated topology.
  Prove the actual removal set equals the selected linker's exact generated
  grammar; reject conflicting legacy identities rather than changing the core.
- `lattice._find_overhang_domain` selects the first matching domain. Require a
  unique consistent owner before calling it. Similarly, reject dangling incoming
  crossover/ligation/deformation/attachment references to removed generated
  resources. Do not silently adopt a dangling output ID for a new owner.

Typed dependencies include selected version, both endpoints and backing owners,
exact removed connections and affected versions, and produced connection/helix/
strand identities, with a conservative part barrier. Apply is topology work and
must **not** enter the pending-metadata postprocessing exception.

## Cohesive implementation and gates

Extract the existing materialization callback into an HTTP-free API helper with
optional explicit identities, preserving its call order and default legacy UUID
behavior. Keep compatibility imports for any tested route helpers. A new
`part_connection_application_commands.py` owns strict input, closed source
selection and identity/ownership checks. The route freezes selections under the
existing lock; the proof dispatcher calls the same builder. Do not edit lattice,
sequence assignment, relocation, geometry formulas, constants or kernel manifests.

Bound source selection and prospective output before native work. Two anchor
lookups are not constant-time: `_linker_anchor_nuc` uses the existing full native
geometry pipeline for a selected helix. Sequence reassignment derives the
complete scaffold before copying only affected strand results. Measure selected
helix slots, total relevant spans and bridge length; retain existing operation,
capture and worker budgets. Missing-ref refusals must precede undo/recovery work.

Meaningful tests, in order:

1. Real native bundle/extrusion prefix, pending create, then Apply; old/new exact
   authoring parity with only injected identities/time normalized. Cover all
   admitted attach/type combinations and real 5′/3′ endpoint orientations.
2. Source immutability, stable output identity, poisoned recovery cold proof,
   version bridge-length edit, upstream overhang resize with exact sequence
   truncate/N-pad behavior, and complete combined Connect undo/redo.
3. Replacement sharing a third endpoint; exact conflict-set changes; prefix-ID
   collisions; dangling owners; missing version/endpoints; no mutation or
   fallback after refusal. Keep unrelated manual strand sequences unchanged.
4. Existing `test_connection_versions.py`, `test_direct_connection_unified.py`
   and `test_targeted_reassign.py` remain parity oracles for legacy behavior.
   Direct cases remain unsupported native history rather than being relabeled.
5. Bounded natural-GC route/lock/concurrent-read benchmark with retained native
   history, and exact partial-response footprint. Keep failures and initial
   limits; do not turn correctness success into latency qualification.

The input/identity contract is the software change. Calling existing native
functions is essential to avoid introducing new molecular choices. Any actual
polarity or placement ambiguity requires the repository's scientific review
process before implementation; none is resolved by this audit.
