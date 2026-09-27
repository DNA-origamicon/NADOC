"""Continuous-field display comparison: shape error and isolation from the baseline."""

import numpy as np
import pytest
from skimage.measure import marching_cubes

from backend.core.surface_field import continuous_surface_field


def test_field_reduces_voxel_sphere_error_without_inflating_envelope():
    axis = np.arange(-1.3, 1.31, 0.05)
    x, y, z = np.meshgrid(axis, axis, axis, indexing="ij")
    occupancy = x * x + y * y + z * z <= 1.0
    original = occupancy.copy()
    field = continuous_surface_field(occupancy)
    np.testing.assert_array_equal(occupancy, original)
    assert field.dtype == np.float32
    assert np.any((field > 0) & (field < 1))
    errors = []
    for grid in [occupancy.astype(np.float32), field]:
        verts, *_ = marching_cubes(grid, 0.5)
        radius = np.linalg.norm(verts * 0.05 + axis[0], axis=1)
        errors.append(np.sqrt(np.mean((radius - 1) ** 2)))
    assert errors[1] < errors[0] * 0.8
    assert errors[1] < 0.01  # sub-grid error, no gross envelope inflation


def test_native_figure_promotes_remeshing_and_alias_matches(monkeypatch):
    from backend.api.routes_display_geometry import _build_design_surface_mesh
    from tests.conftest import build_extruded_bundle, LatticeType

    monkeypatch.setenv("NADOC_SURFACE_GPU", "0")
    design = build_extruded_bundle([(0, 0)], 3, lattice=LatticeType.HONEYCOMB)

    def build(detail):
        return _build_design_surface_mesh(design, 0.2, 0.14, 1.3, 15, detail)

    before = build("chimerax")
    field = build("remeshed")
    after = build("chimerax")
    assert field.vertices.size and np.isfinite(field.vertices).all()
    np.testing.assert_array_equal(field.vertices, before.vertices)
    np.testing.assert_array_equal(before.vertices, after.vertices)
    np.testing.assert_array_equal(before.faces, after.faces)
    assert set(field.vertex_strand_ids) == set(before.vertex_strand_ids)
    assert len(field.vertex_nuc_ids) == len(field.vertices)


@pytest.mark.parametrize("detail", ["chimerax", "continuous", "remeshed"])
def test_simulation_field_selects_continuous_extraction(monkeypatch, detail):
    from types import SimpleNamespace
    from backend.core import surface, oxdna_health
    from backend.api.routes_oxdna import OxdnaSurfaceBody

    calls = []
    remeshed = []
    mesh = surface.SurfaceMesh(np.empty((0, 3)), np.empty((0, 3), int), [])
    monkeypatch.setattr(
        oxdna_health, "build_display_model", lambda *a, **k: SimpleNamespace(atoms=[])
    )
    monkeypatch.setattr(surface, "adaptive_grid_spacing", lambda *a, **k: 0.12)
    monkeypatch.setattr(
        surface, "compute_surface", lambda *a, **k: calls.append(k) or mesh
    )
    monkeypatch.setattr(surface, "smooth_mesh", lambda m, **k: m)
    monkeypatch.setattr(
        "backend.core.surface_remesh.remesh_sharp_patches",
        lambda m: remeshed.append(m) or m,
    )
    oxdna_health.frame_surface_json(None, {}, color_mode="uniform", detail=detail)
    assert len(remeshed) == (0 if detail == "continuous" else 1)
    assert calls[0]["continuous_field"] is True
    assert calls[0]["probe_radius"] == 0.06
    assert calls[0]["grid_spacing"] == 0.05
    assert OxdnaSurfaceBody(detail=detail).probe_radius == 0.06
