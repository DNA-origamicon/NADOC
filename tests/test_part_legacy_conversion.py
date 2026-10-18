"""Legacy history conversion (re-plan R2, option B) and frozen legacy routing rows.

Fixtures are built in memory as pre-overhaul documents: no recipe root and no
proof versions or seeds, with recovery snapshots like the old recorder wrote.
"""

from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from backend.api import doc_context, state
from backend.api.part_proof_commands import dependencies, execute
from backend.core import part_frozen_topology as frozen
from backend.core.part_history_contract import assess_part_history
from backend.core.part_legacy_conversion import convert_legacy_history


def _legacy(recorded):
    """Strip a recorded native part back to the legacy shape."""
    log = []
    for entry in recorded.feature_log:
        if entry.feature_type == "snapshot":
            params = {k: v for k, v in entry.params.items() if k not in {"_proof_version", "history_seed"}}
            log.append(entry.model_copy(update={"params": params}))
        elif entry.feature_type == "deformation":
            log.append(entry.model_copy(update={"proof_version": None}))
        else:
            log.append(entry)
    return recorded.model_copy(update={"recipe_root": None, "feature_log": log})


@pytest.fixture
def recorded():
    from backend.api.main import app

    identity = f"legacy-conversion-{uuid4()}"
    headers = {"X-NADOC-Doc": identity}
    http = TestClient(app)  # no lifespan

    def record(order):
        assert http.post("/api/design", headers=headers, json={"name": "legacy", "lattice_type": "HONEYCOMB"}).status_code == 201
        cells = [[0, 0], [0, 1], [1, 0], [1, 1], [2, 0], [2, 1]]
        assert http.post("/api/design/bundle", headers=headers, json={"cells": cells, "length_bp": 84, "name": "legacy"}).status_code == 201
        bend = {"type": "bend", "plane_a_bp": 20, "plane_b_bp": 60,
                "params": {"kind": "bend", "curvature_deg_per_bp": 0.5, "direction_deg": 0.0}}
        for step in order:
            body = bend if step == "bend" else {}
            path = "/api/design/deformation" if step == "bend" else f"/api/design/{step}"
            assert http.post(path, headers=headers, json=body).status_code == 200, step
        token = doc_context.set_current_doc(identity)
        try:
            return state.get_or_404()
        finally:
            doc_context.reset_current_doc(token)

    try:
        yield record, identity, http, headers
    finally:
        state.drop_doc(identity)
        http.close()


def _convert(design):
    return convert_legacy_history(design, execute=execute, dependencies=dependencies,
                                  decode=state.decode_design_snapshot, assess=assess_part_history)


def test_bend_after_unseeded_rows_stays_editable_and_reproduces_exactly(recorded):
    record, *_ = recorded
    legacy = _legacy(record(["auto-scaffold-seamless", "bend"]))
    assert assess_part_history(legacy, execute=execute, dependencies=dependencies)["status"] != "verified"
    result = _convert(legacy)
    assert result.status == "converted"
    assert result.design.recipe_root.kind == "import"
    assert [row.feature_type for row in result.design.feature_log] == ["snapshot", "deformation"]
    row = result.design.feature_log[0]
    assert row.op_kind == "auto-scaffold-seamless" and frozen.is_frozen(row.params)  # unseeded, frozen
    assert result.absorbed == 1  # bundle-create folded into the import baseline
    assert assess_part_history(result.design, execute=execute, dependencies=dependencies)["status"] == "reproduced_import"
    assert legacy.recipe_root is None  # input untouched


def test_bend_before_frozen_routing_is_editable_and_replays_through_it(recorded):
    record, *_ = recorded
    legacy = _legacy(record(["bend", "auto-scaffold-seamless", "full-autostaple"]))
    result = _convert(legacy)
    assert result.status == "converted" and result.frozen == 2
    design = result.design
    assert design.feature_log[0].feature_type == "deformation"
    # Edit the upstream bend: the frozen routing rows replay exactly (geometry-only edit).
    from backend.api.part_recipe_edit import prepare_change
    from backend.core.part_verification_capture import capture
    op = design.feature_log[0].op_snapshot
    candidate, _report = prepare_change(design, capture(design, preserve_entry_types=True), 0, lambda: None,
        params={"type": "bend", "plane_a_bp": op.plane_a_bp, "plane_b_bp": op.plane_b_bp,
                "params": {"kind": "bend", "curvature_deg_per_bp": 1.4, "direction_deg": 30.0}})
    assert candidate.deformations[0].params.curvature_deg_per_bp == 1.4
    assert candidate.strands == design.strands  # routing reproduced, not re-derived
    assert assess_part_history(candidate, execute=execute, dependencies=dependencies)["status"] == "reproduced_import"


def test_frozen_row_refuses_changed_upstream_topology(recorded):
    record, *_ = recorded
    result = _convert(_legacy(record(["bend", "auto-scaffold-seamless"])))
    row = result.design.feature_log[1]
    assert row.op_kind == "auto-scaffold-seamless" and frozen.is_frozen(row.params)
    from backend.core.part_history_proof import root_design
    base = root_design(result.design.recipe_root)
    changed = base.model_copy(update={"helices": base.helices[:-1]})
    with pytest.raises(ValueError, match="original upstream topology"):
        frozen.build(row.op_kind, changed, row.params)


def test_already_native_and_historical_cursor_are_refused(recorded):
    record, *_ = recorded
    native = record(["bend"])
    assert _convert(native).status == "already_native"
    legacy = _legacy(native).model_copy(update={"feature_log_cursor": 0})
    assert _convert(legacy).status == "refused"


def test_route_dry_run_then_apply_is_one_undoable_step(recorded):
    record, identity, http, headers = recorded
    legacy = _legacy(record(["auto-scaffold-seamless", "bend"]))
    token = doc_context.set_current_doc(identity)
    try:
        state.load_design(legacy)
        before = state.get_or_404().model_dump(mode="json")
    finally:
        doc_context.reset_current_doc(token)
    dry = http.post("/api/design/history/convert", headers=headers, json={"apply": False}).json()
    assert dry["conversion"]["status"] == "converted" and dry["conversion"]["editable"] == ["auto-scaffold-seamless", "deformation"]
    stale = http.post("/api/design/history/convert", headers=headers, json={"apply": True, "expected_revision": dry["revision"] + 5})
    assert stale.status_code == 409
    applied = http.post("/api/design/history/convert", headers=headers, json={"apply": True, "expected_revision": dry["revision"]})
    assert applied.status_code == 200 and applied.json()["design"]["recipe_root"]["kind"] == "import"
    token = doc_context.set_current_doc(identity)
    try:
        state.undo()
        assert state.get_or_404().model_dump(mode="json") == before
    finally:
        doc_context.reset_current_doc(token)


@pytest.mark.parametrize("converted", [False, True])
def test_workspace_save_identity_stamp_keeps_the_proof(converted):
    """Saving stamps file identity into metadata; the recipe must still reproduce."""
    from backend.core.design_identity import prepare_workspace_save
    from tests.deformation_history_app import fixture
    from tests.test_part_deformation_preview import native_source

    design = _convert(fixture("bend-legacy-snapshots")).design if converted else native_source("bend")
    expected = "reproduced_import" if converted else "verified"
    claimed, disposition, _ = prepare_workspace_save(design, "probe/a.nadoc")
    forked, fork_disposition, _ = prepare_workspace_save(claimed, "probe/b.nadoc")
    assert (disposition, fork_disposition) == ("claimed", "save_as")
    assert claimed.metadata.identity_last_known_path == "probe/a.nadoc"
    for saved in (claimed, forked):
        assert assess_part_history(saved, execute=execute, dependencies=dependencies)["status"] == expected
    renamed = claimed.model_copy(update={"metadata": claimed.metadata.model_copy(update={"name": "renamed"})})
    assert assess_part_history(renamed, execute=execute, dependencies=dependencies)["status"] == "mismatch"
