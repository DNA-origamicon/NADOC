# Owned local DNA oxDNA preparation input

Bounded core/host implementation, 2026-10-15; private route integration is now
under tests-first validation. No solver execution, scientific formula change or
complete input receipt is part of this slice. A server-owned rollout constant
remains false pending route correctness and measured capture/HTTP qualification. VR/headset validation is deferred to a capable-machine session.

## Current validation state

The shared graph/recovery extraction was independently checked against six
pre-extraction exact-accounting controls and 114 post-extraction capture/worker
cases; it was committed as `3e12323f`. Its existing proof selection, deadlines,
copy seams, alias/cycle behavior and recovery helper exports remain unchanged.
The archive extension adds rejecting shape/cycle rules, never a field-exclusion
or accounting-bypass option.

The initial 58-case archive/host run produced 53 passes and five expected review
failures: two opaque overhang truthiness cases, mapping key inspection preceding
remaining-node admission, duplicate source classification, and unbumped source
Design-ID drift. Corrections passed all 58 cases together with the 114 existing
capture/worker cases (172 passed, four existing warnings, 10.01 seconds). Peer
review then supplied one additional failing no-hook control: a dict subclass
installed as an exact model's backing storage invoked its `keys()` hook. The
model gate now requires exact dictionary storage before inspecting keys. Three
further negative controls reproduced opaque-key equality hooks in storage and
option headers and the host's early identity lookup. The shared header guard now
checks fixed size and exact string keys before equality or ID extraction. The
final run passed all 62 archive cases and 114 regression cases: 176 passed,
four existing warnings, 10.17 seconds. The shared dictionary
preflight is limited to callers supplying a rejecting validator; ordinary proof
capture retains its existing path. The test result and exact target list are
recorded in `validation_oxdna_preparation_capture.json`.

## Concrete boundary

`create_oxdna_job` currently calls
`get_or_404().without_reference_geometry()`. The latter is a filtering projection,
not isolation: nested strands, domains, helices, poses and history remain shared
with the mutable live document. The same projected object later supplies project
revision metadata, geometry, legacy fingerprints, and threaded
`prepare_oxdna_job`, which writes it as `design.json`. Copying geometry alone or
recording a revision number does not prevent mixed inputs.

Capture one complete independent `Design` under the existing document lock.
Retain every declared document field, including legacy/unrooted history,
opaque recovery strings, cursors, presentation and archival physical metadata.
Do not use proof capture's filtered history headers, run model-load migrations,
infer a recipe root, or require native feature proof. Only then call the unchanged
`without_reference_geometry()` on that private copy. The resulting single owned
projection must supply all existing preparation consumers and the archived
`design.json`. It keeps the existing reference-filtered archive semantics while
making the source internally consistent.

The copy is private preparation input, not a new live state, persistent cache,
immutable revision or publication permit. Two private views may share objects
with each other after isolation; neither may retain mutable objects from the
active document. No generic callback receives the live source.

## Proposed small modules and host seam

- `core/oxdna_preparation_inputs.py`: closed profile/schema assessment and
  `capture_archive(source)`, using shared bounded graph accounting and copying.
- `core/oxdna_preparation_schema.py`: positive exact inventories for each admitted
  nested archival model; unknown fields, private state and copy hooks refuse.
- `api/oxdna_preparation_capture.py`: `capture_current(options,
  expected_revision=None)` and `require_current(captured)`. It owns no session
  registry, job catalog, queue or lifespan.
- Future thin wiring in `routes_oxdna.py`: capture before sequence checks,
  geometry, job/lineage allocation or package I/O; explicitly choose the
  compatibility path for unsupported scope; recheck origin before the first
  lineage/package side effect; pass the same captured design throughout.

The host record binds the canonical document ID, actual session object and its
incarnation, exact source object, source revision and captured Design ID. Exposed
origin fields are immutable scalars; live-source ownership remains private.
Missing documents never cause lazy session creation. Required revision mismatch,
source replacement, close/reopen ABA and a changed current document fail with
409 before side effects. An absent part returns 404. Do not let callers supply a
session incarnation or claim that a saved origin record is authoritative.
The final guard also compares the captured Design ID. Strict immutable sources
explicitly refuse this mutable capture API without decoding; a separate owned
immutable adapter would need its own review. The host only classifies request
options; `capture_archive` owns the single source-profile/accounting pass.

After package creation starts, later ordinary edits must not mutate the frozen
input. They may make the job describe an older source. Do not cancel an otherwise
valid frozen preparation merely because the user edits afterward, or claim that
the prepared package is still current. A mutable alias edited without advancing
revision cannot be detected by identity/revision alone; isolation prevents mixed
package contents but does not close that broader freshness/cache limitation.

## Closed first profile, independent of history support

The first assessed profile is local DNA2 with CPU or CUDA, ordinary engine
selection and no arbitrary stage overrides, surface, anchor, capture-strand,
remote-parent or external-file inputs. Request classification consumes an exact
server-built subset of the existing validated create request; it is not a new
public protocol DTO or a source of new numerical defaults.

Retain canonical DNA helices and axes, loop/skips, strand topology and sequence,
crossovers/forced ligations, native deformation definitions, whole-helix/domain
cluster poses, nucleotide poses and ordinary unbound overhang pose/sequence.
Review each participating nested model's exact field inventory. A new
`Design`/nested field cannot silently become covered. Full archive capture must
still preserve non-consumed metadata such as names/colors, annotations, history,
sources and repair proposals; this ownership slice does not yet define the final
consumed-model freshness digest.

Particles/coatings, proteins, photoproducts, imported native residue geometry,
atomistic references, applied binding/linker/flexible geometry and other
unreviewed source families remain unsupported by this first profile. A nonempty
unsupported family is detected before its opaque contents are traversed. Return
`supported=false`, `design=None`, and an explicit unknown-coverage reason. Never
drop that family to create an apparently supported DNA package. Existing route
compatibility remains available outside the reviewed profile and retains an
honest unknown result; that path's broader input isolation is not declared solved.

For a supported profile, return the owned reference-filtered `design`, immutable
origin scalars and `supported=true`. Physical coverage still reports unknown:
owned model input alone does not prove packaged files, actual executable,
resolved attempt/retry inputs, successful simulation or native editability.
Do not mint a complete receipt in this slice.

## Bounds and factoring prerequisite

Reuse the ordinary 30,000-node / 2,000,000-byte accounting and 25 ms cooperative
capture allowance for non-recovery contents. Retained encoded recovery uses the
existing 2,000-row / 8,000,000-byte admission, counting actual strings without
decompression; claimed snapshot sizes are not authority. All other archival
content, including nested presentation, physical and source metadata, counts
against the ordinary allowance. These are admission bounds, not a hard lock-time,
heap, geometry-generation or simulation-runtime guarantee.

`part_capture_inputs.visit_inputs` retains its proof-specific selection/copy
policy and now delegates graph charges to `part_capture_graph`.
`part_recovery_storage` contains the existing encoded-storage accounting,
re-exported unchanged by the API helper. Full archive selection remains a
separate positive policy; no duplicated recursive walker or generic
skip-fields/budget-bypass flag is exposed. Recovery's separately charged immutable strings may be shared; mutable
containers must not be shared with the source. Unknown object hooks, private
model state, schema drift and cyclic/non-JSON structures need explicit refusal,
not arbitrary `deepcopy` execution followed by an apparent owned verdict.

A reviewed-profile limit failure is a complete named refusal
(`oxdna_input_capture_limit`), before geometry or any job/package side effect.
It must not fall back to the shallow live Design, retry with larger limits, or
mix partially captured fields with current state. Cancellation propagates and
leaves source, history, redo and revision unchanged. Time checks are cooperative;
Python/GIL/GC pauses must remain visible in eventual measurement.

## Tests-first dossier and remaining integration checks

`tests/test_oxdna_preparation_capture.py` used lazy module imports during the
initial tests-first phase so the absent implementation did not break collection.
It covers exact archival equality,
legacy recipe acceptance, deep authoring/history/presentation alias independence,
reference projection after isolation, retained DNA pose families, CPU/CUDA scope,
honest unknown evidence, exact origin checks including ABA, absent/stale rejection
before copy, explicit unsupported families/settings, field evolution, recovery
without decoding, node/byte/row/recovery refusal and cancellation. No geometry,
package writer, project archive, solver or production lifespan is invoked.

Factoring parity tests now cover old/new proof accounting at exact node/byte
boundaries, deterministic deadline injection, alias/cycle handling, and the same
separate recovery charge. Before wiring, add route tests with fake
geometry and package writers: mutate the original during threaded preparation,
assert all consumers see the same captured source, preserve the archived full
history/presentation and reference filtering, verify source guards precede all
lineage/job I/O, and prove unsupported compatibility follows its old data path
with unknown evidence. Existing sequence/complementarity/scientific gates remain
unchanged.

Measure bounded capture and actual lightweight concurrent HTTP requests before
calling the new route profile responsive. Package and attempt byte receipts,
settings/start coordination, restart-file identity and solver provenance remain
the next independently testable checkpoints described in
`physical_freshness_plan.md`.

The resumed non-VR backend runs are recorded in `validation_backend_resume.json`.
Route tests first reproduced the live alias leak in an actual writer thread,
missing stale/session guards and missing capture error handling: 16 failed,
10 passed. Two additional checks cover the default-disabled gate and actual
reference filtering while retaining full archival metadata.

The private route constant `OWNED_DNA_PREPARATION_ENABLED` selects the new path
only when enabled by the host. While false, no capture import, request-option
construction, additional state lock or classification occurs. Enabled requests
adapt the exact nine raw options through `capture_for_request` in the existing
host module. Only explicit unsupported classification chooses the compatibility
path. Header/identity errors remain 422; the known capture-limit code becomes
structured 413; unknown errors and cancellation propagate without fallback.
Unreviewed nested shapes retain their existing explicit unsupported contract.

The retained capture, rather than a second rollout-flag read, controls the final
source guard immediately before lineage. A flag change alone is not a new
revocation protocol; a simultaneous revision change still must be rejected.
After acceptance, later edits may leave a job tied to an older source revision.
That lineage fact does not by itself prove stale consumed physical inputs.
No complete physical receipt is emitted, and the unsupported compatibility path's
aliasing risk remains outside this qualification. See
`validation_oxdna_preparation_route.json` for actual focused and benchmark status.


## Private integration result

The 28 new route cases pass together with existing capture/headless/staleness
regressions: 182 passed, one scientific campaign deselected. The initial 16 red
cases became green without modifying numerical algorithms or physical evidence.
Reference geometry is filtered on the owned copy; retained history, annotations
and presentation remain independent. Both initial and final lifecycle guards
leave ordinary live state untouched.

The first HTTP diagnostic completed 31 alternating pairs per case with natural
GC, 310 correct attempts, 123 equal successful A/B responses and verified cleanup.
One 256-row capture refused at its unchanged time bound; its lock interval reached
68.69 ms, concurrent revision HTTP 71.48 ms, and POST-overlapping GC 55.83 ms.
The 31 intentionally oversized recovery inputs refused before side effects.
This supports retaining the false rollout gate, not increasing capture budgets
or silently retrying through compatibility after a capture failure. Actual
geometry/package I/O, peak memory and larger model families remain unqualified.
See `validation_oxdna_preparation_performance.json` for scope and raw evidence.
