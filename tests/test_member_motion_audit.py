"""The offline ordering evidence is exact, isolated, and labelled as limited."""
import numpy as np
import pytest

from tools.member_motion_audit import build_case


@pytest.mark.parametrize("direction", ["FORWARD", "REVERSE"])
def test_ordering_probe_preserves_identity_and_shows_noncommuting_motion(direction):
    case = build_case(30, direction)
    assert case["provider"]["not_authorized_for_production"]
    assert case["read_only"]
    assert case["invariants"]["unselected_helix_exact"]
    assert case["current"]["bonds"] == case["candidate"]["bonds"]
    assert case["displacement"]["max_nm"] > 1
    assert case["junctions"]
    assert any(abs(j["length_delta_nm"]) > .1 for j in case["junctions"])
    assert case["current"]["nucleotides"] != case["candidate"]["nucleotides"]
    for side in ("current", "candidate"):
        count = len(case[side]["atoms"])
        for hit in case[side]["diagnostics"]["piercing"]["pierced"]:
            assert all(0 <= i < count for i in hit["bond_serials"] + hit["ring_serials"])


def test_commuting_control_has_no_displacement_and_equal_bond_lengths():
    case = build_case(170, prior_pose=False)
    assert case["displacement"]["n_displaced"] == 0
    assert case["displacement"]["max_nm"] == 0
    np.testing.assert_allclose([j["length_delta_nm"] for j in case["junctions"]], 0, atol=1e-12)


@pytest.mark.parametrize("prior", [False, True])
def test_chronological_artifact_identifies_native_later_event(prior):
    case = build_case(50, "REVERSE", prior_pose=prior, chronological=True)
    assert case["provider"]["id"] == "detached-native-prefix-chronological-motion"
    assert [e["feature_id"] for e in case["event_trace"]] == ["diagnostic-world-M", "later-world-delta"]
    assert case["case"]["later_D"]["translation"] == [3, -2, 1]
    assert bool(case["displacement"]["n_displaced"]) is prior


@pytest.mark.parametrize("direction", ["FORWARD", "REVERSE"])
@pytest.mark.parametrize("prior", [False, True])
def test_partial_artifact_keeps_all_unselected_material_exact(direction, prior):
    case = build_case(30, direction, prior_pose=prior, chronological=True, partial=True)
    assert case["case"]["partial"]
    assert case["invariants"]["unselected_material_exact"]
    assert case["invariants"]["selected_residue_count"] == (4 if direction == "FORWARD" else 5)
    assert bool(case["displacement"]["n_displaced"]) is prior
    assert len(case["event_trace"][0]["named_targets"]) == 2
    assert len(case["event_trace"][0]["material_keys"]) == case["invariants"]["selected_residue_count"]
    assert "unresolved" in case["provider"]["description"]
