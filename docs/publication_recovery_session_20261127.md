# Publication recovery benchmark · 27 November 2026

D012 is complete for the pEGFP variant in Supplementary Fig. S9 and the
endpoint table on PDF page 17. The saved part includes all 121 table staples,
54 helices, the 4,733-base scaffold, and one recorded 71-base scaffold loop.
The saved file independently replays 1,197 recorded operations and passes the
bond-review gate. Its companion source PDF, compiler snapshots and native
replay evidence are in the Shared Designs provenance folder. The distinct
p7308 version on page 18 has a different sequence list and a long unpaired
scaffold region. The article describes both variants. [Douglas et al.](https://pmc.ncbi.nlm.nih.gov/articles/PMC2688462/)

The initial continuous-staple recipe failed when a staple revisited a helix.
An uncut precursor still connected domains that should have been separate
when the next crossover was placed. The domain-by-domain recipe published
successfully. Pre-cutting the relevant boundaries before placing crossovers
also passed the real package workflow with 54 staple pen strokes and 926
commands in 70.0 seconds. The compiler applies this scheduling to the new
panel extraction path. The saved library file retains the independently
verified domain-by-domain construction.

## Measured results

| Case | Recovered from the figure and selected table | Independent comparisons and remaining limit |
| --- | --- | --- |
| D010 Slotted cross | Two panels, one 8,634-site scaffold, 186/186 staple routes. Figure extraction and comparison took about 0.38 s. | All 15,420 directed sites match the legacy author graph exactly. The p8634 reference has zero mismatches over 6,760 paired bases. Under the routing model 26 additional table bases have no scaffold partner. Two separately calibrated 42-helix insets still need a relative 3D pose. |
| D011 Stacked cross | Two panels at right angles on the page, one 8,064-site scaffold, 241/241 staple routes. Extraction and comparison took about 0.32 s. | All 16,081 directed sites match exactly. The p8064 reference has zero mismatches over 8,017 paired bases. Bounding each panel by its row labels resolves a false overlap caused by extrapolating the rotated ruler. The folded pose and connector geometry remain unresolved. |
| D012 Genie bottle | One panel selected from a page that contains two designs, one 4,662-site scaffold, 121/121 staple routes. Extraction and comparison took about 0.33 s. | All 8,637 directed sites, normalized lattice cells, and the 71-base insertion match the legacy author graph. The historical pEGFP sequence gives zero mismatches across 3,949 paired bases. The 26 unpaired staple bases use their table sequences. |

The original caDNAno reference differs from GenBank U55762.1 at one position.
The GenBank comparison produced one disagreement with the paper's table. The
historical reference produced none. Both published sequences were tested as
written. [Original caDNAno reference](https://github.com/sdouglas/cadnano/blob/master/edu/harvard/med/cadnano/data/Sequence.as) · [GenBank U55762.1](https://www.ncbi.nlm.nih.gov/nuccore/U55762.1)

The algorithm detects paired columns of helix labels and each panel's ruler,
retains alternative origins, and uses jointly consistent table endpoints to
select a graph. Curves may connect two panel coordinate frames. Inset copies
are compared for the selected design. The author graphs entered the comparisons
after extraction. They supplied no panel calibration, routes, or placement for
the published D012.

A geometry-only measurement probed 24 proper signed-axis orientations for
each cross using four D010 or eight D011 scaffold links between panel groups.
D010 gave 4.500 and 4.506 nm RMS junction-axis separation for the two best
orientations. D011 favored an orthogonal candidate (4.084 versus 7.557 nm)
in this coarse screen, and its second inset fit after an in-plane rotation.
These scores use helix axes. They do not establish atom-level bond distances
or rule out collisions. A transferable next solver would bind each sub-inset
to its own frame, constrain orientation using the published folded view,
fit relative pose against strand-end geometry and steric clearance, and verify
the resulting joins in the native editor's recorded process.

## Remaining figures

The session inventoried all 32 catalog records. The following rows cover the
26 records that still lack a complete part after the D012 publication.

| Cases | Work to reach a complete part and the evidence needed to validate it |
| --- | --- |
| D001 | The raster grid probe finds 48 relative rows. A square-lattice extractor still needs labels and deletions, bridge-junction discrimination, matching to the named table rows, and a fold model for the connected regions. |
| D002 | Reuse the D003 fragmented vector approach for the strong–weak figure. Extract the variant's bridge and edge rows, test all square registers, then fit and verify the panel seams against this variant's routes. D003 provides a method and test oracle for shared drawing conventions. |
| D004, D013, D016, D025, D028 | The catalog figure is conceptual, partial or component-only. For a whole-part result, first identify a full map, a matching original routing file, or an explicit component/variant target. An archive contains candidate D004 variants and a D028 antenna template. They need object-level identification against the paper. |
| D009 | The archive gives exact endpoint and length agreement for the three omitted staples and zero disagreements across their 116 paired bases. Two are already among the image search alternatives. Table row 34 (zero-based report index) crosses the same-helix gap from helix 5 bp 291 to 295, which the search excludes. A source-assisted mode could verify and record these paths, with the existing scaffold length discrepancy still in the report. |
| D010, D011 | Source routing and sequence checks are complete. Per-group inset fitting, a folded-view coordinate constraint, and native recorded pose/connection validation are the remaining work. |
| D014, D015, D021, D022, D024, D026, D027 | Each requires a calibrated raster graph before native compilation. For D014, reuse the supported relative panels and table anchors, resolve overlaps and absolute register, then solve the directed scaffold and staple graph. The simple grid detector missed the other formats altogether. For D021/D022, keep the separate slice and sequence supplement tied to the same pore variant. D026/D027 have particularly small image placements and need higher-resolution or original routing evidence where crossings and labels disappear. |
| D017–D020 | The vector data is available. The current whole-path and panel extractors fail on the plate layout or the stroke/label conventions. Split the variants and schematic layers, build a graph from vector stroke fragments, and align each bundle's table or workbook sheet separately. |
| D023 | A vector ring map is available. Establish periodic routing and a scaffold origin, and map the scaffold/staple routes and published anchor variants to the same ring geometry. |
| D029–D032 | The source ZIP files contain large PNGs. The dominant-line deskew probe finds roughly 65° for D029 and a quarter-turn for the rectangles. Tile the native-resolution rectified images and check overlapping regions, OCR the ruler and labels, then match table routes and modifications by variant. Downsampled orientation and marker counts alone are insufficient to establish base registration. |

The substantial remaining blocks are folded pose and native junction
validation for the two exact cross routings, graph and register recovery
for the raster/fragmented formats, and source coverage for partial figures.
The bounds above describe what each test constrained and leave distinct
hypotheses available for later validation.

Reproduction scripts and source measurements are in
`.development-artifacts/publication-recovery-20261127/`. They include the
32-record inventory, ruler alternatives, held-out pointer comparison, sequence
reference comparison, inset orientation sweep and raster deskew probe.

The full supplement entered Detect designs in 20.9 seconds and offered the
correct figure/table pairs for D010, D011 and D012. All 81 focused backend
tests passed, including the five-source sequence benchmark. That benchmark
takes about 6.7 seconds because it parses real publication PDFs and enumerates
full scaffold registers. It is now routed to the slow headless area.
