# Nanobase publication inventory

The read-only application table is under **Help → Experimental → Nanobase publication inventory**.
It uses `frontend/src/data/nanobase_inventory.json`, not a live browser crawl. Search, software,
publication and figure filters operate locally; CSV and JSON exports contain the current selection.

The October 27, 2026 audit covers all 109 public listing entries (also checked against the public
count endpoint). File manifests are inspected separately from depositor descriptions. Native JSON
is classified by schema; `.mat` and `.dna` software labels require depositor evidence or explicitly
say inferred/unverified. Simulation protocols/results are included even when their filenames have
no standard extension. Coordinates and simulation files are not evidence of physical validation.

Publication identity, accessible supplementary figures, and uploaded-file equivalence are separate.
The last remains **not compared** for every record. Journal successors to old preprint links retain
both deposited and resolved references. `nanobase_publication_links.json` records the evidence for
those associations. `nanobase_figure_reviews.json` binds assistant visual reviews to exact DOI/PDF hashes and records PDF page
numbers (not printed page labels), and construct-specific qualifications. A cross-section labelled
caDNAno does not count as a strand-routing diagram. Other-software/3D routing panels are separate.
No-publication-supplied and failed-retrieval labels must never be interpreted as proof of absence.

## Reproducing a snapshot

Use a fresh, mounted Archive directory for a new collection. The collector caches responses within
one audit directory; it is not a background refresh service. Dependencies are `requests` and
PyMuPDF. In the project's environment, `uv run --with requests python ...` provides the optional
collector dependency; configure `UV_CACHE_DIR` and `TMPDIR` on Archive before doing so.

```sh
python tools/design_archive/inventory_nanobase.py --archive /mounted/archive/audit
python tools/design_archive/screen_supplements.py --archive /mounted/archive/audit
python tools/design_archive/build_inventory.py --archive /mounted/archive/audit
```

The first command follows only public listing IDs, checks listing completeness, inspects native
JSON, and retrieves Crossref/Europe PMC metadata. The second follows publisher supplement links
and ACS Figshare records, downloads PDFs, and records text-hit pages. Those hits do **not** create
verified figure labels. Visual review is recorded separately; changed PDF hashes automatically lose verified status until re-reviewed. Supplement SHA-256 hashes refer to original PDF bytes. Native JSON inspection
hashes are explicitly hashes of the normalized archived JSON, not original download bytes.

The current audit also includes a directly retrieved Europe PMC supplement archive for
PMC10371015 and two Nanobase-hosted uploaded supplements (records 10/11). Their source/host and
limitations are retained in review evidence. Europe PMC search was unavailable during the audit;
several publisher endpoints denied retrieval. These limitations remain visible in the data.

Original sources and compact validation logs are kept outside the user workspace at:
`/media/jojo/Archive/NADOC_archive/runtime/development-artifacts/nanobase-inventory/`.
Temporary review contact sheets, browser captures, traces, profiles and test downloads are removed.
No design imports, topology comparisons, simulation runs or training jobs are performed by this tool.

## Figure reconstruction benchmark (2026-10-27)

The first 21 verified routing-figure records were evaluated separately, preserving each
original PDF SHA-256 and one-based source page. Results are in Archive
`runtime/development-artifacts/nanobase-reconstruction-20261027/`. Shared pages are not
independent training examples. The unchanged application detector found candidates in
only records 132, 18 and 270; candidate detection is not successful reconstruction.
Fourteen records have raster routing; seven have substantial vector drawings. Scaling
and rotation trials expose serious grid false positives and are retained as failed
hypotheses, not improved accuracy claims.

Reproduce serialized, with `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1`, Archive `TMPDIR`,
and `scripts/validation_guard.sh nice -n 15`:

```
.venv/bin/python -m tools.design_archive.evaluate_verified --source ARCHIVE/nanobase-inventory --output AUDIT/evaluation
.venv/bin/python -m tools.design_archive.evaluate_normalized AUDIT
.venv/bin/python -m tools.design_archive.reconstruction_batch AUDIT ARCHIVE/nanobase-inventory
.venv/bin/python -m tools.design_archive.collect_starting_oxdna AUDIT/starting-oxdna
.venv/bin/python -m tools.design_archive.compare_oxdna AUDIT ARCHIVE/nanobase-inventory
```

The exporter comparison expects tacoxDNA checked out at `AUDIT/tacoxDNA`; this audit pins
commit `b8a1706d27548c96dcb13eabc8e5b9340bf241c3`. It runs converters only, never oxDNA.
Its pickle reader is restricted by workflow to the freshly generated local `virt2nuc`;
do not supply an untrusted checkout/output directory. Depositor descriptions are screening
labels, not proof: record 35's alleged unrelaxed input has nonzero time/energies and fails
the converter-coordinate match. Nine other configurations across eight records match
fresh converter coordinates to numerical precision. Export geometry differences remain
open; this workflow changes neither production geometry nor active jobs.

### Stage-two compiler

`backend/core/image_reconstruction.py` preserves vector line/Bézier evidence, image
resolution/bounds, and source-addressable paths without assuming path order is polarity.
It supports piecewise BP calibration with no extrapolation or implicit rounding. The CLI
compiles **reviewed image traces**, then compares a registered draft against a deposited
reference, including occupied sites, crossovers, termini and indels:

```
.venv/bin/python -m tools.design_archive.reconstruct_image compile review.json OUTPUT_DIRECTORY
.venv/bin/python -m tools.design_archive.reconstruct_image compare OUTPUT_DIRECTORY/draft.json reference.json difference.json
```

A review JSON must explicitly provide `source_sha256`, `evidence_ids`,
`registration_source` (`image-reviewed` or `reference-assisted`), `lattice` (`honeycomb`
or `square`), `helices` (`num,row,col`), and `routes`. Confirm `directions_reviewed`,
`termini_reviewed`, and `indels_reviewed` only after inspection. Each route has `kind`
(`scaf`/`stap`) and either exact `[helix,bp]` `sites` in 5′→3′ order or `vertices`
(`helix,x`), `order: "5prime-to-3prime"`, and top-level per-helix `anchors`
(`{"0": [[drawing_x,bp], ...]}`). Vertices are line/curve ENDPOINTS, never Bézier control
points. Split PDF paths require explicitly reviewed joining. `indels` list
`helix,bp,delta`; optional route fields are `circular` and integer staple `color`.

The compiler preserves supplied single branches and nicks, rejects overlapping routes
and non-integer calibration, and writes a draft plus provenance sidecar. It cannot
encode an isolated one-base strand and refuses it. It does not infer sequences, indels,
overhangs, polarity or lattice identities from reference files. Reference-assisted
registration is explicitly labelled and is not independent image reconstruction.
No full draft from this cohort is yet validated; raster tracing and reviewed registration
remain required. The prototype is a headless module/CLI, not a new application menu.

Record35 follow-up: its filename-labelled `_unrelaxed.oxdna` is described as relaxed,
has zero time/energies, but differs from fresh tacoxDNA by 2.926 nm RMSD. It is retained
as an unresolved starting-state candidate; the description-labelled `.dat` is excluded
because it records nonzero simulation time. Nine configurations remain converter-matched.

### Image-only deductions (user clarification)

For this cohort, references are **check-only**. Do not use the compiler's generic
reference-assisted registration mode to fill image gaps. Run `deduce_directions` against
extracted evidence alone, then `check_direction_deductions` against the frozen hashes
and native directory. Outputs retain page-rotation alternatives and conflicting junctions.
The first exploratory report is Archive `nanobase-deductions-20261027/REPORT.txt`.
Track-order agreement is a conditional check, not verified helix identity or an independent
held-out accuracy measurement. Global reversal requires an independently justified image
anchor; unanchored connectivity must keep both possibilities.

### First complete import exercise

`import_triangle_figure.py SOURCE_SUPPLEMENT.pdf OUTPUT_DIRECTORY` traces the explicitly
selected ModularTriangle270 Fig.S1 on PDFpage2. It is case-specific: crop, legend and
cross-section interpretation are documented in the code/provenance. It never reads
native design files. It outputs relative and register-selected caDNAno drafts, with all
32 square-register scores from generic scaffold/staple crossover tables. End-cap and
insertion-symbol offsets follow the original caDNAno renderer; PDF stroke endpoints
are not assumed to be nucleotide centers.

The inspectable `.nadoc`, intermediate caDNAno, selected source PDF, preview and notes
are in workspace `Nanobase Imports`. Scientific audit: Archive
`nanobase-imports-20261027/triangle`. This is an imported part through normal user routes,
not a generative-history reconstruction. Native references are post-inference checks;
24extra reference staple bases on helices27/29 are unresolved and were not copied.
