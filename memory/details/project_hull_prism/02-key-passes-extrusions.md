# Key passes (extrusions) — supporting detail

[Topic head](../../project_hull_prism.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Key passes (extrusions)
- **Per-cluster** (imports): each detected cluster gets its OWN bundle frame
  (`_bundleFrame`) + axial scan. **Whole-part clusters skipped** — `is_default`
  OR ≥90% of helices (drops the autodetect "Scaffold Cluster" that overlaps the
  geometry clusters); falls back to all clusters when no finer ones exist.
- **Size exclusion**: clusters < `_hullMinSizeFraction` (default 0.10) of total
  dsDNA bp are dropped (`window.nadocHull.minSize`).
- **dsDNA-only**: `_dsTrimmedAxes` trims each helix's axis to its base-paired
  extent (projects dsDNA nucleotides onto the axis — `length_bp` is NOT physical
  extent, LESSONS F1), excluding ssDNA: unpaired scaffold, overhang/staple-only tails.
- **5% block filter**: `_filterSmallBlocks` drops boxes < 5% of total volume
  (declutters stub segments); empty-guard keeps the largest if all are below.
- **Margin** (`_hullScanTickBp`, null → per-lattice default): user-chosen
  **7 bp square / 8 bp honeycomb** (set in `_setRepresentation`; X-section margin
  slider overrides). NB: this is the OPPOSITE of the crossover period — a
  deliberate visual default, do not "correct" it.
- **Material**: solid opaque CAD-grey `0x9a9a9a` (`_extrusionMeshMat`), not the
  translucent green `_hullMeshPhong`.

## Overhang markers (color-coded quads)
`_buildOverhangMarkers` — one flat quad per overhang, **raycast onto the BUILT
hull mesh** (built first, then markers) so it lands flush on the actual rendered
face with the hit normal. Position from **current (transformed) overhang
nucleotide positions** (grouped by `overhang_id`), NOT the stored
`OverhangSpec.pivot` (base-frame, goes stale under cluster transforms). Color =
overhang strand color (vertex colors, one merged mesh). EPS 0.08 nm proud.
Why raycast: the rendered hull varies per axial segment (trim/filter/per-segment),
so a computed face plane can't match it.
