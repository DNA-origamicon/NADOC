"""Deferred background work must not resurrect deleted jobs or mask corruption."""
import json
import pytest
from backend.core.trajectory_precompute import prepare


@pytest.mark.parametrize("engine,folder", [("md", "md_jobs"), ("oxdna", "oxdna_jobs")])
def test_deleted_job_is_an_empty_background_operation(tmp_path, engine, folder):
    assert prepare(tmp_path, engine, "removed") is None
    assert not (tmp_path / folder / "removed").exists()


@pytest.mark.parametrize("engine,folder", [("md", "md_jobs"), ("oxdna", "oxdna_jobs")])
def test_existing_corrupt_job_still_reports_failure(tmp_path, engine, folder):
    job = tmp_path / folder / "broken"
    job.mkdir(parents=True)
    (job / "job.json").write_text("corrupt")
    with pytest.raises(json.JSONDecodeError):
        prepare(tmp_path, engine, "broken")
