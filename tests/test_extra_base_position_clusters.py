import numpy as np

from backend.core.extra_base_position_clusters import (
    canonical_medoid,
    pooled_position_clusters,
    reciprocal_crossover_sides,
)
from backend.core.junction_topology import crossover_connectors
from tests.reciprocal_design import reciprocal_design


def _sample(x, y, z):
    return {
        "L": 10.0,
        "g_ih_c1": x,
        "g_ax_c1": y,
        "g_pp_c1": z,
        "g_ih_base": x + 2.0,
        "g_ax_base": y,
        "g_pp_base": z,
        "h1_c1": 0.1,
        "h2_c1": 0.2,
        "h3_c1": 0.3,
        "h1_p1": 1.0,
        "h2_p1": 0.0,
        "h3_p1": 0.0,
        "h1_P": 0.0,
        "h2_P": 0.0,
        "h3_P": 0.0,
        "h1_C3'": 0.2,
        "h2_C3'": 0.2,
        "h3_C3'": 0.3,
        "h1_C5'": 0.1,
        "h2_C5'": 0.1,
        "h3_C5'": 0.1,
        "pose_M": np.eye(3).ravel().tolist(),
        "interhelix": 25.0,
    }


def test_reciprocal_sides_use_lower_bp_as_i_left():
    sides = reciprocal_crossover_sides(reciprocal_design("T"))
    assert {side["side"] for side in sides.values()} == {"i", "i+1"}
    lower = next(side for side in sides.values() if side["side"] == "i")
    upper = next(side for side in sides.values() if side["side"] == "i+1")
    assert lower["bp_level"] == 16
    assert upper["bp_level"] == 17
    assert lower["paired_with"] in sides


def test_canonical_medoid_reconstructs_atoms_in_shared_frame():
    insert = {
        "crossover_id": "xo",
        "k": 0,
        "base": "T",
        "src": ["h0", 13, "FORWARD"],
        "dst": ["h1", 13, "REVERSE"],
    }
    medoid = canonical_medoid(
        _sample(1.0, 2.0, 3.0),
        insert,
        {"side": "i", "bp_level": 13},
        sample_index=4,
        frame=40,
    )
    assert medoid["atoms_A"]["C1'"] == [1.0, 2.0, 3.0]
    assert medoid["atoms_A"]["P"] == [0.0, 0.0, 0.0]
    assert medoid["frame"] == 40
    assert np.allclose(np.asarray(medoid["base_orientation"]).T @ medoid["base_orientation"], np.eye(3))
    atomistic = medoid["atomistic"]
    names = {atom["name"] for atom in atomistic["atoms"]}
    assert {"C1'", "C2'", "C3'", "C4'", "O4'"} <= names
    assert atomistic["ribose_ring"] == ["C1'", "C2'", "C3'", "C4'", "O4'"]
    assert ["C4'", "O4'"] in atomistic["bonds"]
    assert next(atom for atom in atomistic["atoms"] if atom["name"] == "C1'")[
        "coordinate_source"
    ] == "measured"


def test_pooled_clusters_return_one_ensemble_per_hj_side(tmp_path):
    design = reciprocal_design("T")
    (tmp_path / "design.json").write_text(design.model_dump_json())
    connectors = crossover_connectors(design)
    inserts = []
    stable = {}
    for side_index, connector in enumerate(connectors):
        samples = []
        for index in range(30):
            offset = -5.0 if index < 21 else 5.0
            samples.append(_sample(offset + 0.02 * index, side_index * 2.0, -3.0))
        inserts.append(
            {
                "crossover_id": connector.crossover_id,
                "k": 0,
                "base": "T",
                "src": [connector.from_helix, connector.from_bp, connector.from_dir],
                "dst": [connector.to_helix, connector.to_bp, connector.to_dir],
                "samples": samples,
            }
        )
        stable[(str(connector.crossover_id), 0)] = list(range(30))
    result = pooled_position_clusters(
        {
            "job": str(tmp_path),
            "inserts": inserts,
            "paired_fraction": [1.0] * 30,
            "frames": list(range(0, 300, 10)),
        },
        stable,
        max_fit_samples=30,
    )
    assert result["ready"] is True
    assert result["n_unpaired_inserts"] == 0
    assert [side["side"] for side in result["sides"]] == ["i", "i+1"]
    assert all(side["n_observations"] == 30 for side in result["sides"])
    assert all(side["clusters"][0]["medoid"]["atoms_A"]["C1'"] for side in result["sides"])
