"""Project branch naming and single-writer edit leases.

Leases protect mutable branch heads; immutable revision objects never need a
lease.  State is filesystem-backed so separate NADOC server processes sharing a
workspace agree, and every mutation is serialized by the same portable lock
primitive used for revision refs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import re
import socket
import time
import uuid

from backend.core.project_revisions import (
    ProjectRevisionStore,
    _atomic_json,
    _exclusive_lock,
)


@dataclass(frozen=True)
class LeaseResult:
    status: str
    project_id: str
    loadout_id: str
    owner_server_id: str
    owner_client_id: str
    expires_at: float
    forked_from_loadout_id: str | None = None


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "-", value).strip("-")
    return cleaned[:80] or uuid.uuid4().hex


class ProjectLeaseStore:
    def __init__(self, workspace: Path):
        self.revisions = ProjectRevisionStore(workspace)

    def _path(self, project_id: str, loadout_id: str) -> Path:
        return self.revisions._project(project_id) / "leases" / f"{_slug(loadout_id)}.json"

    def current(self, project_id: str, loadout_id: str) -> dict | None:
        path = self._path(project_id, loadout_id)
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if float(data.get("expires_at", 0)) <= time.time():
            path.unlink(missing_ok=True)
            return None
        return data

    def _unique_branch_name(self, project_id: str, requested: str, server_name: str) -> str:
        manifest = self.revisions.project_manifest(project_id)
        taken = {
            str(ref.get("name", "")).strip().casefold()
            for ref in manifest["refs"].values()
        }
        if requested.strip().casefold() not in taken:
            return requested.strip()
        base = f"{requested.strip()} — {server_name} — {datetime.now().date().isoformat()}"
        candidate = base
        number = 2
        while candidate.casefold() in taken:
            candidate = f"{base} ({number})"
            number += 1
        return candidate

    def unique_branch_name(
        self, project_id: str, requested: str, server_name: str
    ) -> str:
        return self._unique_branch_name(project_id, requested, server_name)

    def _fork_branch(
        self, project_id: str, source_loadout_id: str, server_name: str
    ) -> tuple[str, str]:
        manifest = self.revisions.project_manifest(project_id)
        source = manifest["refs"].get(source_loadout_id)
        if source is None:
            raise FileNotFoundError(f"unknown loadout: {source_loadout_id}")
        source_head = source["head_revision_id"]
        name = self._unique_branch_name(project_id, source.get("name", "Branch"), server_name)
        loadout_id = _slug(f"{source_loadout_id}-{server_name}-{uuid.uuid4().hex[:8]}")
        design = self.revisions.load_design(project_id, source_head)
        self.revisions.commit(
            design,
            loadout_id=loadout_id,
            loadout_name=name,
            parent_revision_id=source_head,
            expected_head=None,
        )
        return loadout_id, name

    def acquire(
        self,
        project_id: str,
        loadout_id: str,
        *,
        server_id: str,
        client_id: str,
        server_name: str | None = None,
        ttl_seconds: int = 90,
        force: bool = False,
        auto_fork: bool = False,
    ) -> LeaseResult:
        ttl_seconds = max(15, min(int(ttl_seconds), 600))
        original = loadout_id
        path = self._path(project_id, loadout_id)
        with _exclusive_lock(path.with_suffix(".lock")):
            current = self.current(project_id, loadout_id)
            same_owner = current and (
                current.get("owner_server_id") == server_id
                and current.get("owner_client_id") == client_id
            )
            if current and not same_owner and not force:
                if not auto_fork:
                    return LeaseResult(
                        status="read_only",
                        project_id=project_id,
                        loadout_id=loadout_id,
                        owner_server_id=current["owner_server_id"],
                        owner_client_id=current["owner_client_id"],
                        expires_at=float(current["expires_at"]),
                    )
                loadout_id, _name = self._fork_branch(
                    project_id, loadout_id, server_name or socket.gethostname()
                )
                path = self._path(project_id, loadout_id)
            expires = time.time() + ttl_seconds
            record = {
                "project_id": project_id,
                "loadout_id": loadout_id,
                "owner_server_id": server_id,
                "owner_client_id": client_id,
                "acquired_at": time.time(),
                "expires_at": expires,
                "forced": bool(force and current and not same_owner),
            }
            _atomic_json(path, record)
            return LeaseResult(
                status="forked" if loadout_id != original else "acquired",
                project_id=project_id,
                loadout_id=loadout_id,
                owner_server_id=server_id,
                owner_client_id=client_id,
                expires_at=expires,
                forked_from_loadout_id=(original if loadout_id != original else None),
            )

    def release(
        self,
        project_id: str,
        loadout_id: str,
        *,
        server_id: str,
        client_id: str,
        force: bool = False,
    ) -> bool:
        path = self._path(project_id, loadout_id)
        with _exclusive_lock(path.with_suffix(".lock")):
            current = self.current(project_id, loadout_id)
            if current is None:
                return False
            if not force and (
                current.get("owner_server_id") != server_id
                or current.get("owner_client_id") != client_id
            ):
                return False
            path.unlink(missing_ok=True)
            return True
