"""Continuous crossbars retain terminal directions and stationary NP stations."""

from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest

from backend.core.join_branch_layouts import join_branch_layouts
from backend.core.join_crossbars import crossbar_summary
from backend.core.constants import BDNA_RISE_PER_BP as RISE
from backend.core.models import Design
from backend.core.sweep_model import SweepParams


@pytest.fixture
def source_centers():
    source = Design.model_validate_json(
        (Path(__file__).parent / "fixtures/4np_gen_aligned.json").read_text()
    )
    return source, np.array([p.pose.to_array()[:3, 3] for p in source.nanoparticles])


def gentle_layout(centers):
    layout = deepcopy(join_branch_layouts(centers)[1])
    left, right = np.array(layout["stem_start"]), np.array(layout["stem_end"])
    start = left + (right - left) * 0.05
    end = right - (right - start) * 0.1
    for arm in layout["arms"]:
        arm["junction"] = (
            start if arm["junction"] == layout["stem_start"] else end
        ).tolist()
    layout.update(stem_start=start.tolist(), stem_end=end.tolist(), setback=0.1)
    return layout


def local_centers(centers, summary):
    frame = np.array(summary["base_frame"])
    projected = (centers - centers.mean(0)) @ frame
    projected[:, [0, 2]] -= (
        projected[:, [0, 2]].min(0) + projected[:, [0, 2]].max(0)
    ) / 2
    projected[:, 1] = 0
    return projected


def test_continuous_curved_crossbars_keep_two_junctions_and_point_at_particles(
    source_centers,
):
    source, centers = source_centers
    baseline = source.model_dump_json()
    before = centers.copy()
    summary = crossbar_summary(source, centers, gentle_layout(centers), 12, 12)
    assert summary["join_curved"]
    assert len(summary["join_sections"]) == 3
    assert len(summary["join_crossbars"]) == summary["branch_count"] == 2
    assert all(0 < c["outer_strain"] < 0.35 for c in summary["join_crossbars"])
    local = local_centers(centers, summary)
    for section, crossbar in zip(
        summary["join_sections"][1:], summary["join_crossbars"], strict=True
    ):
        path = section["path"]
        points = np.array(path["positions"])
        frames = np.array(path["frames"]).reshape(-1, 3, 3)
        assert len(points) == section["length_bp"]
        np.testing.assert_allclose(
            points[crossbar["join_bp"]], crossbar["junction"], atol=1e-12
        )
        lo, hi = crossbar["join_interval"]
        np.testing.assert_allclose(
            frames[lo : hi + 1], np.tile(frames[lo], (hi - lo + 1, 1, 1))
        )
        SweepParams(
            points_nm=[points[0].tolist(), points[-1].tolist()],
            origin_nm=(0, 0, 0),
            initial_rotation=path["frames"][0],
            steps=len(points) - 1,
            path_length_nm=(len(points) - 1) * RISE,
            bp_positions_nm=path["positions"],
            bp_frames=path["frames"],
        )
        for end_index, particle_index in enumerate(crossbar["particle_indices"]):
            station = summary["join_attachments"][particle_index]
            assert station["cluster_id"] == section["id"]
            np.testing.assert_allclose(
                points[station["bp"]], local[particle_index], atol=1e-10
            )
            outward = local[particle_index] - crossbar["junction"]
            outward /= np.linalg.norm(outward)
            np.testing.assert_allclose(
                frames[station["bp"], :, 2],
                outward * (-1 if end_index == 0 else 1),
                atol=1e-10,
            )
    assert source.model_dump_json() == baseline
    np.testing.assert_array_equal(centers, before)


def test_crossbar_tail_budget_adjustment_does_not_move_particle_or_join_stations(
    source_centers,
):
    source, centers = source_centers
    layout = gentle_layout(centers)
    short = crossbar_summary(source, centers, layout, 12, 12, tail_bp=[21, 21])
    longer = crossbar_summary(source, centers, layout, 12, 12, tail_bp=[22, 35])
    assert (
        longer["join_sections"][1]["length_bp"] - short["join_sections"][1]["length_bp"]
        == 2
    )
    assert (
        longer["join_sections"][2]["length_bp"] - short["join_sections"][2]["length_bp"]
        == 28
    )
    for i in range(4):
        a, b = short["join_attachments"][i], longer["join_attachments"][i]
        sa = next(s for s in short["join_sections"] if s["id"] == a["cluster_id"])
        sb = next(s for s in longer["join_sections"] if s["id"] == b["cluster_id"])
        np.testing.assert_allclose(
            sa["path"]["positions"][a["bp"]], sb["path"]["positions"][b["bp"]]
        )
    for a, b in zip(short["join_crossbars"], longer["join_crossbars"], strict=True):
        assert a["junction"] == b["junction"]


def test_midpoint_pairing_uses_continuous_straight_crossbars_and_reserves_stem_caps(
    source_centers,
):
    source, centers = source_centers
    summary = crossbar_summary(source, centers, join_branch_layouts(centers)[1], 12, 12)
    assert all(c["outer_strain"] < 1e-10 for c in summary["join_crossbars"])
    stem = summary["join_sections"][0]
    assert stem["span_nm"] - (stem["length_bp"] - 1) * RISE >= 14 * RISE
    np.testing.assert_allclose(
        np.array(stem["position"]) + [0, 0, (stem["length_bp"] - 1) * RISE / 2],
        stem["fit_center"],
    )


def test_tight_curves_rejected_before_routing(source_centers):
    source, centers = source_centers
    with pytest.raises(ValueError, match="strain"):
        crossbar_summary(source, centers, join_branch_layouts(centers)[0], 12, 12)


def test_single_bp_budget_extensions_preserve_particle_and_join_stations(
    source_centers,
):
    from backend.core.joined_branches import _continuous_layouts, _extend_crossbar_tails

    source, centers = source_centers
    original = crossbar_summary(
        source, centers, next(_continuous_layouts(centers)), 24, 12
    )
    extended = _extend_crossbar_tails(original, (1, 13))
    for a, b, extra in zip(
        original["join_sections"][1:], extended["join_sections"][1:], (1, 13)
    ):
        assert b["length_bp"] == a["length_bp"] + extra
        assert len(b["path"]["positions"]) == b["length_bp"]
        for before, after in zip(
            original["join_attachments"], extended["join_attachments"]
        ):
            if before["cluster_id"] == a["id"]:
                np.testing.assert_allclose(
                    a["path"]["positions"][before["bp"]],
                    b["path"]["positions"][after["bp"]],
                )
                np.testing.assert_allclose(
                    a["path"]["frames"][before["bp"]], b["path"]["frames"][after["bp"]]
                )
    for before, after in zip(original["join_crossbars"], extended["join_crossbars"]):
        assert before["junction"] == after["junction"]
