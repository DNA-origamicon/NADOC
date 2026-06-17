"""
API layer — 3D-printing surface exports (extracted from crud.py).

This module hosts the routes that emit a *printable 3D mesh* of the molecular
surface for slicers / 3D printers:

  - ``/design/export/stl``  — binary STL of the (single) molecular surface,
    nm→mm auto-scaled to a target bed dimension.
  - ``/design/export/3mf``  — manifold multi-colour 3MF: each strand-colour
    group re-surfaced as its own closed, watertight solid (per-filament parts).

One reason to change: the printable-mesh file formats NADOC emits for 3D
printing (STL / 3MF). The on-screen *display* surface (``/design/surface`` and
``/design/surface/region``, which feed the Three.js renderer as JSON) and the
atomistic display route are a different concern and stay in crud.py — they share
the surface *pipeline* (build_atomistic_model → compute_surface → smooth_mesh)
but not the reason-to-change (render feed vs downloadable print file). See
``memory/project_stl_export.md``.

The shared export resolver ``_design_for_export`` stays in crud.py (used across
crud.py + assembly.py + core) and is imported back here — same shared-kernel
convention as ``routes_sequences.py`` / ``routes_export_structure.py``.

URLs are unchanged from their previous home in crud.py. Mounting is done in
``backend/api/main.py`` via ``app.include_router(...)``.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

# Shared export resolver used by many routes across crud.py + assembly.py + core;
# it stays in crud.py and is imported back here (same convention as
# routes_sequences.py / routes_export_structure.py).
from backend.api.crud import _design_for_export

router = APIRouter()


# ── 3D-printing surface exports (STL / 3MF) ───────────────────────────────────


@router.get("/design/export/stl")
def export_surface_stl(
    grid_spacing:    float = 0.20,
    probe_radius:    float = 0.28,
    target_mm:       float = 200.0,
    radius_inflate:  float = 1.30,
    smooth:          int   = 15,
) -> Response:
    """Export the molecular surface as a binary STL for 3D printing.

    Builds the same marching-cubes surface as the 'surface' representation,
    inflates it (atoms ×radius_inflate over the displayed surface) so thin
    features survive printing, applies Taubin smoothing to relax the voxel
    staircase, then auto-scales it (nm → mm) so the longest bounding-box
    dimension equals target_mm (default 200 mm — a typical consumer printer
    bed).  STL is unitless; slicers interpret the coordinates as millimetres.

    Query params:
      grid_spacing    — surface voxel size in nm (default 0.20; lower = finer).
      probe_radius    — surface smoothness in nm (default 0.28).
      target_mm       — longest printed dimension in mm (default 200).
      radius_inflate  — fattening over the displayed surface (default 1.30 =
                        +30%; the printed envelope uses atoms at 1.2 × this).
      smooth          — Taubin smoothing iterations (default 15; 0 = off).
    """
    from backend.core.atomistic import build_atomistic_model
    from backend.core.stl_export import auto_scale, export_stl
    from backend.core.surface import compute_surface, smooth_mesh

    design = _design_for_export()
    model  = build_atomistic_model(design)
    mesh   = compute_surface(
        model.atoms,
        grid_spacing=grid_spacing,
        probe_radius=probe_radius,
        radius_scale=1.2 * radius_inflate,
    )
    if mesh.faces.shape[0] == 0:
        raise HTTPException(422, detail="Surface mesh is empty; nothing to export.")

    mesh = smooth_mesh(mesh, iterations=smooth)

    name = (design.metadata.name or "design").replace(" ", "_")
    stl  = export_stl(mesh, scale=auto_scale(mesh, target_mm=target_mm), name=name)
    return Response(
        content     = stl,
        media_type  = "model/stl",
        headers     = {"Content-Disposition": f'attachment; filename="{name}.stl"'},
    )


@router.get("/design/export/3mf")
def export_surface_3mf(
    grid_spacing:    float = 0.20,
    probe_radius:    float = 0.28,
    target_mm:       float = 200.0,
    radius_inflate:  float = 1.30,
    smooth:          int   = 15,
    staple_colors:   int   = 3,
) -> Response:
    """Export the molecular surface as a manifold multi-colour 3MF for 3D printing.

    Same surface pipeline as the STL export (same inflate + Taubin smooth + nm→mm
    auto-scale), but emits each colour as its own **closed, watertight** solid:
    every occupied surface voxel is labelled by its nearest strand's colour and
    re-surfaced per colour, so the parts share coincident interface walls and the
    file satisfies the 3MF watertight requirement slicers enforce (no open
    seams).  The parts are components of one assembly object so they stay aligned;
    Bambu Studio / OrcaSlicer / PrusaSlicer map each to a filament slot.

    Staples are map-coloured into ``staple_colors`` sets (default 3 → 4 groups
    total with the scaffold) so that staples whose surface regions touch get
    different colours.  The response header ``X-NADOC-Coloring`` reports the
    staple count and any unavoidable same-colour borders.

    Query params mirror ``/design/export/stl`` plus ``staple_colors`` (1-3).
    """
    from backend.core.atomistic import build_atomistic_model
    from backend.core.surface import compute_colored_surfaces, compute_surface, smooth_mesh
    from backend.core.threemf_export import (
        auto_scale,
        compute_staple_coloring,
        export_3mf_parts,
    )

    design = _design_for_export()
    model  = build_atomistic_model(design)
    radius_scale = 1.2 * radius_inflate

    # 1. One smoothed surface drives the staple map-colouring (which staples
    #    touch on the surface → different colours).
    mesh = compute_surface(
        model.atoms,
        grid_spacing=grid_spacing,
        probe_radius=probe_radius,
        radius_scale=radius_scale,
    )
    if mesh.faces.shape[0] == 0:
        raise HTTPException(422, detail="Surface mesh is empty; nothing to export.")
    mesh = smooth_mesh(mesh, iterations=smooth)

    strand_to_group, names, colors, stats = compute_staple_coloring(
        mesh, design, n_staple_colors=staple_colors
    )

    # 2. Re-surface each colour group as its own closed solid (shared walls).
    parts = compute_colored_surfaces(
        model.atoms,
        strand_to_group,
        n_groups=len(names),
        grid_spacing=grid_spacing,
        probe_radius=probe_radius,
        radius_scale=radius_scale,
        smooth=smooth,
    )

    # Scale by the same factor the single surface would have used (so size and
    # placement match the STL export exactly).
    scale = auto_scale(mesh, target_mm=target_mm)
    part_specs = [
        (parts[g], names[g], colors[g])
        for g in range(len(names))
        if parts[g] is not None
    ]
    name = (design.metadata.name or "design").replace(" ", "_")
    data = export_3mf_parts(part_specs, scale=scale, name=name)
    return Response(
        content     = data,
        media_type  = "model/3mf",
        headers     = {
            "Content-Disposition": f'attachment; filename="{name}.3mf"',
            "X-NADOC-Coloring": (
                f"{len(colors) - 1} staple colors, {stats['n_staples']} staples, "
                f"{stats['conflicts']} adjacent same-color"
            ),
            "Access-Control-Expose-Headers": "X-NADOC-Coloring",
        },
    )
