import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.api import state
from backend.api.main import app
from backend.core.atomistic import build_atomistic_model
from backend.core.base_keys import atom_base_key, resolve_base_keys
from backend.core.cpd_conversion import BASE_NAMES, convert_thymine_pair, prepare_conversion
from backend.core.cpd_forcefield import CpdCapabilityError, assert_cpd_simulation_supported
from backend.core.design_geometry import _geometry_for_design
from backend.core.models import Design
from backend.core.photoproduct_chemistry import audit_product_chirality, load_chemical_definition
from tests.conftest import make_minimal_design

ISOMERS = ["cis-syn", "trans-syn-I", "trans-syn-II", "cis-anti-I"]


def fixture(interstrand=False):
    d = make_minimal_design(helix_length_bp=8)
    d = d.copy_with(strands=[s.model_copy(update={"sequence": "T" * 8}) for s in d.strands])
    return d, ["h0:2:FORWARD", "h0:3:REVERSE" if interstrand else "h0:3:FORWARD"]


@pytest.mark.parametrize("stereo", ISOMERS)
@pytest.mark.parametrize("interstrand", [False, True])
def test_contextual_conversion_preserves_backbone_and_matches_preview(stereo, interstrand):
    d, keys = fixture(interstrand)
    original = d.model_dump_json()
    before = build_atomistic_model(d)
    _, preview = prepare_conversion(d, keys, stereo)
    converted, actual_preview = convert_thymine_pair(d, keys, stereo)
    assert preview == actual_preview
    assert d.model_dump_json() == original
    assert preview["relationship"] == ("different strands" if interstrand else "same strand")
    assert len(set(preview["strand_ids"])) == (2 if interstrand else 1)
    assert len(preview["positions"]) > 40  # selected residues plus actual flanking residues
    restored = Design.from_json(converted.to_json())
    after = build_atomistic_model(restored)
    before_xyz = {a.serial: [a.x, a.y, a.z] for a in before.atoms}
    actual = {f"{atom_base_key(a)}:{a.name}": [a.x, a.y, a.z] for a in after.atoms}
    for atom in after.atoms:
        if atom_base_key(atom) not in keys or atom.name not in BASE_NAMES:
            np.testing.assert_array_equal([atom.x, atom.y, atom.z], before_xyz[atom.serial])
    for key, xyz in zip(preview["atom_keys"], preview["positions"]):
        np.testing.assert_allclose(actual[key], xyz, atol=1e-12)
    ends, errors = resolve_base_keys(restored, keys, atomistic_model=after)
    assert not errors
    coordinates = {f"{i}:{n}": v for i, e in enumerate(ends, 1) for n, v in e.atom_positions_nm.items()}
    # The display model omits hydrogens; the authored core retains H6 for the
    # ordered stereochemistry audit (no new atom serials are invented).
    for i, key in enumerate(keys, 1):
        coordinates[f"{i}:H6"] = restored.photoproduct_junctions[0].design_coordinates[key]["H6"]
    assert audit_product_chirality(load_chemical_definition("TT-CPD", stereo), coordinates)["passed"]
    old_bonds = {tuple(sorted(b)) for b in before.bonds}
    new_bonds = {tuple(sorted(b)) for b in after.bonds}
    assert old_bonds <= new_bonds
    assert len(new_bonds - old_bonds) == 2
    for bond in load_chemical_definition("TT-CPD", stereo)["graph_delta"]["bonds_added"]:
        serials = []
        for address in (bond["atom_1"], bond["atom_2"]):
            e, n = address.split(":")
            serials.append(ends[int(e)-1].atom_serials[n])
        assert tuple(sorted(serials)) in new_bonds
    old_geo, new_geo = _geometry_for_design(d), _geometry_for_design(restored)
    for a, b in zip(old_geo, new_geo):
        assert a["backbone_position"] == b["backbone_position"]
    changed = [b for a, b in zip(old_geo, new_geo) if a["slab_position"] != b["slab_position"]]
    assert len(changed) == 2
    with pytest.raises(CpdCapabilityError, match="visual construction"):
        assert_cpd_simulation_supported(restored, path="test")


def test_extra_pair_and_existing_poses_remain_fixed():
    from tests.test_cpd_design import fixture as extra_fixture, KEYS
    from backend.core.models import NucleotideTransform
    d = extra_fixture()
    d = d.copy_with(nucleotide_transforms=[NucleotideTransform(kind="extra_base", crossover_id="xo_direct",
        extra_base_k=0, translation=[1., 2., 3.], rotation=[0., 0., 1., 0.])])
    before = build_atomistic_model(d)
    converted, preview = convert_thymine_pair(d, KEYS, "cis-anti-I")
    assert converted.nucleotide_transforms == d.nucleotide_transforms
    after = build_atomistic_model(converted)
    for a, b in zip(before.atoms, after.atoms):
        if a.name not in BASE_NAMES or atom_base_key(a) not in KEYS:
            assert [a.x, a.y, a.z] == [b.x, b.y, b.z]
    actual = {f"{atom_base_key(a)}:{a.name}": [a.x, a.y, a.z] for a in after.atoms}
    for key, xyz in zip(preview["atom_keys"], preview["positions"]):
        np.testing.assert_allclose(actual[key], xyz, atol=1e-12)


def test_preview_is_read_only_conversion_undo_and_stale_revision():
    client = TestClient(app)
    d, keys = fixture(True)
    state.set_design(d); state.clear_history()
    revision = state.revision()
    body = {"base_keys": keys, "stereochemistry": "trans-syn-II", "expected_revision": revision, "placement": "bases-only"}
    preview = client.post("/api/design/photoproducts/conversion-preview", json=body)
    assert preview.status_code == 200, preview.text
    assert state.revision() == revision and state.undo_depth() == 0
    result = client.post("/api/design/photoproducts/convert", json=body)
    assert result.status_code == 200, result.text
    assert state.undo_depth() == 1
    assert client.post("/api/design/photoproducts/convert", json=body).status_code == 409
    state.undo()
    assert not state.get_or_404().photoproduct_junctions


@pytest.mark.parametrize("keys,stereo", [(["h0:2:FORWARD"] * 2, "cis-syn"),
    (["h0:2:FORWARD", "h0:99:REVERSE"], "cis-syn"),
    (["h0:2:FORWARD", "h0:3:FORWARD"], "trans-anti-I")])
def test_invalid_selection_or_unavailable_isomer_rejected(keys, stereo):
    with pytest.raises(ValueError):
        prepare_conversion(fixture()[0], keys, stereo)
