"""
Molecular surface computation — VdW and Solvent Excluded Surface (SES).

Both surfaces are computed using a grid-based (voxel) approach:

VdW surface
    Union of atomic Van der Waals spheres triangulated via marching cubes on
    the binary occupancy grid.  Each atom type is rasterised by placing its
    centre in the nearest voxel and then binary-dilating by its VdW radius.

SES (Connolly surface)
    Morphological closing of the VdW volume by the probe radius:
        ses_vol = erode(dilate(vdw_vol, r_probe), r_probe)
    This fills in molecular grooves narrower than the probe diameter (≈1.4 Å
    for water) and smooths reentrant regions, matching the visual appearance
    of ChimeraX/VMD Connolly surfaces.  The result is triangulated via
    marching cubes on the binary closed volume.

Grid resolution
    The default 0.20 nm grid spacing gives voxel-resolution staircase
    artefacts of ≤ 2 Å per step, which are invisible at the scale of a DNA
    origami structure (10–100 nm).  Reducing grid_spacing to 0.10 nm halves
    the artefact at ~8× compute cost.

Vertex colours are assigned by nearest-atom KD-tree lookup; the strand
palette matches helix_renderer.js exactly (first-appearance ordering).
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

import numpy as np
from scipy.ndimage import binary_dilation, binary_erosion
from scipy.spatial import cKDTree
from skimage.measure import marching_cubes

from backend.core.atomistic import Atom, VDW_RADIUS
from backend.core.models import Design, StrandType


# ── Strand colour palette (mirrors helix_renderer.js exactly) ────────────────

_SCAFFOLD_COLOR = (0x29, 0xB6, 0xF6)   # sky blue, normalised below
_STAPLE_PALETTE_HEX = [
    0xFF6B6B, 0xFFD93D, 0x6BCB77, 0xF9844A, 0xA29BFE, 0xFF9FF3,
    0x00CEC9, 0xE17055, 0x74B9FF, 0x55EFC4, 0xFDCB6E, 0xD63031,
]
_UNASSIGNED_COLOR = (0x44, 0x55, 0x66)

# Convert palette to (R,G,B) tuples in 0-1 range once
_SCAFFOLD_RGB  = tuple(c / 255.0 for c in _SCAFFOLD_COLOR)
_PALETTE_RGB   = [((h >> 16) / 255.0, ((h >> 8) & 0xFF) / 255.0, (h & 0xFF) / 255.0)
                  for h in _STAPLE_PALETTE_HEX]
_UNASSIGNED_RGB = tuple(c / 255.0 for c in _UNASSIGNED_COLOR)


# ── Result type ───────────────────────────────────────────────────────────────

@dataclass
class SurfaceMesh:
    vertices: np.ndarray          # (N, 3) float32, world coords (nm)
    faces: np.ndarray             # (M, 3) int32, triangle indices
    vertex_strand_ids: list[str]  # length N; empty string = unassigned


# ── Internal helpers ──────────────────────────────────────────────────────────

def _sphere_struct(radius_voxels: float) -> np.ndarray:
    """Spherical binary structuring element with given radius in voxels."""
    r = max(1, int(math.ceil(radius_voxels)))
    x, y, z = np.mgrid[-r:r + 1, -r:r + 1, -r:r + 1]
    return (x ** 2 + y ** 2 + z ** 2) <= radius_voxels ** 2


def _build_occupancy_grid(
    atoms: list[Atom],
    vdw_override: dict[str, float] | None,
    grid_spacing: float,
    padding: float,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Build a boolean occupancy grid (True = inside a VdW sphere).

    Strategy: for each unique element type, mark the single voxel nearest to
    each atom centre, then binary-dilate that sparse grid by the element's VdW
    radius.  The union of all four element grids is returned.  This approach
    requires only 4 dilation operations regardless of atom count and is much
    faster than per-atom sphere rasterisation in pure Python.
    """
    radii = vdw_override if vdw_override is not None else VDW_RADIUS
    max_r = max(radii.values())

    positions = np.array([[a.x, a.y, a.z] for a in atoms], dtype=np.float64)
    bbox_min = positions.min(axis=0) - (max_r + padding)
    bbox_max = positions.max(axis=0) + (max_r + padding)

    shape = tuple((np.ceil((bbox_max - bbox_min) / grid_spacing)).astype(int) + 1)

    final_grid = np.zeros(shape, dtype=bool)
    elements = np.array([a.element for a in atoms])

    for elem, elem_r in radii.items():
        mask = elements == elem
        if not mask.any():
            continue

        elem_pos = positions[mask]
        elem_grid = np.zeros(shape, dtype=bool)

        # Map atom centres to nearest voxel indices
        idx = np.round((elem_pos - bbox_min) / grid_spacing).astype(int)
        idx = np.clip(idx, 0, np.array(shape) - 1)
        elem_grid[idx[:, 0], idx[:, 1], idx[:, 2]] = True

        # Dilate by VdW radius
        n_voxels = elem_r / grid_spacing
        struct = _sphere_struct(n_voxels)
        final_grid |= binary_dilation(elem_grid, structure=struct)

    return final_grid, bbox_min


def _assign_vertex_strand_ids(
    verts: np.ndarray,
    atoms: list[Atom],
) -> list[str]:
    """Nearest-atom KD-tree lookup → per-vertex strand IDs."""
    positions = np.array([[a.x, a.y, a.z] for a in atoms], dtype=np.float64)
    tree = cKDTree(positions)
    _, nearest_idx = tree.query(verts, workers=-1)
    return [atoms[int(i)].strand_id or "" for i in nearest_idx]


# ── Public surface computation ────────────────────────────────────────────────

def _marching_cubes_safe(
    grid: np.ndarray,
    level: float,
    grid_spacing: float,
    bbox_min: np.ndarray,
    atoms: list[Atom],
) -> SurfaceMesh:
    """Run marching cubes and return a SurfaceMesh; returns empty mesh if no isosurface found."""
    if grid.max() <= level or grid.min() >= level:
        return SurfaceMesh(
            vertices=np.empty((0, 3), dtype=np.float32),
            faces=np.empty((0, 3), dtype=np.int32),
            vertex_strand_ids=[],
        )
    verts, faces, _, _ = marching_cubes(grid.astype(np.float32), level=level, allow_degenerate=False)
    verts = (verts * grid_spacing + bbox_min).astype(np.float32)
    faces = faces.astype(np.int32)
    strand_ids = _assign_vertex_strand_ids(verts, atoms)
    return SurfaceMesh(vertices=verts, faces=faces, vertex_strand_ids=strand_ids)


def compute_surface(
    atoms: list[Atom],
    grid_spacing: float = 0.20,
    probe_radius: float = 0.28,
) -> SurfaceMesh:
    """
    Unified molecular surface via morphological closing on scaled VdW spheres.

    Atom radii are expanded by 1.2× before rasterisation; the probe radius
    then controls the degree of groove-filling:

      probe_radius = 0   → tight surface hugging the expanded VdW spheres
      probe_radius = 0.28 (default) → smooth envelope with grooves ≤ 0.56 nm
                                       filled in (≈ 2× water molecule radius)

    Algorithm:
        scaled_vdw = build_occupancy_grid(atoms, radii × 1.2)
        surface_vol = erode(dilate(scaled_vdw, probe_radius), probe_radius)
        marching_cubes(surface_vol, level=0.5)

    Parameters
    ----------
    atoms :
        All-atom model atoms (from build_atomistic_model).
    grid_spacing :
        Voxel size in nm.  Default 0.20 nm.
    probe_radius :
        Controls smoothness.  0 = tight VdW-like; larger = smoother envelope.
        Default 0.28 nm.
    """
    scaled_radii = {elem: r * 1.2 for elem, r in VDW_RADIUS.items()}
    grid, bbox_min = _build_occupancy_grid(atoms, scaled_radii, grid_spacing, padding=0.5 + probe_radius)

    if probe_radius > 0:
        probe_vox = probe_radius / grid_spacing
        struct = _sphere_struct(probe_vox)
        dilated = binary_dilation(grid, structure=struct)
        grid = binary_erosion(dilated, structure=struct)

    return _marching_cubes_safe(grid, 0.5, grid_spacing, bbox_min, atoms)


# ── JSON serialisation ────────────────────────────────────────────────────────

def surface_to_json(
    mesh: SurfaceMesh,
    design: Design,
    color_mode: str = "strand",
    t_ms: float = 0.0,
) -> dict:
    """
    Serialise a SurfaceMesh to a JSON-safe dict for the frontend.

    Vertex data is flattened for compact transmission:
        vertices: [x0,y0,z0, x1,y1,z1, ...]   (float, nm)
        faces:    [i0,j0,k0, i1,j1,k1, ...]   (int)
        vertex_colors: [r0,g0,b0, ...]         (float 0-1) or null for uniform

    Parameters
    ----------
    color_mode : 'strand' | 'uniform'
    t_ms : computation time in milliseconds (informational).
    """
    # Build strand → RGB lookup (first-appearance order, matching helix_renderer.js)
    strand_rgb: dict[str, tuple[float, float, float]] = {}
    palette_idx = 0
    for strand in design.strands:
        if not strand.id:
            continue
        if strand.strand_type == StrandType.SCAFFOLD:
            strand_rgb[strand.id] = _SCAFFOLD_RGB
        elif strand.color:
            # Custom colour saved in design (#RRGGBB)
            h = int(strand.color.lstrip("#"), 16)
            strand_rgb[strand.id] = ((h >> 16) / 255.0, ((h >> 8) & 0xFF) / 255.0, (h & 0xFF) / 255.0)
        else:
            strand_rgb[strand.id] = _PALETTE_RGB[palette_idx % len(_PALETTE_RGB)]
            palette_idx += 1

    verts_flat = mesh.vertices.flatten().tolist()
    faces_flat = mesh.faces.flatten().tolist()

    if color_mode == "strand":
        colors: list[float] = []
        for sid in mesh.vertex_strand_ids:
            rgb = strand_rgb.get(sid, _UNASSIGNED_RGB)
            colors.extend(rgb)
        vertex_colors = colors
    else:
        vertex_colors = None

    # Compact per-vertex strand-id table so the frontend can recolour the
    # surface client-side using the same palette/group/cluster overrides as
    # the bead view.  Sent as (unique_id_list, index_per_vertex) to keep the
    # payload small for large meshes.
    unique_strand_ids: list[str] = []
    sid_index: dict[str, int] = {}
    vertex_strand_idx: list[int] = []
    for sid in mesh.vertex_strand_ids:
        i = sid_index.get(sid)
        if i is None:
            i = len(unique_strand_ids)
            sid_index[sid] = i
            unique_strand_ids.append(sid)
        vertex_strand_idx.append(i)

    return {
        "vertices": verts_flat,
        "faces": faces_flat,
        "vertex_colors": vertex_colors,
        "vertex_strand_index_table": unique_strand_ids,
        "vertex_strand_index": vertex_strand_idx,
        "stats": {
            "n_verts": len(mesh.vertices),
            "n_faces": len(mesh.faces),
            "compute_ms": round(t_ms, 1),
        },
    }
