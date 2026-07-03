"""
API layer — on-screen display geometry (atomistic + molecular surface).

These routes feed the Three.js renderer as JSON for the all-atom and
molecular-surface representations:

  - ``GET  /design/atomistic``       — heavy-atom all-atom model (atoms + bonds).
  - ``GET  /design/surface``         — triangulated molecular surface of the
    whole design.
  - ``POST /design/surface/region``  — molecular surface over only the columns
    covered by a set of representation segments (the per-region SURFACE rep).

One reason to change: the *render-feed* JSON these emit for the atomistic /
surface display. They share the surface *pipeline* (build_atomistic_model →
compute_surface → smooth_mesh) with the printable-mesh exports
(``/design/export/stl`` / ``/design/export/3mf`` in
``routes_export_3dprint.py``) but not the reason-to-change: render feed vs
downloadable print file.  See ``memory/project_stl_export.md`` /
``memory/project_mixed_representation.md``.

URLs are unchanged from their previous home in crud.py. Mounting is done in
``backend/api/main.py`` via ``app.include_router(...)``.
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter
from pydantic import BaseModel

from backend.api import state as design_state
from backend.core.flexible_display import flexible_segment_atomistic_frame_overrides
from backend.core.models import RepresentationSegment

router = APIRouter()


class SurfaceRegionRequest(BaseModel):
    """Compute a molecular surface over ONLY the columns covered by `segments`
    (the surface-rep regions). Stateless; same knobs as GET /design/surface."""
    segments: List[RepresentationSegment]
    color_mode:     str   = "strand"
    grid_spacing:   float = 0.20
    probe_radius:   float = 0.28
    radius_inflate: float = 1.30
    smooth:         int   = 15


# ── Atomistic + molecular-surface display geometry ────────────────────────────


def _flexible_display_override(design):
    override = flexible_segment_atomistic_frame_overrides(design)
    return override or None


@router.get("/design/atomistic")
def get_atomistic() -> dict:
    """
    Return the heavy-atom all-atom model for the atomistic Three.js renderer.

    Response: { atoms: [...], bonds: [[i,j], ...], element_meta: {...} }
    Each atom dict contains: serial, name, element, residue, chain_id,
    seq_num, x, y, z (nm), strand_id, helix_id, bp_index, direction,
    is_modified.

    The −32° helical phase offset (aligning the all-atom backbone groove with the
    NADOC CG model) is baked into build_atomistic_model via _ATOMISTIC_PHASE_OFFSET_RAD.
    """
    from backend.core.atomistic import build_atomistic_model, atomistic_to_json, merge_models

    design = design_state.get_or_404()
    nuc_frame_override = _flexible_display_override(design)

    pdb_model = design_state.get_pdb_atomistic()

    if pdb_model is not None:
        pdb_helix_ids = {a.helix_id for a in pdb_model.atoms}
        all_helix_ids = {h.id for h in design.helices}
        template_helix_ids = all_helix_ids - pdb_helix_ids

        if not template_helix_ids:
            return atomistic_to_json(pdb_model)

        template_model = build_atomistic_model(
            design,
            exclude_helix_ids=pdb_helix_ids,
            nuc_frame_override=nuc_frame_override,
        )
        return atomistic_to_json(merge_models(pdb_model, template_model))

    return atomistic_to_json(build_atomistic_model(
        design,
        nuc_frame_override=nuc_frame_override,
    ))


@router.get("/design/surface")
def get_surface(
    color_mode:     str   = "strand",
    grid_spacing:   float = 0.20,
    probe_radius:   float = 0.28,
    radius_inflate: float = 1.30,
    smooth:         int   = 15,
) -> dict:
    """
    Compute and return a triangulated molecular surface mesh.

    The surface is the all-atom model rasterised onto a voxel grid with atom
    radii scaled by ``1.2 × radius_inflate``, followed by a morphological
    closing of radius ``probe_radius`` and Taubin smoothing (``smooth`` iters).
    Defaults match the 3D-print STL export so the on-screen surface is
    visibly de-faceted and feature-fattened by default.  Pass
    ``radius_inflate=1.0&smooth=0`` to recover the raw molecular surface.

    Query params:
      color_mode      — "strand" (per-vertex strand colours) or "uniform".
      grid_spacing    — voxel size in nm (default 0.20; lower = finer).
      probe_radius    — groove-fill radius in nm (default 0.28).
      radius_inflate  — extra atom-radius fattening (default 1.30; 1.0 = bare).
      smooth          — Taubin smoothing iterations (default 15; 0 = off).

    Response: {
      vertices: [x,y,z, ...],      flat float array, nm coords
      faces:    [i,j,k, ...],      flat int array
      vertex_colors: [r,g,b, ...], flat float 0-1, or null for uniform mode
      stats: { n_verts, n_faces, compute_ms }
    }
    """
    import time
    from backend.core.atomistic import build_atomistic_model
    from backend.core.surface import compute_surface, smooth_mesh, surface_to_json

    design = design_state.get_or_404()
    model = build_atomistic_model(
        design,
        nuc_frame_override=_flexible_display_override(design),
    )

    t0 = time.perf_counter()
    mesh = compute_surface(
        model.atoms,
        grid_spacing=grid_spacing,
        probe_radius=probe_radius,
        radius_scale=1.2 * radius_inflate,
    )
    mesh = smooth_mesh(mesh, iterations=smooth)
    t_ms = (time.perf_counter() - t0) * 1000.0

    return surface_to_json(mesh, design, color_mode=color_mode, t_ms=t_ms)


@router.post("/design/surface/region")
def get_region_surface(body: SurfaceRegionRequest) -> dict:
    """Molecular surface over ONLY the duplex columns covered by ``segments`` —
    used by the per-region SURFACE representation (mixed rep). Stateless: reads
    the active design, filters the all-atom model to the region's nucleotides,
    and returns the same payload shape as GET /design/surface. An empty
    ``segments`` list returns a zero-vertex mesh so the client can clear cleanly.
    """
    import time
    from backend.core.atomistic import build_atomistic_model
    from backend.core.surface import compute_surface, smooth_mesh, surface_to_json

    design = design_state.get_or_404()

    colset: set[tuple[str, int]] = set()
    for seg in body.segments:
        lo, hi = min(seg.bp_start, seg.bp_end), max(seg.bp_start, seg.bp_end)
        for bp in range(lo, hi + 1):
            colset.add((seg.helix_id, bp))

    if not colset:
        return {"vertices": [], "faces": [], "vertex_colors": None,
                "stats": {"n_verts": 0, "n_faces": 0, "compute_ms": 0.0}}

    model = build_atomistic_model(
        design,
        nuc_frame_override=_flexible_display_override(design),
    )
    atoms = [a for a in model.atoms if (a.helix_id, a.bp_index) in colset]

    t0 = time.perf_counter()
    mesh = compute_surface(
        atoms,
        grid_spacing=body.grid_spacing,
        probe_radius=body.probe_radius,
        radius_scale=1.2 * body.radius_inflate,
    )
    mesh = smooth_mesh(mesh, iterations=body.smooth)
    t_ms = (time.perf_counter() - t0) * 1000.0

    return surface_to_json(mesh, design, color_mode=body.color_mode, t_ms=t_ms)
