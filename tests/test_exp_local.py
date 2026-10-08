"""Physical invariants and connectivity sensitivity of the isolated local model."""

import numpy as np
import pytest
from scipy.spatial.transform import Rotation
from backend.core.exp_local import prepare, train, predict, psf_block, project


def fixture():
    names = ["C1'", "C3'", "C4'", "O3'", "P", "N6"]
    atom = np.array(
        [
            [0, 0, 0],
            [0.1, 0.1, 0],
            [0, 0.1, 0.1],
            [0.2, 0, 0],
            [-0.14, 0, 0],
            [0, 0, 0.2],
        ]
    )
    positions = np.concatenate([atom + [0.5 * i, 0, 0] for i in range(4)])
    native = dict(
        positions_nm=positions,
        names=names * 4,
        residue_index=np.repeat(np.arange(4), 6),
        keys=[("h", i, "FORWARD") for i in range(4)],
    )
    bonds = np.array(
        [(6 * i, 6 * i + 1) for i in range(4)]
        + [(6 * i + 3, 6 * (i + 1) + 4) for i in range(3)]
    )
    return native, bonds


def test_psf_bonds_are_zero_based_and_complete():
    assert psf_block("3 !NBOND: bonds\n 1 2 2 3\n3 4\n\n", "!NBOND", 2).tolist() == [
        [0, 1],
        [1, 2],
        [2, 3],
    ]


def test_global_rigid_motion_is_equivariant():
    native, bonds = fixture()
    data = prepare(native, bonds)
    target = data["x"].copy()
    target[:, 1] += 0.03 * data["ri"] ** 2
    model = train([(data, target)])
    first, _, _ = predict(data, model, constrain=False)
    rot = Rotation.from_rotvec([0.3, -0.5, 0.2]).as_matrix()
    shifted = {
        **native,
        "positions_nm": native["positions_nm"] @ rot.T + [8.0, -3.0, 1.0],
    }
    moved = prepare(shifted, bonds)
    np.testing.assert_allclose(
        moved["node_features"], data["node_features"], atol=1e-10
    )
    second, _, _ = predict(moved, model, constrain=False)
    np.testing.assert_allclose(second, first @ rot.T + [8.0, -3.0, 1.0], atol=1e-7)


def test_covalent_connectivity_changes_features_without_changing_coordinates():
    native, bonds = fixture()
    original = prepare(native, bonds)
    nicked = prepare(native, bonds[:-1])
    assert not np.allclose(original["node_features"], nicked["node_features"])


def test_rigid_reconstruction_preserves_all_intra_residue_distances():
    native, bonds = fixture()
    data = prepare(native, bonds)
    target = data["x"].copy()
    target[:, 1] += 0.03 * data["ri"] ** 2
    prediction, _, _ = predict(data, train([(data, target)]))
    for group in data["groups"]:
        original = data["x"][group]
        candidate = prediction[group]
        np.testing.assert_allclose(
            np.linalg.norm(original[:, None] - original[None, :], axis=-1),
            np.linalg.norm(candidate[:, None] - candidate[None, :], axis=-1),
            atol=1e-12,
        )


def test_projection_reduces_a_stretched_phosphodiester_link():
    native, bonds = fixture()
    data = prepare(native, bonds)
    centers = data["centers"].copy()
    centers[-1] += [0.2, 0, 0]
    offsets = data["x"] - data["centers"][data["ri"]]
    before = offsets + centers[data["ri"]]
    after_centers, _ = project(data, offsets, centers, rounds=1, iterations=100)
    after = offsets + after_centers[data["ri"]]
    a, b = data["cross"].T
    error = lambda x: np.linalg.norm(np.linalg.norm(x[a] - x[b], axis=1) - 0.16)
    assert error(after) < 0.02 * error(before)


def test_atom_ring_audit_distinguishes_crossing_from_near_miss():
    from tools.audit_exp_local import piercings

    polygon = np.array(
        [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, 0.0], [0.0, 1.0, 0.0]]
    )
    points = np.vstack(
        [polygon, [0.5, 0.5, -1.0], [0.5, 0.5, 1.0], [1.2, 0.5, -1.0], [1.2, 0.5, 1.0]]
    )
    hits = piercings(points, np.array([[4, 5], [6, 7]]), [(0, "test", [0, 1, 2, 3])])
    assert len(hits) == 1
    assert hits[0]["bond"] == [4, 5]


def test_pair_edges_do_not_connect_different_copies():
    native, bonds = fixture()
    native["keys"] = [
        ("h", 1, "FORWARD", 0),
        ("h", 1, "REVERSE", 0),
        ("h", 1, "FORWARD", 1),
        ("h", 1, "REVERSE", 1),
    ]
    # Remove strand edges so paired edges are observable independently.
    data = prepare(native, bonds[:4])
    assert data["ij"][data["kind"] == 1].tolist() == [[0, 1], [2, 3]]


@pytest.mark.parametrize("geometry_schema", [None, "rigid-bond-angle-v2"])
def test_optional_adapter_returns_every_atom_and_the_measured_full_frame(
    tmp_path, monkeypatch, geometry_schema
):
    import json
    from threading import Event
    import pytest
    from backend.core.exp_atomistic import native_atoms
    from backend.core.exp_local_adapter import load_adapter
    from backend.core.lattice import make_bundle_design
    from backend.core.namd_topology import find_psfgen

    try:
        find_psfgen()
    except RuntimeError:
        pytest.skip("psfgen unavailable")
    design = make_bundle_design(cells=[(0, 0)], length_bp=8, strand_filter="scaffold")
    original = design.model_dump_json()
    native = native_atoms(design, include_bonds=True)
    data = prepare(native, native["bonds"])
    target = data["x"].copy()
    target[:, 1] += 0.01 * data["ri"]
    model = train([(data, target)])
    model["model_card"] = {"id": "test-local"}
    model["geometry_schema"] = geometry_schema
    path = tmp_path / "model.json"
    path.write_text(json.dumps(model))
    monkeypatch.setattr(
        "backend.core.exp_local_adapter.native_atoms", lambda *a, **kw: native
    )
    adapter, card = load_adapter(path)
    result = adapter(design, lambda *args: None, Event())
    positions = np.array(result["positions_nm"])
    assert positions.shape == data["x"].shape
    assert len(result["atoms"]["names"]) == len(positions)
    assert sum(n.startswith("H") for n in result["atoms"]["names"]) > 8
    assert card["id"] == "test-local"
    frame = np.array(result["full"]["frame"]).reshape(-1, 12)
    for i in range(len(native["keys"])):
        atoms = {
            n: j
            for j, n in enumerate(native["names"])
            if native["residue_index"][j] == i
        }
        anchor = atoms.get("P", atoms.get("O5'"))
        np.testing.assert_allclose(frame[i, :3], positions[anchor])
    assert design.model_dump_json() == original


def test_training_preflight_checks_bonds_not_only_atom_names(tmp_path):
    import pytest
    from tools.train_exp_local import verify_covalent_identity

    native = "3 !NATOM\n1 D 1 ADE P P2\n2 D 1 ADE O5\n3 D 2 THY P P2\n"
    source = "4 !NATOM\n1 D 2 THY P P2\n2 I 1 SOD SOD SOD\n3 D 1 ADE O5 ON2\n4 D 1 ADE P P2\n3 !NBOND\n4 3 3 1 2 1\n"
    (tmp_path / "source.psf").write_text(source)
    case = {"name": "test", "package": str(tmp_path), "psf": "source.psf"}
    result = verify_covalent_identity(case, native, np.array([[0, 1], [1, 2]]))
    assert result["native_only"] == result["trajectory_only"] == 0
    with pytest.raises(ValueError, match="covalent mismatch"):
        verify_covalent_identity(case, native, np.array([[0, 1]]))
