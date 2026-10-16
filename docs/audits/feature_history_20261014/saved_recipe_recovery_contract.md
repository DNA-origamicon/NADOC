# FH-19: saved recipe recovery contract

October 16, 2026. Private admission/evaluation now connects to an isolated HTTP
worker and File → Recover recipe from file… controls. The implementation evidence
and milestone status are recorded in the delivery ledger. Normal loading is
unchanged; actual desktop and latency qualification remain in FH-27.

## Boundary and ownership

Recovery is an explicit reconstruction from saved inputs, not a claim that the
old materialized geometry was valid or equivalent. Initial support is a native
empty v1 root with a complete, typed history and recognized v1 grouping repairs.
Imported roots, inferred roots, damaged JSON and unsupported definitions refuse.
Every row must be retained or rejected; never silently drop a legacy row.

The browser retains the original immutable File. Inspection and recovery
resubmit those exact bytes; the server computes their SHA-256 independently.
Recovery requires that digest and explicit exact-definition upgrade actions.
Changing even whitespace invalidates the receipt. No automatic upgrades occur.
The parser retains the original bytes unchanged while the private call owns them.
It does not open paths, reconcile workspace identities, write files or install a
document. The result is a download with a new document ID, not Apply
against the occupied document. No second retained recovery catalog is needed.

Ordinary workspace-open reconciliation may rewrite file identity metadata, and
the current frontend workspace-open flow clears its view before successful load.
Neither flow is a recovery host. Existing live-document job permits also cannot
authorize an arbitrary saved file. The private evaluator reuses the repair
planner/rebuilder, with internally generated expectations for its new private
copy; these expectations grant no session or file publication authority.
The download uses server-encoded JSON text and a digest/size
receipt. Browser reserialization of a parsed candidate can change large integer
inputs and is not an acceptable file-producing boundary.

## Inputs, bounds and excluded data

Before decoding: at most 1,500,000 original UTF-8 bytes, depth at most 64.
After decoding: at most 30,000 nodes and 8,000,000 conservatively charged graph
bytes. Duplicate object keys, nonfinite numbers and unsupported versions refuse.
These are separate admission limits, not a measured process-heap guarantee.
Existing 2,000,000-byte/30,000-node recipe admission, 2,000-row replay admission,
64-action/256,000-byte repair request, cumulative recovery encoding and
16,000,000-byte result ceilings still apply. Larger ordinary documents remain
loadable under their existing rules; this first recovery path refuses them.
No ordinary editing, slider, load or autosave path invokes these checks.

Admitted authority consists only of the explicit root, stable document/feature
identities, every typed command definition, and pinned source bytes. Explicit
snapshot/diff payload fields are stripped before typed row admission and never
decoded. Overlay `cluster_snapshot` and `op_snapshot` are command inputs and
must be retained/validated. Mandatory IDs cannot be synthesized by model defaults.
Unknown top-level/definition fields and top-level minor/checkpoint rows refuse.

Materialized authoring fields are regenerated. Saved presentation/physical state,
loadouts, jobs, repair drafts and materialized metadata are excluded from the new
copy. The source root/commands determine regenerated metadata, including name.
Inspection and the final receipt enumerate excluded top-level fields; the UI must
explain these exclusions before offering recovery. Original bytes retain all of
that data. This is deliberate recipe reconstruction, not silent metadata salvage
or a migration of the original. Candidate-specific display retention would need
a separate reviewed contract; it is not implicit in this milestone.

## Candidate acceptance

Use the existing repair engine and ordinary native executor. Validate pinned
sources; return missing-source diagnostics without filesystem/network fallback.
Rebuild all rows from the explicit root, preserving feature and generated-object
identities while assigning a fresh document ID. Require structural closure,
ordinary typed serialization/reload, unchanged authoring across that roundtrip,
and independent input-based proof of the recovered result. Return the validator's
verdict honestly; a failed validation cannot produce a downloadable ready copy.
The original geometry is never used as the comparison oracle. Cancellation,
conflicts, unsupported contracts and failures return no candidate.

## HTTP and process ownership

`POST /api/part-recipe/recovery` accepts an uncompressed octet-stream frame:
four bytes of big-endian metadata length, at most 256,000 UTF-8 JSON metadata
bytes, then 1–1,500,000 exact original file bytes. The closed metadata schema is
`{version:1, operation:"inspect"}` or `{version:1, operation:"recover", request:…}`.
Duplicate/nonfinite metadata and ambiguous HTTP framing refuse. No multipart
spool, base64 copy, filesystem path or client-selected policy is admitted.

The existing single native-worker slot is acquired before reading the body and
retained through child cleanup and the final response send. There is no queue or
retained recovery-job registry. Upload has a 15-second limit within one 180-second
work/send deadline; the client aborts after 190 seconds. Disconnect or repeated
task cancellation signals the supervisor and drains it before admission can be
released. OS resource cleanup and shared threadpool scheduling are cooperative;
the deadline is not a hard OS termination guarantee. Child death alone does not
prove shared-memory cleanup. Admission stays occupied until cleanup succeeds.

Original-file parsing, native reconstruction, exact document encoding, response
decoding and checksum checks run off the event loop. The spawned child uses the
existing numerical thread policy. The server-created private pickle contains
raw bytes and validated metadata, never user-provided pickle. Its input mapping
closes before native evaluation; total private input remains capped at 2 MB.
The complete escaped JSON response, not just the downloadable document, is capped
at 16 MB. Ready responses contain `recovered_file: {json_text, sha256, size_bytes}`
instead of a parsed candidate. The parent verifies the original-file receipt and
artifact checksum, then serves the exact child envelope. `Content-Encoding:
identity` prevents synchronous middleware compression on the event loop.

The document header is used solely to respect the existing host construction
policy. Compatibility and its generation are checked before work and before
delivery; strict dispatch remains closed. No active session, revision, source
Design or state lock is acquired by recovery.

## User review and remaining qualification

The File-menu dialog preserves one immutable File, hashes its bounded bytes and
checks inspection/recovery receipts against it. No repair is selected by default.
The user selects up to 64 offered grouping upgrades, acknowledges the displayed
exclusions, evaluates, then explicitly downloads a separate `-recovered.nadoc`
copy. File changes, cancel and close abort work and invalidate late replies.
The download hashes and writes exact server text; it never parses/reserializes
the document. It neither opens the copy nor changes the occupied part, undo,
autosave or workspace state. The original file retains excluded data.

No general corrupt-file salvage, workspace writing, source restoration UI or
assembly support is added here. Automated lifecycle and HTTP/download checks
are implementation evidence, not desktop or latency acceptance. Actual browser
interaction, download/reopen and larger-design responsiveness remain in FH-27
and MV-49. Archive was unavailable for safe browser/runtime artifacts during
this checkpoint; no app exercise or smoke pass is claimed.

Workflow precedents and primary Onshape/SOLIDWORKS links are recorded in the
[delivery map](remaining_standard_part_checkpoints.md). The exact limits,
definition carrier and stateless download boundary above are NADOC decisions,
not claims about those products' implementation.
