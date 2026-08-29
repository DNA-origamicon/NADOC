"""Authenticated peer sync and local edit-lease routes for NADOC projects."""

from __future__ import annotations

from dataclasses import asdict
import asyncio
import hmac
import ipaddress
import json
import os
from pathlib import Path
import secrets
import socket
import time
import uuid
from typing import Optional
from urllib.parse import urlsplit, urlunsplit

import httpx
from fastapi import APIRouter, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from backend.api import assembly
from backend.core.project_collaboration import ProjectLeaseStore
from backend.core.collaboration_peers import (
    PeerRegistry,
    PeerSyncClient,
    validate_peer_url,
)
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


def _public_url() -> str | None:
    return (os.environ.get("NADOC_PUBLIC_URL") or "").strip() or None


def _pairing_path() -> Path:
    return _workspace() / ".nadoc-projects" / "pairing.json"


def _safe_library_path(path: str) -> Path:
    candidate = (_workspace() / path).resolve()
    root = _workspace().resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise HTTPException(400, "Workspace path escapes the workspace.") from exc
    if candidate.suffix.lower() not in {".nadoc", ".nass"}:
        raise HTTPException(400, "Only NADOC part and assembly files are shared.")
    return candidate


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


class PairCompleteBody(BaseModel):
    code: str = Field(min_length=6, max_length=12)
    peer_id: str = Field(min_length=1, max_length=128)
    peer_name: str = Field(min_length=1, max_length=200)
    peer_base_url: str = Field(min_length=1, max_length=500)
    peer_token: str = Field(min_length=1, max_length=4096)


class PairPeerBody(BaseModel):
    base_url: str = Field(min_length=1, max_length=500)
    code: str = Field(min_length=6, max_length=12)


class ArtifactFetchBody(BaseModel):
    mode: str = Field(pattern="^(selected|full)$")
    paths: list[str] = Field(default_factory=list, max_length=10000)


_ARTIFACT_TRANSFER_TASKS: dict[str, asyncio.Task] = {}
_ARTIFACT_TRANSFER_CANCELLED: set[str] = set()


def _artifact_transfer_path(transfer_id: str) -> Path:
    if not transfer_id or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in transfer_id):
        raise ValueError("invalid transfer identity")
    return _workspace() / ".nadoc-projects" / "artifact-transfers" / f"{transfer_id}.json"


def _save_artifact_transfer(transfer_id: str, values: dict) -> dict:
    path = _artifact_transfer_path(transfer_id)
    current = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    current.update(values)
    current["transfer_id"] = transfer_id
    current["updated_at"] = time.time()
    from backend.core.project_revisions import _atomic_json
    _atomic_json(path, current)
    return current


def _load_artifact_transfer(transfer_id: str) -> dict:
    path = _artifact_transfer_path(transfer_id)
    if not path.is_file():
        raise FileNotFoundError(transfer_id)
    return json.loads(path.read_text(encoding="utf-8"))


async def _run_artifact_transfer(
    transfer_id: str, peer_id: str, project_id: str, engine: str, job_id: str
) -> None:
    try:
        peer = PeerRegistry(_workspace()).get(peer_id)

        async def progress(values: dict) -> None:
            _save_artifact_transfer(transfer_id, {"state": values["phase"], **values})

        result = await PeerSyncClient(_workspace(), peer).fetch_artifacts(
            project_id, engine, job_id, mode="full", progress=progress,
            cancelled=lambda: transfer_id in _ARTIFACT_TRANSFER_CANCELLED,
        )
        _save_artifact_transfer(
            transfer_id, {"state": "done", "phase": "done", "result": result,
                          "finished_at": time.time(), "eta_seconds": 0}
        )
    except InterruptedError:
        _save_artifact_transfer(
            transfer_id, {"state": "cancelled", "phase": "cancelled",
                          "finished_at": time.time(), "error": "Transfer cancelled"}
        )
    except Exception as exc:  # noqa: BLE001 — failure is persisted for UI polling
        _save_artifact_transfer(
            transfer_id, {"state": "failed", "phase": "failed",
                          "finished_at": time.time(), "error": str(exc)}
        )
    finally:
        _ARTIFACT_TRANSFER_TASKS.pop(transfer_id, None)
        _ARTIFACT_TRANSFER_CANCELLED.discard(transfer_id)


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
        "public_url": _public_url(),
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


@router.post("/pairing/start")
def start_pairing() -> dict:
    if _peer_token() is None or _public_url() is None:
        raise HTTPException(503, "Start NADOC with --tailscale before pairing.")
    code = f"{secrets.randbelow(1_000_000):06d}"
    path = _pairing_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"code": code, "expires_at": time.time() + 300}),
        encoding="utf-8",
    )
    return {"code": code, "expires_in_seconds": 300, "public_url": _public_url()}


@router.post("/pairing/complete")
def complete_pairing(body: PairCompleteBody) -> dict:
    path = _pairing_path()
    try:
        pending = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise HTTPException(410, "No active pairing request.") from exc
    if pending.get("expires_at", 0) < time.time():
        path.unlink(missing_ok=True)
        raise HTTPException(410, "Pairing code expired.")
    if not hmac.compare_digest(str(pending.get("code", "")), body.code):
        raise HTTPException(401, "Incorrect pairing code.")
    registry = PeerRegistry(_workspace())
    registry.register(
        peer_id=body.peer_id,
        name=body.peer_name,
        base_url=body.peer_base_url,
        token=body.peer_token,
    )
    path.unlink(missing_ok=True)
    identity = registry.server_identity()
    return {
        "server_id": identity["id"],
        "server_name": identity.get("name") or socket.gethostname(),
        "base_url": _public_url(),
        "token": _peer_token(),
    }


@router.post("/pairing/connect")
async def connect_peer(body: PairPeerBody) -> dict:
    token = _peer_token()
    public_url = _public_url()
    if token is None or public_url is None:
        raise HTTPException(503, "Start NADOC with --tailscale before pairing.")
    base_url = validate_peer_url(body.base_url)
    identity = PeerRegistry(_workspace()).server_identity()
    try:
        async with httpx.AsyncClient(base_url=base_url, timeout=20) as client:
            response = await client.post(
                "/api/collaboration/pairing/complete",
                json={
                    "code": body.code,
                    "peer_id": identity["id"],
                    "peer_name": identity.get("name") or socket.gethostname(),
                    "peer_base_url": public_url,
                    "peer_token": token,
                },
            )
            response.raise_for_status()
            remote = response.json()
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Could not pair with server: {exc}") from exc
    peer = PeerRegistry(_workspace()).register(
        peer_id=remote["server_id"],
        name=remote["server_name"],
        base_url=remote["base_url"],
        token=remote["token"],
    )
    return peer.public()


@router.get("/peers/status")
async def peer_statuses() -> dict:
    async def probe(peer):
        candidates = [peer.base_url]
        parsed = urlsplit(peer.base_url)
        try:
            address = ipaddress.ip_address(parsed.hostname or "")
            if address.version == 4 and address in ipaddress.ip_network("100.64.0.0/10"):
                import asyncio

                hostname = (
                    await asyncio.to_thread(socket.gethostbyaddr, str(address))
                )[0].rstrip(".")
                if hostname.endswith(".ts.net"):
                    port = f":{parsed.port}" if parsed.port else ""
                    candidates.append(
                        urlunsplit((parsed.scheme, f"{hostname}{port}", "", "", ""))
                    )
        except (ValueError, OSError):
            pass
        for candidate in candidates:
            try:
                async with httpx.AsyncClient(base_url=candidate, timeout=3) as client:
                    response = await client.get("/api/collaboration/identity")
                    response.raise_for_status()
                if candidate != peer.base_url:
                    peer = PeerRegistry(_workspace()).register(
                        peer_id=peer.id,
                        name=peer.name,
                        base_url=candidate,
                        token=peer.token,
                    )
                return {**peer.public(), "online": True}
            except httpx.HTTPError:
                continue
        return {**peer.public(), "online": False}

    peers = PeerRegistry(_workspace()).list()
    import asyncio

    return {"peers": await asyncio.gather(*(probe(peer) for peer in peers))}


@router.get("/library/files")
def shared_library_files(
    authorization: Optional[str] = Header(default=None),
) -> list:
    _require_peer(authorization)
    from backend.api.routes_assembly_workspace import _workspace_entries

    return _workspace_entries()


@router.get("/library/content")
def shared_library_content(
    path: str, authorization: Optional[str] = Header(default=None)
) -> FileResponse:
    _require_peer(authorization)
    source = _safe_library_path(path)
    if not source.is_file():
        raise HTTPException(404, "Remote workspace file does not exist.")
    return FileResponse(source, media_type="application/json", filename=source.name)


@router.get("/peers/{peer_id}/library/files")
async def peer_library_files(peer_id: str) -> list:
    try:
        peer = PeerRegistry(_workspace()).get(peer_id)
        async with httpx.AsyncClient(base_url=peer.base_url, timeout=20) as client:
            response = await client.get(
                "/api/collaboration/library/files",
                headers={"Authorization": f"Bearer {peer.token}"},
            )
            response.raise_for_status()
            return response.json()
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Remote workspace is unavailable: {exc}") from exc


@router.post("/peers/{peer_id}/library/checkout")
async def checkout_peer_file(peer_id: str, path: str) -> dict:
    import hashlib
    import tempfile

    from backend.core.models import Design
    from backend.core.project_revisions import refresh_active_revision

    try:
        peer = PeerRegistry(_workspace()).get(peer_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    destination = _safe_library_path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=".nadoc-checkout-", suffix=destination.suffix, dir=destination.parent
    )
    os.close(fd)
    temporary = Path(temporary_name)
    size = 0
    digest = hashlib.sha256()
    try:
        async with httpx.AsyncClient(base_url=peer.base_url, timeout=300) as client:
            async with client.stream(
                "GET",
                "/api/collaboration/library/content",
                params={"path": path},
                headers={"Authorization": f"Bearer {peer.token}"},
            ) as response:
                response.raise_for_status()
                with temporary.open("wb") as handle:
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > MAX_SNAPSHOT_BYTES:
                            raise ValueError("Remote file exceeds the checkout limit.")
                        digest.update(chunk)
                        handle.write(chunk)
        install = destination
        existing_digest = None
        if destination.exists():
            existing_hash = hashlib.sha256()
            with destination.open("rb") as existing_handle:
                for block in iter(lambda: existing_handle.read(1024 * 1024), b""):
                    existing_hash.update(block)
            existing_digest = existing_hash.hexdigest()
        if destination.exists() and existing_digest != digest.hexdigest():
            same_project = False
            if destination.suffix.lower() == ".nadoc":
                try:
                    current = Design.from_json(destination.read_text(encoding="utf-8"))
                    incoming = Design.from_json(temporary.read_text(encoding="utf-8"))
                    same_project = current.id == incoming.id
                    if same_project:
                        refresh_active_revision(_workspace(), current)
                        await PeerSyncClient(_workspace(), peer).pull(current.id)
                except (OSError, ValueError):
                    same_project = False
            if not same_project:
                safe_peer = "".join(
                    char if char.isalnum() or char in "-_ " else "_"
                    for char in peer.name
                ).strip() or "Remote"
                install = destination.with_name(
                    f"{destination.stem} ({safe_peer}){destination.suffix}"
                )
                counter = 2
                while install.exists():
                    install = destination.with_name(
                        f"{destination.stem} ({safe_peer} {counter}){destination.suffix}"
                    )
                    counter += 1
        os.replace(temporary, install)
        return {
            "path": install.relative_to(_workspace()).as_posix(),
            "name": install.stem,
            "type": "assembly" if install.suffix.lower() == ".nass" else "part",
            "source_peer": peer.public(),
            "size_bytes": size,
            "sha256": digest.hexdigest(),
            "synchronized": True,
        }
    except (httpx.HTTPError, OSError, ValueError) as exc:
        raise HTTPException(502, f"Remote checkout failed: {exc}") from exc
    finally:
        temporary.unlink(missing_ok=True)


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


@router.post(
    "/peers/{peer_id}/projects/{project_id}/artifacts/{engine}/{job_id}/transfer",
    status_code=202,
)
async def start_peer_artifact_transfer(
    peer_id: str, project_id: str, engine: str, job_id: str
) -> dict:
    """Start an observable, atomic full-job copy into the engine's local job store."""
    if engine not in {"oxdna", "md"}:
        raise HTTPException(400, "Only oxDNA and NAMD jobs can be transferred here.")
    try:
        peer = PeerRegistry(_workspace()).get(peer_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    destination = _workspace() / f"{engine}_jobs" / job_id
    if destination.exists():
        raise HTTPException(409, f"simulation job already exists: {engine}/{job_id}")
    for path in (_workspace() / ".nadoc-projects" / "artifact-transfers").glob("*.json"):
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if (existing.get("project_id"), existing.get("engine"), existing.get("job_id")) == (
            project_id, engine, job_id
        ) and existing.get("state") in {"queued", "downloading", "verifying", "installing"}:
            if existing.get("transfer_id") in _ARTIFACT_TRANSFER_TASKS:
                return existing
            _save_artifact_transfer(existing["transfer_id"], {
                "state": "interrupted", "phase": "interrupted",
                "error": "NADOC restarted before this transfer completed.",
                "finished_at": time.time(),
            })
    transfer_id = str(uuid.uuid4())
    status = _save_artifact_transfer(transfer_id, {
        "state": "queued", "phase": "queued", "peer_id": peer_id,
        "source_peer_name": peer.name,
        "project_id": project_id, "engine": engine, "job_id": job_id,
        "destination": f"{engine}_jobs/{job_id}", "created_at": time.time(),
        "transferred_bytes": 0, "verified_bytes": 0, "total_bytes": 0,
        "files_completed": 0, "file_count": 0,
    })
    _ARTIFACT_TRANSFER_TASKS[transfer_id] = asyncio.create_task(
        _run_artifact_transfer(transfer_id, peer_id, project_id, engine, job_id)
    )
    return status


@router.get("/artifact-transfers/{transfer_id}")
def artifact_transfer_status(transfer_id: str) -> dict:
    try:
        status = _load_artifact_transfer(transfer_id)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(404, "Unknown artifact transfer.") from exc
    if status.get("state") in {"queued", "downloading", "verifying", "installing", "cancelling"} \
            and transfer_id not in _ARTIFACT_TRANSFER_TASKS:
        status = _save_artifact_transfer(transfer_id, {
            "state": "interrupted", "phase": "interrupted",
            "error": "NADOC restarted before this transfer completed. Start it again to retry.",
            "finished_at": time.time(),
        })
    return status


@router.delete("/artifact-transfers/{transfer_id}")
def cancel_artifact_transfer(transfer_id: str) -> dict:
    try:
        status = _load_artifact_transfer(transfer_id)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(404, "Unknown artifact transfer.") from exc
    if status.get("state") not in {"done", "failed", "cancelled"}:
        _ARTIFACT_TRANSFER_CANCELLED.add(transfer_id)
        status = _save_artifact_transfer(transfer_id, {"state": "cancelling", "phase": "cancelling"})
    return status


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
