"""Persistent NADOC peer registry and project-aware synchronization client."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import ipaddress
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import shutil
import socket
from urllib.parse import urlparse
import uuid
import tempfile

import httpx

from backend.core.project_collaboration import ProjectLeaseStore
from backend.core.project_artifacts import ProjectArtifactCatalog
from backend.core.project_revisions import (
    ProjectRevisionStore,
    SCHEMA_VERSION,
    _atomic_json,
)


CONFIG_DIR = ".nadoc-collaboration"


@dataclass(frozen=True)
class Peer:
    id: str
    name: str
    base_url: str
    token: str

    def public(self) -> dict:
        return {"id": self.id, "name": self.name, "base_url": self.base_url}


def validate_peer_url(url: str) -> str:
    """Allow HTTPS or HTTP constrained to Tailscale/loopback destinations."""
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("peer URL must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("peer URL cannot contain credentials, query, or fragment")
    host = parsed.hostname.casefold()
    allowed_http = host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".ts.net")
    try:
        address = ipaddress.ip_address(host)
        allowed_http = allowed_http or address in ipaddress.ip_network("100.64.0.0/10")
    except ValueError:
        # Single-label MagicDNS hostnames are resolved only inside the tailnet.
        allowed_http = allowed_http or "." not in host
    if parsed.scheme == "http" and not allowed_http:
        raise ValueError("plain HTTP peers must be loopback or Tailscale addresses")
    return url.strip().rstrip("/")


class PeerRegistry:
    def __init__(self, workspace: Path):
        self.workspace = Path(workspace)
        self.root = self.workspace / CONFIG_DIR
        self.server_path = self.root / "server.json"
        self.peers_path = self.root / "peers.json"

    def server_identity(self) -> dict:
        if self.server_path.is_file():
            return json.loads(self.server_path.read_text(encoding="utf-8"))
        identity = {
            "id": str(uuid.uuid4()),
            "name": socket.gethostname(),
            "schema_version": SCHEMA_VERSION,
        }
        _atomic_json(self.server_path, identity)
        return identity

    def _all(self) -> dict[str, dict]:
        if not self.peers_path.is_file():
            return {}
        return json.loads(self.peers_path.read_text(encoding="utf-8"))

    def list(self) -> list[Peer]:
        return [Peer(**value) for _, value in sorted(self._all().items())]

    def get(self, peer_id: str) -> Peer:
        data = self._all().get(peer_id)
        if data is None:
            raise KeyError(f"unknown collaboration peer: {peer_id}")
        return Peer(**data)

    def register(self, *, peer_id: str, name: str, base_url: str, token: str) -> Peer:
        if not peer_id.strip() or not name.strip() or not token:
            raise ValueError("peer id, name, and token are required")
        peer = Peer(peer_id.strip(), name.strip(), validate_peer_url(base_url), token)
        peers = self._all()
        peers[peer.id] = asdict(peer)
        _atomic_json(self.peers_path, peers)
        os.chmod(self.peers_path, 0o600)
        return peer

    def remove(self, peer_id: str) -> bool:
        peers = self._all()
        if peers.pop(peer_id, None) is None:
            return False
        _atomic_json(self.peers_path, peers)
        return True


class PeerSyncClient:
    def __init__(
        self,
        workspace: Path,
        peer: Peer,
        *,
        client: httpx.AsyncClient | None = None,
    ):
        self.workspace = Path(workspace)
        self.peer = peer
        self._provided_client = client

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.peer.token}"}

    async def _client(self):
        if self._provided_client is not None:
            return self._provided_client, False
        return httpx.AsyncClient(
            base_url=self.peer.base_url,
            headers=self._headers(),
            timeout=120,
            follow_redirects=False,
        ), True

    async def pull(self, project_id: str) -> dict:
        local = ProjectRevisionStore(self.workspace)
        client, owned = await self._client()
        try:
            response = await client.get(
                f"/api/collaboration/projects/{project_id}/manifest",
                headers=self._headers(),
            )
            response.raise_for_status()
            remote = response.json()
            if remote.get("project_id") != project_id:
                raise ValueError("peer returned the wrong project identity")
            if remote.get("schema_version") != SCHEMA_VERSION:
                raise ValueError("peer project schema is not compatible")
            local_manifest = local.project_manifest(project_id)
            for checksum in sorted(set(remote["snapshots"]) - set(local_manifest["snapshots"])):
                blob = await client.get(
                    f"/api/collaboration/projects/{project_id}/snapshots/{checksum}",
                    headers=self._headers(),
                )
                blob.raise_for_status()
                local.ingest_snapshot(project_id, checksum, blob.content)
            for revision_id in sorted(set(remote["objects"]) - set(local_manifest["objects"])):
                obj = await client.get(
                    f"/api/collaboration/projects/{project_id}/revisions/{revision_id}",
                    headers=self._headers(),
                )
                obj.raise_for_status()
                local.ingest_revision(obj.json())
            artifacts = ProjectArtifactCatalog(self.workspace)
            for metadata in remote.get("jobs", []):
                artifacts.merge(metadata)

            outcomes = {}
            leases = ProjectLeaseStore(self.workspace)
            identity = PeerRegistry(self.workspace).server_identity()
            for loadout_id, remote_ref in remote["refs"].items():
                local_head = local.branch_head(project_id, loadout_id)
                remote_head = remote_ref["head_revision_id"]
                relation = local.relation(project_id, local_head, remote_head)
                if relation in {"equal", "ahead"}:
                    outcomes[loadout_id] = relation
                    continue
                if relation == "behind":
                    local.advance_branch(
                        project_id,
                        loadout_id,
                        remote_head,
                        expected_head=local_head,
                        name=remote_ref["name"],
                        protected=bool(remote_ref.get("protected")),
                        require_fast_forward=True,
                    )
                    outcomes[loadout_id] = "fast_forwarded"
                    continue
                alias = f"{loadout_id}-from-{self.peer.id[:8]}"
                alias_head = local.branch_head(project_id, alias)
                if alias_head != remote_head:
                    name = leases.unique_branch_name(
                        project_id, remote_ref["name"], self.peer.name
                    )
                    local.advance_branch(
                        project_id,
                        alias,
                        remote_head,
                        expected_head=alias_head,
                        name=name,
                        protected=bool(remote_ref.get("protected")),
                    )
                outcomes[loadout_id] = "diverged_preserved"
            return {
                "project_id": project_id,
                "peer": self.peer.public(),
                "server_id": identity["id"],
                "outcomes": outcomes,
            }
        finally:
            if owned:
                await client.aclose()

    async def push(self, project_id: str) -> dict:
        """Publish missing immutable data, then reconcile remote branch refs."""
        local = ProjectRevisionStore(self.workspace)
        local_manifest = local.project_manifest(project_id)
        local_jobs = ProjectArtifactCatalog(self.workspace).project_metadata(project_id)
        identity = PeerRegistry(self.workspace).server_identity()
        client, owned = await self._client()
        try:
            response = await client.get(
                f"/api/collaboration/projects/{project_id}/manifest",
                headers=self._headers(),
            )
            response.raise_for_status()
            remote = response.json()
            if remote.get("project_id") != project_id:
                raise ValueError("peer returned the wrong project identity")
            if remote.get("schema_version") != SCHEMA_VERSION:
                raise ValueError("peer project schema is not compatible")
            for checksum in sorted(
                set(local_manifest["snapshots"]) - set(remote["snapshots"])
            ):
                sent = await client.put(
                    f"/api/collaboration/projects/{project_id}/snapshots/{checksum}",
                    content=local.snapshot_path(project_id, checksum).read_bytes(),
                    headers={**self._headers(), "Content-Type": "application/gzip"},
                )
                sent.raise_for_status()
            for revision_id in sorted(
                set(local_manifest["objects"]) - set(remote["objects"])
            ):
                sent = await client.put(
                    f"/api/collaboration/projects/{project_id}/revisions/{revision_id}",
                    json=local.export_revision(project_id, revision_id),
                    headers=self._headers(),
                )
                sent.raise_for_status()
            remote_jobs = {
                (item["engine"], item["job_id"]): item
                for item in remote.get("jobs", [])
            }
            for metadata in local_jobs:
                existing = remote_jobs.get((metadata["engine"], metadata["job_id"]))
                if existing == metadata:
                    continue
                sent = await client.put(
                    f"/api/collaboration/projects/{project_id}/jobs/"
                    f"{metadata['engine']}/{metadata['job_id']}",
                    json=metadata,
                    headers=self._headers(),
                )
                sent.raise_for_status()

            outcomes = {}
            leases = ProjectLeaseStore(self.workspace)
            for loadout_id, local_ref in local_manifest["refs"].items():
                local_head = local_ref["head_revision_id"]
                remote_ref = remote["refs"].get(loadout_id)
                remote_head = remote_ref["head_revision_id"] if remote_ref else None
                if remote_head and not local.object_path(project_id, remote_head).is_file():
                    outcomes[loadout_id] = "remote_history_not_fetched"
                    continue
                relation = local.relation(project_id, local_head, remote_head)
                if relation in {"equal", "behind"}:
                    outcomes[loadout_id] = relation
                    continue
                target_id = loadout_id
                target_name = local_ref["name"]
                expected = remote_head
                if relation == "diverged":
                    target_id = f"{loadout_id}-from-{identity['id'][:8]}"
                    existing_alias = remote["refs"].get(target_id)
                    expected = (
                        existing_alias["head_revision_id"] if existing_alias else None
                    )
                    target_name = leases.unique_branch_name(
                        project_id, local_ref["name"], identity["name"]
                    )
                advanced = await client.post(
                    f"/api/collaboration/projects/{project_id}/refs",
                    json={
                        "loadout_id": target_id,
                        "new_head": local_head,
                        "expected_head": expected,
                        "name": target_name,
                        "protected": bool(local_ref.get("protected")),
                        "require_fast_forward": relation != "diverged",
                    },
                    headers=self._headers(),
                )
                advanced.raise_for_status()
                outcomes[loadout_id] = (
                    "diverged_preserved" if relation == "diverged" else "fast_forwarded"
                )
            return {
                "project_id": project_id,
                "peer": self.peer.public(),
                "server_id": identity["id"],
                "outcomes": outcomes,
            }
        finally:
            if owned:
                await client.aclose()

    async def synchronize(self, project_id: str) -> dict:
        """Bidirectional metadata/design sync; pull first so no remote work is lost."""
        pulled = await self.pull(project_id)
        pushed = await self.push(project_id)
        return {"project_id": project_id, "pull": pulled, "push": pushed}

    async def fetch_artifacts(
        self,
        project_id: str,
        engine: str,
        job_id: str,
        *,
        mode: str,
        paths: list[str] | None = None,
    ) -> dict:
        """Explicitly fetch selected files or atomically install one complete job."""
        if mode not in {"selected", "full"}:
            raise ValueError("artifact fetch mode must be 'selected' or 'full'")
        client, owned = await self._client()
        try:
            listing = await client.get(
                f"/api/collaboration/projects/{project_id}/artifacts/"
                f"{engine}/{job_id}/files",
                params={"copy": "true"},
                headers=self._headers(),
            )
            listing.raise_for_status()
            available = {item["path"]: item for item in listing.json()["files"]}
            selected = sorted(available) if mode == "full" else list(paths or [])
            if mode == "selected" and not selected:
                raise ValueError("selected artifact fetch needs at least one file")
            for relative in selected:
                path = PurePosixPath(relative)
                if (
                    relative not in available
                    or path.is_absolute()
                    or ".." in path.parts
                    or not path.parts
                ):
                    raise ValueError(f"unavailable or unsafe artifact path: {relative!r}")

            if mode == "full":
                destination = self.workspace / f"{engine}_jobs" / job_id
                if destination.exists():
                    raise FileExistsError(f"simulation job already exists: {engine}/{job_id}")
            else:
                destination = (
                    self.workspace
                    / ".nadoc-projects"
                    / project_id
                    / "artifact-cache"
                    / self.peer.id
                    / engine
                    / job_id
                )
            destination.parent.mkdir(parents=True, exist_ok=True)
            staging = Path(
                tempfile.mkdtemp(prefix=f".{job_id}.", suffix=".fetch", dir=destination.parent)
            )
            try:
                transferred = 0
                for relative in selected:
                    response = await client.get(
                        f"/api/collaboration/projects/{project_id}/artifacts/"
                        f"{engine}/{job_id}/file/{relative}",
                        headers=self._headers(),
                    )
                    response.raise_for_status()
                    target = staging.joinpath(*PurePosixPath(relative).parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(response.content)
                    transferred += len(response.content)
                if mode == "full":
                    job_json = staging / "job.json"
                    if not job_json.is_file():
                        raise ValueError("complete artifact fetch has no job.json")
                    metadata = json.loads(job_json.read_text(encoding="utf-8"))
                    if metadata.get("project_id") != project_id:
                        raise ValueError("fetched simulation project identity mismatch")
                if destination.exists():
                    if mode == "full":
                        raise FileExistsError(
                            f"simulation job already exists: {engine}/{job_id}"
                        )
                    shutil.rmtree(destination)
                shutil.move(str(staging), str(destination))
            except Exception:
                shutil.rmtree(staging, ignore_errors=True)
                raise
            if mode == "full":
                ProjectArtifactCatalog(self.workspace).publish_local_jobs(project_id)
            return {
                "project_id": project_id,
                "engine": engine,
                "job_id": job_id,
                "mode": mode,
                "files": selected,
                "bytes": transferred,
                "destination": str(destination.relative_to(self.workspace)),
            }
        finally:
            if owned:
                await client.aclose()
