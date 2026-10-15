# Complete authored DNA comparison: next increment

2026-10-15. Read-only follow-up to the implemented particle/free-protein display.
No geometry, scientific algorithm, solver, limit or renderer change is authorized
by this document. Assemblies and numerical-engine upgrade authorization remain
separate. Parent serializes validation and admission measurements.

## Native derivation and completeness boundary

Use the full native order already in `backend/api/crud.py`'s
`_design_response_with_geometry`: `_geometry_for_design(design)`,
`deformed_helix_axes(design)`, then
`_apply_ovhg_rotations_to_axes(design, axes, nucleotides)`. Call these core helpers
on the independently owned source/candidate inside the existing disposable
comparison worker, without state/API response formatting or straight-view copies.
Keep mandatory canonical placement, junction balance, phase/slab poses and all
molecular constants unchanged. No geometry lock or numerical pin update is needed
if the core helpers remain untouched.

`core/design_geometry.py` already handles twist/bend/sweep, cluster poses,
extended strand domains, loop copies/skips, ordinary overhang rotations and base
nucleotide transforms. Keep its full records, especially `copy_k`, strand/domain
identities, `placement_source`, slab poses and reference flags. The compact feed
loses important identity/ownership flags and is not a blanket parity shortcut.
The optional `helix_axes` argument currently is not consumed in that kernel;
passing it must not be advertised as avoiding work.

Full records alone are not a complete drawing. `buildHelixObjects` deliberately
filters ss-linker and flexible-segment beads, and suppresses cross-helix cones.
The normal scene completes those through `overhang_link_arcs`, `flexible_arcs`,
`unfold_view`, crossover-extra placement and CPD bond layers. Drawing only a helix
root would silently lose real geometry and bonds.

| First reviewed DNA family | Required treatment |
| --- | --- |
| Ordinary helices/strands, lattice frames, loops/skips | Exact native bead/slab/axis records and bounded display topology; no placeholder bases |
| Twist/bend/sweep, whole/domain/child cluster poses | Keep complete Design context in the worker; transmitted geometry is already posed |
| Ordinary unconnected overhangs, base-kind nucleotide transforms | Same native rotations/transforms; require every referenced owner and target to resolve uniquely |
| Ordinary crossovers/forced ligations with no extra bases | Include all ordinary strand-domain continuations and explicit connections using `getCrossHelixConnections`; preserve self-closing/periodic-seam semantics |
| Existing uncoated particles/free proteins | Existing complete adapter can compose with the admitted DNA layer only when all cross-family owners remain free; a pure-DNA first release may refuse mixed inputs explicitly |

Initially refuse nonempty extensions; overhang connections/bindings, connection
versions and duplexes; flexible marks/connections; cluster joints/Join constraints;
photoproduct junctions or crossover/forced-ligation extra bases; native-residue or
native-source helices; atom/extra-base nucleotide transforms; anchored proteins,
coatings, conjugates and nanoparticle connections. Also refuse every future or
unclassified authoring field. These are unfinished coverage gates, not completed
features merely labeled unsupported. Their existing native display owners need
separate extraction/parity tests before admission expands.

## Cohesive implementation seams

1. Add a typed DNA display component and reviewed whole-input closure beside
   `part_comparison_projection`. Reuse the same source capture, candidate exact
   decode, job slot/catalog/session/source/draft checks, lease and output budget.
   No second projection job, candidate cache, independent authority or recovery
   decoding. Use an explicit new envelope/scope version; retain v1 compatibility.
2. Publish a closed `display_topology` containing only fields actually consumed
   by the native static builder: bounded helices (ID/span/axes), strands/domains,
   admitted overhang sequence metadata, ordinary crossover/ligation identities
   and reviewed color/cluster ownership. No feature log, source bytes, draft,
   physical state, arbitrary Design JSON or replay inputs in the display packet.
   Validate referenced IDs, domain occupancy and connection endpoint coverage;
   native helpers that skip a missing target cannot establish `complete=true`.
3. Reuse `buildHelixObjects` directly in an isolated scene, never install
   `initDesignRenderer` or `initUnfoldView`. Add the ordinary connection layer
   through a small pure extraction of the native 3D (`t=0`) line construction.
   `getCrossHelixConnections` supplies unchanged topology/ownership decisions;
   no nearest-neighbor inference or new spline/bridge formula. Full deformed
   geometry is displayed without unfold/deform animation or physical overlays.
4. Give the static adapter an explicit disposer: deduplicate owned buffers and
   materials, dispose instance-owned resources, and **never** dispose geometry
   tagged `userData.shared` (including native helix/impostor templates used by
   the ordinary scene). Verify a concurrently retained normal scene survives
   comparison close. Extend the existing private viewer/controller, not `main.js`.

## Bounds before expansion and measured admission

Retain the existing 25 ms / 2 MB / 30,000-node source capture, 2 MB combined worker
transport/result and five-second process deadline. There is no justification to
raise them for this display increment. Counting final occupied nucleotides is too
late: native array generation allocates both directions of every helix, even when
strands occupy few sites; domain walks and extended tails expand before output.

Provisional qualification targets, **not enabled limits**: 16 helices, 128 strands,
256 domains, 64 deformation/cluster operations, 1,024 total prospective generated
nucleotide slots per pane, and bounded total path stations/axis samples. Count
helix spans, positive in-range insertion deltas and left/right extended-domain
ranges before allocating native arrays; separately bound total domain-walk spans,
operation selector sizes and station arrays. Charge emitted records/topology/axes
again before encoding. All finite-coordinate, byte and worker deadlines remain
hard refusals; refusal affects comparison only, not editing/saving/evaluation.

The root benchmark should measure tiny and boundary straight/routed, loop-skip,
bend/sweep, rotated overhang and mixed supported fixtures: capture refusal rate,
lock duration, worker derive/encode time, exact input/output bytes, concurrent
lightweight request latency, CPU mesh construction and GPU allocations/disposal.
Keep ordinary geometry as the parity oracle and preserve failed/over-budget rows.
Do not infer responsiveness from finite ceilings or small unit fixtures.

## Completion gates and later families

- Source and candidate coordinates/IDs/slab frames/axes equal the unchanged full
  native feed, including loop copies and reference strands; no source mutation.
- Render inventory covers every admitted bead/slab, ordinary backbone and direct
  crossover/ligation connection. Missing/ambiguous references and any excluded
  family produce one unavailable result, never a partial pane.
- Pre-expansion tests reject huge empty helices, huge domain tails or insertion
  counts before native geometry runs. Worker timeout/result refusal reaps the
  child and keeps the existing evaluated repair untouched.
- Browser lifetime and same-frame tests preserve shared native templates and
  release all private resources. Existing context/expiry/commit tests remain.
- Extend the isolated e2e with one bounded real DNA parameter repair only after
  scope and cost qualification. Archive/app gates remain in force.

Subsequent complete layers: first extensions and ordinary duplex/binding state;
then extra-base/covalent CPD layers; then ds/ss linkers and flexible/Join arcs with
their exact native owners. Native residues/imported aptamers and anchored/coupled
assets follow their own coverage and byte qualifications. Flexible display has
native history/hysteresis choices; a stateless alternate curve is not a parity
substitute. None of these display layers lifts the separate molecular-upgrade
comparison/authorization gate.

The product precedent remains explicit reference-versus-modified graphical
comparison, not an implicit validity certificate: [Onshape Compare](https://cad.onshape.com/help/Content/Document/compare.htm)
and [SOLIDWORKS Compare](https://help.solidworks.com/2023/English/SolidWorks/sldworks/t_running_the_compare_utility.htm).
The exact closure, quotas, ownership and staging above are NADOC design choices.
