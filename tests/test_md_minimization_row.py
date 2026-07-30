"""The minimisation's timeline record — manifest slot → MdJob.minimization → JSON.

The pre-ladder step (a minimisation; for an ensemble replica, a zero-step velocity
reseed) runs BEFORE segment 1 and is deliberately not a member of ``job.segments`` —
the runner indexes that list by ``current_segment_idx``.  So the UI can only show it
running, and confirm it finished, if the job record carries it separately.  These are
pure dict/dataclass tests: no NAMD, no solvation, no filesystem beyond a tmp job dir.
"""

from __future__ import annotations

from backend.core.md_job import MdJob, MdSegmentStatus, MdStatus, new_job
from backend.core.md_protocols import DEFAULT_MINIMIZATION_STAGE, minimization_status


# ── manifest slot → status record ─────────────────────────────────────────────


def test_minimization_status_reads_name_steps_and_label():
    row = minimization_status({
        "minimization": {"name": "B_tube_00_min_enm_k0p5", "steps": 9600,
                         "stage": "Minimization ENM k=0.5"},
    })
    assert row.name == "B_tube_00_min_enm_k0p5"
    assert row.steps == 9600
    assert row.stage == "Minimization ENM k=0.5"
    assert row.status == "pending"
    assert row.percent == 100.0


def test_minimization_status_keeps_a_replicas_own_label():
    """An ensemble replica's slot is a velocity reseed, not a minimisation.

    The label must come from the manifest — a UI that assumed "Minimization" would
    tell the user a replica minimised when it only reseeded velocities.
    """
    row = minimization_status({"minimization": {"name": "r0_reseed", "steps": 0,
                                                "stage": "Velocity reseed"}})
    assert row.stage == "Velocity reseed"
    assert row.steps == 0


def test_minimization_status_falls_back_for_a_manifest_without_the_label():
    row = minimization_status({"minimization": {"name": "old_00_min", "steps": 4800}})
    assert row.stage == DEFAULT_MINIMIZATION_STAGE


def test_minimization_status_none_when_the_slot_is_absent_or_nameless():
    assert minimization_status({}) is None
    assert minimization_status({"minimization": {}}) is None
    assert minimization_status({"minimization": {"steps": 4800}}) is None
    assert minimization_status(None) is None


# ── persistence ───────────────────────────────────────────────────────────────


def _job(tmp_path) -> MdJob:
    job = new_job("demo", "equilibrium_aware_namd", "demo", "package/demo")
    job.status = MdStatus.queued
    return job


def test_minimization_survives_save_load(tmp_path):
    job = _job(tmp_path)
    job.minimization = minimization_status({
        "minimization": {"name": "demo_00_min_enm_k0p5", "steps": 9600,
                         "stage": "Minimization ENM k=0.5"},
    })
    job.save(tmp_path)

    loaded = MdJob.load(job.job_id, tmp_path)
    assert isinstance(loaded.minimization, MdSegmentStatus)
    assert loaded.minimization.name == "demo_00_min_enm_k0p5"
    assert loaded.minimization.stage == "Minimization ENM k=0.5"
    assert loaded.minimization.status == "pending"


def test_status_transition_round_trips(tmp_path):
    job = _job(tmp_path)
    job.minimization = minimization_status(
        {"minimization": {"name": "demo_00_min", "steps": 4800}})
    job.minimization.status = "running"
    job.save(tmp_path)
    assert MdJob.load(job.job_id, tmp_path).minimization.status == "running"

    job.minimization.status = "done"
    job.save(tmp_path)
    assert MdJob.load(job.job_id, tmp_path).minimization.status == "done"


def test_a_job_json_without_the_field_loads_as_none(tmp_path):
    """Every job that exists today predates this field — loading must not break."""
    job = _job(tmp_path)
    job.save(tmp_path)
    path = job.job_dir(tmp_path) / "job.json"
    import json

    data = json.loads(path.read_text())
    del data["minimization"]
    path.write_text(json.dumps(data))

    loaded = MdJob.load(job.job_id, tmp_path)
    assert loaded.minimization is None
    # …and the serialised form still carries the key, so the frontend can key off it.
    assert "minimization" in loaded.to_dict()


def test_to_dict_serialises_the_nested_record(tmp_path):
    job = _job(tmp_path)
    job.minimization = minimization_status(
        {"minimization": {"name": "demo_00_min", "steps": 4800, "stage": "Minimization"}})
    d = job.to_dict()
    assert d["minimization"] == {
        "name": "demo_00_min", "stage": "Minimization", "percent": 100.0,
        "steps": 4800, "status": "pending", "skipped": False, "auto_resumes": 0,
    }
