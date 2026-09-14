from fastapi.testclient import TestClient
import pytest
from fastapi import HTTPException

from backend.api import state as design_state
from backend.api.main import app
from backend.core.models import PhotoproductJunction
from tests.conftest import make_minimal_design


client = TestClient(app)


def _sequenced_design():
    design = make_minimal_design(helix_length_bp=8)
    strands = [
        strand.model_copy(update={"sequence": "T" * 8}) for strand in design.strands
    ]
    return design.copy_with(strands=strands)


def test_preflight_is_read_only_and_reports_relationship_and_capability():
    design_state.set_design(_sequenced_design())
    design_state.clear_history()
    revision = design_state.revision()
    response = client.post(
        "/api/design/photoproducts/preflight",
        json={
            "base_keys": ["h0:2:FORWARD", "h0:3:FORWARD"],
            "expected_revision": revision,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["eligible"] is True
    assert body["simulation_ready"] is False
    assert body["relationship"]["strand_relationship"] == "intrastrand"
    assert body["relationship"]["extra_pairing"] == "native-native"
    assert (
        body["reactant_geometry"]["interpretation"]
        == "placement input only; not a stability filter"
    )
    assert body["placement_report"]["status"] == "blocked_parameters_unavailable"
    assert body["placement_report"]["coordinates_modified"] is False
    assert design_state.revision() == revision
    assert design_state.undo_depth() == 0


def test_preflight_reports_antiparallel_interstrand_pair_without_using_a_geometry_gate():
    design_state.set_design(_sequenced_design())
    response = client.post(
        "/api/design/photoproducts/preflight",
        json={"base_keys": ["h0:2:FORWARD", "h0:2:REVERSE"]},
    )
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["eligible"] is True
    assert report["relationship"]["strand_relationship"] == "interstrand"
    assert report["relationship"]["source_classes"] == ["ordinary", "ordinary"]
    assert report["reactant_geometry"]["state"] == "reactant"
    assert report["simulation_ready"] is False


def test_catalog_and_toolchain_are_read_only_and_fail_closed():
    design_state.set_design(_sequenced_design())
    revision = design_state.revision()
    catalog = client.get("/api/design/photoproducts/catalog")
    assert catalog.status_code == 200, catalog.text
    body = catalog.json()
    assert [item["stereochemistry"] for item in body["products"]] == [
        "cis-syn",
        "cis-syn-II",
        "trans-syn-I",
        "trans-syn-II",
        "cis-anti-I",
        "cis-anti-II",
        "trans-anti-I",
        "trans-anti-II",
    ]
    assert not any(item["simulation_ready"] for item in body["products"])
    assert not any(item["help_trajectory"]["available"] for item in body["products"])
    trajectory = client.get(
        "/api/design/photoproducts/catalog/tt-cpd-cis-syn/model-trajectory"
    )
    assert trajectory.status_code == 409
    assert "NAMD smoke validation has not passed" in trajectory.json()["detail"]
    doctor = client.get("/api/design/photoproducts/toolchain")
    assert doctor.status_code == 200
    assert doctor.json()["simulation"]["namd"]
    assert design_state.revision() == revision


def test_non_cis_syn_form_can_be_requested_but_simulation_stays_gated():
    design_state.set_design(_sequenced_design())
    response = client.post(
        "/api/design/photoproducts",
        json={
            "base_keys": ["h0:2:FORWARD", "h0:3:FORWARD"],
            "stereochemistry": "trans-syn-I",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["photoproduct"]["stereochemistry"] == "trans-syn-I"
    assert body["preflight"]["simulation_ready"] is False
    assert body["preflight"]["placement_report"]["stereochemistry"] == "trans-syn-I"


def test_anti_preflight_reports_head_to_tail_candidate_bond_distances():
    design_state.set_design(_sequenced_design())
    response = client.post(
        "/api/design/photoproducts/preflight",
        json={
            "base_keys": ["h0:2:FORWARD", "h0:3:FORWARD"],
            "stereochemistry": "cis-anti-I",
        },
    )
    assert response.status_code == 200, response.text
    bonds = response.json()["reactant_geometry"]["candidate_product_bond_distances"]
    assert [(item["atom_1"], item["atom_2"]) for item in bonds] == [
        ("1:C5", "2:C6"),
        ("1:C6", "2:C5"),
    ]
    assert all(item["distance_nm"] is not None for item in bonds)


def test_create_delete_are_individually_undoable_and_revalidate_reuse():
    design_state.set_design(_sequenced_design())
    design_state.clear_history()
    response = client.post(
        "/api/design/photoproducts",
        json={
            "base_keys": ["h0:3:FORWARD", "h0:2:FORWARD"],
            "expected_revision": design_state.revision(),
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    lesion = body["photoproduct"]
    assert [lesion["base_key_1"], lesion["base_key_2"]] == [
        "h0:2:FORWARD",
        "h0:3:FORWARD",
    ]
    assert body["design"]["feature_log"][-1]["op_kind"] == "photoproduct-create"

    reused = client.post(
        "/api/design/photoproducts",
        json={
            "base_keys": ["h0:2:FORWARD", "h0:4:FORWARD"],
        },
    )
    assert reused.status_code == 422
    assert any(
        item["code"] == "endpoint_already_used"
        for item in reused.json()["detail"]["errors"]
    )

    deleted = client.delete(f"/api/design/photoproducts/{lesion['id']}")
    assert deleted.status_code == 200
    assert deleted.json()["design"]["photoproduct_junctions"] == []
    assert (
        deleted.json()["design"]["feature_log"][-1]["op_kind"] == "photoproduct-delete"
    )

    undone = client.post("/api/design/undo")
    assert len(undone.json()["design"]["photoproduct_junctions"]) == 1
    redone = client.post("/api/design/redo")
    assert redone.json()["design"]["photoproduct_junctions"] == []


def test_feature_log_seek_round_trips_manual_product_intent():
    design_state.set_design(_sequenced_design())
    design_state.clear_history()
    created = client.post(
        "/api/design/photoproducts",
        json={
            "base_keys": ["h0:2:FORWARD", "h0:3:FORWARD"],
        },
    )
    assert created.status_code == 200, created.text

    before = client.post("/api/design/features/seek", json={"position": -2})
    assert before.status_code == 200, before.text
    assert before.json()["design"]["photoproduct_junctions"] == []

    after = client.post("/api/design/features/seek", json={"position": -1})
    assert after.status_code == 200, after.text
    lesions = after.json()["design"]["photoproduct_junctions"]
    assert [(item["base_key_1"], item["base_key_2"]) for item in lesions] == [
        ("h0:2:FORWARD", "h0:3:FORWARD")
    ]


def test_http_atomistic_exports_fail_closed_for_product_design():
    design = _sequenced_design()
    lesion = PhotoproductJunction(base_key_1="h0:2:FORWARD", base_key_2="h0:3:FORWARD")
    design_state.set_design(design.copy_with(photoproduct_junctions=[lesion]))
    for path in (
        "/api/design/export/pdb",
        "/api/design/export/psf",
        "/api/design/export/namd-complete",
    ):
        response = client.get(path)
        assert response.status_code == 409, (path, response.text)
        detail = response.json()["detail"]
        assert detail["code"] == "cpd_parameters_unavailable"
        assert "two-bond/restraint fallback" in detail["message"]


def test_create_rejects_non_t_and_stale_revision_without_mutation():
    design = _sequenced_design()
    strands = list(design.strands)
    strands[0] = strands[0].model_copy(update={"sequence": "TATTTTTT"})
    design_state.set_design(design.copy_with(strands=strands))
    design_state.clear_history()
    non_t = client.post(
        "/api/design/photoproducts",
        json={
            "base_keys": ["h0:1:FORWARD", "h0:2:FORWARD"],
        },
    )
    assert non_t.status_code == 422
    assert design_state.get_or_404().photoproduct_junctions == []
    assert design_state.undo_depth() == 0

    stale = client.post(
        "/api/design/photoproducts",
        json={
            "base_keys": ["h0:2:FORWARD", "h0:3:FORWARD"],
            "expected_revision": design_state.revision() - 1,
        },
    )
    assert stale.status_code == 409
    assert design_state.get_or_404().photoproduct_junctions == []


def test_sequence_edit_cannot_leave_formed_product_non_thymine():
    design = _sequenced_design()
    lesion = PhotoproductJunction(base_key_1="h0:2:FORWARD", base_key_2="h0:3:FORWARD")
    design_state.set_design(design.copy_with(photoproduct_junctions=[lesion]))
    design_state.clear_history()

    def mutate(current):
        strands = list(current.strands)
        strands[0] = strands[0].model_copy(update={"sequence": "TTATTTTT"})
        return current.copy_with(strands=strands)

    with pytest.raises(HTTPException) as caught:
        design_state.mutate_with_feature_log(
            "strand-sequence", "Change sequence", {}, mutate
        )
    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "photoproduct_dependency"
    assert design_state.get_or_404().strands[0].sequence == "TTTTTTTT"
    assert design_state.undo_depth() == 0
