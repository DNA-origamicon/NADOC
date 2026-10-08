"""Exp lifecycle tests, not validation of a scientific model."""

from threading import Event
import time

import pytest

from backend.core.exp_predictor import ExpPredictor, ModelUnavailable
from backend.core.models import Design


def wait_done(engine, owner, job_id):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        result = engine.get(owner, job_id)
        if result["status"] not in {"running", "stopping"}:
            return result
        time.sleep(0.005)
    pytest.fail("Prediction failed to terminate")


def test_no_model_never_creates_a_fake_prediction():
    engine = ExpPredictor()
    try:
        assert not engine.status()["available"]
        with pytest.raises(ModelUnavailable):
            engine.start("doc", Design(metadata={"name": "empty"}))
        assert not engine._jobs
    finally:
        engine._pool.shutdown()


def test_snapshot_isolation_result_units_and_document_ownership():
    def predict(design, progress, cancel):
        design.metadata.name = "adapter mutation"
        progress(0.5, "Predicting")
        return {"positions_nm": [[1, 2, 3]], "label": "test fixture"}

    engine = ExpPredictor(predict, {"id": "test-only", "limits": "fixture"})
    design = Design(metadata={"name": "source"})
    try:
        job = engine.start("doc", design)
        result = wait_done(engine, "doc", job["job_id"])
        assert result["status"] == "completed", result
        assert result["progress"] == 1
        assert result["result"]["positions_nm"] == [[1.0, 2.0, 3.0]]
        assert design.metadata.name == "source"
        with pytest.raises(KeyError):
            engine.get("another-doc", job["job_id"])
        with pytest.raises(KeyError):
            engine.stop("another-doc", job["job_id"])
    finally:
        engine._pool.shutdown()


def test_stop_suppresses_even_a_late_success_and_rejects_overlapping_work():
    entered, release = Event(), Event()

    def predict(design, progress, cancel):
        entered.set()
        release.wait(2)
        return {"positions_nm": [[1, 2, 3]], "label": "test fixture"}

    engine = ExpPredictor(predict, {"id": "test-only"})
    try:
        job = engine.start("doc", Design(metadata={"name": "source"}))
        assert entered.wait(1)
        with pytest.raises(RuntimeError, match="already running"):
            engine.start("other", Design(metadata={"name": "second"}))
        assert engine.stop("doc", job["job_id"])["status"] == "stopping"
        release.set()
        result = wait_done(engine, "doc", job["job_id"])
        assert result["status"] == "stopped"
        assert result["result"] is None
        assert result["progress"] < 1
    finally:
        release.set()
        engine._pool.shutdown()


@pytest.mark.parametrize("positions", [[[float("nan"), 0, 0]], [], [[1, 2]]])
def test_invalid_model_output_is_a_failure_not_a_preview(positions):
    engine = ExpPredictor(
        lambda *_: {"positions_nm": positions, "label": "invalid"}, {"id": "test-only"}
    )
    try:
        job = engine.start("doc", Design(metadata={"name": "source"}))
        result = wait_done(engine, "doc", job["job_id"])
        assert result["status"] == "failed"
        assert result["result"] is None
    finally:
        engine._pool.shutdown()


def test_all_atom_identities_and_full_frame_survive_job_transport():
    payload = {
        "positions_nm": [[1, 2, 3], [1.1, 2, 3]],
        "label": "atom fixture",
        "atoms": {
            "names": ["P", "H1"],
            "elements": ["P", "H"],
            "residue_index": [0, 0],
            "keys": [["h", 1, "FORWARD", 0]],
            "includes_hydrogens": True,
        },
        "full": {
            "keys": [["h", 1, "FORWARD", 0]],
            "frame": [1, 2, 3, 1, 0, 0, 0, 0, 1, 2, 2, 3],
        },
    }
    engine = ExpPredictor(lambda *_: payload, {"id": "fixture"})
    try:
        job = engine.start("doc", Design())
        result = wait_done(engine, "doc", job["job_id"])
        assert result["status"] == "completed"
        assert result["result"] == payload
        payload["atoms"]["residue_index"] = [0, 9]
        job = engine.start("doc", Design())
        result = wait_done(engine, "doc", job["job_id"])
        assert result["status"] == "failed"
        assert "invalid atom identities" in result["message"]
    finally:
        engine._pool.shutdown()


def test_full_snapshot_uses_frozen_job_input_and_preserves_document_ownership():
    from backend.core.lattice import make_bundle_design

    engine = ExpPredictor(
        lambda *_: {"positions_nm": [[1, 2, 3]], "label": "fixture"}, {"id": "fixture"}
    )
    design = make_bundle_design(cells=[(0, 0)], length_bp=4, strand_filter="scaffold")
    try:
        job = engine.start("doc", design)
        wait_done(engine, "doc", job["job_id"])
        design.metadata.name = "edited live input"
        result = engine.snapshot_geometry("doc", job["job_id"])
        assert result["design"]["metadata"]["name"] != design.metadata.name
        assert len(result["nucleotides"]) == 4
        assert "snapshot" not in engine.get("doc", job["job_id"])
        with pytest.raises(KeyError):
            engine.snapshot_geometry("other", job["job_id"])
    finally:
        engine._pool.shutdown()
