"""The reported pair uses the existing atomic, recorded batch-move path."""
import pytest

from backend.api import crud, state
from backend.api.doc_context import set_current_doc, reset_current_doc
from backend.api.part_history_verification import verify_current_part
from backend.api.routes_scaffold_routing import auto_scaffold_seamed_endpoint
from backend.core.models import Design
from backend.core.occupancy import occupancy_conflicts


def test_internal_pair_saved_and_independently_replayed(tmp_path):
    guard = pytest.importorskip(
        "scripts.agent_structure_guard",
        reason="Requires the independently developed agent publication guard",
    )
    path = tmp_path / "__e2e__crossover_pair.nadoc"
    token = set_current_doc("crossover-group-drag-proof")
    try:
        crud.create_bundle(crud.BundleRequest(
            cells=[[0, 1], [1, 1], [1, 2], [1, 3], [0, 3], [0, 2],
                   [1, 4], [1, 5], [0, 5], [0, 4]],
            length_bp=232,
        ))
        auto_scaffold_seamed_endpoint()
        before = state.get_or_404()
        pair = [x for x in before.crossovers
                if x.half_a.helix_id == "h_XY_0_4"
                and x.half_a.index in (116, 117)]
        assert len(pair) == 2
        crud.batch_move_crossovers(crud.BatchMoveCrossoversRequest(moves=[
            crud.MoveCrossoverRequest(crossover_id=x.id, new_index=x.half_a.index + 11)
            for x in pair
        ]))
        moved = state.get_or_404()
        assert occupancy_conflicts(moved)[1] == 0
        assert verify_current_part()["status"] == "verified"
        guard.publish(moved, path)
        reopened = Design.model_validate_json(path.read_text())
        guard.audit(reopened)
        indices = {x.id: x.half_a.index for x in reopened.crossovers}
        assert [indices[x.id] for x in pair] == [x.half_a.index + 11 for x in pair]
        from backend.core.part_history_proof import command_rows
        assert any(kind == "crossover-move-batch"
                   for _, kind, _ in command_rows(reopened, 2000))
    finally:
        path.unlink(missing_ok=True)
        state.close_session()
        reset_current_doc(token)
