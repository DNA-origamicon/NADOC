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


def derive_placement_spec(design: dict) -> dict | None:
    """Derive how to *place* a primitive as an additive extrude, or None.

    Pure. A primitive's content is defined by its feature log; for the simple
    single-extrusion building blocks (6hb / 18hb beams) that log is one
    ``bundle-create`` entry whose params already carry the full footprint. We
    read those params and hand them straight to the additive ``bundle-segment``
    path at placement time (translated to the cursor's lattice cell). Falls back
    to deriving the footprint from the helices' ``grid_pos`` for older files with
    no usable log entry.

    Returns a dict with:
      ``cells``           — list of ``[row, col]`` footprint cells (lattice coords)
      ``anchor_cell``     — ``[row, col]`` the deterministic reference cell
                            (min row, then min col); what snaps to the cursor
      ``length_bp``       — default extrude length (editable at placement)
      ``plane``           — the saved origin plane ('XY' | 'XZ' | 'YZ')
      ``strand_filter``   — 'both' | 'scaffold' | 'staple'
      ``ligate_adjacent`` — bool
      ``lattice``         — 'HONEYCOMB' | 'SQUARE'

    None when no footprint can be derived (e.g. an empty/malformed design).
    """
    lattice = design.get("lattice_type") or "HONEYCOMB"

    # Preferred source: the bundle-create op's params (exact footprint + length).
    for entry in design.get("feature_log") or []:
        if entry.get("op_kind") != "bundle-create":
            continue
        p = entry.get("params") or {}
        cells = p.get("cells")
        if not cells:
            break  # malformed create op → fall through to helix derivation
        cells = [[int(r), int(c)] for r, c in cells]
        return {
            "cells": cells,
            "anchor_cell": _anchor_cell(cells),
            "length_bp": int(p.get("length_bp") or _length_from_helices(design) or 0),
            "plane": p.get("plane") or "XY",
            "strand_filter": p.get("strand_filter") or "both",
            "ligate_adjacent": bool(p.get("ligate_adjacent", True)),
            "lattice": p.get("lattice_type") or lattice,
        }

    # Fallback: footprint straight off the helices (no usable log entry).
    cells = _cells_from_helices(design)
    if not cells:
        return None
    return {
        "cells": cells,
        "anchor_cell": _anchor_cell(cells),
        "length_bp": int(_length_from_helices(design) or 0),
        "plane": "XY",
        "strand_filter": "both",
        "ligate_adjacent": True,
        "lattice": lattice,
    }


def _anchor_cell(cells: list[list[int]]) -> list[int]:
    """The deterministic reference cell: lowest row, then lowest col."""
    return list(min(cells, key=lambda rc: (rc[0], rc[1])))


def _cells_from_helices(design: dict) -> list[list[int]]:
    """Footprint cells read off each helix's ``grid_pos`` (deduped, in order)."""
    out: list[list[int]] = []
    seen: set[tuple[int, int]] = set()
    for h in design.get("helices") or []:
        gp = h.get("grid_pos")
        if not gp:
            continue
        rc = (int(gp[0]), int(gp[1]))
        if rc in seen:
            continue
        seen.add(rc)
        out.append([rc[0], rc[1]])
    return out


def _length_from_helices(design: dict) -> int:
    """A representative helix length (bp) for the bundle, 0 if unknown."""
    for h in design.get("helices") or []:
        n = h.get("length_bp")
        if n:
            return int(n)
    return 0


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
        meta["placement"] = derive_placement_spec(design)
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
