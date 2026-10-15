# P4 lattice interchange: pinned input contract

Read-only audit, October 15, 2026. No importer, solver, test, benchmark or user
file was executed or changed for this audit. This supplements
[topology_import_plan.md](topology_import_plan.md). Assemblies remain deferred.

## Recommendation

Implement **small caDNAno v2 import first**, then scadnano with independent
expansion limits. Each should be one explicit source-bearing Import feature,
followed by ordinary editable NADOC features. The original strand graph is an
external input; nucleotide coordinates continue to derive from the unchanged
NADOC lattice/import algorithms. A successful proof is `reproduced_import`,
never proof that NADOC features constructed the original design.

Do not compile an imported topology into a fabricated history of user-authored
extrusions, routing choices or molecular operations. A Python-generated
caDNAno/scadnano file still has imported provenance. P6's native-only policy must
distinguish that from native construction, independent of who produced the file.

## Actual pipelines that the contract must preserve

| Entry point | Current complete pipeline, in execution order |
|---|---|
| `backend/api/crud.py::import_cadnano_design` | `json.loads(content)` → `core/cadnano.py::import_cadnano` → `_recenter_design` → `lattice.autodetect_all_overhangs` → `cluster_autodetect._autodetect_clusters` → `conversion_integrity.require_import_integrity` → `validate_design` → `state.load_design` → response/default-cluster bootstrap |
| `backend/api/crud.py::import_scadnano_design` | `json.loads(content)` → `core/scadnano.py::import_scadnano` → optional request name override → `autodetect_all_overhangs` → `_backfill_overhang_sequences` → `_recenter_design` → `_autodetect_clusters` → `require_import_integrity` → validation → load → response/default-cluster bootstrap |

The core importers already call strict source validation and final topology
integrity checks. The route performs another integrity check after normalization.
Retain both boundaries until equivalence and failure-atomicity are demonstrated;
parser-only output is not the current user-visible imported model.

`_recenter_design` in `crud.py:1933` translates axes and overhang pivots in XY and
translates previously activated cluster pivots; Z is unchanged. The 1e-6 no-op
threshold is part of current behavior. `_backfill_overhang_sequences` at 2003
extracts the existing per-domain sequence slices with its current skip handling.
These are pure helpers embedded in a composition root: move them verbatim to a
small shared core module and leave compatibility imports in `crud.py`. Do not
correct or simplify their formulas during this extraction.

Both routes currently replace the active document and clear undo/history through
`load_design`. This is different from aptamer's additive import. Prepare the new
root, input table, Import feature, recovery snapshots and validation privately,
then publish one new lineage at the existing load boundary. Do not temporarily
install an empty document, append to an existing document, or rewrite its root.
Keep failed parse/identity/recovery/validation work entirely before publication.

## Source semantics and loss policy

### caDNAno

`core/cadnano.py::import_cadnano` consumes v2 linked-list arrays. The source
validator in `core/conversion_integrity.py` requires unique helix numbers,
common scaffold-array widths, equal staple widths, reciprocal in-range directed
links, and nonconflicting loop/skip declarations. These checks are semantic
validation, not resource bounds.

Preserve all current choices:

- Empty placeholder vstrands are omitted; staple-only active vstrands remain.
- `_detect_lattice` uses array divisibility by 21/32 and falls back to honeycomb
  for ambiguous widths. Do not add a new user lattice override in v1.
- Existing Y reflection, normalized cell addresses, bp-axis trimming, stored
  `length_bp`, global phase offsets and locked helical constants remain exact.
- `_find_5primes` sorts source helix numbers; paths follow directed source links.
  Circular scaffold origins are chosen deterministically by source number/bp;
  all bases are retained with the existing linearization warning. Circular
  non-scaffold molecules reject the entire import.
- `extract_crossovers_from_strands` classifies an existing graph transition as a
  crossover or forced ligation using the existing neighbor tests. Same-helix
  discontinuities remain explicit directed ligations.
- Staple colors and name normalization, including removal of `.json`, remain
  unchanged. Do not add sequence synthesis or repair missing links implicitly.

### scadnano

`core/scadnano.py::import_scadnano` consumes helix/domain declarations. Preserve
grid normalization, direction parity, inclusive NADOC domain conversion,
source-order strand traversal, loop/skip accumulation, sequence slicing,
extension creation and loopout-to-junction-base assignment exactly.

`validate_scadnano_source` already rejects unsupported grid/groups/transforms,
unknown helix references, malformed domain bounds, unsupported chemical
modifications, illegal terminal/internal extensions, malformed loopouts,
conflicting/asymmetric modifications and circular non-scaffold molecules.
Some downstream importer branches still say they skip these cases; the earlier
validator prevents that permissive behavior. Do not weaken the validator to
reach those branches. Preserve the existing circular-scaffold nick warning and
the warning that unused helix declarations were omitted.

**Additional native v1 exclusion:** `scadnano.py:456` directly validates
`data['photoproduct_junctions']` as NADOC `PhotoproductJunction` objects. This can
carry formation state and design-coordinate payloads, rather than deriving CPD
geometry from the explicit CPD command. Reject a nonempty field at native
admission; retain the legacy route's existing compatibility behavior. CPD source
imports need a separate provenance/selection contract. Never reinterpret this
embedded output as a native CPD operation.

## Identity and ordering audit

| Family | Existing identity | Required handling |
|---|---|---|
| caDNAno helices | `h_XY_{normalized row}_{normalized col}` | Preserve during existing normalization/classification. A later source update cannot assume these identify the same source `vstrand.num`. |
| caDNAno strands | `scaf_{source num}_{5prime bp}` / `stap_...` | Deterministic for the same source graph; moving a nick changes the source identity. |
| scadnano helices | `h_sc_{idx}`, default idx is source list position | Explicit idx is a useful source key; missing idx inherits order dependence. |
| scadnano strands | `sc_strand_{source list index}` | Array reordering can silently refer to a different molecule. Do not preserve these across arbitrary replacement files without an explicit correspondence policy. |
| Cross-helix crossovers/ligations | `core/routing_identity.py` constructors | Existing `identity_scope(history_seed)` provides local deterministic IDs without changing math or global UUID functions. |
| Same-helix ligations | Direct model constructor in `conversion_integrity.add_same_helix_junctions` | Normalize IDs from the directed endpoint tuple after the unchanged builder, or add an optional identity constructor with unchanged legacy default. |
| scadnano loopout fallback ligations | Direct constructor at `scadnano.py:482` | Same directed-endpoint identity rule; retain extra-base sequence exactly. |
| scadnano terminal extensions | Random `StrandExtension.id` | Derive from the owning source strand and explicit 5′/3′ end; preserve sequence and every other field. |
| Overhangs/subdomains | IDs derived from strand/end; whole subdomain uses UUID5 | Preserve the current construction; map explicit references if owners are normalized later. Do not infer reference semantics from arbitrary strings. |
| Auto clusters | Random model defaults in several `cluster_autodetect.py` helpers, plus `cluster_components` fallback | Normalize identity only after the full existing pipeline, using cluster family plus exact typed membership; include whole-helix and ordered DomainRef membership and reject ambiguous duplicate keys. |
| Default umbrella | Response-side `with_default_cluster` can allocate UUID | Materialize deterministically in the command before recording; response serialization must make no authored change. |

Cluster membership needs a separate determinism check. `_cluster_by_lattice_neighbors`
walks sets to enumerate components before bridge/orphan tie choices; later sorting
the final clusters does not prove those choices were order-independent. Other
helpers choose maximum-overlap/crossover candidates with first-encountered ties.
Run fresh processes with different `PYTHONHASHSEED` values on bridge and equal-score
fixtures. If a real difference occurs, do not silently sort candidates and change
placement membership. First qualify a narrower unambiguous source class, or
record/validate the selected discrete membership inputs through an explicit
versioned contract. Coordinate any actual selection change under the scientific
authorization policy.

For the smallest safe v1, use an **explicit source-update identity policy**:
derive a final identity namespace from authored `history_seed` and the pinned
source digest, then remap only the known imported output identities/references.
Unchanged bytes reproduce IDs; name-only edits preserve IDs. Different source
bytes conservatively invalidate dependent references rather than assigning an
old source index to a different molecule. Even whitespace-only replacement is
conservatively a new source in this first version; disclose this limitation in
the update UI. More selective correspondence using source helix numbers and
unique directed strand topology belongs in a separately tested later version.
This conservative policy avoids implementing heuristic molecular matching while
still permitting explicit replacement and repair.

## Proposed seams and v1 command inputs

1. `backend/core/lattice_import_pipeline.py`: verbatim shared recenter/sequence
   helpers and the two exact ordered pipelines, returning `(design, warnings)`.
   Keep legacy DTO/response behavior and scadnano debug fields in thin route
   adapters. A normalization helper may replace identities and typed references;
   it must not accept coordinates or arbitrary complete model objects as recipe
   parameters.
2. `backend/api/part_lattice_import_commands.py`: strict `cadnano-import` and
   `scadnano-import` commands with `_proof_version=1`, `lattice_import_version=1`,
   `importer_version=1`, `source: InputSource`, `history_seed`, and explicit
   `identity_policy='source-content-v1'`. scadnano additionally records its exact
   optional name override. caDNAno keeps the embedded name semantics. Fixed v1
   pipeline policy covers centering, overhang detection and clustering; no
   sampled geometry or mutable settings are inputs.
3. Builders resolve only admitted `application/json` bytes with the declared
   caDNAno/scadnano format, decode strict UTF-8, preflight structure/work, call the
   unchanged pipeline, normalize typed identities and author the Import output
   only on a genuinely empty input design. They preserve recipe/source/history
   identity and report imported provenance. They must not become whole-design
   reset commands that drop unrelated resources.
4. Add kinds to `SnapshotOpKind`, proof dispatch/resources, `command_sources`,
   capability text and feature editing. Add these together; older receipts remain
   unverified. Parameters contain descriptors only. Portable sources, explicit
   source audit and project revision storage already support the immutable bytes.
5. At live admission, larger or excluded sources keep explicit legacy recovery
   behavior before native evaluation starts. Never fall back after a pinned
   command fails. New native import publication must retain warning/loss details
   and perform no ordinary background proof scan.

## Resource admission before allocation

The legacy caDNAno/scadnano routes call `json.loads` without their own content
limit. Add a bounded transport check before decode and distinguish that from
the much smaller native proof envelope. Existing relevant limits are 256 MiB
document transport, 50 MB per generic source, 30,000 capture nodes / 2 MB charged
bytes / 25 ms cooperative capture, 2 MB worker input, 16 MB candidate and 8 MB
cumulative recovery encoding. None is increased by this proposal.

Provisional qualification starts with **100 KB source bytes**, not a claim of
support for every source below that ceiling. Bound JSON nesting and integer
digits before/during decode; then count shape before invoking importers:

- caDNAno: vstrands, common width, total pointer slots, loop/skip declarations,
  active directed bases, declared inserted bases and resulting nucleotide work.
  A small JSON with an enormous loop integer is still excessive work. Validate
  exact integer coordinate/index types and bounded magnitude without changing
  the existing polarity/parity rules.
- scadnano: helices, strands, domain records, per-helix offset span, total domain
  span, insertion count totals, loopout bases, terminal-extension bases and
  source sequence lengths. Reject excess before `"N" * n`, range expansion,
  occupancy validation or geometry generation. The modification validator also
  compares domains against declared modifications, so bound both counts and
  their product, not only nucleotide inventory.
- Both: reject non-finite numbers, unsupported structure, duplicate identity keys
  and ambiguous source-address maps. Apply the existing semantic validator after
  shape admission. Source digests and retained parsed topology both count toward
  capture; deduplicating source bytes does not remove model-node costs.

Choose concrete topology caps from the serial measurements, retaining explicit
independent refusal reasons. A source/shape preflight does not replace ordinary
capture admission and must not advertise an oversized current design as proven.

## Measurement and completion gates

1. **Extraction oracle:** compare every authored field against the complete
   current route pipeline after identity normalization, including scaffold and
   geometry clusters, overhang domains/pivots/labels, sequences, inserted bases,
   warnings, metadata and debug recenter samples. Keep topology/phase geometry
   oracles unchanged. Relevant existing suites: `test_cadnano.py`,
   `test_cadnano_roundtrip.py`, `test_scadnano.py`, `test_conversion_integrity.py`.
   Select individual meaningful tests; several caDNAno tests emit figures or
   import larger examples and must not become accidental baseline smoke work.
2. **Determinism:** repeated pure construction, new document IDs, fresh spawned
   workers and distinct process hash seeds. Include same-helix jumps, true/forced
   junctions, circular scaffold origin, orphan/bridge clustering, loopouts and
   terminal extensions. Compare complete output, not only counts.
3. **Cold proof and editing:** poison recovery/output bodies; remove local source
   files; persist/reload; edit name and explicitly replace source. Reordered
   source arrays must not silently retarget a downstream feature. Verify missing
   source, hash mismatch, missing producer, repair diagnostics, explicit cascade
   and undo. Invalid versions and malformed replacement sources are atomic.
4. **Admission measurements:** use the 7,780-byte Honeycomb_6hb_test1.json and
   87,248-byte 6hb_cadnano_native_test1.json first, plus tiny synthetic worst-case
   loops/domain fragmentation. Later measure the 336,838-byte 18hb fixture and
   183,136-byte Voltron_Core_Arm.sc independently; neither is initially claimed.
   Record raw bytes, decoded shape/work counts, authored nodes, capture median/max
   and refusals, actual pickle size, fresh-worker time/status, cumulative
   recovery size, candidate size and atomic publication cost. No rendering or
   physical simulation is needed for admission qualification.
5. **Enablement:** publish measured limits and explicit unsupported cases before
   enabling live native imports. Complete small caDNAno before broad scadnano;
   retain larger-source capture architecture as a separate deliverable.

## Numerical pins, scientific boundary and external precedent

No phase constant, axis equation, crossover classification, strand traversal,
sequence slicing, cluster-selection algorithm or molecular topology change is
authorized by this contract work. Identity normalization and helper extraction
must have exact existing-output oracles. A discovered geometry discrepancy is
a separate scientific decision, not an opportunity to regenerate goldens.

Adding new SnapshotOpKind values changes `models.py`, which existing CPD and
duplex relaxation manifests hash. `lattice.py` is also included, and duplex
relaxation includes `cluster_autodetect.py` and `feature_identity.py`. Prefer
adapter-only normalization over changes to these helpers where possible. Before
necessary manifest-covered edits, checkpoint, retain old authored engine pins,
report their incompatibility explicitly, and rerun the focused numerical proof
regressions. Do not silently repin old saved recipes.

Onshape exposes an editable Import feature and explicit source update; downstream
features are reapplied where possible and visibly fail when replacement invalidates
their references. Imported data does not acquire its original parametric history.
This supports an explicit external-source feature plus editable downstream native
operations, rather than inventing the original construction sequence.
[Onshape: Working with Imported CAD](https://cad.onshape.com/help/Content/Document/working_with_imported_cad.htm)

The scadnano project's own Python library explicitly exists to generate editable
scadnano files from scripts. NADOC therefore cannot treat a scadnano extension or
successful parser result as evidence that an LLM used NADOC native commands.
[Official scadnano Python documentation](https://scadnano-python-package.readthedocs.io/en/latest/)
