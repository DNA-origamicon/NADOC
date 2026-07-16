"""Run-location: a run can be archived-from-birth at a chosen directory, and the disk
forecast recommends a roomier volume when the target won't fit."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import backend.api.routes_md as rm
from backend.core.md_job import new_job
from backend.core.job_archive import read_index
from backend.core import disk_guard


def _job():
    return new_job(design_name="d", protocol="equilibrium_aware_namd",
                   name_stem="", package_subdir="")


def test_apply_run_dir_archives_from_birth(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    (ws / "md_jobs").mkdir(parents=True)
    monkeypatch.setattr(rm, "_workspace", lambda: ws)
    run_dir = tmp_path / "BigDrive"
    run_dir.mkdir()

    job = _job()
    rm._apply_run_dir(job, str(run_dir))

    dest = run_dir.resolve() / job.job_id
    assert job.archived is True
    assert job.archive_path == str(dest)
    assert dest.is_dir()                                   # created for prep to write into
    assert read_index(ws, "md_jobs").get(job.job_id) == str(dest)   # resolvable by the app


def test_apply_run_dir_none_is_noop(tmp_path, monkeypatch):
    monkeypatch.setattr(rm, "_workspace", lambda: tmp_path)
    job = _job()
    rm._apply_run_dir(job, None)
    assert job.archived is False and job.archive_path is None


def test_apply_run_dir_rejects_missing_or_unwritable(tmp_path, monkeypatch):
    monkeypatch.setattr(rm, "_workspace", lambda: tmp_path)
    with pytest.raises(HTTPException):
        rm._apply_run_dir(_job(), str(tmp_path / "nope"))          # does not exist
    f = tmp_path / "afile"
    f.write_text("x")
    with pytest.raises(HTTPException):
        rm._apply_run_dir(_job(), str(f))                          # not a directory


def test_forecast_recommends_archive_only_when_tight(tmp_path):
    # A tiny run leaves plenty of room → no warn, no suggestion.
    f_small = disk_guard.forecast(tmp_path, 1 << 20)
    assert f_small["warn"] is False
    assert f_small["suggested_archive"] is None
    # A run bigger than the whole volume → warn; suggestion is either a roomier OTHER-fs
    # volume (shape-checked) or None if this box genuinely has none.
    huge = disk_guard.free_bytes(tmp_path) + (100 << 30)
    f_big = disk_guard.forecast(tmp_path, huge)
    assert f_big["warn"] is True
    s = f_big["suggested_archive"]
    assert s is None or ("path" in s and s["free_bytes"] >= huge + disk_guard.WARN_MIN_FREE_BYTES)
