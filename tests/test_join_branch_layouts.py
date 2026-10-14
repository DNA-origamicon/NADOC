"""Join layout search preserves cargo and supplies independent branch rays."""

import json
from pathlib import Path

import numpy as np
import pytest

from backend.core.join_branch_layouts import join_branch_layouts


def aligned_centers():
    source = json.loads(
        (Path(__file__).parent / "fixtures/4np_gen_aligned.json").read_text()
    )
    return np.array(
        [
            np.array(p.get("pose", {}).get("values", np.eye(4).ravel()))[[3, 7, 11]]
            for p in source["nanoparticles"]
        ]
    )


def test_aligned_layout_matches_connectivity_candidate_two():
    centers = aligned_centers()
    before = centers.copy()
    layouts = join_branch_layouts(centers)
    selected = layouts[0]
    assert selected["setback"] == 0.25
    assert selected["stem_particles"] == []
    np.testing.assert_allclose(
        selected["stem_start"], [4.685439271518181, 0, 19.529976477208702]
    )
    np.testing.assert_allclose(
        selected["stem_end"], [49.10682558769984, 0, 16.119010206493225]
    )
    assert [a["particle_index"] for a in selected["arms"]] == [0, 2, 1, 3]
    for arm in selected["arms"]:
        expected = (
            selected["stem_start"]
            if arm["particle_index"] in (0, 2)
            else selected["stem_end"]
        )
        assert arm["junction"] == expected
        stem_axis = np.subtract(selected["stem_end"], selected["stem_start"])
        branch_axis = centers[arm["particle_index"]] - arm["junction"]
        assert np.linalg.norm(np.cross(stem_axis, branch_axis)) > 1
    np.testing.assert_array_equal(centers, before)
    assert json.loads(json.dumps(layouts)) == layouts


def test_four_particles_cover_all_pairings_and_midpoint_variants():
    centers = aligned_centers()
    layouts = join_branch_layouts(centers)
    assert len(layouts) == 6
    pairings = set()
    for layout in layouts:
        left = tuple(
            arm["particle_index"]
            for arm in layout["arms"]
            if arm["junction"] == layout["stem_start"]
        )
        pairings.add(left)
        if layout["setback"] == 0:
            right = [i for i in range(4) if i not in left]
            np.testing.assert_allclose(
                layout["stem_start"], centers[list(left)].mean(0)
            )
            np.testing.assert_allclose(layout["stem_end"], centers[right].mean(0))
    assert pairings == {(0, 1), (0, 2), (0, 3)}


def test_symmetric_layout_skips_coincident_junctions():
    centers = np.array([[-20, 0, -10], [20, 0, -10], [20, 0, 10], [-20, 0, 10]])
    layouts = join_branch_layouts(centers)
    assert len(layouts) == 4
    for layout in layouts:
        assert np.linalg.norm(np.subtract(layout["stem_end"], layout["stem_start"])) > 1
        for arm in layout["arms"]:
            assert np.linalg.norm(centers[arm["particle_index"]] - arm["junction"]) > 1


def test_three_particles_try_each_stem_terminal():
    centers = np.array([[-25, 0, -20], [25, 0, -20], [0, 0, 30]])
    before = centers.copy()
    layouts = join_branch_layouts(centers)
    assert len(layouts) == 6
    assert {tuple(layout["stem_particles"]) for layout in layouts} == {(0,), (1,), (2,)}
    for layout in layouts:
        singleton = layout["stem_particles"][0]
        np.testing.assert_array_equal(layout["stem_start"], centers[singleton])
        assert {arm["particle_index"] for arm in layout["arms"]} == set(range(3)) - {
            singleton
        }
        assert all(arm["junction"] == layout["stem_end"] for arm in layout["arms"])
    np.testing.assert_array_equal(centers, before)


def test_layouts_follow_world_rotation_and_translation():
    centers = aligned_centers()
    transform = np.array([[0, 0, 1], [1, 0, 0], [0, 1, 0]])
    offset = np.array([10, 25, -7])
    layouts = join_branch_layouts(centers)
    moved = join_branch_layouts(centers @ transform + offset)
    for original, changed in zip(layouts, moved, strict=True):
        for name in ("stem_start", "stem_end"):
            np.testing.assert_allclose(
                changed[name], np.array(original[name]) @ transform + offset
            )
        for arm, moved_arm in zip(original["arms"], changed["arms"], strict=True):
            assert arm["particle_index"] == moved_arm["particle_index"]
            np.testing.assert_allclose(
                moved_arm["junction"], np.array(arm["junction"]) @ transform + offset
            )


@pytest.mark.parametrize(
    "centers",
    [np.zeros((2, 3)), np.zeros((3, 2)), np.zeros((3, 3)), np.full((4, 3), np.nan)],
)
def test_invalid_centers_rejected(centers):
    with pytest.raises(ValueError, match="centers"):
        join_branch_layouts(centers)
