"""Perimeter preference must survive particle order and arbitrary world poses."""

from itertools import permutations

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from backend.core.platform_generator import platform_frame, perimeter_alignment


# Particle centers from workspace/4NP_gen_test.nadoc (no saved DNA or history).
SAMPLE_CENTERS = np.array(
    [
        [0, 0, 0],
        [28.373086501429384, 0, 0],
        [0.4307396540939443, 0, 28.235037410477915],
        [27.075921461900613, 0, 30.289939588125797],
    ]
)


def test_nearly_square_sample_aligns_all_four_edges_not_a_diagonal():
    frame = platform_frame(SAMPLE_CENTERS)
    alignment = perimeter_alignment(SAMPLE_CENTERS, frame)
    assert alignment["aligned_edges"] == 4
    assert max(e["error_deg"] for e in alignment["edges"]) < 3
    for order in permutations(range(4)):
        reordered = platform_frame(SAMPLE_CENTERS[list(order)])
        np.testing.assert_allclose(np.abs(reordered.T @ frame), np.eye(3), atol=1e-10)


@pytest.mark.parametrize(
    "points",
    [
        [[0.0, 0, 0], [24.0, 0, 0], [0.0, 0, 28]],
        [[0.0, 0, 0], [22.0, 0, 4], [6.0, 0, 25]],
    ],
)
def test_triangle_has_an_exact_perimeter_alignment_in_any_world_pose(points):
    points = np.array(points)
    for rotation in [
        Rotation.identity(),
        Rotation.from_euler("xyz", [71, -32, 43], degrees=True),
    ]:
        centers = rotation.apply(points) + [4, -28, 13]
        frame = platform_frame(centers)
        alignment = perimeter_alignment(centers, frame)
        assert min(e["error_deg"] for e in alignment["edges"]) < 1e-9
        assert alignment["aligned_edges"] >= 1
        np.testing.assert_allclose(frame.T @ frame, np.eye(3), atol=1e-12)
        assert np.linalg.det(frame) == pytest.approx(1)


def test_rectangle_and_manual_rotation_are_relative_to_perimeter():
    points = np.array([[0.0, 0, 0], [20.0, 0, 0], [20.0, 0, 30], [0.0, 0, 30]])
    rotation = Rotation.from_euler("xyz", [17, 61, 38], degrees=True)
    centers = rotation.apply(points)
    frame = platform_frame(centers)
    assert perimeter_alignment(centers, frame)["aligned_edges"] == 4
    offset = platform_frame(centers, 17)
    np.testing.assert_allclose(frame[:, 1], offset[:, 1], atol=1e-12)
    assert all(
        e["error_deg"] == pytest.approx(17)
        for e in perimeter_alignment(centers, offset)["edges"]
    )


def test_interior_fourth_particle_is_not_a_perimeter_corner():
    centers = np.array([[0.0, 0, 0], [30.0, 0, 0], [0.0, 0, 30], [10.0, 0, 10]])
    alignment = perimeter_alignment(centers, platform_frame(centers))
    assert len(alignment["edges"]) == 3
    assert all(3 not in e["particle_indices"] for e in alignment["edges"])


def test_routing_falls_back_without_discarding_edge_alignment(monkeypatch):
    import backend.core.platform_generator as module
    from backend.core.models import Design, Nanoparticle, Mat4x4
    from backend.core.two_np_generator import GeneratorSettings

    particles = []
    for center in SAMPLE_CENTERS:
        pose = np.eye(4)
        pose[:3, 3] = center
        particles.append(Nanoparticle(diameter_nm=10, pose=Mat4x4.from_array(pose)))
    attempted = []

    def route(source, settings, frame):
        attempted.append(frame)
        if len(attempted) == 1:
            raise ValueError("This helix direction exceeds the scaffold budget.")
        return "routed", {"frame": frame}

    monkeypatch.setattr(module, "_plan_platforms_in_frame", route)
    candidate, report = module.plan_platforms(
        Design(nanoparticles=particles), GeneratorSettings()
    )
    assert candidate == "routed"
    assert len(attempted) == 2
    assert abs(np.dot(attempted[0][:, 2], attempted[1][:, 2])) < 1e-10
    assert perimeter_alignment(SAMPLE_CENTERS, report["frame"])["aligned_edges"] == 4
