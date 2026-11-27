# Reconstruction output and source triage

A reconstruction package now has a `reconstruction-index.json` and a readable
`README.txt`. The index lists the exact native file, source PDF, and per-design
report paths, along with counts for each output type.

| Output | What the package contains |
| --- | --- |
| Complete | A saved, reopened and audited NADOC part covering the compiler's source reconstruction. Review notes can still apply. |
| Partial | A saved, reopened and audited NADOC part with documented omissions. The report identifies omitted routes and any candidates. |
| Report only | Source and available evidence, including the stage and reason native output stopped. |

Each issue has a stable code, a stage, a severity and a suggested action.
Blocking issues stopped native output. Omissions index into the per-design
report's `omissions` array using zero-based indices. Review issues preserve
conflicts, evidence limits and unsupported annotations. The index can be used
without interpreting prose exceptions. Existing report fields remain available.
CLI sidecar reports for published parts use the same classification.

## D014 assessment

Figure 31 and the selected staple table provide enough evidence for general
extraction and candidate generation. The existing import has 270 table rows,
of which 219 belong to the selected module set. The visible raster supports
lane classification in two of four image placements. The bounded sequence
search under the M13mp18 hypothesis retains 4,721 compatible paired bases.
Two small-gap candidates and the capped short sequence matches at helix 89
show where image and sequence evidence can be tested together. They leave the
image-to-table assignment and the absolute base register open. The published
figure and table are in [the local supplement](../experiments/origami_publication_catalog/assets/sources/PMC6906287-41467_2019_13284_MOESM2_ESM.pdf#page=45).

| Step | General implementation | D014 limit today |
| --- | --- | --- |
| Source and variant selection | Parse structured tables and preserve row provenance, continuations, annotations and variant groups. | The selected module set is available. A module label does not locate an oligo in the image. |
| Registration | Fit panel transforms and register visible row labels and rulers to explicit base coordinates. Test overlaps for agreement. | Partly classified visible placements and unresolved absolute register. Hidden or overlapping pixels cannot be assumed to match the visible composition. |
| Routing | Trace classified lanes, retain crossings and endpoint alternatives, and test short occlusions against joint image and sequence constraints. | The available sequence support leaves competing stapled paths, polarity and junction assignments. The short helix 89 matches cannot settle these independently. |
| Cross-section and placement | Match calibrated row labels to slice cells and test lattice type and orientation before compiling. | A visible honeycomb slice provides context. Full path-to-cell registration still needs to be verified. |
| Output | Author the supported subset through normal editor commands and replay it. Retain other evidence in the report. | Even a partial native file needs a verified directed scaffold core, coordinate mapping and unambiguous termini for every included strand. Those prerequisites are unresolved. |
| Annotations | Retain labeled handles and toeholds; apply supported terminal dyes once routes are identified; report unsupported chemistry. | The lipid flags remain unsupported. Label records can be carried without resolving their native attachment. |

The generalizable work is labeled raster registration followed by joint
constraints over scaffold register, strand direction, route continuity and
table identity. Those constraints can be exercised on clearer figures before
judging what they recover from D014. A better raster or original routing file
can supply constraints that the present visible composite leaves open.
A complete D014 reconstruction from these pages remains unproven.

## Broader source check

The 32 reviewed catalog records include 27 complete design maps, three
conceptual illustrations, one partial design and one component-only map.
The source-scope labels below come from that review. They are not automatically
inferred from arbitrary uploaded figures.

| Cases | Evidence or compiler result | Classification |
| --- | --- | --- |
| D005, D007, D008 | Complete recipes from endpoint-labeled vector sources. Existing saved parts provide native-output examples. | Complete recipe |
| D009 | Recipe with unmatched and multiply matched staples, scaffold length discrepancy, unpaired scaffold review and base conflicts. The existing saved part is partial. | Partial recipe and distinct omission/review codes |
| D001, D002, D003, D010, D012, D015 | Endpoint-table compiler stopped before calibration. D003 has a verified part from another workflow. | Base register unresolved in this compiler |
| D014 | Full PDF-to-report packaging with source trace and sequence evidence. | Report only, with sequence alignment, base register, lane classification, search bounds and annotation issues |
| D004, D013 | Conceptual figures. The exact figure/table variant is unmatched or unverified. | Incomplete figure scope and unverified table variant |
| D016, D028 | Partial design and component-only map, respectively. | Incomplete scope for whole-object reconstruction |

Recipe checks in this comparison did not author parts. A recipe status is
separate from the result of publication and replay. The check covered 15 figures from 10 publications and several evidence levels.
It does not measure reconstruction accuracy across the full catalog.

A mixed package also exercised actual construction, publication and reopening.
Its index matched the archived files for D008 (complete), D009 (partial) and
D010 (report only). The check held the ZIP in memory and verified cleanup of the
temporary native files.
