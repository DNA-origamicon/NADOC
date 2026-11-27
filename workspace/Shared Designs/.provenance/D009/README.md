# D009 partial reconstruction

`../../D009.nadoc` is a source-only, recorded reconstruction of Figure S6 from
`shapes-supp.pdf` (diagram page 6; endpoint table page 14).

It includes 46 helices, 194 of 197 table staples, 7703 scaffold bases, both
39-base strand-owned scaffold loops, and 285 native on-helix overhang bases. It has 1592 recorded
operations, including 46 initial staple pens. Seven table-only staple routes
were recovered uniquely under bounded native-crossover/sequence constraints.
Three staples remain omitted (two ambiguous, one without a matching route).

Read `reconstruction-report.json` for omissions, route alternatives, the accepted
one-base scaffold discrepancy hypothesis, and image/table conflict notices.
`publication-audit.json` contains source comparison, saved/reopened independent
replay, and native bond review. All 14678 backbone bonds had geometry; six exceed
the conservative 1.2 nm display envelope (two nonlocal joins, four loop boundary
bonds). This is unrelaxed geometry, not a simulation-ready conformation.

`code/` and `construction-code.json` preserve the actual code used for this build;
subsequent general algorithm improvements must not overwrite these snapshots.

The rebuilt design preserves source figure staple colors and helix row order.
`insertion-30-119.png` and `insertion-42-119.png` show the source loop glyphs
labelled 39 (PDF page 6). The November 26 rebuild uses two recorded
`strand-loop-set` operations at visible helices 30 and 42, base 119, with native
aspect ratio 3 and rotation 0. There are no helix-wide insertion/skip marks.
Scaffold sequence and staple routes are preserved. Appearance and insertion
representation evidence are included in reconstruction-report.json.

These loops support native NADOC persistence and display; simulation and
cadnano/scadnano export currently refuse strand-owned loops. The four loop-root
spans remain slightly above the 1.2 nm display screen (about 1.25–1.26 nm);
using the approved loop feature does not certify a relaxed molecular structure.
