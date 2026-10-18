# P5 repair-source staging

This slice adds explicit source inspection and raw-byte preparation/publication
helpers, registered through thin state/feature-route adapters. It does
not modify source-owning commands, molecular algorithms, numerical pins, proof
capture limits or the ordinary operation envelope.

## Operations and ownership

- `stage_proposed` requires an exact **named input** in the saved draft's patched
  native command. The shared repair planner checks authored old values,
  protected identities and strict command schema. A digest used anywhere in the
  published recipe is refused with `restore_published_required`.
- `restore_published` requires an exact named published binding. It replaces
  missing/corrupt evidence only when the caller supplies the exact previous
  encoded-byte receipt. Changed file content requires a different SHA descriptor
  and an explicit input edit; it cannot replace bytes under the old digest.
- Inspection returns `expected_blob: {state: missing}` or
  `{state: present, encoded_size, encoded_sha256}`. The latter hashes the exact
  encoded string using UTF-8/surrogatepass, including corrupt text. Its size is
  encoded characters, matching the existing source-table allowance. Inspection
  does not decode, restore or certify a source.
- Both mutations require document context plus part ID, session revision, draft
  ID and draft generation. The internal transaction additionally compares exact
  captured session and Design identities, preventing close/reopen ABA.
- One successful mutation replaces only `input_sources`, increments revision
  once, and creates no geometry undo snapshot or feature row. It retains the
  exact current proposal/base/generation. Restoring published evidence changes
  the durable base fingerprint; the response requests explicit rebase, and the
  evaluator must still regenerate. No ready/verified state is persisted.
- Protected simulation loadouts permit inspection and refuse mutation. No
  exception allows repair metadata or source restoration to edit such branches.

Unknown/legacy commands, undeclared fields, generic blobs, saved output geometry
and arbitrary recursive source discovery are not upload contracts. Storing bytes
does not execute their importer or grant native-construction provenance. Actual
parsing and replay remain the existing native command's responsibility.
Current source-owning kinds are snapshot definitions. No persisted minor routing
kind presently declares a source; a routing child carrying arbitrary source JSON
is refused with its group/child identity rather than gaining an import contract.

## Bounds and performance

The async transport accepts original `application/octet-stream` bytes plus one
ASCII JSON `X-NADOC-Repair-Source` header of at most 8,192 bytes. The header carries
the explicit selection and prior-byte receipt, never the file bytes. Metadata,
named command binding and prior-byte expectation are checked before consuming
the body. The body must exactly match the declared size and SHA.

The global 350,000-byte upload ceiling **does not expand any command family**:

| Named source | Existing byte limit / format |
| --- | --- |
| protein import `source` | 250,000 / PDB |
| aptamer import `source` | 150,000 / PDB |
| caDNAno import `source` | 100,000 / caDNAno-v2 JSON |
| quantum-dot create `source` | 65,536 / selected catalog JSON |
| coating `pdb_source` | 350,000 ceiling; v1 still requires exact 329,994-byte 1STP SHA |
| coating `coverage_source` | 4,096 / JSON |

Limits are imported from command owners; formats and the fixed coating identity
are checked without invoking scientific code. The existing table maximum of
256 records and 66,666,668 cumulative encoded characters applies before and
after insertion. No limit for an ordinary proof or source descriptor is raised.

One nonqueued upload is admitted per server. A second receives an explicit busy
response; the body read has a 15-second deadline. Error, timeout, disconnection
and cancellation release admission. Cancellation waits for an already started
private metadata worker to finish before releasing its slot. Publication checks
local cancellation after obtaining the state lock; cancellation after an atomic
commit begins cannot undo that commit. No temporary files or network lookups are
used. ASGI server transport buffers precede these application-owned bounds.

Under the state lock, capture clones only the existing bounded definition/draft
envelope (25 ms cooperative / 2 MB / 30,000 nodes / 2,000 entries) and retains
immutable source-record references after count/length checks. It does not copy,
hash or decode source strings and does not visit geometry/recovery/presentation.
Old-byte receipt hashing and uploaded SHA/base64 preparation run outside the
lock. A private checked token avoids hashing the same captured old blob again
after upload. Final publication is a shallow field replacement using the shared
metadata CAS/rollback primitive. The source table's dictionary is privately
owned; immutable embedded records can be shared.

## Remaining integration and validation

The registered state facade / feature routes call:

1. `part_repair_source_host.inspect_source(selection)` for explicit receipt
   inspection; the returned object is the upload metadata.
2. `part_repair_source_transport.upload_source(request)` for bounded raw upload.
   That host owns capture, preparation, final compare-and-swap and response
   serialization before publication.

Focused tests cover named selection and undeclared routing-child refusal, strict families and old-byte
expectations, staging versus published restoration, unchanged proposal/base,
required rebase, exact revision/session races, protected branches, no geometry
work, cancellation/error rollback and transport/admission cleanup. Root runs all
tests serially, including existing metadata transaction and metadata API suites.
Malformed published descriptors remain a structured refusal: this version does
not guess source ownership from arbitrary JSON. Ordinary save/package closure
continues to verify retained source bytes; proposals do not bypass that check.

## CAD precedent

[Onshape's imported-CAD update workflow](https://cad.onshape.com/help/Content/Document/working_with_imported_cad.htm)
uses an explicit Update action to replace original import data, then reapplies
downstream features and reports rebuild failures. Imported geometry does not
recover its original parametric feature history. NADOC similarly separates
source restoration from editing/re-evaluating its native definitions.

[FeatureScript external-data imports](https://cad.onshape.com/FsDoc/imports.html)
require external data to be uploaded into document tabs. Workspace references
may update automatically; version references remain pinned until explicitly
updated. NADOC's content-addressed descriptors choose the latter reproducibility
property, with changed bytes represented by an explicit descriptor edit.
