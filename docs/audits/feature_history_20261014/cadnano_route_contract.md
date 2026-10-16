# P4 pinned caDNAno route boundary

October 15, 2026. This is a separate explicit endpoint; the legacy caDNAno upload
route and ordinary file replacement remain unchanged.

`POST /api/design/features/import/cadnano` takes original UTF-8 caDNAno v2 bytes
as an `application/json` body. Query parameters are required
`expected_design_id` and `expected_revision`, plus optional `name_override`.
The endpoint streams at most 100,000 bytes, checks declared size before reading,
checks actual cumulative size before copying each chunk, and rejects compressed
request bodies. ASGI server-owned receive buffers are outside that application
retention bound. No multipart spool, eager request JSON decoder, mutable source
path or fallback importer participates.

The active target must be a **fresh explicit empty part**, not merely a design
whose visible geometry was deleted. The pure command's empty-root/history/
authoring checks run before body reading. Route-only checks reject retained
input sources and nondefault physical or presentation fields using `FIELD_ROLES`
and the explicit empty baseline; an unclassified new field fails admission.
The initial name is bounded to 1,024 characters. This keeps the old part's undo
snapshot small under the shared state lock. A missing or nonempty target gets a
clear request to create a fresh empty part/tab; the existing legacy upload still
supports ordinary nonempty replacement.

The route captures only the current reference and revision, then builds a new
empty-root lineage privately. Native import, immutable source embedding, both
recovery snapshots, validation and response formatting run in a context-aware
worker thread outside the state lock. The response helper's recipe-root branch
skips legacy default-cluster publication. The candidate contains one source-
bearing Import feature, with no copied output geometry in its parameters. It
retains imported provenance rather than claiming native-only construction.

Publication uses the existing `state.set_design` identity/revision guard and one
undo snapshot. The new document ID/root does not inherit the empty tab's file
identity or presentation state. Undo restores that small prior part, while
feature-history revert independently restores the Import feature's own explicit
empty root. Disconnect is checked immediately before publication; stale input,
builder, encoder, validator, formatter and undo-snapshot failures publish no
candidate. Actual HTTP response revision is the value returned by publication,
not a precomputation timestamp or thread-local stale value.

## Qualification evidence and remaining performance gate

The parent ran 44 pure-command and 10 registered-history tests, with 63 warm and
seven cold benchmark reproductions under unchanged capture limits. Maximum
observed capture was 8.82 ms and maximum pickle size 222,350 bytes. The existing
87 KB fixture required 93.9 ms private preparation in that run; this motivates
the threadpool boundary and is not a guaranteed latency ceiling.

`tests/test_part_cadnano_routes.py` adds HTTP and stream limits, fresh-host
admission, full source/history roundtrip, undo/redo, independent cold proof,
cross-document context, stale target changes, disconnect and preparation-fault
coverage. Root serializes these runs.

`scripts/benchmark_cadnano_route.py --repeats 9` exercises the actual async route
through an isolated FastAPI/TestClient app for both real small sources and a
100 KB padded boundary. A delegating lock probe records actual lock wait/hold
intervals for reference capture, private response reads, publication and a
concurrent lightweight HTTP revision endpoint. It reports baseline/concurrent
request latency, observed publication overlap, p50/p95/max and raw samples.
It introduces no artificial lock delay and does not infer zero contention from
zero observed overlap. The standalone process starts no production lifespan,
creates no files and removes its one owned session with `drop_doc` in `finally`.
Ordinary proof capture and its limits remain unchanged.

## Deferred exceptional publication hardening

`state.set_design` performs its expected-revision/source and molecular checks,
then computes the undo snapshot before mutating history. A snapshot failure is
therefore atomic and covered by the new route test. However, after appending
undo, clearing redo and assigning the candidate, it calls `_bump_revision`
without a transaction rollback. An exception in that hook can leave a partially
published design/history/revision. Currently the hook only increments an integer
and calls `ContextVar.set`; ordinary validation or input errors cannot reach
this failure window. It remains reachable through injected faults or exceptional
interpreter/resource failures.

Do not claim the helper has the stronger `feature_recording._transaction`
failure contract. Track this as **P6 shared publication transaction hardening**:
centralize rollback of design, undo/redo, revision and request markers in the
state owner, then test failures both before and after request-revision update.
Avoid a route-local private-session mutation or a second conflicting transaction
implementation. This slice deliberately retains the existing shared helper.

## Executed route qualification — October 15

All 47 focused route tests passed. The 27 real HTTP benchmark imports published
correctly and removed their isolated session afterward. Private preparation did
not acquire the shared state lock. Publication hold medians were 0.065/0.112/
0.066 ms for the 7.8 KB/87 KB/100 KB sources; the largest observed hold was
1.34 ms. Lightweight request lock waits stayed below 0.004 ms in this sample.

End-to-end costs were higher and remain relevant: import medians were 10.7/90.1/
16.6 ms. The first small import reached 576 ms with cold module setup. Concurrent
lightweight HTTP medians were 2.98/6.32/3.53 ms versus baseline 0.92/1.06/0.93 ms;
the 87 KB case had a 52.8 ms p95 and 97.8 ms maximum. Thus the state-lock scope is
small, but CPU work, interpreter scheduling and HTTP serialization still affect
responsiveness. These measurements do not prove a browser-wide latency bound or
zero overhead. The existing import route remains unchanged and no proof runs
automatically during rendering or ordinary edits.

See [raw route evidence](cadnano_route_benchmark_p4.json), including all samples,
actual overlap counts, cleanup verification and instrumentation limitations.
