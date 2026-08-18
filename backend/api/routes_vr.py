"""Local native-OpenXR companion lifecycle for Linux VR.

Stock Linux browsers do not currently bridge WebXR to SteamVR. These endpoints
are therefore deliberately localhost-only: they snapshot the active NADOC part
into a compact read-only scene file and launch/stop the bundled native viewer.
No design data is mutated and no shell command is constructed from request data.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import threading
import time
from typing import Literal, Optional
from urllib.parse import urlparse

import numpy as np
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from backend.api import state as design_state
from backend.core.constants import STAPLE_PALETTE
from backend.core.models import MODIFICATION_COLORS

router = APIRouter(tags=["vr"])

_REPO_ROOT = Path(__file__).resolve().parents[2]
_VIEWER_DIR = _REPO_ROOT / "native" / "vr_viewer"
_BUILD_DIR = _VIEWER_DIR / "build"
_VIEWER = _BUILD_DIR / "nadoc-vr-viewer"
_STATE_PATH = Path(tempfile.gettempdir()) / f"nadoc-vr-{os.getuid()}.json"
_LOG_PATH = Path(tempfile.gettempdir()) / f"nadoc-vr-{os.getuid()}.log"
_STEAMVR_LOG_PATH = Path(tempfile.gettempdir()) / f"nadoc-steamvr-{os.getuid()}.log"
_STATE_LOCK = threading.Lock()
_RUNTIME_LOCK = threading.Lock()


class VRCamera(BaseModel):
    position: list[float] = Field(min_length=3, max_length=3)
    target: list[float] = Field(min_length=3, max_length=3)
    up: list[float] = Field(min_length=3, max_length=3)


class VRLaunchRequest(BaseModel):
    camera: Optional[VRCamera] = None
    measured_positioning: bool = False
    assembly_active: bool = False
    representation: Literal["cylinders", "full", "ballstick", "stick"] = "full"
    coloring: Literal["strand", "base", "cluster", "cpk"] = "strand"


def _require_local(request: Request) -> None:
    host = request.client.host if request.client else ""
    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise HTTPException(
            403, detail="Native VR launch is available only from localhost."
        )
    # A local Vite reverse proxy makes every backend peer look loopback. Preserve
    # the workstation-only boundary by also checking the browser's Origin.
    origin = request.headers.get("origin")
    if origin and (urlparse(origin).hostname or "") not in {
        "127.0.0.1",
        "::1",
        "localhost",
    }:
        raise HTTPException(
            403, detail="Native VR launch is available only from localhost."
        )


def _rgb(hex_color: str) -> tuple[float, float, float]:
    value = int(hex_color.lstrip("#"), 16)
    return (
        ((value >> 16) & 0xFF) / 255.0,
        ((value >> 8) & 0xFF) / 255.0,
        (value & 0xFF) / 255.0,
    )


def _strand_colors(design) -> dict[str, tuple[float, float, float]]:
    colors: dict[str, tuple[float, float, float]] = {}
    staple_index = 0
    for strand in design.strands:
        if not strand.id:
            continue
        if strand.is_scaffold:
            colors[strand.id] = _rgb("#0070bb")
        elif strand.color:
            colors[strand.id] = _rgb(strand.color)
        else:
            colors[strand.id] = _rgb(STAPLE_PALETTE[staple_index % len(STAPLE_PALETTE)])
            staple_index += 1
    return colors


_BASE_COLORS = {
    "A": _rgb("#44dd88"),
    "T": _rgb("#ff5555"),
    "G": _rgb("#ffcc00"),
    "C": _rgb("#55aaff"),
}


def _base_letters(design, nucleotides: list[dict]) -> dict[int, str]:
    """Geometry-list index → assigned base, matching the frontend's 5′→3′ walk."""
    by_strand: dict[str, list[tuple[int, dict]]] = {}
    for index, nucleotide in enumerate(nucleotides):
        strand_id = nucleotide.get("strand_id")
        if strand_id:
            by_strand.setdefault(strand_id, []).append((index, nucleotide))
    sequences = {
        strand.id: strand.sequence for strand in design.strands if strand.sequence
    }
    result: dict[int, str] = {}
    for strand_id, entries in by_strand.items():
        sequence = sequences.get(strand_id)
        if not sequence:
            continue
        entries.sort(
            key=lambda item: (
                int(item[1].get("domain_index") or 0),
                int(item[1].get("bp_index") or 0)
                if item[1].get("direction") == "FORWARD"
                else -int(item[1].get("bp_index") or 0),
                int(item[1].get("copy_k") or item[1].get("ext_k") or 0),
            )
        )
        for offset, (index, _) in enumerate(entries):
            if offset < len(sequence) and sequence[offset].upper() in _BASE_COLORS:
                result[index] = sequence[offset].upper()
    return result


def _cluster_color(design, nucleotide: dict) -> tuple[float, float, float] | None:
    """Resolve the best matching display cluster for one nucleotide."""
    candidates: list[tuple[int, int, int, int]] = []
    for index, cluster in enumerate(design.cluster_transforms):
        domain_match = any(
            ref.strand_id == nucleotide.get("strand_id")
            and ref.domain_index == int(nucleotide.get("domain_index") or 0)
            for ref in cluster.domain_ids
        )
        helix_match = nucleotide.get("helix_id") in cluster.helix_ids
        if not domain_match and not helix_match:
            continue
        candidates.append(
            (
                1 if domain_match else 0,
                0 if cluster.auto_created else 1,
                1 if cluster.color else 0,
                index,
            )
        )
    if not candidates:
        return None
    index = max(candidates)[-1]
    cluster = design.cluster_transforms[index]
    return _rgb(cluster.color or STAPLE_PALETTE[index % len(STAPLE_PALETTE)])


def _nucleotide_colors(design, nucleotides: list[dict], coloring: str) -> list[tuple]:
    strand_colors = _strand_colors(design)
    letters = _base_letters(design, nucleotides) if coloring == "base" else {}
    result = []
    for index, nucleotide in enumerate(nucleotides):
        fallback = strand_colors.get(
            nucleotide.get("strand_id") or "", (0.55, 0.62, 0.72)
        )
        if coloring == "base" and index in letters:
            result.append(_BASE_COLORS[letters[index]])
        elif coloring == "cluster":
            result.append(_cluster_color(design, nucleotide) or fallback)
        else:
            result.append(fallback)
    return result


def _view_rotation(camera: VRCamera | None) -> np.ndarray:
    """Rows map NADOC world coordinates into the desktop camera's view axes."""
    if camera is None:
        return np.identity(3, dtype=float)
    position = np.asarray(camera.position, dtype=float)
    target = np.asarray(camera.target, dtype=float)
    up_hint = np.asarray(camera.up, dtype=float)
    if not np.all(np.isfinite([position, target, up_hint])):
        return np.identity(3, dtype=float)
    forward = target - position
    forward_norm = float(np.linalg.norm(forward))
    up_norm = float(np.linalg.norm(up_hint))
    if forward_norm < 1e-9 or up_norm < 1e-9:
        return np.identity(3, dtype=float)
    forward /= forward_norm
    up_hint /= up_norm
    right = np.cross(forward, up_hint)
    right_norm = float(np.linalg.norm(right))
    if right_norm < 1e-9:
        return np.identity(3, dtype=float)
    right /= right_norm
    up = np.cross(right, forward)
    # OpenXR neutral view looks down -Z.
    return np.stack([right, up, -forward])


def _serialize_scene(
    design,
    nucleotides: list[dict],
    axes: list[dict],
    camera=None,
    representation: str = "full",
    coloring: str = "strand",
    atomistic_model=None,
) -> str:
    """Create the deliberately trivial line-oriented format read by the C++ viewer."""
    rotation = _view_rotation(camera)
    color_channels = {
        mode: _nucleotide_colors(design, nucleotides, mode)
        for mode in ("strand", "base", "cluster", "cpk")
    }

    def point(value) -> np.ndarray | None:
        if not isinstance(value, (list, tuple)) or len(value) != 3:
            return None
        p = np.asarray(value, dtype=float)
        if not np.all(np.isfinite(p)):
            return None
        return rotation @ p

    def nums(*values: float) -> str:
        return " ".join(f"{float(value):.7g}" for value in values)

    def palette_for_index(index: int) -> tuple[float, ...]:
        return tuple(
            channel
            for mode in ("strand", "base", "cluster", "cpk")
            for channel in color_channels[mode][index]
        )

    def solid_palette(color: tuple[float, float, float]) -> tuple[float, ...]:
        return color * 4

    lines = [f"NADOCVR 5 {representation} {coloring}", "# preloaded VR representations"]
    by_strand: dict[str, list[tuple[dict, np.ndarray, tuple[float, ...]]]] = {}
    identity_palettes: dict[tuple, tuple[float, ...]] = {}
    lines.append("R full")
    assigned = [
        (index, nucleotide)
        for index, nucleotide in enumerate(nucleotides)
        if nucleotide.get("strand_id")
        and not nucleotide.get("is_modification")
        and not nucleotide.get("is_flexible_segment")
        and not (
            str(nucleotide.get("strand_id", "")).startswith("__lnk__")
            and str(nucleotide.get("strand_id", "")).endswith("__s")
            and str(nucleotide.get("helix_id", "")).startswith("__lnk__")
        )
    ]
    strand_by_id = {strand.id: strand for strand in design.strands}
    site_entries: dict[
        tuple[str, int, str], tuple[dict, np.ndarray, tuple[float, ...]]
    ] = {}

    def palette_variant(
        palette: tuple[float, ...], nucleotide: dict, scaffold_hex: str
    ) -> tuple[float, ...]:
        strand = strand_by_id.get(nucleotide.get("strand_id"))
        if not strand or not strand.is_scaffold:
            return palette
        return (*_rgb(scaffold_hex), *palette[3:])

    def box(
        center: np.ndarray,
        axis_x: np.ndarray,
        axis_y: np.ndarray,
        axis_z: np.ndarray,
        palette: tuple[float, ...],
    ) -> None:
        lines.append(f"B {nums(*center, *axis_x, *axis_y, *axis_z, *palette)}")

    for index, nucleotide in assigned:
        backbone = point(nucleotide.get("backbone_position"))
        if backbone is None:
            continue
        strand_id = nucleotide.get("strand_id") or ""
        palette = palette_for_index(index)
        identity = (
            strand_id,
            nucleotide.get("helix_id") or "",
            int(nucleotide.get("bp_index") or 0),
            nucleotide.get("direction") or "",
        )
        identity_palettes[identity] = palette
        site_entries[
            (
                str(nucleotide.get("helix_id") or ""),
                int(nucleotide.get("bp_index") or 0),
                str(nucleotide.get("direction") or ""),
            )
        ] = (nucleotide, backbone, palette)
        if nucleotide.get("is_five_prime"):
            size = np.identity(3) * 0.18
            box(backbone, *(rotation @ size[:, column] for column in range(3)), palette)
        else:
            lines.append(f"P {nums(*backbone, 0.10, *palette)}")
        if strand_id:
            by_strand.setdefault(strand_id, []).append((nucleotide, backbone, palette))

    # Modification-only extension tips are intentionally not ordinary DNA beads:
    # desktop Full renders them as larger, chemistry-colored marker spheres and
    # excludes them from backbone cones/slabs. Preserve that separation in VR.
    for nucleotide in nucleotides:
        if not nucleotide.get("is_modification"):
            continue
        marker_position = point(nucleotide.get("backbone_position"))
        if marker_position is None:
            continue
        marker_color = _rgb(
            MODIFICATION_COLORS.get(nucleotide.get("modification"), "#ffffff")
        )
        lines.append(f"P {nums(*marker_position, 0.25, *solid_palette(marker_color))}")

    # Standard Full uses one oriented 0.30 × 0.06 × 0.70 nm base slab per
    # nucleotide. Paired slabs share their mean axial plane and are shifted
    # radially until their rectangle reaches the backbone bead, exactly matching
    # helix_renderer.pairedSlabCenter().
    pair_groups: dict[tuple, dict[str, list[tuple[int, dict]]]] = {}
    for index, nucleotide in assigned:
        helix_id = str(nucleotide.get("helix_id") or "")
        if helix_id.startswith("__ext_"):
            continue
        key = (helix_id, int(nucleotide.get("bp_index") or 0))
        group = pair_groups.setdefault(key, {"FORWARD": [], "REVERSE": []})
        direction = nucleotide.get("direction")
        if direction in group:
            group[direction].append((index, nucleotide))
    mates: dict[int, dict] = {}
    for group in pair_groups.values():
        for (_, forward), (_, reverse) in zip(group["FORWARD"], group["REVERSE"]):
            mates[id(forward)] = reverse
            mates[id(reverse)] = forward

    for index, nucleotide in assigned:
        if str(nucleotide.get("helix_id") or "").startswith("__ext_"):
            continue
        try:
            raw_bead = np.asarray(nucleotide.get("backbone_position"), dtype=float)
            raw_base = np.asarray(nucleotide.get("base_position"), dtype=float)
            raw_normal = np.asarray(nucleotide.get("base_normal"), dtype=float)
            raw_tangent = np.asarray(nucleotide.get("axis_tangent"), dtype=float)
        except (TypeError, ValueError):
            continue
        if not all(
            value.shape == (3,) and np.all(np.isfinite(value))
            for value in (raw_bead, raw_base, raw_normal, raw_tangent)
        ):
            continue
        tangent_norm = float(np.linalg.norm(raw_tangent))
        if tangent_norm < 1e-9:
            continue
        tangent = raw_tangent / tangent_norm
        normal = raw_normal - tangent * float(np.dot(raw_normal, tangent))
        normal_norm = float(np.linalg.norm(normal))
        if normal_norm < 1e-9:
            continue
        normal /= normal_norm
        tangential = np.cross(tangent, normal)
        tangential /= max(float(np.linalg.norm(tangential)), 1e-9)

        center = raw_base.copy()
        mate = mates.get(id(nucleotide))
        if mate and isinstance(mate.get("base_position"), (list, tuple)):
            mate_base = np.asarray(mate["base_position"], dtype=float)
            if mate_base.shape == (3,) and np.all(np.isfinite(mate_base)):
                center += tangent * float(np.dot(mate_base - center, tangent)) * 0.5
        radial = raw_bead - center
        radial -= tangent * float(np.dot(radial, tangent))
        bead_distance = float(np.linalg.norm(radial))
        if bead_distance > 1e-9:
            radial /= bead_distance
            support = (
                abs(float(np.dot(radial, tangential))) * 0.15
                + abs(float(np.dot(radial, normal))) * 0.35
            )
            center += radial * max(0.0, bead_distance - support + 0.02)

        palette = palette_variant(palette_for_index(index), nucleotide, "#0277bd")
        box(
            rotation @ center,
            rotation @ (tangential * 0.30),
            rotation @ (tangent * 0.06),
            rotation @ (normal * 0.70),
            palette,
        )
        z_sign = -1.0 if float(np.dot(raw_bead - center, normal)) < 0 else 1.0
        corner = center + tangential * 0.15 + normal * (z_sign * 0.35)
        lines.append(
            f"C {nums(*(rotation @ raw_bead), *(rotation @ corner), 0.025, *palette)}"
        )

    # Join sequential backbone beads. Long jumps are omitted so malformed or
    # sparse strand metadata cannot draw a line across an entire structure.
    for strand_nucleotides in by_strand.values():
        strand_nucleotides.sort(
            key=lambda item: (
                int(item[0].get("domain_index") or 0),
                int(item[0].get("bp_index") or 0)
                if item[0].get("direction") == "FORWARD"
                else -int(item[0].get("bp_index") or 0),
                int(item[0].get("copy_k") or item[0].get("ext_k") or 0),
            )
        )
        for (first_nucleotide, first, palette), (second_nucleotide, second, _) in zip(
            strand_nucleotides, strand_nucleotides[1:]
        ):
            if (
                first_nucleotide.get("helix_id") == second_nucleotide.get("helix_id")
                and float(np.linalg.norm(second - first)) <= 5.0
            ):
                arrow_palette = palette_variant(palette, first_nucleotide, "#0288d1")
                lines.append(f"C {nums(*first, *second, 0.075, *arrow_palette)}")

    # The desktop arc layer reads crossover and forced-ligation records directly;
    # it never infers their endpoints from proximity. Mirror that contract here so
    # unligated crossover records and cross-helix forced ligations cannot vanish
    # merely because the backbone-order pass above only joins same-helix beads.
    # Extra-base junctions are projected separately because their connector is a
    # bead/slab chain, not a direct chord. Periodic seams are hidden by default in
    # the desktop view and stay hidden in this immutable snapshot too.
    def direction_value(value) -> str:
        return str(getattr(value, "value", value))

    domain_end_keys = {
        (
            str(domain.helix_id),
            int(domain.end_bp),
            direction_value(domain.direction),
        )
        for strand in design.strands
        for domain in getattr(strand, "domains", [])
    }

    explicit_connections = [
        (
            (
                str(xo.half_a.helix_id),
                int(xo.half_a.index),
                direction_value(xo.half_a.strand),
            ),
            (
                str(xo.half_b.helix_id),
                int(xo.half_b.index),
                direction_value(xo.half_b.strand),
            ),
            xo.extra_bases,
            False,
        )
        for xo in getattr(design, "crossovers", [])
    ]
    explicit_connections.extend(
        (
            (
                str(fl.three_prime_helix_id),
                int(fl.three_prime_bp),
                direction_value(fl.three_prime_direction),
            ),
            (
                str(fl.five_prime_helix_id),
                int(fl.five_prime_bp),
                direction_value(fl.five_prime_direction),
            ),
            fl.extra_bases,
            bool(fl.is_periodic_seam),
        )
        for fl in getattr(design, "forced_ligations", [])
    )
    for first_key, second_key, extra_bases, hidden_periodic in explicit_connections:
        if hidden_periodic:
            continue
        first_entry = site_entries.get(first_key)
        second_entry = site_entries.get(second_key)
        if first_entry is None or second_entry is None:
            continue
        first_nucleotide, first, palette = first_entry
        second_nucleotide, second, _ = second_entry
        if extra_bases:
            from backend.core.vr_scene_projection import (
                crossover_extra_base_full_projections,
            )

            projections = crossover_extra_base_full_projections(
                first_nucleotide,
                second_nucleotide,
                str(extra_bases),
                sim_reversed=first_key not in domain_end_keys,
                local_frame_reversed=first_key[2] == "REVERSE",
            )
            bead_palette = palette_variant(palette, first_nucleotide, "#0070bb")
            slab_palette = palette_variant(palette, first_nucleotide, "#0277bd")
            backbone_points = [first]
            for projection in projections:
                extra_palette = (
                    *bead_palette[0:3],
                    *_BASE_COLORS.get(projection.base, bead_palette[3:6]),
                    *bead_palette[6:],
                )
                bead = rotation @ projection.bead_center
                slab_center = rotation @ projection.slab_center
                slab_axis_x = rotation @ projection.slab_axis_x
                slab_axis_y = rotation @ projection.slab_axis_y
                slab_axis_z = rotation @ projection.slab_axis_z
                slab_corner = rotation @ projection.slab_corner
                lines.append(f"P {nums(*bead, 0.10, *extra_palette)}")
                box(
                    slab_center,
                    slab_axis_x,
                    slab_axis_y,
                    slab_axis_z,
                    (
                        *slab_palette[0:3],
                        *_BASE_COLORS.get(projection.base, slab_palette[3:6]),
                        *slab_palette[6:],
                    ),
                )
                lines.append(f"C {nums(*bead, *slab_corner, 0.025, *slab_palette)}")
                backbone_points.append(bead)
            backbone_points.append(second)
            for start, end in zip(backbone_points, backbone_points[1:]):
                lines.append(f"C {nums(*start, *end, 0.075, *bead_palette)}")
            continue
        if first_key[0] == second_key[0]:
            continue
        arc_palette = palette_variant(palette, first_nucleotide, "#0288d1")
        lines.append(f"C {nums(*first, *second, 0.025, *arc_palette)}")

    def axis_edges(axis: dict):
        """Yield visible axis edges, preferring authoritative domain segments.

        ``deformed_helix_axes`` deliberately emits one segment per occupied
        domain interval. Falling back to the whole sampled shaft when those
        segments exist fills the negative space between domains, which changes
        the topology's visual reading in both Full and cylinder views.
        """
        segments = axis.get("segments")
        if segments is not None:
            for segment in segments:
                first, second = point(segment.get("start")), point(segment.get("end"))
                if first is not None and second is not None:
                    yield first, second, segment
            return
        samples = axis.get("samples") or [axis.get("start"), axis.get("end")]
        for first_raw, second_raw in zip(samples, samples[1:]):
            first, second = point(first_raw), point(second_raw)
            if first is not None and second is not None:
                yield first, second, None

    def append_axes(radius: float = 0.025) -> None:
        palette = solid_palette((0.30, 0.34, 0.42))
        for axis in axes:
            for first, second, _ in axis_edges(axis):
                lines.append(f"C {nums(*first, *second, radius, *palette)}")

    append_axes(0.05)

    lines.append("R cylinders")
    direct_overhang_ids: set[str] = set()
    for binding in getattr(design, "overhang_bindings", []):
        if getattr(binding, "bound", True) is False or getattr(
            binding, "connection_type", None
        ) not in {"root-to-root", "end-to-root"}:
            continue
        for attribute in (
            "driver_oh_id",
            "driven_oh_id",
            "overhang_a_id",
            "overhang_b_id",
        ):
            value = getattr(binding, attribute, None)
            if value:
                direct_overhang_ids.add(str(value))
    for duplex in getattr(design, "duplexes", []):
        if getattr(duplex, "bound", True) is False or getattr(
            duplex, "connection_type", None
        ) not in {"root-to-root", "end-to-root"}:
            continue
        for side_name in ("left", "right"):
            value = getattr(getattr(duplex, side_name, None), "overhang_id", None)
            if value:
                direct_overhang_ids.add(str(value))

    first_palette_by_helix = {}
    for index, nucleotide in enumerate(nucleotides):
        first_palette_by_helix.setdefault(
            nucleotide.get("helix_id"), palette_for_index(index)
        )
    for axis in axes:
        fallback_palette = first_palette_by_helix.get(
            axis.get("helix_id"), solid_palette((0.45, 0.55, 0.72))
        )
        for first, second, segment in axis_edges(axis):
            palette = fallback_palette
            if segment is not None and segment.get("strand_id"):
                match = next(
                    (
                        index
                        for index, nucleotide in enumerate(nucleotides)
                        if nucleotide.get("strand_id") == segment.get("strand_id")
                        and int(nucleotide.get("domain_index") or 0)
                        == int(segment.get("domain_index") or 0)
                    ),
                    None,
                )
                if match is not None:
                    palette = palette_for_index(match)
            record_type = (
                "H"
                if segment is not None
                and segment.get("ovhg_id")
                and str(segment.get("ovhg_id")) not in direct_overhang_ids
                else "C"
            )
            lines.append(f"{record_type} {nums(*first, *second, 0.72, *palette)}")

    if atomistic_model is None:
        raise HTTPException(500, detail="Atomistic VR snapshot was not built.")
    from backend.core.atomistic import (
        CPK_COLOR,
        DEFAULT_CPK_COLOR,
        DEFAULT_VDW_RADIUS,
        VDW_RADIUS,
    )

    strand_colors = _strand_colors(design)
    atom_positions = [point([atom.x, atom.y, atom.z]) for atom in atomistic_model.atoms]
    atom_palettes = []
    for atom in atomistic_model.atoms:
        fallback = strand_colors.get(atom.strand_id, (0.55, 0.62, 0.72))
        identity = identity_palettes.get(
            (atom.strand_id, atom.helix_id, atom.bp_index, atom.direction),
            solid_palette(fallback),
        )
        strand_color = identity[0:3]
        base_color = _BASE_COLORS.get(atom.residue[-1:], identity[3:6])
        cluster_color = identity[6:9]
        cpk_color = _rgb(f"#{CPK_COLOR.get(atom.element, DEFAULT_CPK_COLOR):06x}")
        atom_palettes.append((*strand_color, *base_color, *cluster_color, *cpk_color))

    def append_atomistic(name: str, include_points: bool, radius: float) -> None:
        lines.append(f"R {name}")
        if include_points:
            for atom, position, palette in zip(
                atomistic_model.atoms, atom_positions, atom_palettes
            ):
                if position is not None:
                    radius = VDW_RADIUS.get(atom.element, DEFAULT_VDW_RADIUS) * 0.55
                    lines.append(f"P {nums(*position, radius, *palette)}")
        for first_index, second_index in atomistic_model.bonds:
            first, second = atom_positions[first_index], atom_positions[second_index]
            if first is None or second is None:
                continue
            palette = tuple(
                (a + b) * 0.5
                for a, b in zip(atom_palettes[first_index], atom_palettes[second_index])
            )
            lines.append(f"C {nums(*first, *second, radius, *palette)}")
        append_axes(0.05)

    append_atomistic("ballstick", True, 0.035)
    append_atomistic("stick", False, 0.055)

    if not any(line.startswith(("P ", "C ", "B ")) for line in lines):
        raise HTTPException(
            409, detail="The active design contains no display geometry."
        )
    return "\n".join(lines) + "\n"


def _snapshot(body: VRLaunchRequest) -> str:
    from backend.core.deformation import (
        _apply_ovhg_rotations_to_axes,
        deformed_helix_axes,
    )
    from backend.core.design_geometry import _geometry_for_design

    design = design_state.get_or_404()
    nucleotides = _geometry_for_design(
        design,
        measured_positioning=body.measured_positioning,
        junction_balance=True,
    )
    axes = deformed_helix_axes(design)
    _apply_ovhg_rotations_to_axes(design, axes, nucleotides)
    from backend.core.atomistic import build_atomistic_model

    # The in-headset menu switches instantly, so all four representations are
    # preloaded in one immutable snapshot instead of calling back into the browser.
    atomistic_model = build_atomistic_model(
        design,
        fast_bridges=True,
        measured_positioning=body.measured_positioning,
    )
    return _serialize_scene(
        design,
        nucleotides,
        axes,
        body.camera,
        body.representation,
        body.coloring,
        atomistic_model,
    )


def _build_environment() -> dict[str, str]:
    env = dict(os.environ)
    for key in (
        "CFLAGS",
        "CXXFLAGS",
        "CPPFLAGS",
        "LDFLAGS",
        "CPATH",
        "CPLUS_INCLUDE_PATH",
        "CMAKE_PREFIX_PATH",
        "LIBRARY_PATH",
        "LD_LIBRARY_PATH",
        "CONDA_PREFIX",
    ):
        env.pop(key, None)
    env["PATH"] = "/usr/local/bin:/usr/bin:/bin"
    runtime = (
        Path.home() / ".local/share/Steam/steamapps/common/SteamVR/steamxr_linux64.json"
    )
    if runtime.is_file():
        env["XR_RUNTIME_JSON"] = str(runtime)
    return env


def _ensure_viewer_built() -> None:
    sources = [
        _VIEWER_DIR / "CMakeLists.txt",
        *(_VIEWER_DIR / "src").glob("*.cpp"),
        *(_VIEWER_DIR / "src").glob("*.hpp"),
    ]
    newest_source = max(path.stat().st_mtime for path in sources)
    if _VIEWER.is_file() and _VIEWER.stat().st_mtime >= newest_source:
        return

    env = _build_environment()
    env.update({"CC": "/usr/bin/gcc", "CXX": "/usr/bin/g++"})
    configure = subprocess.run(
        [
            "/usr/bin/cmake",
            "-S",
            str(_VIEWER_DIR),
            "-B",
            str(_BUILD_DIR),
            "-G",
            "Ninja",
            "-DCMAKE_BUILD_TYPE=Release",
        ],
        env=env,
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if configure.returncode != 0:
        raise HTTPException(
            503, detail=f"VR viewer configure failed: {configure.stderr[-1200:]}"
        )
    build = subprocess.run(
        ["/usr/bin/cmake", "--build", str(_BUILD_DIR)],
        env=env,
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if build.returncode != 0 or not _VIEWER.is_file():
        raise HTTPException(
            503, detail=f"VR viewer build failed: {build.stderr[-1200:]}"
        )


def _read_state() -> dict | None:
    try:
        state = json.loads(_STATE_PATH.read_text())
        pid = int(state["pid"])
        expected = _VIEWER.resolve()
        actual = Path(f"/proc/{pid}/exe").resolve()
        if actual != expected:
            raise ValueError("PID no longer belongs to NADOC VR")
        return state
    except (FileNotFoundError, KeyError, ValueError, OSError, json.JSONDecodeError):
        _STATE_PATH.unlink(missing_ok=True)
        return None


def _process_names() -> set[str]:
    """Read Linux process names without introducing a psutil dependency."""
    names: set[str] = set()
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            names.add((entry / "comm").read_text().strip())
        except OSError:
            continue
    return names


def _runtime_payload() -> dict[str, bool]:
    names = _process_names()
    return {
        "steamvr_running": "vrserver" in names and "vrcompositor" in names,
        "dashboard_running": "vrdashboard" in names,
    }


def _start_steamvr() -> dict[str, bool]:
    """Start SteamVR through Steam so its dashboard owns the runtime lifecycle."""
    with _RUNTIME_LOCK:
        status = _runtime_payload()
        if status["steamvr_running"] and status["dashboard_running"]:
            return status
        steam = Path("/usr/bin/steam")
        if not steam.is_file():
            raise HTTPException(503, detail="Steam is not installed at /usr/bin/steam.")
        log = _STEAMVR_LOG_PATH.open("ab")
        try:
            subprocess.Popen(
                [str(steam), "-silent", "steam://rungameid/250820"],
                cwd=Path.home(),
                env=dict(os.environ),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
            )
        except OSError as exc:
            raise HTTPException(503, detail=f"Could not start SteamVR: {exc}") from exc
        finally:
            log.close()

        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline:
            status = _runtime_payload()
            if status["steamvr_running"] and status["dashboard_running"]:
                return status
            time.sleep(0.25)
        status = _runtime_payload()
        if not status["steamvr_running"]:
            raise HTTPException(
                503,
                detail=f"SteamVR did not start. See {_STEAMVR_LOG_PATH}.",
            )
        return status


def _write_state(state: dict) -> None:
    _STATE_PATH.write_text(json.dumps(state))
    _STATE_PATH.chmod(0o600)


def _cleanup_after_process(process: subprocess.Popen, scene_path: Path) -> None:
    process.wait()
    scene_path.unlink(missing_ok=True)
    with _STATE_LOCK:
        state = _read_state()
        if state and int(state["pid"]) == process.pid:
            _STATE_PATH.unlink(missing_ok=True)


def _status_payload() -> dict:
    state = _read_state()
    if not state:
        return {
            "running": False,
            "available": _VIEWER.is_file()
            or (_VIEWER_DIR / "CMakeLists.txt").is_file(),
            "log_path": str(_LOG_PATH),
            **_runtime_payload(),
        }
    return {
        "running": True,
        "available": True,
        "pid": int(state["pid"]),
        "started_at": state.get("started_at"),
        "log_path": str(_LOG_PATH),
        **_runtime_payload(),
    }


@router.get("/vr/status")
def vr_status(request: Request) -> dict:
    _require_local(request)
    return _status_payload()


@router.post("/vr/runtime/start")
def start_vr_runtime(request: Request) -> dict:
    _require_local(request)
    return {
        **_start_steamvr(),
        "desktop_hint": (
            "Press the Vive System button, then select Desktop in the SteamVR dashboard."
        ),
        "log_path": str(_STEAMVR_LOG_PATH),
    }


@router.post("/vr/launch")
def launch_vr(body: VRLaunchRequest, request: Request) -> dict:
    _require_local(request)
    if body.assembly_active:
        raise HTTPException(
            409,
            detail="The first native VR viewer supports Part view; exit Assembly mode first.",
        )

    # Starting SteamVR through the Steam client (rather than incidentally through
    # xrCreateInstance) keeps Dashboard/Desktop available after the NADOC scene exits.
    _start_steamvr()

    with _STATE_LOCK:
        running = _read_state()
        if running:
            return _status_payload()
        _ensure_viewer_built()
        scene_text = _snapshot(body)
        with tempfile.NamedTemporaryFile(
            mode="w",
            prefix="nadoc-vr-",
            suffix=".nadocvr",
            delete=False,
        ) as scene_file:
            scene_file.write(scene_text)
            scene_path = Path(scene_file.name)
        scene_path.chmod(0o600)

        log = _LOG_PATH.open("ab")
        try:
            process = subprocess.Popen(
                [str(_VIEWER), str(scene_path)],
                cwd=_REPO_ROOT,
                env=_build_environment(),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
            )
        except OSError as exc:
            scene_path.unlink(missing_ok=True)
            raise HTTPException(
                503, detail=f"Could not launch VR viewer: {exc}"
            ) from exc
        finally:
            log.close()

        # Catch immediate loader/display errors and return their last log line.
        time.sleep(0.15)
        if process.poll() is not None:
            scene_path.unlink(missing_ok=True)
            detail = "Native VR viewer exited during startup."
            try:
                tail = _LOG_PATH.read_text(errors="replace").splitlines()[-1]
                if tail:
                    detail = tail
            except (OSError, IndexError):
                pass
            raise HTTPException(503, detail=detail)

        state = {
            "pid": process.pid,
            "scene_path": str(scene_path),
            "started_at": time.time(),
        }
        _write_state(state)
        threading.Thread(
            target=_cleanup_after_process,
            args=(process, scene_path),
            daemon=True,
            name="nadoc-vr-cleanup",
        ).start()
        return _status_payload()


@router.post("/vr/stop")
def stop_vr(request: Request) -> dict:
    _require_local(request)
    with _STATE_LOCK:
        state = _read_state()
        if not state:
            return _status_payload()
        try:
            os.killpg(int(state["pid"]), signal.SIGTERM)
        except ProcessLookupError:
            _STATE_PATH.unlink(missing_ok=True)
        return {**_status_payload(), "stopping": True}
