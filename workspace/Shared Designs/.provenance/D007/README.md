# D007 monolith reconstruction

Source: *Self-assembly of DNA into nanoscale three-dimensional shapes*,
DOI 10.1038/nature08016. Original supplement `shapes-supp.pdf`: diagram PDF
page 4 (Figure S4), staple table PDF page 12.

The default PDF reconstruction algorithm generated 1,298 recorded native commands:
60 helix placements, scaffold routing, 60 continuous staple precursor pens,
134 terminal nicks, 780 total native crossovers and 145 sequence assignments.
There are 60 helices, one 7,560-base p7560 scaffold and exactly 144 published
staples (5,880 bases): 13,440 nucleotides total.

All 1,680 bare terminal scaffold bases are retained in their drawn domains,
28 per helix and 840 per bundle end. No additional staples were authored. The
archived caDNAno variant has 70 additional terminal staples; it was consulted
only after construction for comparison. The target here is the publication's
bare-ended design, as clarified by the user. All scaffold pointers and all
published staple pointers/sequences match, with no extra or wrong pointers.

`publication-audit.json` records publication and saved/reopened independent replay.
`reference-audit.json` distinguishes exact PDF recovery from the intentional
reference-only staples. `construction-code.json` and `code/` pin the executed
source versions; the complete authoring process is in the native feature log.

All 13,295 backbone bonds were measured, including 780 interhelix bonds. There
are no forced ligations, no periodic seams, no missing geometry and no Full-view
O5 spans above 1.2 nm. This verifies the idealized lattice representation;
no physical relaxation or conformational prediction of the bare scaffold ends
has been performed.

Reproduce with `scripts.reconstruct_publication_design`, `--name D007`,
`--diagram-page 4 --table-page 12` and this supplement. Continuous staple pens
and end-wrap detection are defaults; D007 contains no qualifying end-wrap seams.
Existing destination replacement requires its exact current SHA-256.
