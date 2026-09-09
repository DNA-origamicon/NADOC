"""Immutable, content-addressed project history for NADOC loadout branches.

The user-visible ``.nadoc`` remains a portable compatibility document.  This
store is the authoritative synchronization substrate: immutable revision
objects can be copied between servers, while tiny branch refs are advanced with
compare-and-swap semantics so divergent edits are preserved instead of won by
mtime/last-writer-wins.
"""

from __future__ import annotations

import base64
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import socket
import tempfile
import time
from typing import Any
import uuid

from backend.core.design_loadouts import decode_snapshot, encode_snapshot
from backend.core.models import Design, DesignLoadout


FORMAT = "nadoc.project-revision"
SCHEMA_VERSION = 1
STORE_DIR = ".nadoc-projects"


class BranchConflict(RuntimeError):
    """A branch head moved since the caller last observed it."""

    def __init__(self, loadout_id: str, expected: str | None, current: str | None):
        self.loadout_id = loadout_id
        self.expected = expected
        self.current = current
        super().__init__(
            f"loadout {loadout_id!r} head changed: expected {expected!r}, "
            f"current {current!r}"
        )


class RevisionCompatibilityError(ValueError):
    """A peer object uses a schema this server cannot safely interpret."""


@dataclass(frozen=True)
class StoredRevision:
    project_id: str
    revision_id: str
    snapshot_sha256: str
    loadout_id: str
    parent_revision_id: str | None
    created_at: str
    created_by: str
    application_version: str | None
    protected: bool


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(value, output, indent=2, ensure_ascii=False, sort_keys=True)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _atomic_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(value)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


@contextmanager
def _exclusive_lock(path: Path, timeout: float = 5.0):
    """Portable cross-process lock using atomic create, with crash recovery."""
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    fd = None
    while fd is None:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.write(fd, f"{os.getpid()}\n".encode())
        except FileExistsError:
            try:
                if time.time() - path.stat().st_mtime > 30:
                    path.unlink(missing_ok=True)
                    continue
            except FileNotFoundError:
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError(f"timed out acquiring project ref lock: {path}")
            time.sleep(0.02)
    try:
        yield
    finally:
        os.close(fd)
        path.unlink(missing_ok=True)


class ProjectRevisionStore:
    def __init__(self, workspace: Path):
        self.workspace = Path(workspace)
        self.root = self.workspace / STORE_DIR

    def _project(self, project_id: str) -> Path:
        if not project_id or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in project_id):
            raise ValueError("invalid project id")
        return self.root / project_id

    def object_path(self, project_id: str, revision_id: str) -> Path:
        if len(revision_id) != 64 or any(c not in "0123456789abcdef" for c in revision_id):
            raise ValueError("invalid revision id")
        return self._project(project_id) / "objects" / f"{revision_id}.json"

    def ref_path(self, project_id: str, loadout_id: str) -> Path:
        if not loadout_id or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in loadout_id):
            raise ValueError("invalid loadout id")
        return self._project(project_id) / "refs" / f"{loadout_id}.json"

    def snapshot_path(self, project_id: str, snapshot_sha256: str) -> Path:
        if len(snapshot_sha256) != 64 or any(
            c not in "0123456789abcdef" for c in snapshot_sha256
        ):
            raise ValueError("invalid snapshot checksum")
        return self._project(project_id) / "snapshots" / f"{snapshot_sha256}.nadoc.gz"

    def branch_head(self, project_id: str, loadout_id: str) -> str | None:
        path = self.ref_path(project_id, loadout_id)
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("head_revision_id")

    def branch_ref(self, project_id: str, loadout_id: str) -> dict | None:
        path = self.ref_path(project_id, loadout_id)
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

    def commit(
        self,
        design: Design,
        *,
        loadout_id: str,
        loadout_name: str,
        parent_revision_id: str | None,
        expected_head: str | None,
        protected: bool = False,
        created_by: str | None = None,
        application_version: str | None = None,
    ) -> StoredRevision:
        """Store an immutable snapshot and atomically advance its branch ref.

        ``expected_head`` is mandatory in meaning (``None`` means the caller
        observed no branch).  A mismatch never overwrites the competing head.
        Cross-process ref locking is introduced with peer sync; this local CAS
        already closes stale-client conflicts and keeps the storage contract.
        """
        stripped = design.model_copy(update={"loadouts": [], "active_loadout_id": None, "last_editable_loadout_id": None})
        snapshot = stripped.model_dump_json().encode("utf-8")
        snapshot_sha = hashlib.sha256(snapshot).hexdigest()
        identity = {
            "schema_version": SCHEMA_VERSION,
            "project_id": design.id,
            "loadout_id": loadout_id,
            "parent_revision_id": parent_revision_id,
            "snapshot_sha256": snapshot_sha,
        }
        revision_id = hashlib.sha256(_canonical_json(identity)).hexdigest()
        created_at = datetime.now(timezone.utc).isoformat()
        record = {
            "format": FORMAT,
            **identity,
            "revision_id": revision_id,
            "created_at": created_at,
            "created_by": created_by or socket.gethostname(),
            "application_version": application_version,
            "protected": protected,
        }
        snapshot_path = self.snapshot_path(design.id, snapshot_sha)
        if not snapshot_path.exists():
            _atomic_bytes(snapshot_path, gzip.compress(snapshot, mtime=0))
        object_path = self.object_path(design.id, revision_id)
        if object_path.exists():
            existing = json.loads(object_path.read_text(encoding="utf-8"))
            if any(existing.get(k) != record.get(k) for k in identity):
                raise ValueError(f"revision object collision: {revision_id}")
        else:
            _atomic_json(object_path, record)
        self.advance_branch(
            design.id,
            loadout_id,
            revision_id,
            expected_head=expected_head,
            name=loadout_name,
            protected=protected,
        )
        return StoredRevision(
            project_id=design.id,
            revision_id=revision_id,
            snapshot_sha256=snapshot_sha,
            loadout_id=loadout_id,
            parent_revision_id=parent_revision_id,
            created_at=created_at,
            created_by=record["created_by"],
            application_version=application_version,
            protected=protected,
        )

    def advance_branch(
        self,
        project_id: str,
        loadout_id: str,
        new_head: str,
        *,
        expected_head: str | None,
        name: str,
        protected: bool = False,
        require_fast_forward: bool = False,
    ) -> None:
        """Atomically move a ref after validating identity and ancestry."""
        self.read_revision(project_id, new_head)
        ref = self.ref_path(project_id, loadout_id)
        with _exclusive_lock(ref.with_suffix(".lock")):
            current = self.branch_head(project_id, loadout_id)
            if current != expected_head:
                raise BranchConflict(loadout_id, expected_head, current)
            if (
                require_fast_forward
                and current is not None
                and not self.is_ancestor(project_id, current, new_head)
            ):
                raise BranchConflict(loadout_id, current, new_head)
            _atomic_json(
                ref,
                {
                    "project_id": project_id,
                    "loadout_id": loadout_id,
                    "name": name,
                    "head_revision_id": new_head,
                    "protected": protected,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
            )

    def is_ancestor(self, project_id: str, ancestor: str, descendant: str) -> bool:
        """Whether ``ancestor`` occurs on descendant's first-parent chain."""
        seen: set[str] = set()
        cursor: str | None = descendant
        while cursor and cursor not in seen:
            if cursor == ancestor:
                return True
            seen.add(cursor)
            cursor = self.read_revision(project_id, cursor).parent_revision_id
        return False

    def revision_history(self, project_id: str, head: str) -> list[dict]:
        history = []
        seen: set[str] = set()
        cursor: str | None = head
        while cursor and cursor not in seen:
            seen.add(cursor)
            revision = self.read_revision(project_id, cursor)
            history.append(asdict(revision))
            cursor = revision.parent_revision_id
        return history

    def compare_revisions(
        self, project_id: str, left_revision: str, right_revision: str
    ) -> dict:
        left = self.load_design(project_id, left_revision)
        right = self.load_design(project_id, right_revision)
        fields = {
            "helices": len(left.helices),
            "strands": len(left.strands),
            "crossovers": len(left.crossovers),
            "forced_ligations": len(left.forced_ligations),
            "cluster_transforms": len(left.cluster_transforms),
            "feature_log": len(left.feature_log),
        }
        right_fields = {
            "helices": len(right.helices),
            "strands": len(right.strands),
            "crossovers": len(right.crossovers),
            "forced_ligations": len(right.forced_ligations),
            "cluster_transforms": len(right.cluster_transforms),
            "feature_log": len(right.feature_log),
        }
        left_log = [entry.model_dump(mode="json") for entry in left.feature_log]
        right_log = [entry.model_dump(mode="json") for entry in right.feature_log]
        common = 0
        for left_entry, right_entry in zip(left_log, right_log):
            if left_entry != right_entry:
                break
            common += 1
        return {
            "project_id": project_id,
            "left_revision": left_revision,
            "right_revision": right_revision,
            "identical": self.read_revision(project_id, left_revision).snapshot_sha256
            == self.read_revision(project_id, right_revision).snapshot_sha256,
            "left": {"name": left.metadata.name, "counts": fields},
            "right": {"name": right.metadata.name, "counts": right_fields},
            "delta": {key: right_fields[key] - fields[key] for key in fields},
            "common_feature_prefix": common,
            "left_only_features": max(0, len(left_log) - common),
            "right_only_features": max(0, len(right_log) - common),
        }

    def create_version(
        self,
        project_id: str,
        revision_id: str,
        *,
        name: str,
        source_loadout_id: str | None = None,
    ) -> dict:
        self.read_revision(project_id, revision_id)
        version_id = f"version-{uuid.uuid4().hex}"
        now = datetime.now(timezone.utc).isoformat()
        record = {
            "project_id": project_id,
            "loadout_id": version_id,
            "name": name.strip() or "Version",
            "head_revision_id": revision_id,
            "protected": True,
            "kind": "version",
            "source_loadout_id": source_loadout_id,
            "updated_at": now,
        }
        _atomic_json(self.ref_path(project_id, version_id), record)
        return record

    def promote_branch(
        self,
        project_id: str,
        source_loadout_id: str,
        target_loadout_id: str,
        *,
        expected_target_head: str | None,
        recovery_name: str | None = None,
    ) -> dict:
        """Promote source to target and preserve target's old head as a version."""
        source = self.branch_ref(project_id, source_loadout_id)
        target = self.branch_ref(project_id, target_loadout_id)
        if source is None:
            raise FileNotFoundError(f"unknown source loadout: {source_loadout_id}")
        current = target.get("head_revision_id") if target else None
        ref_path = self.ref_path(project_id, target_loadout_id)
        with _exclusive_lock(ref_path.with_suffix(".lock")):
            target = self.branch_ref(project_id, target_loadout_id)
            current = target.get("head_revision_id") if target else None
            if current != expected_target_head:
                raise BranchConflict(target_loadout_id, expected_target_head, current)
            recovery = None
            if current is not None:
                recovery = self.create_version(
                    project_id,
                    current,
                    name=recovery_name
                    or f"Before promotion to {target.get('name', target_loadout_id)}",
                    source_loadout_id=target_loadout_id,
                )
            now = datetime.now(timezone.utc).isoformat()
            promoted = {
                "project_id": project_id,
                "loadout_id": target_loadout_id,
                "name": target.get("name", target_loadout_id)
                if target
                else target_loadout_id,
                "head_revision_id": source["head_revision_id"],
                "protected": False,
                "kind": "branch",
                "promoted_from_loadout_id": source_loadout_id,
                "updated_at": now,
            }
            _atomic_json(ref_path, promoted)
        return {"target": promoted, "recovery_version": recovery}

    def relation(
        self, project_id: str, local_head: str | None, remote_head: str | None
    ) -> str:
        if local_head == remote_head:
            return "equal"
        if local_head is None:
            return "behind"
        if remote_head is None:
            return "ahead"
        if self.is_ancestor(project_id, local_head, remote_head):
            return "behind"
        if self.is_ancestor(project_id, remote_head, local_head):
            return "ahead"
        return "diverged"

    def project_manifest(self, project_id: str) -> dict:
        """Small sync inventory; never walks or hashes simulation artifacts."""
        project = self._project(project_id)
        refs = {}
        for path in sorted((project / "refs").glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            refs[data["loadout_id"]] = data
        objects = sorted(path.stem for path in (project / "objects").glob("*.json"))
        snapshots = sorted(
            path.name.removesuffix(".nadoc.gz")
            for path in (project / "snapshots").glob("*.nadoc.gz")
        )
        return {
            "format": "nadoc.project-manifest",
            "schema_version": SCHEMA_VERSION,
            "project_id": project_id,
            "refs": refs,
            "objects": objects,
            "snapshots": snapshots,
        }

    def project_ids(self) -> list[str]:
        if not self.root.is_dir():
            return []
        return sorted(
            path.name
            for path in self.root.iterdir()
            if path.is_dir() and (path / "refs").is_dir()
        )

    def export_revision(self, project_id: str, revision_id: str) -> dict:
        return json.loads(
            self.object_path(project_id, revision_id).read_text(encoding="utf-8")
        )

    def ingest_snapshot(
        self, project_id: str, snapshot_sha256: str, compressed: bytes
    ) -> None:
        try:
            raw = gzip.decompress(compressed)
        except (gzip.BadGzipFile, EOFError) as exc:
            raise ValueError("project snapshot checksum/decompression failure") from exc
        if hashlib.sha256(raw).hexdigest() != snapshot_sha256:
            raise ValueError("project snapshot checksum mismatch")
        design = Design.model_validate_json(raw)
        if design.id != project_id:
            raise ValueError("project snapshot identity mismatch")
        destination = self.snapshot_path(project_id, snapshot_sha256)
        if not destination.exists():
            _atomic_bytes(destination, gzip.compress(raw, mtime=0))

    def ingest_revision(self, record: dict) -> StoredRevision:
        if record.get("format") != FORMAT:
            raise ValueError("invalid project revision format")
        if record.get("schema_version") != SCHEMA_VERSION:
            raise RevisionCompatibilityError(
                f"unsupported project revision schema {record.get('schema_version')!r}"
            )
        identity = {
            "schema_version": record["schema_version"],
            "project_id": record["project_id"],
            "loadout_id": record["loadout_id"],
            "parent_revision_id": record.get("parent_revision_id"),
            "snapshot_sha256": record["snapshot_sha256"],
        }
        expected = hashlib.sha256(_canonical_json(identity)).hexdigest()
        if record.get("revision_id") != expected:
            raise ValueError("project revision identity checksum mismatch")
        if not self.snapshot_path(
            record["project_id"], record["snapshot_sha256"]
        ).is_file():
            raise FileNotFoundError("project revision snapshot is not present")
        destination = self.object_path(record["project_id"], expected)
        if not destination.exists():
            _atomic_json(destination, record)
        return self.read_revision(record["project_id"], expected)

    def load_design(self, project_id: str, revision_id: str) -> Design:
        data = json.loads(self.object_path(project_id, revision_id).read_text(encoding="utf-8"))
        if data.get("format") != FORMAT or data.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("unsupported project revision format")
        if "snapshot_gz_b64" in data:  # v1 development compatibility
            raw = gzip.decompress(base64.b64decode(data["snapshot_gz_b64"]))
        else:
            raw = gzip.decompress(
                self.snapshot_path(project_id, data["snapshot_sha256"]).read_bytes()
            )
        if hashlib.sha256(raw).hexdigest() != data.get("snapshot_sha256"):
            raise ValueError("project revision snapshot checksum mismatch")
        return Design.model_validate_json(raw)

    def read_revision(self, project_id: str, revision_id: str) -> StoredRevision:
        data = json.loads(
            self.object_path(project_id, revision_id).read_text(encoding="utf-8")
        )
        if data.get("format") != FORMAT or data.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("unsupported project revision format")
        return StoredRevision(
            project_id=data["project_id"],
            revision_id=data["revision_id"],
            snapshot_sha256=data["snapshot_sha256"],
            loadout_id=data["loadout_id"],
            parent_revision_id=data.get("parent_revision_id"),
            created_at=data["created_at"],
            created_by=data["created_by"],
            application_version=data.get("application_version"),
            protected=bool(data.get("protected")),
        )

    def materialize_loadouts(self, design: Design) -> Design:
        """Migrate embedded loadouts to revision objects, idempotently."""
        migrated: list[DesignLoadout] = []
        for loadout in design.loadouts:
            snapshot = decode_snapshot(loadout.design_snapshot_gz_b64)
            # Legacy copied snapshots can carry the old project identity.
            snapshot = snapshot.model_copy(update={"id": design.id, "metadata": design.metadata})
            head = self.branch_head(design.id, loadout.id)
            if loadout.head_revision_id and head == loadout.head_revision_id:
                migrated.append(loadout)
                continue
            if loadout.head_revision_id and head != loadout.head_revision_id:
                # Two autosaves may start from the same embedded head.  If the
                # winner only persisted the exact embedded fallback snapshot,
                # adopting its head is safe and makes the operation idempotent.
                # A content difference remains a real branch divergence.
                same_snapshot = False
                if head and self.object_path(design.id, loadout.head_revision_id).is_file():
                    try:
                        current = self.load_design(design.id, head)
                        same_snapshot = (
                            current.model_dump_json()
                            == snapshot.model_copy(
                                update={"loadouts": [], "active_loadout_id": None,
                                        "last_editable_loadout_id": None}
                            ).model_dump_json()
                        )
                        # The active fallback still contains the pre-edit
                        # topology. A sibling autosave may already have saved
                        # our exact live edit (e.g. a forced ligation).
                        if loadout.id == design.active_loadout_id and not loadout.protected:
                            same_snapshot = same_snapshot or (
                                current.model_dump_json()
                                == design.model_copy(update={
                                    "loadouts": [], "active_loadout_id": None,
                                    "last_editable_loadout_id": None,
                                }).model_dump_json()
                            )
                    except (FileNotFoundError, ValueError, OSError):
                        same_snapshot = False
                if same_snapshot:
                    migrated.append(loadout.model_copy(update={"head_revision_id": head}))
                    continue
                raise BranchConflict(loadout.id, loadout.head_revision_id, head)
            revision = self.commit(
                snapshot,
                loadout_id=loadout.id,
                loadout_name=loadout.name,
                parent_revision_id=head,
                expected_head=head,
                protected=loadout.protected,
            )
            migrated.append(loadout.model_copy(update={
                "head_revision_id": revision.revision_id,
                "base_revision_id": loadout.base_revision_id or revision.parent_revision_id,
            }))
        return design.model_copy(update={"loadouts": migrated})


def refresh_active_revision(workspace: Path, design: Design) -> Design:
    """Persist current editable state as the active loadout's next revision."""
    if not design.loadouts:
        payload, size = encode_snapshot(design)
        design = design.model_copy(update={
            "loadouts": [DesignLoadout(
                id="main",
                name="Main",
                design_snapshot_gz_b64=payload,
                snapshot_size_bytes=size,
            )],
            "active_loadout_id": "main",
        })
    elif not design.active_loadout_id:
        design = design.model_copy(
            update={"active_loadout_id": design.loadouts[0].id}
        )
    store = ProjectRevisionStore(workspace)
    materialized = store.materialize_loadouts(design)
    active = next((item for item in materialized.loadouts if item.id == materialized.active_loadout_id), None)
    if active is None or active.protected:
        return materialized
    head = store.branch_head(materialized.id, active.id)
    # Do not create a child revision when only the portable-file wrapper is
    # being re-saved.  Besides avoiding history noise, this closes the race
    # where overlapping autosaves made one another spuriously stale.
    if head:
        current_record = store.read_revision(materialized.id, head)
        stripped = materialized.model_copy(
            update={"loadouts": [], "active_loadout_id": None,
                    "last_editable_loadout_id": None}
        )
        current_sha = hashlib.sha256(stripped.model_dump_json().encode("utf-8")).hexdigest()
        if current_sha == current_record.snapshot_sha256:
            payload, size = encode_snapshot(materialized)
            loadouts = [
                item.model_copy(update={
                    "head_revision_id": head,
                    "design_snapshot_gz_b64": payload,
                    "snapshot_size_bytes": size,
                }) if item.id == active.id else item
                for item in materialized.loadouts
            ]
            return materialized.model_copy(update={"loadouts": loadouts})
    try:
        revision = store.commit(
            materialized,
            loadout_id=active.id,
            loadout_name=active.name,
            parent_revision_id=active.head_revision_id,
            expected_head=active.head_revision_id,
        )
    except BranchConflict as exc:
        # A concurrent save can win after materialization. Acknowledge only
        # byte-identical content; a different edit must retain the conflict.
        if not exc.current:
            raise
        revision = store.read_revision(materialized.id, exc.current)
        stripped = materialized.model_copy(update={
            "loadouts": [], "active_loadout_id": None,
            "last_editable_loadout_id": None,
        })
        if hashlib.sha256(stripped.model_dump_json().encode("utf-8")).hexdigest() != revision.snapshot_sha256:
            raise
    payload, size = encode_snapshot(materialized)
    loadouts = [
        item.model_copy(update={
            "head_revision_id": revision.revision_id,
            "base_revision_id": item.base_revision_id or head,
            "design_snapshot_gz_b64": payload,
            "snapshot_size_bytes": size,
        }) if item.id == active.id else item
        for item in materialized.loadouts
    ]
    return materialized.model_copy(update={"loadouts": loadouts})


def design_revision_provenance(design: Design) -> tuple[str, str | None]:
    """Return the stable project and exact active-loadout revision identities."""
    active = next(
        (item for item in design.loadouts if item.id == design.active_loadout_id),
        None,
    )
    return design.id, active.head_revision_id if active is not None else None


def record_simulation_revision(
    workspace: Path, design: Design, engine: str, job_id: str
) -> StoredRevision:
    """Create the immutable design tag a simulation job is bound to.

    The tag is independent of the editable branch head: submitting a job must
    freeze the exact input even when the design has never been saved or its
    current loadout has advanced. Repeated calls for one job are idempotent.
    """
    safe_engine = "".join(c for c in engine.lower() if c.isalnum() or c in "-_")
    loadout_id = f"simulation-{safe_engine}-{job_id}"
    store = ProjectRevisionStore(workspace)
    existing = store.branch_head(design.id, loadout_id)
    if existing is not None:
        return store.read_revision(design.id, existing)
    return store.commit(
        design,
        loadout_id=loadout_id,
        loadout_name=f"Simulation · {engine} · {job_id}",
        parent_revision_id=None,
        expected_head=None,
        protected=True,
    )


def migrate_job_revision_provenance(
    workspace: Path, source_path: str | None = None
) -> dict[str, int]:
    """Backfill legacy job identity from frozen snapshots without copying artifacts."""
    from backend.core.job_cleanup import _job_classes, _norm

    workspace = Path(workspace)
    wanted = _norm(source_path) if source_path else None
    migrated = 0
    skipped = 0
    for cls in _job_classes():
        engine = cls.__module__.rsplit(".", 1)[-1].removesuffix("_job")
        for job in cls.list_jobs(workspace):
            if wanted is not None and _norm(job.design_source_path) != wanted:
                continue
            if job.project_id and job.design_revision_id:
                skipped += 1
                continue
            frozen = job.job_dir(workspace) / "design.json"
            if not frozen.is_file():
                skipped += 1
                continue
            try:
                snapshot = Design.from_json(frozen.read_text(encoding="utf-8"))
                if job.design_source_path:
                    source = workspace / _norm(job.design_source_path)
                    if source.is_file():
                        current = Design.from_json(source.read_text(encoding="utf-8"))
                        snapshot = snapshot.model_copy(update={"id": current.id})
                revision = record_simulation_revision(
                    workspace, snapshot, engine, job.job_id
                )
                job.project_id = revision.project_id
                job.design_revision_id = revision.revision_id
                job.save(workspace)
                migrated += 1
            except (OSError, ValueError, json.JSONDecodeError):
                skipped += 1
    return {"migrated": migrated, "skipped": skipped}
