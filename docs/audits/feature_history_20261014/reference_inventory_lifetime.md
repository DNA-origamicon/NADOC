# Reference inventory scratch lifetime

October 15, 2026. `referenced_resources()` created a recursive local `visit`
function whose closure referred back to itself. Each inventory call left a
collectable cycle retaining its temporary reference set until cyclic GC ran.
Finite Apply visits every retained authoring record; the legacy callback does
not perform this inventory. The cycle held typed reference tuples and strings,
not a cached Design or geometry payload.

The recursive visitor is now a module-level helper. The public function, typed
schema, traversal order, errors, linker ownership, deformation selections, CPD
keys and saved-definition subtraction are unchanged. No cache, numerical
algorithm, manifest, command limit, GC policy or rollout gate changed.

The first tests-first run had **9 passes and 2 failures in 2.90 s**: the expected
immediate-lifetime failure and an invalid CPD control fixture. Production stayed
unchanged while that fixture was corrected to the real two-endpoint coordinate
contract; its independent control then passed **1 case in 2.73 s**. After the
extraction, **247 cases across seven files passed in 5.37 s**, including all 11
new lifetime/semantic cases. The lifetime assertion observes weak references to
temporary storage after return; it neither forces GC nor changes its settings.
Caller coverage includes generated scope/saved topology, finite and NP Apply,
DNA comparison and the owned finite route. See the [validation record](validation_reference_inventory_lifetime.json).

Two separate compact-parity HTTP runs used the same benchmark script and route
sources, with only the reference helper changed. Each retained all **496
successful Apply/reapply requests, 124 exact authoring/response parity pairs,
four verified input-only replays and two missing-endpoint controls**. Cleanup
passed, and no GC events were dropped. Four fixtures cover six-cell/42-bp and
16-cell/84-bp native prefixes, ss/ds links and 1/16 real pending history rows.

For 16-cell ss reapply, values below are milliseconds. Lock values sum all
outer holds per request; pooling individual holds would compare legacy's two
holds against native's one.

| Metric | Before legacy | Before native | After legacy | After native |
|---|---:|---:|---:|---:|
| HTTP median | 73.552 | 125.832 | 71.304 | 72.985 |
| HTTP p95 | 130.262 | 141.318 | 135.737 | 135.619 |
| Per-request maximum revision-read delay, p95 | 69.999 | 70.593 | 67.785 | 68.820 |
| Concurrent revision-read maximum | 71.436 | 72.481 | 67.872 | 71.359 |
| Summed lock median | 5.852 | 7.191 | 5.450 | 6.970 |

The large observed median regression is absent after the extraction in this
rerun. This does **not** qualify interactive latency: long HTTP/read tails remain,
and the after-run native 16-cell ds Apply maximum is 181.677 ms. Natural-GC
overlap is retained as correlation, never subtracted from elapsed time.
The gate remains `OWNED_FINITE_CONNECTION_APPLY_ENABLED=False`.

Compact mode releases raw, decoded and normalized client responses before the
next request, retaining exact semantic digests. Untimed normalization still
shares the server process and can alter collection cadence; this is not external
browser or application validation. The earlier full-response-retention runs
remain valid evidence of that harness profile and are neither erased nor
retroactively relabeled. The initial ds mismatch and bounded diagnostic also
remain: only the known random ID in the existing occupancy-warning location was
normalized; its warning, polarity and verdict remain compared.

Reports: [compact baseline](benchmark_finite_connection_apply_compact_baseline.json),
[compact after extraction](benchmark_finite_connection_apply_compact_refactor.json),
[initial run](benchmark_finite_connection_apply_route_initial.json),
[warning diagnostic](benchmark_finite_connection_apply_route_warning_diagnostic.json),
[corrected full-retention run](benchmark_finite_connection_apply_route.json).
Broader app/latency qualification remains in the [route plan](ordinary_connection_owned_route_plan.md).
