"""Authenticated peer sync and local edit-lease routes for NADOC projects."""

from __future__ import annotations

from dataclasses import asdict
import hmac
import os
from pathlib import Path
import socket
from typing import Optional

import httpx
from fastapi import APIRouter, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from backend.api import assembly
from backend.core.project_collaboration import ProjectLeaseStore
from backend.core.collaboration_peers import PeerRegistry, PeerSyncClient
from backend.core.project_artifacts import ProjectArtifactCatalog
from backend.core.project_revisions import (
    BranchConflict,
    ProjectRevisionStore,
    RevisionCompatibilityError,
    SCHEMA_VERSION,
)


router = APIRouter(prefix="/collaboration", tags=["collaboration"])
MAX_SNAPSHOT_BYTES = 512 * 1024 * 1024


def _workspace() -> Path:
    return assembly._WORKSPACE_DIR


def _peer_token() -> str | None:
    return (os.environ.get("NADOC_PEER_TOKEN") or "").strip() or None


def _require_peer(authorization: Optional[str] = Header(default=None)) -> None:
    expected = _peer_token()
    if expected is None:
        raise HTTPException(503, "Peer synchronization is not enabled on this server.")
    supplied = authorization or ""
    if supplied.lower().startswith("bearer "):
        supplied = supplied[7:].strip()
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(401, "Invalid NADOC peer synchronization token.")


class RefAdvanceBody(BaseModel):
    loadout_id: str = Field(min_length=1, max_length=128)
    new_head: str = Field(min_length=64, max_length=64)
    expected_head: Optional[str] = Field(default=None, min_length=64, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    protected: bool = False
    require_fast_forward: bool = True


class LeaseBody(BaseModel):
    server_id: str = Field(min_length=1, max_length=128)
    client_id: str = Field(min_length=1, max_length=128)
    server_name: Optional[str] = Field(default=None, max_length=200)
    ttl_seconds: int = Field(default=90, ge=15, le=600)
    force: bool = False
    auto_fork: bool = False


class PeerBody(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=200)
    base_url: str = Field(min_length=1, max_length=500)
    token: str = Field(min_length=1, max_length=4096)


class ArtifactFetchBody(BaseModel):
    mode: str = Field(pattern="^(selected|full)$")
    paths: list[str] = Field(default_factory=list, max_length=10000)


class VersionBody(BaseModel):
    revision_id: str = Field(min_length=64, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    source_loadout_id: Optional[str] = Field(default=None, max_length=128)


class PromoteBody(BaseModel):
    source_loadout_id: str = Field(min_length=1, max_length=128)
    target_loadout_id: str = Field(min_length=1, max_length=128)
    expected_target_head: Optional[str] = Field(
        default=None, min_length=64, max_length=64
    )
    recovery_name: Optional[str] = Field(default=None, max_length=200)


@router.get("/identity")
def collaboration_identity() -> dict:
    """Non-secret capability document used by a workspace hub."""
    identity = PeerRegistry(_workspace()).server_identity()
    return {
        "format": "nadoc.collaboration-server",
        "schema_version": SCHEMA_VERSION,
        "server_id": identity["id"],
        "server_name": identity.get("name") or socket.gethostname(),
        "sync_enabled": _peer_token() is not None,
    }


@router.get("/projects")
def list_projects() -> dict:
    return {"projects": ProjectRevisionStore(_workspace()).project_ids()}


@router.get("/projects/{project_id}/overview")
def project_overview(project_id: str) -> dict:
    """Local UI view of a project; peer credentials never enter the browser."""
    try:
        manifest = ProjectRevisionStore(_workspace()).project_manifest(project_id)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(404, str(exc)) from exc
    manifest["jobs"] = ProjectArtifactCatalog(_workspace()).project_metadata(project_id)
    return manifest


@router.get("/projects/{project_id}/loadouts/{loadout_id}/history")
def loadout_history(project_id: str, loadout_id: str) -> dict:
    store = ProjectRevisionStore(_workspace())
    head = store.branch_head(project_id, loadout_id)
    if head is None:
        raise HTTPException(404, f"Unknown loadout: {loadout_id}")
    return {
        "project_id": project_id,
        "loadout_id": loadout_id,
        "head": head,
        "history": store.revision_history(project_id, head),
    }


@router.get("/projects/{project_id}/compare")
def compare_project_revisions(project_id: str, left: str, right: str) -> dict:
    try:
        return ProjectRevisionStore(_workspace()).compare_revisions(
            project_id, left, right
        )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/projects/{project_id}/versions", status_code=201)
def create_project_version(project_id: str, body: VersionBody) -> dict:
    try:
        return ProjectRevisionStore(_workspace()).create_version(
            project_id,
            body.revision_id,
            name=body.name,
            source_loadout_id=body.source_loadout_id,
        )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/projects/{project_id}/promote")
def promote_project_branch(project_id: str, body: PromoteBody) -> dict:
    try:
        return ProjectRevisionStore(_workspace()).promote_branch(
            project_id,
            body.source_loadout_id,
            body.target_loadout_id,
            expected_target_head=body.expected_target_head,
            recovery_name=body.recovery_name,
        )
    except BranchConflict as exc:
        raise HTTPException(
            409,
            {
                "kind": "branch_diverged",
                "loadout_id": exc.loadout_id,
                "expected_head": exc.expected,
                "current_head": exc.current,
            },
        ) from exc
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/peers")
def list_peers() -> dict:
    return {"peers": [peer.public() for peer in PeerRegistry(_workspace()).list()]}


@router.post("/peers", status_code=201)
def register_peer(body: PeerBody) -> dict:
    try:
        peer = PeerRegistry(_workspace()).register(
            peer_id=body.id,
            name=body.name,
            base_url=body.base_url,
            token=body.token,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return peer.public()


@router.delete("/peers/{peer_id}")
def remove_peer(peer_id: str) -> dict:
    return {"removed": PeerRegistry(_workspace()).remove(peer_id)}


@router.post("/peers/{peer_id}/projects/{project_id}/pull")
async def pull_from_peer(peer_id: str, project_id: str) -> dict:
    try:
        peer = PeerRegistry(_workspace()).get(peer_id)
        return await PeerSyncClient(_workspace(), peer).pull(project_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, f"Peer synchronization failed: {exc}") from exc


@router.post("/peers/{peer_id}/projects/{project_id}/push")
async def push_to_peer(peer_id: str, project_id: str) -> dict:
    try:
        peer = PeerRegistry(_workspace()).get(peer_id)
        return await PeerSyncClient(_workspace(), peer).push(project_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, f"Peer synchronization failed: {exc}") from exc


@router.post("/peers/{peer_id}/projects/{project_id}/sync")
async def synchronize_with_peer(peer_id: str, project_id: str) -> dict:
    try:
        peer = PeerRegistry(_workspace()).get(peer_id)
        return await PeerSyncClient(_workspace(), peer).synchronize(project_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, f"Peer synchronization failed: {exc}") from exc


@router.post(
    "/peers/{peer_id}/projects/{project_id}/artifacts/{engine}/{job_id}/fetch"
)
async def fetch_peer_artifacts(
    peer_id: str,
    project_id: str,
    engine: str,
    job_id: str,
    body: ArtifactFetchBody,
) -> dict:
    try:
        peer = PeerRegistry(_workspace()).get(peer_id)
        return await PeerSyncClient(_workspace(), peer).fetch_artifacts(
            project_id,
            engine,
            job_id,
            mode=body.mode,
            paths=body.paths,
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(409, str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        status = 409 if exc.response.status_code == 409 else 502
        raise HTTPException(status, f"Peer artifact fetch failed: {exc}") from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, f"Peer artifact fetch failed: {exc}") from exc


@router.get("/projects/{project_id}/manifest", dependencies=[])
def project_manifest(
    project_id: str, authorization: Optional[str] = Header(default=None)
) -> dict:
    _require_peer(authorization)
    manifest = ProjectRevisionStore(_workspace()).project_manifest(project_id)
    manifest["jobs"] = ProjectArtifactCatalog(_workspace()).project_metadata(project_id)
    return manifest


@router.get("/projects/{project_id}/jobs")
def project_jobs(
    project_id: str, authorization: Optional[str] = Header(default=None)
) -> dict:
    _require_peer(authorization)
    return {"jobs": ProjectArtifactCatalog(_workspace()).project_metadata(project_id)}


@router.put("/projects/{project_id}/jobs/{engine}/{job_id}", status_code=201)
def put_project_job(
    project_id: str,
    engine: str,
    job_id: str,
    metadata: dict,
    authorization: Optional[str] = Header(default=None),
) -> dict:
    _require_peer(authorization)
    if (
        metadata.get("project_id") != project_id
        or metadata.get("engine") != engine
        or metadata.get("job_id") != job_id
    ):
        raise HTTPException(400, "Job URL and metadata identities differ.")
    try:
        return ProjectArtifactCatalog(_workspace()).merge(metadata)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/projects/{project_id}/artifacts/{engine}/{job_id}/files")
def list_artifact_files(
    project_id: str,
    engine: str,
    job_id: str,
    copy: bool = False,
    authorization: Optional[str] = Header(default=None),
) -> dict:
    _require_peer(authorization)
    try:
        catalog = ProjectArtifactCatalog(_workspace())
        if copy:
            catalog.assert_fetchable(project_id, engine, job_id)
        return {
            "files": catalog.list_files(project_id, engine, job_id)
        }
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/projects/{project_id}/artifacts/{engine}/{job_id}/file/{path:path}")
def stream_artifact_file(
    project_id: str,
    engine: str,
    job_id: str,
    path: str,
    authorization: Optional[str] = Header(default=None),
) -> FileResponse:
    _require_peer(authorization)
    try:
        artifact = ProjectArtifactCatalog(_workspace()).artifact_file(
            project_id, engine, job_id, path
        )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(404, str(exc)) from exc
    return FileResponse(artifact, filename=artifact.name)


@router.get("/projects/{project_id}/revisions/{revision_id}")
def get_revision(
    project_id: str,
    revision_id: str,
    authorization: Optional[str] = Header(default=None),
) -> dict:
    _require_peer(authorization)
    try:
        return ProjectRevisionStore(_workspace()).export_revision(project_id, revision_id)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(404, str(exc)) from exc


@router.put("/projects/{project_id}/revisions/{revision_id}", status_code=201)
def put_revision(
    project_id: str,
    revision_id: str,
    record: dict,
    authorization: Optional[str] = Header(default=None),
) -> dict:
    _require_peer(authorization)
    if record.get("project_id") != project_id or record.get("revision_id") != revision_id:
        raise HTTPException(400, "Revision URL and payload identities differ.")
    try:
        return asdict(ProjectRevisionStore(_workspace()).ingest_revision(record))
    except RevisionCompatibilityError as exc:
        raise HTTPException(422, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/projects/{project_id}/snapshots/{snapshot_sha256}")
def get_snapshot(
    project_id: str,
    snapshot_sha256: str,
    authorization: Optional[str] = Header(default=None),
) -> Response:
    _require_peer(authorization)
    try:
        content = ProjectRevisionStore(_workspace()).snapshot_path(
            project_id, snapshot_sha256
        ).read_bytes()
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(404, str(exc)) from exc
    return Response(content, media_type="application/gzip")


@router.put("/projects/{project_id}/snapshots/{snapshot_sha256}", status_code=201)
async def put_snapshot(
    project_id: str,
    snapshot_sha256: str,
    request: Request,
    authorization: Optional[str] = Header(default=None),
) -> dict:
    _require_peer(authorization)
    length = int(request.headers.get("content-length", "0") or 0)
    if length > MAX_SNAPSHOT_BYTES:
        raise HTTPException(413, "Project snapshot exceeds the transfer limit.")
    content = await request.body()
    if len(content) > MAX_SNAPSHOT_BYTES:
        raise HTTPException(413, "Project snapshot exceeds the transfer limit.")
    try:
        ProjectRevisionStore(_workspace()).ingest_snapshot(
            project_id, snapshot_sha256, content
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"project_id": project_id, "snapshot_sha256": snapshot_sha256}


@router.post("/projects/{project_id}/refs")
def advance_ref(
    project_id: str,
    body: RefAdvanceBody,
    authorization: Optional[str] = Header(default=None),
) -> dict:
    _require_peer(authorization)
    try:
        store = ProjectRevisionStore(_workspace())
        store.advance_branch(
            project_id,
            body.loadout_id,
            body.new_head,
            expected_head=body.expected_head,
            name=body.name,
            protected=body.protected,
            require_fast_forward=body.require_fast_forward,
        )
    except BranchConflict as exc:
        raise HTTPException(
            409,
            {
                "kind": "branch_diverged",
                "loadout_id": exc.loadout_id,
                "expected_head": exc.expected,
                "current_head": exc.current,
            },
        ) from exc
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"project_id": project_id, "loadout_id": body.loadout_id, "head": body.new_head}


@router.post("/projects/{project_id}/loadouts/{loadout_id}/lease")
def acquire_lease(project_id: str, loadout_id: str, body: LeaseBody) -> dict:
    try:
        return asdict(
            ProjectLeaseStore(_workspace()).acquire(
                project_id,
                loadout_id,
                server_id=body.server_id,
                client_id=body.client_id,
                server_name=body.server_name,
                ttl_seconds=body.ttl_seconds,
                force=body.force,
                auto_fork=body.auto_fork,
            )
        )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.delete("/projects/{project_id}/loadouts/{loadout_id}/lease")
def release_lease(
    project_id: str,
    loadout_id: str,
    server_id: str,
    client_id: str,
    force: bool = False,
) -> dict:
    released = ProjectLeaseStore(_workspace()).release(
        project_id,
        loadout_id,
        server_id=server_id,
        client_id=client_id,
        force=force,
    )
    return {"released": released}
