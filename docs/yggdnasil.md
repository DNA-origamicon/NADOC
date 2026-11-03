# YggDNAsil: solid rod atlas

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
twist, routing, and sequence variants are outside this first grammar.

Footprints are canonicalized under translation and proper lattice rotations.
This preserves embedded shape rather than only contact-graph isomorphism.
Generating-center aliases are retained. Lattices remain separate, even for a
single helix. The exported `canonical` key identifies an occupancy footprint;
short IDs are local to an enumeration, not permanent molecular design IDs.

For H helices, S scaffold nucleotides, reserved allowance U, and minimum length
Lmin, every integer length Lmin through floor((S-U)/H) is represented. The default
minimum is 21 bp and can be increased; it is an atlas boundary, not a mechanical
qualification. Dimensions use NADOC's 2.25 nm helix pitch and 0.34 nm/bp axial
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
