"""Conforming local refinement, bounded shape change, and mode routing."""

import numpy as np
from scipy.spatial import ConvexHull, cKDTree
from skimage.measure import marching_cubes

from backend.core.surface import SurfaceMesh
from backend.core.surface_quality import surface_quality
from backend.core.surface_remesh import remesh_sharp_patches


def test_local_remesh_preserves_closed_shell_and_bounds_displacement():
    v = np.array(
        [
            [0.1, 0, 0],
            [-0.1, 0, 0],
            [0, 0.1, 0],
            [0, -0.1, 0],
            [0, 0, 0.1],
            [0, 0, -0.1],
        ]
    )
    hull = ConvexHull(v)
    f = hull.simplices.copy()
    cross = np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]])
    flip = np.einsum("ij,ij->i", cross, v[f].mean(axis=1)) < 0
    f[flip] = f[flip, ::-1]
    mesh = SurfaceMesh(v.astype(np.float32), f, ["strand"] * 6, ["nuc"] * 6)
    before = mesh.vertices.copy()
    result = remesh_sharp_patches(mesh)
    assert len(result.faces) > len(f)
    np.testing.assert_array_equal(mesh.vertices, before)
    q = surface_quality(result)
    assert q["boundary_edges"] == q["nonmanifold_edges"] == q["degenerate_faces"] == 0
    assert (
        q["thresholds"]["60"]["length_nm"]
        < surface_quality(mesh)["thresholds"]["60"]["length_nm"]
    )
    edges = np.unique(
        np.sort(np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]]), axis=1),
        axis=0,
    )
    reference = np.concatenate([v, v[edges].mean(axis=1)])
    assert cKDTree(reference).query(result.vertices)[0].max() <= 0.010001
    assert set(result.vertex_strand_ids) == {"strand"}
    assert set(result.vertex_nuc_ids) == {"nuc"}
    assert len(result.vertex_nuc_ids) == len(result.vertices)


def test_smooth_sphere_is_exact_noop():
    a = np.linspace(-1.2, 1.2, 49)
    x, y, z = np.meshgrid(a, a, a, indexing="ij")
    v, f, *_ = marching_cubes(
        (x * x + y * y + z * z).astype(np.float32), 0.97317, allow_degenerate=False
    )
    mesh = SurfaceMesh(v * 0.05, f, [])
    assert remesh_sharp_patches(mesh) is mesh


def test_native_presets_route_to_same_field_and_only_experiment_remeshes(monkeypatch):
    from backend.api import routes_display_geometry as routes
    from backend.core import surface

    calls = []
    monkeypatch.setattr(routes, "_can_use_surface_cloud", lambda d: True)
    monkeypatch.setattr(
        "backend.core.atomistic.surface_atom_cloud", lambda d: ([], [], [], [])
    )
    monkeypatch.setattr(
        surface, "compute_split_surfaces_from_cloud", lambda *a, **k: calls.append(k)
    )
    for detail in ("chimerax", "continuous", "remeshed"):
        routes._build_design_surface_mesh(None, 0.2, None, 1.3, 15, detail)
    assert [c["continuous_field"] for c in calls] == [True] * 3
    assert [c["probe_radius"] for c in calls] == [0.06] * 3
    assert [c["local_remesh"] for c in calls] == [True, False, True]


def test_refinement_leaves_other_shell_and_ownership_unchanged():
    a = np.linspace(-1.2, 1.2, 25)
    x, y, z = np.meshgrid(a, a, a, indexing="ij")
    sv, sf, *_ = marching_cubes(
        (x * x + y * y + z * z).astype(np.float32), 0.97317, allow_degenerate=False
    )
    sv = sv * 0.1 - 1.2
    ov = np.array(
        [
            [0.1, 0, 0],
            [-0.1, 0, 0],
            [0, 0.1, 0],
            [0, -0.1, 0],
            [0, 0, 0.1],
            [0, 0, -0.1],
        ]
    )
    of = ConvexHull(ov).simplices.copy()
    cross = np.cross(ov[of[:, 1]] - ov[of[:, 0]], ov[of[:, 2]] - ov[of[:, 0]])
    flip = np.einsum("ij,ij->i", cross, ov[of].mean(axis=1)) < 0
    of[flip] = of[flip, ::-1]
    v = np.concatenate([sv, ov + 4]).astype(np.float32)
    f = np.concatenate([sf, of + len(sv)])
    mesh = SurfaceMesh(v, f, ["smooth"] * len(sv) + ["sharp"] * 6)
    result = remesh_sharp_patches(mesh)
    assert len(result.faces) > len(f)
    np.testing.assert_array_equal(result.vertices[: len(sv)], sv)
    np.testing.assert_array_equal(result.faces[: len(sf)], sf)
    assert result.vertex_strand_ids[: len(sv)] == ["smooth"] * len(sv)
    assert set(result.vertex_strand_ids[len(sv) :]) == {"sharp"}


def test_edge_sort_reuse_preserves_ownership_on_irregular_connectivity():
    from backend.core.surface_remesh import _edge_table

    faces = np.array([[0, 1, 2], [2, 1, 3], [0, 2, 3], [0, 1, 4], [4, 1, 5], [5, 1, 0]])
    owners = {}
    for a, b in [(0, 1), (1, 2), (2, 0)]:
        for i, face in enumerate(faces):
            owners.setdefault(tuple(sorted((face[a], face[b]))), []).append(i)
    edges = sorted(owners)
    index = {edge: i for i, edge in enumerate(edges)}
    inverse = [
        [index[tuple(sorted((face[a], face[b])))] for a, b in [(0, 1), (1, 2), (2, 0)]]
        for face in faces
    ]
    paired = [i for i, edge in enumerate(edges) if len(owners[edge]) == 2]
    expected = (edges, inverse, paired, [owners[edges[i]] for i in paired])
    for actual, want in zip(_edge_table(faces), expected):
        np.testing.assert_array_equal(actual, want)
