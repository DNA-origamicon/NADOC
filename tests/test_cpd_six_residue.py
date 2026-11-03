from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from backend.api import state
from backend.api.main import app
from backend.core.atomistic import build_atomistic_model
from backend.core.base_keys import atom_base_key
from backend.core.cpd_conversion import (
    convert_thymine_pair,
    prepare_conversion,
    BASE_NAMES,
)
from backend.core.cpd_forcefield import (
    assert_cpd_simulation_supported,
)
from backend.core.design_geometry import _geometry_for_design
from backend.core.models import Design, NucleotideTransform


def fixture():
    d = Design.from_json(Path("tests/fixtures/cpd_six_residue_1xt.nadoc").read_text())
    return d, [f"__xb__:{x.id}:0" for x in d.crossovers if x.extra_bases == "T"]


@pytest.mark.parametrize(
    "stereo", ["cis-syn", "trans-syn-I", "trans-syn-II", "cis-anti-I"]
)
def test_six_residue_preview_commit_reload_and_removal(stereo):
    d, keys = fixture()
    original = d.to_json()
    before = build_atomistic_model(d)
    converted, preview = convert_thymine_pair(d, keys, stereo)
    assert prepare_conversion(d, keys[::-1], stereo)[1] == preview
    assert d.to_json() == original
    restored = Design.from_json(converted.to_json())
    lesion = restored.photoproduct_junctions[0]
    assert len(lesion.context_coordinates) == 4
    assert lesion.bond_relaxation["flanking_bases_fixed"]
    assert not lesion.bond_relaxation["backbone_fixed"]
    assert max(preview["glycosidic_distances_nm"]) < 0.16
    assert all(0.13 < x < 0.19 for x in preview["placement"]["attachment_distances_nm"])
    after = build_atomistic_model(restored)
    actual = {
        f"{atom_base_key(a)}:{a.name}": np.array([a.x, a.y, a.z]) for a in after.atoms
    }
    for key, xyz in zip(preview["atom_keys"], preview["positions"]):
        np.testing.assert_allclose(actual[key], xyz, atol=1e-12)
    moved = set()
    for a, b in zip(before.atoms, after.atoms):
        key = atom_base_key(a)
        if key not in keys and (
            key not in lesion.context_coordinates
            or a.name in BASE_NAMES
            or a.name not in lesion.context_coordinates[key]
        ):
            assert (a.x, a.y, a.z) == (b.x, b.y, b.z)
        if (a.x, a.y, a.z) != (b.x, b.y, b.z):
            moved.add(key)
    assert moved == set(keys) | set(lesion.context_coordinates)
    g0, g1 = _geometry_for_design(d), _geometry_for_design(restored)
    assert (
        sum(a["backbone_position"] != b["backbone_position"] for a, b in zip(g0, g1))
        == 4
    )
    for a, b in zip(g0, g1):
        assert a["slab_position"] == b["slab_position"]
        assert a["slab_quaternion"] == b["slab_quaternion"]
    removed = restored.copy_with(photoproduct_junctions=[])
    assert _geometry_for_design(removed) == g0
    assert build_atomistic_model(removed).atoms == before.atoms
    assert_cpd_simulation_supported(restored, path="test")


def test_reject_incompatible_flanking_geometry_and_overlap():
    d, keys = fixture()
    converted, preview = convert_thymine_pair(d, keys, "cis-syn")
    flank = preview["placement"]["context_keys"][0]
    h, bp, direction = flank.split(":")
    shifted = d.copy_with(
        nucleotide_transforms=[
            NucleotideTransform(
                kind="base",
                helix_id=h,
                bp_index=int(bp),
                direction=direction,
                translation=[1.0, 0.0, 0.0],
            )
        ]
    )
    with pytest.raises(ValueError, match="context differs|attachments"):
        prepare_conversion(shifted, keys, "cis-syn")
    with pytest.raises(ValueError, match="already belongs"):
        prepare_conversion(converted, [flank, keys[0]], "cis-syn")


def test_preview_api_undo_and_delete_restore_context():
    client = TestClient(app)
    d, keys = fixture()
    state.set_design(d)
    state.clear_history()
    body = {
        "base_keys": keys,
        "stereochemistry": "cis-anti-I",
        "placement": "contextual",
        "expected_revision": state.revision(),
    }
    response = client.post("/api/design/photoproducts/conversion-preview", json=body)
    assert response.status_code == 200, response.text
    assert state.undo_depth() == 0
    response = client.post("/api/design/photoproducts/convert", json=body)
    assert response.status_code == 200, response.text
    assert len(state.get_or_404().photoproduct_junctions[0].context_coordinates) == 4
    state.undo()
    assert not state.get_or_404().photoproduct_junctions
    body["expected_revision"] = state.revision()
    assert (
        client.post("/api/design/photoproducts/convert", json=body).status_code == 200
    )
    identity = state.get_or_404().photoproduct_junctions[0].id
    response = client.delete("/api/design/photoproducts/" + identity)
    assert response.status_code == 200, response.text
    assert not response.json().get("geometry_unchanged")
    assert not state.get_or_404().photoproduct_junctions


def test_saved_endpoint_pose_is_not_applied_twice():
    d, keys = fixture()
    _, baseline = prepare_conversion(d, keys, 'trans-syn-I')
    d = d.copy_with(nucleotide_transforms=[NucleotideTransform(
        kind='extra_base', crossover_id=d.crossovers[0].id, extra_base_k=0,
        pivot=[.2,.3,.4], translation=[1.,2.,3.], rotation=[0.,0.,1.,0.])])
    converted, preview = convert_thymine_pair(d, keys[::-1], 'trans-syn-I')
    assert preview['positions'] == baseline['positions']
    model = build_atomistic_model(Design.from_json(converted.to_json()))
    xyz = {f'{atom_base_key(a)}:{a.name}': [a.x,a.y,a.z] for a in model.atoms}
    for key, p in zip(preview['atom_keys'], preview['positions']):
        np.testing.assert_allclose(xyz[key], p, atol=1e-12)
