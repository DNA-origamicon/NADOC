"""One explicit attached Sweep downstream of a historical Bend/Twist edit."""
from uuid import uuid4

import numpy as np
import pytest

from backend.api import state, part_proof_commands
from backend.core.design_geometry import _geometry_for_design
from backend.core.models import Design, SnapshotLogEntry
from backend.core.part_history_contract import assess_part_history, create_empty_part
from backend.core.part_overlay_commands import edit_entry
from backend.core.sweep import SweepRequest
from tests.test_part_deformation_preview import _append, patch, authoring
from tests.test_part_deformation_preview_sessions import (
    document as document, opening, update, cancellation, checkpoint, unchanged,
)


def append_attached_sweep(source):
    params = SweepRequest(
        sweep_id=str(uuid4()), cells=[tuple(h.grid_pos) for h in source.helices],
        source_helix_id=source.helices[0].id, source_end="end",
        points_nm=[(0, 0, 0), (0, 0, 4)], ligate_adjacent=False,
    ).model_dump(mode="json")
    return _append(source, SnapshotLogEntry(
        id="downstream-sweep", op_kind="sweep", label="Attached downstream Sweep",
        params={**params, "_proof_version": 1}, evicted=True,
        design_snapshot_gz_b64="poisoned-before", post_state_gz_b64="poisoned-after",
    ))


@pytest.mark.parametrize("kind", ["bend", "twist"])
def test_deformation_edit_rebuilds_attached_sweep_and_cancel_preserves_redo(document, kind):
    host, _ = document
    from tests.deformation_history_app import fixture

    source = fixture(f"{kind}-sweep")
    proof = assess_part_history(source, execute=part_proof_commands.execute,
                                dependencies=part_proof_commands.dependencies)
    assert proof["status"] == "verified", proof
    state.load_design(source)
    state.set_design(source.copy_with())
    state.undo()
    before = checkpoint()
    assert before["redo"]
    opened = host.prepare(opening())
    host.evaluate(update(opened, params=patch(kind)))
    host.cancel(cancellation(opened))
    unchanged(before)

    # Independently rebuild from authored inputs, never preview/cached recovery.
    expected = create_empty_part(source.recipe_root.initial_name, source.recipe_root.lattice_type)
    expected = expected.copy_with(id=source.id, recipe_root=source.recipe_root)
    for entry in source.feature_log:
        expected = _append(expected, edit_entry(entry, patch(kind))
                           if entry.id == "edited-feature" else entry)
    opened = host.prepare(opening())
    receipt = host.apply(update(opened, params=patch(kind)))
    assert receipt["status"] == "applied"
    current = state.get_or_404()
    assert authoring(current) == authoring(expected)
    assert _geometry_for_design(current) == _geometry_for_design(expected)
    assert _geometry_for_design(current) != _geometry_for_design(source)
    sweep_ids = {h.id for h in source.helices[1:]}
    assert sweep_ids
    assert [n for n in _geometry_for_design(current) if n["helix_id"] in sweep_ids] != [
        n for n in _geometry_for_design(source) if n["helix_id"] in sweep_ids]
    if kind == "twist":
        # The native contract is pure axial spin for this straight single helix.
        # Sweep inherits the source radial frame, not a Bend-like axis displacement.
        from backend.core.sweep import sweep_source
        request = SweepRequest.model_validate(source.feature_log[-1].params)
        old_frame, new_frame = sweep_source(source, request), sweep_source(current, request)
        np.testing.assert_allclose(new_frame["origin"], old_frame["origin"], rtol=0, atol=1e-12)
        np.testing.assert_allclose(new_frame["rotation"][:, 2], old_frame["rotation"][:, 2],
                                   rtol=0, atol=1e-12)
        assert not np.allclose(new_frame["rotation"][:, 0], old_frame["rotation"][:, 0])
    assert current.feature_log[-1].id == source.feature_log[-1].id
    assert current.feature_log[-1].params == source.feature_log[-1].params
    assert [h.id for h in current.helices] == [h.id for h in source.helices]
    assert state.undo_depth() == len(before["history"]) + 1
    restored = Design.model_validate_json(current.model_dump_json())
    proof = assess_part_history(restored, execute=part_proof_commands.execute,
                                dependencies=part_proof_commands.dependencies)
    assert proof["status"] == "verified", proof
    assert _geometry_for_design(restored) == _geometry_for_design(expected)
    state.undo()
    assert state.get_or_404().model_dump(mode="json") == before["json"]
    state.redo()
    assert authoring(state.get_or_404()) == authoring(expected)
