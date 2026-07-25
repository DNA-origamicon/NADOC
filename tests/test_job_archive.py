"""Tests for backend.core.job_archive + the archive/unarchive/fs-browse routes —
moving a job's heavy folder off-workspace while keeping its list entry, size, and
the ability to chain new jobs off it."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from backend.core import job_archive as ja
from backend.core.md_job import new_job as new_md_job
from backend.core.oxdna_job import OxdnaJob, new_oxdna_job


def _wait(kind: str, job_id: str, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = ja.task_status(kind, job_id)
        if st and st["state"] in ("done", "error"):
            return st
        time.sleep(0.02)
    raise AssertionError(f"archive task for {job_id} did not finish: {ja.task_status(kind, job_id)}")


class TestIndex:
    def test_resolve_default_and_archived(self, tmp_path: Path) -> None:
        assert ja.resolve_job_json(tmp_path, "oxdna_jobs", "abc") == tmp_path / "oxdna_jobs" / "abc" / "job.json"
        ja._write_index(tmp_path, "oxdna_jobs", {"abc": "/ext/abc"})
        assert ja.resolve_job_json(tmp_path, "oxdna_jobs", "abc") == Path("/ext/abc") / "job.json"
        assert ja.archived_job_ids(tmp_path, "oxdna_jobs") == ["abc"]

    def test_purge(self, tmp_path: Path) -> None:
        ja._write_index(tmp_path, "md_jobs", {"a": "/x/a", "b": "/x/b"})
        ja.purge_index_entry(tmp_path, "md_jobs", "a")
        assert ja.archived_job_ids(tmp_path, "md_jobs") == ["b"]


class TestArchiveRoundTrip:
    def test_oxdna_archive_then_unarchive(self, tmp_path: Path) -> None:
        ws = tmp_path / "ws"
        arch = tmp_path / "ext"
        ws.mkdir()
        job = new_oxdna_job("demo", [], design_source_path="demo.nadoc")
        job.save(ws)
        (job.job_dir(ws) / "trajectory.dat").write_bytes(b"x" * 5000)

        ja.start_archive(job, ws, "oxdna_jobs", arch)
        st = _wait("oxdna_jobs", job.job_id)
        assert st["state"] == "done"
        assert st["total_bytes"] >= 5000

        # Source gone, destination present, index updated.
        assert not (ws / "oxdna_jobs" / job.job_id).exists()
        assert (arch / job.job_id / "trajectory.dat").exists()
        assert ja.archived_job_ids(ws, "oxdna_jobs") == [job.job_id]

        # Still discoverable + resolves to the archive location.
        reloaded = OxdnaJob.list_jobs(ws)
        assert [j.job_id for j in reloaded] == [job.job_id]
        j2 = reloaded[0]
        assert j2.archived and j2.job_dir(ws) == arch / job.job_id

        ja.start_unarchive(j2, ws, "oxdna_jobs")
        st = _wait("oxdna_jobs", job.job_id)
        assert st["state"] == "done"
        assert (ws / "oxdna_jobs" / job.job_id / "trajectory.dat").exists()
        assert not (arch / job.job_id).exists()
        assert ja.archived_job_ids(ws, "oxdna_jobs") == []
        assert OxdnaJob.list_jobs(ws)[0].archived is False

    def test_archive_job_sync_moves_and_indexes(self, tmp_path: Path) -> None:
        # The blocking archive_job (for headless/scripted callers) moves the folder,
        # flips `archived`, updates the index, and leaves the job loadable — same end
        # state as the async start_archive, but inline (no task polling).
        ws = tmp_path / "ws"; ws.mkdir()
        arch = tmp_path / "ext"
        job = new_oxdna_job("demo", [], design_source_path="demo.nadoc")
        job.save(ws)
        (job.job_dir(ws) / "trajectory.dat").write_bytes(b"x" * 4096)

        dest = ja.archive_job(job, ws, "oxdna_jobs", arch)
        assert dest == str(arch / job.job_id)
        assert not (ws / "oxdna_jobs" / job.job_id).exists()        # source moved
        assert (arch / job.job_id / "trajectory.dat").exists()       # data preserved
        assert ja.archived_job_ids(ws, "oxdna_jobs") == [job.job_id]
        j2 = OxdnaJob.list_jobs(ws)[0]
        assert j2.archived and j2.job_dir(ws) == arch / job.job_id

    def test_archive_job_sync_rejects_double_archive(self, tmp_path: Path) -> None:
        ws = tmp_path / "ws"; ws.mkdir()
        job = new_oxdna_job("d", [])
        job.save(ws)
        job.archived = True
        with pytest.raises(ValueError):
            ja.archive_job(job, ws, "oxdna_jobs", tmp_path / "ext")

    def test_archive_rejects_double_archive(self, tmp_path: Path) -> None:
        ws = tmp_path / "ws"; ws.mkdir()
        job = new_oxdna_job("d", [])
        job.save(ws)
        job.archived = True
        job.archive_path = "/somewhere"
        with pytest.raises(ValueError):
            ja.start_archive(job, ws, "oxdna_jobs", tmp_path / "ext")

    def test_archive_rejects_symlinked_job_dir(self, tmp_path: Path) -> None:
        # A job whose workspace folder is a symlink (manually relocated to an
        # external drive) must NOT be followed-and-copied — that duplicated 40 GB
        # in the field. Refuse with a clear error instead.
        ws = tmp_path / "ws"; (ws / "oxdna_jobs").mkdir(parents=True)
        real = tmp_path / "external"; real.mkdir()
        job = new_oxdna_job("d", [])
        # Build the job at the external location, then symlink the workspace slot.
        real_job = real / job.job_id
        real_job.mkdir()
        (real_job / "job.json").write_text("{}")
        (ws / "oxdna_jobs" / job.job_id).symlink_to(real_job)
        with pytest.raises(ValueError, match="symlink"):
            ja.start_archive(job, ws, "oxdna_jobs", tmp_path / "dest")
        # Nothing copied, original intact.
        assert real_job.exists()
        assert not (tmp_path / "dest").exists()

    def test_archive_rejects_existing_dest(self, tmp_path: Path) -> None:
        ws = tmp_path / "ws"; ws.mkdir()
        job = new_md_job("A", "mgh_slow_release", "A", "pkg")
        job.save(ws)
        dest_root = tmp_path / "ext"
        (dest_root / job.job_id).mkdir(parents=True)   # pre-existing collision
        with pytest.raises(FileExistsError):
            ja.start_archive(job, ws, "md_jobs", dest_root)


class TestRoutes:
    @pytest.fixture
    def client(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from fastapi.testclient import TestClient

        from backend.api import assembly
        from backend.api import state as design_state
        from backend.api.main import app
        from tests.conftest import make_minimal_design

        monkeypatch.setattr(assembly, "_WORKSPACE_DIR", tmp_path)
        # routes_md/_oxdna read their own _workspace(); point those at tmp_path too.
        from backend.api import routes_md, routes_oxdna
        monkeypatch.setattr(routes_md, "_workspace", lambda: tmp_path)
        monkeypatch.setattr(routes_oxdna, "_workspace", lambda: tmp_path)
        design_state.set_design(make_minimal_design())
        return TestClient(app), tmp_path

    def test_md_list_includes_size(self, client) -> None:
        from backend.core.design_disk_usage import warm_dir_sizes

        c, ws = client
        job = new_md_job("A", "mgh_slow_release", "A", "pkg", design_source_path="a.nadoc")
        job.save(ws)
        (job.job_dir(ws) / "blob.bin").write_bytes(b"\0" * 2048)
        # Size is warmed lazily OFF the poll hot path: a cold list reports None (never blocks
        # on a multi-GB stat-walk), then the background walk fills it in for the next poll.
        r = c.get("/api/md/jobs")
        assert r.status_code == 200
        entry = next(e for e in r.json() if e["job_id"] == job.job_id)
        assert entry["size_bytes"] is None or entry["size_bytes"] >= 2048
        assert entry["archived"] is False
        warm_dir_sizes([job.job_dir(ws)])   # what the scheduled background task does
        # The list endpoint's own fire-and-forget warm (from the cold GET above) may
        # still hold the _warming claim on this dir, in which case our warm_dir_sizes()
        # dedups to a no-op and the size fills in a beat later once that walk finishes.
        # The feature is eventually-consistent by design, so poll rather than assume a
        # single call populated the cache synchronously (the source of a full-suite flake).
        size = None
        for _ in range(100):
            size = next(e for e in c.get("/api/md/jobs").json()
                        if e["job_id"] == job.job_id)["size_bytes"]
            if size is not None:
                break
            time.sleep(0.02)
        assert size is not None and size >= 2048

    def test_oxdna_archive_unarchive_via_api(self, client, tmp_path) -> None:
        c, ws = client
        job = new_oxdna_job("demo", [], design_source_path="demo.nadoc")
        job.save(ws)
        (job.job_dir(ws) / "trajectory.dat").write_bytes(b"x" * 3000)
        dest_root = tmp_path / "archive_drive"

        r = c.post(f"/api/oxdna/jobs/{job.job_id}/archive", json={"dest_root": str(dest_root)})
        assert r.status_code == 202
        _wait("oxdna_jobs", job.job_id)

        # Job still listed, now archived with the right size + path.
        entry = next(e for e in c.get("/api/oxdna/jobs").json() if e["job_id"] == job.job_id)
        assert entry["archived"] is True
        assert entry["archive_path"] == str(dest_root / job.job_id)
        assert entry["size_bytes"] >= 3000

        st = c.get(f"/api/oxdna/jobs/{job.job_id}/archive-status").json()
        assert st["state"] == "done"

        r = c.post(f"/api/oxdna/jobs/{job.job_id}/unarchive")
        assert r.status_code == 202
        _wait("oxdna_jobs", job.job_id)
        entry = next(e for e in c.get("/api/oxdna/jobs").json() if e["job_id"] == job.job_id)
        assert entry["archived"] is False

    def test_fs_listdir_and_mkdir(self, client, tmp_path) -> None:
        c, _ = client
        (tmp_path / "sub_a").mkdir()
        (tmp_path / "sub_b").mkdir()
        (tmp_path / "file.txt").write_text("x")
        r = c.get("/api/fs/listdir", params={"path": str(tmp_path)})
        assert r.status_code == 200
        body = r.json()
        names = [e["name"] for e in body["entries"]]
        assert names == ["sub_a", "sub_b"]          # dirs only, sorted, no files
        assert body["parent"] == str(tmp_path.parent)

        r = c.post("/api/fs/mkdir", json={"path": str(tmp_path), "name": "fresh"})
        assert r.status_code == 201
        assert "fresh" in [e["name"] for e in r.json()["entries"]]
        assert (tmp_path / "fresh").is_dir()

    def test_fs_mkdir_rejects_separators(self, client, tmp_path) -> None:
        c, _ = client
        r = c.post("/api/fs/mkdir", json={"path": str(tmp_path), "name": "a/b"})
        assert r.status_code == 400
