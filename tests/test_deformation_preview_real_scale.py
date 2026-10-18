"""Isolated Bend/Twist history editing on ordinary origami parts at production limits.

The original allowances admitted only test-sized parts and refused any scaffolded
or stapled history. These tests build an ordinary part through the production
routes and exercise the private host without test-scale overrides.
"""

from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from backend.api import doc_context, state
from backend.api import part_deformation_preview_sessions as host
from backend.api.part_proof_commands import dependencies, execute
from backend.core.part_history_contract import assess_part_history


class _Timer:
    daemon = False

    def __init__(self, *_args):
        pass

    def start(self):
        pass

    def cancel(self):
        pass


@pytest.fixture
def ordinary_part(monkeypatch):
    from backend.api.main import app

    monkeypatch.setattr(host, "Timer", _Timer)
    identity = f"real-scale-preview-{uuid4()}"
    headers = {"X-NADOC-Doc": identity}
    # No context manager: the production lifespan (autosave, jobs) is not started.
    http = TestClient(app)
    cells = [[0, 0], [0, 1], [1, 0], [1, 1], [2, 0], [2, 1]]
    assert http.post("/api/design", headers=headers, json={"name": "real scale", "lattice_type": "HONEYCOMB"}).status_code == 201
    assert http.post("/api/design/bundle", headers=headers, json={"cells": cells, "length_bp": 126, "name": "real scale"}).status_code == 201
    assert http.post("/api/design/auto-scaffold-seamless", headers=headers, json={}).status_code == 200
    assert http.post("/api/design/full-autostaple", headers=headers, json={}).status_code == 200
    bend = {"type": "bend", "plane_a_bp": 20, "plane_b_bp": 60,
            "params": {"kind": "bend", "curvature_deg_per_bp": 0.5, "direction_deg": 0.0}}
    assert http.post("/api/design/deformation", headers=headers, json=bend).status_code == 200
    token = doc_context.set_current_doc(identity)
    try:
        yield
    finally:
        host.clear_for_testing()
        state.drop_doc(identity)
        doc_context.reset_current_doc(token)
        http.close()


def test_scaffolded_stapled_six_helix_part_edits_through_isolated_host(ordinary_part):
    source, revision = state.get_design_with_revision()
    kinds = {getattr(entry, "op_kind", None) for entry in source.feature_log}
    assert {"auto-scaffold-seamless", "full-autostaple"} <= kinds
    assert len(source.helices) == 6 and len(source.strands) > 6
    assert assess_part_history(source, execute=execute, dependencies=dependencies)["status"] == "verified"
    before = source.model_dump(mode="json")

    feature = source.feature_log[-1].id
    opened = host.prepare({"preview_id": str(uuid4()), "expected_design_id": source.id,
                           "expected_revision": revision, "feature_id": feature})
    body = {key: opened[key] for key in ("preview_id", "lease_id", "expected_design_id",
                                         "expected_revision", "feature_id")}
    params = {"type": "bend", "plane_a_bp": 20, "plane_b_bp": 60,
              "params": {"kind": "bend", "curvature_deg_per_bp": 0.8, "direction_deg": 15.0}}
    evaluated = host.evaluate({**body, "request_sequence": 1, "params": params})
    assert evaluated["candidate"] is not None
    assert state.get_or_404().model_dump(mode="json") == before  # preview never mutates

    receipt = host.apply({**body, "request_sequence": 2, "params": params})
    assert receipt["status"] == "applied"
    current = state.get_or_404()
    assert current.deformations[-1].params.curvature_deg_per_bp == 0.8
    assert assess_part_history(current, execute=execute, dependencies=dependencies)["status"] == "verified"
    state.undo()
    assert state.get_or_404().model_dump(mode="json") == before


def test_downstream_failure_refuses_apply_naming_the_earliest_failing_feature():
    """C4: an upstream edit that breaks a downstream fixed-endpoint bend is refused."""
    from backend.api.part_recipe_edit import prepare_change
    from backend.core import deformation
    from backend.core.models import DeformationLogEntry, DeformationOp
    from backend.core.part_verification_capture import capture
    from tests.test_part_deformation_preview import _append, native_source

    source = native_source("bend")
    helices = [deformation.effective_helix_for_geometry(h, source) for h in source.helices]
    start = min(h.bp_start for h in helices)
    ends = [tuple(float(x) for x in deformation._frame_at_bp(source, bp - start, helices)[0]) for bp in (10, 20)]
    op = DeformationOp(id="fixed-bend", type="bend", plane_a_bp=10, plane_b_bp=20,
                       affected_helix_ids=[h.id for h in source.helices], cluster_ids=[],
                       params={"kind": "bend", "curvature_deg_per_bp": .25, "direction_deg": 0, "endpoints": ends})
    entry = DeformationLogEntry(id="fixed-feature", deformation_id=op.id, op_snapshot=op, proof_version=1)
    source = _append(source, entry)
    source.feature_log[-1] = entry.model_copy(update={"op_snapshot": source.deformations[-1]})
    assert assess_part_history(source, execute=execute, dependencies=dependencies)["status"] == "verified"

    index = [row.id for row in source.feature_log].index("edited-feature")
    with pytest.raises(HTTPException) as caught:
        prepare_change(source, capture(source, preserve_entry_types=True), index, lambda: None,
                       params={"type": "bend", "plane_a_bp": 4, "plane_b_bp": 32,
                               "params": {"kind": "bend", "curvature_deg_per_bp": .6, "direction_deg": 0}})
    assert caught.value.status_code == 409
    assert caught.value.detail["feature_id"] == "fixed-feature"
    assert "fixed-length bend" in caught.value.detail["detail"]


def test_scientific_and_import_commands_still_refuse_isolated_replay():
    from backend.api import part_deformation_preview as preview
    from backend.core.part_command_errors import CommandContractError
    from tests.test_part_deformation_preview import native_source

    source = native_source("bend")
    for kind in ("photoproduct-relax", "duplex-relax", "cadnano-import", "nanoparticle-create"):
        assert kind not in preview.ORDINARY_UNESTIMATED
        with pytest.raises(CommandContractError) as caught:
            preview._before_command(kind, {}, source)
        assert caught.value.code == "unsupported_preview_scope"
