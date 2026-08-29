from __future__ import annotations

import pytest

from backend.core.oxdna_job import OxdnaStatus, new_oxdna_job
from backend.core.project_artifacts import ProjectArtifactCatalog


def _job(tmp_path, status=OxdnaStatus.completed):
    job = new_oxdna_job(
        "Part",
        [],
        project_id="project-1",
        design_revision_id="a" * 64,
    )
    job.status = status
    job.save(tmp_path)
    (job.job_dir(tmp_path) / "design.json").write_text("{}")
    (job.job_dir(tmp_path) / "trajectory.dat").write_bytes(b"frames")
    return job


def test_local_job_metadata_is_lightweight_and_location_aware(tmp_path):
    job = _job(tmp_path)
    catalog = ProjectArtifactCatalog(tmp_path)
    records = catalog.publish_local_jobs("project-1")
    assert len(records) == 1
    record = records[0]
    assert record["job_id"] == job.job_id
    assert record["project_id"] == "project-1"
    assert record["design_revision_id"] == "a" * 64
    assert record["locations"][0]["available"] is True
    assert record["locations"][0]["active"] is False
    assert "trajectory" not in record


def test_remote_metadata_merges_locations_without_creating_job_directory(tmp_path):
    job = _job(tmp_path)
    catalog = ProjectArtifactCatalog(tmp_path)
    local = catalog.publish_local_jobs("project-1")[0]
    remote = {
        **local,
        "locations": [
            {
                "server_id": "remote",
                "server_name": "Remote PC",
                "available": True,
                "active": False,
                "updated_at": 1,
            }
        ],
    }
    merged = catalog.merge(remote)
    assert {item["server_id"] for item in merged["locations"]} == {
        "remote",
        local["locations"][0]["server_id"],
    }
    assert job.job_dir(tmp_path).is_dir()  # only the original local job exists


def test_artifact_listing_and_path_resolution_are_confined_to_job(tmp_path):
    job = _job(tmp_path)
    catalog = ProjectArtifactCatalog(tmp_path)
    files = catalog.list_files("project-1", "oxdna", job.job_id)
    assert {item["path"] for item in files} == {
        "design.json",
        "job.json",
        "trajectory.dat",
    }
    assert catalog.artifact_file(
        "project-1", "oxdna", job.job_id, "trajectory.dat"
    ).read_bytes() == b"frames"
    with pytest.raises(FileNotFoundError):
        catalog.artifact_file("project-1", "oxdna", job.job_id, "../../secret")


def test_active_jobs_can_stream_existing_files_but_cannot_be_copied(tmp_path):
    job = _job(tmp_path, OxdnaStatus.running)
    catalog = ProjectArtifactCatalog(tmp_path)
    assert catalog.artifact_file(
        "project-1", "oxdna", job.job_id, "trajectory.dat"
    ).is_file()
    with pytest.raises(RuntimeError, match="active"):
        catalog.assert_fetchable("project-1", "oxdna", job.job_id)
