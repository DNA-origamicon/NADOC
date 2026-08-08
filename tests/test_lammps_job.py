"""Tests for the lean LAMMPS job model (backend/core/lammps_job)."""

from __future__ import annotations

from backend.core.lammps_job import LammpsJob, LammpsStatus, new_lammps_job


def test_new_job_defaults():
    job = new_lammps_job("6hb", n_atoms=504, n_bonds=492, steps=5000)
    assert job.status is LammpsStatus.queued
    assert job.design_name == "6hb"
    assert job.n_atoms == 504 and job.n_bonds == 492
    assert job.steps == 5000 and job.ranks == 1
    assert len(job.job_id) == 12


def test_save_load_roundtrip(tmp_path):
    job = new_lammps_job("d", n_atoms=10, steps=2000, temperature=0.09, salt_molar=0.3)
    job.status = LammpsStatus.running
    job.current_step = 1500
    job.lammps_pid = 4242
    job.save(tmp_path)

    loaded = LammpsJob.load(job.job_id, tmp_path)
    assert loaded.status is LammpsStatus.running
    assert loaded.current_step == 1500
    assert loaded.lammps_pid == 4242
    assert loaded.temperature == 0.09 and loaded.salt_molar == 0.3


def test_load_tolerates_missing_newer_fields(tmp_path):
    job = new_lammps_job("d")
    job.save(tmp_path)
    # simulate an older job.json lacking some fields
    import json

    p = job.job_dir(tmp_path) / "job.json"
    data = json.loads(p.read_text())
    for k in ("parent_job_id", "lammps_path", "frames", "current_step", "ranks"):
        data.pop(k, None)
    p.write_text(json.dumps(data))
    loaded = LammpsJob.load(job.job_id, tmp_path)  # setdefaults fill them
    assert loaded.ranks == 1 and loaded.frames == 0 and loaded.parent_job_id is None


def test_list_jobs_returns_all(tmp_path):
    ids = {new_lammps_job(f"d{i}").job_id for i in range(3)}
    for jid in ids:
        LammpsJob(
            job_id=jid, design_name="d", status=LammpsStatus.completed, created_at=0.0
        ).save(tmp_path)
    listed = {j.job_id for j in LammpsJob.list_jobs(tmp_path)}
    assert ids <= listed


def test_to_dict_serialises_status_as_string():
    d = new_lammps_job("d").to_dict()
    assert d["status"] == "queued"
    assert isinstance(d["status"], str)
