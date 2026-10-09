"""Generated sweeps approximate the planned path and remain ordinary authoring inputs."""

import numpy as np
import pytest

from backend.core.models import Design, LatticeType, Mat4x4, Nanoparticle
from backend.core.two_np_generator import GeneratorSettings
from backend.core.curved_rod_generator import (
    path_options,
    bend_operations,
    plan_curved_rods,
)
from backend.core.generated_sweep import sweep_request
from backend.core.sweep import build_sweep
from backend.core.lattice import make_bundle_design
from backend.core.deformation import _precompute_arm_frames


def source(points, lattice=LatticeType.HONEYCOMB):
    particles = []
    for point in points:
        pose = np.eye(4)
        pose[:3, 3] = point
        particles.append(Nanoparticle(diameter_nm=10, pose=Mat4x4.from_array(pose)))
    return Design(lattice_type=lattice, nanoparticles=particles)


@pytest.mark.parametrize("lattice", list(LatticeType))
def test_sweep_approximates_bends_with_fewer_editable_points(lattice):
    original = source([(0, 0, 0), (40, 0, 0), (40, 0, 45)], lattice)
    path = path_options(original, GeneratorSettings(shape="curved-rod"))[0]
    cells = [(0, 0), (0, 1), (1, 0), (1, 1)]
    length, start = 336, 21
    seed = make_bundle_design(cells, length, lattice_type=lattice)
    ops = bend_operations(path, start, [h.id for h in seed.helices])
    bent = seed.copy_with(deformations=ops)
    request = sweep_request(lattice, cells, length, path, start, source=seed)
    assert not set(request.cells).intersection(cells)
    assert len(request.points_nm) < len(ops)
    swept = build_sweep(seed, request)
    new = [h for h in swept.helices if h.id not in {h.id for h in seed.helices}]
    assert all(h.length_bp == length for h in new)
    expected = _precompute_arm_frames(bent, bent.helices, 0, length - 1)[0]
    actual = _precompute_arm_frames(swept, new, 0, length - 1)[0]
    # Ignore the footprint translation used to avoid the existing lattice cells.
    np.testing.assert_allclose(actual - actual[0], expected - expected[0], atol=0.05)


def test_collinear_particles_do_not_require_a_sweep():
    original = source([(0, 0, 0), (0, 0, 30), (0, 0, 60)])
    candidate, report = plan_curved_rods(
        original, GeneratorSettings(shape="curved-rod")
    )
    assert candidate.summary["path_feature"] == "bends"
    assert candidate.summary["bend_count"] == 0
    assert report["selected"]["path_feature"] == "bends"
    assert "sweep_request" not in report["selected"]


def test_complex_path_selects_sweep_but_legacy_planning_keeps_bends():
    original = source([(0, 0, 0), (40, 0, 0), (40, 0, 45)])
    settings = GeneratorSettings(shape="curved-rod")
    modern, report = plan_curved_rods(original, settings)
    assert modern.summary["path_feature"] == "sweep"
    assert modern.summary["bend_count"] > len(original.nanoparticles)
    assert report["selected"]["scaffold_used_nt"] <= report["selected"]["scaffold_size"]
    assert "sweep_request" not in report["selected"]
    legacy, _ = plan_curved_rods(original, settings, use_sweeps=False)
    assert legacy.summary["path_feature"] == "bends"
    assert legacy.summary["sweep_request"] is None
