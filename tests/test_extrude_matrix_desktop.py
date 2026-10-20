"""Real worker and complete cold native geometry for the six desktop fixtures."""
import pytest
from fastapi.testclient import TestClient

from backend.api import state
from backend.api.main import app
from backend.api.part_extrusion_edit_inputs import normalize, bind_prefix
from backend.core.design_geometry import _geometry_for_design
from backend.core.models import Design
from backend.core.part_history_contract import create_empty_part
from tests.extrude_matrix_fixture import FAMILIES, fixture, change
from tests.test_part_deformation_preview import _append, authoring
from tests.test_part_deformation_preview_sessions import document as document
from tests.test_part_sweep_preview_sessions import verified


@pytest.mark.parametrize("kind", FAMILIES)
def test_real_worker_matrix_edit_matches_independent_native_replay(document, kind):
    _, identity = document
    source = fixture(kind)
    verified(source)
    state.load_design(source)
    old, revision = state.get_design_with_revision()
    patch = change(kind, source)
    expected = create_empty_part(source.recipe_root.initial_name, source.recipe_root.lattice_type)
    expected = expected.copy_with(id=source.id, recipe_root=source.recipe_root)
    for i, row in enumerate(source.feature_log):
        if i == 1:
            params = bind_prefix(kind, normalize(kind, row.params, patch), expected)
            row = row.model_copy(update={"params": params})
        expected = _append(expected, row)
    client = TestClient(app, headers={"X-NADOC-Doc": identity})
    response = client.post("/api/design/features/1/edit", json={"params": patch,
        "expected_design_id": source.id, "expected_revision": revision,
        "expected_feature_id": source.feature_log[1].id})
    assert response.status_code == 200, response.text[:1500]
    current = state.get_or_404()
    assert authoring(current) == authoring(expected)
    assert _geometry_for_design(current) == _geometry_for_design(expected)
    assert _geometry_for_design(current) != _geometry_for_design(old)
    assert current.feature_log[-1].params == old.feature_log[-1].params
    assert [r.id for r in current.feature_log] == [r.id for r in old.feature_log]
    assert state.undo_depth() == 1
    restored = Design.model_validate_json(current.model_dump_json())
    verified(restored)
    assert _geometry_for_design(restored) == _geometry_for_design(expected)
    state.undo()
    assert state.get_or_404().model_dump(mode="json") == old.model_dump(mode="json")
    state.redo()
    assert authoring(state.get_or_404()) == authoring(expected)
