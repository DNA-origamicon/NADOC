"""Preliminary stages do not turn incomplete/changed evidence into fit permission."""

import json

import pytest

from experiments.cpd_anti_additive import preliminary_protocol as protocol
from experiments.cpd_anti_additive.validation_gate import source


def ready(tmp_path, monkeypatch):
    pause = tmp_path / "pause.json"
    pause.write_text('{"paused": false}')
    monkeypatch.setattr(protocol, "PAUSE", pause)
    artifact = tmp_path / "targets.json"
    artifact.write_text('{"target": 1}')
    receipt = tmp_path / "inputs.json"
    receipt.write_text(json.dumps(dict(stage="electrostatics", ready=True,
        case_ids=["registered-water-case"], artifacts=[source(artifact)])))
    activation = tmp_path / "activation.json"
    activation.write_text(json.dumps(dict(user_authorized_resume=True,
        policy=source(protocol.POLICY))))
    protocol.lock_inputs("electrostatics", receipt, tmp_path)
    return artifact, receipt, pause


def test_stage_is_independent_but_missing_other_stage_blocks(tmp_path, monkeypatch):
    ready(tmp_path, monkeypatch)
    _, receipt = protocol.require("electrostatics", tmp_path)
    assert receipt["case_ids"] == ["registered-water-case"]
    with pytest.raises(FileNotFoundError):
        protocol.require("conformational", tmp_path)


def test_changed_target_and_pause_fail_closed(tmp_path, monkeypatch):
    artifact, _, pause = ready(tmp_path, monkeypatch)
    artifact.write_text("changed")
    with pytest.raises(ValueError, match="Changed evidence"):
        protocol.require("electrostatics", tmp_path)
    pause.write_text('{"paused": true}')
    with pytest.raises(RuntimeError, match="paused"):
        protocol.require("electrostatics", tmp_path)


def test_candidate_lock_prevents_refitting(tmp_path, monkeypatch):
    ready(tmp_path, monkeypatch)
    (tmp_path/"electrostatics_candidate_lock.json").write_text("{}")
    with pytest.raises(RuntimeError, match="Candidate locked"):
        protocol.begin_round("electrostatics", tmp_path/"fit", tmp_path)


def test_second_round_needs_review_and_budget_cannot_expand(tmp_path, monkeypatch):
    artifact, _, _ = ready(tmp_path, monkeypatch)
    assert protocol.begin_round("electrostatics", tmp_path/"fit1", tmp_path)[2] == 1
    with pytest.raises(FileNotFoundError):
        protocol.begin_round("electrostatics", tmp_path/"fit2", tmp_path)
    (tmp_path/"electrostatics_second_round_review.json").write_text(json.dumps(dict(
        prior_result=source(artifact), authorized=True, rationale="Specific residual diagnosis")))
    assert protocol.begin_round("electrostatics", tmp_path/"fit2", tmp_path)[2] == 2
    with pytest.raises(RuntimeError, match="budget exhausted"):
        protocol.begin_round("electrostatics", tmp_path/"fit3", tmp_path)
