"""Storage guards for large photoproduct evidence and engine-generated artifacts."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


ARCHIVE_MOUNT = Path("/media/jojo/Archive")


def validate_photoproduct_storage_root(storage_root: Path) -> dict[str, Any]:
    """Resolve a writable root and fail if the workstation Archive is unmounted.

    Portable callers may select another durable root. On this workstation, however, a
    path beneath the known Archive mount must never fall back to the system filesystem's
    empty mount-point directory.
    """

    root = storage_root.resolve()
    if not root.is_dir():
        raise ValueError(f"storage root is missing or not a directory: {root}")
    if not os.access(root, os.W_OK):
        raise ValueError(f"storage root is not writable: {root}")
    archive_mount = ARCHIVE_MOUNT.resolve()
    try:
        root.relative_to(archive_mount)
    except ValueError:
        archive_required = False
    else:
        archive_required = True
        if not archive_mount.is_mount():
            raise ValueError(
                f"Archive drive is not mounted at {archive_mount}; refusing to write "
                "photoproduct data to the system-disk mount directory"
            )
    return {
        "storage_root": str(root),
        "archive_mount_required": archive_required,
        "archive_mount": str(archive_mount) if archive_required else None,
        "archive_mounted": archive_mount.is_mount() if archive_required else None,
    }
