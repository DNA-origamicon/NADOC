"""Real owned Bundle edit through later Bend and attached Sweep."""
from fastapi.testclient import TestClient

from backend.api import state
from backend.api.main import app
from backend.core.design_geometry import _geometry_for_design
from backend.core.models import Design
from backend.core.part_history_contract import create_empty_part
from tests.deformation_history_app import fixture
from tests.test_part_deformation_preview import _append, authoring
from tests.test_part_deformation_preview_sessions import document as document
from tests.test_part_sweep_preview_sessions import verified


def test_bundle_edit_rebuilds_bend_and_sweep_with_real_worker(document):
    _, identity = document
    source = fixture("extrude-chain")
    verified(source)
    state.load_design(source)
    before, revision = state.get_design_with_revision()
    change = {"length_bp": 48, "name": "Edited native Bundle"}
    expected = create_empty_part(source.recipe_root.initial_name, source.recipe_root.lattice_type)
    expected = expected.copy_with(id=source.id, recipe_root=source.recipe_root)
    for i, row in enumerate(source.feature_log):
        expected = _append(expected, row.model_copy(update={"params": {**row.params, **change}})
                           if i == 0 else row)
    client = TestClient(app, headers={"X-NADOC-Doc": identity})
    response = client.post("/api/design/features/0/edit", json={
        "params": change, "expected_design_id": source.id,
        "expected_revision": revision, "expected_feature_id": source.feature_log[0].id,
    })
    assert response.status_code == 200, response.text[:1500]
    current = state.get_or_404()
    assert authoring(current) == authoring(expected)
    assert _geometry_for_design(current) == _geometry_for_design(expected)
    assert _geometry_for_design(current) != _geometry_for_design(before)
    assert current.feature_log[1].op_snapshot == source.feature_log[1].op_snapshot
    assert current.feature_log[2].params == source.feature_log[2].params
    assert [r.id for r in current.feature_log] == [r.id for r in source.feature_log]
    assert [h.id for h in current.helices] == [h.id for h in source.helices]
    assert state.undo_depth() == 1
    restored = Design.model_validate_json(current.model_dump_json())
    verified(restored)
    assert _geometry_for_design(restored) == _geometry_for_design(expected)
    state.undo()
    assert state.get_or_404().model_dump(mode="json") == before.model_dump(mode="json")
    state.redo()
    assert authoring(state.get_or_404()) == authoring(expected)
