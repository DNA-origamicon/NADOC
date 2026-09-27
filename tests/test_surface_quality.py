import numpy as np
from backend.core.surface import SurfaceMesh
from backend.core.surface_quality import surface_quality


def mesh(vertices, faces):
    return SurfaceMesh(
        np.asarray(vertices, float).reshape(-1, 3),
        np.asarray(faces, int).reshape(-1, 3),
        [],
    )


def test_flat_patch_has_no_crease_and_reports_open_boundary():
    m = mesh([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]], [[0, 1, 2], [1, 3, 2]])
    q = surface_quality(m)
    assert q["normal_turn_max_deg"] == 0
    assert q["thresholds"]["30"]["edges"] == 0
    assert q["boundary_edges"] == 4


def test_fold_detects_right_angle_and_scales_length_density():
    m = mesh([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], [[0, 1, 2], [1, 0, 3]])
    q = surface_quality(m)
    assert np.isclose(q["normal_turn_p99_deg"], 90)
    assert q["thresholds"]["60"]["edge_length_percent"] == 100
    assert np.allclose(q["hotspots"][0]["position_nm"], [0.5, 0, 0])
    m.vertices *= 2
    bigger = surface_quality(m)
    assert bigger["normal_turn_p99_deg"] == q["normal_turn_p99_deg"]
    assert np.isclose(
        bigger["thresholds"]["60"]["length_per_area_nm_inverse"],
        q["thresholds"]["60"]["length_per_area_nm_inverse"] / 2,
    )


def test_nonmanifold_and_degenerate_faces_are_not_treated_as_smooth():
    m = mesh(
        [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]],
        [[0, 1, 2], [1, 0, 3], [0, 1, 3], [0, 0, 0]],
    )
    q = surface_quality(m)
    assert q["nonmanifold_edges"] >= 1
    assert q["degenerate_faces"] == 1


def test_empty_surface_has_no_fabricated_angle():
    q = surface_quality(mesh([], []))
    assert q["normal_turn_max_deg"] is None
    assert q["measured_edges"] == 0
    assert q["hotspots"] == []


def test_continuous_strands_share_physical_probe_and_grid(monkeypatch):
    from backend.core import surface

    # Long scaffold-like extent versus a local staple-like extent; no metadata
    # branch may change either probe or sampling in continuous mode.
    points = np.array(
        [
            [0, 0, 0],
            [100, 0, 0],
            [0, 100, 0],
            [0, 0, 100],
            [1, 1, 1],
            [2, 1, 1],
            [1, 2, 1],
            [1, 1, 2],
        ],
        float,
    )
    calls = []

    def capture(*args, **kwargs):
        calls.append(kwargs)
        return mesh([], [])

    monkeypatch.setattr(surface, "compute_surface_from_cloud", capture)
    for radius in [0.14, 0.24, 0.0]:
        calls.clear()
        surface.compute_split_surfaces_from_cloud(
            points,
            np.full(8, 0.17),
            ["scaffold"] * 4 + ["staple"] * 4,
            probe_radius=radius,
            continuous_field=True,
        )
        assert [c["probe_radius"] for c in calls] == [radius, radius]
        assert calls[0]["grid_spacing"] == calls[1]["grid_spacing"] == 0.05
        assert all(c["continuous_field"] for c in calls)
