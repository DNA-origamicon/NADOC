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
from dataclasses import dataclass

import numpy as np
from scipy.ndimage import binary_dilation, binary_erosion
from scipy.sparse import csr_matrix
from scipy.spatial import cKDTree
from skimage.measure import marching_cubes

from backend.core.atomistic import Atom, VDW_RADIUS
from backend.core.models import Design


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


# Voxel budget for the adaptive grid.  At 0.20 nm a 14774-nt VoltronCore rasterises to
# ~12M voxels (~4.6 s for occupancy + morphology + marching cubes) and a ~46 MB mesh;
# capping at 3.5M coarsens it to ~0.31 nm — surface compute ~4.6→~2 s and the mesh ~4×
# smaller — with no visible loss at the 10-100 nm scale these origami live at.
_ADAPTIVE_VOXEL_CAP = 3_500_000


def adaptive_grid_spacing(atoms: list[Atom], requested: float,
                          cap_voxels: int = _ADAPTIVE_VOXEL_CAP,
                          max_spacing: float = 0.40) -> float:
    """Coarsen the surface grid for LARGE structures so the voxel count stays bounded.

    Returns ``requested`` (the finest allowed — default 0.20 nm) for small designs; a big
    one is coarsened just enough to keep the grid under ``cap_voxels`` (never coarser than
    ``max_spacing``).  Marching-cubes cost + mesh size scale with the voxel count, so this
    halves both on large origami without a visible change at their 10-100 nm scale."""
    if not atoms:
        return requested
    positions = np.asarray([[a.x, a.y, a.z] for a in atoms], dtype=np.float64)
    return adaptive_grid_spacing_arr(positions, requested, cap_voxels, max_spacing)


def adaptive_grid_spacing_arr(positions: np.ndarray, requested: float,
                              cap_voxels: int = _ADAPTIVE_VOXEL_CAP,
                              max_spacing: float = 0.40) -> float:
    """:func:`adaptive_grid_spacing` for a raw ``(N,3)`` positions array (the point-cloud
    fast path) — same voxel-cap coarsening, no ``Atom`` objects."""
    positions = np.asarray(positions, dtype=np.float64)
    if positions.shape[0] == 0:
        return requested
    span = np.maximum(positions.max(axis=0) - positions.min(axis=0), 1e-6) + 2.0  # + padding slack
    gs_cap = float(np.prod(span) / max(cap_voxels, 1)) ** (1.0 / 3.0)
    return float(min(max_spacing, max(requested, gs_cap)))


def compute_surface(
    atoms: list[Atom],
    grid_spacing: float = 0.20,
    probe_radius: float = 0.28,
    radius_scale: float = 1.2,
) -> SurfaceMesh:
    """
    Unified molecular surface via morphological closing on scaled VdW spheres.

    Atom radii are expanded by ``radius_scale`` (default 1.2×) before
    rasterisation; the probe radius then controls the degree of groove-filling.
    Increasing ``radius_scale`` inflates the whole envelope outward — useful for
    3D printing, where a fatter surface fuses thin features into robust solids.

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
    radius_scale :
        Multiplier applied to each atom's VdW radius before rasterisation.
        Default 1.2× matches ChimeraX/VMD molecular surfaces.  For 3D-print
        export, pass a larger value (e.g. 1.56 ≈ 1.2 × 1.3) to inflate the
        envelope by ~30% so thin features print robustly.
    """
    scaled_radii = {elem: r * radius_scale for elem, r in VDW_RADIUS.items()}
    grid, bbox_min = _build_occupancy_grid(atoms, scaled_radii, grid_spacing, padding=0.5 + probe_radius)

    if probe_radius > 0:
        probe_vox = probe_radius / grid_spacing
        struct = _sphere_struct(probe_vox)
        dilated = binary_dilation(grid, structure=struct)
        grid = binary_erosion(dilated, structure=struct)

    return _marching_cubes_safe(grid, 0.5, grid_spacing, bbox_min, atoms)


# ── Fast coarse (CG-bead) surface ─────────────────────────────────────────────
# The all-atom rebuild (~300k Atom objects) DOMINATES the surface time and is largely
# wasted: at the display grid (~0.3 nm) individual atoms aren't resolved.  Rasterising
# ~2 spheres per nucleotide (backbone + base, from the CG geometry / relaxed frame) skips
# the rebuild entirely and lands within ~2.8 Å of the full-atom envelope (< the grid's own
# spacing).  This is the ChimeraX-style low-resolution surface; the full-atom path stays
# available for "high detail".
CG_BEAD_RADIUS_NM = 0.50   # per-nucleotide sphere radius (nm) ≈ a nucleotide's atomic extent


def make_cg_bead(x, y, z, strand_id: str = "", helix_id: str = "",
                 bp_index: int = 0, direction: str = "FORWARD") -> Atom:
    """One coarse per-nucleotide sphere as an element-'C' Atom (radius set by cg_surface_mesh
    via radius_scale); carries strand/helix/bp/dir for colouring + RMSF lookup."""
    return Atom(serial=0, name="CG", element="C", residue="DT", chain_id="A", seq_num=0,
                x=float(x), y=float(y), z=float(z), strand_id=strand_id, helix_id=helix_id,
                bp_index=int(bp_index), direction=direction)


def compute_surface_from_cloud(
    positions: np.ndarray,
    radii: np.ndarray,
    strand_ids: list,
    grid_spacing: float = 0.20,
    probe_radius: float = 0.28,
    radius_scale: float = 1.2,
) -> SurfaceMesh:
    """Molecular surface from a raw point cloud (positions + per-atom VdW radius + per-atom
    strand id) instead of ``Atom`` objects — the fast fine-surface path fed by
    ``atomistic.surface_atom_cloud``.  Same morphological-closing algorithm as
    :func:`compute_surface` (scaled VdW spheres → dilate/erode by the probe → marching cubes),
    but the occupancy grid is built by grouping the FEW distinct radii rather than by element,
    and vertex strand ids come from a nearest-cloud-point KD-tree."""
    positions = np.asarray(positions, dtype=np.float64)
    radii = np.asarray(radii, dtype=np.float64) * radius_scale
    if positions.shape[0] == 0:
        return SurfaceMesh(vertices=np.empty((0, 3), np.float32),
                           faces=np.empty((0, 3), np.int32), vertex_strand_ids=[])

    # Pad the bbox by the SAME max radius _build_occupancy_grid uses — the max over the WHOLE
    # VDW_RADIUS table (not just the elements present) — so this grid's origin aligns voxel-for-
    # voxel with compute_surface's; a different pad shifts bbox_min and offsets the whole mesh
    # by the sub-voxel remainder (~1 Å).  Per-atom dilation still uses each atom's own radius.
    max_r = max(VDW_RADIUS.values()) * radius_scale
    padding = 0.5 + probe_radius
    bbox_min = positions.min(axis=0) - (max_r + padding)
    bbox_max = positions.max(axis=0) + (max_r + padding)
    shape = tuple((np.ceil((bbox_max - bbox_min) / grid_spacing)).astype(int) + 1)

    grid = np.zeros(shape, dtype=bool)
    idx_all = np.clip(np.round((positions - bbox_min) / grid_spacing).astype(int),
                      0, np.array(shape) - 1)
    # Group by the handful of distinct radii (P/C/N/O × scale) → one dilation each.
    uniq = np.unique(np.round(radii, 6))
    for r in uniq:
        mask = np.round(radii, 6) == r
        sub = np.zeros(shape, dtype=bool)
        gi = idx_all[mask]
        sub[gi[:, 0], gi[:, 1], gi[:, 2]] = True
        grid |= binary_dilation(sub, structure=_sphere_struct(r / grid_spacing))

    if probe_radius > 0:
        struct = _sphere_struct(probe_radius / grid_spacing)
        grid = binary_erosion(binary_dilation(grid, structure=struct), structure=struct)

    if grid.max() <= 0.5 or grid.min() >= 0.5:
        return SurfaceMesh(vertices=np.empty((0, 3), np.float32),
                           faces=np.empty((0, 3), np.int32), vertex_strand_ids=[])
    verts, faces, _, _ = marching_cubes(grid.astype(np.float32), level=0.5, allow_degenerate=False)
    verts = (verts * grid_spacing + bbox_min).astype(np.float32)
    _, nn = cKDTree(positions).query(verts, workers=-1)
    vsids = [strand_ids[int(i)] if strand_ids else "" for i in nn]
    return SurfaceMesh(vertices=verts, faces=faces.astype(np.int32), vertex_strand_ids=vsids)


def cg_surface_mesh(bead_atoms: list, grid_spacing: float = 0.20, probe_radius: float = 0.28,
                    smooth: int = 15, bead_radius: float = CG_BEAD_RADIUS_NM) -> SurfaceMesh:
    """FAST approximate molecular surface from coarse per-nucleotide spheres — skips the
    all-atom rebuild (the bottleneck).  ~3× faster than the full-atom path; envelope within
    ~2.8 Å of it (< the grid spacing).  ``bead_radius`` (nm) sets the sphere size; the grid
    is coarsened adaptively for large structures."""
    rs = bead_radius / VDW_RADIUS["C"]
    gs = adaptive_grid_spacing(bead_atoms, grid_spacing)
    mesh = compute_surface(bead_atoms, grid_spacing=gs, probe_radius=probe_radius, radius_scale=rs)
    return smooth_mesh(mesh, iterations=smooth)


# ── Mesh smoothing ────────────────────────────────────────────────────────────

def smooth_mesh(
    mesh: SurfaceMesh,
    iterations: int = 15,
    lamb: float = 0.5,
    mu: float = -0.53,
) -> SurfaceMesh:
    """
    Taubin (λ|μ) smoothing — relaxes marching-cubes voxel-staircase faceting
    without the volumetric shrinkage of a plain Laplacian filter.

    Each iteration applies a positive Laplacian step (``+λ·L``) followed by a
    negative one (``+μ·L`` with ``μ<-λ``), which acts as a low-pass band that
    removes high-frequency facets while preserving overall shape.  Topology
    (faces) is unchanged, so a closed input mesh stays closed/watertight.

    Defaults are the canonical Taubin values: ``λ=0.5``, ``μ=-0.53``, 15
    iterations — visibly de-faceted with negligible feature loss.
    """
    n = mesh.vertices.shape[0]
    if iterations <= 0 or n == 0:
        return mesh

    V = mesh.vertices.astype(np.float64)
    F = mesh.faces

    # Symmetric edge list from triangles → row-normalised binary adjacency W.
    e = np.vstack([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    e = np.vstack([e, e[:, ::-1]])
    A = csr_matrix((np.ones(len(e)), (e[:, 0], e[:, 1])), shape=(n, n))
    A.data[:] = 1.0                                       # binarise (dedupe duplicate edges)
    deg = np.asarray(A.sum(axis=1)).ravel()
    deg[deg == 0] = 1.0
    Dinv = csr_matrix((1.0 / deg, (np.arange(n), np.arange(n))), shape=(n, n))
    W = Dinv @ A                                          # neighbour-averaging operator

    for _ in range(iterations):
        V += lamb * (W @ V - V)
        V += mu   * (W @ V - V)

    return SurfaceMesh(
        vertices=V.astype(np.float32),
        faces=F,
        vertex_strand_ids=mesh.vertex_strand_ids,
    )


# ── Per-colour closed sub-surfaces (manifold multi-material export) ────────────

def _weld_smooth_parts(
    parts: list[tuple[np.ndarray, np.ndarray] | None],
    iterations: int,
    weld_round: int = 4,
) -> list[tuple[np.ndarray, np.ndarray] | None]:
    """Taubin-smooth several meshes as one welded complex, then redistribute.

    Vertices that coincide across parts (the shared interface walls, extracted at
    identical voxel mid-planes) are welded to a single vertex before smoothing,
    so they move identically and the walls stay coincident — each part remains
    closed.  ``parts`` is a list of ``(vertices, faces)`` (or ``None``); the same
    structure is returned with smoothed vertices.
    """
    metas: list[tuple[int, int] | None] = []
    chunks_v: list[np.ndarray] = []
    chunks_f: list[np.ndarray] = []
    voff = 0
    for p in parts:
        if p is None:
            metas.append(None)
            continue
        v, f = p
        metas.append((voff, v.shape[0]))
        chunks_v.append(v)
        chunks_f.append(f + voff)
        voff += v.shape[0]

    if not chunks_v:
        return parts

    V = np.concatenate(chunks_v, axis=0)
    F = np.concatenate(chunks_f, axis=0)

    # Weld coincident vertices by rounded position (1e-4 nm ⇒ sub-picometre).
    _, inv = np.unique(np.round(V, weld_round), axis=0, return_inverse=True)
    inv = inv.ravel()
    welded = SurfaceMesh(
        vertices=np.unique(np.round(V, weld_round), axis=0).astype(np.float32),
        faces=inv[F].astype(np.int32),
        vertex_strand_ids=[],
    )
    smoothed = smooth_mesh(welded, iterations=iterations)
    V_new = smoothed.vertices.astype(np.float64)[inv]      # back to per-part order

    out: list[tuple[np.ndarray, np.ndarray] | None] = []
    for p, meta in zip(parts, metas):
        if p is None or meta is None:
            out.append(None)
            continue
        start, count = meta
        out.append((V_new[start : start + count], p[1]))
    return out


def compute_colored_surfaces(
    atoms: list[Atom],
    strand_to_group: dict[str, int],
    n_groups: int,
    grid_spacing: float = 0.20,
    probe_radius: float = 0.28,
    radius_scale: float = 1.2,
    smooth: int = 15,
) -> list[SurfaceMesh | None]:
    """Per-group CLOSED (watertight) molecular sub-surfaces with shared walls.

    The SES volume is built exactly as :func:`compute_surface`, then every
    occupied voxel is labelled with the group of its nearest atom (via
    ``strand_to_group``; default group 0).  Marching cubes runs separately on
    each group's voxel mask, so every returned part is a closed surface.  The
    masks partition one grid, so the internal wall between two groups is the same
    voxel mid-plane for both — the walls coincide.  All parts are welded and
    Taubin-smoothed together (:func:`_weld_smooth_parts`) so shared walls move in
    lock-step while each part stays watertight.

    Returns a list of length ``n_groups``; entry ``g`` is the closed SurfaceMesh
    for group ``g`` (vertices in nm), or ``None`` if that group has no voxels.
    """
    scaled_radii = {elem: r * radius_scale for elem, r in VDW_RADIUS.items()}
    grid, bbox_min = _build_occupancy_grid(
        atoms, scaled_radii, grid_spacing, padding=0.5 + probe_radius
    )
    if probe_radius > 0:
        struct = _sphere_struct(probe_radius / grid_spacing)
        grid = binary_erosion(binary_dilation(grid, structure=struct), structure=struct)

    if not grid.any():
        return [None] * n_groups

    # Label occupied voxels by nearest-atom group.
    positions = np.array([[a.x, a.y, a.z] for a in atoms], dtype=np.float64)
    atom_group = np.fromiter(
        (strand_to_group.get(a.strand_id or "", 0) for a in atoms),
        dtype=np.int64,
        count=len(atoms),
    )
    tree = cKDTree(positions)
    occ = np.argwhere(grid)                                # (K, 3) voxel indices
    _, nn = tree.query(occ * grid_spacing + bbox_min, workers=-1)
    label = np.full(grid.shape, -1, dtype=np.int64)
    label[occ[:, 0], occ[:, 1], occ[:, 2]] = atom_group[nn]

    shape = np.array(grid.shape)
    raw: list[tuple[np.ndarray, np.ndarray] | None] = []
    for g in range(n_groups):
        mask = label == g
        if not mask.any():
            raw.append(None)
            continue
        idx = np.argwhere(mask)
        lo = np.maximum(idx.min(axis=0) - 1, 0)
        hi = np.minimum(idx.max(axis=0) + 2, shape)
        sub = mask[lo[0] : hi[0], lo[1] : hi[1], lo[2] : hi[2]].astype(np.float32)
        sub = np.pad(sub, 1, mode="constant", constant_values=0.0)
        v, f, _, _ = marching_cubes(sub, level=0.5, allow_degenerate=False)
        # Undo the +1 pad and the crop origin (lo), then voxel → world (nm).
        v = (v - 1.0 + lo) * grid_spacing + bbox_min
        raw.append((v.astype(np.float64), f.astype(np.int64)))

    if smooth > 0:
        raw = _weld_smooth_parts(raw, smooth)

    return [
        None if p is None else SurfaceMesh(
            vertices=p[0].astype(np.float32),
            faces=p[1].astype(np.int32),
            vertex_strand_ids=[],
        )
        for p in raw
    ]


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
        if strand.is_scaffold:
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
