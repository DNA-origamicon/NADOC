import copy
import numpy as np
from tests.conftest import make_minimal_design
from backend.api.simulation_atomistic_display import SimulationAtomisticRequest, simulation_atomistic_display


def test_display_reuses_visualized_export_mapping_without_mutating_design(monkeypatch):
    from backend.core import atomistic
    design = make_minimal_design()
    original = copy.deepcopy(design.model_dump())
    received = {}
    def build(snapshot, **kwargs):
        received.update(kwargs)
        assert snapshot.model_dump() == original
        return object()
    monkeypatch.setattr(atomistic, "build_atomistic_model", build)
    monkeypatch.setattr(atomistic, "atomistic_to_json", lambda model: {"atoms": ["rendered"], "bonds": []})
    body = SimulationAtomisticRequest(design=design, positions=[
        {"helix_id": "h1", "bp_index": 3, "direction": "FORWARD", "backbone_position": [9, 8, 7], "copy": 2},
        {"helix_id": "__ext_tail", "bp_index": 1, "direction": "FORWARD", "backbone_position": [6, 5, 4]},
    ])
    assert simulation_atomistic_display(body)["atoms"] == ["rendered"]
    np.testing.assert_array_equal(received["nuc_pos_override"][("h1", 3, "FORWARD", 2)], [9, 8, 7])
    np.testing.assert_array_equal(received["ext_pos_override"][("tail", 1)], [6, 5, 4])
    assert received["close_backbone"] is True
    assert design.model_dump() == original


def test_real_reconstruction_follows_simulated_translation_and_keeps_topology():
    design = make_minimal_design(helix_length_bp=5)
    original = design.model_dump()
    positions = [dict(helix_id="h0", bp_index=i, direction=direction,
                      backbone_position=[0, side, .34*i])
                 for i in range(5) for direction, side in [("FORWARD", 1), ("REVERSE", -1)]]
    shift = np.array([8.0, 6.0, 4.0])
    first = simulation_atomistic_display(SimulationAtomisticRequest(design=design, positions=positions))
    moved = [{**p, "backbone_position": (np.array(p["backbone_position"])+shift).tolist()} for p in positions]
    second = simulation_atomistic_display(SimulationAtomisticRequest(design=design, positions=moved))
    assert first["atoms"] and first["bonds"] == second["bonds"]
    xyz = lambda model: np.array([[a[c] for c in ("x", "y", "z")] for a in model["atoms"]])
    np.testing.assert_allclose(xyz(second)-xyz(first), np.broadcast_to(shift, xyz(first).shape), atol=2e-5)
    assert design.model_dump() == original
