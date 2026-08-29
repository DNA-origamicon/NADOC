from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from backend.core.collaboration_peers import (
    Peer,
    PeerRegistry,
    PeerSyncClient,
    validate_peer_url,
)
from backend.core.models import Design, DesignMetadata
from backend.core.oxdna_job import OxdnaStatus, new_oxdna_job
from backend.core.project_artifacts import ProjectArtifactCatalog
from backend.core.project_revisions import ProjectRevisionStore


def test_peer_url_policy_allows_tailnet_and_rejects_plain_lan_or_public_http():
    assert validate_peer_url("http://100.100.1.2:5173") == "http://100.100.1.2:5173"
    assert validate_peer_url("https://machine.example.ts.net")
    assert validate_peer_url("http://simulation-pc:5173")
    with pytest.raises(ValueError, match="Tailscale"):
        validate_peer_url("http://192.168.1.20:5173")
    with pytest.raises(ValueError, match="Tailscale"):
        validate_peer_url("http://example.com")


def test_peer_registry_persists_identity_and_hides_token_from_public_shape(tmp_path):
    registry = PeerRegistry(tmp_path)
    identity = registry.server_identity()
    assert registry.server_identity() == identity
    peer = registry.register(
        peer_id="server-b",
        name="Simulation PC",
        base_url="https://simulation.example.ts.net/",
        token="secret",
    )
    assert registry.get("server-b") == peer
    assert peer.public() == {
        "id": "server-b",
        "name": "Simulation PC",
        "base_url": "https://simulation.example.ts.net",
    }
    assert "token" not in peer.public()
    assert registry.remove("server-b") is True
    assert registry.remove("server-b") is False


def _commit(store, design, parent, name):
    return store.commit(
        design.model_copy(
            update={"metadata": design.metadata.model_copy(update={"name": name})}
        ),
        loadout_id="main",
        loadout_name="Main",
        parent_revision_id=parent,
        expected_head=parent,
    )


def _remote_transport(store: ProjectRevisionStore, project_id: str):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer secret"
        path = request.url.path
        if path.endswith("/manifest"):
            return httpx.Response(200, json=store.project_manifest(project_id))
        if "/snapshots/" in path:
            checksum = path.rsplit("/", 1)[-1]
            return httpx.Response(200, content=store.snapshot_path(project_id, checksum).read_bytes())
        if "/revisions/" in path:
            revision = path.rsplit("/", 1)[-1]
            return httpx.Response(200, json=store.export_revision(project_id, revision))
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def _writable_remote_transport(store: ProjectRevisionStore, project_id: str):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer secret"
        path = request.url.path
        if request.method == "GET" and path.endswith("/manifest"):
            return httpx.Response(200, json=store.project_manifest(project_id))
        if "/snapshots/" in path:
            checksum = path.rsplit("/", 1)[-1]
            if request.method == "GET":
                return httpx.Response(
                    200, content=store.snapshot_path(project_id, checksum).read_bytes()
                )
            store.ingest_snapshot(project_id, checksum, request.content)
            return httpx.Response(201, json={"snapshot_sha256": checksum})
        if "/revisions/" in path:
            revision = path.rsplit("/", 1)[-1]
            if request.method == "GET":
                return httpx.Response(
                    200, json=store.export_revision(project_id, revision)
                )
            store.ingest_revision(json.loads(request.content))
            return httpx.Response(201, json={"revision_id": revision})
        if request.method == "POST" and path.endswith("/refs"):
            body = json.loads(request.content)
            store.advance_branch(
                project_id,
                body["loadout_id"],
                body["new_head"],
                expected_head=body.get("expected_head"),
                name=body["name"],
                protected=body.get("protected", False),
                require_fast_forward=body.get("require_fast_forward", True),
            )
            return httpx.Response(200, json={"head": body["new_head"]})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def test_pull_fast_forwards_and_transfers_only_missing_revision_objects(tmp_path):
    design = Design(id="project-1", metadata=DesignMetadata(name="Root"))
    remote = ProjectRevisionStore(tmp_path / "remote")
    root = remote.commit(
        design,
        loadout_id="main",
        loadout_name="Main",
        parent_revision_id=None,
        expected_head=None,
    )
    tip = _commit(remote, design, root.revision_id, "Remote")
    local = ProjectRevisionStore(tmp_path / "local")
    local.ingest_snapshot(
        design.id,
        root.snapshot_sha256,
        remote.snapshot_path(design.id, root.snapshot_sha256).read_bytes(),
    )
    local.ingest_revision(remote.export_revision(design.id, root.revision_id))
    local.advance_branch(
        design.id, "main", root.revision_id, expected_head=None, name="Main"
    )
    http = httpx.AsyncClient(
        base_url="https://peer.example.ts.net",
        transport=_remote_transport(remote, design.id),
    )
    result = asyncio.run(
        PeerSyncClient(
            tmp_path / "local",
            Peer("remote", "Remote", "https://peer.example.ts.net", "secret"),
            client=http,
        ).pull(design.id)
    )
    asyncio.run(http.aclose())
    assert result["outcomes"]["main"] == "fast_forwarded"
    assert local.branch_head(design.id, "main") == tip.revision_id


def test_pull_preserves_divergence_as_named_remote_branch(tmp_path):
    design = Design(id="project-1", metadata=DesignMetadata(name="Root"))
    remote = ProjectRevisionStore(tmp_path / "remote")
    root = remote.commit(
        design,
        loadout_id="main",
        loadout_name="Main",
        parent_revision_id=None,
        expected_head=None,
    )
    local = ProjectRevisionStore(tmp_path / "local")
    local.ingest_snapshot(
        design.id,
        root.snapshot_sha256,
        remote.snapshot_path(design.id, root.snapshot_sha256).read_bytes(),
    )
    local.ingest_revision(remote.export_revision(design.id, root.revision_id))
    local.advance_branch(
        design.id, "main", root.revision_id, expected_head=None, name="Main"
    )
    local_tip = _commit(local, design, root.revision_id, "Local")
    remote_tip = _commit(remote, design, root.revision_id, "Remote")
    http = httpx.AsyncClient(
        base_url="https://peer.example.ts.net",
        transport=_remote_transport(remote, design.id),
    )
    result = asyncio.run(
        PeerSyncClient(
            tmp_path / "local",
            Peer("remote-server", "Remote PC", "https://peer.example.ts.net", "secret"),
            client=http,
        ).pull(design.id)
    )
    asyncio.run(http.aclose())

    assert result["outcomes"]["main"] == "diverged_preserved"
    assert local.branch_head(design.id, "main") == local_tip.revision_id
    alias = local.project_manifest(design.id)["refs"]["main-from-remote-s"]
    assert alias["head_revision_id"] == remote_tip.revision_id
    assert alias["name"].startswith("Main — Remote PC — ")


def test_push_transfers_missing_objects_and_fast_forwards_remote(tmp_path):
    design = Design(id="project-1", metadata=DesignMetadata(name="Root"))
    local = ProjectRevisionStore(tmp_path / "local")
    tip = local.commit(
        design,
        loadout_id="main",
        loadout_name="Main",
        parent_revision_id=None,
        expected_head=None,
    )
    remote = ProjectRevisionStore(tmp_path / "remote")
    http = httpx.AsyncClient(
        base_url="https://peer.example.ts.net",
        transport=_writable_remote_transport(remote, design.id),
    )
    result = asyncio.run(
        PeerSyncClient(
            tmp_path / "local",
            Peer("remote", "Remote", "https://peer.example.ts.net", "secret"),
            client=http,
        ).push(design.id)
    )
    asyncio.run(http.aclose())
    assert result["outcomes"]["main"] == "fast_forwarded"
    assert remote.branch_head(design.id, "main") == tip.revision_id
    assert remote.load_design(design.id, tip.revision_id).id == design.id


def test_bidirectional_sync_preserves_both_divergent_heads_on_both_peers(tmp_path):
    design = Design(id="project-1", metadata=DesignMetadata(name="Root"))
    remote = ProjectRevisionStore(tmp_path / "remote")
    root = remote.commit(
        design,
        loadout_id="main",
        loadout_name="Main",
        parent_revision_id=None,
        expected_head=None,
    )
    local = ProjectRevisionStore(tmp_path / "local")
    local.ingest_snapshot(
        design.id,
        root.snapshot_sha256,
        remote.snapshot_path(design.id, root.snapshot_sha256).read_bytes(),
    )
    local.ingest_revision(remote.export_revision(design.id, root.revision_id))
    local.advance_branch(
        design.id, "main", root.revision_id, expected_head=None, name="Main"
    )
    local_tip = _commit(local, design, root.revision_id, "Local")
    remote_tip = _commit(remote, design, root.revision_id, "Remote")
    http = httpx.AsyncClient(
        base_url="https://peer.example.ts.net",
        transport=_writable_remote_transport(remote, design.id),
    )
    result = asyncio.run(
        PeerSyncClient(
            tmp_path / "local",
            Peer("remote-server", "Remote PC", "https://peer.example.ts.net", "secret"),
            client=http,
        ).synchronize(design.id)
    )
    asyncio.run(http.aclose())

    assert result["pull"]["outcomes"]["main"] == "diverged_preserved"
    assert result["push"]["outcomes"]["main"] == "diverged_preserved"
    assert local.branch_head(design.id, "main") == local_tip.revision_id
    assert remote.branch_head(design.id, "main") == remote_tip.revision_id
    remote_refs = remote.project_manifest(design.id)["refs"]
    local_aliases = [
        ref for key, ref in remote_refs.items() if key.startswith("main-from-")
    ]
    assert any(ref["head_revision_id"] == local_tip.revision_id for ref in local_aliases)


def _artifact_transport(workspace, project_id, job_id, *, active=False):
    catalog = ProjectArtifactCatalog(workspace)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/files"):
            if active:
                return httpx.Response(409, json={"detail": "active job"})
            return httpx.Response(
                200, json={"files": catalog.list_files(project_id, "oxdna", job_id)}
            )
        marker = "/file/"
        if marker in request.url.path:
            relative = request.url.path.split(marker, 1)[1]
            path = catalog.artifact_file(project_id, "oxdna", job_id, relative)
            return httpx.Response(200, content=path.read_bytes())
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def test_selected_artifact_fetch_uses_isolated_cache_and_full_fetch_is_atomic(tmp_path):
    remote_ws = tmp_path / "remote"
    local_ws = tmp_path / "local"
    job = new_oxdna_job(
        "Part", [], project_id="project-1", design_revision_id="a" * 64
    )
    job.status = OxdnaStatus.completed
    job.save(remote_ws)
    (job.job_dir(remote_ws) / "design.json").write_text("{}")
    (job.job_dir(remote_ws) / "trajectory.dat").write_bytes(b"trajectory")
    peer = Peer("remote", "Remote", "https://peer.example.ts.net", "secret")
    http = httpx.AsyncClient(
        base_url=peer.base_url,
        transport=_artifact_transport(remote_ws, "project-1", job.job_id),
    )
    sync = PeerSyncClient(local_ws, peer, client=http)
    selected = asyncio.run(
        sync.fetch_artifacts(
            "project-1",
            "oxdna",
            job.job_id,
            mode="selected",
            paths=["trajectory.dat"],
        )
    )
    assert selected["files"] == ["trajectory.dat"]
    assert not (local_ws / "oxdna_jobs" / job.job_id).exists()
    assert (local_ws / selected["destination"] / "trajectory.dat").read_bytes() == b"trajectory"

    full = asyncio.run(
        sync.fetch_artifacts("project-1", "oxdna", job.job_id, mode="full")
    )
    asyncio.run(http.aclose())
    assert full["mode"] == "full"
    installed = local_ws / "oxdna_jobs" / job.job_id
    assert (installed / "job.json").is_file()
    assert (installed / "trajectory.dat").read_bytes() == b"trajectory"


def test_full_artifact_fetch_reports_alpine_grade_progress_and_verifies_sizes(tmp_path):
    remote_ws = tmp_path / "remote"
    local_ws = tmp_path / "local"
    job = new_oxdna_job(
        "Part", [], project_id="project-1", design_revision_id="a" * 64
    )
    job.status = OxdnaStatus.completed
    job.save(remote_ws)
    (job.job_dir(remote_ws) / "trajectory.dat").write_bytes(b"trajectory-data")
    peer = Peer("remote", "Remote", "https://peer.example.ts.net", "secret")
    http = httpx.AsyncClient(
        base_url=peer.base_url,
        transport=_artifact_transport(remote_ws, "project-1", job.job_id),
    )
    updates = []
    result = asyncio.run(
        PeerSyncClient(local_ws, peer, client=http).fetch_artifacts(
            "project-1", "oxdna", job.job_id, mode="full", progress=updates.append
        )
    )
    asyncio.run(http.aclose())

    phases = [update["phase"] for update in updates]
    assert phases[0] == "downloading"
    assert phases[-3:] == ["verifying", "installing", "done"]
    assert updates[-1]["transferred_bytes"] == updates[-1]["total_bytes"]
    assert updates[-1]["verified_bytes"] == updates[-1]["total_bytes"]
    assert updates[-1]["files_completed"] == updates[-1]["file_count"]
    assert updates[-1]["bytes_per_second"] > 0
    assert result["destination"] == f"oxdna_jobs/{job.job_id}"


def test_active_remote_job_refuses_selected_and_full_copy(tmp_path):
    remote_ws = tmp_path / "remote"
    job = new_oxdna_job(
        "Part", [], project_id="project-1", design_revision_id="a" * 64
    )
    job.status = OxdnaStatus.running
    job.save(remote_ws)
    peer = Peer("remote", "Remote", "https://peer.example.ts.net", "secret")
    http = httpx.AsyncClient(
        base_url=peer.base_url,
        transport=_artifact_transport(
            remote_ws, "project-1", job.job_id, active=True
        ),
    )
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(
            PeerSyncClient(tmp_path / "local", peer, client=http).fetch_artifacts(
                "project-1",
                "oxdna",
                job.job_id,
                mode="selected",
                paths=["job.json"],
            )
        )
    asyncio.run(http.aclose())
