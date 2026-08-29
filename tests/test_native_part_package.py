import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api import assembly
from backend.api.main import app
from backend.api.routes import _demo_design
from backend.core import native_part_package as package


class FakeJob:
    job_id = "job-1"
    design_source_path = "parts/a.nadoc"
    status = "completed"
    project_id = "project-1"
    design_revision_id = "a" * 64
    design_name = "a"
    created_at = 1.0

    def __init__(self, root):
        self.root = root

    def job_dir(self, _workspace):
        return self.root


class FakeJobClass:
    __module__ = "backend.core.oxdna_job"
    jobs = []

    @classmethod
    def list_jobs(cls, _workspace):
        return cls.jobs


def test_portable_part_package_round_trip(tmp_path: Path, monkeypatch) -> None:
    source_ws = tmp_path / "source"
    destination_ws = tmp_path / "destination"
    part = source_ws / "parts" / "a.nadoc"
    part.parent.mkdir(parents=True)
    part.write_text(_demo_design().to_json())
    job_dir = source_ws / "oxdna_jobs" / "job-1"
    (job_dir / "trajectory").mkdir(parents=True)
    (job_dir / "job.json").write_text(json.dumps({
        "job_id": "job-1", "design_source_path": "parts/a.nadoc",
        "archived": True, "archive_path": "/old/computer/archive",
    }))
    (job_dir / "trajectory" / "last.dat").write_bytes(b"large-result")
    FakeJobClass.jobs = [FakeJob(job_dir)]
    monkeypatch.setattr(package, "_job_classes", lambda: (FakeJobClass,))

    archive = tmp_path / "a.nadocpkg"
    manifest = package.create_package(source_ws, "parts/a.nadoc", archive)
    assert manifest["simulations"][0]["tree"] == "oxdna_jobs"

    result = package.import_package(destination_ws, archive, "imported/a.nadoc")
    assert result["simulations"] == ["oxdna_jobs/job-1"]
    assert (destination_ws / "imported" / "a.nadoc").is_file()
    assert (destination_ws / "oxdna_jobs/job-1/trajectory/last.dat").read_bytes() == b"large-result"
    restored = json.loads((destination_ws / "oxdna_jobs/job-1/job.json").read_text())
    assert restored["design_source_path"] == "imported/a.nadoc"
    assert restored["archived"] is False
    assert restored["archive_path"] is None


def test_import_refuses_existing_job_without_partial_install(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(package, "_job_classes", lambda: (FakeJobClass,))
    archive = tmp_path / "p.nadocpkg"
    design = _demo_design().to_json()
    manifest = {
        "format": package.FORMAT, "version": 1,
        "part": {"archive_path": "part/p.nadoc", "source_path": "p.nadoc"},
        "simulations": [{"tree": "oxdna_jobs", "job_id": "same", "archive_path": "simulations/oxdna_jobs/same"}],
    }
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("part/p.nadoc", design)
        zf.writestr("simulations/oxdna_jobs/same/job.json", "{}")
    (tmp_path / "ws/oxdna_jobs/same").mkdir(parents=True)

    with pytest.raises(FileExistsError):
        package.import_package(tmp_path / "ws", archive, "p.nadoc")
    assert not (tmp_path / "ws/p.nadoc").exists()


def test_import_rejects_zip_slip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(package, "_job_classes", lambda: (FakeJobClass,))
    archive = tmp_path / "bad.nadocpkg"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../outside", "bad")
    with pytest.raises(ValueError, match="unsafe archive path"):
        package.import_package(tmp_path / "ws", archive, "p.nadoc")


def test_thin_package_carries_history_without_artifact_bytes(tmp_path: Path, monkeypatch) -> None:
    source_ws = tmp_path / "source"
    part = source_ws / "parts/a.nadoc"
    part.parent.mkdir(parents=True)
    part.write_text(_demo_design().to_json())
    job_dir = source_ws / "oxdna_jobs/job-1"
    job_dir.mkdir(parents=True)
    (job_dir / "job.json").write_text("{}")
    (job_dir / "huge.dat").write_bytes(b"large-result")
    FakeJobClass.jobs = [FakeJob(job_dir)]
    monkeypatch.setattr(package, "_job_classes", lambda: (FakeJobClass,))

    archive = tmp_path / "thin.nadocpkg"
    manifest = package.create_package(
        source_ws, "parts/a.nadoc", archive, mode="thin"
    )
    assert manifest["mode"] == "thin"
    assert manifest["simulations"][0]["included"] is False
    with zipfile.ZipFile(archive) as zipped:
        assert not any(name.endswith("huge.dat") for name in zipped.namelist())
    result = package.import_package(tmp_path / "destination", archive, "a.nadoc")
    assert result["simulations"] == []
    assert result["referenced_simulations"][0]["job_id"] == "job-1"
    assert result["mode"] == "thin"


def test_selected_package_includes_only_requested_jobs(tmp_path: Path, monkeypatch) -> None:
    source_ws = tmp_path / "source"
    part = source_ws / "parts/a.nadoc"
    part.parent.mkdir(parents=True)
    part.write_text(_demo_design().to_json())
    first_dir = source_ws / "oxdna_jobs/job-1"
    second_dir = source_ws / "oxdna_jobs/job-2"
    for directory, marker in ((first_dir, b"one"), (second_dir, b"two")):
        directory.mkdir(parents=True)
        (directory / "job.json").write_text("{}")
        (directory / "result.dat").write_bytes(marker)
    first = FakeJob(first_dir)
    second = FakeJob(second_dir)
    second.job_id = "job-2"
    FakeJobClass.jobs = [first, second]
    monkeypatch.setattr(package, "_job_classes", lambda: (FakeJobClass,))

    archive = tmp_path / "selected.nadocpkg"
    manifest = package.create_package(
        source_ws,
        "parts/a.nadoc",
        archive,
        mode="selected",
        selected_job_ids={"job-2"},
    )
    included = {item["job_id"]: item["included"] for item in manifest["simulations"]}
    assert included == {"job-1": False, "job-2": True}
    result = package.import_package(tmp_path / "destination", archive, "a.nadoc")
    assert result["simulations"] == ["oxdna_jobs/job-2"]
    assert not (tmp_path / "destination/oxdna_jobs/job-1").exists()


def test_selected_package_rejects_unknown_or_empty_selection(tmp_path: Path, monkeypatch) -> None:
    source_ws = tmp_path / "source"
    source_ws.mkdir()
    (source_ws / "a.nadoc").write_text(_demo_design().to_json())
    FakeJobClass.jobs = []
    monkeypatch.setattr(package, "_job_classes", lambda: (FakeJobClass,))
    with pytest.raises(ValueError, match="at least one"):
        package.create_package(source_ws, "a.nadoc", tmp_path / "a.pkg", mode="selected")
    with pytest.raises(ValueError, match="not associated"):
        package.create_package(
            source_ws,
            "a.nadoc",
            tmp_path / "b.pkg",
            mode="selected",
            selected_job_ids={"missing"},
        )


def test_download_and_streaming_upload_routes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(assembly, "_WORKSPACE_DIR", tmp_path)
    (tmp_path / "source.nadoc").write_text(_demo_design().to_json())
    client = TestClient(app)

    downloaded = client.get("/api/library/native-package", params={"path": "source.nadoc"})
    assert downloaded.status_code == 200
    assert downloaded.headers["content-disposition"].endswith('filename="source.nadocpkg"')

    uploaded = client.post(
        "/api/library/native-package",
        params={"path": "copies/restored.nadoc"},
        content=downloaded.content,
        headers={"content-type": "application/vnd.nadoc.part-package+zip"},
    )
    assert uploaded.status_code == 201, uploaded.text
    assert uploaded.json()["path"] == "copies/restored.nadoc"
    assert (tmp_path / "copies/restored.nadoc").is_file()
