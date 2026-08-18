"""Stable native-VR scene contract parsing and diagnostic comparison."""

from pathlib import Path

import pytest

from backend.core.vr_scene_contract import (
    SceneTolerance,
    compare_scenes,
    parse_scene_contract,
    parse_scene_v6,
)


FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "native"
    / "vr_viewer"
    / "examples"
    / "triangle.nadocvr"
)
V11_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "native"
    / "vr_viewer"
    / "examples"
    / "semantic_atom_v11.nadocvr"
)
V12_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "native"
    / "vr_viewer"
    / "examples"
    / "tool_scope_v12.nadocvr"
)


def test_v6_fixture_has_unique_identities_in_every_representation() -> None:
    scene = parse_scene_v6(FIXTURE.read_text())

    assert set(scene) == {"full", "cylinders", "ballstick", "stick"}
    assert scene["full"]["triangle:a"].record_type == "P"
    assert scene["cylinders"]["triangle:ab"].record_type == "H"


def test_v11_fixture_accepts_semantic_atom_and_bond_identities() -> None:
    scene = parse_scene_contract(V11_FIXTURE.read_text())
    identities = set(scene["ballstick"])
    assert any(identity.startswith("atom-ref:") for identity in identities)
    assert any(identity.startswith("atom-bond-ref:") for identity in identities)


def test_v12_fixture_locks_generalized_handles_and_endpoint_ownership() -> None:
    scene = parse_scene_contract(V12_FIXTURE.read_text())

    assert scene["ballstick"]["atom-token"].tool_scope_kind == "atom"
    assert scene["ballstick"]["boundary-bond"].tool_scope_owners == (
        ("cluster-token", 1.0, 0.0),
        ("base-token", 1.0, 0.0),
        ("atom-token", 1.0, 0.0),
    )

    changed = V12_FIXTURE.read_text().replace(
        "W boundary-bond 3 c 1 0 b 1 0 a 1 0",
        "W boundary-bond 3 c 1 0 b 1 1 a 1 0",
        1,
    )
    comparison = compare_scenes(V12_FIXTURE.read_text(), changed)
    assert "tool_scope_owner" in {
        difference.category for difference in comparison.differences
    }


def test_v12_rejects_unknown_or_duplicate_tool_scope_handles() -> None:
    text = V12_FIXTURE.read_text()
    with pytest.raises(ValueError, match="invalid tool-scope owner"):
        parse_scene_contract(text.replace("a 1 0", "missing-id 1 0", 1))
    with pytest.raises(ValueError, match="invalid tool handle"):
        parse_scene_contract(text.replace("J a atom-token atom", "J a base-token atom", 1))


def test_parser_rejects_duplicate_identity_in_one_representation() -> None:
    duplicate = """NADOCVR 6 full strand
R full
P same 0 0 0 .1 1 1 1 1 1 1 1 1 1 1 1 1
P same 1 0 0 .1 1 1 1 1 1 1 1 1 1 1 1 1
"""

    with pytest.raises(ValueError, match="duplicate identity same in full"):
        parse_scene_v6(duplicate)


def test_v7_parser_compares_natural_and_expanded_poses_independently() -> None:
    scene = parse_scene_contract(
        """NADOCVR 7 full strand
R full
P owner 0 0 0 .1 1 1 1 1 1 1 1 1 1 1 1 1
E full
P owner 2 0 0 .1 1 1 1 1 1 1 1 1 1 1 1 1
"""
    )

    assert set(scene) == {"full", "expanded/full"}
    assert scene["full"]["owner"].values[0] == 0
    assert scene["expanded/full"]["owner"].values[0] == 2


def test_v8_parser_attaches_bounded_owner_aliases_to_existing_primitives() -> None:
    text = """NADOCVR 8 full strand
R full
P owner 0 0 0 .1 1 1 1 1 1 1 1 1 1 1 1 1
A owner 2 base-owner domain-owner
"""
    scene = parse_scene_contract(text)
    assert scene["full"]["owner"].owner_aliases == (
        "base-owner",
        "domain-owner",
    )

    with pytest.raises(ValueError, match="unknown identity missing"):
        parse_scene_contract(text.replace("A owner", "A missing"))
    with pytest.raises(ValueError, match="invalid owner alias count"):
        parse_scene_contract(text.replace("A owner 2", "A owner 3"))


def test_v8_comparator_reports_owner_alias_regressions() -> None:
    expected = """NADOCVR 8 full strand
R full
P owner 0 0 0 .1 1 1 1 1 1 1 1 1 1 1 1 1
A owner 1 base-owner
"""
    actual = expected.replace("base-owner", "domain-owner")

    comparison = compare_scenes(expected, actual)

    assert [difference.category for difference in comparison.differences] == ["owner"]


def test_v9_parser_and_comparator_lock_cluster_handle_positions() -> None:
    expected = """NADOCVR 9 full strand
R full
K cluster-owner 1 2 3
P owner 0 0 0 .1 1 1 1 1 1 1 1 1 1 1 1 1
"""
    scene = parse_scene_contract(expected)
    assert scene["full"]["cluster-owner"].record_type == "K"
    assert scene["full"]["cluster-owner"].values == (1.0, 2.0, 3.0)

    moved = expected.replace("K cluster-owner 1 2 3", "K cluster-owner 1.01 2 3")
    comparison = compare_scenes(expected, moved)
    handle_difference = next(
        difference
        for difference in comparison.differences
        if difference.identity == "cluster-owner"
    )
    assert handle_difference.category == "position"
    assert "handle error" in handle_difference.detail

    with pytest.raises(ValueError, match="cluster handles require v9"):
        parse_scene_contract(expected.replace("NADOCVR 9", "NADOCVR 8"))


def test_v10_parser_locks_endpoint_transform_ownership() -> None:
    expected = """NADOCVR 10 full strand
R full
K cluster-owner 1 2 3
C boundary-bond 0 0 0 1 0 0 .1 1 1 1 1 1 1 1 1 1 1 1 1
T boundary-bond 1 cluster-owner 1 0
"""
    scene = parse_scene_contract(expected)
    assert scene["full"]["boundary-bond"].transform_owners == (
        ("cluster-owner", 1.0, 0.0),
    )

    changed = expected.replace("cluster-owner 1 0", "cluster-owner 1 1")
    comparison = compare_scenes(expected, changed)
    assert [difference.category for difference in comparison.differences] == [
        "transform_owner"
    ]

    with pytest.raises(ValueError, match="transform owners require v10"):
        parse_scene_contract(expected.replace("NADOCVR 10", "NADOCVR 9"))
    with pytest.raises(ValueError, match="invalid transform owner"):
        parse_scene_contract(
            expected.replace("cluster-owner 1 0", "cluster-owner 1.1 0")
        )


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
