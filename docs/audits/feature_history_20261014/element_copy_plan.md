# Standard-part rigid copy: P4 contract audit

Read-only audit against checkpoint `a000e1c7`, October 15, 2026. No production
changes, tests or molecular calculations were performed. Assemblies remain
deferred. Existing placement formulas and canonical geometry are the oracle.

## Recommended first slice

Add a versioned **same-part copy feature** for undecorated gold particles,
undecorated catalog quantum dots, and free proteins without an owned binder.
Resolve the selected resources from the current replay prefix. Record selection,
paste index and stable output identities; never record a source `Design`, solved
coordinates, atom arrays or a copied feature-output snapshot as native inputs.

This slice needs no DNA geometry and shares the protein asset already present in
the part. A copy creates a distinct editable placement/particle; later edits to
that copy do not edit the original. Editing an upstream source feature can
regenerate its downstream copy, as with other feature dependencies. Protein/QD
source provenance remains imported when the prefix contains an import.

Keep the existing frozen clipboard route explicitly unverified until a separate
admission adapter proves it is equivalent to a current same-part selection.
Do not silently change frozen clipboard semantics or call a saved authoring
snapshot a native source.

## Current paths and concrete risks

- [HTTP paste:1051](../../../backend/api/routes_nanoparticles.py#L1051) accepts a
  complete client-supplied `Design` and logs only protein/particle IDs. The row
  omits the source, `paste_index`, generated identities and placement choices.
  It is correctly outside the versioned proof registry today.
- [Clipboard:21](../../../frontend/src/scene/element_clipboard.js#L21) clones the
  displayed Design, clears history/loadouts and keeps that snapshot across
  later edits/deletion. It has no document/revision binding. The first-party
  callsites found are the HTTP route, browser clipboard and tests; no dedicated
  native headless copy adapter was found. Headless callers can presently submit
  the same snapshot endpoint.
- [Identity allocation/remap:51](../../../backend/core/element_copy.py#L51)
  uses a flat string map and UUID4. Every matching string is rewritten,
  including names, sequences, metadata and embedded source labels. Distinct
  resource kinds sharing the same raw ID alias each other. Dictionary keys
  containing references are not rewritten. This must not enter a native recipe.
- [Ownership extraction:32](../../../backend/core/element_copy.py#L32)
  silently filters away missing declared strands/helices. There is no complete
  outgoing reference or ownership check before copying a conjugate.
- [DNA correspondence:141](../../../backend/core/element_copy.py#L141) keys
  residues by `(copied strand, bp, copy)` only, omitting helix and direction.
  Repeated base indices in multi-domain strands can overwrite each other.
  Unmatched output residues are silently skipped at line 160. Reject such
  selections until an exact, unique, complete correspondence is established.
  The fragment at line 137 also omits lattice type and therefore uses the
  default HONEYCOMB context even when the destination is SQUARE; its native
  frame comparison needs explicit lattice-context parity before qualification.
- [Asset additions:222](../../../backend/core/element_copy.py#L222) trusts a
  destination asset with the same ID without checking equal content, and
  appends missing assets by set iteration. Cross-document identity collisions
  and cross-process asset ordering are therefore additional blockers. V1
  avoids both: only current-part asset references, with no asset additions.
- The copied family list omits crossovers, ligations, flexible connections,
  cluster/domain transforms, deformations, CPDs and saved connection versions.
  Some displayed DNA effects are instead baked into newly allocated nucleotide
  transforms. That is not a generic closed topology copy contract.

The native geometry source is
[fitting_geometry:826](../../../backend/core/design_geometry.py#L826), which
delegates to canonical Full geometry, not relaxed display caches. The current
copy calls it without a selection filter and therefore computes whole-design
DNA whenever an owned strand or anchored protein is selected. V1 avoids this
work entirely. Later geometry-bearing slices can use its existing scoped
arguments only after full-versus-scoped parity is demonstrated; extensions and
bridge connections already force its conservative full path.

## Existing placement behavior to preserve

[element_copy.py:85–190](../../../backend/core/element_copy.py#L85) determines
one batch bounding width along world X from selected protein atoms, particle
diameter bounds and owned DNA backbone points. It translates by
`((width + 5.0) * paste_index, 0, 0)`. It composes the protein world transform
using the existing helper, left-multiplies the shift into particle/protein poses,
and detaches copied anchored proteins to a free target. No new rotation, phase,
clearance or molecular-placement rule is proposed.

For DNA copies it shifts helix axes/native atoms, clears grid/frame placement,
clears domain binding and parent-overhang links, resets copied overhang motion,
and derives residue transforms to retain the native source pose. These are
observable semantics needing their own parity evidence, not incidental cloning
details. Group naming continues existing numeric suffixes while preserving
custom oligo names ([group handling:191](../../../backend/core/element_copy.py#L191)).

## Explicit v1 inputs and execution

Reuse existing operation kind `element-paste` with `_proof_version: 1` and a new
strict `copy_version: 1` discriminator. Legacy rows remain unsupported.

- Authored inputs: typed selections with `source_id` and host-allocated
  `output_id`, plus strict integer `paste_index` using the existing 1–10000
  range. Require a nonempty, bounded batch, unique typed selections and unique
  output identities. Preserve output IDs during source-reference repair;
  deriving public outputs solely from source IDs would break that repair.
- The live request supplies selections, paste index and expected revision.
  The host allocates outputs once, then resolves/evaluates/records under the
  shared atomic helper. Return existing `pasted_refs`; keep one undo entry.
  Prefer a new small route/module to overloading the required legacy `source`
  field. Registered headless transactions call the same pure builder.
- Require each source exactly once. Free protein means target `free`, no
  binder ID and no azide ownership. Resolve its captured asset exactly once,
  check any selected atom reference, retain the current 1000-atom/4000-bond
  admission, and bound total selected-atom work across the batch. Gold/QD must
  have consistent kind metadata, no applied coating/biotin DNA, conjugations or
  connection-version ownership. Missing references are structured failures;
  unsupported source families are explicitly unverified.
- Clone only selected models and change declared identity/pose fields. Share
  `asset_id` by reference; leave labels, metadata, source provenance and unrelated
  models unchanged. Deep-copy selected mutable nested particle/placement data
  to avoid aliases, not the full document or recovery history.
- Preserve current source-collection output order when qualifying the old
  clipboard path. Compute the batch offset with the unchanged formula. Reject
  nonfinite input poses/coordinates or generated results before publication.
  Check fresh IDs against existing definitions and dangling typed incoming
  owners so a new particle cannot accidentally acquire old conjugations.
- Keep a conservative part dependency barrier initially, with typed source
  resources for diagnostics. No source bytes are added by same-part copy;
  existing upstream import provenance is retained. Add strict registry parsing,
  output-identity preservation and capabilities only after the pure contract.
- If a compatibility adapter requires a default cluster, author it with a stable
  identity before publication; response formatting must not introduce UUID4
  authoring changes after the recorded candidate.
- A small pure command module and a live recorder module should own this logic;
  the already-large nanoparticle router receives only thin wiring. Factor shared
  placement calculations only without changing the legacy mathematical path.

Native output is ordinary authoring state, so standard particle/protein patch
features can edit the copies. Verification must reconstruct it from prefix
resources and copy inputs; it must never inspect recovery blobs or the old
clipboard source. Existing capture/payload/worker limits remain unchanged; choose
the initial batch cap from measured candidate transport, not just arithmetic.

## Typed ownership for later slices

| Source family | Current evidence and next boundary |
| --- | --- |
| Free unconjugated protein, undecorated gold/QD | V1; no geometry/ownership graph to duplicate beyond current asset reference. |
| Unowned protein anchored to a part overhang | Next narrow slice: resolve exact overhang/backing domain/atom and canonical anchor, then use the existing world transform and free-target detachment. Missing anchor must fail; `protein_base_world` otherwise falls back to identity when no anchor is supplied. |
| Unbound thiol-functionalized gold | Native source creation is supported, but copy needs the entire declared conjugation → surface strand/helix/overhang/subdomain graph, groups and typed reference closure. Existing thiol ownership checks are a useful extraction basis; deletion's incoming-reference rule cannot be reused indiscriminately because copying leaves sources intact. |
| Part-overhang protein with one owned binder | Requires exact owned binder/asset/target resolution, explicit detachment of binding, complete directional residue correspondence and pose parity. Parent overhang is a read dependency; it is not necessarily copied. Shared source helix alone is not an error. |
| Already detached free conjugate | Current legacy movement/copy bakes per-residue transforms; needs the same exact residue/ownership contract before native admission. |
| Streptavidin coating, biotin DNA, bound NP versions, mixed CPD/linker/Join/deformation owners | Unsupported until each selected family's geometry context, detachment policy and outgoing ownership are explicit. Do not copy an arbitrary nested protein asset/pose array as native authored inputs. |
| Other-document or frozen/deleted clipboard source | Separate explicit pinned-source/import or pinned recipe-prefix contract; cannot resolve against the current replay prefix. A JSON `Design` digest alone proves bytes, not native construction. |

For copied DNA, key identities by `(resource kind, identity)` and use
[part_scope_references.py:310](../../../backend/core/part_scope_references.py#L310)
for typed model remapping where its full-closure assumptions apply. Build a
minimal authored view after explicit allowed detachment; do not pass the entire
Design through the mapper. Preserve required identity grammars (`__np__`,
`__strep_dna__`, and owner-derived `__lnk__…` if linkers are ever supported).
Allocate subdomain/extension/group/transform IDs deterministically from explicit
copy output identity and semantic child keys. Geometry-derived transforms are
outputs, never command inputs. Check complete source/output residue bijection
including helix, direction, base index and copy index before deriving any poses.

Copy closure is not deletion closure: incoming consumers of the unchanged source
may remain unchanged. Outgoing references of a copied object must be copied,
retained intentionally (protein asset), or explicitly severed by the native
copy semantics. An unsupported constraint affecting source pose must be rejected
or included as a declared read context; it must not disappear silently.

## Clipboard compatibility and external sources

Add document/revision provenance to future copy capture. A small first adapter
may qualify a legacy clipboard only when its selected source records, required
assets and complete v1 reference scope equal the current authoritative selection.
Perform equality/eligibility before mutation, then recheck under the expected
revision. Native execution reads the authoritative current part, never client
snapshot geometry. Repeated paste remains valid after unrelated copy additions.

If the original was changed/deleted, another document is active, or the selected
scope is unsupported, preserve the old frozen clipboard path and mark it
unverified. No fallback after native evaluation fails. A later native frozen
copy can pin an independently replayable recipe prefix plus immutable import
sources, or use a separately reviewed explicit external import. Do not silently
promote a client-authored whole Design to native evidence. P6 can then apply its
server-authoritative policy to legacy/import paths.

## Official CAD evidence and interpretation

Onshape Transform creates separate copies that can be edited subsequently;
its copy feature takes source parts and placement choices.
[Transform](https://cad.onshape.com/help/Content/PartStudio/transform.htm).
FeatureScript patterns likewise take queried entities, transforms and distinct
instance identifiers; outputs can be queried by those instance identifiers.
[opPattern and qPatternInstances](https://cad.onshape.com/FsDoc/library.html#opPattern-Context-Id-map).
This supports explicit source references and stable copy identities, rather than
copying generated outputs into a feature's parameters (NADOC design inference).

Onshape distinguishes duplicating a result from reapplying its defining
features. Reapplication includes dependencies/end conditions and costs more
regeneration time. A first NADOC rigid-copy command should similarly reuse its
prefix result and existing placement mechanics, rather than replay its entire
source feature subtree for every instance.
[Linear Pattern](https://cad.onshape.com/help/Content/PartStudio/linear_pattern.htm).

Derived geometry has one-way references. Other documents are version-pinned;
same-document references may use a workspace or a version. Onshape recommends
versions for controlled updates/performance and rejects circular references.
These are useful boundaries for a later pinned external/clipboard source, not
evidence that a snapshot is a native feature.
[Derived](https://cad.onshape.com/help/Content/PartStudio/derived.htm).

Onshape repairs broken references by selecting a replacement from a healthy
historical context, optionally propagating it downstream. NADOC should expose
the selected `source_id` as a typed repair target while preserving its output
ID; it should never guess another element from equal names or nearest position.
[Repairing](https://cad.onshape.com/help/Content/Document/repairing.htm).

## Implementation and acceptance sequence

1. **Pure v1 + registered headless path.** Exact native legacy parity for free
   proteins/gold/QD, batch/multiple paste indices, complete-authoring equality,
   deterministic outputs across cold workers, transport reconstruction, poisoned
   recovery, source immutability and no fitting-geometry calls. Test equal raw
   IDs across resource kinds and text equal to IDs without metadata rewrites.
2. **Live route and qualified clipboard.** One undo/redo step, expected-revision
   rejection, atomic recording rollback, preserved pasted selection/placement,
   stale/deleted/other-document snapshot compatibility and no native fallback.
   Browser tests/app exercise are required if clipboard UI wiring changes.
3. **Anchored placements, then closed conjugates.** Add separate versions/scopes
   only with independent geometry parity, exact missing-reference failures,
   loop/copy-index/direction cases, multi-domain collision regressions, stable
   child IDs, both lattice contexts and group-name behavior. Shared source
   references remain untouched.
4. **External/frozen sources.** Explicit immutable input policy and provenance;
   unsupported import coverage remains visible until independently reproducible.

Benchmark copy-only and full atomic route/capture separately: a tiny selection
in both small and large unrelated DNA/history documents, then the admission
boundary. V1 must not evaluate DNA or deep-copy unselected payloads. Existing
snapshot/capture costs should be reported separately; do not weaken guards or
claim lower whole-document costs from a faster clone alone.
