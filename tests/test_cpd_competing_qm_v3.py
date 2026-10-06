"""Diagnostic acquisition must refuse changed inputs and exhausted budgets."""
import json
import time

import pytest

from experiments.cpd_anti_additive import competing_qm_v3 as campaign
from experiments.cpd_anti_additive.validation_gate import source


def registered(tmp_path, monkeypatch, deadline=None, gradients=160):
    monkeypatch.setattr(campaign, "ROOT", tmp_path)
    def write(name, value):
        path = tmp_path / name
        path.write_text(json.dumps(value))
        return path
    contract = write("contract.json", {"deadline_epoch": deadline or time.time() + 60})
    seed = write("seed.json", {"coordinates": [1, 2, 3]})
    plan = write("plan.json", {
        "campaign": source(contract), "sources": [source(seed)],
        "runtime_sources": [], "versions": {},
        "max_total_new_gradients": gradients, "tasks": [{}, {}, {}, {}],
    })
    inputs = write("inputs.json", {"files": [source(seed)]})
    write("registration.json", {"plan": source(plan), "inputs": source(inputs)})
    return seed


def test_changed_seed_is_rejected(tmp_path, monkeypatch):
    seed = registered(tmp_path, monkeypatch)
    campaign.validate()
    seed.write_text('{"coordinates": [9, 2, 3]}')
    with pytest.raises((RuntimeError, ValueError, AssertionError)):
        campaign.validate()


def test_deadline_blocks_acquisition(tmp_path, monkeypatch):
    registered(tmp_path, monkeypatch, deadline=time.time() - 1)
    with pytest.raises(RuntimeError, match="deadline"):
        campaign.validate()


def test_budget_cannot_expand(tmp_path, monkeypatch):
    registered(tmp_path, monkeypatch, gradients=161)
    with pytest.raises(RuntimeError, match="budget"):
        campaign.validate()
