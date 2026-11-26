# D006 publication reconstruction

Source: Dietz et al., *Folding DNA into Twisted and Curved Nanoscale Shapes*,
DOI 10.1126/science.1174251. Original supplement `twist-supp.pdf`: diagram PDF
page 20 (Figure S10), staple table PDF page 39.

The PDF-only algorithm emitted 1,434 ordinary recorded editor commands. The
published part has 20 native tracks, one 7,704-base scaffold, 209 published staples
(7,658 bases), and 15,362 total nucleotides. All source routing pointers match a
separately consulted reference after construction. Independent saved-file replay
passes without captured/import roots or recovery snapshots.

Source row 19 contains two independent loops with separate 49-base staples.
Native viewer helix 18 is the loop from helix 0 (source 19[256..179]); viewer
helix 19 is the loop from helix 1 (source 19[163..98]). The 46 unpaired bases stay
on native scaffold domains. No terminal extensions or invented oligos were used.

`publication-audit.json`: guard publication and independent reopen/replay.
`reference-audit.json`: subsequent source-reference comparison, including limits.
`construction-code.json` and `code/`: exact source versions used for construction.
The complete ordered recipe is also embedded in the part's native feature log.

## Geometry limitation

This is complete **source-topology reconstruction**, not simulation-ready molecular
geometry. There are 18 source same-helix end-to-end staple joins (~140 nm in the
straight monomer frame) and four nonlocal loop joins. The 18 end-to-end joins are explicitly marked as periodic
polymerization seams following the user's confirmation. Repeated instances belong
to a future assembly. The four loop joins remain nonlocal; no axial fitting,
flexible-loop conformation or physical relaxation was performed. A passed replay audit does not certify these bonds as physical.

## Continuous staple construction

The algorithm draws 18 continuous body staple precursors and two auxiliary-track
precursors. It excludes all segments of the 18 polymerization staples, which are
authored separately. Published terminal nicks precede crossover placement to avoid
intermediate cycles; each crossover uses the editor's native nick-and-ligate
operation. Final sequence assignment requires an exact directed-route match.
The scaffold construction is unchanged. This is a fresh recorded reconstruction
from the PDF, not a compression or relabeling of the previous feature history.
The prior saved file and provenance are retained in local development evidence.

Reproduce using `scripts.reconstruct_publication_design` with diagram page 20,
table page 39, `--continuous-staples --periodic-staple-seams`. The periodic flag
records explicit confirmation; internal same-helix loops are not silently treated
as polymerization. Existing-file replacement requires the exact current SHA-256.
