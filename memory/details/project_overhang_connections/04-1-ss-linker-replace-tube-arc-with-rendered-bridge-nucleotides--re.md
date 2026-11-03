# 1. ss linker: replace tube arc with rendered bridge nucleotides — RESOLVED 2026-05-11 — supporting detail

[Topic head](../../project_overhang_connections.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

### 1. ss linker: replace tube arc with rendered bridge nucleotides — RESOLVED 2026-05-11

The polarity-rule blocker (originally listed here) is **resolved** as of 2026-05-02 — `_check_linker_compatibility` now uses the unified Watson-Crick test (see "Validation rules" above). Both `_make_complement_domain` ordering and bridge directions are computed per-side from `comp_first`, so the ds atomistic / bond topology is correct on every accepted combo (verified end-to-end across all 16 (end × attach)² combos in `tests/test_overhang_connections.py::test_polarity_rule_accepts_only_physical_combos`).

**Visual upgrade SHIPPED 2026-05-11.** ss bridges now render as the FJC bead chain from the pre-baked slab+SAW lookup table, picked by the user via the interactive R_ee×Rg config modal. Pre-relax draws a Bezier fallback arc; post-relax draws N beads positioned by `transform_to_chord` on the selected bin's representative shape. See [project_ssdna_linker_relax](../../project_ssdna_linker_relax.md) for the full pipeline, schema, and gotchas.

**For ds:** the bead+slab+cone duplex from `_makeDsLinkerMeshes` already serves; future improvement would be a real helix layout for the bridge so atomistic + CG share one source of truth (atomistic already aligns now via `position_linker_virtual_helices` + the deformed-anchor `_linker_anchor_nuc` fix).
