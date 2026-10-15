# Bounded standard-part document transport

October 15, 2026. This boundary is independent of native proof and worker input
admission. No proof, source-table, solver or capture budget was increased.

## Evidence and limits

A read-only file metadata inventory found 233 workspace/fixture `.nadoc` files.
The largest were Benchy (89,999,675 bytes), VoltronCoreArm (85,288,338) and
VoltronCoreArmV2 (83,744,004). Of 983 project snapshots, the largest observed
gzip footer ISIZE was 37,344,300 bytes; this footer observation was not trusted
as a validated decompressed size. Of 162 `job.json` files, the largest was
170,303 bytes. No designs were parsed, rewritten, moved or removed for inventory.

The decoded document ceiling is 256 MiB, with an independent 512 MiB compressed
snapshot ceiling matching existing peer transfer admission. Package manifest,
branch metadata and job metadata use 8 MiB. ZIP directory reads are capped at
16 MiB before the standard library allocates them; a separate 100,000-member
guard applies after parsing. Simulation members remain streamed and are not
subject to the document ceiling. These are transport byte bounds, not hard
process heap limits; JSON/model construction can require additional memory.

`part_document_io.py` bounds filesystem/member reads, existing JSON text, gzip
output and incremental base64 decoding before model validation. MIME whitespace
in legacy snapshot base64 remains supported. CRC failures, truncation and
multi-member gzip behavior remain checked by `GzipFile`. Oversized input raises
`document_transport_limit` with the configured byte limit before publication.
ZIP/ZIP64 offsets and CRC remain owned by `zipfile`; a file wrapper bounds its
construction-time reads instead of introducing a competing ZIP parser.

The package, revision/loadout readers, server file load/import, library-open
seam, authenticated snapshot request and peer pull use this boundary. Old
embedded revision envelopes remain accepted within the document ceiling.
Package export writes the already admitted bytes rather than rereading a file
that could have changed after validation. Existing recovery encoders reject an
oversized completed JSON representation before compression/publication; this
does not bound the encoder's initial model serialization allocation.

## Inactive branch evidence

`part_source_audit.py` uses the same admitted `command_sources` contracts as
portable-source closure. Current-source inspection never decodes feature
recovery or inactive loadouts. Missing/corrupt evidence remains `unverified`
with source hash, feature ID and, when applicable, loadout ID. It never triggers
cascade deletion or substitutes bytes from another branch or a process cache.
Repeated references share one byte verification within each explicit audit.

`GET /api/design/loadouts/source-audit` explicitly audits current and inactive
branches. Inactive inspection is capped at 256 branches, 512 MiB cumulative
decoded documents, and 20,000 history entries per branch. A failed decompression
charges its allowance conservatively. Uninspected/nested branches are reported
as incomplete, never silently omitted. All saved bytes remain intact.

Load and branch-activation responses add `source_warnings` for the activated
state. Ordinary edit responses and native proof do not run these audits.
Package manifests include additive `authoring_loadouts` diagnostics; inactive
broken drafts remain portable and package import returns their warnings. The
existing strict active-source closure remains unchanged. P5 must render these
warnings and provide explicit source restoration/feature repair controls; this
increment adds no draft schema or automatic repair.

## Regression gates and remaining boundary

Focused tests cover bounded reads before parse, gzip bombs/CRC/truncation and
concatenated streams, incremental legacy base64, ZIP64 and large streamed member
compatibility, revision and package failure before publication, chunked peer
request/pull cleanup, library-open identity preservation, inactive missing-source
package round-trip, branch activation warnings, cumulative audit budgets, and
native proof independence from poisoned inactive recovery. Root serializes
execution; no test result is claimed in this document.

This is not a general request-body middleware or simulation-storage quota.
Framework JSON parsing may allocate a browser's already received raw design
request before the application text check. Package upload and simulation
extraction retain their existing streaming disk behavior; archive upload/disk
quotas and Archive-first temporary storage are separate outstanding work.

Primary references: [Python gzip](https://docs.python.org/3.12/library/gzip.html),
[Python zipfile resource limits](https://docs.python.org/3.12/library/zipfile.html#decompression-pitfalls),
and [PKWARE ZIP specification, 4.3.14–4.3.16](https://pkware.cachefly.net/webdocs/casestudies/APPNOTE.TXT).
