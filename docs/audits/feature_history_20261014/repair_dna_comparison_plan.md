# Complete authored DNA comparison: next increment

2026-10-15. The first pure DNA projection/admission and version-two worker
integration are implemented for qualification. `DNA_COMPARISON_ENABLED = False`
keeps the public route unavailable before any source capture. Existing version
one remains unchanged. No geometry kernel, scientific algorithm, solver,
numerical pin or ordinary renderer changes are included. Assemblies and numerical
engine upgrade authorization remain separate. Parent serializes validation and
admission measurements.

## Implemented qualification boundary

`core/part_dna_comparison_contract.py` counts both directions of every helix,
positive insertions, occupied domain walks, extended tails including empty gaps,
and the global deformed arm span before native allocation. It bounds typed
collections, selectors and path stations. The worker then checks typed reference
closure, unique domain occupancy, exact nucleotide copy/owner coverage, native
slab authority and complete axis/domain/overhang inventory. Missing records or
unreviewed output fields refuse the whole comparison. The new
`core/part_dna_comparison.py` calls the unchanged native pipeline and passes its
records/axes through without coordinate changes.

Version two uses scope `ordinary-dna-uncoated-particles-free-proteins-v2` and adds
one closed `dna` component to each existing pane:
`component_version: 2`, `representation: native-full-v1`, `units: nm`, lossless
fixed-row `nucleotides`, `helix_axes`, `display_topology`, and `bounds_nm`. The row
order is a versioned constant; every native value survives JSON roundtrip exactly.
This removes repeated property names, without float rounding, downsampling,
identity reassignment or dropping ownership/reference/copy flags. Free assets use
the unchanged version-one projection; combined bounds share nanometres. The
coverage policy explicitly declares `all_authored_opaque_except_reference_strands`:
cluster opacity and ordinary presentation/physical overlays are excluded.

`display_topology` is not a Design. It carries only reviewed helix, domain,
strand, overhang sequence, cluster/color ownership and direct connection fields.
Native continuity/seam decisions also require helix lattice identity/direction
and a small explicit deformation provenance projection: selected helix/range IDs,
planes, sweep start/direction and bend circle/curvature values. These fields must
not be reapplied to coordinates. In the later frontend adapter, assign a private
palette namespace: the native staple-color helper keeps per-design pins. Dispose
only that namespace with `_resetStapleColorPins(privateId)`; never clear the live
part's palette or shared native geometry templates.

The original job catalog/slot, source/session/revision/draft guards, worker
cleanup, lease expiry and 2 MB combined transport/result remain authoritative.
Strict HTTP still refuses this compatibility route. No new state/model fields,
cache, job catalog or readiness receipt are added.

Initial pure target: **58 passed in 2.89 s**, parent-run. Five warnings from
partial tagged-union DTO serialization were corrected by directly serializing
the selected concrete params model without changing output. The combined pure,
version-two integration and version-one worker/owner/route regressions then
passed **142 tests in 5.84 s**, including a real spawned DNA worker and registered
recipe comparison followed by one commit. No frontend DNA implementation or app
check has run. Public enablement, GPU ownership/parity and representative resource
qualification remain explicit completion gates.

The initial parent-run benchmark is retained in
`benchmark_dna_comparison_initial.json`: 72 admitted warm cases projected and nine
oversized-helix cases refused early. Three tiny HTTP requests succeeded; all three
512-bp and three six-helix requests failed with **413 result_limit**. These failed
admission, regardless of the original script's zero cleanup-oriented exit status.
The short-ID warm boundary was 1,928,446 bytes; actual recipe UUID identities repeat
in each record and exceed the unchanged 2,000,000-byte result cap. Source/candidate
and revision remained unchanged and cleanup succeeded. Capture lock maximum was
2.76 ms; child process high-water RSS was 176,588 KiB. The reported light-request
maximum (8.06 ms) is **not full-request evidence**: a 256-request sampler stopped
before worker completion and parent output encoding. No admission or responsiveness
qualification follows from that run.

The post-checkpoint correction uses fixed-row transport and measures actual
recipe result sizes. Revision sampling now lasts until request completion, with
10 ms pacing and a five-second measurement ceiling; no per-request array is
retained. A non-successful boundary response or incomplete measurement makes the
transport verdict false and script exit nonzero. Corrected backend tests passed
**149 in 6.49 s**, including both real UUID boundary byte/parity regressions.
The corrected benchmark rerun remains pending.
`python -m scripts.benchmark_dna_comparison --repeats 9 --http-repeats 3`
creates no
files or production app lifespan. Warm native derivation/capture/encoding cases
include loop/skip, bend, sweep, rotated overhang, child-cluster, 1,024-slot and mixed
free-asset inputs plus an early-refusal case. Real HTTP comparisons use fresh
spawned workers and registered small/boundary/six-helix repair recipes, retaining
all refusals and concurrent scalar-revision request/lock timings. Setup uses the
real repair evaluator outside measured projection time. One isolated document
and its jobs are removed in `finally`; host instrumentation/gate are restored.
Only compact stdout JSON is emitted. Renderer/GPU costs remain unmeasured.

## Frontend qualification implementation (not yet tested)

The private controller accepts an explicitly injected projection version; its
production default remains version one and refuses a mismatched response version.
Closed DTO validation proves bounded record/axis/domain ownership before renderer
allocation, then the fixed-row codec restores every native field for the unchanged
`buildHelixObjects` Full builder. Raw axis records use the normal API adapter's
per-helix map shape, including overhang axes. No poses are reapplied.

`native_connection_lines.js` extracts the existing merged RGBA line constructor
and exact 20-segment quadratic write loop from `unfold_view.js`. Normal unfold
and comparison share it; comparison uses the existing `t=0` midpoint control.
The native connection inventory supplies topology decisions. Explicit ligation
metadata absent from that inventory refuses the whole preview; no connection is
invented to make a source appear complete. Setup-only polymer continuation previews
are excluded from this authored-geometry view.

Each comparison owns its scenes and a private Symbol palette key, which cannot
collide with an authored string Design ID. Cleanup skips shared native templates;
the instance-alpha installer's exact private attribute identifies its cloned
geometry even though Three copied the template's shared marker. Those proven
private clones, owned instance resources, materials and lines are released. Tests
prepare normal-scene parity, template/palette survival, failed-second-pane cleanup,
and actual Python-to-Node packet consumption. `main.js` has no changes. Frontend,
GPU, app and resource gates remain pending until their recorded runs complete.

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
