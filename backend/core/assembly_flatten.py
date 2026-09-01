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
    ForcedLigation,
    Helix,
    LatticeType,
    PartSourceFile,
    PartSourceInline,
    Strand,
    StrandExtension,
    Vec3,
)
from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.sequences import domain_bp_range

# Project root — two levels above this file: core/ → backend/ → root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_LIBRARY_DIR = _PROJECT_ROOT / "parts-library"
_WORKSPACE_DIR = _PROJECT_ROOT / "workspace"


def _load_design(source) -> Design:
    """Resolve a PartSource to a Design object."""
    if isinstance(source, PartSourceInline):
        return source.design
    if isinstance(source, PartSourceFile):
        # Match the assembly API's source semantics: ordinary .nass files store
        # workspace-relative part paths (for example ``BigO.nadoc``).  The old
        # flatten path omitted workspace and silently produced an empty Design.
        raw = Path(source.path)
        candidates = [
            raw,
            _WORKSPACE_DIR / raw,
            _PROJECT_ROOT / raw,
            _LIBRARY_DIR / raw,
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


def _prefix_extension(extension: StrandExtension, prefix: str) -> StrandExtension:
    """Namespace a part's authored terminal extension with its owning strand."""
    return extension.model_copy(update={
        "id": f"{prefix}{extension.id}",
        "strand_id": f"{prefix}{extension.strand_id}",
    })


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


def _strand_slice_sequence(strand: Strand, start: int, stop: int) -> str | None:
    """Sequence belonging to ``strand.domains[start:stop]`` (or ``None``).

    Periodic polymerization staples are split at their seam before being rejoined to a
    neighbouring instance. Keeping the sequence slices with the domain slices prevents a
    cross-instance strand from silently retaining the sequence of only one repeat.
    """
    if strand.sequence is None:
        return None
    offsets = [0]
    for dm in strand.domains:
        offsets.append(offsets[-1] + len(list(domain_bp_range(dm))))
    return strand.sequence[offsets[start] : offsets[stop]]


def _domain_axis_point(design: Design, mat4: np.ndarray, helix_id: str, bp: int) -> np.ndarray:
    """World-space helix-axis point for a seam endpoint."""
    helix = next(h for h in design.helices if h.id == helix_id)
    a = np.array([helix.axis_start.x, helix.axis_start.y, helix.axis_start.z], float)
    b = np.array([helix.axis_end.x, helix.axis_end.y, helix.axis_end.z], float)
    axis = b - a
    unit = axis / (np.linalg.norm(axis) or 1.0)
    local = a + unit * ((bp - helix.bp_start) * BDNA_RISE_PER_BP)
    return (mat4 @ np.array([*local, 1.0]))[:3]


def _periodic_owner(design: Design, seam: ForcedLigation) -> tuple[Strand, int] | None:
    """Return ``(strand, cut)`` whose domain transition is the periodic seam.

    ``cut`` is the first domain on the seam's 5' side. This intentionally requires an
    exact 3'-domain-end → 5'-domain-start match: a scaffold can cover both endpoint
    coordinates without being the polymerization staple that crosses the seam.
    """
    for strand in design.strands:
        for cut in range(1, len(strand.domains)):
            left, right = strand.domains[cut - 1], strand.domains[cut]
            if (
                left.helix_id == seam.three_prime_helix_id
                and left.end_bp == seam.three_prime_bp
                and left.direction == seam.three_prime_direction
                and right.helix_id == seam.five_prime_helix_id
                and right.start_bp == seam.five_prime_bp
                and right.direction == seam.five_prime_direction
            ):
                return strand, cut
    return None


def _materialize_periodic_strands(
    assembly: Assembly,
    instance_designs: dict[str, Design],
    instance_mats: dict[str, np.ndarray],
    helices: list[Helix],
    strands: list[Strand],
    overhangs: list,
    extensions: list[StrandExtension],
) -> tuple[list[Helix], list[Strand], list, list[StrandExtension], list[ForcedLigation]]:
    """Replace within-repeat periodic jumps with physical inter-repeat strands.

    A periodic part stores each polymerization staple as ``far-domain → near-domain``
    inside one Design. Literal instance copying therefore draws a covalent jump across the
    *same* origami. Assembly seam joints instead pair the far fragment of one repeat with
    the near fragment of its neighbour. The two unused boundary fragments are retained as
    full-length staples by supplying their missing half as an explicitly tagged ssDNA tail.

    Returns additional forced ligations for the cross-instance domain transitions. They are
    topology records (and are consumed by the FEM); terminal tail transitions are already
    present in the strand path but do not join two duplex FEM nodes.
    """
    periodic_joints = [
        j for j in assembly.joints
        if j.connector_a_label == "seam0:3p" and j.connector_b_label == "seam0:5p"
        and j.instance_a_id in instance_designs and j.instance_b_id in instance_designs
    ]
    if not periodic_joints:
        return helices, strands, overhangs, extensions, []

    visible_ids = set(instance_designs)
    neighbour_ids: dict[str, set[str]] = {iid: set() for iid in visible_ids}
    for joint in periodic_joints:
        neighbour_ids[joint.instance_a_id].add(joint.instance_b_id)
        neighbour_ids[joint.instance_b_id].add(joint.instance_a_id)

    # Process a seam signature once. Periodic copies share a source Design; the signature
    # remains stable even when instance IDs and strand IDs are namespaced.
    signatures: dict[tuple, ForcedLigation] = {}
    for design in instance_designs.values():
        for seam in design.forced_ligations:
            if seam.is_periodic_seam:
                sig = (
                    seam.three_prime_helix_id, seam.three_prime_bp,
                    seam.three_prime_direction.value, seam.five_prime_helix_id,
                    seam.five_prime_bp, seam.five_prime_direction.value,
                )
                signatures.setdefault(sig, seam)

    added_strands: list[Strand] = []
    added_extensions: list[StrandExtension] = []
    added_ligations: list[ForcedLigation] = []
    remove_ids: set[str] = set()

    for seam_idx, seam in enumerate(signatures.values()):
        fragments: dict[tuple[str, str], dict] = {}
        for iid, design in instance_designs.items():
            owned = _periodic_owner(design, seam)
            if owned is None:
                continue
            source, cut = owned
            remove_ids.add(f"inst-{iid}::{source.id}")
            hp = f"inst-{iid}::"
            for side, lo, hi in (("pre", 0, cut), ("post", cut, len(source.domains))):
                fragments[(iid, side)] = {
                    "source": source,
                    "domains": [_prefix_domain(d, hp) for d in source.domains[lo:hi]],
                    "sequence": _strand_slice_sequence(source, lo, hi),
                }

        used: set[tuple[str, str]] = set()
        for joint_idx, joint in enumerate(periodic_joints):
            a, b = joint.instance_a_id, joint.instance_b_id
            if not all((iid, side) in fragments for iid in (a, b) for side in ("pre", "post")):
                continue
            da, db = instance_designs[a], instance_designs[b]
            ma, mb = instance_mats[a], instance_mats[b]
            # Strand polarity alternates across a bundle. Select the direction whose actual
            # 3'/5' axis points meet at this physical joint; for reverse strands this is
            # B(3') → A(5'), not the assembly joint record's aggregate A→B label.
            options = [
                (a, b, np.linalg.norm(
                    _domain_axis_point(da, ma, seam.three_prime_helix_id, seam.three_prime_bp)
                    - _domain_axis_point(db, mb, seam.five_prime_helix_id, seam.five_prime_bp)
                )),
                (b, a, np.linalg.norm(
                    _domain_axis_point(db, mb, seam.three_prime_helix_id, seam.three_prime_bp)
                    - _domain_axis_point(da, ma, seam.five_prime_helix_id, seam.five_prime_bp)
                )),
            ]
            three_iid, five_iid, _ = min(options, key=lambda row: row[2])
            pre, post = fragments[(three_iid, "pre")], fragments[(five_iid, "post")]
            if (three_iid, "pre") in used or (five_iid, "post") in used:
                continue
            used.update(((three_iid, "pre"), (five_iid, "post")))
            source = pre["source"]
            sid = f"polymer::{seam_idx}::{joint.id}"
            seq = None if pre["sequence"] is None or post["sequence"] is None else pre["sequence"] + post["sequence"]
            domains = [*pre["domains"], *post["domains"]]
            added_strands.append(source.model_copy(update={"id": sid, "domains": domains, "sequence": seq}))
            left, right = domains[len(pre["domains"]) - 1], domains[len(pre["domains"])]
            added_ligations.append(ForcedLigation(
                id=f"polymer-ligation::{seam_idx}::{joint.id}",
                three_prime_helix_id=left.helix_id, three_prime_bp=left.end_bp,
                three_prime_direction=left.direction,
                five_prime_helix_id=right.helix_id, five_prime_bp=right.start_bp,
                five_prime_direction=right.direction,
            ))

        # Exactly two fragments remain per open chain and seam. Complete each strand with
        # the missing sequence as a real StrandExtension.  This is deliberately NOT a
        # synthetic one-strand Helix/Domain: all-atom preparation has dedicated terminal
        # ssDNA placement which roots the tail on C3'/C5', repairs each phosphodiester,
        # and threads residues in chemical order.  Treating the tail like duplex DNA
        # bypassed that path and produced ring-pierced NAMD seeds at polymer ends.
        for (iid, side), fragment in fragments.items():
            if (iid, side) in used:
                continue
            other = fragments[(iid, "post" if side == "pre" else "pre")]
            tail_sid = f"polymer-terminal::{seam_idx}::{iid}::{side}"
            own_seq, missing_seq = fragment["sequence"], other["sequence"]
            # Unknown source sequence stays explicit as N bases: every simulation
            # engine can include the physical tail while still reporting undefined
            # chemistry through its normal sequence validation.
            if missing_seq is None:
                tail_n = sum(len(list(domain_bp_range(d))) for d in other["domains"])
                missing_seq = "N" * max(1, tail_n)
            source = fragment["source"]
            added_strands.append(source.model_copy(update={
                "id": tail_sid,
                "domains": fragment["domains"],
                "sequence": own_seq,
            }))
            added_extensions.append(StrandExtension(
                id=f"polymer-extension::{seam_idx}::{iid}::{side}",
                strand_id=tail_sid,
                end="three_prime" if side == "pre" else "five_prime",
                sequence=missing_seq,
                label="Polymer end",
            ))

    if not remove_ids:
        return helices, strands, overhangs, extensions, []
    return (
        helices,
        [s for s in strands if s.id not in remove_ids] + added_strands,
        overhangs,
        [*extensions, *added_extensions],
        added_ligations,
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
    all_extensions: list[StrandExtension] = []
    instance_designs: dict[str, Design] = {}
    instance_mats: dict[str, np.ndarray] = {}

    # Every instance whose helices are emitted below — used to remap the
    # namespaced complement-domain references on assembly linker strands onto
    # their flattened part helix.
    real_instance_ids = {inst.id for inst in assembly.instances if inst.visible}

    for inst in assembly.instances:
        if not inst.visible:
            continue
        # A visible missing part must abort flattening. Silently omitting it can
        # launch a scientifically meaningless partial/empty simulation while the
        # assembly viewport still shows the complete structure.
        design = _load_design(inst.source)
        instance_designs[inst.id] = design

        hp = f"inst-{inst.id}::"  # helix/domain prefix
        sp = f"inst-{inst.id}::"  # strand prefix
        mat4 = _mat4_from_values(inst.transform.values)
        instance_mats[inst.id] = mat4

        for helix in design.helices:
            all_helices.append(_prefix_helix(helix, hp, mat4))

        for strand in design.strands:
            all_strands.append(_prefix_strand(strand, sp, hp))

        for overhang in design.overhangs:
            all_overhangs.append(_prefix_overhang(overhang, hp))
        for extension in design.extensions:
            all_extensions.append(_prefix_extension(extension, sp))

    # Assembly-level helices and strands (linkers, VSC dashed lines)
    asm_hp = "asm::"
    identity = np.eye(4)
    for helix in assembly.assembly_helices:
        all_helices.append(_prefix_helix(helix, asm_hp, identity))
    for strand in assembly.assembly_strands:
        all_strands.append(_prefix_assembly_strand(strand, real_instance_ids))

    all_helices, all_strands, all_overhangs, all_extensions, periodic_ligations = _materialize_periodic_strands(
        assembly, instance_designs, instance_mats, all_helices, all_strands,
        all_overhangs, all_extensions,
    )

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
        extensions=all_extensions,
        forced_ligations=periodic_ligations,
        lattice_type=LatticeType.HONEYCOMB,
        # This is a derived simulation projection, but its user-facing identity
        # remains the assembly name. Provenance is already explicit in the flat_ id.
        metadata=DesignMetadata(name=name),
    )

    # Materialize direct cross-part Watson-Crick pairs (AssemblyDuplex) into real
    # paired topology in the merged Design — the flatten-time analog of the part
    # editor's `relocate_duplex`. Derived-artifact only: the parts' source
    # topology is untouched (Three-Layer Law).
    return _materialize_direct_duplexes(assembly, flat)
