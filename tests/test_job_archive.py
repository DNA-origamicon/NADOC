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
    raise AssertionError(
        f"archive task for {job_id} did not finish: {ja.task_status(kind, job_id)}"
    )


class TestIndex:
    def test_resolve_default_and_archived(self, tmp_path: Path) -> None:
        assert (
            ja.resolve_job_json(tmp_path, "oxdna_jobs", "abc")
            == tmp_path / "oxdna_jobs" / "abc" / "job.json"
        )
        ja._write_index(tmp_path, "oxdna_jobs", {"abc": "/ext/abc"})
        assert (
            ja.resolve_job_json(tmp_path, "oxdna_jobs", "abc")
            == Path("/ext/abc") / "job.json"
        )
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
        ws = tmp_path / "ws"
        ws.mkdir()
        arch = tmp_path / "ext"
        job = new_oxdna_job("demo", [], design_source_path="demo.nadoc")
        job.save(ws)
        (job.job_dir(ws) / "trajectory.dat").write_bytes(b"x" * 4096)

        dest = ja.archive_job(job, ws, "oxdna_jobs", arch)
        assert dest == str(arch / job.job_id)
        assert not (ws / "oxdna_jobs" / job.job_id).exists()  # source moved
        assert (arch / job.job_id / "trajectory.dat").exists()  # data preserved
        assert ja.archived_job_ids(ws, "oxdna_jobs") == [job.job_id]
        j2 = OxdnaJob.list_jobs(ws)[0]
        assert j2.archived and j2.job_dir(ws) == arch / job.job_id

    def test_job_can_move_from_one_external_directory_to_another(self, tmp_path: Path) -> None:
        ws = tmp_path / "ws"
        ws.mkdir()
        job = new_oxdna_job("d", [])
        job.save(ws)
        first = tmp_path / "first"
        second = tmp_path / "second"
        ja.archive_job(job, ws, "oxdna_jobs", first)
        moved = OxdnaJob.list_jobs(ws)[0]
        ja.archive_job(moved, ws, "oxdna_jobs", second)
        assert not (first / job.job_id).exists()
        assert (second / job.job_id / "job.json").exists()
        assert OxdnaJob.list_jobs(ws)[0].archive_path == str(second / job.job_id)

    def test_move_rejects_unmounted_source(self, tmp_path: Path) -> None:
        ws = tmp_path / "ws"
        ws.mkdir()
        job = new_oxdna_job("d", [])
        job.save(ws)
        job.archived = True
        job.archive_path = "/somewhere"
        with pytest.raises(FileNotFoundError):
            ja.start_archive(job, ws, "oxdna_jobs", tmp_path / "ext")

    def test_archive_rejects_symlinked_job_dir(self, tmp_path: Path) -> None:
        # A job whose workspace folder is a symlink (manually relocated to an
        # external drive) must NOT be followed-and-copied — that duplicated 40 GB
        # in the field. Refuse with a clear error instead.
        ws = tmp_path / "ws"
        (ws / "oxdna_jobs").mkdir(parents=True)
        real = tmp_path / "external"
        real.mkdir()
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
        ws = tmp_path / "ws"
        ws.mkdir()
        job = new_md_job("A", "mgh_slow_release", "A", "pkg")
        job.save(ws)
        dest_root = tmp_path / "ext"
        (dest_root / job.job_id).mkdir(parents=True)  # pre-existing collision
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
        job = new_md_job(
            "A", "mgh_slow_release", "A", "pkg", design_source_path="a.nadoc"
        )
        job.save(ws)
        (job.job_dir(ws) / "blob.bin").write_bytes(b"\0" * 2048)
        # Size is warmed lazily OFF the poll hot path: a cold list reports None (never blocks
        # on a multi-GB stat-walk), then the background walk fills it in for the next poll.
        r = c.get("/api/md/jobs")
        assert r.status_code == 200
        entry = next(e for e in r.json() if e["job_id"] == job.job_id)
        assert entry["size_bytes"] is None or entry["size_bytes"] >= 2048
        assert entry["archived"] is False
        warm_dir_sizes([job.job_dir(ws)])  # what the scheduled background task does
        # The list endpoint's own fire-and-forget warm (from the cold GET above) may
        # still hold the _warming claim on this dir, in which case our warm_dir_sizes()
        # dedups to a no-op and the size fills in a beat later once that walk finishes.
        # The feature is eventually-consistent by design, so poll rather than assume a
        # single call populated the cache synchronously (the source of a full-suite flake).
        size = None
        for _ in range(100):
            size = next(
                e for e in c.get("/api/md/jobs").json() if e["job_id"] == job.job_id
            )["size_bytes"]
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

        r = c.post(
            f"/api/oxdna/jobs/{job.job_id}/archive", json={"dest_root": str(dest_root)}
        )
        assert r.status_code == 202
        _wait("oxdna_jobs", job.job_id)

        # Job still listed, now archived with the right size + path. The archived
        # directory is a cache-cold path the first time it's listed — oxdna/jobs
        # reports size_bytes eventually-consistently (like md/jobs above), so poll
        # rather than assume the first response already ran the background warm.
        entry = next(
            e for e in c.get("/api/oxdna/jobs").json() if e["job_id"] == job.job_id
        )
        assert entry["archived"] is True
        assert entry["archive_path"] == str(dest_root / job.job_id)
        size = entry["size_bytes"]
        for _ in range(100):
            if size is not None:
                break
            time.sleep(0.02)
            size = next(
                e for e in c.get("/api/oxdna/jobs").json() if e["job_id"] == job.job_id
            )["size_bytes"]
        assert size is not None and size >= 3000

        st = c.get(f"/api/oxdna/jobs/{job.job_id}/archive-status").json()
        assert st["state"] == "done"

        r = c.post(f"/api/oxdna/jobs/{job.job_id}/unarchive")
        assert r.status_code == 202
        _wait("oxdna_jobs", job.job_id)
        entry = next(
            e for e in c.get("/api/oxdna/jobs").json() if e["job_id"] == job.job_id
        )
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
        assert names == ["sub_a", "sub_b"]  # dirs only, sorted, no files
        assert body["parent"] == str(tmp_path.parent)

        r = c.post("/api/fs/mkdir", json={"path": str(tmp_path), "name": "fresh"})
        assert r.status_code == 201
        assert "fresh" in [e["name"] for e in r.json()["entries"]]
        assert (tmp_path / "fresh").is_dir()

    def test_fs_mkdir_rejects_separators(self, client, tmp_path) -> None:
        c, _ = client
        r = c.post("/api/fs/mkdir", json={"path": str(tmp_path), "name": "a/b"})
        assert r.status_code == 400


class TestDeleteAnArchivedJob:
    """Deleting a job whose archive drive is not mounted must REFUSE, not lie.

    The route did `if job_dir.exists(): rmtree(...)` and then purged the index
    unconditionally, so an unreachable archive path meant the job vanished from the UI
    while its (often multi-GB) folder stayed on the unmounted disk with nothing pointing
    at it — and the response still said `{"ok": true}`.
    """

    @pytest.fixture
    def client(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from fastapi.testclient import TestClient

        from backend.api import routes_md
        from backend.api import state as design_state
        from backend.api.main import app
        from tests.conftest import make_minimal_design

        monkeypatch.setattr(routes_md, "_workspace", lambda: tmp_path)
        design_state.set_design(make_minimal_design())
        return TestClient(app), tmp_path

    def _job_archived_to(self, ws: Path, dest: Path):
        """A job whose RECORD says archived to `dest`, with the record itself still in the
        workspace so `_load_job` can find it — which is exactly the on-disk shape after a
        real archive (`resolve_job_json` reads the workspace copy)."""
        job = new_md_job(
            "A", "mgh_slow_release", "A", "pkg", design_source_path="a.nadoc"
        )
        job.save(ws)
        p = ws / "md_jobs" / job.job_id / "job.json"
        p.write_text(
            p.read_text()
            .replace('"archived": false', '"archived": true')
            .replace('"archive_path": null', f'"archive_path": "{dest}"')
        )
        return job

    def test_refuses_when_the_archive_drive_is_not_mounted(
        self, client, tmp_path
    ) -> None:
        c, ws = client
        missing = tmp_path / "not-mounted" / "deadbeef"
        job = self._job_archived_to(ws, missing)

        r = c.delete(f"/api/md/jobs/{job.job_id}")
        assert r.status_code == 409
        assert "not reachable" in r.json()["detail"]
        # and it is still listed — a refused delete must not half-happen
        assert any(e["job_id"] == job.job_id for e in c.get("/api/md/jobs").json())

    def test_deletes_normally_when_the_archive_is_reachable(
        self, client, tmp_path
    ) -> None:
        c, ws = client
        dest = tmp_path / "archive" / "job"
        dest.mkdir(parents=True)
        (dest / "traj.dcd").write_bytes(b"\0" * 16)
        job = self._job_archived_to(ws, dest)

        r = c.delete(f"/api/md/jobs/{job.job_id}")
        assert r.status_code == 200, r.text
        assert not dest.exists()


@pytest.mark.parametrize("kind", ["md_jobs", "oxdna_jobs"])
def test_disconnected_archive_stays_listed_and_recovers(tmp_path, kind):
    from backend.core.md_job import MdJob
    cls = MdJob if kind == "md_jobs" else OxdnaJob
    job = (new_md_job("demo", "mgh_slow_release", "A", "pkg")
           if kind == "md_jobs" else new_oxdna_job("demo", []))
    ws, drive = tmp_path / "ws", tmp_path / "drive"
    job.save(ws)
    (job.job_dir(ws) / "trajectory.dat").write_bytes(b"trajectory")
    ja.archive_job(job, ws, kind, drive)
    assert cls.load(job.job_id, ws).to_dict()["storage_available"] is True
    drive.rename(tmp_path / "unplugged")
    offline = cls.list_jobs(ws)
    assert len(offline) == 1
    assert offline[0].archive_path == str(drive / job.job_id)
    assert offline[0].to_dict()["storage_available"] is False
    with pytest.raises(FileNotFoundError, match="disconnected"):
        offline[0].save(ws)
    assert not drive.exists()
    # A server restart loads the same cached record, without an in-memory registry.
    assert cls.load(job.job_id, ws).design_name == "demo"
    (tmp_path / "unplugged").rename(drive)
    assert cls.load(job.job_id, ws).to_dict()["storage_available"] is True
    assert (job.job_dir(ws) / "trajectory.dat").read_bytes() == b"trajectory"
    ja.start_unarchive(cls.load(job.job_id, ws), ws, kind)
    assert _wait(kind, job.job_id)["state"] == "done"
    assert not (ws / kind / ".archive_metadata" / f"{job.job_id}.json").exists()


def test_legacy_archive_metadata_is_cached_when_connected(tmp_path):
    job = new_oxdna_job("legacy", [])
    ws, drive = tmp_path / "ws", tmp_path / "drive"
    job.save(ws)
    ja.archive_job(job, ws, "oxdna_jobs", drive)
    cached = ws / "oxdna_jobs" / ".archive_metadata" / f"{job.job_id}.json"
    cached.unlink()
    OxdnaJob.list_jobs(ws)
    assert cached.exists()
    drive.rename(tmp_path / "unplugged")
    assert OxdnaJob.list_jobs(ws)[0].to_dict()["storage_available"] is False


@pytest.mark.parametrize("engine,kind", [("md", "md_jobs"), ("oxdna", "oxdna_jobs")])
def test_api_lists_disconnected_jobs_and_refuses_deletion(tmp_path, monkeypatch, engine, kind):
    from fastapi.testclient import TestClient
    from backend.api import routes_md, routes_oxdna, state
    from backend.api.main import app
    from tests.conftest import make_minimal_design
    ws, drive = tmp_path / "ws", tmp_path / "drive"
    routes = routes_md if engine == "md" else routes_oxdna
    monkeypatch.setattr(routes, "_workspace", lambda: ws)
    state.set_design(make_minimal_design())
    job = (new_md_job("demo", "mgh_slow_release", "A", "pkg")
           if engine == "md" else new_oxdna_job("demo", []))
    job.save(ws)
    ja.archive_job(job, ws, kind, drive)
    drive.rename(tmp_path / "unplugged")
    client = TestClient(app)
    result = client.get(f"/api/{engine}/jobs")
    assert result.status_code == 200, result.text
    row = next(j for j in result.json() if j["job_id"] == job.job_id)
    assert row["storage_available"] is False
    assert row["archive_path"] == str(drive / job.job_id)
    assert client.delete(f"/api/{engine}/jobs/{job.job_id}").status_code == 409
    assert job.job_id in ja.archived_job_ids(ws, kind)


def test_large_file_progress_advances_before_file_finishes(tmp_path):
    src, dst = tmp_path / 'source', tmp_path / 'dest'
    src.mkdir()
    payload = b'progress-test' * (2 * 1024 * 1024)
    original = src / 'trajectory.dcd'
    original.write_bytes(payload)
    original.chmod(0o640)
    updates = []

    class Progress(dict):
        def __setitem__(self, key, value):
            super().__setitem__(key, value)
            if key == 'moved_bytes':
                updates.append(value)

    progress = Progress(moved_bytes=0, total_bytes=0)
    ja._copy_tree_with_progress(src, dst, progress)
    assert any(0 < value < len(payload) for value in updates)
    assert updates == sorted(updates)
    assert progress['moved_bytes'] == progress['total_bytes'] == len(payload)
    assert (dst / original.name).read_bytes() == payload
    assert (dst / original.name).stat().st_mtime_ns == original.stat().st_mtime_ns
    assert (dst / original.name).stat().st_mode == original.stat().st_mode


def test_copy_failure_preserves_source_and_does_not_archive(tmp_path, monkeypatch):
    ws = tmp_path / 'ws'
    job = new_oxdna_job('copy failure', [])
    job.save(ws)
    source = job.job_dir(ws)
    (source / 'trajectory.dcd').write_bytes(b'original trajectory')

    def fail(*args, **kwargs):
        raise OSError('simulated drive disconnect')

    monkeypatch.setattr(ja.shutil, 'copystat', fail)
    with pytest.raises(RuntimeError, match='simulated drive disconnect'):
        ja.archive_job(job, ws, 'oxdna_jobs', tmp_path / 'drive')
    assert (source / 'trajectory.dcd').read_bytes() == b'original trajectory'
    assert not (tmp_path / 'drive' / job.job_id).exists()
    assert job.job_id not in ja.archived_job_ids(ws, 'oxdna_jobs')


def test_task_is_visible_before_worker_is_scheduled(tmp_path, monkeypatch):
    from types import SimpleNamespace
    job = new_oxdna_job('pending worker', [])
    job.save(tmp_path)
    monkeypatch.setattr(ja.threading, 'Thread', lambda **kwargs: SimpleNamespace(start=lambda: None))
    ja.start_archive(job, tmp_path, 'oxdna_jobs', tmp_path / 'drive')
    try:
        assert ja.task_status('oxdna_jobs', job.job_id)['state'] == 'running'
        with pytest.raises(ValueError, match='already in progress'):
            ja.start_archive(job, tmp_path, 'oxdna_jobs', tmp_path / 'other')
    finally:
        ja._TASKS.pop(ja._task_key('oxdna_jobs', job.job_id), None)
