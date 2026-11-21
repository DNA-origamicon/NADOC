"""Read-only filesystem validation for the workspace Move to picker."""

import os
from pathlib import Path

from backend.core.workspace import is_internal_workspace_path
from backend.core.workspace_listing import list_workspace_entries


def list_move_destinations(workspace: Path, paths: list[str]) -> list[str]:
    root = workspace.resolve()
    sources = []
    for path in dict.fromkeys(paths):
        source = (root / path).resolve(strict=True)
        if source == root or not source.is_relative_to(root):
            raise ValueError("Choose an item inside the workspace.")
        source_relative = source.relative_to(root)
        if is_internal_workspace_path(source_relative) or any(
            part.startswith((".", "__")) for part in source_relative.parts
        ):
            raise ValueError("Internal workspace items cannot be moved here.")
        if not os.access(source.parent, os.W_OK | os.X_OK):
            return []
        sources.append(source)
    if not sources:
        raise ValueError("Choose at least one item to move.")
    # These selections cannot be moved together without overwriting or moving
    # the same item twice. Do not offer destinations for a partially valid move.
    if len({source.name for source in sources}) != len(sources):
        return []
    if any(a != b and a.is_relative_to(b) for a in sources for b in sources):
        return []

    candidates = [""] + [entry["path"] for entry in list_workspace_entries(root)
                         if entry["type"] == "folder"]
    result = []
    seen = set()
    for relative in candidates:
        try:
            folder = (root / relative).resolve(strict=True)
            if not folder.is_relative_to(root) or not folder.is_dir():
                continue
            resolved_relative = folder.relative_to(root)
            if is_internal_workspace_path(resolved_relative) or any(
                part.startswith((".", "__")) for part in resolved_relative.parts
            ):
                continue
            if folder in seen or not os.access(folder, os.W_OK | os.X_OK):
                continue
            if all(folder == source.parent for source in sources):
                continue
            if any(source.is_dir() and folder.is_relative_to(source) for source in sources):
                continue
            if any(folder != source.parent and (
                (folder / source.name).exists() or (folder / source.name).is_symlink()
            ) for source in sources):
                continue
            seen.add(folder)
            result.append(relative)
        except (OSError, RuntimeError):
            continue
    return sorted(result)
