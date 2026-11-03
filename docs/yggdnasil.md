# YggDNAsil: DNA-origami design atlas

**Priority: non-critical / future consideration (2026-11-02).** YggDNAsil is an
exploratory side project. Preserve the current atlas, screening evidence and 3D
tree as a prototype; further expansion is deferred until explicitly prioritized.
It is not a release requirement or a blocker for core NADOC work.

Open **Help → YggDNAsil…** in the main NADOC window. This read-only explorer
maps a finite family of geometric candidates; it does not edit the active design.

Version 1 covers connected, filled circular footprints on square and honeycomb
lattices. Disks are centered on a helix, a nearest-neighbor bond midpoint, or a
cell center. All sites at a boundary radius enter together. Every distinct shell
is considered until its helix count exceeds the scaffold budget. Disconnected
footprints are excluded. Arbitrary off-center disks, hollow structures, bend,
twist, routing, and sequence variants are outside the original straight-rod grammar.
The extensions below add uniform solid-rod arcs and straight hollow cylinders, including wider thin-walled footprints.

Footprints are canonicalized under translation and proper lattice rotations.
This preserves embedded shape rather than only contact-graph isomorphism.
Generating-center aliases are retained. Lattices remain separate, even for a
single helix. The exported `canonical` key identifies an occupancy footprint;
short IDs are local to an enumeration, not permanent molecular design IDs.

For H helices, S scaffold nucleotides, reserved allowance U, and minimum length
Lmin, every integer length Lmin through floor((S-U)/H) is represented. The default
minimum is 21 bp and can be increased; it is an atlas boundary, not a mechanical
qualification. Dimensions use NADOC's 2.25 nm helix pitch and 0.334 nm/bp axial
rise. Disk radii measure helix-center inclusion, not molecular surface radius.

With Lmin=21 and U=0:

| Scaffold (nt) | Unique footprints | Footprint–length candidates |
| --- | ---: | ---: |
| 7249 | 308 | 52,016 |
| 7560 | 320 | 54,557 |
| 8064 | 341 | 58,660 |

Counts are exhaustive only within this stated grammar and budget. Remaining
scaffold needs an explicit complete route. A reserve does not establish such a
route. Crossovers, staples, exact scaffold completion, folding and rigidity are
not verified by this atlas.

The interactive 3D tree shows a fixed-length slice: square and honeycomb form
the two main limbs, with separate helix-, bond- and cell-centered twigs. The
shared tree-length control sets every point to one specific axial size. Click a
point or label to inspect its cross-section and side silhouette. Drag to orbit,
scroll to zoom, and use Reset view (or F with the canvas focused) to recenter.
A structure selector and adjacent-step buttons provide keyboard navigation. JSON export includes
all footprints, lattice addresses, aliases, and inclusive length intervals rather
than materializing every length as a repeated point list.

Implementation: `frontend/src/design/yggdnasil.js` (enumeration),
`frontend/src/ui/yggdnasil.js` and `.css` (explorer). Regression coverage includes
known small shells, canonicalization, integer length counts, reserve bounds,
modal lifecycle, and a browser Help-menu integration test.

## Scaffold traversal screen

The routing filter separates **excluded**, **traversal found**, and **unresolved**
entries. Excluded entries remain inspectable and are included in JSON exports
with their evidence. Changing size bounds recomputes counts from the screened
footprints.

This screen targets the Hamiltonian helix-path prerequisite used by NADOC's
uniform-bundle seamed/seamless routing family. It is not an impossibility claim
for arbitrary custom scaffold routes that revisit helices, add return tracks,
introduce modifications, or use multiple scaffolds.

For each footprint, the native `crossover_neighbor(..., is_scaffold=True)` table
supplies edges over one complete crossover period. This is a permissive graph:
a missing Hamiltonian path rules out every length/register within this routing
family, while a found path alone does not establish bp-level placement or budget
completion. A path alternates lattice parities, requiring populations differing
by at most one. Remaining footprints undergo the native admissibly pruned DFS,
with all possible starts and a shared limit of 20,000 visited states. Finishing
all starts without a path is a proof within the graph model. Reaching the visit
limit is **unresolved**, never a reason to prune. Verified witnesses are stored
as indices into the footprint's point list.

Default bounds (minimum 21 bp, no reserved scaffold):

| Scaffold | Initial candidates | Parity exclusions | Exhaustive-search exclusions | Total excluded | Traversal found | Unresolved |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 7249 | 52,016 | 7,760 | 6,507 | **14,267 (27.4%)** | 34,772 | 2,977 |
| 7560 | 54,557 | 8,162 | 6,870 | **15,032 (27.6%)** | 36,311 | 3,214 |
| 8064 | 58,660 | 8,820 | 7,450 | **16,270 (27.7%)** | 38,801 | 3,589 |

For 7249 nt, 153 of 308 footprints are excluded; 46 have a traversal witness and
109 remain unresolved. Counts above weight each footprint by all its allowed
integer lengths. Traversal witnesses are not complete scaffold designs, and
none of the remaining counts should be labeled experimentally valid.

Reproduce from the repository root:

```sh
.venv/bin/python scripts/screen_yggdnasil.py
```

The generated `frontend/src/design/yggdnasil_routing.json` includes source
hashes, parity populations, search visits, verified traversal witnesses, and
per-lattice summaries. Its fingerprint is tied to this atlas grammar; rerun the
screen when lattice/routing rules or footprint enumeration change. Frontend
exports include screening scope and provenance.

Reproduce the illustrative native router checks with
`.venv/bin/python scripts/yggdnasil_route_examples.py`. Outputs are recorded in
`analysis/yggdnasil/route_examples.json`. A 6-helix honeycomb rod of 1208 paired bp
per helix occupies 7248 scaffold sites, but the native seamless route consumes
**7332 nt** after adding end turns. It exceeds a 7249-nt scaffold despite having
a valid helix traversal. These examples are not extrapolated into the pruning
totals. Some seamed examples also fail the separate ssDNA-clearance invariant
despite a true router `valid` flag; this is recorded rather than treated as a
verified route. Exact scaffold completion, terminal clearance and nucleotide-level
integrity remain further screening stages.


## Spatial tree edge semantics

Colored edges connect consecutive radius shells in the same lattice and center
family at the same axial length. Thus exactly one design parameter changes.
The helix-count increment is the number of sites in the next shell; it is not
necessarily +2. Neighbor buttons and labels show the actual increment. A
40hb → 42hb → 44hb chain appears only if those consecutive shells exist in the
same family; the viewer does not fabricate intermediate designs or silently
change the centering rule. The thicker trunk is a categorical grouping, not a
structural edit edge. Tree coordinates are a layout, not molecular coordinates.

Routing filters remove points and their incident edges without joining across
gaps. Changing the scaffold budget or length removes infeasible sizes. Aliases
can appear on multiple twigs while retaining one footprint identity and being
counted once in the distinct-structure total. The default 100 bp slice shows
only footprints that fit at 100 bp; full-atlas totals still cover every allowed
length. The JSON export now includes the displayed tree nodes, fixed length,
filter, and explicit edge differences in addition to the complete atlas.

Implementation: `frontend/src/design/yggdnasil_tree.js` builds semantic nodes
and edges; `frontend/src/scene/yggdnasil_tree.js` renders them in an isolated
Three.js scene. Closing the dialog disposes its renderer, controls, geometries,
materials, resize observer, and animation loop. If WebGL is unavailable, the
structure selector and neighbor controls remain usable.


## Bounded curvature count classes (2026-11-02)

The current UI is restricted to **7249 nt**. Every eligible radius-tree point
is the shared zero-curvature junction of its own outward-growing curvature limb.
There is no separate explore mode. Footprint and axial length stay fixed along
each curvature limb, while its nominal bend increases monotonically
through distinct `(inserted bases, deleted bases)` pairs. Counts include native
square-lattice baseline compensation (one staggered skip per 48 bp per helix).
Loops of different sizes count by their added bases, not by event count.

Scope decisions confirmed by the user: uniform planar arcs, no added twist,
separate insertion/deletion totals, and a preliminary budget with unallocated
scaffold shown. The bend direction is canonical +X across the footprint. Moving
a modification within a domain, reallocating modifications between domains, or
changing inserted sequences does not create another count class. This is an
intentional coarse grouping, not a claim of physical or sequence equivalence.

For centered transverse helix offsets r_i, nominal arc length L_nm, and angle
theta in radians, the uniform-arc form of Sweep's local demand is:

```text
local demand_i = 7 × abs(r_i) × theta / L_nm <= 3
maximum angle = min(2π, 3 × L_nm / (7 × max(abs(r_i))))
nominal per-helix correction = round(-r_i × theta / rise)
structural scaffold budget = H × L_bp + inserted − deleted
structural budget + reserved allowance <= 7249
```

Constants are exported from NADOC by
`.venv/bin/python scripts/export_yggdnasil_limits.py`. The current native rise is
**0.334 nm/bp**, replacing the earlier atlas's approximate 0.34 nm/bp display.
Tests compare the analytic limit with native Sweep warnings on controlled
circular paths. The atlas uses exact nominal arcs, not a newly instantiated
spline; it does not claim to validate arbitrary natural-spline interpolation.

The catalog visits every rounding threshold in that bounded angular interval,
merges states with identical separate insertion/deletion totals, and keeps one
canonical representative angle plus its target-angle interval. Zero bending
modifications represent a straight rod. The cap endpoint is retained when it
belongs to an eligible class, including a 360° circle where allowed. Counts use
deterministic half-up rounding at exact ties; within intervals the representative
is unambiguous. Other allocations can yield different curvature despite having
the same totals. Induced twist and physical relaxation are not predicted.

A canonical integer allocation reserves square compensation first, then fits
bending counts into remaining capacity with at most three modified bases per
seven-bp cell. Partial cells cannot contain more modifications than available
sites. These cells are **not yet routed strand domains**. No crossover-safe site
or terminal-clearance certification is implied. JSON exports include the count
classes, scope, native constant provenance, and selected cell allocation.

Classes exceeding the budget or local capacity are excluded. A limb requires an
eligible zero state and stops at the first rejected class; links never bridge a
gap. Traversal-excluded footprints receive no curvature limbs. Unresolved routing
searches remain included and labeled as unresolved, not certified valid. All limbs
are drawn together, using instanced points and batched thin links to keep the
complete tree responsive. Radius and bend neighbor buttons are separate at the
junction, and curved states offer a direct return to their straight junction.
JSON exports contain all displayed tree nodes and edges plus the selected
footprint's complete count catalog and selected cell allocation.

The shared length control slices the original straight-footprint library; its
screening counts remain separate. This is not an exhaustive enumeration of new
footprints or lengths made possible by insertions/deletions. The preview shows
the remaining scaffold explicitly. This remainder
is unallocated, not a completed route. End-turn overhead, exact 7249-nt routing,
collision freedom near closure, end ligation at 360°, staples, sequence identity,
and folding/rigidity remain unverified.

Validation of integrated branches: 20 focused unit tests and both YggDNAsil
browser tests passed; the complete branching tree was visually inspected and a
production build passed. Broader frontend validation found two failures in
unchanged modules (ISSUE-109/110), with 8,683 tests passing. On 2026-11-03,
ISSUE-109 was fixed and its positioning-review gate explicitly cleared. All 23
smoke tests and both YggDNAsil browser tests, including direct canvas picking,
then passed. ISSUE-110 and nine lint findings in unchanged Python files remain
separate. Temporary browser captures and workspace test artifacts were cleaned up.

## Straight hollow cylinders (2026-11-03)

The tree now combines solid rods (including bounded curvature) with **straight
hollow cylinders only**. Ring markers identify hollow points; the Shapes control
can isolate solids or cylinders. Hollow limbs hold lattice, center, outer radius
and axial length fixed while removing successive complete inner shells. Links
change only inner radius and never bridge missing or routing-excluded states.
Their brown/categorical stems group outer-radius families; they are not design
transitions from a solid node or between different outer radii.

Occupied helix centers satisfy `Ri < r <= Ro`. Ri is the last removed shell's
radius, not the molecular bore surface: Ri=0 means the central helix was removed.
The remaining wall must be connected on the lattice-neighbor graph. Every
removed site's neighbors must remain inside the outer disk, ensuring no open
slit from the removed interior to the exterior through vacant lattice sites.
This is a discrete enclosure condition, not a solvent-tightness assertion.
Translation and proper lattice rotations deduplicate wall footprints.

Per the requested expanded scope, cylinders are **not** limited to the filled
solid-disk size. At each selected length L, use `Hmax=floor((7249-reserve)/L)`.
A connected H-site wall has graph diameter at most H-1 edges; lattice edges have
unit pitch. Each complete outer shell contains opposite points, or a pair 120°
apart for a honeycomb helix-centered shell. Thus `Ro/pitch <= (Hmax-1)/2`, or
`(Hmax-1)/sqrt(3)` for that honeycomb family, is a conservative finite search
bound. All whole-shell annuli inside it that meet the wall and budget tests are
visited. This includes wider thin walls whose filled disk would exceed 7249 nt.
Enumeration runs in a cancellable worker; changing length/budget or closing the
modal discards stale responses. Short slices can take longer: at 21 bp there are
49,249 geometric footprints before routing screening (about 15.5 s in the local
standalone enumeration measurement). At 100 bp there are 748, with maximum outer
helix-center radius 22.2739 nm. Counts are fixed-length hollow footprints, not the
solid atlas's footprint-times-length total.

At the default 100 bp, native full-period scaffold traversal screening finds:

| Status | Hollow footprints |
|---|---:|
| Parity obstruction | 153 |
| Exhaustive traversal failure | 407 |
| Helix traversal witness | 166 |
| Search-budget exhausted | 22 |

The 560 known failures are omitted from hollow limbs. The remaining 188 include
22 explicitly unresolved cases; traversal witnesses still do not validate an
actual bp-indexed scaffold route. The generated audit covers all walls up to
72 helices. Larger walls visible at shorter lengths receive a parity check;
passing that necessary check leaves them explicitly **unresolved / native
traversal not yet screened**, never certified or assigned a solid-rod witness.
Regenerate with `.venv/bin/python scripts/screen_yggdnasil_cylinders.py`; the
report preserves native search bounds, witnesses and source hashes. A focused
Python check verifies every stored witness against the actual crossover graph.

Cylinder accounting currently uses `H*L+reserve <= 7249`, without enumerating
indels, curvature or twist. Square compensation and exact end-turn overhead are
not deducted/filled in this cylinder preview. Export includes the complete
selected-length cylinder atlas, routing labels, radii, and displayed tree links.

Hollow-cylinder validation: 26 focused frontend tests, the native witness/source
provenance check, all three YggDNAsil browser scenarios and all 23 smoke tests
passed. Combined and hollow-only tree views were inspected; the production build
passed. Temporary captures and test workspace artifacts were removed. The
positioning-review gate remains clear. `main.js` LOC delta: 0.

## Five-degree curvature pruning (2026-11-03)

Solid-rod branches now sample nominal targets `0°, 5°, 10°, …` through
`5*floor(maxAngle/5)`, with the same Sweep density, per-cell capacity and scaffold
budget checks. No off-grid endpoint is appended. Each sampled target is
quantized directly into inserted/deleted base totals, rather than merely
rounding the label of an existing representative. Sampling stops at the first
rejected target.

Count-based identity is preserved: repeated I/D pairs collapse to one point,
keeping their largest sampled target. The zero-bend class remains at 0°, even
when small nonzero targets round to no modifications. Consequently retained
angles are all multiples of five, but some adjacent distinct designs differ by
10° or more. Preview angles are nominal targets, not guaranteed relaxed angles.
The 360° endpoint is retained when allowed. The underlying exhaustive count
catalog remains available to the calculation code; the displayed tree and
selected-footprint JSON catalog use the pruned samples and export
`angleStepDeg: 5` plus the largest grid target below the local cap. Hollow
cylinders remain straight.

At 100 bp this reduces distinct non-excluded solid candidates from 2,847 to
1,122 (60.6%), including straight junctions and unresolved traversal cases.
Validation: 14 focused tests, all three feature browser scenarios, all 23 smoke
tests and production build passed. `main.js` LOC delta: 0. Temporary browser
captures and workspace test artifacts were cleaned up; positioning gate clear.
