"""
Binary STL export of the molecular surface for 3D printing.

The source geometry is the same watertight marching-cubes mesh produced by
``backend.core.surface.compute_surface`` (vertices in nm, triangle faces).
That mesh is closed (the occupancy grid is padded so the structure never
touches a grid edge) and free of degenerate triangles
(``allow_degenerate=False``), which is exactly what slicers require.

STL is unitless; every common slicer (Cura, PrusaSlicer, Bambu Studio,
Chitubox) interprets the coordinates as millimetres.  We therefore auto-scale
the nm geometry so the longest bounding-box dimension matches a target print
size (default 200 mm — a typical consumer printer bed).  Binary STL is used
(≈8× smaller than ASCII, faster slicer load).
"""

from __future__ import annotations

import struct

import numpy as np

from backend.core.surface import SurfaceMesh


def auto_scale(mesh: SurfaceMesh, target_mm: float = 200.0) -> float:
    """Scale factor (mm per nm) so the longest extent equals ``target_mm``.

    Returns 1.0 for an empty or zero-size mesh.
    """
    if mesh.vertices.shape[0] == 0:
        return 1.0
    extent = mesh.vertices.max(axis=0) - mesh.vertices.min(axis=0)
    longest = float(extent.max())
    if longest <= 0.0:
        return 1.0
    return target_mm / longest


def _face_normals(verts: np.ndarray, faces: np.ndarray) -> np.ndarray:
    """Per-face unit normals from right-hand-rule winding (zero-length kept 0)."""
    v0 = verts[faces[:, 0]]
    v1 = verts[faces[:, 1]]
    v2 = verts[faces[:, 2]]
    n = np.cross(v1 - v0, v2 - v0)
    lens = np.linalg.norm(n, axis=1, keepdims=True)
    lens[lens == 0.0] = 1.0
    return (n / lens).astype(np.float32)


def _signed_volume(verts: np.ndarray, faces: np.ndarray) -> float:
    """Signed volume of the closed mesh (divergence theorem).

    Positive when face winding yields outward normals.  Used only as a global
    orientation sanity check.
    """
    v0 = verts[faces[:, 0]]
    v1 = verts[faces[:, 1]]
    v2 = verts[faces[:, 2]]
    return float(np.einsum("ij,ij->i", v0, np.cross(v1, v2)).sum() / 6.0)


# Packed binary-STL triangle record: float32 normal[3] + v0[3] + v1[3] + v2[3]
# + uint16 attribute byte count.  align=False ⇒ itemsize == 50, matching spec.
_TRI_DTYPE = np.dtype(
    [
        ("normal", "<f4", (3,)),
        ("v0", "<f4", (3,)),
        ("v1", "<f4", (3,)),
        ("v2", "<f4", (3,)),
        ("attr", "<u2"),
    ],
    align=False,
)
assert _TRI_DTYPE.itemsize == 50


def export_stl(mesh: SurfaceMesh, scale: float = 1.0, name: str = "surface") -> bytes:
    """Serialise a SurfaceMesh as binary STL bytes (vertices × ``scale``, in mm)."""
    verts = mesh.vertices.astype(np.float64) * float(scale)
    faces = mesh.faces.astype(np.int64)

    # Orientation safety net: skimage marching_cubes already yields outward
    # winding for a solid>background grid, but flip globally if inside-out.
    if faces.shape[0] and _signed_volume(verts, faces) < 0.0:
        faces = faces[:, ::-1]

    n_tri = int(faces.shape[0])
    records = np.zeros(n_tri, dtype=_TRI_DTYPE)
    if n_tri:
        records["normal"] = _face_normals(verts, faces)
        records["v0"] = verts[faces[:, 0]].astype(np.float32)
        records["v1"] = verts[faces[:, 1]].astype(np.float32)
        records["v2"] = verts[faces[:, 2]].astype(np.float32)
        # "attr" left zero.

    header = f"NADOC surface {name}".encode("ascii", "ignore")[:80].ljust(80, b"\0")
    return header + struct.pack("<I", n_tri) + records.tobytes()
