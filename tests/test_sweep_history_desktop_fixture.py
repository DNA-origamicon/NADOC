"""Native oracle for the exact Sweep source-mode desktop fixtures."""
import pytest

from backend.api import state, part_deformation_preview_sessions as host
from backend.core.design_geometry import _geometry_for_design
from backend.core.models import Design
from backend.core.part_history_contract import create_empty_part
from tests.sweep_history_fixture import fixture
from tests.test_part_deformation_preview import _append, authoring
from tests.test_part_deformation_preview_sessions import cancellation, checkpoint, unchanged
from tests.test_part_sweep_preview_sessions import document as document, opening, update, verified


@pytest.mark.parametrize("mode", ["end", "independent", "start", "detached"])
def test_sweep_editor_rebuilds_later_extrude_from_native_inputs(document, mode):
    source = fixture(mode)
    verified(source)
    state.load_design(source)
    state.set_design(source.copy_with())
    state.undo()
    before = checkpoint()
    assert before["redo"]
    change = {"points_nm": [[0, 0, 0], [0, 0, -6 if mode == "start" else 6]],
              "orientations_deg": [None, [0, 0, 10]], "detach_source": mode == "detached"}
    opened = host.prepare(opening(feature_id="selected-sweep"), family="sweep")
    if mode == "detached":
        moved = host.evaluate(update(opened, params={"points_nm": [[1, 0, 0], [0, 0, 6]]}), family="sweep")
        assert moved["sweep_preview"]["source_detached"] is True
    host.evaluate(update(opened, sequence=2, params=change), family="sweep")
    host.cancel(cancellation(opened), family="sweep")
    unchanged(before)
    expected = create_empty_part(source.recipe_root.initial_name, source.recipe_root.lattice_type)
    expected = expected.copy_with(id=source.id, recipe_root=source.recipe_root)
    for row in source.feature_log:
        expected = _append(expected, row.model_copy(update={"params": {**row.params, **change}})
                           if row.id == "selected-sweep" else row)
    opened = host.prepare(opening(feature_id="selected-sweep"), family="sweep")
    receipt = host.apply(update(opened, params=change), family="sweep")
    current = state.get_or_404()
    assert receipt["status"] == "applied"
    assert authoring(current) == authoring(expected)
    assert _geometry_for_design(current) == _geometry_for_design(expected)
    assert _geometry_for_design(current) != _geometry_for_design(source)
    selected = current.feature_log[1].params
    assert selected["source_helix_id"] == source.feature_log[1].params["source_helix_id"]
    assert selected["source_end"] == ("start" if mode == "start" else "end")
    assert selected["detach_source"] is (mode == "detached")
    assert selected["orientations_deg"] == [None, [0, 0, 10]]
    assert current.feature_log[-1].params == source.feature_log[-1].params
    assert [r.id for r in current.feature_log] == [r.id for r in source.feature_log]
    assert state.undo_depth() == len(before["history"]) + 1
    restored = Design.model_validate_json(current.model_dump_json())
    verified(restored)
    assert _geometry_for_design(restored) == _geometry_for_design(expected)
    state.undo()
    assert state.get_or_404().model_dump(mode="json") == before["json"]
    state.redo()
    assert authoring(state.get_or_404()) == authoring(expected)
