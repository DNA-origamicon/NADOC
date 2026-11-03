# Assembly exclusion (2026-05-24) — supporting detail

[Topic head](../../project_reference_geometry.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Assembly exclusion (2026-05-24)
Assembly DISPLAY drops reference strands. Helper `_display_design(design)` in
[backend/api/assembly.py](../../../backend/api/assembly.py) = the same active-strands
`model_copy` as `_design_for_export` (strands only, never helices — no dangling
helix refs; returns input unchanged when no reference strands, zero-alloc common
case). Applied at all 5 assembly display-geometry sites: `get_assembly_geometry`,
`get_instance_geometry`, `seek_instance_features` (CG nucleotides + design dict),
`get_instance_atomistic_geometry`, `get_instance_surface_geometry`. **Never feed
the result into persisted assembly state** — `seek_instance_features` keeps the
unstripped `updated_design` for `_replace_instance_design` and strips only the
shipped geometry/design_dict (topology preserved). The `_GEO_CACHE` only serves
these display endpoints, so caching the stripped form is consistent. Frontend
needed NO change — `buildHelixObjects` renders from `nucleotides`, which the
backend now omits for reference strands. Regression:
`test_assembly_geometry_excludes_reference_strands` in `tests/test_reference_geometry.py`.
