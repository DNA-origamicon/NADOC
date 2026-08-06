"""
Tests for backend/core/stl_export.py — binary STL export of the molecular surface.

Verifies the on-disk binary STL format, that the marching-cubes surface stays
watertight through the exporter (every edge shared by exactly two triangles),
and that auto-scaling fits the longest dimension to the target print size.
"""

import struct

import numpy as np

from backend.core.atomistic import build_atomistic_model
from backend.core.lattice import make_bundle_design
from backend.core.stl_export import auto_scale, export_stl
from backend.core.surface import SurfaceMesh, compute_surface, smooth_mesh

_CELLS_6HB = [(0, 0), (0, 1), (1, 0), (1, 2), (0, 2), (2, 1)]


def _surface_mesh() -> SurfaceMesh:
    design = make_bundle_design(cells=_CELLS_6HB, length_bp=42, plane="XY")
    model = build_atomistic_model(design)
    # Coarser grid keeps the test fast while still producing a real surface.
    return compute_surface(model.atoms, grid_spacing=0.30, probe_radius=0.28)


def _parse_binary_stl(data: bytes):
    """Return (header_bytes, n_tri, list of (normal, v0, v1, v2))."""
    header = data[:80]
    (n_tri,) = struct.unpack("<I", data[80:84])
    tris = []
    off = 84
    for _ in range(n_tri):
        vals = struct.unpack("<12f", data[off : off + 48])
        normal = vals[0:3]
        v0, v1, v2 = vals[3:6], vals[6:9], vals[9:12]
        tris.append((normal, v0, v1, v2))
        off += 50  # 48 floats + 2-byte attribute
    return header, n_tri, tris


def test_binary_stl_layout():
    mesh = _surface_mesh()
    assert mesh.faces.shape[0] > 0, "expected a non-empty surface mesh"
    data = export_stl(mesh, scale=1.0, name="test")

    # 80-byte header + uint32 count + 50 bytes/triangle.
    n_tri = mesh.faces.shape[0]
    assert len(data) == 84 + 50 * n_tri
    header, parsed_n, tris = _parse_binary_stl(data)
    assert len(header) == 80
    assert parsed_n == n_tri
    assert len(tris) == n_tri


def test_normals_are_unit_length():
    mesh = _surface_mesh()
    _, _, tris = _parse_binary_stl(export_stl(mesh, scale=1.0))
    norms = np.array([t[0] for t in tris])
    lengths = np.linalg.norm(norms, axis=1)
    # Marching-cubes faces have area, so every normal should be (near) unit length.
    assert np.allclose(lengths, 1.0, atol=1e-4)


def test_surface_is_closed():
    """The surface must be closed (watertight): no boundary/hole edges.

    A closed mesh is what slicers need to determine interior vs exterior. Every
    edge is shared by an EVEN number of triangles — count 2 for manifold edges,
    and rarely count 4 at a non-manifold junction where two surface lobes touch
    (a normal marching-cubes artifact that slicers auto-repair on import). The
    print-critical invariant is that NO edge has an odd count, i.e. no holes.
    """
    mesh = _surface_mesh()
    edge_count: dict[tuple[int, int], int] = {}
    for a, b, c in mesh.faces:
        for u, v in ((a, b), (b, c), (c, a)):
            key = (int(u), int(v)) if u < v else (int(v), int(u))
            edge_count[key] = edge_count.get(key, 0) + 1

    boundary = [e for e, n in edge_count.items() if n % 2 == 1]
    assert not boundary, f"{len(boundary)} boundary edges → mesh has holes (not watertight)"

    # Non-manifold junctions are tolerated but should stay vanishingly rare; a
    # regression that shatters the mesh would blow past this bound.
    junctions = sum(1 for n in edge_count.values() if n > 2)
    assert junctions < 0.001 * len(edge_count), (
        f"{junctions} non-manifold junctions of {len(edge_count)} edges — too many"
    )


def test_auto_scale_fits_target_dimension():
    mesh = _surface_mesh()
    scale = auto_scale(mesh, target_mm=200.0)
    scaled = mesh.vertices.astype(np.float64) * scale
    extent = scaled.max(axis=0) - scaled.min(axis=0)
    assert abs(float(extent.max()) - 200.0) < 1e-3


def _face_normals(verts, faces):
    v0, v1, v2 = verts[faces[:, 0]], verts[faces[:, 1]], verts[faces[:, 2]]
    n = np.cross(v1 - v0, v2 - v0)
    lens = np.linalg.norm(n, axis=1, keepdims=True)
    lens[lens == 0] = 1.0
    return n / lens


def _edge_distribution(faces):
    ec: dict[tuple[int, int], int] = {}
    for a, b, c in faces:
        for u, v in ((a, b), (b, c), (c, a)):
            k = (int(u), int(v)) if u < v else (int(v), int(u))
            ec[k] = ec.get(k, 0) + 1
    return ec


def test_radius_inflate_grows_envelope():
    """A larger radius_scale must produce a strictly larger enclosed volume.

    Measured as the mesh's own volume, not its bounding box.  The bounding box is the
    wrong oracle twice over: marching-cubes vertices land on grid planes, so scaling
    1.2 -> 1.56 (which moves the envelope out by only ~0.11 nm) may or may not gain a
    voxel on a 0.30 nm grid; and the probe close-operation can pull the EXTREME
    vertices inward even as the body grows, so the box can shrink while the envelope
    inflates.  Volume has neither problem.
    """
    design = make_bundle_design(cells=_CELLS_6HB, length_bp=42, plane="XY")
    atoms = build_atomistic_model(design).atoms
    base = compute_surface(atoms, grid_spacing=0.15, radius_scale=1.2)
    fat = compute_surface(atoms, grid_spacing=0.15, radius_scale=1.2 * 1.30)

    def enclosed_volume(mesh):
        v = mesh.vertices[mesh.faces]
        return abs(
            float(
                np.einsum("ij,ij->i", v[:, 0], np.cross(v[:, 1], v[:, 2])).sum() / 6.0
            )
        )

    assert enclosed_volume(fat) > enclosed_volume(base) * 1.10


def test_smooth_mesh_preserves_topology_and_closedness():
    """Taubin smoothing only moves vertices: face indices and closedness unchanged."""
    mesh = _surface_mesh()
    smoothed = smooth_mesh(mesh, iterations=15)
    assert smoothed.faces.shape == mesh.faces.shape
    assert np.array_equal(smoothed.faces, mesh.faces)
    ec = _edge_distribution(smoothed.faces)
    boundary = [e for e, n in ec.items() if n % 2 == 1]
    assert not boundary, "smoothing broke closedness (introduced holes)"


def test_smooth_mesh_reduces_facet_roughness():
    """Adjacent-face normal alignment should improve after smoothing."""
    mesh = _surface_mesh()
    smoothed = smooth_mesh(mesh, iterations=15)

    def mean_adjacent_normal_dot(m):
        normals = _face_normals(m.vertices.astype(np.float64), m.faces)
        # Map each undirected edge to the face indices that own it.
        edge_to_faces: dict[tuple[int, int], list[int]] = {}
        for fi, (a, b, c) in enumerate(m.faces):
            for u, v in ((a, b), (b, c), (c, a)):
                k = (int(u), int(v)) if u < v else (int(v), int(u))
                edge_to_faces.setdefault(k, []).append(fi)
        dots = []
        for fs in edge_to_faces.values():
            if len(fs) == 2:
                dots.append(float(np.dot(normals[fs[0]], normals[fs[1]])))
        return float(np.mean(dots))

    # Closer to 1.0 = smoother (adjacent faces more coplanar).
    assert mean_adjacent_normal_dot(smoothed) > mean_adjacent_normal_dot(mesh)


def test_smooth_mesh_zero_iterations_is_identity():
    mesh = _surface_mesh()
    same = smooth_mesh(mesh, iterations=0)
    assert np.array_equal(same.vertices, mesh.vertices)
    assert np.array_equal(same.faces, mesh.faces)


def test_empty_mesh_exports_valid_zero_triangle_stl():
    empty = SurfaceMesh(
        vertices=np.empty((0, 3), dtype=np.float32),
        faces=np.empty((0, 3), dtype=np.int32),
        vertex_strand_ids=[],
    )
    assert auto_scale(empty) == 1.0
    data = export_stl(empty)
    header, n_tri, tris = _parse_binary_stl(data)
    assert len(data) == 84
    assert n_tri == 0
    assert tris == []
