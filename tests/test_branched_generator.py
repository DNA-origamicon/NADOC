"""Branched footprints must route real DNA, preserve gaps, and fit fixed cargo."""

import numpy as np
import pytest

from backend.core.models import Design, Direction, LatticeType, Mat4x4, Nanoparticle
from backend.core.platform_generator import plan_generated
from backend.core.two_np_generator import GeneratorSettings, scaffold_nt
from backend.core.validator import validate_design


def source(
    points=((-20, 0, -40), (20, 0, -40), (20, 0, 40), (-20, 0, 40)),
    lattice=LatticeType.HONEYCOMB,
):
    particles = []
    for point in points:
        pose = np.eye(4)
        pose[:3, 3] = point
        particles.append(Nanoparticle(diameter_nm=10, pose=Mat4x4.from_array(pose)))
    return Design(lattice_type=lattice, nanoparticles=particles)


@pytest.mark.parametrize("lattice", [LatticeType.HONEYCOMB, LatticeType.SQUARE])
def test_plan_has_one_scaffold_and_real_empty_branch_gaps(lattice):
    original = source(
        ((-15, 0, -30), (15, 0, -30), (15, 0, 30), (-15, 0, 30)), lattice=lattice
    )
    before = original.model_dump_json()
    candidate, report = plan_generated(original, GeneratorSettings(shape="branched", branch_geometry="lattice"))
    assert original.model_dump_json() == before
    assert len(candidate.design.scaffolds()) == 1
    assert validate_design(candidate.design).passed
    assert scaffold_nt(candidate.design) == report["selected"]["scaffold_used_nt"]
    assert scaffold_nt(candidate.design) <= report["selected"]["scaffold_size"]
    # The chosen tall rectangle must have open space between its crossbars.
    from backend.core.branched_generator import branch_seed
    from tests.test_section_router import (
        intertooth_gap_extension,
        min_per_gap_clearance,
    )

    seed = branch_seed(lattice, candidate.summary)
    assert any(len(t["intervals"]) > 1 for t in candidate.summary["branch_tracks"])
    assert intertooth_gap_extension(candidate.design, seed)[0] <= 12
    assert min_per_gap_clearance(candidate.design, seed) >= 15
    # Both left and right branches retain the lattice's scaffold polarity.
    for strand in candidate.design.scaffolds():
        for domain in strand.domains:
            helix = candidate.design.find_helix(domain.helix_id)
            assert domain.direction == (
                Direction.FORWARD if sum(helix.grid_pos) % 2 == 0 else Direction.REVERSE
            )


@pytest.mark.parametrize(
    "points,message",
    [
        (
            [[-60, 0, -90], [60, 0, -90], [60, 0, 90], [-60, 0, 90]],
            "No routable branched",
        ),
        ([[-20, 0, -40], [20, 0, -40], [20, 25, 40], [-20, 0, 40]], "within 2 nm"),
    ],
)
def test_unsupported_arrangements_fail_without_mutation(points, message):
    original = source(points)
    before = original.model_dump_json()
    with pytest.raises(ValueError, match=message):
        plan_generated(original, GeneratorSettings(shape="branched", branch_geometry="lattice"))
    assert original.model_dump_json() == before


@pytest.mark.slow
def test_triangle_generation_and_structural_screen():
    from backend.api.generated_history import build_recorded
    from backend.core.generator_validation import check_generated_structure

    original = source([[-25, 0, -20], [25, 0, -20], [0, 0, 30]])
    settings = GeneratorSettings(shape="branched", branch_geometry="lattice")
    candidate, _ = plan_generated(original, settings)
    generated, placement = build_recorded(original, candidate, settings)
    assert len(placement["connections"]) == 3
    assert max(placement["attachment_residuals_nm"]) < 0.02
    assert validate_design(generated).passed
    assert scaffold_nt(generated) <= candidate.summary["scaffold_size"]
    assert generated.feature_log[0].label == "Create branched lattice sections"
    for actual, expected in zip(generated.nanoparticles, original.nanoparticles):
        np.testing.assert_array_equal(
            actual.pose.to_array()[:3, 3], expected.pose.to_array()[:3, 3]
        )
    assert (
        check_generated_structure(generated, placement["generated_helix_ids"])[
            "connected_components"
        ]
        == 1
    )
