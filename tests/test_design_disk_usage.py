"""Tests for backend.core.design_disk_usage and the GET /design/about endpoint —
the on-disk size accounting behind the welcome-screen "Data on disk" column and
the Help ▸ About-this-file panel."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.core.design_disk_usage import (
    assemblies_referencing,
    dir_size_bytes,
    dir_size_bytes_cached_only,
    jobs_for_source_path,
    sim_bytes_by_source_path,
    warm_dir_sizes,
)
from backend.core.md_job import new_job as new_md_job
from backend.core.oxdna_job import new_oxdna_job


def _write_job_payload(job, ws: Path, nbytes: int) -> None:
    """Save a job, then drop a fixed-size blob in its folder so size is known."""
    job.save(ws)
    (job.job_dir(ws) / "blob.bin").write_bytes(b"\0" * nbytes)


class TestDirSize:
    def test_empty_and_missing(self, tmp_path: Path) -> None:
        assert dir_size_bytes(tmp_path / "nope") == 0
        assert dir_size_bytes(tmp_path) == 0

    def test_sums_nested_files(self, tmp_path: Path) -> None:
        (tmp_path / "a.bin").write_bytes(b"x" * 100)
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "b.bin").write_bytes(b"y" * 50)
        assert dir_size_bytes(tmp_path) == 150


class TestSimBytesBySourcePath:
    def test_groups_md_and_oxdna(self, tmp_path: Path) -> None:
        a_md = new_md_job(
            "A", "mgh_slow_release", "A", "pkg", design_source_path="a.nadoc"
        )
        a_ox = new_oxdna_job("A", [], design_source_path="a.nadoc")
        b_md = new_md_job(
            "B", "mgh_slow_release", "B", "pkg", design_source_path="b.nadoc"
        )
        _write_job_payload(a_md, tmp_path, 1000)
        _write_job_payload(a_ox, tmp_path, 2000)
        _write_job_payload(b_md, tmp_path, 500)

        agg = sim_bytes_by_source_path(tmp_path)
        # a.nadoc = MD blob + oxDNA blob (+ tiny job.json/design.json on each)
        assert agg["a.nadoc"] >= 3000
        assert agg["b.nadoc"] >= 500
        assert agg["a.nadoc"] > agg["b.nadoc"]

    def test_ignores_jobs_without_source_path(self, tmp_path: Path) -> None:
        j = new_md_job("A", "mgh_slow_release", "A", "pkg", design_source_path=None)
        _write_job_payload(j, tmp_path, 1000)
        assert sim_bytes_by_source_path(tmp_path) == {}

    def test_empty_workspace(self, tmp_path: Path) -> None:
        assert sim_bytes_by_source_path(tmp_path) == {}


class TestJobsForSourcePath:
    def test_filters_to_target(self, tmp_path: Path) -> None:
        a = new_md_job(
            "A", "mgh_slow_release", "A", "pkg", design_source_path="a.nadoc"
        )
        b = new_oxdna_job("B", [], design_source_path="b.nadoc")
        _write_job_payload(a, tmp_path, 100)
        _write_job_payload(b, tmp_path, 100)
        recs = jobs_for_source_path(tmp_path, "a.nadoc")
        assert [r["job_id"] for r in recs] == [a.job_id]
        assert recs[0]["kind"] == "md"
        assert recs[0]["size_bytes"] >= 100


class TestAssembliesReferencing:
    def _nass(self, ws: Path, name: str, part_paths: list[str]) -> None:
        instances = [
            {"id": f"i{i}", "name": "p", "source": {"type": "file", "path": p}}
            for i, p in enumerate(part_paths)
        ]
        (ws / f"{name}.nass").write_text(json.dumps({"instances": instances}))

    def test_finds_referencing_assembly(self, tmp_path: Path) -> None:
        self._nass(tmp_path, "asmA", ["beam.nadoc", "other.nadoc"])
        self._nass(tmp_path, "asmB", ["unrelated.nadoc"])
        out = assemblies_referencing(tmp_path, "beam.nadoc")
        assert [a["path"] for a in out] == ["asmA.nass"]

    def test_inline_sources_ignored(self, tmp_path: Path) -> None:
        (tmp_path / "asm.nass").write_text(
            json.dumps(
                {
                    "instances": [
                        {"id": "i0", "source": {"type": "inline", "design": {}}}
                    ]
                }
            )
        )
        assert assemblies_referencing(tmp_path, "beam.nadoc") == []

    def test_no_match(self, tmp_path: Path) -> None:
        self._nass(tmp_path, "asm", ["x.nadoc"])
        assert assemblies_referencing(tmp_path, "beam.nadoc") == []


class TestRoutes:
    @pytest.fixture
    def client(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from fastapi.testclient import TestClient

        from backend.api import assembly
        from backend.api import state as design_state
        from backend.api.main import app
        from tests.conftest import make_minimal_design

        monkeypatch.setattr(assembly, "_WORKSPACE_DIR", tmp_path)
        design_state.set_design(make_minimal_design(n_helices=2))
        return TestClient(app), tmp_path

    def test_library_files_reports_disk_bytes(self, client) -> None:
        c, ws = client
        (ws / "a.nadoc").write_text('{"x": 1}')
        job = new_md_job(
            "A", "mgh_slow_release", "A", "pkg", design_source_path="a.nadoc"
        )
        job.save(ws)
        (job.job_dir(ws) / "blob.bin").write_bytes(b"\0" * 4096)

        r = c.get("/api/library/files")
        assert r.status_code == 200
        entry = next(e for e in r.json() if e["path"] == "a.nadoc")
        assert entry["sim_bytes"] >= 4096
        assert entry["disk_bytes"] == entry["size_bytes"] + entry["sim_bytes"]

    def test_about_aggregates(self, client) -> None:
        c, ws = client
        (ws / "a.nadoc").write_text('{"x": 1}')
        new_md_job(
            "A", "mgh_slow_release", "A", "pkg", design_source_path="a.nadoc"
        ).save(ws)
        new_oxdna_job("A", [], design_source_path="a.nadoc").save(ws)

        r = c.get("/api/design/about", params={"path": "a.nadoc"})
        assert r.status_code == 200
        d = r.json()
        assert d["path"] == "a.nadoc"
        assert d["total_bases"] > 0
        assert len(d["md_jobs"]) == 1
        assert len(d["oxdna_jobs"]) == 1
        assert d["total_disk_bytes"] == d["file_size_bytes"] + d["sim_total_bytes"]

    def test_about_unsaved_design(self, client) -> None:
        c, ws = client
        r = c.get("/api/design/about")
        assert r.status_code == 200
        d = r.json()
        assert d["path"] is None
        assert d["md_jobs"] == [] and d["oxdna_jobs"] == []
        assert d["total_bases"] > 0

    def test_about_no_active_design_loads_from_disk(self, client, monkeypatch) -> None:
        from fastapi import HTTPException

        from backend.api import state as design_state
        from tests.conftest import make_minimal_design

        c, ws = client
        (ws / "a.nadoc").write_text(make_minimal_design(n_helices=2).to_json())
        monkeypatch.setattr(
            design_state,
            "get_or_404",
            lambda: (_ for _ in ()).throw(HTTPException(404)),
        )

        r = c.get("/api/design/about", params={"path": "a.nadoc"})
        assert r.status_code == 200
        assert r.json()["total_bases"] > 0  # came from the file on disk

    def test_about_no_design_no_path_is_empty(self, client, monkeypatch) -> None:
        from fastapi import HTTPException

        from backend.api import state as design_state

        c, _ = client
        monkeypatch.setattr(
            design_state,
            "get_or_404",
            lambda: (_ for _ in ()).throw(HTTPException(404)),
        )
        r = c.get("/api/design/about")
        assert r.status_code == 200
        assert r.json()["empty"] is True


class TestAsyncSizeWarm:
    """Cache-only reads + background warming — so a polled job list never blocks on a
    multi-GB archived-run stat-walk (24hb-scale designs used to wedge the panel for
    tens of seconds on the first /md/jobs after a server start)."""

    def test_cached_only_is_none_until_warmed(self, tmp_path: Path) -> None:
        (tmp_path / "blob.bin").write_bytes(b"z" * 4096)
        # Cold: never walks the dir → None (the poll returns immediately).
        assert dir_size_bytes_cached_only(tmp_path) is None
        # The background warm (what list_md_jobs schedules) populates the cache.
        warm_dir_sizes([tmp_path])
        assert dir_size_bytes_cached_only(tmp_path) == 4096

    def test_warm_does_not_rewalk_a_fresh_entry(self, tmp_path: Path) -> None:
        (tmp_path / "a.bin").write_bytes(b"x" * 1000)
        warm_dir_sizes([tmp_path])
        assert dir_size_bytes_cached_only(tmp_path) == 1000
        # Within the TTL a second warm is a no-op even though the dir grew — proves the
        # dedup/skip (informational size; a short TTL refresh is enough).
        (tmp_path / "b.bin").write_bytes(b"y" * 2000)
        warm_dir_sizes([tmp_path])
        assert dir_size_bytes_cached_only(tmp_path) == 1000

    def test_warm_recomputes_a_stale_entry(self, tmp_path: Path) -> None:
        (tmp_path / "a.bin").write_bytes(b"x" * 1000)
        warm_dir_sizes([tmp_path], ttl=0.0)  # ttl 0 → always stale
        assert dir_size_bytes_cached_only(tmp_path, ttl=1e9) == 1000
        (tmp_path / "b.bin").write_bytes(b"y" * 500)
        warm_dir_sizes([tmp_path], ttl=0.0)  # recomputes
        assert dir_size_bytes_cached_only(tmp_path, ttl=1e9) == 1500

    def test_cached_only_expires_with_ttl(self, tmp_path: Path) -> None:
        (tmp_path / "a.bin").write_bytes(b"x" * 100)
        warm_dir_sizes([tmp_path])
        assert (
            dir_size_bytes_cached_only(tmp_path, ttl=1e9) == 100
        )  # fresh under a huge ttl
        assert (
            dir_size_bytes_cached_only(tmp_path, ttl=0.0) is None
        )  # stale under a zero ttl
