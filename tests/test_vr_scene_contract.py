"""Stable native-VR scene contract parsing and diagnostic comparison."""

from pathlib import Path

import pytest

from backend.core.vr_scene_contract import (
    SceneTolerance,
    compare_scenes,
    parse_scene_v6,
)


FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "native"
    / "vr_viewer"
    / "examples"
    / "triangle.nadocvr"
)


def test_v6_fixture_has_unique_identities_in_every_representation() -> None:
    scene = parse_scene_v6(FIXTURE.read_text())

    assert set(scene) == {"full", "cylinders", "ballstick", "stick"}
    assert scene["full"]["triangle:a"].record_type == "P"
    assert scene["cylinders"]["triangle:ab"].record_type == "H"


def test_parser_rejects_duplicate_identity_in_one_representation() -> None:
    duplicate = """NADOCVR 6 full strand
R full
P same 0 0 0 .1 1 1 1 1 1 1 1 1 1 1 1 1
P same 1 0 0 .1 1 1 1 1 1 1 1 1 1 1 1 1
"""

    with pytest.raises(ValueError, match="duplicate identity same in full"):
        parse_scene_v6(duplicate)


def test_comparator_matches_within_tolerance_and_reports_semantic_owner() -> None:
    expected = FIXTURE.read_text()
    actual = expected.replace(
        "P triangle:a -1 0 0 .18", "P triangle:a -0.9999995 0 0 .18"
    )
    comparison = compare_scenes(expected, actual)
    assert comparison.ok

    moved = expected.replace("P triangle:a -1 0 0 .18", "P triangle:a -0.99 0 0 .18")
    comparison = compare_scenes(expected, moved)
    assert not comparison.ok
    assert comparison.differences[0].identity == "triangle:a"
    assert comparison.differences[0].category == "position"
    assert "full/triangle:a" in comparison.summary()


def test_comparator_separates_type_geometry_orientation_dimension_and_color() -> None:
    expected = """NADOCVR 6 full strand
R full
B owner:slab 0 0 0 .3 0 0 0 .06 0 0 0 .7 1 0 0 1 0 0 1 0 0 1 0 0
"""
    actual = """NADOCVR 6 full strand
R full
B owner:slab .01 0 0 0 .31 0 0 .06 0 0 0 .7 .5 0 0 1 0 0 1 0 0 1 0 0
"""
    comparison = compare_scenes(
        expected,
        actual,
        SceneTolerance(position_nm=1e-6, dimension_nm=1e-6, orientation_deg=1e-5),
    )

    assert {difference.category for difference in comparison.differences} == {
        "position",
        "dimension",
        "orientation",
        "color",
    }


def test_comparator_reports_missing_unexpected_and_type_changes() -> None:
    expected = """NADOCVR 6 full strand
R full
P retained 0 0 0 .1 1 1 1 1 1 1 1 1 1 1 1 1
P removed 0 0 0 .1 1 1 1 1 1 1 1 1 1 1 1 1
"""
    actual = """NADOCVR 6 full strand
R full
C retained 0 0 0 1 0 0 .1 1 1 1 1 1 1 1 1 1 1 1 1
P added 0 0 0 .1 1 1 1 1 1 1 1 1 1 1 1 1
"""

    comparison = compare_scenes(expected, actual)
    assert [
        (difference.identity, difference.category)
        for difference in comparison.differences
    ] == [
        ("removed", "missing"),
        ("added", "unexpected"),
        ("retained", "type"),
    ]
