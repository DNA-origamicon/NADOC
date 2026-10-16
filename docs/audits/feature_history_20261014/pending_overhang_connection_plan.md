# Ordinary pending overhang connection contracts

Implemented checkpoint: `acad1d51`. Assemblies and connection Apply remain separate.

The old ordinary candidate CRUD routes changed `Design.connection_versions` through
`mutate_and_validate` without a feature row. The new native path records explicit
inputs under the existing `overhang-bulk` kind, with one of three closed actions
(`connection-version-create`, `connection-version-patch`, `connection-version-delete`)
and `connection_version_contract=1`. No model literal or numerical pin changed.

`backend/api/part_connection_version_commands.py` owns the bounded schema, exact
endpoint/version lookup, immutable metadata builder and lock-owned route adapter.
Creation records identity/time once; editing preserves those values. A/B endpoint
order is exact. Sparse patch inputs retain the existing absent/null/blank rules.
The existing sequence cleaner and default-name algorithm are reused unchanged;
default names group unordered pairs and use the original creation order. Naming
copies old version records before filling any blank legacy names.

The contract reads both selected ordinary overhangs and, for edits/deletion, the
selected version. Missing references include typed parameter paths. Dependencies
remain a conservative part barrier. Unsupported scoped composition, auxiliary
nanoparticle endpoints, applied versions, explicit applied-flag patches and legacy
request shapes do not gain native authority. Missing native references fail
explicitly; there is no fallback after native evaluation. A pending alternative
may coexist with an applied connection on its endpoints.

The metadata policy is shared by recording and replay and validates the entire
closed schema. It skips cluster reconciliation and pending-ligation retry because
the original pending routes did neither; this avoids unrelated topology changes
and unnecessary work. Photoproduct guards, full validation, repair draft retention,
atomic rollback, revision advancement and one undo remain in force. Malformed
claimed actions fail before their callback; the safe classification helper returns
false for malformed/non-string discriminators. No geometry, placement, polarity,
sequence assignment or scientific calculation changed.

Validation reported by root: the native fixture passed and the missing-log route
and unknown-action replay tests failed as intended before implementation (the
combined serialized run, including other queued tests, took 4.04 s). Afterward,
seven focused files passed **147 tests in 6.56 s**, with 43 deprecation warnings.
Coverage includes poisoned recovery/cold worker proof, source identity and creation
time, naming/bridge/sequence semantics, endpoint removal/cascade, one-undo CRUD,
unrelated ligations/domain-cluster metadata, CPD refusal, draft retention and
encode/validation/publication/cancellation rollback. See
[validation evidence](validation_pending_overhang_connections_p4.json). No app
exercise or large-model performance qualification is claimed.

## Performance measurement before expansion

`scripts/benchmark_pending_overhang_connections.py` prepares five finite cases:
six-cell native DNA with 0/16/128 pending rows, and sixteen-cell DNA with 16/64
pending rows. Every table row has its own native command and matching recovery;
the benchmark does not manufacture an unlogged candidate table or claim to run
cold proof. Each repetition alternates old/new route order, performs create/edit/
delete and an atomic missing-endpoint refusal, and retains every timing sample.

The old module is read directly from `bc2ae3cb` into a private in-memory router.
Both routes use the same current state/core runtime; this is a route/recording
comparison, not a whole historical binary comparison. Measurement includes
response bytes, revision/undo/history semantics, lock hold/wait, snapshot copy,
snapshot encoding, validation/response work, natural GC overlap and paced scalar
revision reads throughout the complete request (bounded at five seconds). The
historical route records no history, so some added snapshot cost is intentional;
all overhead/refusals must remain visible and existing budgets stay unchanged.
There is no forced GC, app lifespan, browser, simulation, scratch directory or
workspace output. Isolated documents, wrappers and locks are cleaned in `finally`;
stdout JSON is the only result. Root alone runs this benchmark.

### Initial measured regression (not latency-qualified)

Root completed nine repetitions of all five paired cases: 360 requests, cleanup
and semantic checks passed, no dropped GC events, maximum RSS 146,156 KiB. The
report's `all_checks_passed` means correctness and cleanup only; it is **not** a
latency qualification. The raw report retains natural GC and every request:
[initial benchmark](benchmark_pending_overhang_connections_initial.json).

All values below are milliseconds. Successful overhead is the range of
current-minus-historical medians across create, patch and delete. The final three
columns concern the missing-endpoint request only.

| Native DNA / retained rows | Successful median overhead | Historical / current 404 median | Current 404 maximum | Current 404 lock maximum | Concurrent revision-read maximum |
| --- | ---: | ---: | ---: | ---: | ---: |
| Six cells / 0 candidates | 0.41–0.52 | 1.95 / 2.97 | 3.38 | 1.18 | 3.40 |
| Six cells / 16 candidates | 0.53–0.69 | 1.91 / 3.56 | 53.03 | 50.89 | 53.09 |
| Six cells / 128 candidates | 0.37–1.10 | 2.15 / 7.37 | 8.05 | 5.56 | 7.81 |
| Sixteen cells / 16 candidates | 0.61–0.80 | 1.94 / 4.99 | 58.18 | 56.01 | 57.84 |
| Sixteen cells / 64 candidates | 0.80–1.34 | 1.94 / 6.54 | 58.42 | 56.28 | 58.34 |

The historical missing-endpoint route performs no undo copy or snapshot encode.
The new route resolves endpoints inside the recording callback, after the undo
copy and pre-snapshot encode. The three long refusal samples spent 49.28, 53.48
and 52.60 ms in natural GC while holding the document lock. They delayed
concurrent revision reads. Historical successful requests also have natural GC
tails (up to 67.82 ms); those remain in the report and do not excuse the newly
avoidable refusal work. **The new under-lock cost remains an open regression.**

The immediate repair is one shared, pure selection/preparation step, used by the
public builder and the ordinary route. Under the existing lock, it validates the
exact selected version, ordered endpoints, ordinary ownership and distinctness
before output identity/time allocation and before entering the recorder. A
private receipt belongs to that exact source and parsed command; the callback
uses it without repeating selection or silently falling back. Generated output
ID collisions must also reject before recording. No API caller receives a
postprocessing-skip flag or can supply its own prepared result.

`tests/test_pending_connection_early_refusal.py` adds tests-first traps for both
missing create endpoints, a self-pair, missing patch/delete versions and dangling
patch/delete endpoints. They require exact typed errors, zero whole-design work
or output identity allocation, and unchanged object, undo/redo, revision and
request markers. Root will record the red baseline before production changes.

Successful requests currently take **one** independent undo copy, as the
historical mutation helper does, plus the two new recovery encodes. The undo
copy is not redundant: subsequent compatibility callbacks can mutate nested
models, so retaining a shallow source as undo would corrupt history. Pure
metadata preparation can avoid repeated bounded selection, but must retain that
copy, full validation, CPD protection, draft preservation and rollback. Reusing
the preceding feature's snapshot without exact ownership is unsafe after other
metadata/source/loadout mutations; hashing the entire model under the lock is
not an acceptable substitute. Existing minor diffs also still encode post-state
and do not cover connection-version rows. Any compact recovery representation
is a separate reader/format change requiring exact seek/revert/undo tests before
it can remove an encode. No format switch, budget increase, GC suppression or
positive-path performance claim is authorized by this first measurement.

## Next independent families

1. **Ordinary Apply/connect:** extract the existing compound operation without
   changing its molecular algorithms. Its current receipt records only version ID
   and type, while execution can revert prior bindings, create binding/duplex/
   child-cluster/linker identities, relocate different-length pairs and reassign
   dependent sequences. Record exact input selections and identities; test direct
   equal/unequal-length, indirect, ss/ds and replacement parity separately.
2. **scadnano import:** reuse the bounded fresh-empty, pinned-source caDNAno
   architecture. Preserve recenter, OH detection/sequence backfill, clustering and
   integrity checks. Preflight spans/loopouts/extensions before expansion and
   reject its embedded `photoproduct_junctions` model extension. Imported topology
   remains imported provenance, including files generated by scripts.
3. **Biotin DNA:** current native pocket/orientation/phase search also consults
   existing DNA obstacles, an implicit streptavidin template, and display chemistry
   with SQLite fit caching. It needs explicit source/engine contracts, stable
   identities and bounded evaluation; it is not a metadata-only follow-up.
4. **Duplex DNA PDB:** preserve original source authority and bound pairing search.
   Existing output identity randomness also affects atom sorting, and atomistic
   output lives in a separate session cache; both require explicit deterministic,
   atomic treatment. Existing library/open-part is document navigation and should
   retain the file's actual recipe/unknown status, without invented history.

This import boundary follows [Onshape's official imported-CAD behavior](https://cad.onshape.com/help/Content/Document/working_with_imported_cad.htm):
the Import feature has an explicitly replaceable source, imported geometry does
not supply its original parametric history, and downstream features can fail
after source replacement. Exact missing-reference diagnostics are preferable to
guessing correspondence or granting arbitrary imported bytes native-construction
authority.
