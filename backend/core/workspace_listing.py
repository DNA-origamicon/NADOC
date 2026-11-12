"""Read-only library metadata, without materializing validation result folders."""

import os
from datetime import datetime, timezone
from pathlib import Path

from backend.core.workspace import is_internal_workspace_path


def list_workspace_entries(workspace: Path) -> list[dict]:
    entries = []
    validation_folders = {}
    needed_validation_folders = set()
    pending = [(os.fspath(workspace), "")]

    def append_entry(name, relative, kind, stat):
        entries.append({
            "name": name,
            "path": relative,
            "type": kind,
            "mtime_iso": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            "size_bytes": 0 if kind == "folder" else stat.st_size,
        })

    while pending:
        directory, parent = pending.pop()
        try:
            with os.scandir(directory) as scan:
                children = sorted(scan, key=lambda child: child.name)
        except OSError:
            continue
        for child in children:
            # Nested design repositories keep their Git database beside the
            # documents. Never expose or walk hidden metadata directories.
            if child.name.startswith("."):
                continue
            relative = os.path.join(parent, child.name) if parent else child.name
            # The existing exclusion policy is root-scoped. Check it once per
            # root, rather than constructing Paths for every nested result file.
            if not parent and is_internal_workspace_path(child.name):
                continue
            validation = relative.split(os.sep, 1)[0] == "validation"
            try:
                if child.is_dir():
                    # Match os.walk's no-follow policy, including visible links.
                    if not child.is_symlink():
                        pending.append((child.path, relative))
                    if validation:
                        validation_folders[relative] = child
                    else:
                        append_entry(child.name, relative, "folder", child.stat())
                    continue
                if child.name.startswith((".", "__")):
                    continue
                stem, suffix = os.path.splitext(child.name)
                if suffix not in (".nadoc", ".nass"):
                    continue
                append_entry(stem, relative, "assembly" if suffix == ".nass" else "part", child.stat())
            except OSError:
                continue
            if validation:
                ancestor = parent
                while ancestor:
                    needed_validation_folders.add(ancestor)
                    ancestor = os.path.dirname(ancestor)

    # Discover documents at arbitrary depth, but only stat/return their ancestor
    # folders. Empty user folders outside validation remain visible as before.
    for relative in sorted(needed_validation_folders):
        child = validation_folders[relative]
        try:
            append_entry(child.name, relative, "folder", child.stat())
        except OSError:
            continue
    entries.sort(key=lambda entry: entry["mtime_iso"], reverse=True)
    return entries
