"""
assembly_flatten.py — flatten an Assembly into a single merged Design.

Each PartInstance's Design is:
  1. Loaded from source (inline design or file).
  2. All helix axes (axis_start, axis_end) are transformed by the instance's
     placement Mat4x4 (row-major) from local frame into world frame.
  3. All IDs are namespaced: helix.id → "inst-{inst.id}::{helix.id}".
     Strand IDs and Domain.helix_id references are updated to match.

Assembly-level helices/strands are included with an "asm::" prefix.

The returned Design has:
  - lattice_type = HONEYCOMB   (safest default for mixed designs)
  - All helix IDs globally unique (validated before return)
  - No deformations, cluster_transforms, or feature_log (those are per-part)
"""

from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    pass

from backend.core.models import (
    Assembly,
    Design,
    DesignMetadata,
    Domain,
    Helix,
    LatticeType,
    PartSourceFile,
    PartSourceInline,
    Strand,
    Vec3,
)

# Project root — two levels above this file: core/ → backend/ → root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_LIBRARY_DIR  = _PROJECT_ROOT / "parts-library"


def _load_design(source) -> Design:
    """Resolve a PartSource to a Design object."""
    if isinstance(source, PartSourceInline):
        return source.design
    if isinstance(source, PartSourceFile):
        # Resolve relative to project root then parts-library
        candidates = [
            _PROJECT_ROOT / source.path,
            _LIBRARY_DIR  / source.path,
        ]
        for p in candidates:
            if p.exists():
                return Design.from_json(p.read_text())
        raise FileNotFoundError(f"Part file not found: {source.path!r}")
    raise ValueError(f"Unknown source type: {type(source)}")


def _mat4_from_values(values: list[float]) -> np.ndarray:
    """Build a 4×4 numpy array from a row-major flat list of 16 floats."""
    if not values or len(values) != 16:
        return np.eye(4)
    return np.array(values, dtype=float).reshape(4, 4)


def _transform_vec3(mat4: np.ndarray, v: Vec3) -> Vec3:
    """Apply a 4×4 row-major transform to a Vec3 and return a new Vec3."""
    pt = np.array([v.x, v.y, v.z, 1.0])
    result = mat4 @ pt   # row-major: M × p
    return Vec3(x=float(result[0]), y=float(result[1]), z=float(result[2]))


def _prefix_helix(helix: Helix, prefix: str, mat4: np.ndarray) -> Helix:
    """Return a copy of helix with prefixed ID and transformed axis."""
    return helix.model_copy(update={
        "id":         f"{prefix}{helix.id}",
        "axis_start": _transform_vec3(mat4, helix.axis_start),
        "axis_end":   _transform_vec3(mat4, helix.axis_end),
    })


def _prefix_domain(domain: Domain, prefix: str) -> Domain:
    """Return a copy of domain with the helix_id prefixed."""
    return domain.model_copy(update={"helix_id": f"{prefix}{domain.helix_id}"})


def _prefix_strand(strand: Strand, strand_prefix: str, helix_prefix: str) -> Strand:
    """Return a copy of strand with prefixed strand ID and all domain helix_ids."""
    return strand.model_copy(update={
        "id":      f"{strand_prefix}{strand.id}",
        "domains": [_prefix_domain(d, helix_prefix) for d in strand.domains],
    })


def flatten_assembly(assembly: Assembly) -> Design:
    """
    Merge all PartInstances (and assembly-level helices/strands) into one Design.

    Returns a new Design with:
      - Helix IDs: "inst-{inst.id}::{helix.id}"
      - Strand IDs: "inst-{inst.id}::{strand.id}"
      - Assembly helix IDs: "asm::{helix.id}"
      - Assembly strand IDs: "asm::{strand.id}"
      - lattice_type = HONEYCOMB
    Raises ValueError if any flattened helix ID appears more than once.
    """
    all_helices: list[Helix]  = []
    all_strands: list[Strand] = []

    for inst in assembly.instances:
        if not inst.visible:
            continue
        try:
            design = _load_design(inst.source)
        except FileNotFoundError:
            continue  # skip missing file sources

        hp = f"inst-{inst.id}::"          # helix/domain prefix
        sp = f"inst-{inst.id}::"          # strand prefix
        mat4 = _mat4_from_values(inst.transform.values)

        for helix in design.helices:
            all_helices.append(_prefix_helix(helix, hp, mat4))

        for strand in design.strands:
            all_strands.append(_prefix_strand(strand, sp, hp))

    # Assembly-level helices and strands (linkers, VSC dashed lines)
    asm_hp = "asm::"
    identity = np.eye(4)
    for helix in assembly.assembly_helices:
        all_helices.append(_prefix_helix(helix, asm_hp, identity))
    for strand in assembly.assembly_strands:
        all_strands.append(_prefix_strand(strand, asm_hp, asm_hp))

    # Validate ID uniqueness
    helix_ids = [h.id for h in all_helices]
    if len(helix_ids) != len(set(helix_ids)):
        from collections import Counter
        dupes = [hid for hid, cnt in Counter(helix_ids).items() if cnt > 1]
        raise ValueError(f"Flattened design has duplicate helix IDs: {dupes}")

    strand_ids = [s.id for s in all_strands]
    if len(strand_ids) != len(set(strand_ids)):
        from collections import Counter
        dupes = [sid for sid, cnt in Counter(strand_ids).items() if cnt > 1]
        raise ValueError(f"Flattened design has duplicate strand IDs: {dupes}")

    name = assembly.metadata.name or "Assembly"
    return Design(
        id=f"flat_{assembly.id}",
        helices=all_helices,
        strands=all_strands,
        lattice_type=LatticeType.HONEYCOMB,
        metadata=DesignMetadata(name=f"Flattened: {name}"),
    )
