"""Tests for backend.core.job_cleanup — associating a deleted workspace path
with the MD / oxDNA job folders generated from it."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.core.job_cleanup import find_associated_jobs, path_matches
from backend.core.md_job import new_job as new_md_job
from backend.core.oxdna_job import new_oxdna_job


class TestPathMatches:
    def test_file_exact_match(self) -> None:
        assert path_matches("beam.nadoc", "beam.nadoc", False)

    def test_file_no_match(self) -> None:
        assert not path_matches("beam.nadoc", "other.nadoc", False)

    def test_file_target_does_not_prefix_match(self) -> None:
        # A file target must be exact — a sibling sharing a stem must not match.
        assert not path_matches("beam2.nadoc", "beam.nadoc", False)

    def test_folder_contains_descendant(self) -> None:
        assert path_matches("sub/beam.nadoc", "sub", True)

    def test_folder_contains_nested_descendant(self) -> None:
        assert path_matches("sub/deep/beam.nadoc", "sub", True)

    def test_folder_excludes_sibling_prefix(self) -> None:
        # "sub2/..." must not match folder "sub" via raw string prefix.
        assert not path_matches("sub2/beam.nadoc", "sub", True)

    def test_backslash_and_trailing_slash_normalised(self) -> None:
        assert path_matches("sub\\beam.nadoc", "sub/", True)

    def test_empty_source_never_matches(self) -> None:
        assert not path_matches(None, "beam.nadoc", False)
        assert not path_matches("", "sub", True)


class TestFindAssociatedJobs:
    def test_matches_by_file(self, tmp_path: Path) -> None:
        a = new_md_job("A", "mgh_slow_release", "A", "pkg", design_source_path="a.nadoc")
        b = new_md_job("B", "mgh_slow_release", "B", "pkg", design_source_path="b.nadoc")
        a.save(tmp_path)
        b.save(tmp_path)
        ox = new_oxdna_job("A", [], design_source_path="a.nadoc")
        ox.save(tmp_path)

        found = find_associated_jobs(tmp_path, "a.nadoc", False)
        assert {j.job_id for j in found["md"]} == {a.job_id}
        assert {j.job_id for j in found["oxdna"]} == {ox.job_id}

    def test_matches_by_folder(self, tmp_path: Path) -> None:
        inside = new_md_job("X", "mgh_slow_release", "X", "pkg", design_source_path="figs/x.nadoc")
        outside = new_md_job("Y", "mgh_slow_release", "Y", "pkg", design_source_path="y.nadoc")
        inside.save(tmp_path)
        outside.save(tmp_path)

        found = find_associated_jobs(tmp_path, "figs", True)
        assert {j.job_id for j in found["md"]} == {inside.job_id}

    def test_no_jobs_for_unrelated_path(self, tmp_path: Path) -> None:
        new_md_job("A", "mgh_slow_release", "A", "pkg", design_source_path="a.nadoc").save(tmp_path)
        found = find_associated_jobs(tmp_path, "nope.nadoc", False)
        assert found == {"md": [], "oxdna": []}

    def test_empty_workspace(self, tmp_path: Path) -> None:
        found = find_associated_jobs(tmp_path, "a.nadoc", False)
        assert found == {"md": [], "oxdna": []}


class TestLibraryDeleteRoute:
    """Endpoint behaviour: GET /library/file/jobs + DELETE with delete_jobs."""

    @pytest.fixture
    def client(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from fastapi.testclient import TestClient

        from backend.api import assembly
        from backend.api.main import app

        monkeypatch.setattr(assembly, "_WORKSPACE_DIR", tmp_path)
        (tmp_path / "a.nadoc").write_text("{}")
        return TestClient(app), tmp_path

    def test_lists_associated_jobs(self, client) -> None:
        c, ws = client
        new_md_job("A", "mgh_slow_release", "A", "pkg", design_source_path="a.nadoc").save(ws)
        new_oxdna_job("A", [], design_source_path="a.nadoc").save(ws)
        r = c.get("/api/library/file/jobs", params={"path": "a.nadoc"})
        assert r.status_code == 200
        body = r.json()
        assert len(body["md"]) == 1
        assert len(body["oxdna"]) == 1
        assert body["running"] is False

    def test_delete_without_flag_keeps_jobs(self, client) -> None:
        c, ws = client
        job = new_md_job("A", "mgh_slow_release", "A", "pkg", design_source_path="a.nadoc")
        job.save(ws)
        r = c.delete("/api/library/file", params={"path": "a.nadoc"})
        assert r.status_code == 200
        assert r.json()["deleted_jobs"] == []
        assert job.job_dir(ws).exists()           # job folder untouched
        assert not (ws / "a.nadoc").exists()       # file gone

    def test_delete_with_flag_removes_job_folders(self, client) -> None:
        c, ws = client
        job = new_md_job("A", "mgh_slow_release", "A", "pkg", design_source_path="a.nadoc")
        job.save(ws)
        r = c.delete("/api/library/file", params={"path": "a.nadoc", "delete_jobs": "true"})
        assert r.status_code == 200
        assert r.json()["deleted_jobs"] == [job.job_id]
        assert not job.job_dir(ws).exists()
        assert not (ws / "a.nadoc").exists()

    def test_delete_blocked_when_job_running(self, client) -> None:
        from backend.core.md_job import MdStatus

        c, ws = client
        job = new_md_job("A", "mgh_slow_release", "A", "pkg", design_source_path="a.nadoc")
        job.status = MdStatus.running
        job.save(ws)
        r = c.delete("/api/library/file", params={"path": "a.nadoc", "delete_jobs": "true"})
        assert r.status_code == 409
        assert job.job_dir(ws).exists()            # nothing deleted
        assert (ws / "a.nadoc").exists()           # file kept too (whole op refused)
