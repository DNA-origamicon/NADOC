"""MdJob.load() must not crash on a field a prior schema wrote but the current
dataclass no longer declares.

MdJob fields have only ever been ADDED before (the long run of ``data.setdefault``
calls in ``load()`` back-fills a NEW field for an OLD job.json). 2026-08-21 was the
first REMOVAL (``early_stop_tier``, retired with the early-stop tier system) and
``cls(**data)`` — a plain dataclass constructor — raises TypeError on any unknown
kwarg. A real archived job (24hb_2xT, ``bb8654eef459``) still carries
``"early_stop_tier": "B"`` on disk; loading it must not crash NADOC.
"""

from __future__ import annotations

import json
from pathlib import Path

from backend.core.md_job import MdJob, new_job

_REPO = Path(__file__).resolve().parents[1]


def test_load_drops_a_retired_field_instead_of_crashing(tmp_path):
    job = new_job("d", "mgh_slow_release", "d", "package/d_namd_solvated")
    job.save(tmp_path)

    job_json = job.job_dir(tmp_path) / "job.json"
    data = json.loads(job_json.read_text())
    data["early_stop_tier"] = "B"  # simulate a job saved under the old schema
    data["some_future_retired_field"] = {"anything": "at all"}
    job_json.write_text(json.dumps(data))

    loaded = MdJob.load(job.job_id, tmp_path)
    assert loaded.job_id == job.job_id
    assert not hasattr(loaded, "early_stop_tier")


def test_the_real_archived_24hb_2xT_job_still_loads():
    """Direct regression pin: this exact job.json (still on disk) triggered the bug."""
    archive = Path("/media/jojo/Archive/NADOC_archive/bb8654eef459/job.json")
    if not archive.exists():
        import pytest

        pytest.skip("archived job not present on this machine")
    data = json.loads(archive.read_text())
    assert data.get("early_stop_tier") == "B"  # confirms this pins the real scenario

    job = MdJob.load("bb8654eef459", _REPO / "workspace")
    assert job.design_name == "24hb_2xT"
    assert not hasattr(job, "early_stop_tier")
