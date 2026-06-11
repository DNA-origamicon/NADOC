"""Primitive catalog service — scan a folder of ``.nadoc`` designs and expose
them as a list of pre-validated building blocks for the editor's "Add Primitive"
panel.

This is the *temporary* dev source: it reads whatever ``.nadoc`` files sit in the
workspace ``Primitives/`` folder, deriving display metadata (helix count,
lattice, bundle name) directly from each design. There is no curated manifest yet
— that's the planned in-repo registry migration (see ``workspace/Primitives/
README.md``). Keeping the derivation here, pure and testable, means swapping the
source later only changes *where the dicts come from*, not their shape.

Layering: this is core (L1) — it never imports the api layer. The caller (the
``routes_primitives`` router) owns resolving the workspace directory and passes
it in, so this module has no opinion about where the workspace lives.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# Files we generate next to each primitive's design (by the headless
# build-primitives pipeline). Named off the design's stem.
_PREVIEW_SUFFIX = ".gif"
_POSTER_SUFFIX = ".poster.png"

# A safe primitive id is the design's filename stem — letters, digits, dash,
# underscore. Used to build URLs, so it must never contain path separators.
_SAFE_ID = re.compile(r"^[A-Za-z0-9_\-]+$")


def is_safe_id(primitive_id: str) -> bool:
    """True if ``primitive_id`` is a bare, path-separator-free stem."""
    return bool(_SAFE_ID.match(primitive_id))


def derive_metadata(design: dict, stem: str) -> dict:
    """Derive a primitive's display metadata from a parsed ``.nadoc`` dict.

    Pure. No file IO. Everything is read off the design document so a new
    primitive needs no hand-written manifest yet — drop a posed ``.nadoc`` in
    and it shows up named by its helix count.
    """
    helices = design.get("helices") or []
    helix_count = len(helices)
    lattice = design.get("lattice_type") or "HONEYCOMB"
    poses = design.get("camera_poses") or []

    # Prefer a deliberately-set human name; otherwise name by size. A name equal
    # to the filename stem is treated as auto-set-on-save (not a real label) and
    # ignored, so "6hb_primitive.nadoc" shows as "6-Helix Bundle", not its stem.
    name = (design.get("metadata") or {}).get("name") or design.get("name")
    if not name or name == stem:
        name = f"{helix_count}-Helix Bundle"

    lattice_label = "Honeycomb" if lattice == "HONEYCOMB" else "Square" if lattice == "SQUARE" else lattice

    return {
        "id": stem,
        "name": name,
        "short_name": f"{helix_count}HB",
        "description": f"{lattice_label} {helix_count}-helix beam",
        "lattice": lattice,
        "helix_count": helix_count,
        "pose_count": len(poses),
    }


def list_primitives(primitives_dir: Path) -> list[dict]:
    """Scan ``primitives_dir`` for ``*.nadoc`` files and return one metadata dict
    per primitive, sorted by helix count then name.

    Each entry is :func:`derive_metadata` plus ``has_preview`` / ``has_poster``
    flags reflecting whether the generated assets exist on disk. Malformed
    ``.nadoc`` files are skipped rather than aborting the whole listing.
    """
    if not primitives_dir.is_dir():
        return []

    out: list[dict] = []
    for path in sorted(primitives_dir.glob("*.nadoc")):
        stem = path.stem
        if not is_safe_id(stem):
            continue
        try:
            design = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        meta = derive_metadata(design, stem)
        meta["has_preview"] = (primitives_dir / f"{stem}{_PREVIEW_SUFFIX}").is_file()
        meta["has_poster"] = (primitives_dir / f"{stem}{_POSTER_SUFFIX}").is_file()
        out.append(meta)

    out.sort(key=lambda m: (m["helix_count"], m["name"]))
    return out


def design_path(primitives_dir: Path, primitive_id: str) -> Path | None:
    """Path to a primitive's ``.nadoc`` design, or None if id is unsafe/missing."""
    if not is_safe_id(primitive_id):
        return None
    p = primitives_dir / f"{primitive_id}.nadoc"
    return p if p.is_file() else None


def preview_path(primitives_dir: Path, primitive_id: str) -> Path | None:
    """Path to a primitive's generated preview GIF, or None if unsafe/missing."""
    if not is_safe_id(primitive_id):
        return None
    p = primitives_dir / f"{primitive_id}{_PREVIEW_SUFFIX}"
    return p if p.is_file() else None


def poster_path(primitives_dir: Path, primitive_id: str) -> Path | None:
    """Path to a primitive's generated static poster PNG, or None if unsafe/missing."""
    if not is_safe_id(primitive_id):
        return None
    p = primitives_dir / f"{primitive_id}{_POSTER_SUFFIX}"
    return p if p.is_file() else None
