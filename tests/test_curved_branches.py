"""Actual 6→12→6+6 forks: routing, curved coordinates and persisted split limits."""

import numpy as np
import pytest

from tests.test_branched_generator import source
from backend.core.models import Design, LatticeType, Crossover, HalfCrossover
from backend.core.two_np_generator import GeneratorSettings
from backend.core.platform_generator import plan_generated
from backend.core.crossover_positions import (
    all_valid_crossover_sites,
    crossover_allowed,
)
from backend.core.validator import validate_design


def test_fork_has_six_helix_trunk_and_twelve_helix_junctions():
    candidate, report = plan_generated(source(), GeneratorSettings(branch_sizing="fixed", shape="branched"))
    summary = candidate.summary

    def count(bp):
        return sum(
            any(lo <= bp <= hi for lo, hi in t["intervals"])
            for t in summary["branch_tracks"]
        )

    assert count(summary["nominal_length_bp"] // 2) == 6
    for lo, hi in summary["fork_crossover_intervals"]:
        assert count((lo + hi) // 2) == 12
    assert all(len(face) == 6 for face in summary["fork_faces"])
    assert len(candidate.design.scaffolds()) == 1
    assert len(candidate.design.deformations) == 2
    assert any(h.loop_skips for h in candidate.design.helices)
    assert report["selected"]["scaffold_used_nt"] < 7249
    assert validate_design(candidate.design).passed


def test_split_constraint_survives_serialization_and_blocks_rerouting():
    candidate, _ = plan_generated(source(), GeneratorSettings(branch_sizing="fixed", shape="branched"))
    design = Design.model_validate_json(candidate.design.model_dump_json())
    rule = design.crossover_constraints[0]
    from backend.api.crud import _topology_substitute

    assert not _topology_substitute(design, Design()).crossover_constraints
    assert (
        _topology_substitute(Design(), design).crossover_constraints
        == design.crossover_constraints
    )
    # Adjacent lattice faces remain separate outside the allowed junction regions.
    from backend.core.crossover_positions import crossover_neighbor

    a, b = next(
        (a, b)
        for a in rule.helix_ids_a
        for b in rule.helix_ids_b
        if any(
            crossover_neighbor(design.lattice_type, *design.find_helix(a).grid_pos, bp)
            == design.find_helix(b).grid_pos
            for bp in range(21)
        )
    )
    assert not crossover_allowed(design, a, b, 0)
    assert all(
        crossover_allowed(design, x["helix_a_id"], x["helix_b_id"], x["index"])
        for x in all_valid_crossover_sites(design)
    )
    bad = Crossover(
        half_a=HalfCrossover(
            helix_id=a, index=7, strand=design.find_helix(a).direction
        ),
        half_b=HalfCrossover(
            helix_id=b, index=7, strand=design.find_helix(b).direction
        ),
    )
    assert not validate_design(
        design.copy_with(crossovers=[*design.crossovers, bad])
    ).passed


@pytest.mark.parametrize(
    "design,message",
    [
        (source(lattice=LatticeType.SQUARE), "honeycomb"),
        (
            source([[-10, 0, -40], [10, 0, -40], [10, 0, 40], [-10, 0, 40]]),
            "No curved 6HB fork",
        ),
        (
            source([[-20, 0, -15], [20, 0, -15], [20, 0, 15], [-20, 0, 15]]),
            "No curved 6HB fork",
        ),
    ],
)
def test_unsupported_forks_fail_before_mutation(design, message):
    before = design.model_dump_json()
    with pytest.raises(ValueError, match=message):
        plan_generated(design, GeneratorSettings(branch_sizing="fixed", shape="branched"))
    assert design.model_dump_json() == before


@pytest.mark.slow
def test_curved_i_closes_twelve_attachments_and_has_real_staple_junctions():
    from backend.api.generated_history import build_recorded
    from backend.core.generator_validation import check_generated_structure
    from backend.core.deformation import deformed_nucleotide_arrays
    from backend.core.curved_rod_generator import physical_scaffold_nt

    original = source()
    settings = GeneratorSettings(branch_sizing="fixed", shape="branched", connections_per_particle=3)
    candidate, _ = plan_generated(original, settings)
    generated, placement = build_recorded(original, candidate, settings)
    assert validate_design(generated).passed
    assert len(placement["connections"]) == 12
    assert max(placement["attachment_residuals_nm"]) < 0.02
    assert physical_scaffold_nt(generated) <= candidate.summary["scaffold_size"]
    for p, q in zip(generated.nanoparticles, original.nanoparticles):
        np.testing.assert_array_equal(
            p.pose.to_array()[:3, 3], q.pose.to_array()[:3, 3]
        )
    rule = generated.crossover_constraints[0]
    positions = {}
    for hid in rule.helix_ids_a + rule.helix_ids_b:
        arr = deformed_nucleotide_arrays(generated.find_helix(hid), generated)
        positions[hid] = dict(zip(arr["bp_indices"], arr["axis_points"]))
    crosslinks = [
        xo
        for xo in generated.crossovers
        if (
            xo.half_a.helix_id in rule.helix_ids_a
            and xo.half_b.helix_id in rule.helix_ids_b
        )
        or (
            xo.half_b.helix_id in rule.helix_ids_a
            and xo.half_a.helix_id in rule.helix_ids_b
        )
    ]
    for lo, hi in rule.allowed_bp_intervals:
        links = [xo for xo in crosslinks if lo <= xo.half_a.index <= hi]
        assert any(
            xo.half_a.strand != generated.find_helix(xo.half_a.helix_id).direction
            for xo in links
        )
        assert any(
            xo.half_a.strand == generated.find_helix(xo.half_a.helix_id).direction
            for xo in links
        )
    for xo in crosslinks:
        a, b = xo.half_a, xo.half_b
        assert crossover_allowed(generated, a.helix_id, b.helix_id, a.index)
        assert np.linalg.norm(
            positions[a.helix_id][a.index] - positions[b.helix_id][b.index]
        ) == pytest.approx(2.25, abs=0.01)
    assert (
        check_generated_structure(generated, placement["generated_helix_ids"])["status"]
        == "passed"
    )


@pytest.mark.slow
def test_three_particle_fork_generates_and_reports_flexibility():
    from backend.api.generated_history import build_recorded
    from backend.core.generator_validation import check_generated_structure

    original = source([[-25, 0, 30], [25, 0, 30], [0, 0, -30]])
    settings = GeneratorSettings(branch_sizing="fixed", shape="branched")
    candidate, _ = plan_generated(original, settings)
    generated, placement = build_recorded(original, candidate, settings)
    assert len(placement["connections"]) == 3
    assert max(placement["attachment_residuals_nm"]) < 0.02
    assert validate_design(generated).passed
    screen = check_generated_structure(generated, placement["generated_helix_ids"])
    assert screen["connected_components"] == 1
    assert screen["max_rmsf_nm"] > 0
    if screen["max_rmsf_nm"] > 5:
        assert screen["status"] == "warning"
        assert screen["warnings"]
