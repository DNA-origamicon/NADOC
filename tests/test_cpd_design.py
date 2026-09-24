import numpy as np
import pytest
from fastapi.testclient import TestClient
from backend.api.main import app
from backend.api import state
from backend.core.atomistic import build_atomistic_model
from backend.core.base_keys import resolve_base_keys
from backend.core.cpd_design import convert_extra_pair, design_template
from backend.core.cpd_preliminary import validate_preliminary_design
from backend.core.models import Design
from tests.test_atomistic import _crossover_design_needing_linker_bases

KEYS = ["__xb__:xo_direct:0", "__xb__:xo_direct:1"]


def fixture():
    d = _crossover_design_needing_linker_bases()
    d.crossovers[0].extra_bases = "TT"
    d.crossovers[0].half_a.index = d.crossovers[0].half_b.index = 11
    d.strands[0].domains[0].end_bp = 11
    d.strands[0].domains[1].start_bp = 11
    return d


def positions(design):
    model = build_atomistic_model(design)
    ends, errors = resolve_base_keys(design, KEYS, atomistic_model=model)
    assert not errors
    return model, ends


def test_conversion_preserves_complete_template_and_round_trips():
    d = fixture()
    before = d.model_dump_json()
    converted, lesion = convert_extra_pair(d, KEYS)
    assert d.model_dump_json() == before
    converted = Design.from_json(converted.to_json())
    assert converted.photoproduct_junctions[0] == lesion
    model, ends = positions(converted)
    template = design_template()
    # All pairwise distances pin geometry/chirality-preserving template placement,
    # not just the two crosslinks.
    names = ["C5", "C6", "C1'", "N1"]
    actual = np.array([e.atom_positions_nm[n] for e in ends for n in names])
    expected = np.array([template[f"{i}:{n}"] for i in (1, 2) for n in names])
    np.testing.assert_allclose(
        np.linalg.norm(actual[:, None] - actual, axis=2),
        np.linalg.norm(expected[:, None] - expected, axis=2),
        atol=1e-10,
    )
    for name in ["C5", "C6"]:
        pair = tuple(e.atom_serials[name] for e in ends)
        assert pair in model.bonds or pair[::-1] in model.bonds
    with pytest.raises(ValueError, match="adjacent TT"):
        validate_preliminary_design(converted)


@pytest.mark.parametrize(
    "keys,stereo",
    [
        (KEYS, "trans-syn-I"),
        ([KEYS[0]] * 2, "cis-syn"),
        (["h:1:FORWARD", KEYS[0]], "cis-syn"),
    ],
)
def test_rejects_unsupported_conversion(keys, stereo):
    with pytest.raises(ValueError):
        convert_extra_pair(fixture(), keys, stereo)


def test_rejects_reuse_and_non_thymine():
    d, _ = convert_extra_pair(fixture(), KEYS)
    with pytest.raises(ValueError, match="already belongs"):
        convert_extra_pair(d, KEYS)
    d = fixture()
    d.crossovers[0].extra_bases = "AT"
    with pytest.raises(ValueError, match="thymine"):
        convert_extra_pair(d, KEYS)


def test_api_conversion_and_unit_transform_are_atomic_and_undoable():
    client = TestClient(app)
    state.set_design(fixture())
    state.clear_history()
    revision = state.revision()
    response = client.post(
        "/api/design/photoproducts/convert",
        json={"base_keys": KEYS, "expected_revision": revision},
    )
    assert response.status_code == 200, response.text
    assert state.undo_depth() == 1
    before, ends = positions(state.get_or_404())
    transforms = [
        {
            "kind": "extra_base",
            "crossover_id": "xo_direct",
            "extra_base_k": k,
            "pivot": [0, 0, 0],
            "translation": [1, 2, 3],
            "rotation": [0, 0, 1, 0],
            "compose": True,
        }
        for k in (0, 1)
    ]
    response = client.put(
        "/api/design/nucleotide-transforms", json={"transforms": transforms}
    )
    assert response.status_code == 200, response.text
    assert state.undo_depth() == 2
    _, moved = positions(state.get_or_404())
    for old, new in zip(ends, moved):
        for name, xyz in old.atom_positions_nm.items():
            np.testing.assert_allclose(
                new.atom_positions_nm[name],
                np.array(xyz) * [-1, -1, 1] + [1, 2, 3],
                atol=1e-10,
            )
    assert (
        client.post(
            "/api/design/photoproducts/convert",
            json={"base_keys": KEYS, "expected_revision": revision},
        ).status_code
        == 409
    )
    assert state.undo_depth() == 2

    state.undo()
    _, restored = positions(state.get_or_404())
    for old, new in zip(ends, restored):
        np.testing.assert_allclose(
            old.atom_positions_nm["C5"], new.atom_positions_nm["C5"]
        )
    state.undo()
    assert not state.get_or_404().photoproduct_junctions
    assert not state.get_or_404().nucleotide_transforms


def test_single_endpoint_api_move_expands_to_unit_and_rejects_separation():
    client = TestClient(app)
    d, _ = convert_extra_pair(fixture(), KEYS)
    state.set_design(d)
    state.clear_history()
    _, old = positions(d)
    body = {
        "kind": "extra_base",
        "crossover_id": "xo_direct",
        "extra_base_k": 0,
        "pivot": [0, 0, 0],
        "translation": [1, 2, 3],
        "rotation": [0, 0, 0, 1],
        "compose": True,
    }
    response = client.put("/api/design/nucleotide-transform", json=body)
    assert response.status_code == 200, response.text
    assert state.undo_depth() == 1
    _, new = positions(state.get_or_404())
    for a, b in zip(old, new):
        np.testing.assert_allclose(
            b.atom_positions_nm["C5"], np.array(a.atom_positions_nm["C5"]) + [1, 2, 3]
        )
    response = client.put(
        "/api/design/nucleotide-transforms",
        json={
            "transforms": [body, {**body, "extra_base_k": 1, "translation": [0, 0, 0]}]
        },
    )
    assert response.status_code == 422
    assert state.undo_depth() == 1


def test_conversion_relaxes_attachment_bonds_without_moving_neighbors():
    design = fixture()
    original, _ = positions(design)
    converted, lesion = convert_extra_pair(design, KEYS)
    report = lesion.bond_relaxation
    assert report["bond_count"] == 2
    assert report["rms_error_after_nm"] < report["rms_error_before_nm"]
    assert report["evaluations"] <= report["starts"] * 180 + 5000
    relaxed, _ = positions(converted)
    from backend.core.base_keys import atom_base_key

    original_neighbors = {
        a.serial: [a.x, a.y, a.z]
        for a in original.atoms
        if atom_base_key(a) not in KEYS
    }
    for atom in relaxed.atoms:
        if atom.serial in original_neighbors:
            np.testing.assert_allclose(
                [atom.x, atom.y, atom.z], original_neighbors[atom.serial]
            )
    loaded = Design.from_json(converted.to_json())
    assert loaded.photoproduct_junctions[0].bond_relaxation == report
