# Standard-part assets, imports and conjugates: P4 source audit

Audit and implementation ledger, October 15, 2026. P4a uncoated gold and the
initial P4b pinned-protein/duplex slices are implemented; this document also
contains the remaining work. Assemblies, including assembly protein targets,
remain deferred. Existing scientific builders and placement formulas remain
the oracle.

## P4b implemented boundaries

- `Design.input_sources` is a bounded, deduplicated portable source table. Frozen
  source descriptors identify SHA-256, length, format and media type. Input bytes
  are separate from generated authoring output and are charged by existing
  verification capture limits. Scoped execution retains these immutable bytes.
- `POST /api/design/features/import/protein` takes source/data, parser choices
  and a required revision. It verifies bytes before recording and atomically
  adds the source and imported asset. The initial contract permits 250 KB,
  1000 atom records and 4000 parsed bonds. Existing free/library import remains
  a legacy workflow until it can emit separate import and placement commands.
- Versioned free/part-overhang placement, patch and delete share pure builders
  with eligible live routes. Defaults are selected once under the recording
  lock. Explicit identities and atom serials survive replay; missing targets
  cannot become native no-ops. Conjugated/owned placements remain outside this
  slice. Native builders create stable default clusters before publication.
- An imported command makes whole-part provenance `reproduced_import`, including
  when the root was empty. Its supported native parameter rows remain editable.
  Missing or corrupt source evidence is `unverified` with a typed repair target;
  it cannot justify geometry cascade deletion.
- Revision snapshots, peer transfer and all package modes retain embedded inputs.
  Packages declare active authoring source descriptors. Project-store blobs are
  derived caches, restored only from independently verified inline bytes. Cache
  write failure does not block a portable save; explicit cache reads fail closed.
- Native files bypass legacy inference during deserialization/load/response
  formatting. Rootless files retain compatibility migrations. Authored absence
  of crossovers, duplexes or clusters survives save/reload. Two duplicate load
  migration chains were consolidated.
- Duplex create/connect/patch/delete and explicit sync use exact endpoints,
  selected binding IDs, stable outputs and creation times. Reversible saved
  topology has a typed codec that separates current owners from historical
  definitions; ambiguous historical co-ownership remains unsupported.

Remaining source work includes large-input transport/capture measurements,
validation of inactive loadout closure, source restoration/repair UI, full
conjugation/NP decoration and placement coverage, topology-format imports, typed
rigid copy and explicit physical-source provenance. Recovery blobs deliberately
remain outside input proof; poisoned recovery bytes must not invalidate an
otherwise reproducible native recipe. No source garbage collection is enabled.
See `implementation.md` and `validation_inputs_duplex_p4.json` for executed checks.
The architectural sections below preserve the fuller P4 plan.

## Architectural decisions

Use immutable source bytes plus versioned parser/options as an import feature's
inputs. Keep ordinary native placement, conjugation, binding and editing as
separate commands. A protein's parsed atom array, a saved candidate Design, or a
post-fit pose must not stand in for the source and choices that produced it.

The smallest external source descriptor is:

```json
{"version":1,"sha256":"<64 lowercase hex>","size_bytes":1234,
 "format":"pdb","media_type":"chemical/x-pdb"}
```

A first protein import command can carry `asset_id`, that `source` descriptor,
`importer_version: 1`, and explicit `name`, `source_filename`, and `exclude_dna`
options. Source descriptions, URLs and RCSB IDs are provenance only. Fetch once
at admission, pin the exact received bytes, and never fetch during replay.
Selecting a newer source is an ordinary explicit source-parameter edit.

Resource dependencies need two identities: the source content hash and the
authored `protein_asset` ID. Changing bytes can preserve that asset ID while
downstream atom selections are revalidated. Record conjugation atoms by serial
plus the applicable asset dependency; do not silently choose a different site
when an edited source no longer contains the selected atom.

Allocate public IDs and creation timestamps once before execution; derive child
IDs with the existing identity scope. Record stochastic seeds. Parser, command
and algorithm versions describe executable compatibility, not copied scientific
constants. Keep labels and source residue/chain identifiers out of ID rewriting.

Current proof determines `native_editable` only from `root.kind` in
`backend/core/part_history_proof.py`. An empty root followed by imported geometry
must not be reported as wholly native. Extend command provenance to report
imported resources and reproduced-import status; preserve the ability to edit
supported native rows independently of the whole-part provenance label.

## Immutable storage and portability

`backend/core/project_revisions.py` already provides validated project/hash paths,
atomic fsync/replace writers (lines 65–97), immutable snapshots/revision objects,
hash checking, and branch compare-and-swap. Add a narrow input-blob API beside
these primitives, with project-local `inputs/<sha256>.blob`, bounded ingestion,
verified reads and a small source manifest. Do not use `ingest_snapshot` for
assets: it specifically decompresses and validates a Design. Do not use
`ProjectArtifactCatalog`, which catalogs simulation outputs and mutable locations.

Stage and verify blobs without advancing a branch. Publish a feature candidate
only after its complete source closure is present and after normal revision
checks. Reusing an existing digest must verify the stored object when it enters
an evaluation. Missing, truncated, changed or unsupported source bytes produce
structured diagnostics with the feature and source hash. Relinking may restore
the same hash; selecting different bytes requires an explicit edit. Never
substitute a process cache or a similarly named file.

The pure executor needs an explicit read-only resource resolver. Bind it into
the existing evaluation, verification and prefix-rebuild executors; do not make
builders consult the current document session, a global protein library, a
client filesystem path, or the network. The worker receives only admitted
descriptors and immutable resources, verifies bytes, then invokes the existing
parser. Cache parsed resources by source hash, parser version and every parsing
option, with deterministic asset identity applied separately.

`native_part_package.py` currently packages a `.nadoc` and optional simulations.
It does not package revision-store objects or external authoring sources. Extend
its manifest with the complete required source set; **thin, selected and full
packages must all include authoring inputs**. Those modes may continue to differ
only in simulation payloads. Check lengths/hashes while streaming to staging,
reject duplicate/conflicting members and unsafe paths, install immutable inputs,
then publish the part. A failed part install may leave unreferenced immutable
blobs but must not publish a part missing its sources.

Plain `.nadoc` is explicitly a portable compatibility document today. Do not
silently change that contract to depend on a hidden project directory. The
smallest compatible first increment embeds a deduplicated source table at the
document/file boundary and hydrates the immutable store on load; recipes retain
only content descriptors. Package export can store those bytes as members. A
later external-only save mode needs an explicit product decision and UI, not an
implicit consequence of adding hash references. Every new Design field needs an
explicit `FIELD_ROLES` classification; storage envelopes are not geometry proof.

Project peer sync currently inventories only refs, objects and snapshots
(`project_revisions.py:420`, `routes_project_collaboration.py:661`). Extend source
inventory/transfer and validate a revision's required source closure before
advancing its ref. Reuse peer authentication and immutable transfer semantics.
Old revisions with inline data remain valid. Do not migrate or rewrite their
hash identities. Any garbage collection must retain blobs referenced by all
retained revisions, loadouts and undo/redo states; defer collection initially.

## Existing source gaps and pure command families

| Family | Existing authority and gap | Required native/input contract |
|---|---|---|
| Protein source import | `core/protein.py:150` parses PDB; `routes_protein.py:64` stores a process-global library; `routes_design_interchange.py:351` logs only asset ID/name. | Pin raw PDB, parser/options and explicit asset ID. Import asset separately from placement. `_resolve_protein_asset` must resolve the captured Design resource for replay, never prefer the process library. |
| Free/overhang protein attachment | `routes_protein.py:414` logs asset/overhang only. | `protein-attach` records attachment ID, asset, discriminated free/part-overhang target, attach end, selected atom, pose and handle options. Validate selected source and target before mutation. |
| Protein conjugation | `routes_protein.py:490` already validates a full private candidate and uses native binder/terminal geometry. Its log omits selected conjugation atom and group identity. | Extract a pure `protein-conjugate` builder with asset, overhang, optional existing free attachment, selected serial, azide end, explicit attachment/binder/group identity scope. Reuse native chemistry, accessibility, sequence and pose calculations. Preserve idempotence and stale-request behavior at publication. |
| Protein edit/delete | `routes_protein.py:725` computes constrained moves but logs only attachment ID; delete searches prior history to infer binder ownership. | Patch logs actual supplied pose/gizmo/atom/handle/visibility fields, recomputed against the regenerated prefix. Native deletion uses explicit authored binder ownership; retain history-based inference only for legacy repair. Reuse `constrained_conjugate_move`, `gizmo_move_to_pose` and group cleanup. |
| Gold particle CRUD | `core/nanoparticle.py:18` already accepts explicit particle ID; replace/delete maintain owned geometry. | Uncoated gold create/patch/delete are the smallest source-free P4 commands. Preserve diameter/pose/gizmo semantics and owned-resource closure; reject missing targets. Coating becomes a separate native step when compiled. |
| Quantum dots | `core/quantum_dots.py:46` reads mutable bundled catalog data and allocates a random ID. | Pin the catalog entry/source bytes plus catalog/parser version, selected catalog ID, explicit particle ID and diameter. Preserve vendor eligibility/range checks. Catalog metadata is not a native geometry source exemption. |
| Streptavidin coating | `core/streptavidin.py:22,55` reads bundled 1STP assembly and optional coverage JSON. PDB metadata includes a hash, but replay still reads the live file. | Pin PDB and selected coverage source; record mode, footprint, spacer, coverage reference/count override, and seed. Reuse exact tetramer preparation and placement. Coating removal is explicit. Do not record generated protein instances/poses as input. |
| Thiol DNA | `core/nanoparticle.py:211` already has seeded Fibonacci placement, but child/group/conjugation IDs are random. | Conjugate/create-replace and delete commands record particle, sequence, chemistry/end, count/coverage/spacer/seed choices and identity scope. Reuse `build_thiol_conjugation`, ownership and bound-state guards. |
| NP surface-strand bind | `routes_nanoparticles.py:917` uses `make_binder_for_overhang` while preserving the owned strand identity. | Particle + owned strand + target overhang. Validate exact ownership, polarity, sequence, free state and auxiliary endpoints; preserve native carrier removal and reference updates. |
| NP connection versions | `routes_nanoparticles.py:554,785,828` applies native duplex relocation, but create/patch logs omit requested values. | Create records version ID/time, particle, strand, overhang, variant, name and applied flag. Patch records name/applied changes; delete records target. Deterministically create duplex/child cluster IDs. Preserve conflict unapply and reversible topology. |
| NP attach and relaxation | `api/nanoparticle_attachment.py` fits privately; route logs derived diagnostics. Collective relax uses `solve_nanoparticle_anchors`. | Record selected handle/target, fixed-center choice and explicit version identity. Native fit recomputes poses; diagnostics are output. Preserve existing search, acceptance and obstacle formulas. Collective relax records exact selected versions/options; run through bounded long evaluation if required. |
| Biotin DNA | `core/gold_strep_dna.py:110` uses coated protein and a bundled tether template; random helix/strand IDs. Add/remove share one log kind with implicit shape. | Separate explicit create/remove action, particle/coating/template dependencies, sequence, occupancy/pocket/linker inputs and identity scope. Reuse exact pocket geometry/clearance search and extension updates. Never broaden simulation-readiness claims. |
| Part duplex lifecycle | `routes_duplex.py` directly changes state without feature rows. `core/duplex.py` supplies register, placement, relocation and restoration. | Native create/connect, patch, delete and explicit relaxation commands with endpoints/register/driver/bound/mode/identity/time. Reuse binding kernels instead of a competing topology implementation. Sync-from-bindings remains explicit migration or an admitted deterministic operation. |
| Rigid element copy | `core/element_copy.py:18` accepts a whole source Design, allocates random IDs and rewrites every matching string. | Native same-part selection + copy options + identity seed, or an explicit pinned external import followed by selection/copy. Require closed owned references and typed remapping. Preserve names/text and existing placement formula. |
| PDB/aptamer and other topology imports | `routes_design_interchange.py:34,481` installs imported designs or logs template ID/name without actual bytes. PDB/aptamer builders allocate random identities. | Pin raw input, format/parser/options and identity scope; distinguish replacement-root/import-add semantics. Bundled templates must be pinned too. Native DNA import remains visibly imported, even when its parser is reproducible. caDNAno/scadnano use the same source contract. |

Typed scope schemas already describe retained part-local asset references in
`core/part_scope_references.py`; that is not proof coverage for asset creation.
New contracts must include exact consumed/produced resources, ownership and
incoming references. Atom serials, protein chains and source metadata are not
global object IDs. `element_copy.py`'s generic string walker is a P4 refactor
target, using the existing typed mapper rather than creating another registry.

Two behavior gaps need explicit treatment before enabling their contracts:

- `routes_duplex.connect_duplex` catches relocation exceptions and can retain a
  duplex without completing binding. Strict execution must fail atomically or
  expose creation and binding as separate commands; it must not certify partial
  success as a successful bind. Preserve legacy compatibility intentionally.
- Duplex relocation stores prior topology for reversible unapply. That state
  can be freshly derived output of a native command, never trusted input copied
  from a recovery snapshot. Its nested reference schema and deterministic IDs
  must be covered before scoped replay can admit it.

## Performance prerequisites

Current proof capture is bounded to 30,000 nodes, 2 MB and 25 ms; worker input and
result buffers are 2 MB (`part_verification_capture.py`,
`part_verification_worker.py`). PDB import accepts 50 MB and up to 250,000 protein
atoms. A normal large asset cannot simply pass through today's eager deep-copy
capture. Increasing all limits would undermine the responsiveness requirement.

Introduce bounded immutable-resource admission and worker transport as its own
checkpoint. Keep source bytes outside repeated command rows and avoid copying
large atom arrays under the document lock. Full authoring comparison must remain
complete: `protein_asset_fingerprint` hashes selected atom structure fields, but
omits bonds, serials, default conjugation site and metadata, so it is not a
replacement for the existing whole-field comparison. A future immutable parsed
asset digest must cover every authored field and enforce immutability first.

Measured small-asset support may be admitted first with explicit limits. Larger
supported imports require a bounded evaluation path and cancellation; they must
remain honestly unverified if outside the proven budget. Recovery snapshot
generation/retention also needs measurement because each native row currently
captures the full authoring state. Do not hide cost by dropping assets from
proof, raising global deadlines, or treating simulation caches as authority.

## Suggested checkpoints and regression map

1. **P4a: source-free particle primitives.** Pure uncoated gold CRUD and complete
   reference diagnostics. Tests against existing native output, cold proof,
   diameter/pose edit, delete/cascade, undo and unchanged unrelated DNA.
2. **P4b: pinned input foundation.** Descriptor, bounded store/resolver, embedded
   standalone source envelope, package/peer closure, provenance labels and small
   protein asset import/free placement. Test offline replay, changed source
   library/file/network, wrong digest/size/parser, missing source, portable
   round-trip and atomic publication. Include asset-scaling measurements before
   admitting larger imports.
3. **P4c: protein placement/conjugation and thiol DNA.** Extract pure builders,
   stable IDs/timestamps and exact user-input recording. Test selected-atom and
   overhang deletion/repair, same asset used twice, cold parameter edits, owner
   cleanup and sequence/geometry equality.
4. **P4d: duplex/NP connection lifecycle.** Explicit versions, apply/unapply,
   attach/relax and bounded numerical jobs. Test child-ID stability, conflict
   unapply, restored topology, polarity, multi-anchor constraints, fixed centers,
   stale revisions, cancellation and failure atomicity.
5. **P4e: bundled assets and remaining imports/copies.** Catalog QDs,
   streptavidin/biotin, aptamer/PDB and other source import adapters; typed element
   copy. Test swapped bundled data, original versus imported status, source
   replacement repair and ownership closure. Prune duplicate route callbacks and
   obsolete global-library fallback only after caller coverage; retain named
   legacy recovery paths.

Reuse existing scientific and persistence tests instead of duplicating them:
`test_protein.py`, `test_nanoparticles.py`, `test_nanoparticle_attachment.py`,
`test_nanoparticle_kinematics.py`, `test_streptavidin.py`, `test_gold_strep_dna.py`,
`test_quantum_dots.py`, `test_duplex_crud.py`, `test_duplex_relocate.py`,
`test_duplex_cluster_parity.py`, `test_element_copy.py`, `test_pdb_to_design.py`,
`test_aptamer_import.py`, `test_project_revisions.py`,
`test_project_collaboration_api.py`, and `test_native_part_package.py`. Add
focused proof/edit/repair/portable-source cases; retain existing numerical
tolerances and expected molecular behavior.

## Primary CAD precedent

Onshape requires external data to be uploaded before FeatureScript references it
so regeneration has stable inputs. Its external-document imports select a
specific version and update explicitly; reference parameters let users change
the selected source without editing the feature's code. These are documented
precedents for source availability, version pinning and repairable input
selection. NADOC's content-addressed storage layout and imported/native status
rules above are architectural recommendations, not claims about Onshape's
internal implementation. [FeatureScript imports](https://cad.onshape.com/FsDoc/imports.html).
