"""Local native-OpenXR companion lifecycle for Linux VR.

Stock Linux browsers do not currently bridge WebXR to SteamVR. These endpoints
are therefore deliberately localhost-only: they snapshot the active NADOC part
into a compact read-only scene file and launch/stop the bundled native viewer.
No design data is mutated and no shell command is constructed from request data.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import threading
import time
from typing import Literal, Optional
from urllib.parse import quote, urlparse

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
_FEEDBACK_LOCK = threading.Lock()

SelectionKind = Literal[
    "none",
    "cluster",
    "strand",
    "domain",
    "base",
    "end",
    "bond",
    "crossover",
    "overhang",
    "extension",
    "protein",
]


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
    selection_level: Literal[
        "default", "cluster", "strand", "domain", "end", "xover", "base"
    ] = "default"
    selected_owner_tokens: list[str] = Field(default_factory=list, max_length=8)
    selected_selection_kind: SelectionKind = "none"


class VRFeedbackRequest(BaseModel):
    select_sequence: int = Field(ge=0)
    identity: Optional[str] = Field(default=None, max_length=2048)
    accepted: bool = False
    selected: bool = False
    selection_level: Literal[
        "default", "cluster", "strand", "domain", "end", "xover", "base"
    ] = "default"
    owner_tokens: list[str] = Field(default_factory=list, max_length=8)
    selection_kind: SelectionKind = "none"


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


def _display_cluster(design, nucleotide: dict):
    """Resolve the same best matching cluster used by desktop coloring."""
    candidates: list[tuple[int, int, int, int]] = []
    clusters = getattr(design, "cluster_transforms", [])
    for index, cluster in enumerate(clusters):
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
    return clusters[index]


def _cluster_color(design, nucleotide: dict) -> tuple[float, float, float] | None:
    """Resolve the best matching display cluster color for one nucleotide."""
    cluster = _display_cluster(design, nucleotide)
    if cluster is None:
        return None
    index = getattr(design, "cluster_transforms", []).index(cluster)
    return _rgb(cluster.color or STAPLE_PALETTE[index % len(STAPLE_PALETTE)])


def _cluster_contains_nucleotide(
    design, cluster, nucleotide: dict, strands: dict | None = None
) -> bool:
    """Mirror ``clusterMemberFilter`` from the desktop selection/gizmo path."""
    helix_ids = list(getattr(cluster, "helix_ids", []) or [])
    if not helix_ids:
        return False
    domain_ids = list(getattr(cluster, "domain_ids", []) or [])
    if not domain_ids:
        return nucleotide.get("helix_id") in helix_ids
    if strands is None:
        strands = {strand.id: strand for strand in getattr(design, "strands", [])}
    domain_keys, exclusive_helices = _cluster_membership_facts(
        cluster, strands
    )
    return (
        (
            nucleotide.get("strand_id"),
            int(nucleotide.get("domain_index") or 0),
        )
        in domain_keys
        or nucleotide.get("helix_id") in exclusive_helices
    )


def _cluster_membership_facts(cluster, strands: dict) -> tuple[set, set]:
    domain_ids = list(getattr(cluster, "domain_ids", []) or [])
    domain_keys = {(ref.strand_id, int(ref.domain_index)) for ref in domain_ids}
    bridge_helices = set()
    for ref in domain_ids:
        strand = strands.get(ref.strand_id)
        if strand is not None and 0 <= ref.domain_index < len(strand.domains):
            bridge_helices.add(str(strand.domains[ref.domain_index].helix_id))
    return domain_keys, set(getattr(cluster, "helix_ids", []) or []) - bridge_helices


def _selection_clusters(design, nucleotide: dict) -> tuple:
    """Containing clusters ordered by the desktop click default, then stable size."""
    clusters = getattr(design, "cluster_transforms", [])
    strands = {strand.id: strand for strand in getattr(design, "strands", [])}
    matches = [
        (index, cluster)
        for index, cluster in enumerate(clusters)
        if _cluster_contains_nucleotide(design, cluster, nucleotide, strands)
    ]
    matches.sort(
        key=lambda item: (
            1 if getattr(item[1], "is_default", False) else 0,
            0
            if getattr(item[1], "is_default", False)
            else len(getattr(item[1], "helix_ids", []) or []),
            item[0],
        )
    )
    return tuple(cluster for _, cluster in matches)


def _selection_cluster(design, nucleotide: dict):
    """Mirror the desktop's smallest non-default selectable cluster resolution."""
    clusters = _selection_clusters(design, nucleotide)
    return clusters[0] if clusters else None


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


def _cluster_gizmo_handle_centers(
    design, nucleotides: list[dict], view_rotation: np.ndarray
) -> tuple[tuple[str, np.ndarray], ...]:
    """Owner token + current visual gizmo center, matching desktop attach.

    Desktop computes the mean live backbone position, reverses the stored transform
    only to rebase its persisted pivot/translation, then places the gizmo back at
    this same visual centroid. The VR projection therefore records the centroid
    directly and never trusts or mutates a possibly stale stored pivot.
    """
    records: list[tuple[str, np.ndarray]] = []
    strands = {strand.id: strand for strand in getattr(design, "strands", [])}
    for cluster in getattr(design, "cluster_transforms", []) or []:
        domain_ids = list(getattr(cluster, "domain_ids", []) or [])
        if domain_ids:
            domain_keys, exclusive_helices = _cluster_membership_facts(
                cluster, strands
            )
            def contains(nucleotide):
                return (
                    (
                        nucleotide.get("strand_id"),
                        int(nucleotide.get("domain_index") or 0),
                    )
                    in domain_keys
                    or nucleotide.get("helix_id") in exclusive_helices
                )
        else:
            helix_ids = set(getattr(cluster, "helix_ids", []) or [])

            def contains(nucleotide):
                return nucleotide.get("helix_id") in helix_ids
        positions = []
        for nucleotide in nucleotides:
            raw = nucleotide.get("backbone_position")
            if (
                contains(nucleotide)
                and isinstance(raw, (list, tuple))
                and len(raw) == 3
            ):
                position = np.asarray(raw, dtype=float)
                if np.all(np.isfinite(position)):
                    positions.append(position)
        if not positions:
            continue
        visual_centroid = np.mean(positions, axis=0)
        token = quote(
            json.dumps(
                ("cluster", str(cluster.id)),
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            safe="-_.!~*'()",
        )
        records.append((token, view_rotation @ visual_centroid))
    return tuple(records)


def _serialize_scene(
    design,
    nucleotides: list[dict],
    axes: list[dict],
    camera=None,
    representation: str = "full",
    coloring: str = "strand",
    atomistic_model=None,
    unligated_crossover_ids: list[str] | None = None,
) -> str:
    """Create the deliberately trivial line-oriented format read by the C++ viewer."""
    rotation = _view_rotation(camera)
    cluster_handles = _cluster_gizmo_handle_centers(design, nucleotides, rotation)
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

    primitive_ids: dict[str, set[str]] = {
        name: set() for name in ("full", "cylinders", "ballstick", "stick")
    }
    active_representation = "full"

    def selection_token(*values) -> str:
        payload = json.dumps(values, ensure_ascii=False, separators=(",", ":"))
        # Match JavaScript encodeURIComponent, which produces the feedback tokens.
        return quote(payload, safe="-_.!~*'()")

    def owner_tokens(*refs: tuple) -> tuple[str, ...]:
        return tuple(dict.fromkeys(selection_token(*ref) for ref in refs if ref))

    def base_key(nucleotide: dict) -> str | None:
        if (
            nucleotide.get("crossover_id") is not None
            and nucleotide.get("extra_base_k") is not None
        ):
            return (
                f"__xb__:{nucleotide['crossover_id']}:"
                f"{int(nucleotide['extra_base_k'])}"
            )
        if (
            nucleotide.get("extension_id") is not None
            and nucleotide.get("ext_k") is not None
            and nucleotide.get("direction")
        ):
            return (
                f"__ext_{nucleotide['extension_id']}:"
                f"{int(nucleotide['ext_k'])}:{nucleotide['direction']}"
            )
        helix_id = nucleotide.get("helix_id")
        direction = nucleotide.get("direction")
        if not helix_id or not direction:
            return None
        bp_index = int(nucleotide.get("bp_index") or nucleotide.get("ext_k") or 0)
        copy_k = int(nucleotide.get("copy_k") or 0)
        key = f"{helix_id}:{bp_index}:{direction}"
        return f"{key}:{copy_k}" if copy_k else key

    def nucleotide_owner_tokens(nucleotide: dict) -> tuple[str, ...]:
        refs: list[tuple] = []
        key = base_key(nucleotide)
        if key:
            refs.append(("base", key))
            if nucleotide.get("is_five_prime") or nucleotide.get("is_three_prime"):
                refs.append(("end", key))
        strand_id = nucleotide.get("strand_id")
        if strand_id:
            refs.append(
                ("domain", str(strand_id), int(nucleotide.get("domain_index") or 0))
            )
            refs.append(("strand", str(strand_id)))
        crossover_id = nucleotide.get("crossover_id")
        if crossover_id is not None:
            forced = any(
                str(getattr(connection, "id", "")) == str(crossover_id)
                for connection in getattr(design, "forced_ligations", [])
            )
            refs.append(
                (
                    "crossover",
                    "forced_ligation" if forced else "crossover",
                    str(crossover_id),
                )
            )
        for cluster in _selection_clusters(design, nucleotide):
            if len(refs) >= 8:
                break
            refs.append(("cluster", str(cluster.id)))
        return owner_tokens(*refs)

    def domain_owner_tokens(
        strand_id: str | None, domain_index: int, helix_id: str | None
    ) -> tuple[str, ...]:
        if not strand_id:
            return ()
        nucleotide = {
            "strand_id": str(strand_id),
            "domain_index": int(domain_index),
            "helix_id": helix_id or "",
        }
        refs: list[tuple] = [
            ("domain", str(strand_id), int(domain_index)),
            ("strand", str(strand_id)),
        ]
        for cluster in _selection_clusters(design, nucleotide):
            if len(refs) >= 8:
                break
            refs.append(("cluster", str(cluster.id)))
        return owner_tokens(*refs)

    def emit(
        record_type: str,
        identity: str,
        *values: float,
        aliases: tuple[str, ...] = (),
    ) -> None:
        encoded_identity = quote(str(identity), safe="-_.:~")
        if encoded_identity in primitive_ids[active_representation]:
            raise HTTPException(
                500,
                detail=(
                    f"Duplicate VR primitive identity in {active_representation}: "
                    f"{identity}"
                ),
            )
        primitive_ids[active_representation].add(encoded_identity)
        lines.append(f"{record_type} {encoded_identity} {nums(*values)}")
        if aliases:
            if len(aliases) > 8 or any(not token or len(token) > 2048 for token in aliases):
                raise HTTPException(500, detail="Invalid VR primitive owner aliases.")
            lines.append(f"A {encoded_identity} {len(aliases)} {' '.join(aliases)}")

    def nucleotide_identity(nucleotide: dict) -> str:
        return ":".join(
            str(value)
            for value in (
                "nuc",
                nucleotide.get("strand_id") or "_",
                int(nucleotide.get("domain_index") or 0),
                nucleotide.get("helix_id") or "_",
                int(nucleotide.get("bp_index") or 0),
                nucleotide.get("direction") or "_",
                int(nucleotide.get("copy_k") or nucleotide.get("ext_k") or 0),
            )
        )

    def palette_for_strand(strand_id: str) -> tuple[float, ...]:
        match = next(
            (
                index
                for index, nucleotide in enumerate(nucleotides)
                if nucleotide.get("strand_id") == strand_id
            ),
            None,
        )
        if match is not None:
            return palette_for_index(match)
        strand = next(
            (strand for strand in design.strands if strand.id == strand_id), None
        )
        if strand is not None:
            return solid_palette(
                _strand_colors(design).get(strand_id, (0.55, 0.62, 0.72))
            )
        return solid_palette((1.0, 1.0, 1.0))

    def append_linker_geometry(*, include_full_bases: bool) -> None:
        """Append canonical overhang-linker visuals to Full or Cylinders."""
        from backend.core.vr_scene_projection import (
            ds_linker_connector_projections,
            ss_linker_projection,
        )

        for connection in getattr(design, "overhang_connections", []):
            if getattr(connection, "linker_type", "ds") == "ss":
                projection = ss_linker_projection(nucleotides, connection)
                if projection is None:
                    continue
                palette = palette_for_strand(projection.strand_id)
                if include_full_bases:
                    for base_index, base in enumerate(projection.bases):
                        aliases = owner_tokens(
                            ("base", f"__lnk__{connection.id}:{base_index}:FORWARD")
                        )
                        bead = rotation @ base.bead_center
                        emit(
                            "P",
                            f"linker:{connection.id}:ss:bead:{base_index}",
                            *bead,
                            0.10,
                            *palette,
                            aliases=aliases,
                        )
                        box(
                            f"linker:{connection.id}:ss:slab:{base_index}",
                            rotation @ base.slab_center,
                            rotation @ base.slab_axis_x,
                            rotation @ base.slab_axis_y,
                            rotation @ base.slab_axis_z,
                            palette,
                            aliases=aliases,
                        )
                points = [rotation @ value for value in projection.backbone_points]
                edge_count = max(len(points) - 1, 1)
                base_count = len(projection.bases)
                for edge_index, (first, second) in enumerate(zip(points, points[1:])):
                    nearest_base = -1 if base_count == 0 else min(
                        int((edge_index + 0.5) * base_count / edge_count),
                        base_count - 1,
                    )
                    emit(
                        "C",
                        f"linker:{connection.id}:ss:backbone:{edge_index}:near:{nearest_base}",
                        *first,
                        *second,
                        0.055,
                        *palette,
                        aliases=(
                            owner_tokens(
                                (
                                    "base",
                                    f"__lnk__{connection.id}:"
                                    f"{nearest_base}:FORWARD",
                                )
                            )
                            if nearest_base >= 0
                            else ()
                        ),
                    )
                continue

            for connector in ds_linker_connector_projections(nucleotides, connection):
                palette = palette_for_strand(connector.strand_id)
                points = [rotation @ value for value in connector.points]
                side = connector.strand_id.rsplit("__", 1)[-1]
                for edge_index, (first, second) in enumerate(zip(points, points[1:])):
                    emit(
                        "C",
                        f"linker:{connection.id}:ds:{side}:connector:{edge_index}",
                        *first,
                        *second,
                        0.065,
                        *palette,
                    )

    def append_flexible_geometry() -> None:
        """Append Full-only fixed-contour flexible ssDNA runs."""
        from backend.core.vr_scene_projection import flexible_segment_projection

        magenta = _rgb("#ff33cc")
        for connection in getattr(design, "flexible_connections", []):
            projection = flexible_segment_projection(
                design, nucleotides, axes, connection
            )
            if projection is None:
                continue
            strand_a, domain_a, helix_a = projection.anchor_a_owner
            strand_b, domain_b, helix_b = projection.anchor_b_owner
            cluster_color = _cluster_color(
                design,
                {
                    "strand_id": strand_a,
                    "domain_index": domain_a,
                    "helix_id": helix_a,
                },
            ) or _cluster_color(
                design,
                {
                    "strand_id": strand_b,
                    "domain_index": domain_b,
                    "helix_id": helix_b,
                },
            )
            palette = (*magenta, *magenta, *(cluster_color or magenta), *magenta)

            def flexible_aliases(base_index: int) -> tuple[str, ...]:
                anchors = getattr(connection, "segment_bead_keys", [])
                if not 0 <= base_index < len(anchors):
                    return ()
                anchor = anchors[base_index]
                strand = next(
                    (item for item in design.strands if item.id == anchor.strand_id),
                    None,
                )
                if (
                    strand is None
                    or not 0 <= anchor.domain_index < len(strand.domains)
                ):
                    return ()
                domain = strand.domains[anchor.domain_index]
                return nucleotide_owner_tokens(
                    {
                        "strand_id": anchor.strand_id,
                        "domain_index": anchor.domain_index,
                        "helix_id": str(domain.helix_id),
                        "bp_index": anchor.bp_index,
                        "direction": str(
                            getattr(anchor.direction, "value", anchor.direction)
                        ),
                    }
                )

            for base_index, base in enumerate(projection.bases):
                aliases = flexible_aliases(base_index)
                bead = rotation @ base.bead_center
                emit(
                    "P",
                    f"flex:{projection.connection_id}:bead:{base_index}",
                    *bead,
                    0.12,
                    *palette,
                    aliases=aliases,
                )
                box(
                    f"flex:{projection.connection_id}:slab:{base_index}",
                    rotation @ base.slab_center,
                    rotation @ base.slab_axis_x,
                    rotation @ base.slab_axis_y,
                    rotation @ base.slab_axis_z,
                    palette,
                    aliases=aliases,
                )
            points = [rotation @ value for value in projection.backbone_points]
            edge_count = max(len(points) - 1, 1)
            base_count = len(projection.bases)
            for edge_index, (first, second) in enumerate(zip(points, points[1:])):
                nearest_base = -1 if base_count == 0 else min(
                    int((edge_index + 0.5) * base_count / edge_count),
                    base_count - 1,
                )
                emit(
                    "C",
                    f"flex:{projection.connection_id}:backbone:{edge_index}:near:{nearest_base}",
                    *first,
                    *second,
                    0.06,
                    *palette,
                    aliases=flexible_aliases(nearest_base),
                )

    def append_unligated_warning(crossover_id: str, center: np.ndarray) -> None:
        """Add a physical amber counterpart of desktop's warning sprite."""
        palette = solid_palette(_rgb("#f5a623"))
        aliases = owner_tokens(("crossover", "crossover", crossover_id))
        top = center + np.array([0.0, 1.8, 0.0])
        left = center + np.array([-1.6, -1.2, 0.0])
        right = center + np.array([1.6, -1.2, 0.0])
        for edge_index, (first, second) in enumerate(
            ((top, left), (left, right), (right, top))
        ):
            emit(
                "C",
                f"warning:{crossover_id}:outline:{edge_index}",
                *first,
                *second,
                0.12,
                *palette,
                aliases=aliases,
            )
        box(
            f"warning:{crossover_id}:stem",
            center + np.array([0.0, 0.25, 0.0]),
            np.array([0.24, 0.0, 0.0]),
            np.array([0.0, 0.90, 0.0]),
            np.array([0.0, 0.0, 0.12]),
            palette,
            aliases=aliases,
        )
        box(
            f"warning:{crossover_id}:dot",
            center + np.array([0.0, -0.72, 0.0]),
            np.array([0.28, 0.0, 0.0]),
            np.array([0.0, 0.28, 0.0]),
            np.array([0.0, 0.0, 0.14]),
            palette,
            aliases=aliases,
        )

    lines = [
        f"NADOCVR 9 {representation} {coloring}",
        "# stable primitive identities, owner aliases, and cluster handles",
    ]
    by_strand: dict[
        str, list[tuple[dict, np.ndarray, tuple[float, ...], str]]
    ] = {}
    identity_palettes: dict[tuple, tuple[float, ...]] = {}
    lines.append("R full")
    lines.extend(
        f"K {token} {nums(*center)}" for token, center in cluster_handles
    )
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
        identity: str,
        center: np.ndarray,
        axis_x: np.ndarray,
        axis_y: np.ndarray,
        axis_z: np.ndarray,
        palette: tuple[float, ...],
        *,
        aliases: tuple[str, ...] = (),
    ) -> None:
        emit(
            "B",
            identity,
            *center,
            *axis_x,
            *axis_y,
            *axis_z,
            *palette,
            aliases=aliases,
        )

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
        primitive_owner = nucleotide_identity(nucleotide)
        aliases = nucleotide_owner_tokens(nucleotide)
        if nucleotide.get("is_five_prime"):
            size = np.identity(3) * 0.18
            box(
                f"{primitive_owner}:backbone",
                backbone,
                *(rotation @ size[:, column] for column in range(3)),
                palette,
                aliases=aliases,
            )
        else:
            emit(
                "P",
                f"{primitive_owner}:backbone",
                *backbone,
                0.10,
                *palette,
                aliases=aliases,
            )
        if strand_id:
            by_strand.setdefault(strand_id, []).append(
                (nucleotide, backbone, palette, primitive_owner)
            )

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
        emit(
            "P",
            f"{nucleotide_identity(nucleotide)}:modification",
            *marker_position,
            0.25,
            *solid_palette(marker_color),
            aliases=nucleotide_owner_tokens(nucleotide),
        )

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
            f"{nucleotide_identity(nucleotide)}:slab",
            rotation @ center,
            rotation @ (tangential * 0.30),
            rotation @ (tangent * 0.06),
            rotation @ (normal * 0.70),
            palette,
            aliases=nucleotide_owner_tokens(nucleotide),
        )
        z_sign = -1.0 if float(np.dot(raw_bead - center, normal)) < 0 else 1.0
        corner = center + tangential * 0.15 + normal * (z_sign * 0.35)
        emit(
            "C",
            f"{nucleotide_identity(nucleotide)}:slab-connector",
            *(rotation @ raw_bead),
            *(rotation @ corner),
            0.025,
            *palette,
            aliases=nucleotide_owner_tokens(nucleotide),
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
        for (
            first_nucleotide,
            first,
            palette,
            first_identity,
        ), (second_nucleotide, second, _, second_identity) in zip(
            strand_nucleotides, strand_nucleotides[1:]
        ):
            if (
                first_nucleotide.get("helix_id") == second_nucleotide.get("helix_id")
                and float(np.linalg.norm(second - first)) <= 5.0
            ):
                arrow_palette = palette_variant(palette, first_nucleotide, "#0288d1")
                first_key = base_key(first_nucleotide)
                second_key = base_key(second_nucleotide)
                bond_aliases = owner_tokens(
                    (
                        "bond",
                        first_key,
                        second_key,
                        (
                            str(first_nucleotide.get("strand_id"))
                            if first_nucleotide.get("strand_id")
                            == second_nucleotide.get("strand_id")
                            else None
                        ),
                    )
                    if first_key and second_key
                    else (),
                    ("base", first_key) if first_key else (),
                    ("base", second_key) if second_key else (),
                    (
                        "strand",
                        str(first_nucleotide.get("strand_id")),
                    )
                    if first_nucleotide.get("strand_id")
                    == second_nucleotide.get("strand_id")
                    and first_nucleotide.get("strand_id")
                    else (),
                )
                emit(
                    "C",
                    f"backbone:{first_identity}~{second_identity}",
                    *first,
                    *second,
                    0.075,
                    *arrow_palette,
                    aliases=bond_aliases,
                )

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
            "crossover",
            str(getattr(xo, "id", f"{xo.half_a.helix_id}:{xo.half_a.index}")),
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
            "ligation",
            str(
                getattr(
                    fl,
                    "id",
                    f"{fl.three_prime_helix_id}:{fl.three_prime_bp}:{fl.five_prime_helix_id}:{fl.five_prime_bp}",
                )
            ),
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
    for (
        connection_kind,
        connection_id,
        first_key,
        second_key,
        extra_bases,
        hidden_periodic,
    ) in explicit_connections:
        if hidden_periodic:
            continue
        first_entry = site_entries.get(first_key)
        second_entry = site_entries.get(second_key)
        if first_entry is None or second_entry is None:
            continue
        first_nucleotide, first, palette = first_entry
        second_nucleotide, second, _ = second_entry
        crossover_aliases = owner_tokens(
            (
                "crossover",
                "forced_ligation" if connection_kind == "ligation" else "crossover",
                connection_id,
            )
        )
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
                projection_id = f"{connection_kind}:{connection_id}:extra:{projection.geometric_index}"
                extra_aliases = owner_tokens(
                    ("base", f"__xb__:{connection_id}:{projection.sim_k}"),
                    (
                        "crossover",
                        (
                            "forced_ligation"
                            if connection_kind == "ligation"
                            else "crossover"
                        ),
                        connection_id,
                    ),
                )
                emit(
                    "P",
                    f"{projection_id}:bead",
                    *bead,
                    0.10,
                    *extra_palette,
                    aliases=extra_aliases,
                )
                box(
                    f"{projection_id}:slab",
                    slab_center,
                    slab_axis_x,
                    slab_axis_y,
                    slab_axis_z,
                    (
                        *slab_palette[0:3],
                        *_BASE_COLORS.get(projection.base, slab_palette[3:6]),
                        *slab_palette[6:],
                    ),
                    aliases=extra_aliases,
                )
                emit(
                    "C",
                    f"{projection_id}:slab-connector",
                    *bead,
                    *slab_corner,
                    0.025,
                    *slab_palette,
                    aliases=extra_aliases,
                )
                backbone_points.append(bead)
            backbone_points.append(second)
            for edge_index, (start, end) in enumerate(
                zip(backbone_points, backbone_points[1:])
            ):
                emit(
                    "C",
                    f"{connection_kind}:{connection_id}:extra-backbone:{edge_index}",
                    *start,
                    *end,
                    0.075,
                    *bead_palette,
                    aliases=crossover_aliases,
                )
            continue
        if first_key[0] == second_key[0]:
            continue
        arc_palette = palette_variant(palette, first_nucleotide, "#0288d1")
        emit(
            "C",
            f"{connection_kind}:{connection_id}:direct",
            *first,
            *second,
            0.025,
            *arc_palette,
            aliases=crossover_aliases,
        )

    unligated_ids = set(unligated_crossover_ids or [])
    for crossover in getattr(design, "crossovers", []):
        if getattr(crossover, "id", None) not in unligated_ids:
            continue
        first_key = (
            str(crossover.half_a.helix_id),
            int(crossover.half_a.index),
            direction_value(crossover.half_a.strand),
        )
        second_key = (
            str(crossover.half_b.helix_id),
            int(crossover.half_b.index),
            direction_value(crossover.half_b.strand),
        )
        first_entry, second_entry = (
            site_entries.get(first_key),
            site_entries.get(second_key),
        )
        if first_entry is None or second_entry is None:
            continue
        append_unligated_warning(
            str(crossover.id), (first_entry[1] + second_entry[1]) * 0.5
        )

    append_linker_geometry(include_full_bases=True)
    append_flexible_geometry()

    def axis_edges(axis: dict):
        """Yield visible axis edges, preferring authoritative domain segments.

        ``deformed_helix_axes`` deliberately emits one segment per occupied
        domain interval. Falling back to the whole sampled shaft when those
        segments exist fills the negative space between domains, which changes
        the topology's visual reading in both Full and cylinder views.
        """
        segments = axis.get("segments")
        if segments is not None:
            for segment_index, segment in enumerate(segments):
                first, second = point(segment.get("start")), point(segment.get("end"))
                if first is not None and second is not None:
                    edge_identity = ":".join(
                        str(value)
                        for value in (
                            "segment",
                            axis.get("helix_id") or "_",
                            segment.get("strand_id") or "_",
                            int(segment.get("domain_index") or 0),
                            int(segment.get("bp_lo", segment_index)),
                            int(segment.get("bp_hi", segment_index)),
                        )
                    )
                    yield first, second, segment, edge_identity
            return
        samples = axis.get("samples") or [axis.get("start"), axis.get("end")]
        for sample_index, (first_raw, second_raw) in enumerate(
            zip(samples, samples[1:])
        ):
            first, second = point(first_raw), point(second_raw)
            if first is not None and second is not None:
                yield (
                    first,
                    second,
                    None,
                    f"axis:{axis.get('helix_id') or '_'}:sample:{sample_index}",
                )

    def append_axes(radius: float = 0.025) -> None:
        palette = solid_palette((0.30, 0.34, 0.42))
        for axis in axes:
            for first, second, _, edge_identity in axis_edges(axis):
                emit(
                    "C",
                    f"{edge_identity}:axis",
                    *first,
                    *second,
                    radius,
                    *palette,
                )

    append_axes(0.05)

    lines.append("R cylinders")
    active_representation = "cylinders"
    lines.extend(
        f"K {token} {nums(*center)}" for token, center in cluster_handles
    )
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
    design_strands_by_id = {strand.id: strand for strand in design.strands}
    emitted_linker_binding_domains: set[tuple[str, int]] = set()
    for axis in axes:
        fallback_palette = first_palette_by_helix.get(
            axis.get("helix_id"), solid_palette((0.45, 0.55, 0.72))
        )
        for first, second, segment, edge_identity in axis_edges(axis):
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
            segment_strand = (
                design_strands_by_id.get(segment.get("strand_id"))
                if segment is not None
                else None
            )
            is_linker_binding = bool(
                segment is not None
                and segment_strand is not None
                and getattr(segment_strand, "strand_type", None) == "linker"
                and not str(axis.get("helix_id") or "").startswith("__lnk__")
            )
            record_type = (
                "H"
                if segment is not None
                and (
                    is_linker_binding
                    or (
                        segment.get("ovhg_id")
                        and str(segment.get("ovhg_id")) not in direct_overhang_ids
                    )
                )
                else "C"
            )
            # Reversing the endpoints reverses the native half-cylinder's
            # deterministic radial basis. The linker complement therefore fills
            # the opposite half of the authored overhang, matching desktop's π
            # axial roll without adding a second orientation convention.
            if is_linker_binding:
                first, second = second, first
                emitted_linker_binding_domains.add(
                    (
                        str(segment.get("strand_id")),
                        int(segment.get("domain_index") or 0),
                    )
                )
            emit(
                record_type,
                f"{edge_identity}:coarse",
                *first,
                *second,
                0.72,
                *palette,
                aliases=(
                    domain_owner_tokens(
                        segment.get("strand_id"),
                        int(segment.get("domain_index") or 0),
                        str(axis.get("helix_id") or ""),
                    )
                    if segment is not None
                    else ()
                ),
            )

    # deformed_helix_axes intentionally deduplicates coincident domain ranges.
    # On a paired overhang that means the authored overhang segment usually wins
    # and its linker-complement domain has no separate axis record. Reuse that
    # exact authoritative interval, reversed, for the complementary half.
    for strand in design.strands:
        if getattr(strand, "strand_type", None) != "linker":
            continue
        for domain_index, domain in enumerate(getattr(strand, "domains", [])):
            if (
                str(domain.helix_id).startswith("__lnk__")
                or (
                    strand.id,
                    domain_index,
                )
                in emitted_linker_binding_domains
            ):
                continue
            domain_lo = min(int(domain.start_bp), int(domain.end_bp))
            domain_hi = max(int(domain.start_bp), int(domain.end_bp))
            axis = next(
                (item for item in axes if item.get("helix_id") == domain.helix_id),
                None,
            )
            if axis is None:
                continue
            palette = palette_for_strand(strand.id)
            for segment in axis.get("segments") or []:
                segment_lo = int(segment.get("bp_lo", domain_lo))
                segment_hi = int(segment.get("bp_hi", domain_hi))
                if segment_lo < domain_lo or segment_hi > domain_hi:
                    continue
                first, second = point(segment.get("start")), point(segment.get("end"))
                if first is None or second is None:
                    continue
                emit(
                    "H",
                    f"linker:{strand.id}:binding:{domain_index}:{segment_lo}:{segment_hi}",
                    *second,
                    *first,
                    0.72,
                    *palette,
                    aliases=domain_owner_tokens(
                        strand.id, domain_index, str(domain.helix_id)
                    ),
                )

    # A ds linker bridge lives on a synthetic helix intentionally omitted from
    # deformed_helix_axes. Desktop reconstructs its coarse cylinder from the
    # mean base/backbone position at the minimum and maximum bridge bp.
    for connection in getattr(design, "overhang_connections", []):
        if getattr(connection, "linker_type", "ds") != "ds":
            continue
        bridge_helix_id = f"__lnk__{connection.id}"
        bridge_nucleotides = [
            nucleotide
            for nucleotide in nucleotides
            if nucleotide.get("helix_id") == bridge_helix_id
        ]
        if len(bridge_nucleotides) < 2:
            continue
        bp_values = [
            int(nucleotide.get("bp_index") or 0) for nucleotide in bridge_nucleotides
        ]

        def bridge_axis_at(bp_index: int) -> np.ndarray | None:
            positions = []
            for nucleotide in bridge_nucleotides:
                if int(nucleotide.get("bp_index") or 0) != bp_index:
                    continue
                raw = nucleotide.get("base_position")
                if raw is None:
                    raw = nucleotide.get("backbone_position")
                position = point(raw)
                if position is not None:
                    positions.append(position)
            return np.mean(positions, axis=0) if positions else None

        first = bridge_axis_at(min(bp_values))
        second = bridge_axis_at(max(bp_values))
        if first is None or second is None:
            continue
        if float(np.linalg.norm(second - first)) < 1e-3:
            # Desktop gives a one-bp bridge a 0.001 nm minimum Y extent so the
            # coarse primitive remains non-degenerate.
            second = first + rotation @ np.array([0.0, 0.001, 0.0])
        palette = palette_for_strand(f"{bridge_helix_id}__a")
        emit(
            "C",
            f"linker:{connection.id}:ds:bridge",
            *first,
            *second,
            0.72,
            *palette,
        )

    # Cylinders retains thin ssDNA and dsDNA connector paths but omits the
    # fine ssDNA bead/slab decoration, matching desktop detail visibility.
    append_linker_geometry(include_full_bases=False)

    if atomistic_model is None:
        raise HTTPException(500, detail="Atomistic VR snapshot was not built.")
    from backend.core.atomistic import (
        CPK_COLOR,
        DEFAULT_CPK_COLOR,
        DEFAULT_VDW_RADIUS,
        VDW_RADIUS,
    )

    strand_colors = _strand_colors(design)
    nucleotide_by_base_key = {
        key: nucleotide
        for nucleotide in nucleotides
        if (key := base_key(nucleotide)) is not None
    }
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

    def atom_base_key(atom) -> str:
        if getattr(atom, "crossover_id", None) is not None and getattr(
            atom, "extra_base_k", None
        ) is not None:
            return f"__xb__:{atom.crossover_id}:{atom.extra_base_k}"
        if getattr(atom, "extension_id", None) is not None and getattr(
            atom, "ext_k", None
        ) is not None:
            return f"__ext_{atom.extension_id}:{atom.ext_k}:{atom.direction}"
        key = f"{atom.helix_id}:{atom.bp_index}:{atom.direction}"
        copy_k = int(getattr(atom, "copy_k", 0) or 0)
        return f"{key}:{copy_k}" if copy_k else key

    atom_connection_aliases: dict[frozenset[str], tuple[str, ...]] = {}
    for connection in getattr(design, "crossovers", []):
        keys = frozenset(
            (
                f"{connection.half_a.helix_id}:{connection.half_a.index}:"
                f"{getattr(connection.half_a.strand, 'value', connection.half_a.strand)}",
                f"{connection.half_b.helix_id}:{connection.half_b.index}:"
                f"{getattr(connection.half_b.strand, 'value', connection.half_b.strand)}",
            )
        )
        atom_connection_aliases[keys] = owner_tokens(
            ("crossover", "crossover", str(connection.id))
        )
    for connection in getattr(design, "forced_ligations", []):
        keys = frozenset(
            (
                f"{connection.three_prime_helix_id}:{connection.three_prime_bp}:"
                f"{getattr(connection.three_prime_direction, 'value', connection.three_prime_direction)}",
                f"{connection.five_prime_helix_id}:{connection.five_prime_bp}:"
                f"{getattr(connection.five_prime_direction, 'value', connection.five_prime_direction)}",
            )
        )
        atom_connection_aliases[keys] = owner_tokens(
            (
                "crossover",
                "forced_ligation",
                str(
                    getattr(
                        connection,
                        "id",
                        f"{connection.three_prime_helix_id}:"
                        f"{connection.three_prime_bp}:"
                        f"{connection.five_prime_helix_id}:"
                        f"{connection.five_prime_bp}",
                    )
                ),
            )
        )

    def atom_crossover_aliases(atom) -> tuple[str, ...]:
        crossover_id = getattr(atom, "crossover_id", None)
        if crossover_id is None:
            return ()
        forced = any(
            str(getattr(connection, "id", "")) == str(crossover_id)
            for connection in getattr(design, "forced_ligations", [])
        )
        return owner_tokens(
            (
                "crossover",
                "forced_ligation" if forced else "crossover",
                str(crossover_id),
            )
        )

    def append_atomistic(name: str, include_points: bool, radius: float) -> None:
        nonlocal active_representation
        lines.append(f"R {name}")
        active_representation = name
        lines.extend(
            f"K {token} {nums(*center)}" for token, center in cluster_handles
        )
        if include_points:
            for atom_index, (atom, position, palette) in enumerate(
                zip(atomistic_model.atoms, atom_positions, atom_palettes)
            ):
                if position is not None:
                    radius = VDW_RADIUS.get(atom.element, DEFAULT_VDW_RADIUS) * 0.55
                    key = atom_base_key(atom)
                    nucleotide = nucleotide_by_base_key.get(key)
                    aliases = (
                        nucleotide_owner_tokens(nucleotide)
                        if nucleotide is not None
                        else owner_tokens(("base", key))
                    )
                    emit(
                        "P",
                        f"atom:{atom_index}:base:{key}:{atom.element}",
                        *position,
                        radius,
                        *palette,
                        aliases=aliases,
                    )
        for first_index, second_index in atomistic_model.bonds:
            first, second = atom_positions[first_index], atom_positions[second_index]
            if first is None or second is None:
                continue
            palette = tuple(
                (a + b) * 0.5
                for a, b in zip(atom_palettes[first_index], atom_palettes[second_index])
            )
            first_atom = atomistic_model.atoms[first_index]
            second_atom = atomistic_model.atoms[second_index]
            first_key = atom_base_key(first_atom)
            second_key = atom_base_key(second_atom)
            common_strand = (
                str(first_atom.strand_id)
                if first_atom.strand_id == second_atom.strand_id
                and first_atom.strand_id
                else None
            )
            bond_aliases = owner_tokens(
                (
                    "bond",
                    first_key,
                    second_key,
                    common_strand,
                )
                if first_key != second_key
                else (),
                ("base", first_key),
                ("base", second_key),
                ("strand", common_strand) if common_strand else (),
            )
            bond_aliases = tuple(
                dict.fromkeys(
                    (
                        *bond_aliases,
                        *atom_connection_aliases.get(
                            frozenset((first_key, second_key)), ()
                        ),
                        *atom_crossover_aliases(first_atom),
                        *atom_crossover_aliases(second_atom),
                    )
                )
            )
            emit(
                "C",
                "atom-bond:bases:"
                f"{atom_base_key(atomistic_model.atoms[first_index])}~"
                f"{atom_base_key(atomistic_model.atoms[second_index])}:atoms:"
                f"{min(first_index, second_index)}-{max(first_index, second_index)}",
                *first,
                *second,
                radius,
                *palette,
                aliases=bond_aliases,
            )
        append_axes(0.05)

    append_atomistic("ballstick", True, 0.035)
    append_atomistic("stick", False, 0.055)

    if not any(line.startswith(("P ", "C ", "B ")) for line in lines):
        raise HTTPException(
            409, detail="The active design contains no display geometry."
        )
    return "\n".join(lines) + "\n"


def _expanded_helix_offsets(design, spacing_nm: float = 5.0) -> dict[str, np.ndarray]:
    """Mirror Expanded Quick View's per-helix lateral translations.

    This is display-only geometry.  The 2.25 nm reference spacing and centroid
    expansion intentionally match ``frontend/src/scene/expanded_spacing.js``.
    """
    helices = list(getattr(design, "helices", []) or [])
    if not helices:
        return {}
    first = helices[0]
    start = np.asarray(
        [first.axis_start.x, first.axis_start.y, first.axis_start.z], dtype=float
    )
    end = np.asarray(
        [first.axis_end.x, first.axis_end.y, first.axis_end.z], dtype=float
    )
    axis_index = int(np.argmax(np.abs(end - start)))
    lateral_indices = [index for index in range(3) if index != axis_index]
    starts = np.asarray(
        [
            [helix.axis_start.x, helix.axis_start.y, helix.axis_start.z]
            for helix in helices
        ],
        dtype=float,
    )
    centroid = np.mean(starts[:, lateral_indices], axis=0)
    scale_delta = float(spacing_nm) / 2.25 - 1.0
    result: dict[str, np.ndarray] = {}
    for helix, position in zip(helices, starts):
        offset = np.zeros(3, dtype=float)
        offset[lateral_indices] = (
            position[lateral_indices] - centroid
        ) * scale_delta
        result[str(helix.id)] = offset
    return result


def _expanded_scene_inputs(design, nucleotides, axes, atomistic_model):
    """Translate immutable scene inputs to Expanded Quick View's target pose."""
    offsets = _expanded_helix_offsets(design)
    expanded_nucleotides = copy.deepcopy(nucleotides)

    extension_parents: dict[str, str] = {}
    strands = {str(strand.id): strand for strand in getattr(design, "strands", [])}
    for extension in getattr(design, "extensions", []) or []:
        strand = strands.get(str(extension.strand_id))
        domains = list(getattr(strand, "domains", []) or []) if strand else []
        if not domains:
            continue
        domain = domains[0] if extension.end == "five_prime" else domains[-1]
        extension_parents[f"__ext_{extension.id}"] = str(domain.helix_id)

    def owner_offset(helix_id) -> np.ndarray:
        key = str(helix_id or "")
        return offsets.get(extension_parents.get(key, key), np.zeros(3, dtype=float))

    for nucleotide in expanded_nucleotides:
        offset = owner_offset(nucleotide.get("helix_id"))
        for field in ("backbone_position", "base_position"):
            value = nucleotide.get(field)
            if isinstance(value, (list, tuple)) and len(value) == 3:
                nucleotide[field] = (np.asarray(value, dtype=float) + offset).tolist()

    expanded_axes = copy.deepcopy(axes)
    for axis in expanded_axes:
        offset = owner_offset(axis.get("helix_id"))

        def translate(value):
            if isinstance(value, (list, tuple)) and len(value) == 3:
                return (np.asarray(value, dtype=float) + offset).tolist()
            return value

        for field in ("start", "end"):
            if field in axis:
                axis[field] = translate(axis[field])
        if isinstance(axis.get("samples"), list):
            axis["samples"] = [translate(value) for value in axis["samples"]]
        for segment in axis.get("segments") or []:
            for field in ("start", "end"):
                if field in segment:
                    segment[field] = translate(segment[field])

    expanded_atomistic = copy.deepcopy(atomistic_model)
    for atom in expanded_atomistic.atoms:
        offset = owner_offset(atom.helix_id)
        aux_helix_id = getattr(atom, "aux_helix_id", "")
        if aux_helix_id:
            aux_offset = owner_offset(aux_helix_id)
            weight = float(getattr(atom, "aux_t", 0.0))
            offset = offset * (1.0 - weight) + aux_offset * weight
        atom.x += float(offset[0])
        atom.y += float(offset[1])
        atom.z += float(offset[2])
    return expanded_nucleotides, expanded_axes, expanded_atomistic


def _bundle_expanded_scene(natural_text: str, expanded_text: str) -> str:
    """Combine two identity/alias/handle-equivalent v9 scenes into one contract."""
    natural_lines = natural_text.splitlines()
    expanded_lines = expanded_text.splitlines()
    natural_header = natural_lines[0].split()
    expanded_header = expanded_lines[0].split()
    if natural_header != expanded_header or natural_header[0:2] != ["NADOCVR", "9"]:
        raise HTTPException(500, detail="Expanded VR scene headers do not match.")

    def blocks(lines: list[str]) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        active = None
        for line in lines[1:]:
            fields = line.split()
            if not fields or fields[0] == "#":
                continue
            if fields[0] == "R":
                active = fields[1]
                result[active] = []
            elif active is not None:
                result[active].append(line)
        return result

    natural_blocks, expanded_blocks = blocks(natural_lines), blocks(expanded_lines)
    if set(natural_blocks) != set(expanded_blocks):
        raise HTTPException(500, detail="Expanded VR representations do not match.")
    output = [
        f"NADOCVR 9 {natural_header[2]} {natural_header[3]}",
        "# natural and expanded poses share identities, aliases, and cluster handles",
    ]
    for representation, natural_records in natural_blocks.items():
        expanded_records = expanded_blocks[representation]
        primitive_types = {"P", "C", "H", "B"}
        natural_keys = [
            (line.split()[0], line.split()[1])
            for line in natural_records
            if line.split()[0] in primitive_types
        ]
        expanded_keys = [
            (line.split()[0], line.split()[1])
            for line in expanded_records
            if line.split()[0] in primitive_types
        ]
        if natural_keys != expanded_keys:
            raise HTTPException(
                500,
                detail=f"Expanded VR primitive identities differ in {representation}.",
            )
        natural_aliases = [line for line in natural_records if line.startswith("A ")]
        expanded_aliases = [line for line in expanded_records if line.startswith("A ")]
        if natural_aliases != expanded_aliases:
            raise HTTPException(
                500,
                detail=f"Expanded VR primitive owner aliases differ in {representation}.",
            )
        natural_handles = [line.split()[1] for line in natural_records if line.startswith("K ")]
        expanded_handles = [line.split()[1] for line in expanded_records if line.startswith("K ")]
        if natural_handles != expanded_handles:
            raise HTTPException(
                500,
                detail=f"Expanded VR cluster handles differ in {representation}.",
            )
        output.append(f"R {representation}")
        output.extend(natural_records)
        output.append(f"E {representation}")
        output.extend(expanded_records)
    return "\n".join(output) + "\n"


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
    from backend.api.crud import unligated_crossover_ids

    natural_scene = _serialize_scene(
        design,
        nucleotides,
        axes,
        body.camera,
        body.representation,
        body.coloring,
        atomistic_model,
        unligated_crossover_ids(design),
    )
    expanded_nucleotides, expanded_axes, expanded_atomistic = _expanded_scene_inputs(
        design, nucleotides, axes, atomistic_model
    )
    expanded_scene = _serialize_scene(
        design,
        expanded_nucleotides,
        expanded_axes,
        body.camera,
        body.representation,
        body.coloring,
        expanded_atomistic,
        unligated_crossover_ids(design),
    )
    return _bundle_expanded_scene(natural_scene, expanded_scene)


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


def _cleanup_after_process(
    process: subprocess.Popen,
    scene_path: Path,
    event_path: Path,
    feedback_path: Path,
) -> None:
    process.wait()
    scene_path.unlink(missing_ok=True)
    event_path.unlink(missing_ok=True)
    feedback_path.unlink(missing_ok=True)
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


def _event_payload(state: dict | None) -> dict:
    """Read one bounded, overwrite-in-place native event record."""
    if not state or not state.get("event_path"):
        return {
            "sequence": 0,
            "hover_identity": None,
            "select_sequence": 0,
            "select_identity": None,
            "level_sequence": 0,
            "selection_level": "default",
            "tool_sequence": 0,
            "tool_mode": "inspect",
            "tool_action": "activate",
        }
    path = Path(state["event_path"])
    try:
        if path.stat().st_size > 4096:
            raise ValueError("event record is too large")
        event = json.loads(path.read_text())
        sequence = int(event.get("sequence", 0))
        hover_identity = event.get("hover_identity")
        select_sequence = int(event.get("select_sequence", 0))
        select_identity = event.get("select_identity")
        level_sequence = int(event.get("level_sequence", 0))
        selection_level = event.get("selection_level", "default")
        tool_sequence = int(event.get("tool_sequence", 0))
        tool_mode = event.get("tool_mode", "inspect")
        tool_action = event.get("tool_action", "activate")
        identities = (hover_identity, select_identity)
        if (
            sequence < 0
            or select_sequence < 0
            or level_sequence < 0
            or tool_sequence < 0
            or any(value is not None and not isinstance(value, str) for value in identities)
            or selection_level
            not in {"default", "cluster", "strand", "domain", "end", "xover", "base"}
            or tool_mode
            not in {"inspect", "move_rotate", "extrude", "twist", "bend"}
            or tool_action
            not in {"activate", "preview", "confirm", "cancel", "undo"}
        ):
            raise ValueError("invalid event record")
        if any(isinstance(value, str) and len(value) > 2048 for value in identities):
            raise ValueError("event identity is too large")
        return {
            "sequence": sequence,
            "hover_identity": hover_identity,
            "select_sequence": select_sequence,
            "select_identity": select_identity,
            "level_sequence": level_sequence,
            "selection_level": selection_level,
            "tool_sequence": tool_sequence,
            "tool_mode": tool_mode,
            "tool_action": tool_action,
        }
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        # A truncate/write can briefly expose an incomplete record. Pollers keep
        # their prior sequence and recover on the next read.
        return {
            "sequence": 0,
            "hover_identity": None,
            "select_sequence": 0,
            "select_identity": None,
            "level_sequence": 0,
            "selection_level": "default",
            "tool_sequence": 0,
            "tool_mode": "inspect",
            "tool_action": "activate",
        }


@router.get("/vr/status")
def vr_status(request: Request) -> dict:
    _require_local(request)
    return _status_payload()


@router.get("/vr/event")
def vr_event(request: Request) -> dict:
    _require_local(request)
    return _event_payload(_read_state())


def _write_feedback(state: dict | None, body: VRFeedbackRequest) -> None:
    """Atomically publish one bounded canonical-selection acknowledgement."""
    if not state or not state.get("feedback_path"):
        raise HTTPException(409, detail="Native VR is not running.")
    identity = body.identity or "-"
    owner_tokens = body.owner_tokens if body.selected else []
    selection_kind = body.selection_kind if body.selected else "none"
    record = (
        f"NADOCVR_FEEDBACK 3 {body.select_sequence} "
        f"{int(body.accepted)} {int(body.selected)} "
        f"{body.selection_level} {selection_kind} {identity} {len(owner_tokens)}"
        + (f" {' '.join(owner_tokens)}" if owner_tokens else "")
        + "\n"
    )
    values = [identity, *owner_tokens]
    if (body.selected and selection_kind == "none") or len(record.encode()) > 4096 or any(
        any(character.isspace() for character in value) or len(value) > 2048
        for value in values
    ):
        raise HTTPException(422, detail="Invalid VR feedback identity.")
    path = Path(state["feedback_path"])
    temporary = path.with_name(f"{path.name}.next")
    with _FEEDBACK_LOCK:
        try:
            temporary.write_text(record)
            temporary.chmod(0o600)
            os.replace(temporary, path)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise HTTPException(503, detail="Could not acknowledge VR selection.") from exc


@router.post("/vr/feedback")
def vr_feedback(body: VRFeedbackRequest, request: Request) -> dict:
    _require_local(request)
    _write_feedback(_read_state(), body)
    return {"acknowledged": True, "select_sequence": body.select_sequence}


def _viewer_command(
    scene_path: Path,
    event_path: Path,
    feedback_path: Path,
    body: VRLaunchRequest,
) -> list[str]:
    command = [
        str(_VIEWER),
        str(scene_path),
        "--events",
        str(event_path),
        "--selection-level",
        body.selection_level,
        "--feedback",
        str(feedback_path),
    ]
    for token in body.selected_owner_tokens:
        command.extend(["--selected-owner", token])
    command.extend(["--selected-kind", body.selected_selection_kind])
    return command


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

    if bool(body.selected_owner_tokens) != (
        body.selected_selection_kind != "none"
    ) or any(
        not token
        or len(token) > 2048
        or any(character.isspace() for character in token)
        for token in body.selected_owner_tokens
    ):
        raise HTTPException(422, detail="Invalid initial VR selection identity.")

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
        with tempfile.NamedTemporaryFile(
            mode="w",
            prefix="nadoc-vr-event-",
            suffix=".json",
            delete=False,
        ) as event_file:
            event_file.write(
                '{"sequence":0,"hover_identity":null,'
                '"select_sequence":0,"select_identity":null,'
                f'"level_sequence":0,"selection_level":"{body.selection_level}",'
                '"tool_sequence":0,"tool_mode":"inspect",'
                '"tool_action":"activate"}'
            )
            event_path = Path(event_file.name)
        event_path.chmod(0o600)
        with tempfile.NamedTemporaryFile(
            mode="w",
            prefix="nadoc-vr-feedback-",
            suffix=".txt",
            delete=False,
        ) as feedback_file:
            feedback_file.write(
                "NADOCVR_FEEDBACK 2 0 0 0 "
                f"{body.selection_level} - 0\n"
            )
            feedback_path = Path(feedback_file.name)
        feedback_path.chmod(0o600)

        log = _LOG_PATH.open("ab")
        try:
            process = subprocess.Popen(
                _viewer_command(scene_path, event_path, feedback_path, body),
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
            event_path.unlink(missing_ok=True)
            feedback_path.unlink(missing_ok=True)
            raise HTTPException(
                503, detail=f"Could not launch VR viewer: {exc}"
            ) from exc
        finally:
            log.close()

        # Catch immediate loader/display errors and return their last log line.
        time.sleep(0.15)
        if process.poll() is not None:
            scene_path.unlink(missing_ok=True)
            event_path.unlink(missing_ok=True)
            feedback_path.unlink(missing_ok=True)
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
            "event_path": str(event_path),
            "feedback_path": str(feedback_path),
            "started_at": time.time(),
        }
        _write_state(state)
        threading.Thread(
            target=_cleanup_after_process,
            args=(process, scene_path, event_path, feedback_path),
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
