"""The ordinary 18HB must fit the routing editor without unbounded capture."""

import os
import subprocess
import sys

import pytest
from fastapi import HTTPException

from backend.api import part_deformation_preview as limits
from backend.api import state
from tests.deformation_history_app import fixture
from tests.test_part_pattern_recording import saved, unchanged, worker
from tests.test_part_routing_edit_native_matrix import document, edit, native_parity
from tests.test_part_routing_owned_edit import _verified, host

__all__ = ["document", "worker"]


def test_large_routing_inputs_edit_undo_and_capacity_refusal(document, worker, monkeypatch):
    source = fixture("routing-large")
    session = document(source)
    index = len(source.feature_log) - 1
    child = source.feature_log[index].children[-1]
    sub_index = len(source.feature_log[index].children) - 1
    before = saved(session)
    guards = dict(expected_design_id=source.id, expected_revision=session.revision,
                  expected_feature_id=source.feature_log[index].id, expected_child_id=child.id)
    packet = host().routing_inputs(index, sub_index, **guards)
    assert packet["child_id"] == child.id and packet["prefix"]["strands"]
    unchanged(session, before)

    patch = {"entries": [{**child.params["entries"][0], "delta_bp": -3}]}
    candidate, report, _ = edit(session, index, patch, sub_index=sub_index)
    assert report.passed and candidate is session.design
    assert len(session.history) == len(before[3]) + 1
    _verified(candidate)
    state.undo()
    native_parity(session.design, source)
    state.redo()
    native_parity(session.design, candidate)

    # A resource refusal must stay atomic and must never fall back to a second
    # copy with a more permissive profile. This exercises the actual admission.
    before = saved(session)
    workers = len(worker.instances)
    monkeypatch.setattr(limits, "MAX_CAPTURE_NODES", 1)
    with pytest.raises(HTTPException) as caught:
        edit(session, index, patch, sub_index=sub_index)
    assert caught.value.status_code == 413
    assert caught.value.detail["code"] == "routing_capture_limit"
    assert len(worker.instances) == workers
    unchanged(session, before)


def test_large_routing_recipe_replays_across_python_hash_seeds():
    source = fixture("routing-large")
    program = """
import json, sys
from backend.core.models import Design
from backend.core.part_history_contract import assess_part_history
from backend.api.part_proof_commands import execute_long, dependencies
source = Design.model_validate_json(sys.stdin.read())
report = assess_part_history(source, execute=execute_long, dependencies=dependencies)
assert report['status'] == 'verified', json.dumps(report['issues'])
"""
    for seed in ("1", "2"):
        result = subprocess.run([sys.executable, "-c", program], input=source.model_dump_json(),
                                text=True, capture_output=True, timeout=60,
                                env={**os.environ, "PYTHONHASHSEED": seed})
        assert result.returncode == 0, result.stderr
