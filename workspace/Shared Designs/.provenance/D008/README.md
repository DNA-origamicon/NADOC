# D008 square-nut reconstruction

Source: *Self-assembly of DNA into nanoscale three-dimensional shapes*,
DOI 10.1038/nature08016. `shapes-supp.pdf`: diagram page 5 (Figure S5),
staple table page 13.

The PDF-only compiler generated 1,186 recorded native commands: 60 helices,
one 7,560-base scaffold, and 149 staples totaling 5,015 bases (12,575 nt total).
148 staples come from the published table and match the aligned scaffold exactly.
One additional 38-base strand is visibly drawn but absent from that table:
viewer helix 27[60] to helix 17[55]. Its direction follows unanimous antiparallel
scaffold evidence; its sequence is the scaffold complement along the drawn route:
`AAGTAATAAGCCCACAATGAGGGCTTAATTGAAGTACC`.
This sequence is explicitly derived, not claimed as a published table entry or
independent sequence validation. No strand route was invented.

The remaining 2,545 scaffold bases lie outside the published staple bands and
stay unpaired. A separately consulted native reference contains 120 additional
terminal staples; none were copied into this reconstruction. All recovered
scaffold and staple pointers match the reference, including the 38-base route.
The reference was never a construction input.

`publication-audit.json` records saved/reopened independent replay;
`reference-audit.json` describes the intentional reference-only terminal staples.
`construction-code.json` and `code/` retain the exact executed implementations.
The complete native feature history records the construction and sequence origin.

All 12,425 backbone edges, including 660 interhelix joins, were measured. There
are zero forced ligations, missing geometries or Full O5 spans above 1.2 nm.
This remains an idealized lattice representation, not physical relaxation.

Reproduce using `scripts.reconstruct_publication_design` with this PDF,
`--name D008 --diagram-page 5 --table-page 13` and default precursor settings.
