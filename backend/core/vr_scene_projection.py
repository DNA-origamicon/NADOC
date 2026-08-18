"""Pure, representation-specific projections shared by the native VR snapshot.

Topology and residue placement remain owned by the regular NADOC model and geometry
modules. This module only converts those authoritative records into Full-view primitive
poses; keeping that conversion pure makes numeric desktop/VR parity testable without an
OpenXR runtime.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from backend.core.atomistic_helpers import crossover_extra_base_placements
from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.linker_relax import linker_anchor_nucleotide


@dataclass(frozen=True, slots=True)
class CrossoverExtraBaseFullProjection:
    """One crossover-insert bead, slab, and bead-to-slab attachment pose."""

    geometric_index: int
    sim_k: int
    base: str
    bead_center: np.ndarray
    slab_center: np.ndarray
    slab_axis_x: np.ndarray
    slab_axis_y: np.ndarray
    slab_axis_z: np.ndarray
    slab_corner: np.ndarray


@dataclass(frozen=True, slots=True)
class LinkerSlabProjection:
    """One ssDNA linker base slab in the desktop Full representation."""

    bead_center: np.ndarray
    slab_center: np.ndarray
    slab_axis_x: np.ndarray
    slab_axis_y: np.ndarray
    slab_axis_z: np.ndarray


@dataclass(frozen=True, slots=True)
class SsLinkerProjection:
    """Visible ssDNA linker beads/slabs plus its thin backbone path."""

    strand_id: str
    bases: tuple[LinkerSlabProjection, ...]
    backbone_points: tuple[np.ndarray, ...]


@dataclass(frozen=True, slots=True)
class DsLinkerConnectorProjection:
    """One short arc from an overhang anchor to a dsDNA bridge boundary."""

    strand_id: str
    points: tuple[np.ndarray, ...]


def _unit(vector: np.ndarray, fallback: np.ndarray) -> np.ndarray:
    length = float(np.linalg.norm(vector))
    if length < 1e-9:
        return np.asarray(fallback, dtype=float).copy()
    return vector / length


def _quadratic_point(
    first: np.ndarray, control: np.ndarray, second: np.ndarray, t: float
) -> np.ndarray:
    u = 1.0 - t
    return u * u * first + 2.0 * u * t * control + t * t * second


def _quadratic_tangent(
    first: np.ndarray, control: np.ndarray, second: np.ndarray, t: float
) -> np.ndarray:
    tangent = 2.0 * (1.0 - t) * (control - first) + 2.0 * t * (second - control)
    return _unit(tangent, second - first)


def _quadratic_samples(
    first: np.ndarray,
    control: np.ndarray,
    second: np.ndarray,
    *,
    segments: int = 48,
) -> tuple[np.ndarray, ...]:
    return tuple(
        _quadratic_point(first, control, second, i / segments)
        for i in range(segments + 1)
    )


def _linker_length_to_bases(conn) -> int:
    value = float(getattr(conn, "length_value", 0.0))
    if value <= 0:
        return 0
    if getattr(conn, "length_unit", "bp") == "nm":
        return max(1, round(value / BDNA_RISE_PER_BP))
    return max(1, round(value))


def _anchor(nucleotides: list[dict], conn, *, is_a_side: bool) -> dict | None:
    overhang_id = conn.overhang_a_id if is_a_side else conn.overhang_b_id
    return linker_anchor_nucleotide(nucleotides, conn, overhang_id, is_a_side)


def _position(nucleotide: dict | None) -> np.ndarray | None:
    if nucleotide is None:
        return None
    value = nucleotide.get("backbone_position") or nucleotide.get("base_position")
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return None
    result = np.asarray(value, dtype=float)
    return result if np.all(np.isfinite(result)) else None


def _ss_control_and_normal(
    first: np.ndarray,
    second: np.ndarray,
    first_nucleotide: dict,
    second_nucleotide: dict,
) -> tuple[np.ndarray, np.ndarray]:
    """Mirror the framed Bezier setup in ``overhang_link_arcs.js``."""
    has_frames = all(
        isinstance(nucleotide.get(field), (list, tuple)) and len(nucleotide[field]) == 3
        for nucleotide in (first_nucleotide, second_nucleotide)
        for field in ("axis_tangent", "base_normal")
    )
    chord = second - first
    distance = float(np.linalg.norm(chord))
    if has_frames:
        chord_direction = _unit(chord, np.array([1.0, 0.0, 0.0]))
        helix_axis = _unit(
            np.asarray(first_nucleotide["axis_tangent"], dtype=float)
            + np.asarray(second_nucleotide["axis_tangent"], dtype=float),
            np.array([0.0, 0.0, 1.0]),
        )
        bow = np.cross(chord_direction, helix_axis)
        bow = _unit(bow, helix_axis)
        control = (first + second) * 0.5 + bow * distance * 0.30
        slab_normal = np.asarray(first_nucleotide["base_normal"], dtype=float)
        slab_normal += np.asarray(second_nucleotide["base_normal"], dtype=float)
        slab_normal = _unit(
            slab_normal, np.asarray(first_nucleotide["base_normal"], dtype=float)
        )
        return control, slab_normal

    up = np.array([0.0, 0.0, 1.0])
    perpendicular = np.cross(chord, up)
    if float(np.dot(perpendicular, perpendicular)) < 1e-6:
        perpendicular = np.cross(chord, np.array([1.0, 0.0, 0.0]))
    perpendicular = _unit(perpendicular, np.array([0.0, 1.0, 0.0]))
    control = (first + second) * 0.5 + perpendicular * distance * 0.30
    slab_normal = _unit(2.0 * control - first - second, perpendicular)
    return control, slab_normal


def _desktop_fjc_positions(
    base_count: int, first: np.ndarray, second: np.ndarray, bin_index: int
) -> np.ndarray | None:
    """Map an FJC representative exactly like frontend ``transformToChord``.

    The older general Python helper currently rotates without the desktop's
    longitudinal stretch. This projection-local transform intentionally keeps
    VR visual parity without changing linker optimization or persisted state.
    """
    from backend.core import ssdna_fjc

    if not ssdna_fjc.has_entry(base_count):
        return None
    canonical = ssdna_fjc.bin_positions(base_count, bin_index).copy()
    r_ee = ssdna_fjc.bin_r_ee(base_count, bin_index)
    chord = second - first
    chord_length = float(np.linalg.norm(chord))
    if r_ee < 1e-9 or chord_length < 1e-9:
        return np.repeat(first[None, :], base_count, axis=0)
    canonical[:, 0] *= chord_length / r_ee
    target = chord / chord_length
    source = np.array([1.0, 0.0, 0.0])
    cross = np.cross(source, target)
    sine = float(np.linalg.norm(cross))
    cosine = float(np.dot(source, target))
    if sine < 1e-12:
        rotation = np.identity(3) if cosine > 0 else np.diag([-1.0, -1.0, 1.0])
    else:
        axis = cross / sine
        skew = np.array(
            [
                [0.0, -axis[2], axis[1]],
                [axis[2], 0.0, -axis[0]],
                [-axis[1], axis[0], 0.0],
            ]
        )
        rotation = np.identity(3) + sine * skew + (1.0 - cosine) * (skew @ skew)
    return canonical @ rotation.T + first


def ss_linker_projection(nucleotides: list[dict], conn) -> SsLinkerProjection | None:
    """Project one ssDNA overhang connection using desktop geometry rules."""
    base_count = _linker_length_to_bases(conn)
    first_nucleotide = _anchor(nucleotides, conn, is_a_side=True)
    second_nucleotide = _anchor(nucleotides, conn, is_a_side=False)
    first, second = _position(first_nucleotide), _position(second_nucleotide)
    if first is None or second is None:
        return None
    control, slab_normal = _ss_control_and_normal(
        first, second, first_nucleotide, second_nucleotide
    )
    bead_centers = None
    if bool(getattr(conn, "bridge_relaxed", False)) and base_count > 0:
        bead_centers = _desktop_fjc_positions(
            base_count,
            first,
            second,
            int(getattr(conn, "bridge_bin_index", 0) or 0),
        )
    if bead_centers is None:
        bead_centers = np.asarray(
            [
                _quadratic_point(first, control, second, i / (base_count + 1))
                for i in range(1, base_count + 1)
            ]
        )
        tangents = [
            _quadratic_tangent(first, control, second, i / (base_count + 1))
            for i in range(1, base_count + 1)
        ]
        backbone = _quadratic_samples(first, control, second)
    else:
        tangents = []
        for index in range(base_count):
            if base_count == 1:
                tangent = second - first
            elif index == 0:
                tangent = bead_centers[1] - bead_centers[0]
            elif index == base_count - 1:
                tangent = bead_centers[index] - bead_centers[index - 1]
            else:
                tangent = bead_centers[index + 1] - bead_centers[index - 1]
            tangents.append(_unit(tangent, second - first))
        # The desktop smooths these sites with centripetal Catmull-Rom. The
        # native scene uses short cylinders, so the canonical sites form the
        # non-invented path and preserve every selected FJC bend.
        backbone = tuple(np.asarray(point, dtype=float) for point in bead_centers)

    bases = []
    for center, tangent in zip(bead_centers, tangents):
        tangent = _unit(tangent, second - first)
        long_axis = np.cross(tangent, slab_normal)
        if float(np.linalg.norm(long_axis)) < 1e-12:
            axis_x = np.array([0.30, 0.0, 0.0])
            axis_y = np.array([0.0, 0.06, 0.0])
            axis_z = np.array([0.0, 0.0, 0.70])
        else:
            long_axis = _unit(long_axis, np.array([1.0, 0.0, 0.0]))
            axis_x = long_axis * 0.30
            axis_y = tangent * 0.06
            axis_z = slab_normal * 0.70
        bases.append(
            LinkerSlabProjection(
                bead_center=np.asarray(center, dtype=float),
                slab_center=np.asarray(center, dtype=float) + slab_normal * 0.45,
                slab_axis_x=axis_x,
                slab_axis_y=axis_y,
                slab_axis_z=axis_z,
            )
        )
    return SsLinkerProjection(
        strand_id=f"__lnk__{conn.id}__s",
        bases=tuple(bases),
        backbone_points=backbone,
    )


def ds_linker_connector_projections(
    nucleotides: list[dict], conn
) -> tuple[DsLinkerConnectorProjection, ...]:
    """Project the two desktop dsDNA anchor-to-bridge connector arcs."""
    base_count = _linker_length_to_bases(conn)
    first_nucleotide = _anchor(nucleotides, conn, is_a_side=True)
    second_nucleotide = _anchor(nucleotides, conn, is_a_side=False)
    first, second = _position(first_nucleotide), _position(second_nucleotide)
    if first is None or second is None:
        return ()
    axis = _unit(second - first, np.array([0.0, 0.0, 1.0]))
    result = []
    for side, anchor, bp_index in (("a", first, 0), ("b", second, base_count - 1)):
        strand_id = f"__lnk__{conn.id}__{side}"
        bridge = next(
            (
                _position(nucleotide)
                for nucleotide in nucleotides
                if nucleotide.get("strand_id") == strand_id
                and nucleotide.get("helix_id") == f"__lnk__{conn.id}"
                and int(nucleotide.get("bp_index") or 0) == bp_index
            ),
            None,
        )
        if bridge is None or float(np.linalg.norm(bridge - anchor)) <= 1e-3:
            continue
        chord = bridge - anchor
        bow = np.cross(chord, axis)
        if float(np.dot(bow, bow)) < 1e-6:
            bow = np.cross(chord, np.array([0.0, 0.0, 1.0]))
        if float(np.dot(bow, bow)) < 1e-6:
            bow = np.cross(chord, np.array([1.0, 0.0, 0.0]))
        control = (anchor + bridge) * 0.5 + _unit(
            bow, np.array([0.0, 1.0, 0.0])
        ) * float(np.linalg.norm(chord)) * 0.25
        result.append(
            DsLinkerConnectorProjection(
                strand_id=strand_id,
                points=_quadratic_samples(anchor, control, bridge),
            )
        )
    return tuple(result)


def _base_centroid(base: str) -> np.ndarray:
    """Mean heavy-atom base-ring site from the atom template of record."""
    # Import lazily: atomistic imports atomistic_helpers, so a module-level import
    # would create a cycle. Reading the template here avoids a second copied centroid
    # table drifting away from both the atomistic model and the desktop Full renderer.
    from backend.core.atomistic import BASE_TEMPLATES, _BASE_CHAR_TO_RESIDUE

    residue = _BASE_CHAR_TO_RESIDUE.get(base.upper(), "DT")
    atom_defs, _ = BASE_TEMPLATES[residue]
    return np.mean(
        np.asarray([[atom[2], atom[3], atom[4]] for atom in atom_defs], dtype=float),
        axis=0,
    )


def crossover_extra_base_full_projections(
    first_nucleotide: dict,
    second_nucleotide: dict,
    sequence: str,
    *,
    sim_reversed: bool,
    local_frame_reversed: bool,
) -> list[CrossoverExtraBaseFullProjection]:
    """Project canonical crossover residue frames into desktop-Full slab geometry.

    Slab local axes exactly mirror ``crossoverExtraSlabQuaternion`` in
    ``crossover_extra_placement.js``: box X follows residue-frame Y, box Y follows
    residue-frame Z, and box Z follows residue-frame X. The attachment point is the
    canonical +X / backbone-facing-Z corner used by ``slabConnectionCorner``.
    """
    if not sequence:
        return []
    placements = crossover_extra_base_placements(
        np.asarray(first_nucleotide["backbone_position"], dtype=float),
        np.asarray(second_nucleotide["backbone_position"], dtype=float),
        np.asarray(first_nucleotide["axis_tangent"], dtype=float),
        np.asarray(second_nucleotide["axis_tangent"], dtype=float),
        len(sequence),
        sim_reversed=sim_reversed,
        local_frame_reversed=local_frame_reversed,
    )
    result = []
    for placement in placements:
        frame = np.asarray(placement["frame_rotation"], dtype=float)
        bead_center = np.asarray(placement["center"], dtype=float)
        base = sequence[int(placement["sim_k"])].upper()
        slab_center = bead_center + frame @ _base_centroid(base)
        axis_x = frame[:, 1] * 0.30
        axis_y = frame[:, 2] * 0.06
        axis_z = frame[:, 0] * 0.70
        z_sign = (
            -1.0 if float(np.dot(bead_center - slab_center, frame[:, 0])) < 0 else 1.0
        )
        slab_corner = slab_center + frame[:, 1] * 0.15 + frame[:, 0] * (z_sign * 0.35)
        result.append(
            CrossoverExtraBaseFullProjection(
                geometric_index=int(placement["geometric_index"]),
                sim_k=int(placement["sim_k"]),
                base=base,
                bead_center=bead_center,
                slab_center=slab_center,
                slab_axis_x=axis_x,
                slab_axis_y=axis_y,
                slab_axis_z=axis_z,
                slab_corner=slab_corner,
            )
        )
    return result
