import pytest

from tools.member_motion_tail_audit import build_tail_case


@pytest.mark.parametrize("end", ["five_prime", "three_prime"])
@pytest.mark.parametrize("direction", ["FORWARD", "REVERSE"])
def test_tail_hypotheses_keep_representation_changes_separate(end, direction):
    full = build_tail_case(0, direction, end, "full-follows")
    atoms = build_tail_case(0, direction, end, "atoms-stay")
    assert len(full["current_design"]["helices"]) == 2
    assert full["current"]["atoms"] == full["candidate"]["atoms"]
    assert full["displacement"]["n_displaced"] == 0
    assert full["full_displacement"]["n_displaced"] == 2
    assert full["full_displacement"]["max_nm"] > 1
    assert atoms["current"]["nucleotides"] == atoms["candidate"]["nucleotides"]
    assert atoms["full_displacement"]["n_displaced"] == 0
    assert atoms["displacement"]["n_displaced"] == 0
    # The user-approved atoms-stay hypothesis now matches production locality.
    assert atoms["current"]["atoms"] == atoms["candidate"]["atoms"]
    for serial in full["full_affected_atom_serials"]:
        # Detector hits can include other material; moved Full records must
        # resolve by extension identity, never their atomistic anchor address.
        row = full["current"]["atoms"][serial]
        assert row["material_key"]
    for old, new in zip(atoms["current"]["atoms"], atoms["candidate"]["atoms"], strict=True):
        if not old["material_key"].startswith("__ext_selected-tail:"):
            assert old == new
    for row in full["candidate"]["nucleotides"]:
        if row.get("extension_id") == "selected-tail":
            assert row["slab_position"] is None and row["slab_quaternion"] is None
            assert not row.get("helical_site")
