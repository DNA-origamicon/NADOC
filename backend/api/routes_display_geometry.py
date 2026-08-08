"""
API layer — on-screen display geometry (atomistic + molecular surface).

These routes feed the Three.js renderer as JSON for the all-atom and
molecular-surface representations:

  - ``GET  /design/atomistic``       — heavy-atom all-atom model (atoms + bonds).
  - ``GET  /design/surface``         — triangulated molecular surface of the
    whole design.
  - ``POST /design/surface/region``  — molecular surface over only the columns
    covered by a set of representation segments (the per-region SURFACE rep).
  - ``GET  /design/clashes``         — design-layer steric-clash report over the
    POSED (cluster/deformation-applied) backbone beads.

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
    color_mode: str = "strand"
    grid_spacing: float = 0.20
    probe_radius: float = 0.28
    radius_inflate: float = 1.30
    smooth: int = 15


# ── Atomistic + molecular-surface display geometry ────────────────────────────


def _flexible_display_override(design):
    override = flexible_segment_atomistic_frame_overrides(design)
    return override or None


@router.get("/design/atomistic")
def get_atomistic(
    seed_lattice_nm: str | None = None, measured_positioning: bool = True
) -> dict:
    """
    Return the heavy-atom all-atom model for the atomistic Three.js renderer.

    Response: { atoms: [...], bonds: [[i,j], ...], element_meta: {...} }
    Each atom dict contains: serial, name, element, residue, chain_id,
    seq_num, x, y, z (nm), strand_id, helix_id, bp_index, direction,
    is_modified.

    The −32° helical phase offset (aligning the all-atom backbone groove with the
    NADOC CG model) is baked into build_atomistic_model via _ATOMISTIC_PHASE_OFFSET_RAD.

    ``measured_positioning`` defaults TRUE and is NADOC's native geometry: nucleotide
    templates re-extracted from free NAMD, both strands measured separately in one
    shared base-pair frame (``core/measured_atomistic.py``).  Pass false to get the
    1ZEW-derived templates back for comparison — that is what Help ▸ New Positioning
    switches off.  Topology and the geometric layer are untouched either way.

    ``seed_lattice_nm`` switches this to **MD SEED** mode — the t=0, pre-minimisation
    coordinates the simulation would actually start from, for EVERY atom:

      * exact L-BFGS-B phosphodiester linkers instead of the display build's cheap
        interpolation (``fast_bridges``), which moves the ~1.5% linker atoms by up
        to 2.4 A at junctions — the very atoms a junction clash is made of;
      * no flexible-display frame override, which is a viewer affordance the seed
        does not have;
      * optional lattice pre-expansion — ``"auto"`` for the measured relaxed
        spacing of this design's largest extra-base count, or a float in nm.

    Absent = today's display build, unchanged. Values match ``seed_lattice_nm`` on
    ``POST /md/jobs``, so what you see is what a job would build. Slower (~27 s on
    a 60-crossover design) but cached.

    Refused when a PDB-imported model is present: those atoms are measured
    coordinates that no lattice scale applies to, so a seed built around them
    would silently mix two frames.
    """
    from backend.core.atomistic import (
        build_atomistic_model,
        atomistic_to_json,
        merge_models,
    )

    design = design_state.get_or_404()
    nuc_frame_override = _flexible_display_override(design)

    pdb_model = design_state.get_pdb_atomistic()

    if seed_lattice_nm is not None:
        from fastapi import HTTPException

        from backend.core.atomistic_cache import build_atomistic_model_cached
        from backend.core.lattice import scale_helix_spacing
        from backend.core.md_protocols import _resolve_seed_lattice_nm

        if pdb_model is not None:
            raise HTTPException(
                status_code=409,
                detail="Seed view is unavailable for a PDB-imported design: its atoms are "
                "measured coordinates, so scaling the lattice around them would mix "
                "two frames.",
            )
        resolved = _resolve_seed_lattice_nm(design, seed_lattice_nm)
        seed_design = (
            scale_helix_spacing(design, resolved) if resolved is not None else design
        )
        out = atomistic_to_json(build_atomistic_model_cached(seed_design))
        out["seed"] = True
        out["lattice_nm"] = resolved
        return out

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
            fast_bridges=True,  # display renderer: cheap interpolated linkers (6× faster on large designs)
            measured_positioning=measured_positioning,
        )
        return atomistic_to_json(merge_models(pdb_model, template_model))

    return atomistic_to_json(
        build_atomistic_model(
            design,
            nuc_frame_override=nuc_frame_override,
            fast_bridges=True,  # display renderer: cheap interpolated linkers (6× faster on large designs)
            measured_positioning=measured_positioning,
        )
    )


@router.get("/design/clashes")
def get_clashes(
    threshold_nm: float = 0.65,
    designed_margin_nm: float = 2.0,
) -> dict:
    """
    Return the design-layer steric-clash report for the active design.

    Backbone beads are placed in their POSED positions (cluster poses +
    bend/twist deformations applied).  A pair is a clash when it overlaps now
    (``< threshold_nm``) but was NOT close in the straight, un-posed design
    (``> designed_margin_nm``) — i.e. the collision came from folding, not from
    designed packing (WC partners, covalent neighbours, crossovers, tight
    lattice packing are all close straight and are therefore excluded).

    Read-only — never mutates topology.  This is the no-simulation counterpart
    to the MD-time NAMD declash.

    Response: {
      clashes: [ { a: {helix_id, bp_index, direction, position:[x,y,z]},
                   b: {...}, distance_nm }, ... ],   nearest first
      count: int,
      threshold_nm: float,
      designed_margin_nm: float,
    }
    """
    from backend.core.clash import clash_report

    design = design_state.get_or_404()
    report = clash_report(
        design,
        threshold_nm=threshold_nm,
        designed_margin_nm=designed_margin_nm,
    )
    return report.to_dict()


@router.get("/design/surface")
def get_surface(
    color_mode: str = "strand",
    grid_spacing: float = 0.20,
    probe_radius: float = 0.28,
    radius_inflate: float = 1.30,
    smooth: int = 15,
    detail: str = "coarse",
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
    from backend.core.surface import surface_to_json

    design = design_state.get_or_404()
    t0 = time.perf_counter()
    mesh = _build_design_surface_mesh(
        design, grid_spacing, probe_radius, radius_inflate, smooth, detail
    )
    t_ms = (time.perf_counter() - t0) * 1000.0

    return surface_to_json(mesh, design, color_mode=color_mode, t_ms=t_ms)


@router.get("/design/surface-bin")
def get_surface_bin(
    color_mode: str = "strand",
    grid_spacing: float = 0.20,
    probe_radius: float = 0.28,
    radius_inflate: float = 1.30,
    smooth: int = 15,
    detail: str = "coarse",
):
    """Binary counterpart of ``GET /design/surface`` — the SAME mesh packed by
    ``oxdna_health.pack_surface_bin`` into a compact little-endian blob (~2× smaller AND no
    million-number ``JSON.parse`` on the client; decode with ``scene/surface_bin.js``).  The
    strand-index table rides along so the design surface still recolours client-side (mirrors
    the sim overlay's ``display-surface-bin``).  Empty 16-byte header (n_verts=0) = empty."""
    from fastapi import Response
    from backend.core.surface import surface_to_json
    from backend.core.oxdna_health import pack_surface_bin

    design = design_state.get_or_404()
    mesh = _build_design_surface_mesh(
        design, grid_spacing, probe_radius, radius_inflate, smooth, detail
    )
    data = surface_to_json(mesh, design, color_mode=color_mode)
    return Response(
        content=pack_surface_bin(data), media_type="application/octet-stream"
    )


def _build_design_surface_mesh(
    design, grid_spacing, probe_radius, radius_inflate, smooth, detail
):
    """Build the design's molecular surface mesh — the shared body of ``get_surface`` and
    ``get_surface_bin`` (JSON vs binary transfer).  ``detail='coarse'`` (default) rasterises
    ~2 CG spheres/nucleotide from design geometry (no all-atom rebuild — ~3× faster, envelope
    within ~2.8 Å); ``'fine'`` builds the exact all-atom model."""
    from backend.core.surface import (
        compute_surface,
        compute_surface_from_cloud,
        smooth_mesh,
        adaptive_grid_spacing,
        adaptive_grid_spacing_arr,
        cg_surface_mesh,
        make_cg_bead,
    )

    if detail == "chimerax":
        return _build_chimerax_surface(design)
    if detail == "coarse":
        from backend.core.design_geometry import _geometry_for_design

        beads = []
        for g in _geometry_for_design(design, junction_balance=True):
            for _k in ("backbone_position", "base_position"):
                p = g.get(_k)
                if p is None:
                    continue
                beads.append(
                    make_cg_bead(
                        p[0],
                        p[1],
                        p[2],
                        strand_id=g.get("strand_id", ""),
                        helix_id=g.get("helix_id", ""),
                        bp_index=int(g.get("bp_index", 0)),
                        direction=g.get("direction", "FORWARD"),
                    )
                )
        return cg_surface_mesh(
            beads, grid_spacing=grid_spacing, probe_radius=probe_radius, smooth=smooth
        )

    # FINE (all-atom) surface.  The vectorised point cloud (surface_atom_cloud) reproduces the
    # full fast_bridges build BYTE-FOR-BYTE on designs it covers (VoltronCore build 7 s → 0.8 s)
    # — but it omits flexible-ssDNA frames, extra-base crossover atoms, and extension tails, so
    # those designs fall back to the exact Atom-object build (correctness over speed).
    if _can_use_surface_cloud(design):
        from backend.core.atomistic import surface_atom_cloud

        pos, radii, sids, nucs = surface_atom_cloud(design)
        gs = adaptive_grid_spacing_arr(pos, grid_spacing)
        mesh = compute_surface_from_cloud(
            pos,
            radii,
            sids,
            grid_spacing=gs,
            probe_radius=probe_radius,
            radius_scale=1.2 * radius_inflate,
            nuc_ids=nucs,
        )
        return smooth_mesh(mesh, iterations=smooth)

    from backend.core.atomistic import build_atomistic_model

    # DISPLAY surface: cheap interpolated phosphate bridges (fast_bridges — 6× faster
    # build; the VdW envelope is unaffected) + adaptive grid coarsening.
    model = build_atomistic_model(
        design, nuc_frame_override=_flexible_display_override(design), fast_bridges=True
    )
    mesh = compute_surface(
        model.atoms,
        grid_spacing=adaptive_grid_spacing(model.atoms, grid_spacing),
        probe_radius=probe_radius,
        radius_scale=1.2 * radius_inflate,
    )
    return smooth_mesh(mesh, iterations=smooth)


def _build_chimerax_surface(design):
    """EXPERIMENTAL 'ChimeraX quality' surface (``detail='chimerax'``).  Mimics ChimeraX's
    default molecular surface on two axes: (1) a FINE ~0.5 Å grid + 1.4 Å water probe + true
    VdW radii (vs the display path's coarse ~3 Å grid that blurs the helical grooves), and
    (2) a SEPARATE surface PER STRAND (like ChimeraX's per-chain surfaces), so complementary
    strands are distinct geometry with a real solvent gap between them instead of one fused
    blob with a jagged colour seam.  See ``surface.compute_split_surfaces_from_cloud`` +
    ``surface.CHIMERAX_*``.  EXPENSIVE (one marching-cubes pass per strand) but voxel-capped."""
    import numpy as np
    from backend.core.surface import compute_split_surfaces_from_cloud, _nuc_key

    if _can_use_surface_cloud(design):
        from backend.core.atomistic import surface_atom_cloud

        pos, radii, sids, nucs = surface_atom_cloud(design)
    else:
        # Extra-base crossovers / flexible ssDNA / extension tails → exact Atom build (includes
        # every atom the cloud omits; the extra-base atoms carry their crossover's strand id).
        from backend.core.atomistic import build_atomistic_model, VDW_RADIUS

        model = build_atomistic_model(
            design,
            nuc_frame_override=_flexible_display_override(design),
            fast_bridges=True,
        )
        pos = np.array([[a.x, a.y, a.z] for a in model.atoms], dtype=float)
        radii = np.array(
            [VDW_RADIUS.get(a.element, VDW_RADIUS["C"]) for a in model.atoms],
            dtype=float,
        )
        sids = [a.strand_id or "" for a in model.atoms]
        nucs = [_nuc_key(a) for a in model.atoms]
    return compute_split_surfaces_from_cloud(pos, radii, sids, nuc_ids=nucs)


def _can_use_surface_cloud(design) -> bool:
    """The vectorised ``surface_atom_cloud`` fast path reproduces the exact fine surface only
    for designs without flexible-ssDNA display frames, extra-base crossovers, or 5'/3' extension
    tails (it stamps the standard nucleotide templates + phosphate bridges).  Those designs fall
    back to the exact Atom-object build — no speedup, but no envelope regression."""
    if getattr(design, "flexible_connections", None):
        return False
    if getattr(design, "extensions", None):
        return False
    if any(getattr(xo, "extra_bases", None) for xo in design.crossovers):
        return False
    return True


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
        return {
            "vertices": [],
            "faces": [],
            "vertex_colors": None,
            "stats": {"n_verts": 0, "n_faces": 0, "compute_ms": 0.0},
        }

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
