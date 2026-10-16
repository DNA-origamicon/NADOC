# Finite ordinary Apply: private route integration

Tests-first proposal, 2026-10-15. This increment concerns existing-version
finite ssDNA/dsDNA Apply and reapply only. It does not enable a public gate,
change molecular algorithms, add model fields or alter numerical pins.

`routes_connection_versions.OWNED_FINITE_CONNECTION_APPLY_ENABLED` defaults to
`False`. When enabled, `_apply_connection_version_impl` may call
`part_connection_application_commands.try_record(version_id)` only when
`new_version is None`. The existing callback remains explicitly available as
`_apply_connection_version_legacy(version_id, *, new_version=None)`; disabled,
direct, indirect, combined Connect and unsupported source profiles retain that
path and their existing history authority. The compatibility branch is chosen
before native materialization. Selected missing/invalid references and any
materialization or publication failure are explicit, never reasons to retry
through legacy. Bounds remain provisional eligibility for the private branch;
they do not introduce unqualified user-facing refusal of larger legacy work.

The native adapter holds the existing state lock through selection and recording.
It checks compatibility policy and active-loadout editability, selects the actual
current version and ordered endpoints, freezes exact conflict IDs, allocates one
connection ID and binds the prepared command to that source. Preparation reuses
one bounded source walk and one typed identity inventory. The recorder callback
consumes that receipt and the existing `_materialize` directly; calling `build`
again would duplicate selection, and calling proof `execute` would duplicate
reconciliation/retry. Detach the feature-log list before the recorder appends.
The private receipt return shape is not an API contract.

`record_feature` retains one whole-design undo copy, PRE/POST recovery encodes,
normal topology reconciliation, pending-ligation retry, CPD guard, validation,
draft retention and failure-atomic revision/context publication. No proof,
whole-source comparison or additional private Design clone runs on normal Apply.
The scientific native helpers retain their current sequence and geometry behavior.

A shared `_connection_apply_response` retains the existing occupancy diff and
response serializer. Finite Apply/reapply changes `overhang_connections`, so
`_local_changed_helices` currently selects **full geometry**, not partial geometry.
The partial serializer also excludes `__lnk__` IDs from its real-helix set. This
increment must not bypass either rule or claim partial finite-linker rendering.

`tests/test_connection_version_owned_apply_route.py` uses the existing authentic
six-cell native bundle/extrusion fixture with dedicated overhang hosts. It invokes
the actual routes, recording transaction and small geometry response in memory.
It covers ss/ds Apply/reapply, recorded identities and exact conflicts, fresh
deserialization/root replay with poisoned recovery, one-undo behavior, unrelated
manual sequence/draft preservation, bounded preparation/copy counts, early typed
refusal, no fallback after failure, compatibility dispatch and the full-response
contract. Direct/indirect/combined dispatch tests intercept the explicit legacy
seam; their existing algorithm parity suites remain authoritative. No worker,
solver, application lifespan, file/package write or native bulk scratch is used.

After correctness, qualification must measure the actual complete HTTP response,
lock hold/wait, selection, one undo copy, both encodes, native work, response bytes
and concurrent lightweight reads. Include retained native history and natural GC;
the 4,096-base source bound excludes history/presentation, so it cannot establish
whole-request latency. Keep the gate disabled until this evidence is reviewed.
The legacy shared-host sequence-resize defect remains separately open.

Status: implemented behind the disabled gate. Root executed 244 distinct cases
across nine files, including 35 new route cases. Preflight failures exposed and
fixed version classification order, output-ID checks and overbound conflict
fallback. No native algorithm or numerical pin changed.

The complete HTTP benchmark covers four native fixtures, 31 alternating pairs
each and Apply/reapply: 496 successful requests, two missing-endpoint controls,
124 full authoring/response parity pairs and four fresh input-only replays.
The first run's ds warning mismatch was traced in a separate one-repeat diagnostic
to an unquoted random virtual-helix ID. The final oracle normalizes only that
known occupancy-location token; the original warning, polarity and verdict are
still compared. Initial and diagnostic evidence is retained. Cleanup passed and
the bounded natural-GC probes dropped no events.

Latency is **not qualified**. In the final run, 16-cell ss reapply was 144.27 ms
native versus 96.30 ms legacy at the median (initially 145.20 versus 73.26 ms).
Both arms have substantial GC-overlapping tails. Summed per-request lock medians
were 7.43 versus 6.07 ms; compare these rather than pooled individual holds,
because legacy takes two holds per request and native one. Natural GC overlap
does not remove user-visible cost or establish its cause. Investigate reference
inventory allocation and retained benchmark lifetimes before any optimization.
The public gate remains false. See [validation](validation_finite_connection_apply_route.json)
and [complete measurements](benchmark_finite_connection_apply_route.json).
