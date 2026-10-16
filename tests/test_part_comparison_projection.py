"""Display-only projection closure and exact native placement parity."""

from copy import deepcopy

import numpy as np
import pytest

from backend.core.models import (
    Design, Helix, Mat4x4, Nanoparticle, ProteinAsset, ProteinAtom,
    ProteinAttachment, ProteinTargetFree, QuantumDotSpec,
)
from backend.core.part_command_errors import CommandContractError
from backend.core.part_comparison_projection import (
    MAX_PLACEMENTS, MAX_PROJECTED_ATOMS, check_scope, compare, decode_candidate, parse_request, project,
)
from backend.core.protein import compose_protein_world_transform, protein_asset_to_atomistic


def asset_part():
    design = Design(id="part")
    pose = Mat4x4(values=[0., -1., 0., 4., 1., 0., 0., -2., 0., 0., 1., 3., 0., 0., 0., 1.])
    design.nanoparticles = [Nanoparticle(id="gold", diameter_nm=10., pose=pose, visible=False)]
    design.protein_assets = [ProteinAsset(id="protein", atoms=[
        ProteinAtom(serial=1, name="CA", element="C", res_name="ALA", chain_id="A", res_seq=1, x=1., y=2., z=3.),
        ProteinAtom(serial=2, name="N", element="N", res_name="ALA", chain_id="A", res_seq=1, x=2., y=2., z=3.),
    ], bonds=[(0, 1)])]
    design.protein_attachments = [ProteinAttachment(id="placed", asset_id="protein", target=ProteinTargetFree(), pose=pose)]
    return design


def test_complete_projection_uses_exact_native_world_placement_without_mutation():
    design = asset_part()
    before = design.model_dump_json()
    result = project(design)
    particle = result["particles"][0]
    assert particle["pose"] == design.nanoparticles[0].pose.values
    assert particle["authored_visible"] is False
    asset, attachment = design.protein_assets[0], design.protein_attachments[0]
    expected = protein_asset_to_atomistic(asset,
        pose_matrix=compose_protein_world_transform(asset, attachment), sentinel_id=attachment.id)
    actual = result["proteins"][0]
    assert actual["representation"] == "trace"
    assert [(a["x"], a["y"], a["z"]) for a in actual["atoms"]] == [(a.x, a.y, a.z) for a in expected.atoms]
    assert {a["helix_id"] for a in actual["atoms"]} == {"__protein__placed"}
    assert result["bounds_nm"] == {"minimum": [-1., -7., -2.], "maximum": [9., 3., 8.]}
    assert design.model_dump_json() == before


def test_protein_without_alpha_carbon_has_explicit_nonempty_ovoid_representation():
    design = asset_part()
    design.protein_assets[0].atoms[0].name = "C"
    result = project(design)
    assert result["proteins"][0]["representation"] == "ovoid"
    assert len(result["proteins"][0]["atoms"]) == 2


def test_quantum_dot_keeps_exact_authored_size_pose_and_catalog_color():
    design = asset_part()
    particle = design.nanoparticles[0]
    particle.kind = "quantum_dot"
    particle.quantum_dot = QuantumDotSpec(catalog_id="test", catalog_version="1", vendor="Test",
        product_name="Dot", product_code="test", product_url="https://example.test", composition="CdSe",
        emission_peak_nm=525., diameter_range_nm=(8., 12.), size_basis="catalog", size_source_url="https://example.test",
        surface_coating="none", functionalization="none", display_color="#58d65d",
        spectra={"source_url": "https://example.test", "source_page": 1, "plot_file": "plot.png", "sha256": "a" * 64,
                 "note": "Test provenance"})
    result = project(design)["particles"][0]
    assert result["display_color"] == "#58d65d" and result["kind"] == "quantum_dot"
    assert result["diameter_nm"] == particle.diameter_nm and result["pose"] == particle.pose.values


def test_unplaced_library_asset_is_reported_without_inventing_placement():
    design = asset_part()
    design.protein_attachments = []
    assert project(design)["unplaced_asset_ids"] == ["protein"]
    assert project(design)["proteins"] == []


def test_two_panes_are_read_only_authored_state_not_a_design_or_certificate():
    source = asset_part()
    candidate = source.model_copy(deep=True)
    candidate.nanoparticles[0].diameter_nm = 12.
    result = compare(source, candidate.model_dump(mode="json"))
    assert result["status"] == "projected"
    assert result["coverage"] == {"complete": True, "scientific_qualification": False,
        "visibility": "all_authored_placements", "excluded_layers": ["physical", "presentation"]}
    assert result["published"]["particles"][0]["diameter_nm"] == 10.
    assert result["proposed"]["particles"][0]["diameter_nm"] == 12.
    assert not ({"design", "candidate", "native_editable", "ready", "input_sources", "feature_log"} & result.keys())
    assert project(Design())["bounds_nm"] is None


@pytest.mark.parametrize("change", ["helix", "coating", "attached", "missing_asset", "duplicate_particle",
                                   "duplicate_asset", "duplicate_attachment", "missing_qd"])
def test_unsupported_or_incomplete_family_refuses_entire_comparison(change):
    design = asset_part()
    if change == "helix":
        design.helices = [Helix(id="h", axis_start={"x": 0, "y": 0, "z": 0},
                               axis_end={"x": 0, "y": 0, "z": 7}, length_bp=21)]
    elif change == "coating":
        design.nanoparticles[0].coating = object()
    elif change == "attached":
        design.protein_attachments[0].binder_strand_id = "binder"
    elif change == "missing_asset":
        design.protein_assets = []
    elif change == "duplicate_particle":
        design.nanoparticles *= 2
    elif change == "duplicate_asset":
        design.protein_assets *= 2
    elif change == "duplicate_attachment":
        design.protein_attachments *= 2
    else:
        design.nanoparticles[0].kind = "quantum_dot"
    with pytest.raises(CommandContractError):
        project(design)


@pytest.mark.parametrize("change", ["count", "atoms", "scaled_particle", "nonfinite", "negative_diameter"])
def test_bounds_and_unsupported_pose_refuse_before_success(change):
    design = asset_part()
    if change == "count":
        design.nanoparticles = [Nanoparticle(id=str(i), diameter_nm=10) for i in range(MAX_PLACEMENTS + 1)]
    elif change == "atoms":
        design.protein_assets[0].atoms = design.protein_assets[0].atoms[:1] * (MAX_PROJECTED_ATOMS + 1)
    elif change == "scaled_particle":
        design.nanoparticles[0].pose = Mat4x4(values=np.diag([2., 2., 2., 1.]).flatten().tolist())
    elif change == "nonfinite":
        design.protein_assets[0].atoms[0].x = float("nan")
    else:
        design.nanoparticles[0].diameter_nm = -10.
    with pytest.raises(CommandContractError):
        project(design)


def test_future_design_fields_fail_closed(monkeypatch):
    from backend.core import part_comparison_projection as projection
    monkeypatch.setattr(projection, "FIELD_ROLES", {**projection.FIELD_ROLES, "future_geometry": "authoring"})
    with pytest.raises(CommandContractError, match="schema"):
        check_scope(asset_part())


def test_long_mutated_identity_is_refused_before_dictionary_hashing():
    class UnhashableIdentity(str):
        def __hash__(self):
            pytest.fail("Unadmitted identity was hashed")
    design = asset_part()
    design.nanoparticles[0].id = UnhashableIdentity("x" * 1000)
    with pytest.raises(CommandContractError, match="bounded"):
        check_scope(design)


def test_pdb_angstroms_are_converted_once_by_native_import_before_nm_projection():
    from backend.core.protein import parse_protein_pdb
    pdb = "ATOM      1  CA  ALA A   1      10.000  20.000  30.000  1.00 20.00           C  \nEND\n"
    asset = parse_protein_pdb(pdb)
    design = Design(protein_assets=[asset], protein_attachments=[ProteinAttachment(
        id="placed", asset_id=asset.id, target=ProteinTargetFree())])
    result = project(design)
    atom = result["proteins"][0]["atoms"][0]
    assert [atom["x"], atom["y"], atom["z"]] == [1., 2., 3.]
    assert result["units"] == "nm"
    assert result["bounds_nm"] == {"minimum": [1., 2., 3.], "maximum": [1., 2., 3.]}


@pytest.mark.parametrize("projection", ["authoring", "recipe"])
def test_candidate_decode_cannot_normalize_evaluated_inputs(monkeypatch, projection):
    source = asset_part()
    data = source.model_dump(mode="json")
    original = Design.model_validate
    def normalize(value):
        decoded = original(value)
        if projection == "authoring":
            decoded.nanoparticles[0].diameter_nm = 11.
        else:
            decoded.feature_log_cursor = 0
        return decoded
    monkeypatch.setattr(Design, "model_validate", normalize)
    with pytest.raises(CommandContractError) as error:
        decode_candidate(data)
    assert error.value.code == f"candidate_decode_changed_{projection}"


def test_candidate_must_belong_to_captured_part():
    source = asset_part()
    candidate = source.model_copy(update={"id": "another"})
    with pytest.raises(CommandContractError, match="another part"):
        compare(source, candidate.model_dump(mode="json"))


@pytest.mark.parametrize("field,value", [("projection_version", 3), ("expected_revision", True),
    ("expected_generation", -1), ("candidate", {}), ("pose", [0] * 16), ("expected_source", "client")])
def test_request_accepts_only_versioned_context_not_geometry_or_authority(field, value):
    body = {"projection_version": 1, "expected_design_id": "part", "expected_revision": 7,
            "expected_draft_id": "proposal", "expected_generation": 3, field: value}
    with pytest.raises(ValueError):
        parse_request(body)


def test_candidate_and_source_transport_values_are_not_changed_by_projection():
    source = asset_part()
    candidate = source.model_dump(mode="json")
    before = deepcopy(candidate)
    compare(source, candidate)
    assert candidate == before
