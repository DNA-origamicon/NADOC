"""Generated Join branches retain native topology, history and fixed cargo."""

from copy import deepcopy
from pathlib import Path
from uuid import UUID

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from backend.api.generated_history import build_recorded
from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.curved_rod_generator import physical_scaffold_nt
from backend.core.join_crossbars import crossbar_summary
from backend.core.joined_branches import _continuous_layouts, joined_seed
from backend.core.models import Design, LatticeType
from backend.core.two_np_generator import GeneratorSettings
from backend.core.validator import validate_design


def _source(aligned_four):
    from tests.test_branched_generator import source

    return (
        Design.model_validate_json(
            (Path(__file__).parent / "fixtures/4np_gen_aligned.json").read_text()
        )
        if aligned_four
        else source([[-25, 0, -20], [25, 0, -20], [0, 0, 30]])
    )


def _cluster_axis(design, cluster_id, bp=None, *, section_cluster_ids=None):
    if section_cluster_ids is not None:
        cluster_id = section_cluster_ids[cluster_id]
    cluster = next(
        c
        for c in design.cluster_transforms
        if c.id == cluster_id or c.id.endswith("_" + cluster_id)
    )
    helices = [h for h in design.helices if h.id in cluster.helix_ids]
    if bp is None:
        center = np.mean(
            [p.to_array() for h in helices for p in (h.axis_start, h.axis_end)], axis=0
        )
        tangent = np.array([0.0, 0.0, 1.0])
    else:
        from backend.core.deformation import _frame_at_bp

        center, _, tangent = _frame_at_bp(
            design, bp - min(h.bp_start for h in helices), helices
        )
    rotation = Rotation.from_quat(cluster.rotation).as_matrix()
    pivot = np.asarray(cluster.pivot)
    center = rotation @ (center - pivot) + pivot + cluster.translation
    return cluster, center, rotation @ tangent


def _assert_opposed_t_layout(summary, centers):
    # Connectivity candidate #2 in the saved four-NP arrangement pairs the
    # left particles (1, 3) and right particles (2, 4) around a solid middle stem.
    junctions = {}
    sections = {s["id"]: s for s in summary["join_sections"]}
    for crossbar in summary["join_crossbars"]:
        junctions[tuple(crossbar["junction"])] = set(crossbar["particle_indices"])
        targets = []
        for index in crossbar["particle_indices"]:
            attachment = summary["join_attachments"][index]
            assert attachment["cluster_id"] == crossbar["cluster_id"]
            target = sections[crossbar["cluster_id"]]["path"]["positions"][
                attachment["bp"]
            ]
            targets.append(target)
        a, b = crossbar["particle_indices"]
        np.testing.assert_allclose(
            np.asarray(targets[1]) - targets[0],
            (centers[b] - centers[a]) @ np.asarray(summary["base_frame"]),
            atol=1e-9,
        )
    assert {frozenset(group) for group in junctions.values()} == {
        frozenset((0, 2)),
        frozenset((1, 3)),
    }
    assert summary["branch_count"] == 2
    assert len(summary["join_sections"]) == 3


@pytest.mark.parametrize("lattice", [LatticeType.HONEYCOMB, LatticeType.SQUARE])
@pytest.mark.parametrize("aligned_four", [False, True], ids=["triangle", "4np-aligned"])
def test_join_branch_seed_has_disjoint_whole_helix_lattices(lattice, aligned_four):
    original = _source(aligned_four).copy_with(lattice_type=lattice)
    centers = np.asarray([p.pose.to_array()[:3, 3] for p in original.nanoparticles])
    summary = crossbar_summary(
        original, centers, next(_continuous_layouts(centers)), 12, 6
    )
    design = joined_seed(lattice, summary)
    assert len(design.cluster_transforms) == (3 if aligned_four else 2)
    assert len(design.deformations) == (2 if aligned_four else 1)
    assert all(op.type == "sweep" for op in design.deformations)
    assert len({h.grid_pos for h in design.helices}) == len(design.helices)
    ids = [hid for c in design.cluster_transforms for hid in c.helix_ids]
    assert len(set(ids)) == len(ids) == len(design.helices)
    assert all(not c.domain_ids for c in design.cluster_transforms)
    assert len(summary["join_attachments"]) == len(original.nanoparticles)
    assert sum(
        a["cluster_id"] == "branch_cluster_0" for a in summary["join_attachments"]
    ) == (0 if aligned_four else 1)
    if aligned_four:
        _assert_opposed_t_layout(summary, centers)
        _, stem_center, stem_axis = _cluster_axis(design, "branch_cluster_0")
        stem = next(c for c in design.cluster_transforms if c.id == "branch_cluster_0")
        stem_length = (
            min(design.find_helix(hid).length_bp for hid in stem.helix_ids)
            * BDNA_RISE_PER_BP
        )
        stations = []
        for crossbar in summary["join_crossbars"]:
            relative = np.asarray(crossbar["junction"]) - stem_center
            assert np.linalg.norm(np.cross(relative, stem_axis)) < 1e-9
            stations.append(relative @ stem_axis)
        assert min(stations) < -stem_length / 2 < stem_length / 2 < max(stations)


@pytest.mark.slow
@pytest.mark.parametrize(
    "aligned_four,budget",
    [(False, "auto"), (True, "auto"), (True, 7249), (True, 8064)],
    ids=["triangle", "4np-auto", "4np-7249", "4np-8064"],
)
def test_generate_join_branches_with_history_without_cando(aligned_four, budget, monkeypatch):
    from backend.api import state
    from backend.api.branch_optimization import plan_for_generation
    from backend.core import generator_validation
    from backend.core.flexible_segments import derive_flexible_connections

    def unexpected_cando(*args, **kwargs):
        pytest.fail("First-pass generation must not run CanDo.")

    monkeypatch.setattr(generator_validation, "check_generated_structure", unexpected_cando)
    original = _source(aligned_four)
    centers = np.asarray([p.pose.to_array()[:3, 3] for p in original.nanoparticles])
    baseline = original.model_dump_json()
    settings = GeneratorSettings(
        shape="branched", branch_geometry="join", branch_scaffold_size=budget
    )
    candidate, report = plan_for_generation(original, settings)
    assert original.model_dump_json() == baseline
    assert len(candidate.design.scaffolds()) == 1
    selected_budget = report["selected"]["scaffold_size"]
    assert selected_budget in (7249, 8064)
    if budget != "auto":
        assert selected_budget == budget
    assert report["selected"]["scaffold_used_nt"] == selected_budget
    assert report["selected"]["unused_scaffold_nt"] == 0
    assert report["selected"]["sizing_validation"]["scaffold_count"] == 1
    assert "max_rmsf_nm" not in report["selected"]["sizing_validation"]
    if budget == "auto":
        assert {a["scaffold_size"] for a in report["alternatives"]} == {7249, 8064}
    assert (
        physical_scaffold_nt(candidate.design)
        == candidate.summary["budget_pre_staple_nt"]
    )
    assert min(report["selected"]["bridge_pair_counts"]) >= 2
    _, _, stem_axis = _cluster_axis(candidate.design, "branch_cluster_0")
    sections = {s["id"]: s for s in candidate.summary["join_sections"]}
    for crossbar in candidate.summary["join_crossbars"]:
        for index in crossbar["particle_indices"]:
            mapping = candidate.summary["join_attachments"][index]
            _, center, axis = _cluster_axis(
                candidate.design, mapping["cluster_id"], mapping["bp"]
            )
            target = np.asarray(
                sections[crossbar["cluster_id"]]["path"]["positions"][mapping["bp"]]
            )
            # A small normal offset can align additional short Join pairs;
            # the terminal axis must still pass through the NP in the plane.
            np.testing.assert_allclose(center[[0, 2]], target[[0, 2]], atol=1e-6)
            assert np.linalg.norm(np.cross(target - crossbar["junction"], axis)) < 1e-6
            assert abs(axis @ stem_axis) < np.cos(np.deg2rad(10))
            assert mapping["cluster_id"] == crossbar["cluster_id"]
            assert mapping["particle_id"] == original.nanoparticles[index].id
    if aligned_four:
        _assert_opposed_t_layout(candidate.summary, centers)
    planned_summary = deepcopy(candidate.summary)
    design, placement = build_recorded(original, candidate, settings)
    assert original.model_dump_json() == baseline
    assert candidate.summary == planned_summary
    section_cluster_ids = placement["join_section_cluster_ids"]
    assert set(section_cluster_ids) == {section["id"] for section in candidate.summary["join_sections"]}
    assert set(section_cluster_ids.values()) <= {cluster.id for cluster in design.cluster_transforms}
    assert len(set(section_cluster_ids.values())) == len(section_cluster_ids)
    for cluster_id in section_cluster_ids.values():
        UUID(cluster_id)
    assert len(design.scaffolds()) == 1
    assert validate_design(design).passed
    assert len(placement["connections"]) == len(original.nanoparticles)
    if aligned_four:
        assert all(c["reused"] for c in placement["connections"])
    normal = np.asarray(candidate.summary["base_frame"])[:, 1]
    _, _, stem_axis = _cluster_axis(design, "branch_cluster_0", section_cluster_ids=section_cluster_ids)
    for index, mapping in enumerate(candidate.summary["join_attachments"]):
        cluster, center, axis = _cluster_axis(
            design, mapping["cluster_id"], mapping["bp"], section_cluster_ids=section_cluster_ids
        )
        relative = centers[index] - center
        relative -= normal * (relative @ normal)
        assert np.linalg.norm(np.cross(relative, axis)) < 1e-6
        if mapping["cluster_id"] != "branch_cluster_0":
            assert abs(axis @ stem_axis) < np.cos(np.deg2rad(10))
        connection = next(
            c
            for c in placement["connections"]
            if c["particle_id"] == mapping["particle_id"]
        )
        overhang = next(
            o for o in design.overhangs if o.id == connection["overhang_id"]
        )
        anchor = design.find_strand(overhang.strand_id)
        embedded_ids = {d.helix_id for d in anchor.domains if not d.overhang_id}
        assert embedded_ids and embedded_ids <= set(cluster.helix_ids)
    assert max(placement["attachment_residuals_nm"]) < 0.02
    assert physical_scaffold_nt(design) == selected_budget
    assert len(design.scaffolds()[0].sequence) == selected_budget
    joins = [
        e for e in design.feature_log if getattr(e, "op_kind", None) == "cluster-join"
    ]
    assert (
        len(joins) == report["selected"]["branch_count"] == (2 if aligned_four else 1)
    )
    for entry in joins:
        before = state.decode_design_snapshot(entry.design_snapshot_gz_b64)
        after = state.decode_design_snapshot(entry.post_state_gz_b64)
        assert len(after.scaffolds()) == len(before.scaffolds()) - 1
        assert len(after.forced_ligations) > len(before.forced_ligations)
        assert entry.params["moving_cluster_id"] in {
            c.id for c in after.cluster_transforms
        }
    from backend.api.crud import _seek_feature_log

    live = design
    for entry in joins:
        index = design.feature_log.index(entry)
        expected = state.decode_design_snapshot(entry.post_state_gz_b64)
        live = _seek_feature_log(live, index)
        assert live.forced_ligations == expected.forced_ligations
        assert live.cluster_transforms == expected.cluster_transforms
        assert live.deformations == expected.deformations
    live = _seek_feature_log(live, -1)
    assert live.forced_ligations == design.forced_ligations
    assert live.cluster_transforms == design.cluster_transforms
    assert live.deformations == design.deformations
    for a, b in zip(original.nanoparticles, design.nanoparticles):
        np.testing.assert_array_equal(
            a.pose.to_array()[:3, 3], b.pose.to_array()[:3, 3]
        )
    restored = Design.model_validate_json(design.model_dump_json())
    assert restored.forced_ligations == design.forced_ligations
    assert derive_flexible_connections(restored)
    assert any(h.id.startswith("join_") for h in restored.helices)
