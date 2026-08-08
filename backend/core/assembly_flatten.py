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

from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    pass

from backend.core.assembly_linker import parse_namespaced_helix_id
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
_LIBRARY_DIR = _PROJECT_ROOT / "parts-library"


def _load_design(source) -> Design:
    """Resolve a PartSource to a Design object."""
    if isinstance(source, PartSourceInline):
        return source.design
    if isinstance(source, PartSourceFile):
        # Resolve relative to project root then parts-library
        candidates = [
            _PROJECT_ROOT / source.path,
            _LIBRARY_DIR / source.path,
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
    result = mat4 @ pt  # row-major: M × p
    return Vec3(x=float(result[0]), y=float(result[1]), z=float(result[2]))


def _prefix_helix(helix: Helix, prefix: str, mat4: np.ndarray) -> Helix:
    """Return a copy of helix with prefixed ID and transformed axis."""
    return helix.model_copy(
        update={
            "id": f"{prefix}{helix.id}",
            "axis_start": _transform_vec3(mat4, helix.axis_start),
            "axis_end": _transform_vec3(mat4, helix.axis_end),
        }
    )


def _prefix_domain(domain: Domain, prefix: str) -> Domain:
    """Return a copy of domain with the helix_id (and any overhang_id) prefixed.

    ``overhang_id`` is namespaced in lockstep with the :class:`OverhangSpec` id
    (see :func:`_prefix_overhang`) so a cross-part overhang stays unique in the
    merged Design and ``_find_oh_strand_and_domain`` can locate it for
    materialization."""
    upd = {"helix_id": f"{prefix}{domain.helix_id}"}
    if domain.overhang_id:
        upd["overhang_id"] = f"{prefix}{domain.overhang_id}"
    return domain.model_copy(update=upd)


def _prefix_overhang(overhang, prefix: str):
    """Namespace an :class:`OverhangSpec`'s id + helix_id + strand_id so it stays
    unique across parts in the flattened Design (its ``sub_domains`` are kept)."""
    return overhang.model_copy(
        update={
            "id": f"{prefix}{overhang.id}",
            "helix_id": f"{prefix}{overhang.helix_id}",
            "strand_id": f"{prefix}{overhang.strand_id}",
        }
    )


def _remap_assembly_domain(domain: Domain, real_instance_ids: set[str]) -> Domain:
    """Rewrite an assembly-strand domain's ``helix_id`` for the flattened Design.

    Cross-part linker complement domains (built by
    :func:`backend.core.assembly_linker.generate_assembly_linker_topology`)
    address a *part* helix through the namespaced form ``"<inst_id>::<helix_id>"``
    (see :func:`namespaced_helix_id`). In the flattened Design that helix lives
    under ``"inst-<inst_id>::<helix_id>"`` (the part-instance prefix), so we remap
    the complement onto the REAL flattened part helix instead of blindly adding an
    ``asm::`` prefix — which would produce a dangling ``asm::<inst_id>::<helix_id>``
    reference matching nothing (the pre-2026-07 bug). Binding both the overhang and
    its complement onto the SAME flattened helix also sidesteps LESSONS A4 (no
    separate world-aliased helix to phase-correct).

    Any other assembly-local helix reference (the ``__lnk__`` bridge helix, VSC
    dashed lines, …) keeps the ``asm::`` prefix.
    """
    parsed = parse_namespaced_helix_id(domain.helix_id)
    if parsed is not None and parsed[0] in real_instance_ids:
        inst_id, orig = parsed
        return domain.model_copy(update={"helix_id": f"inst-{inst_id}::{orig}"})
    return domain.model_copy(update={"helix_id": f"asm::{domain.helix_id}"})


def _prefix_strand(strand: Strand, strand_prefix: str, helix_prefix: str) -> Strand:
    """Return a copy of strand with prefixed strand ID and all domain helix_ids."""
    return strand.model_copy(
        update={
            "id": f"{strand_prefix}{strand.id}",
            "domains": [_prefix_domain(d, helix_prefix) for d in strand.domains],
        }
    )


def _prefix_assembly_strand(strand: Strand, real_instance_ids: set[str]) -> Strand:
    """``asm::``-prefix an assembly-level strand, but remap any namespaced
    part-helix domain references onto their flattened part helix (see
    :func:`_remap_assembly_domain`)."""
    return strand.model_copy(
        update={
            "id": f"asm::{strand.id}",
            "domains": [
                _remap_assembly_domain(d, real_instance_ids) for d in strand.domains
            ],
        }
    )


def _materialize_direct_duplexes(assembly: Assembly, flat: Design) -> Design:
    """Relocate the driven overhang of every DIRECT cross-part AssemblyDuplex onto
    the driver's (flattened) helix at the register range, producing real paired
    topology in the merged Design.

    Reuses the PROVEN per-design primitives ``compute_bind_topology`` /
    ``apply_bind_topology`` (a transient ``OverhangBinding`` carries the namespaced
    overhang ids; ``target_*_override`` comes from the driver-side register, so the
    polarity is inherited from the validated per-design path — no cross-part
    reasoning). Exactly mirrors ``backend.core.duplex.relocate_duplex`` but on the
    flattened Design.

    Only ``connection_id``-less duplexes are materialized here — linker complements
    already emit their own strands via ``generate_assembly_linker_topology``. The
    duplex list is derived from ``overhang_bindings`` on demand (a freshly-loaded
    assembly may carry bindings but an empty ``duplexes``). Best-effort: a duplex
    whose overhangs don't resolve or whose relocation raises is skipped (flatten
    must never crash on a stale/garbled pair)."""
    from fastapi import HTTPException

    from backend.core.assembly_duplex import sync_assembly_duplexes_from_bindings
    from backend.core.binding_relax import apply_bind_topology, compute_bind_topology
    from backend.core.models import OverhangBinding

    effective = sync_assembly_duplexes_from_bindings(assembly)
    flat_overhang_ids = {o.id for o in flat.overhangs}
    out = flat
    for dx in effective.duplexes:
        if dx.connection_id is not None:
            continue
        driver_end = dx.left if dx.driver == "left" else dx.right
        driven_end = dx.right if dx.driver == "left" else dx.left
        driver_ns = f"inst-{driver_end.instance_id}::{driver_end.overhang_id}"
        driven_ns = f"inst-{driven_end.instance_id}::{driven_end.overhang_id}"
        if driver_ns not in flat_overhang_ids or driven_ns not in flat_overhang_ids:
            continue
        transient = OverhangBinding(
            name="__asm_duplex_reloc__",
            sub_domain_a_id="a",
            sub_domain_b_id="b",
            overhang_a_id=driver_ns,
            overhang_b_id=driven_ns,
            driver_oh_id=driver_ns,
            driven_oh_id=driven_ns,
        )
        try:
            topo = compute_bind_topology(
                out,
                transient,
                driver_side="a",
                # Antiparallel onto the driver's paired window (mirror the full-
                # domain swap: target_start = window 3' bp, target_end = 5' bp).
                target_start_override=driver_end.end_bp,
                target_end_override=driver_end.start_bp,
            )
            out = apply_bind_topology(out, topo)
        except HTTPException:
            continue
    return out


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
    all_helices: list[Helix] = []
    all_strands: list[Strand] = []
    all_overhangs: list = []

    # Every instance whose helices are emitted below — used to remap the
    # namespaced complement-domain references on assembly linker strands onto
    # their flattened part helix.
    real_instance_ids = {inst.id for inst in assembly.instances if inst.visible}

    for inst in assembly.instances:
        if not inst.visible:
            continue
        try:
            design = _load_design(inst.source)
        except FileNotFoundError:
            continue  # skip missing file sources

        hp = f"inst-{inst.id}::"  # helix/domain prefix
        sp = f"inst-{inst.id}::"  # strand prefix
        mat4 = _mat4_from_values(inst.transform.values)

        for helix in design.helices:
            all_helices.append(_prefix_helix(helix, hp, mat4))

        for strand in design.strands:
            all_strands.append(_prefix_strand(strand, sp, hp))

        for overhang in design.overhangs:
            all_overhangs.append(_prefix_overhang(overhang, hp))

    # Assembly-level helices and strands (linkers, VSC dashed lines)
    asm_hp = "asm::"
    identity = np.eye(4)
    for helix in assembly.assembly_helices:
        all_helices.append(_prefix_helix(helix, asm_hp, identity))
    for strand in assembly.assembly_strands:
        all_strands.append(_prefix_assembly_strand(strand, real_instance_ids))

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
    flat = Design(
        id=f"flat_{assembly.id}",
        helices=all_helices,
        strands=all_strands,
        overhangs=all_overhangs,
        lattice_type=LatticeType.HONEYCOMB,
        metadata=DesignMetadata(name=f"Flattened: {name}"),
    )

    # Materialize direct cross-part Watson-Crick pairs (AssemblyDuplex) into real
    # paired topology in the merged Design — the flatten-time analog of the part
    # editor's `relocate_duplex`. Derived-artifact only: the parts' source
    # topology is untouched (Three-Layer Law).
    return _materialize_direct_duplexes(assembly, flat)
