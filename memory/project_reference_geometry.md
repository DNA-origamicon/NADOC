---
name: reference-geometry
description: Per-strand is_reference flag — inactive translucent backdrop strands that auto-features ignore and exports/validation exclude. Shipped 2026-05-23.
metadata: 
  node_type: memory
  type: project
  originSessionId: 01eb753c-9ca3-4aad-8714-645b7751981c
---

# Reference geometry (is_reference flag)

## Topic navigation and current boundaries

Reorganized October 17, 2026. Read the retained contracts here, then only the
matching detail below. Dated results and old handoffs are not new verification
or authorization; current user instructions and `CLAUDE.md` take precedence.

<a id="helical-axis-lines-toggle-2026-07-16-out-of-session-work"></a>
- [Helical Axis Lines toggle (2026-07-16, out-of-session work)](details/project_reference_geometry/01-helical-axis-lines-toggle-2026-07-16-out-of-session-work.md#helical-axis-lines-toggle-2026-07-16-out-of-session-work)

## Exclusion architecture (two patterns — decided deliberately)
- **Generative loops** (sequences, scaffold_router, seamed/seamless_router, lattice
  autostaple/break/merge + overhang autodetect, crud.auto_crossover): per-site
  `if strand.is_reference: ... continue`, mirroring the existing SCAFFOLD/LINKER skip.
  Loops that REBUILD `design.strands` must append-and-continue reference strands
  (never drop them — that would delete topology). seamless inherits the filter via
  seamed's `_scaffold_coverage`. auto_crossover filters by building `build_strand_ranges`
  from `active_strands()` so reference slots read as uncovered.
- **Passive whole-design consumers** (exports: oxDNA/PDB/PSF/NAMD/GROMACS/caDNAno/
  sequence-CSV): single entry-layer filter `_design_for_export()` in crud.py = a
  `model_copy(strands=active_strands())`. Works because exporters are strand-driven
  (look up positions from per-helix geometry by slot), so dropping reference strands
  omits their nucleotides with no dangling crossovers. **Display/overlay geometry is
  NOT filtered** (get_atomistic, atomistic_batch, /design/geometry) — reference must
  stay VISIBLE. Validator (validator.py) skips reference per-strand (scaffold-count,
  seq-length, loop, domain-ref) but keeps the unique-ID check over all strands.

<a id="assembly-exclusion-2026-05-24"></a>
- [Assembly exclusion (2026-05-24)](details/project_reference_geometry/02-assembly-exclusion-2026-05-24.md#assembly-exclusion-2026-05-24)

## Bend/twist freeze (user chose per-strand freeze on possibly-shared helices)
deformation.py: `_reference_nuc_mask(arrs, helix, design)` (bp-range+direction mask,
same shape as the domain-level cluster mask). Restore straight values for masked rows
BEFORE cluster transforms (so manual cluster moves still apply) in BOTH
`deformed_nucleotide_arrays` (array fast-path, used by /design/geometry) and
`deformed_nucleotide_positions` (object path). `deformed_helix_axes` keeps a straight
axis for a helix whose strands are ALL reference (bare helices still bend).
**Accepted v1 caveat**: on a MIXED helix (active + reference strands), the axis bends
(driven by active strands) while reference beads stay straight → they detach from the
bent stick. Documented in the function docstrings.

<a id="clusters-exclude-reference-geometry-2026-05-23"></a>
- [Clusters exclude reference geometry (2026-05-23)](details/project_reference_geometry/03-clusters-exclude-reference-geometry-2026-05-23.md#clusters-exclude-reference-geometry-2026-05-23)

<a id="route--payload"></a>
- [Route + payload](details/project_reference_geometry/03-clusters-exclude-reference-geometry-2026-05-23.md#route--payload)

## Simulation exclusion (2026-08-11)
Reference geometry is editor-only and never enters a simulation. The canonical
`Design.without_reference_geometry()` projection removes reference strands and
reference-only helices while retaining mixed helices needed by active strands. All job-create
paths (oxDNA, LAMMPS, mrDNA, CanDo, SNUPI, BLADE, and NAMD) use this projection before
counts, geometry, topology, sizing, and setup. Engine preparers apply it again before writing
their frozen `design.json`/engine inputs, providing a defense against internal callers that
bypass an API route. While the expanded Simulations tab is active, reference geometry is
temporarily hidden in the 3D and unfold renderers without changing the user's persistent View
toggle; leaving the tab restores the normal preference.

<a id="loopskip-and-linker-handling-2026-08-11"></a>
- [Loop/skip and linker handling (2026-08-11)](details/project_reference_geometry/04-loopskip-and-linker-handling-2026-08-11.md#loopskip-and-linker-handling-2026-08-11)

<a id="frontend"></a>
- [Frontend](details/project_reference_geometry/04-loopskip-and-linker-handling-2026-08-11.md#frontend)

- [Frontend — continued detail](details/project_reference_geometry/04-loopskip-and-linker-handling-2026-08-11.md)
