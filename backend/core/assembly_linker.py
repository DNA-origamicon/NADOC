"""
Cross-part linker topology generation for AssemblyOverhangConnection.

The per-design ``generate_linker_topology`` in
:mod:`backend.core.lattice` produces complement domains + a virtual
``__lnk__`` helix + bridge strand(s) within a single :class:`Design`. This
module mirrors that for the cross-part case: the two overhangs sit on
different ``PartInstance`` designs, so the linker is materialised on the
:class:`Assembly` itself (``assembly_helices`` + ``assembly_strands``) and
the complement domains reference *namespaced* helix ids
(``"<inst_id>::<orig_helix_id>"``) — the synthetic-design pass in
``GET /assembly/linker-geometry`` rebuilds world-space alias helices under
those ids so the geometry pipeline can resolve the lookups.

The strand sequence is assembled at generation time (composed from each
side's overhang sequence + the user-typed ``bridge_sequence``) so the
spreadsheet panel can render it directly without re-walking the topology.
"""

from __future__ import annotations

from typing import Optional, Tuple

import numpy as np

from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.lattice import (
    _LINKER_HELIX_PREFIX,
    _LINKER_DEFAULT_COLOR,
    _find_overhang_domain,
    _is_comp_first,
    _length_value_to_bp,
    _make_complement_domain,
    _opposite_direction,
)
from backend.core.linker_relax import bridge_axis_geometry
from backend.core.models import (
    Direction,
    Domain,
    Helix,
    Strand,
    StrandType,
    Vec3,
)


_NAMESPACE_SEP = "::"


def namespaced_helix_id(instance_id: str, helix_id: str) -> str:
    """Helix id used by cross-part complement domains.

    The original part-design helix id stays unchanged on the part itself;
    the assembly stores a *world-space alias* under this namespaced id, and
    the complement domain references the alias so its bead positions are
    computed in world space (with the instance's placement transform
    applied)."""
    return f"{instance_id}{_NAMESPACE_SEP}{helix_id}"


def parse_namespaced_helix_id(helix_id: str) -> Optional[Tuple[str, str]]:
    """Inverse of :func:`namespaced_helix_id`, or ``None`` if not namespaced."""
    if _NAMESPACE_SEP not in helix_id:
        return None
    inst_id, _, orig = helix_id.partition(_NAMESPACE_SEP)
    if not inst_id or not orig:
        return None
    return inst_id, orig


_COMPLEMENT = {
    "A": "T", "T": "A", "C": "G", "G": "C",
    "a": "t", "t": "a", "c": "g", "g": "c",
    "N": "N", "n": "n",
    "U": "A", "u": "a",
}


def reverse_complement(seq: Optional[str], length: int) -> str:
    """Reverse-complement *seq*, padding to *length* with N when shorter.

    Unrecognised characters are mapped to N. Empty / None input yields an
    all-N string of the target length."""
    s = seq or ""
    if len(s) < length:
        s = "N" * (length - len(s)) + s
    elif len(s) > length:
        s = s[:length]
    return "".join(_COMPLEMENT.get(c, "N") for c in reversed(s))


def _bridge_sequence_padded(raw: Optional[str], length: int) -> str:
    s = raw or ""
    if len(s) < length:
        s = s + "N" * (length - len(s))
    elif len(s) > length:
        s = s[:length]
    return s.upper().replace("U", "T")


def _oh_sequence_for_domain(design, ovhg_id: str, oh_dom: Optional[Domain]) -> str:
    """Return the overhang's stored sequence aligned to ``oh_dom``'s bp range.

    The OverhangSpec carries the user-typed sequence in 5'→3' order along
    the OH strand. For the bp range of the OH domain we return the slice
    aligned to ``start_bp..end_bp`` traversal. When the OH has no sequence
    set we return all-N at the domain length so RC composition still has a
    well-defined length.
    """
    if oh_dom is None:
        return ""
    length = abs(oh_dom.end_bp - oh_dom.start_bp) + 1
    seq: Optional[str] = None
    for o in (design.overhangs or []):
        if o.id == ovhg_id:
            seq = o.sequence
            break
    if not seq:
        return "N" * length
    seq = seq.upper().replace("U", "T")
    if len(seq) < length:
        return seq + "N" * (length - len(seq))
    return seq[:length]


def _world_axes_for_helix(helix: Helix, transform: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Apply a row-major 4x4 instance transform to a helix's axis endpoints."""
    s = np.array([helix.axis_start.x, helix.axis_start.y, helix.axis_start.z, 1.0])
    e = np.array([helix.axis_end.x, helix.axis_end.y, helix.axis_end.z, 1.0])
    ws = transform @ s
    we = transform @ e
    return ws[:3], we[:3]


def _world_anchor(design, instance, ovhg_id: str, attach: str, oh_dom: Optional[Domain]) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    """World-space (position, base_normal) at the overhang's attach end.

    ``attach='free_end'`` → overhang free-tip bp; ``attach='root'`` →
    OH-crossover bp. Mirrors :func:`backend.core.lattice._linker_anchor_nuc`
    but operates in the *instance frame* and then applies the part instance's
    placement matrix to push the result into world space.
    """
    if oh_dom is None:
        return None
    helix = design.find_helix(oh_dom.helix_id)
    if helix is None:
        return None

    from backend.core.deformation import deformed_nucleotide_arrays

    tip_bp  = oh_dom.end_bp if ovhg_id.endswith("_3p") else oh_dom.start_bp
    root_bp = oh_dom.start_bp if tip_bp == oh_dom.end_bp else oh_dom.end_bp
    bp      = tip_bp if attach == "free_end" else root_bp
    direction = _opposite_direction(oh_dom.direction)
    arrs = deformed_nucleotide_arrays(helix, design)
    bp_arr  = arrs["bp_indices"]
    dir_arr = arrs["directions"]
    dir_int = 0 if direction == Direction.FORWARD else 1
    matches = (bp_arr == bp) & (dir_arr == dir_int)
    if not matches.any():
        return None
    i = int(matches.argmax())
    pos_local    = np.asarray(arrs["positions"][i], dtype=float)
    normal_local = np.asarray(arrs["base_normals"][i], dtype=float)

    T = instance.transform.to_array()
    pos_world = (T @ np.array([pos_local[0], pos_local[1], pos_local[2], 1.0]))[:3]
    # Normals transform by the rotation block (no translation).
    R = T[:3, :3]
    normal_world = R @ normal_local
    return pos_world, normal_world


def _build_complement_namespaced(oh_dom: Domain, instance_id: str) -> Domain:
    """Antiparallel complement of *oh_dom*, addressed by namespaced helix id."""
    return Domain(
        helix_id=namespaced_helix_id(instance_id, oh_dom.helix_id),
        start_bp=oh_dom.end_bp,
        end_bp=oh_dom.start_bp,
        direction=_opposite_direction(oh_dom.direction),
    )


def _make_bridge_domain(bridge_helix_id: str, side: str, comp_first: bool, linker_bp: int) -> Domain:
    """Bridge half whose complement-side end lands at the side's __lnk__ bp.

    Mirrors :func:`backend.core.lattice.generate_linker_topology`'s inner
    ``_make_bridge_domain`` — kept in sync because the bridge direction
    choice is the only thing telling the geometry emitter which end of the
    virtual helix is which side."""
    L = linker_bp
    if side == "a":
        if comp_first:
            return Domain(helix_id=bridge_helix_id, start_bp=0, end_bp=L - 1, direction=Direction.FORWARD)
        return Domain(helix_id=bridge_helix_id, start_bp=L - 1, end_bp=0, direction=Direction.REVERSE)
    if comp_first:
        return Domain(helix_id=bridge_helix_id, start_bp=L - 1, end_bp=0, direction=Direction.REVERSE)
    return Domain(helix_id=bridge_helix_id, start_bp=0, end_bp=L - 1, direction=Direction.FORWARD)


def _make_world_virtual_linker_helix(
    helix_id: str,
    linker_bp: int,
    pos_a: np.ndarray,
    normal_a: np.ndarray,
    pos_b: np.ndarray,
    comp_first_a: bool,
    comp_first_b: bool,
) -> Helix:
    """Virtual ``__lnk__`` helix placed in world space between the two anchors."""
    axis_start: Optional[np.ndarray]
    axis_end:   Optional[np.ndarray]
    try:
        g = bridge_axis_geometry(pos_a, normal_a, pos_b, linker_bp, comp_first_a, comp_first_b)
        axis_start = g["axis_start"]
        axis_end   = g["axis_end"]
    except Exception:
        chord = pos_b - pos_a
        cl = float(np.linalg.norm(chord))
        if cl < 1e-9:
            axis_start = pos_a.copy()
            axis_end   = pos_a + np.array([0.0, 0.0, max(linker_bp - 1, 1) * BDNA_RISE_PER_BP])
        else:
            visual = max(linker_bp - 1, 1) * BDNA_RISE_PER_BP
            mid = (pos_a + pos_b) * 0.5
            dirn = chord / cl
            axis_start = mid - dirn * (visual * 0.5)
            axis_end   = mid + dirn * (visual * 0.5)
    return Helix(
        id=helix_id,
        axis_start=Vec3.from_array(axis_start),
        axis_end=Vec3.from_array(axis_end),
        phase_offset=0.0,
        length_bp=linker_bp,
    )


def _compose_ds_strand_sequence(
    *,
    side: str,
    comp_first: bool,
    oh_seq: str,
    bridge_seq: str,
) -> str:
    """Per-strand sequence for one side of a ds linker.

    The strand carries the antiparallel complement of the OH bp range plus a
    *bridge half* on the virtual ``__lnk__`` helix:
      comp-first → ``[complement, bridge]`` (concatenated 5'→3')
      bridge-first → ``[bridge, complement]``
    The two strands span the SAME bridge bp range in opposite directions, so
    side B's bridge half reads as the reverse-complement of the user-typed
    ``bridge_sequence`` (which is in side A's 5'→3' order).
    """
    comp = reverse_complement(oh_seq, len(oh_seq))
    if side == "a":
        bridge_half = bridge_seq
    else:
        bridge_half = reverse_complement(bridge_seq, len(bridge_seq))
    return (comp + bridge_half) if comp_first else (bridge_half + comp)


def _compose_ss_strand_sequence(
    *,
    oh_a_seq: str,
    oh_b_seq: str,
    bridge_seq: str,
) -> str:
    """Single-strand sequence for an ss linker: ``RC(OH_A) + bridge + RC(OH_B)``.

    The ss linker has one strand traversing the two complements with the
    bridge between them (see ``_build_ss_linker_strand`` in
    :mod:`backend.core.lattice`)."""
    return reverse_complement(oh_a_seq, len(oh_a_seq)) + bridge_seq + reverse_complement(oh_b_seq, len(oh_b_seq))


def generate_assembly_linker_topology(
    conn,
    inst_a,
    inst_b,
    design_a,
    design_b,
) -> Tuple[list[Helix], list[Strand]]:
    """Build the helix + strand objects implementing a cross-part linker.

    Returns ``(new_helices, new_strands)`` — the caller appends each list to
    ``assembly.assembly_helices`` / ``assembly.assembly_strands`` inside a
    single ``model_copy(update=...)`` so the mutation is atomic.

    A zero-length linker (``length_value == 0`` — used by 'indirect'
    variants in the frontend) generates no topology; the connection is
    still recorded as metadata on the assembly.
    """
    if conn.length_value == 0:
        return [], []

    linker_bp = _length_value_to_bp(conn.length_value, conn.length_unit)
    bridge_helix_id = f"{_LINKER_HELIX_PREFIX}{conn.id}"

    oh_a_dom = _find_overhang_domain(design_a, conn.overhang_a_id)
    oh_b_dom = _find_overhang_domain(design_b, conn.overhang_b_id)

    anchor_a = _world_anchor(design_a, inst_a, conn.overhang_a_id, conn.overhang_a_attach, oh_a_dom)
    anchor_b = _world_anchor(design_b, inst_b, conn.overhang_b_id, conn.overhang_b_attach, oh_b_dom)
    if anchor_a is not None and anchor_b is not None:
        pos_a, n_a = anchor_a
        pos_b, _   = anchor_b
    else:
        pos_a = np.array([0.0, 0.0, 0.0])
        n_a   = np.array([1.0, 0.0, 0.0])
        pos_b = np.array([0.0, 0.0, max(linker_bp - 1, 1) * BDNA_RISE_PER_BP])

    comp_first_a = _is_comp_first(conn.overhang_a_id, conn.overhang_a_attach) if oh_a_dom is not None else True
    comp_first_b = _is_comp_first(conn.overhang_b_id, conn.overhang_b_attach) if oh_b_dom is not None else True

    bridge_helix = _make_world_virtual_linker_helix(
        bridge_helix_id, linker_bp,
        pos_a, n_a, pos_b,
        comp_first_a, comp_first_b,
    )

    bridge_seq = _bridge_sequence_padded(conn.bridge_sequence, linker_bp)
    oh_a_seq   = _oh_sequence_for_domain(design_a, conn.overhang_a_id, oh_a_dom)
    oh_b_seq   = _oh_sequence_for_domain(design_b, conn.overhang_b_id, oh_b_dom)

    new_strands: list[Strand] = []

    if conn.linker_type == "ds":
        for side, oh_id, attach, oh_dom, inst, comp_first, oh_seq in (
            ("a", conn.overhang_a_id, conn.overhang_a_attach, oh_a_dom, inst_a, comp_first_a, oh_a_seq),
            ("b", conn.overhang_b_id, conn.overhang_b_attach, oh_b_dom, inst_b, comp_first_b, oh_b_seq),
        ):
            comp = _build_complement_namespaced(oh_dom, inst.id) if oh_dom is not None else None
            bridge = _make_bridge_domain(bridge_helix_id, side, comp_first, linker_bp)
            if comp is None:
                domains = [bridge]
            elif comp_first:
                domains = [comp, bridge]
            else:
                domains = [bridge, comp]
            seq = _compose_ds_strand_sequence(
                side=side, comp_first=comp_first, oh_seq=oh_seq, bridge_seq=bridge_seq,
            )
            new_strands.append(Strand(
                id=f"{_LINKER_HELIX_PREFIX}{conn.id}__{side}",
                domains=domains,
                strand_type=StrandType.LINKER,
                color=_LINKER_DEFAULT_COLOR,
                sequence=seq,
            ))
    else:
        comp_a = _build_complement_namespaced(oh_a_dom, inst_a.id) if oh_a_dom is not None else None
        comp_b = _build_complement_namespaced(oh_b_dom, inst_b.id) if oh_b_dom is not None else None
        bridge = Domain(
            helix_id=bridge_helix_id,
            start_bp=0,
            end_bp=linker_bp - 1,
            direction=Direction.FORWARD,
        )
        domains = []
        if comp_a is not None: domains.append(comp_a)
        domains.append(bridge)
        if comp_b is not None: domains.append(comp_b)
        seq = _compose_ss_strand_sequence(
            oh_a_seq=oh_a_seq, oh_b_seq=oh_b_seq, bridge_seq=bridge_seq,
        )
        new_strands.append(Strand(
            id=f"{_LINKER_HELIX_PREFIX}{conn.id}__s",
            domains=domains,
            strand_type=StrandType.LINKER,
            color=_LINKER_DEFAULT_COLOR,
            sequence=seq,
        ))

    return [bridge_helix], new_strands


def remove_assembly_linker_topology(
    existing_helices: list[Helix],
    existing_strands: list[Strand],
    conn_id: str,
) -> Tuple[list[Helix], list[Strand]]:
    """Drop every helix and strand whose id starts with ``__lnk__<conn_id>``."""
    prefix = f"{_LINKER_HELIX_PREFIX}{conn_id}"
    new_helices = [h for h in existing_helices if not h.id.startswith(prefix)]
    new_strands = [s for s in existing_strands if not s.id.startswith(prefix)]
    return new_helices, new_strands


def recompose_strand_sequences_for_connection(
    conn,
    inst_a,
    inst_b,
    design_a,
    design_b,
    existing_strands: list[Strand],
) -> list[Strand]:
    """Update the ``.sequence`` field on every ``__lnk__<conn.id>__*`` strand.

    Used by PATCH on bridge_sequence / overhang sequence changes — topology
    stays the same, only the sequence string needs to be re-composed.
    """
    if not existing_strands:
        return existing_strands

    prefix = f"{_LINKER_HELIX_PREFIX}{conn.id}__"
    if not any(s.id.startswith(prefix) for s in existing_strands):
        return existing_strands

    linker_bp = _length_value_to_bp(conn.length_value, conn.length_unit) if conn.length_value > 0 else 0
    oh_a_dom = _find_overhang_domain(design_a, conn.overhang_a_id)
    oh_b_dom = _find_overhang_domain(design_b, conn.overhang_b_id)
    bridge_seq = _bridge_sequence_padded(conn.bridge_sequence, linker_bp)
    oh_a_seq   = _oh_sequence_for_domain(design_a, conn.overhang_a_id, oh_a_dom)
    oh_b_seq   = _oh_sequence_for_domain(design_b, conn.overhang_b_id, oh_b_dom)
    comp_first_a = _is_comp_first(conn.overhang_a_id, conn.overhang_a_attach) if oh_a_dom is not None else True
    comp_first_b = _is_comp_first(conn.overhang_b_id, conn.overhang_b_attach) if oh_b_dom is not None else True

    updated: list[Strand] = []
    for s in existing_strands:
        if not s.id.startswith(prefix):
            updated.append(s)
            continue
        if s.id.endswith("__a"):
            seq = _compose_ds_strand_sequence(
                side="a", comp_first=comp_first_a, oh_seq=oh_a_seq, bridge_seq=bridge_seq,
            )
        elif s.id.endswith("__b"):
            seq = _compose_ds_strand_sequence(
                side="b", comp_first=comp_first_b, oh_seq=oh_b_seq, bridge_seq=bridge_seq,
            )
        elif s.id.endswith("__s"):
            seq = _compose_ss_strand_sequence(
                oh_a_seq=oh_a_seq, oh_b_seq=oh_b_seq, bridge_seq=bridge_seq,
            )
        else:
            updated.append(s)
            continue
        updated.append(s.model_copy(update={"sequence": seq}))
    return updated
