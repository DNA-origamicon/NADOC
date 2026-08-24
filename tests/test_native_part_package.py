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
