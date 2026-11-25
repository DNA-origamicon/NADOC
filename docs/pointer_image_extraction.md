# Pointer image-routing extraction: first controlled result

The deterministic vector-diagram extractor reproduces the pinned Pointer
reference's directed routing exactly from a rendered diagram and published
staple sequences. The extraction worker receives **no caDNAno reference or
NADOC model**. The reference is read separately by the image renderer and by
the validator after extraction.

This is a **controlled vector-PDF benchmark**, not a claim to have reconstructed
the original published Pointer image or an arbitrary raster screenshot.

## Result

- 15,240 occupied source sites recovered; zero missing/extra sites.
- Every predecessor/successor pointer agrees with the reference.
- One scaffold, 161 staples, and the single deletion recovered.
- All 82 square-lattice positions agree up to overall lattice translation.
- 7,249 paired staple bases agree with M13mp18 at the identified register.
- 740 staple bases without scaffold partners remain explicitly unknown.
- Original and independently reversed drawing primitives, shuffled primitive
  order, and fragmented horizontal strokes give the same routing.
- Three scale/row-spacing combinations pass. Incorrect staple sequences,
  a missing ruler, or a missing deletion mark do not yield a directed solution.

The deletion is retained as a source slot when comparing connectivity, and
excluded when comparing realized sequences. This distinguishes the 15,240
source slots from 15,238 realized nucleotides.

## Method

1. Read the visible base-index ruler and numbered helix-row labels.
2. Separate the blue scaffold and gray staple tracks by displayed color.
3. Expand horizontal vector spans into observed base-address edges. Connect
   crossover endpoints; Bézier control points are not nucleotide addresses.
4. Assemble connected components from the undirected edge graph. Stroke order
   and stroke direction are discarded. Crossings in the middle of curves do
   not become connections.
5. Read visible deletion crosses and the numbered square-lattice inset.
6. Enumerate scaffold senses and sequence-supported registers. For each
   candidate, test both orientations of **each staple independently**.
7. Use up to 12 informative paths to nominate registers, then validate every
   path against the supplied oligos. Raw sequences and uppercase cores are
   explicit alternatives; lowercase flanks are never silently erased.
8. Require a unique complete one-to-one staple assignment before returning
   directed routing. Unknown partners are not filled with guessed bases.

`backend/core/diagram_route_extraction.py` contains no Pointer filename,
reference loader, hardcoded helix map, register, or per-junction override.
`Detect designs` invokes it independently of the earlier whole-path detector,
which can miss fragmented diagrams. Its results include source hashes,
calibration, observed primitives, directed paths, deletions and lattice positions.
The UI distinguishes recovered topology from an authored molecular model.

## Reproduce

```bash
uv run python -m tools.design_archive.pointer_image_benchmark \
  --output .development-artifacts/pointer-image-extraction/controlled
just test-focused tests/test_diagram_route_extraction.py
```

The benchmark writes the controlled PDF and a quantitative `report.json`; it
never writes `.nadoc`/`.nass` designs. The recipe and process stages are included
in the report. The pinned source and published oligo evidence are described in
[dietz_pointer_reconstruction.md](dietz_pointer_reconstruction.md).

## Published-image check and remaining scope

The available Gerling 2018 supplement, Fig. S7 (PDF page 9), has 159 continuous
gray drawing paths and explicitly describes added terminal thymidines and
crossover TT motifs. It is not certified identical to the pinned 161-staple
reference. Its helix labels are outlines rather than extractable text, so this
first extractor reports that visible numeric row labels could not be read.
The source audit is retained locally under
`.development-artifacts/pointer-image-extraction/published-source-audit.json`.

Raster tracing/OCR, outlined labels, nonuniform scale, insertion symbols,
circular origins, multiple scaffolds, missing annotations, arbitrary colors
and full molecular-model construction remain unsupported by this first method.
The earlier partial-evidence method remains available when the calibrated
method cannot resolve the graph. No missing published-image information is
filled from the validation reference.
