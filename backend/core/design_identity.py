"""Persistent design identity and workspace-location reconciliation.

``Design.id`` follows a logical document across rename/move.  A copy or Save As
is a new document and receives a fresh UUID.  The embedded last-known path is
provenance/signoff, never the identity itself.  Legacy files have no path claim
and acquire one without changing their existing UUID.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import uuid

from backend.core.models import Design


def normalize_workspace_path(path: str | None) -> str | None:
    if not path:
        return None
    return str(path).replace("\\", "/").lstrip("./").rstrip("/") or None


def _stamp(design: Design, path: str, *, new_id: bool) -> Design:
    metadata = design.metadata.model_copy(
        update={
            "identity_last_known_path": normalize_workspace_path(path),
            "identity_confirmed_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    updates = {"metadata": metadata}
    if new_id:
        updates["id"] = str(uuid.uuid4())
    return design.model_copy(update=updates)


def reconcile_open_identity(
    design: Design, path: str, workspace: Path
) -> tuple[Design, str, str | None]:
    """Return ``(design, disposition, previous_path)`` for a workspace open.

    * legacy/unclaimed -> retain UUID and claim path
    * same path -> retain UUID and refresh signoff
    * old path missing -> move, retain UUID
    * old path still exists -> copy, mint UUID
    """
    current = normalize_workspace_path(path)
    previous = normalize_workspace_path(design.metadata.identity_last_known_path)
    if not current:
        return design, "untracked", previous
    if previous is None:
        return _stamp(design, current, new_id=False), "claimed", None
    if previous == current:
        return design, "confirmed", previous
    old_exists = (workspace / previous).is_file()
    if old_exists:
        return _stamp(design, current, new_id=True), "copy", previous
    return _stamp(design, current, new_id=False), "move", previous


def prepare_workspace_save(
    design: Design, destination: str
) -> tuple[Design, str, str | None]:
    """Claim an initial save, preserve an in-place save, fork a Save As."""
    dest = normalize_workspace_path(destination)
    previous = normalize_workspace_path(design.metadata.identity_last_known_path)
    if not dest:
        return design, "untracked", previous
    if previous is None:
        return _stamp(design, dest, new_id=False), "claimed", None
    if previous == dest:
        return _stamp(design, dest, new_id=False), "confirmed", previous
    return _stamp(design, dest, new_id=True), "save_as", previous


def relocate_identity(design: Design, old_path: str, new_path: str) -> Design:
    """Retain UUID while updating a path after a NADOC-managed move/rename."""
    old = normalize_workspace_path(old_path)
    claimed = normalize_workspace_path(design.metadata.identity_last_known_path)
    if claimed not in (None, old):
        return design
    return _stamp(design, new_path, new_id=False)


def fork_identity_for_copy(design: Design, path: str) -> Design:
    """Assign an independent logical-document UUID to a detected copy."""
    return _stamp(design, path, new_id=True)
