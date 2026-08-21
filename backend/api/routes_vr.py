"""Local native-OpenXR companion lifecycle for Linux VR.

Stock Linux browsers do not currently bridge WebXR to SteamVR. These endpoints
are therefore deliberately localhost-only: they snapshot the active NADOC part
into a compact read-only scene file and launch/stop the bundled native viewer.
No design data is mutated and no shell command is constructed from request data.
"""

from __future__ import annotations

import copy
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from typing import Callable, Literal, Optional
from urllib.parse import quote, urlparse

import numpy as np
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from backend.api import state as design_state
from backend.core.constants import STAPLE_PALETTE
from backend.core.models import MODIFICATION_COLORS
from backend.core.vr_scene_projection import (
    normalize_geometry_copy_indices,
    strand_nucleotide_order_key,
)

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
_TOOL_FEEDBACK_LOCK = threading.Lock()
_TOOL_EXECUTION_FEEDBACK_LOCK = threading.Lock()
_JOB_FEEDBACK_LOCK = threading.Lock()
_VISUALIZATION_FEEDBACK_LOCK = threading.Lock()

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


class VRJobSnapshotRow(BaseModel):
    """One bounded read-only row from the canonical unified jobs list."""

    job_id: str = Field(min_length=1, max_length=128)
    parent_job_id: Optional[str] = Field(default=None, max_length=128)
    engine: str = Field(min_length=1, max_length=24, pattern=r"^[a-z0-9_-]+$")
    status: str = Field(min_length=1, max_length=32, pattern=r"^[a-z0-9_-]+$")
    label: str = Field(min_length=1, max_length=48)
    status_text: str = Field(min_length=1, max_length=96)
    depth: int = Field(ge=0, le=8)
    progress_permille: int = Field(ge=0, le=1000)
    viewable: bool = False
    stale: bool = False
    archived: bool = False


class VRVisualizationPoint(BaseModel):
    """One live base/atom position and optional exact Full-slab transform."""

    owner_token: str = Field(min_length=1, max_length=2048)
    position: list[float] = Field(min_length=3, max_length=3)
    color: Optional[int] = Field(default=None, ge=0, le=0xFFFFFF)
    slab_center: Optional[list[float]] = Field(default=None, min_length=3, max_length=3)
    slab_axis_x: Optional[list[float]] = Field(default=None, min_length=3, max_length=3)
    slab_axis_y: Optional[list[float]] = Field(default=None, min_length=3, max_length=3)
    slab_axis_z: Optional[list[float]] = Field(default=None, min_length=3, max_length=3)


class VRLaunchRequest(BaseModel):
    browser_requested_at_ms: Optional[float] = Field(default=None, gt=0, lt=1e15)
    job_snapshot_ms: Optional[float] = Field(default=None, ge=0, lt=1e6)
    camera: Optional[VRCamera] = None
    measured_positioning: bool = False
    assembly_active: bool = False
    representation: Literal["cylinders", "full", "ballstick", "stick"] = "full"
    coloring: Literal["strand", "base", "cluster", "cpk"] = "strand"
    show_periodic_seam_arcs: bool = False
    selection_level: Literal[
        "default", "cluster", "strand", "domain", "end", "xover", "base"
    ] = "default"
    selected_owner_tokens: list[str] = Field(default_factory=list, max_length=8)
    selected_selection_kind: SelectionKind = "none"
    jobs_snapshot_available: bool = False
    jobs_snapshot_total: int = Field(default=0, ge=0, le=1_000_000)
    jobs: list[VRJobSnapshotRow] = Field(default_factory=list, max_length=64)
    active_job_id: Optional[str] = Field(default=None, max_length=128)
    active_job_engine: Optional[str] = Field(
        default=None, max_length=24, pattern=r"^[a-z0-9_-]+$"
    )
    visualization_mode: str = Field(
        default="none", min_length=1, max_length=32, pattern=r"^[a-z0-9_-]+$"
    )
    visualization_points: list[VRVisualizationPoint] = Field(
        default_factory=list, max_length=1_000_000
    )


class VRJobsFeedbackRequest(BaseModel):
    """One successful refresh of the desktop-authoritative unified job list."""

    jobs_snapshot_total: int = Field(default=0, ge=0, le=1_000_000)
    jobs: list[VRJobSnapshotRow] = Field(default_factory=list, max_length=64)
    active_job_id: Optional[str] = Field(default=None, max_length=128)
    active_job_engine: Optional[str] = Field(
        default=None, max_length=24, pattern=r"^[a-z0-9_-]+$"
    )
    representation: Literal["cylinders", "full", "ballstick", "stick"] = "full"
    coloring: Literal["strand", "base", "cluster", "cpk"] = "strand"
    visualization_mode: str = Field(
        default="none", min_length=1, max_length=32, pattern=r"^[a-z0-9_-]+$"
    )
    visualization_points: list[VRVisualizationPoint] = Field(
        default_factory=list, max_length=1_000_000
    )


class VRVisualizationFeedbackRequest(BaseModel):
    representation: Literal["cylinders", "full", "ballstick", "stick"] = "full"
    coloring: Literal["strand", "base", "cluster", "cpk"] = "strand"
    visualization_mode: str = Field(
        default="none", min_length=1, max_length=32, pattern=r"^[a-z0-9_-]+$"
    )
    visualization_points: list[VRVisualizationPoint] = Field(
        default_factory=list, max_length=1_000_000
    )


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
    selected_identities: list[str] = Field(default_factory=list, max_length=16)
    selected_owner_tokens: list[str] = Field(default_factory=list, max_length=16)


VRToolContextReason = Literal[
    "resolved",
    "end_selection_required",
    "invalid_end_ref",
    "loop_copy_not_supported",
    "synthetic_end_not_supported",
    "ambiguous_live_end",
    "stale_live_end",
    "not_terminal",
    "helix_not_live",
    "ambiguous_continuation_face",
    "no_continuation_face",
    "invalid_continuation_face",
]


class VRToolFeedbackRequest(BaseModel):
    tool_config_sequence: int = Field(ge=1)
    target_identity: str = Field(min_length=1, max_length=2048)
    target_kind: SelectionKind
    resolved: bool = False
    reason: VRToolContextReason
    face_position: Optional[list[float]] = Field(
        default=None, min_length=3, max_length=3
    )
    face_normal: Optional[list[float]] = Field(
        default=None, min_length=3, max_length=3
    )
    preview_origin: Optional[list[float]] = Field(
        default=None, min_length=3, max_length=3
    )
    expanded_face_position: Optional[list[float]] = Field(
        default=None, min_length=3, max_length=3
    )
    expanded_face_normal: Optional[list[float]] = Field(
        default=None, min_length=3, max_length=3
    )
    expanded_preview_origin: Optional[list[float]] = Field(
        default=None, min_length=3, max_length=3
    )
    occupied: bool = False
    deformed: bool = False
    footprint_resolved: bool = False
    footprint_lattice_type: Optional[Literal["HONEYCOMB", "SQUARE"]] = None
    footprint_cell: Optional[list[int]] = Field(
        default=None, min_length=2, max_length=2
    )


class VRToolPreflightFeedbackRequest(BaseModel):
    preflight_sequence: int = Field(ge=1, le=2**53 - 1)
    tool_config_sequence: int = Field(ge=1)
    target_identity: Optional[str] = Field(default=None, max_length=2048)
    target_kind: SelectionKind
    tool_mode: Literal["extrude", "twist", "bend"]
    status: Literal["waiting", "ok", "warn", "block", "error"]
    reason: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$")


class VRToolExecutionFeedbackRequest(BaseModel):
    """Browser-authoritative acknowledgement for one native tool action."""

    execution_sequence: int = Field(ge=1, le=2**53 - 1)
    tool_sequence: int = Field(ge=1, le=2**53 - 1)
    tool_mode: Literal["move_rotate", "extrude"]
    tool_action: Literal["confirm", "undo"]
    target_identity: str = Field(min_length=1, max_length=2048)
    target_kind: SelectionKind
    status: Literal["pending", "succeeded", "failed", "refused"]
    reason: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$")
    feature_log_entry_id: Optional[str] = Field(default=None, max_length=128)


VRPlanePickReason = Literal[
    "resolved",
    "invalid_primitive",
    "ambiguous_primitive",
    "synthetic_not_supported",
    "out_of_range",
    "plane_frame_unavailable",
    "stale_target",
]


class VRPlaneFeedbackRequest(BaseModel):
    plane_pick_sequence: int = Field(ge=1)
    tool_config_sequence: int = Field(ge=1)
    target_identity: str = Field(min_length=1, max_length=2048)
    target_kind: SelectionKind
    picked_identity: str = Field(min_length=1, max_length=2048)
    plane_slot: Literal["a", "b"]
    resolved: bool = False
    reason: VRPlanePickReason
    plane_bp: Optional[int] = Field(default=None, ge=-(2**31 - 1), le=2**31 - 1)
    plane_center: Optional[list[float]] = Field(
        default=None, min_length=3, max_length=3
    )
    plane_normal: Optional[list[float]] = Field(
        default=None, min_length=3, max_length=3
    )
    plane_half_extent_nm: Optional[float] = Field(default=None, gt=0, le=1e6)
    expanded_plane_center: Optional[list[float]] = Field(
        default=None, min_length=3, max_length=3
    )
    expanded_plane_normal: Optional[list[float]] = Field(
        default=None, min_length=3, max_length=3
    )
    expanded_plane_half_extent_nm: Optional[float] = Field(
        default=None, gt=0, le=1e6
    )


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
    result = {
        index: str(base).upper()
        for index, nucleotide in enumerate(nucleotides)
        if (base := nucleotide.get("nucleobase"))
        and str(base).upper() in _BASE_COLORS
    }
    by_strand: dict[str, list[tuple[int, dict]]] = {}
    for index, nucleotide in enumerate(nucleotides):
        strand_id = nucleotide.get("strand_id")
        # Extension sequence is independent of Strand.sequence and is already
        # carried as authoritative per-bead ``nucleobase`` geometry metadata.
        if strand_id and nucleotide.get("extension_id") is None:
            by_strand.setdefault(strand_id, []).append((index, nucleotide))
    sequences = {
        strand.id: strand.sequence for strand in design.strands if strand.sequence
    }
    for strand_id, entries in by_strand.items():
        sequence = sequences.get(strand_id)
        if not sequence:
            continue
        entries.sort(key=lambda item: strand_nucleotide_order_key(item[1]))
        for offset, (index, _) in enumerate(entries):
            if (
                index not in result
                and offset < len(sequence)
                and sequence[offset].upper() in _BASE_COLORS
            ):
                result[index] = sequence[offset].upper()

    overhangs = {
        str(overhang.id): overhang
        for overhang in getattr(design, "overhangs", [])
    }
    by_overhang: dict[str, list[tuple[int, dict]]] = {}
    for index, nucleotide in enumerate(nucleotides):
        overhang_id = nucleotide.get("overhang_id")
        if overhang_id is not None:
            by_overhang.setdefault(str(overhang_id), []).append((index, nucleotide))
    from backend.core.sequences import _assemble_overhang_5to3

    for overhang_id, entries in by_overhang.items():
        overhang = overhangs.get(overhang_id)
        if overhang is None:
            continue
        entries.sort(key=lambda item: strand_nucleotide_order_key(item[1]))
        sequence = "".join(_assemble_overhang_5to3(overhang, len(entries)))
        for offset, (index, _) in enumerate(entries):
            if (
                index not in result
                and offset < len(sequence)
                and sequence[offset].upper() in _BASE_COLORS
            ):
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
    domain_keys, exclusive_helices = _cluster_membership_facts(cluster, strands)
    return (
        nucleotide.get("strand_id"),
        int(nucleotide.get("domain_index") or 0),
    ) in domain_keys or nucleotide.get("helix_id") in exclusive_helices


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
            domain_keys, exclusive_helices = _cluster_membership_facts(cluster, strands)

            def contains(nucleotide):
                return (
                    nucleotide.get("strand_id"),
                    int(nucleotide.get("domain_index") or 0),
                ) in domain_keys or nucleotide.get("helix_id") in exclusive_helices
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


_SCENE_MANIFEST_CATEGORIES = ("primitive", "D", "A", "T", "W", "K", "J")


class _SceneLineEmitter:
    """Optional line sink plus constant-memory natural/Expanded parity digest."""

    def __init__(self, writer: Callable[[str], None] | None = None):
        self._writer = writer
        self._lines: list[str] | None = [] if writer is None else None
        self._active: str | None = None
        self._digests: dict[str, dict[str, object]] = {}
        self.has_visible = False

    def _category(self, representation: str, category: str):
        categories = self._digests.setdefault(representation, {})
        entry = categories.get(category)
        if entry is None:
            entry = [hashlib.blake2b(digest_size=20), 0]
            categories[category] = entry
        return entry

    def append(self, line: str) -> None:
        if self._lines is not None:
            self._lines.append(line)
        else:
            assert self._writer is not None
            self._writer(line)
        fields = line.split()
        if not fields or fields[0] == "#" or fields[0] == "NADOCVR":
            return
        record_type = fields[0]
        if record_type == "R":
            self._active = fields[1]
            self._digests.setdefault(self._active, {})
            return
        if self._active is None:
            return
        if record_type in {"P", "C", "H", "B"}:
            category = "primitive"
            payload = f"{record_type} {fields[1]}"
            self.has_visible = True
        elif record_type in _SCENE_MANIFEST_CATEGORIES:
            category = record_type
            payload = (
                " ".join(fields[:4])
                if record_type == "J"
                else " ".join(fields[:2])
                if record_type == "K"
                else line
            )
        else:
            return
        digest, count = self._category(self._active, category)
        digest.update(payload.encode())
        digest.update(b"\n")
        self._category(self._active, category)[1] = count + 1

    def extend(self, lines) -> None:
        for line in lines:
            self.append(line)

    def text(self) -> str:
        if self._lines is None:
            raise RuntimeError("Streaming scene emitter has no text buffer")
        return "\n".join(self._lines) + "\n"

    def manifest(self) -> dict[str, dict[str, tuple[int, str]]]:
        return {
            representation: {
                category: (entry[1], entry[0].hexdigest())
                for category, entry in categories.items()
            }
            for representation, categories in self._digests.items()
        }


def _serialize_scene(
    design,
    nucleotides: list[dict],
    axes: list[dict],
    camera=None,
    representation: str = "full",
    coloring: str = "strand",
    atomistic_model=None,
    unligated_crossover_ids: list[str] | None = None,
    show_periodic_seam_arcs: bool = False,
    line_writer: Callable[[str], None] | None = None,
) -> str | dict[str, dict[str, tuple[int, str]]]:
    """Create the deliberately trivial line-oriented format read by the C++ viewer."""
    # Stable IDs and aliases need the loop-copy identity that the canonical
    # geometry transport deliberately leaves implicit in emission order.
    nucleotides = normalize_geometry_copy_indices(nucleotides)

    rotation = _view_rotation(camera)
    cluster_handles = _cluster_gizmo_handle_centers(design, nucleotides, rotation)
    cluster_transform_tokens = tuple(token for token, _ in cluster_handles)
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
                f"__xb__:{nucleotide['crossover_id']}:{int(nucleotide['extra_base_k'])}"
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
        extension_id = nucleotide.get("extension_id")
        if extension_id is not None:
            refs.append(("extension", str(extension_id)))
        overhang_id = nucleotide.get("overhang_id")
        if overhang_id is not None:
            refs.append(("overhang", str(overhang_id)))
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
        strand_id: str | None,
        domain_index: int,
        helix_id: str | None,
        overhang_id: str | None = None,
    ) -> tuple[str, ...]:
        if not strand_id:
            return ()
        nucleotide = {
            "strand_id": str(strand_id),
            "domain_index": int(domain_index),
            "helix_id": helix_id or "",
        }
        refs: list[tuple] = []
        if overhang_id:
            refs.append(("overhang", str(overhang_id)))
        refs.extend(
            [
                ("domain", str(strand_id), int(domain_index)),
                ("strand", str(strand_id)),
            ]
        )
        for cluster in _selection_clusters(design, nucleotide):
            if len(refs) >= 8:
                break
            refs.append(("cluster", str(cluster.id)))
        return owner_tokens(*refs)

    def nucleotide_tool_handles() -> tuple[tuple[str, str, np.ndarray], ...]:
        """Representation-independent pivots for residue-backed tool scopes.

        These use the same live backbone centroids as the desktop nucleotide
        transform tool. Cluster pivots remain in legacy ``K`` records; atom
        pivots are added only to the atomistic representation blocks below.
        """
        grouped: dict[tuple[str, str], list[np.ndarray]] = {}
        for nucleotide in nucleotides:
            raw = nucleotide.get("backbone_position")
            if not isinstance(raw, (list, tuple)) or len(raw) != 3:
                continue
            position = np.asarray(raw, dtype=float)
            if not np.all(np.isfinite(position)):
                continue
            key = base_key(nucleotide)
            if key:
                grouped.setdefault(
                    (selection_token("base", key), "base"), []
                ).append(position)
                if nucleotide.get("is_five_prime") or nucleotide.get(
                    "is_three_prime"
                ):
                    grouped.setdefault(
                        (selection_token("end", key), "end"), []
                    ).append(position)
            strand_id = nucleotide.get("strand_id")
            if strand_id:
                grouped.setdefault(
                    (
                        selection_token(
                            "domain",
                            str(strand_id),
                            int(nucleotide.get("domain_index") or 0),
                        ),
                        "domain",
                    ),
                    [],
                ).append(position)
                grouped.setdefault(
                    (selection_token("strand", str(strand_id)), "strand"), []
                ).append(position)
            crossover_id = nucleotide.get("crossover_id")
            if crossover_id is not None:
                forced = any(
                    str(getattr(connection, "id", "")) == str(crossover_id)
                    for connection in getattr(design, "forced_ligations", [])
                )
                grouped.setdefault(
                    (
                        selection_token(
                            "crossover",
                            "forced_ligation" if forced else "crossover",
                            str(crossover_id),
                        ),
                        "crossover",
                    ),
                    [],
                ).append(position)
        return tuple(
            (token, kind, rotation @ np.mean(positions, axis=0))
            for (token, kind), positions in sorted(grouped.items())
        )

    # Full-view crossover inserts are projection-owned rather than ordinary entries in
    # ``nucleotides``.  Their Base handles are appended lazily when that projection is
    # built below, then reused by every later representation (including Stick).
    tool_handles = list(nucleotide_tool_handles())
    tool_handle_tokens = {
        *(token for token, _ in cluster_handles),
        *(token for token, _, _ in tool_handles),
    }
    owner_token_ids: dict[str, str] = {}
    owner_id_tokens: dict[str, str] = {}
    declared_owner_tokens: set[str] = set()

    def register_owner_token(token: str) -> str:
        cached = owner_token_ids.get(token)
        if cached is not None:
            return cached
        scope_id = hashlib.blake2s(token.encode(), digest_size=8).hexdigest()
        previous = owner_id_tokens.setdefault(scope_id, token)
        if previous != token:
            raise HTTPException(500, detail="VR owner token ID collision.")
        owner_token_ids[token] = scope_id
        return scope_id

    for token, _, _ in tool_handles:
        register_owner_token(token)

    def declare_owner_tokens(tokens) -> None:
        for token in dict.fromkeys(tokens):
            owner_id = register_owner_token(token)
            if token not in declared_owner_tokens:
                lines.append(f"D {owner_id} {token}")
                declared_owner_tokens.add(token)

    def append_tool_handles(
        handles: list[tuple[str, str, np.ndarray]] | tuple[
            tuple[str, str, np.ndarray], ...
        ] = tool_handles,
    ) -> None:
        for token, kind, center in handles:
            lines.append(
                f"J {owner_token_ids[token]} {token} {kind} {nums(*center)}"
            )
            declared_owner_tokens.add(token)

    def append_projected_base_handle(token: str, center: np.ndarray) -> None:
        """Declare one synthetic Full-view Base pivot exactly at its backbone bead."""
        if token in tool_handle_tokens:
            return
        register_owner_token(token)
        tool_handle_tokens.add(token)
        tool_handles.append((token, "base", center))
        lines.append(
            f"J {owner_token_ids[token]} {token} base {nums(*center)}"
        )
        declared_owner_tokens.add(token)

    def emit(
        record_type: str,
        identity: str,
        *values: float,
        aliases: tuple[str, ...] = (),
        endpoint_aliases: tuple[tuple[str, ...], tuple[str, ...]] | None = None,
        transform_owners: tuple[tuple[str, float, float], ...] | None = None,
        tool_endpoint_tokens: (
            tuple[tuple[str, ...], tuple[str, ...]] | None
        ) = None,
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
            if len(aliases) > 8 or any(
                not token or len(token) > 2048 for token in aliases
            ):
                raise HTTPException(500, detail="Invalid VR primitive owner aliases.")
            declare_owner_tokens(aliases)
            lines.append(
                f"A {encoded_identity} {len(aliases)} "
                f"{' '.join(owner_token_ids[token] for token in aliases)}"
            )
        if transform_owners is None:
            endpoint_owners = endpoint_aliases or (aliases, aliases)
            transform_owners = tuple(
                (
                    token,
                    float(token in endpoint_owners[0]),
                    float(token in endpoint_owners[1]),
                )
                for token in cluster_transform_tokens
                if token in endpoint_owners[0] or token in endpoint_owners[1]
            )
        if transform_owners:
            if len(transform_owners) > 8 or any(
                token not in cluster_transform_tokens
                or not np.all(np.isfinite([start_weight, end_weight]))
                or not 0.0 <= start_weight <= 1.0
                or not 0.0 <= end_weight <= 1.0
                for token, start_weight, end_weight in transform_owners
            ):
                raise HTTPException(500, detail="Too many VR transform owners.")
            declare_owner_tokens(token for token, _, _ in transform_owners)
            values = " ".join(
                f"{owner_token_ids[token]} {start_weight:.7g} {end_weight:.7g}"
                for token, start_weight, end_weight in transform_owners
            )
            lines.append(f"T {encoded_identity} {len(transform_owners)} {values}")
        scope_endpoints = tool_endpoint_tokens or endpoint_aliases or (aliases, aliases)
        scope_owners = {
            token: (
                float(token in scope_endpoints[0]),
                float(token in scope_endpoints[1]),
            )
            for token in dict.fromkeys((*scope_endpoints[0], *scope_endpoints[1]))
            if token in tool_handle_tokens
        }
        # Preserve fractional ownership already computed for interpolated detail
        # and Cluster boundaries while adding exact non-Cluster endpoint scopes.
        for token, start_weight, end_weight in transform_owners or ():
            if token in tool_handle_tokens:
                scope_owners[token] = (start_weight, end_weight)
        # A canonical alias implies rigid 1/1 ownership. W records exist only
        # for endpoint asymmetry, interpolation, or transient scopes (Atom),
        # avoiding a redundant owner table beside every static primitive.
        scope_owners = {
            token: weights
            for token, weights in scope_owners.items()
            if weights != (1.0, 1.0) or token not in aliases
        }
        if scope_owners:
            if len(scope_owners) > 32:
                raise HTTPException(500, detail="Too many VR tool-scope owners.")
            declare_owner_tokens(scope_owners)
            values = " ".join(
                f"{owner_token_ids[token]} "
                f"{start_weight:.7g} {end_weight:.7g}"
                for token, (start_weight, end_weight) in scope_owners.items()
            )
            lines.append(f"W {encoded_identity} {len(scope_owners)} {values}")

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

    def extra_base_identity(base_key_value: str, primitive: str) -> str:
        """Semantic projected-insert identity understood by desktop VR selection."""
        return "extra-base-ref:" + json.dumps(
            [base_key_value, primitive], ensure_ascii=False, separators=(",", ":")
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
        from backend.core.linker_relax import linker_anchor_nucleotide

        for connection in getattr(design, "overhang_connections", []):
            anchor_a = linker_anchor_nucleotide(
                nucleotides, connection, connection.overhang_a_id, True
            )
            anchor_b = linker_anchor_nucleotide(
                nucleotides, connection, connection.overhang_b_id, False
            )
            anchor_a_aliases = nucleotide_owner_tokens(anchor_a) if anchor_a else ()
            anchor_b_aliases = nucleotide_owner_tokens(anchor_b) if anchor_b else ()

            def linker_transform_owners(
                start_t: float, end_t: float
            ) -> tuple[tuple[str, float, float], ...]:
                def weight(token: str, value: float) -> float:
                    return min(
                        1.0,
                        (1.0 - value if token in anchor_a_aliases else 0.0)
                        + (value if token in anchor_b_aliases else 0.0),
                    )

                return tuple(
                    (token, weight(token, start_t), weight(token, end_t))
                    for token in cluster_transform_tokens
                    if token in anchor_a_aliases or token in anchor_b_aliases
                )

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
                        parameter = float(base_index + 1) / float(
                            len(projection.bases) + 1
                        )
                        base_transform_owners = linker_transform_owners(
                            parameter, parameter
                        )
                        emit(
                            "P",
                            f"linker:{connection.id}:ss:bead:{base_index}",
                            *bead,
                            0.10,
                            *palette,
                            aliases=aliases,
                            transform_owners=base_transform_owners,
                        )
                        box(
                            f"linker:{connection.id}:ss:slab:{base_index}",
                            rotation @ base.slab_center,
                            rotation @ base.slab_axis_x,
                            rotation @ base.slab_axis_y,
                            rotation @ base.slab_axis_z,
                            palette,
                            aliases=aliases,
                            transform_owners=base_transform_owners,
                        )
                points = [rotation @ value for value in projection.backbone_points]
                edge_count = max(len(points) - 1, 1)
                base_count = len(projection.bases)
                path_has_anchors = len(points) != base_count

                def path_parameter(index: int) -> float:
                    if path_has_anchors:
                        return float(index) / float(max(len(points) - 1, 1))
                    return float(index + 1) / float(len(points) + 1)

                for edge_index, (first, second) in enumerate(zip(points, points[1:])):
                    nearest_base = (
                        -1
                        if base_count == 0
                        else min(
                            int((edge_index + 0.5) * base_count / edge_count),
                            base_count - 1,
                        )
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
                                    f"__lnk__{connection.id}:{nearest_base}:FORWARD",
                                )
                            )
                            if nearest_base >= 0
                            else ()
                        ),
                        transform_owners=linker_transform_owners(
                            path_parameter(edge_index),
                            path_parameter(edge_index + 1),
                        ),
                    )
                continue

            for connector in ds_linker_connector_projections(nucleotides, connection):
                palette = palette_for_strand(connector.strand_id)
                points = [rotation @ value for value in connector.points]
                side = connector.strand_id.rsplit("__", 1)[-1]
                side_aliases = anchor_a_aliases if side == "a" else anchor_b_aliases
                for edge_index, (first, second) in enumerate(zip(points, points[1:])):
                    emit(
                        "C",
                        f"linker:{connection.id}:ds:{side}:connector:{edge_index}",
                        *first,
                        *second,
                        0.065,
                        *palette,
                        endpoint_aliases=(side_aliases, side_aliases),
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
            anchor_a_aliases = domain_owner_tokens(strand_a, domain_a, helix_a)
            anchor_b_aliases = domain_owner_tokens(strand_b, domain_b, helix_b)

            def flexible_transform_owners(
                start_t: float, end_t: float
            ) -> tuple[tuple[str, float, float], ...]:
                def weight(token: str, value: float) -> float:
                    return min(
                        1.0,
                        (1.0 - value if token in anchor_a_aliases else 0.0)
                        + (value if token in anchor_b_aliases else 0.0),
                    )

                return tuple(
                    (token, weight(token, start_t), weight(token, end_t))
                    for token in cluster_transform_tokens
                    if token in anchor_a_aliases or token in anchor_b_aliases
                )

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
                if strand is None or not 0 <= anchor.domain_index < len(strand.domains):
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
                parameter = float(base_index + 1) / float(len(projection.bases) + 1)
                base_transform_owners = flexible_transform_owners(parameter, parameter)
                bead = rotation @ base.bead_center
                emit(
                    "P",
                    f"flex:{projection.connection_id}:bead:{base_index}",
                    *bead,
                    0.12,
                    *palette,
                    aliases=aliases,
                    transform_owners=base_transform_owners,
                )
                box(
                    f"flex:{projection.connection_id}:slab:{base_index}",
                    rotation @ base.slab_center,
                    rotation @ base.slab_axis_x,
                    rotation @ base.slab_axis_y,
                    rotation @ base.slab_axis_z,
                    palette,
                    aliases=aliases,
                    transform_owners=base_transform_owners,
                )
            points = [rotation @ value for value in projection.backbone_points]
            edge_count = max(len(points) - 1, 1)
            base_count = len(projection.bases)
            for edge_index, (first, second) in enumerate(zip(points, points[1:])):
                nearest_base = (
                    -1
                    if base_count == 0
                    else min(
                        int((edge_index + 0.5) * base_count / edge_count),
                        base_count - 1,
                    )
                )
                emit(
                    "C",
                    f"flex:{projection.connection_id}:backbone:{edge_index}:near:{nearest_base}",
                    *first,
                    *second,
                    0.06,
                    *palette,
                    aliases=flexible_aliases(nearest_base),
                    transform_owners=flexible_transform_owners(
                        float(edge_index) / float(edge_count),
                        float(edge_index + 1) / float(edge_count),
                    ),
                )

    def append_unligated_warning(
        crossover_id: str,
        center: np.ndarray,
        transform_owners: tuple[tuple[str, float, float], ...] = (),
    ) -> None:
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
                transform_owners=transform_owners,
            )
        box(
            f"warning:{crossover_id}:stem",
            center + np.array([0.0, 0.25, 0.0]),
            np.array([0.24, 0.0, 0.0]),
            np.array([0.0, 0.90, 0.0]),
            np.array([0.0, 0.0, 0.12]),
            palette,
            aliases=aliases,
            transform_owners=transform_owners,
        )
        box(
            f"warning:{crossover_id}:dot",
            center + np.array([0.0, -0.72, 0.0]),
            np.array([0.28, 0.0, 0.0]),
            np.array([0.0, 0.28, 0.0]),
            np.array([0.0, 0.0, 0.14]),
            palette,
            aliases=aliases,
            transform_owners=transform_owners,
        )

    lines = _SceneLineEmitter(line_writer)
    lines.append(f"NADOCVR 12 {representation} {coloring}")
    lines.append("# stable identities, owner aliases, and endpoint-aware tool scopes")
    by_strand: dict[str, list[tuple[dict, np.ndarray, tuple[float, ...], str]]] = {}
    identity_palettes: dict[tuple, tuple[float, ...]] = {}
    lines.append("R full")
    declared_owner_tokens.clear()
    lines.extend(f"K {token} {nums(*center)}" for token, center in cluster_handles)
    append_tool_handles()
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
        transform_owners: tuple[tuple[str, float, float], ...] | None = None,
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
            transform_owners=transform_owners,
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
            key=lambda item: strand_nucleotide_order_key(item[0])
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
                    endpoint_aliases=(
                        nucleotide_owner_tokens(first_nucleotide),
                        nucleotide_owner_tokens(second_nucleotide),
                    ),
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
        if hidden_periodic and not show_periodic_seam_arcs:
            continue
        first_entry = site_entries.get(first_key)
        second_entry = site_entries.get(second_key)
        if first_entry is None or second_entry is None:
            continue
        first_nucleotide, first, palette = first_entry
        second_nucleotide, second, _ = second_entry
        first_transform_aliases = nucleotide_owner_tokens(first_nucleotide)
        second_transform_aliases = nucleotide_owner_tokens(second_nucleotide)

        def interpolated_transform_owners(
            start_t: float, end_t: float
        ) -> tuple[tuple[str, float, float], ...]:
            def weight(token: str, value: float) -> float:
                return min(
                    1.0,
                    (1.0 - value if token in first_transform_aliases else 0.0)
                    + (value if token in second_transform_aliases else 0.0),
                )

            return tuple(
                (token, weight(token, start_t), weight(token, end_t))
                for token in cluster_transform_tokens
                if token in first_transform_aliases or token in second_transform_aliases
            )

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
            backbone_parameters = [0.0]
            backbone_endpoint_aliases = [
                nucleotide_owner_tokens(first_nucleotide)
            ]
            for projection in projections:
                parameter = float(projection.geometric_index + 1) / float(
                    len(projections) + 1
                )
                projection_transform_owners = interpolated_transform_owners(
                    parameter, parameter
                )
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
                extra_key = f"__xb__:{connection_id}:{projection.sim_k}"
                extra_token = selection_token("base", extra_key)
                append_projected_base_handle(extra_token, bead)
                extra_aliases = owner_tokens(
                    ("base", extra_key),
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
                    extra_base_identity(extra_key, "bead"),
                    *bead,
                    0.10,
                    *extra_palette,
                    aliases=extra_aliases,
                    transform_owners=projection_transform_owners,
                )
                box(
                    extra_base_identity(extra_key, "slab"),
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
                    transform_owners=projection_transform_owners,
                )
                emit(
                    "C",
                    extra_base_identity(extra_key, "slab-connector"),
                    *bead,
                    *slab_corner,
                    0.025,
                    *slab_palette,
                    aliases=extra_aliases,
                    transform_owners=projection_transform_owners,
                )
                backbone_points.append(bead)
                backbone_parameters.append(parameter)
                backbone_endpoint_aliases.append(extra_aliases)
            backbone_points.append(second)
            backbone_parameters.append(1.0)
            backbone_endpoint_aliases.append(
                nucleotide_owner_tokens(second_nucleotide)
            )
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
                    endpoint_aliases=(
                        backbone_endpoint_aliases[edge_index],
                        backbone_endpoint_aliases[edge_index + 1],
                    ),
                    transform_owners=interpolated_transform_owners(
                        backbone_parameters[edge_index],
                        backbone_parameters[edge_index + 1],
                    ),
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
            endpoint_aliases=(
                nucleotide_owner_tokens(first_nucleotide),
                nucleotide_owner_tokens(second_nucleotide),
            ),
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
        first_aliases = nucleotide_owner_tokens(first_entry[0])
        second_aliases = nucleotide_owner_tokens(second_entry[0])
        warning_transform_owners = tuple(
            (
                token,
                min(
                    1.0,
                    (0.5 if token in first_aliases else 0.0)
                    + (0.5 if token in second_aliases else 0.0),
                ),
                min(
                    1.0,
                    (0.5 if token in first_aliases else 0.0)
                    + (0.5 if token in second_aliases else 0.0),
                ),
            )
            for token in cluster_transform_tokens
            if token in first_aliases or token in second_aliases
        )
        append_unligated_warning(
            str(crossover.id),
            (first_entry[1] + second_entry[1]) * 0.5,
            warning_transform_owners,
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
            for first, second, segment, edge_identity in axis_edges(axis):
                emit(
                    "C",
                    f"{edge_identity}:axis",
                    *first,
                    *second,
                    radius,
                    *palette,
                    aliases=(
                        domain_owner_tokens(
                            segment.get("strand_id"),
                            int(segment.get("domain_index") or 0),
                            str(axis.get("helix_id") or ""),
                            segment.get("ovhg_id"),
                        )
                        if segment is not None
                        else ()
                    ),
                )

    append_axes(0.05)

    lines.append("R cylinders")
    active_representation = "cylinders"
    declared_owner_tokens.clear()
    lines.extend(f"K {token} {nums(*center)}" for token, center in cluster_handles)
    append_tool_handles()
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
                        segment.get("ovhg_id"),
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
        from backend.core.linker_relax import linker_anchor_nucleotide

        anchor_a = linker_anchor_nucleotide(
            nucleotides, connection, connection.overhang_a_id, True
        )
        anchor_b = linker_anchor_nucleotide(
            nucleotides, connection, connection.overhang_b_id, False
        )
        emit(
            "C",
            f"linker:{connection.id}:ds:bridge",
            *first,
            *second,
            0.72,
            *palette,
            endpoint_aliases=(
                nucleotide_owner_tokens(anchor_a) if anchor_a else (),
                nucleotide_owner_tokens(anchor_b) if anchor_b else (),
            ),
        )

    # Cylinders retains thin ssDNA and dsDNA connector paths but omits the
    # fine ssDNA bead/slab decoration, matching desktop detail visibility.
    append_linker_geometry(include_full_bases=False)

    if atomistic_model is None:
        raise HTTPException(500, detail="Atomistic VR snapshot was not built.")
    from backend.core.atomistic import (
        CPK_COLOR,
        DEFAULT_CPK_COLOR,
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
        if (
            getattr(atom, "crossover_id", None) is not None
            and getattr(atom, "extra_base_k", None) is not None
        ):
            return f"__xb__:{atom.crossover_id}:{atom.extra_base_k}"
        if (
            getattr(atom, "extension_id", None) is not None
            and getattr(atom, "ext_k", None) is not None
        ):
            return f"__ext_{atom.extension_id}:{atom.ext_k}:{atom.direction}"
        key = f"{atom.helix_id}:{atom.bp_index}:{atom.direction}"
        copy_k = int(getattr(atom, "copy_k", 0) or 0)
        return f"{key}:{copy_k}" if copy_k else key

    # Atomistic draw indices are deliberately excluded from scene identity. A
    # chemical atom name is unique within one residue/base key; treating a
    # duplicate as an invalid snapshot is safer than inventing an order-dependent
    # suffix that could later become an edit target.
    atom_identity_payloads: list[tuple[str, str]] = []
    seen_atom_refs: set[tuple[str, str]] = set()
    for atom in atomistic_model.atoms:
        atom_name = getattr(atom, "name", None)
        if not isinstance(atom_name, str) or not atom_name:
            raise HTTPException(500, detail="Atomistic VR atom is missing its name.")
        payload = (atom_base_key(atom), atom_name)
        if payload in seen_atom_refs:
            raise HTTPException(
                500,
                detail=f"Duplicate semantic VR atom identity: {payload!r}",
            )
        seen_atom_refs.add(payload)
        atom_identity_payloads.append(payload)

    atom_tool_tokens = tuple(
        selection_token("atom", base_key_value, atom_name)
        for base_key_value, atom_name in atom_identity_payloads
    )
    atom_tool_handles = tuple(
        (token, "atom", position)
        for token, position in zip(atom_tool_tokens, atom_positions)
        if position is not None
    )
    tool_handle_tokens.update(token for token, _, _ in atom_tool_handles)
    for token, _, _ in atom_tool_handles:
        register_owner_token(token)

    def atom_primitive_identity(index: int) -> str:
        return "atom-ref:" + json.dumps(
            atom_identity_payloads[index], ensure_ascii=False, separators=(",", ":")
        )

    def atom_bond_primitive_identity(first_index: int, second_index: int) -> str:
        return "atom-bond-ref:" + json.dumps(
            [atom_identity_payloads[first_index], atom_identity_payloads[second_index]],
            ensure_ascii=False,
            separators=(",", ":"),
        )

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

    def append_atomistic(
        name: str, include_points: bool, point_radius: float, bond_radius: float
    ) -> None:
        nonlocal active_representation
        lines.append(f"R {name}")
        active_representation = name
        declared_owner_tokens.clear()
        lines.extend(f"K {token} {nums(*center)}" for token, center in cluster_handles)
        append_tool_handles()
        # Atom handles are needed even in stick-only mode: the live visualization
        # feed addresses each bond endpoint by its real trajectory atom position.
        append_tool_handles(atom_tool_handles)
        if include_points:
            for atom_index, (atom, position, palette) in enumerate(
                zip(atomistic_model.atoms, atom_positions, atom_palettes)
            ):
                if position is not None:
                    key = atom_base_key(atom)
                    nucleotide = nucleotide_by_base_key.get(key)
                    aliases = (
                        nucleotide_owner_tokens(nucleotide)
                        if nucleotide is not None
                        else owner_tokens(("base", key))
                    )
                    emit(
                        "P",
                        atom_primitive_identity(atom_index),
                        *position,
                        point_radius,
                        *palette,
                        aliases=aliases,
                        tool_endpoint_tokens=(
                            (*aliases, atom_tool_tokens[atom_index]),
                            (*aliases, atom_tool_tokens[atom_index]),
                        ),
                    )
        for first_index, second_index in atomistic_model.bonds:
            # Canonicalize undirected bond endpoint order together with positions
            # and owner weights so identity/value parity survives topology writers
            # that enumerate the same edge in the opposite direction.
            if (
                atom_identity_payloads[second_index]
                < atom_identity_payloads[first_index]
            ):
                first_index, second_index = second_index, first_index
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
            first_endpoint_aliases = (
                nucleotide_owner_tokens(nucleotide_by_base_key[first_key])
                if first_key in nucleotide_by_base_key
                else owner_tokens(("base", first_key))
            )
            second_endpoint_aliases = (
                nucleotide_owner_tokens(nucleotide_by_base_key[second_key])
                if second_key in nucleotide_by_base_key
                else owner_tokens(("base", second_key))
            )
            bond_aliases = tuple(
                dict.fromkeys(
                    (*bond_aliases, *first_endpoint_aliases, *second_endpoint_aliases)
                )
            )[:8]
            emit(
                "C",
                atom_bond_primitive_identity(first_index, second_index),
                *first,
                *second,
                bond_radius,
                *palette,
                aliases=bond_aliases,
                endpoint_aliases=(first_endpoint_aliases, second_endpoint_aliases),
                tool_endpoint_tokens=(
                    (
                        *first_endpoint_aliases,
                        atom_tool_tokens[first_index],
                    ),
                    (
                        *second_endpoint_aliases,
                        atom_tool_tokens[second_index],
                    ),
                ),
            )
        append_axes(0.05)

    # Match desktop atomistic_renderer/atom_palette.js exactly. Ball-and-stick
    # uses uniform balls rather than scaled VdW radii; both atomistic modes use
    # the same bond radius.
    append_atomistic("ballstick", True, 0.070, 0.025)
    append_atomistic("stick", False, 0.0, 0.025)

    if not lines.has_visible:
        raise HTTPException(
            409, detail="The active design contains no display geometry."
        )
    return lines.text() if line_writer is None else lines.manifest()


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
    delta = np.abs(end - start)
    # Match desktop Expanded Quick View's deterministic Z/Y/X tie priority.
    axis_index = (
        2 if delta[2] >= delta[0] and delta[2] >= delta[1]
        else 1 if delta[1] >= delta[0] and delta[1] >= delta[2]
        else 0
    )
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
        offset[lateral_indices] = (position[lateral_indices] - centroid) * scale_delta
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
    """Combine two identity/ownership-equivalent v12 scenes into one contract."""
    natural_lines = natural_text.splitlines()
    expanded_lines = expanded_text.splitlines()
    natural_header = natural_lines[0].split()
    expanded_header = expanded_lines[0].split()
    if natural_header != expanded_header or natural_header[0:2] != ["NADOCVR", "12"]:
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
        f"NADOCVR 12 {natural_header[2]} {natural_header[3]}",
        "# natural and expanded poses share identities and endpoint-aware tool scopes",
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
        natural_declarations = [
            line for line in natural_records if line.startswith("D ")
        ]
        expanded_declarations = [
            line for line in expanded_records if line.startswith("D ")
        ]
        if natural_declarations != expanded_declarations:
            raise HTTPException(
                500,
                detail=f"Expanded VR owner dictionaries differ in {representation}.",
            )
        natural_aliases = [line for line in natural_records if line.startswith("A ")]
        expanded_aliases = [line for line in expanded_records if line.startswith("A ")]
        if natural_aliases != expanded_aliases:
            raise HTTPException(
                500,
                detail=f"Expanded VR primitive owner aliases differ in {representation}.",
            )
        natural_transforms = [line for line in natural_records if line.startswith("T ")]
        expanded_transforms = [
            line for line in expanded_records if line.startswith("T ")
        ]
        if natural_transforms != expanded_transforms:
            raise HTTPException(
                500,
                detail=f"Expanded VR transform owners differ in {representation}.",
            )
        natural_scope_owners = [
            line for line in natural_records if line.startswith("W ")
        ]
        expanded_scope_owners = [
            line for line in expanded_records if line.startswith("W ")
        ]
        if natural_scope_owners != expanded_scope_owners:
            raise HTTPException(
                500,
                detail=f"Expanded VR tool-scope owners differ in {representation}.",
            )
        natural_handles = [
            line.split()[1] for line in natural_records if line.startswith("K ")
        ]
        expanded_handles = [
            line.split()[1] for line in expanded_records if line.startswith("K ")
        ]
        if natural_handles != expanded_handles:
            raise HTTPException(
                500,
                detail=f"Expanded VR cluster handles differ in {representation}.",
            )
        natural_tool_handles = [
            tuple(line.split()[1:4])
            for line in natural_records
            if line.startswith("J ")
        ]
        expanded_tool_handles = [
            tuple(line.split()[1:4])
            for line in expanded_records
            if line.startswith("J ")
        ]
        if natural_tool_handles != expanded_tool_handles:
            raise HTTPException(
                500,
                detail=f"Expanded VR tool handles differ in {representation}.",
            )
        output.append(f"R {representation}")
        output.extend(natural_records)
        output.append(f"E {representation}")
        output.extend(expanded_records)
    return "\n".join(output) + "\n"


def _validate_streamed_scene_manifests(
    natural: dict[str, dict[str, tuple[int, str]]],
    expanded: dict[str, dict[str, tuple[int, str]]],
) -> None:
    if set(natural) != set(expanded):
        raise HTTPException(500, detail="Expanded VR representations do not match.")
    labels = {
        "primitive": "primitive identities",
        "D": "owner dictionaries",
        "A": "primitive owner aliases",
        "T": "transform owners",
        "W": "tool-scope owners",
        "K": "cluster handles",
        "J": "tool handles",
    }
    for representation in natural:
        for category in _SCENE_MANIFEST_CATEGORIES:
            if natural[representation].get(category) != expanded[representation].get(
                category
            ):
                raise HTTPException(
                    500,
                    detail=(
                        f"Expanded VR {labels[category]} differ in "
                        f"{representation}."
                    ),
                )


def _snapshot(
    body: VRLaunchRequest,
    line_writer: Callable[[str], None] | None = None,
) -> str | None:
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
        body.show_periodic_seam_arcs,
        line_writer=line_writer,
    )
    expanded_nucleotides, expanded_axes, expanded_atomistic = _expanded_scene_inputs(
        design, nucleotides, axes, atomistic_model
    )
    expanded_writer = None
    if line_writer is not None:
        def expanded_writer(line: str) -> None:
            if line.startswith("NADOCVR ") or line.startswith("#"):
                return
            line_writer(f"E {line[2:]}") if line.startswith("R ") else line_writer(line)

    expanded_scene = _serialize_scene(
        design,
        expanded_nucleotides,
        expanded_axes,
        body.camera,
        body.representation,
        body.coloring,
        expanded_atomistic,
        unligated_crossover_ids(design),
        body.show_periodic_seam_arcs,
        line_writer=expanded_writer,
    )
    if line_writer is not None:
        assert isinstance(natural_scene, dict) and isinstance(expanded_scene, dict)
        _validate_streamed_scene_manifests(natural_scene, expanded_scene)
        return None
    assert isinstance(natural_scene, str) and isinstance(expanded_scene, str)
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
    # sbin must stay on PATH: SteamVR's own vrsetup.sh shells out to `getcap`
    # (/usr/sbin/getcap) to verify vrcompositor-launcher's CAP_SYS_NICE. Without it
    # setup "fails", and vrstartup raises a BLOCKING zenity dialog ("SteamVR setup is
    # incomplete") that stalls the whole launch until a human dismisses it.
    env["PATH"] = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
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
        # The legacy dashboard process alone does not prove that its browser-backed
        # Steam/Desktop surfaces exist. Report the two UI helpers independently so
        # a blank Linux overlay is no longer misreported as fully ready.
        "desktop_overlay_running": (
            "steamwebhelper" in names and "vrwebhelper" in names
        ),
        # The native viewer has an X11 root-capture fallback in its controller tablet.
        "native_desktop_available": (
            bool(os.environ.get("DISPLAY"))
            and os.environ.get("XDG_SESSION_TYPE", "x11").lower() == "x11"
        ),
    }


#: The Vive's own EDID does not advertise itself as a non-desktop device, so GNOME/X
#: shows it as an ordinary extended monitor and SteamVR's compositor cannot DRM-lease
#: it away from the desktop (fails with CannotDRMLeaseDisplay). Marking the connector
#: non-desktop and detaching it fixes this, but the property is session-local: it
#: resets whenever the connector re-links (headset standby/wake, replug, logout), so
#: this must be reapplied before every SteamVR launch rather than once.
_HMD_DISPLAY_CONNECTOR = "HDMI-0"


def _detach_hmd_from_desktop() -> None:
    xrandr = shutil.which("xrandr")
    if not xrandr:
        return
    subprocess.run(
        [xrandr, "--output", _HMD_DISPLAY_CONNECTOR, "--set", "non-desktop", "1", "--off"],
        env=dict(os.environ),
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )


def _start_steamvr() -> dict[str, bool]:
    """Start SteamVR through Steam so its dashboard owns the runtime lifecycle."""
    with _RUNTIME_LOCK:
        _detach_hmd_from_desktop()
        status = _runtime_payload()
        if (
            status["steamvr_running"]
            and status["dashboard_running"]
            and status["desktop_overlay_running"]
        ):
            return status
        steam = Path("/usr/bin/steam")
        if not steam.is_file():
            raise HTTPException(503, detail="Steam is not installed at /usr/bin/steam.")
        log = _STEAMVR_LOG_PATH.open("ab")
        try:
            subprocess.Popen(
                [str(steam), "-silent", "steam://rungameid/250820"],
                cwd=Path.home(),
                env=_build_environment(),
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

        # Headroom for a genuinely cold start: this may boot the Steam client itself,
        # then vrstartup, vrserver, vrcompositor, vrmonitor and vrdashboard. A measured
        # cold start with Steam not running took 18.8s. The old 20s ceiling left almost
        # no margin and failed the first launch even when SteamVR came up moments later.
        deadline = time.monotonic() + 60.0
        while time.monotonic() < deadline:
            status = _runtime_payload()
            if (
                status["steamvr_running"]
                and status["dashboard_running"]
                and status["desktop_overlay_running"]
            ):
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
    tool_feedback_path: Path,
    plane_feedback_path: Path,
    preflight_feedback_path: Path,
    tool_execution_feedback_path: Path,
    job_path: Path,
    visualization_path: Path,
) -> None:
    process.wait()
    scene_path.unlink(missing_ok=True)
    event_path.unlink(missing_ok=True)
    feedback_path.unlink(missing_ok=True)
    tool_feedback_path.unlink(missing_ok=True)
    plane_feedback_path.unlink(missing_ok=True)
    preflight_feedback_path.unlink(missing_ok=True)
    tool_execution_feedback_path.unlink(missing_ok=True)
    job_path.unlink(missing_ok=True)
    visualization_path.unlink(missing_ok=True)
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
        "timing": _runtime_timing(state, _event_payload(state)),
        "log_path": str(_LOG_PATH),
        **_runtime_payload(),
    }


def _runtime_timing(state: dict, event: dict) -> dict:
    """Return launch milestones without trusting native clock-derived durations."""
    requested_at = state.get("launch_requested_at")
    browser_requested_at = state.get("browser_requested_at")
    snapshot_started_at = state.get("snapshot_started_at")
    snapshot_ready_at = state.get("snapshot_ready_at")
    process_started_at = state.get("process_started_at")
    first_frame_at_ms = event.get("first_frame_at_ms")

    def elapsed_ms(start, end) -> float | None:
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
            return None
        value = (float(end) - float(start)) * 1000.0
        return round(value, 1) if np.isfinite(value) and value >= 0 else None

    first_frame_at = (
        float(first_frame_at_ms) / 1000.0
        if isinstance(first_frame_at_ms, (int, float))
        else None
    )
    return {
        "first_frame_ready": int(event.get("ready_sequence", 0)) > 0,
        "snapshot_ms": elapsed_ms(snapshot_started_at, snapshot_ready_at),
        "process_to_first_frame_ms": elapsed_ms(process_started_at, first_frame_at),
        "launch_to_first_frame_ms": elapsed_ms(requested_at, first_frame_at),
        "click_to_first_frame_ms": elapsed_ms(browser_requested_at, first_frame_at),
        "job_snapshot_ms": state.get("job_snapshot_ms"),
        "first_frame_cpu_ms": event.get("first_frame_cpu_ms"),
        "display_period_ms": event.get("display_period_ms"),
    }


_VR_TOOL_CONFIG_TARGET_KINDS = {
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
}


def _parse_tool_config(raw: object, sequence: int) -> dict | None:
    """Validate one bounded, target-bound configuration draft.

    Bounds protect the localhost transport only. A future desktop-authoritative
    adapter must still resolve footprint/plane geometry and run normal operation
    validation before previewing or mutating a design.
    """
    if sequence == 0:
        if raw is not None:
            raise ValueError("configuration without sequence")
        return None
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("missing tool configuration")

    mode = raw.get("mode")
    target_identity = raw.get("target_identity")
    target_kind = raw.get("target_kind")
    target_owner_tokens = raw.get("target_owner_tokens")
    if (
        mode not in {"extrude", "twist", "bend"}
        or target_kind not in _VR_TOOL_CONFIG_TARGET_KINDS
        or not isinstance(target_owner_tokens, list)
        or len(target_owner_tokens) > 8
        or any(
            not isinstance(token, str)
            or not token
            or len(token) > 2048
            or any(character.isspace() for character in token)
            for token in target_owner_tokens
        )
        or (
            target_kind == "none"
            and (target_identity is not None or target_owner_tokens)
        )
        or (
            target_kind != "none"
            and (
                not isinstance(target_identity, str)
                or not target_identity
                or len(target_identity) > 2048
                or not target_owner_tokens
            )
        )
    ):
        raise ValueError("invalid tool configuration target")

    common = {
        "mode": mode,
        "target_identity": target_identity,
        "target_kind": target_kind,
        "target_owner_tokens": target_owner_tokens,
    }

    def bounded_int(value: object, low: int, high: int, *, nullable=False):
        if nullable and value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise ValueError("invalid tool configuration integer")
        return value

    def bounded_float(value: object, low: float, high: float) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("invalid tool configuration number")
        result = float(value)
        if not math.isfinite(result) or not low <= result <= high:
            raise ValueError("invalid tool configuration number")
        return result

    if mode == "extrude":
        length_bp = bounded_int(raw.get("length_bp"), 0, 1_000_000)
        direction_sign = bounded_int(raw.get("direction_sign"), -1, 1)
        if (
            direction_sign == 0
            or raw.get("strand_filter") not in {"both", "scaffold", "staples"}
            or not isinstance(raw.get("ligate_adjacent"), bool)
            or raw.get("footprint_state") != "unresolved"
        ):
            raise ValueError("invalid extrusion configuration")
        return {
            **common,
            "length_bp": length_bp,
            "direction_sign": direction_sign,
            "strand_filter": raw["strand_filter"],
            "ligate_adjacent": raw["ligate_adjacent"],
            "footprint_state": "unresolved",
        }

    plane_a_bp = bounded_int(
        raw.get("plane_a_bp"), -(2**31 - 1), 2**31 - 1, nullable=True
    )
    plane_b_bp = bounded_int(
        raw.get("plane_b_bp"), -(2**31 - 1), 2**31 - 1, nullable=True
    )
    if mode == "twist":
        if raw.get("amount_mode") not in {"total_degrees", "degrees_per_nm"}:
            raise ValueError("invalid twist amount mode")
        return {
            **common,
            "plane_a_bp": plane_a_bp,
            "plane_b_bp": plane_b_bp,
            "amount_mode": raw["amount_mode"],
            "amount": bounded_float(raw.get("amount"), -1_000_000, 1_000_000),
        }
    return {
        **common,
        "plane_a_bp": plane_a_bp,
        "plane_b_bp": plane_b_bp,
        "angle_deg": bounded_float(raw.get("angle_deg"), 0, 360),
        "direction_deg": bounded_float(raw.get("direction_deg"), 0, 360),
    }


def _event_payload(state: dict | None) -> dict:
    """Read one bounded, overwrite-in-place native event record."""
    if not state or not state.get("event_path"):
        return {
            "sequence": 0,
            "hover_identity": None,
            "select_sequence": 0,
            "select_identity": None,
            "select_identities": [],
            "level_sequence": 0,
            "selection_level": "default",
            "style_sequence": 0,
            "representation": "full",
            "coloring": "strand",
            "tool_sequence": 0,
            "tool_mode": "inspect",
            "tool_action": "activate",
            "tool_target_identity": None,
            "tool_target_kind": "none",
            "tool_target_owner_tokens": [],
            "tool_config_sequence": 0,
            "tool_config": None,
            "plane_pick_sequence": 0,
            "plane_pick_config_sequence": 0,
            "plane_pick_slot": None,
            "plane_pick_identity": None,
            "transform_sequence": 0,
            "transform_matrix": np.identity(4, dtype=float).flatten(order="F").tolist(),
            "ready_sequence": 0,
            "first_frame_at_ms": None,
            "first_frame_cpu_ms": None,
            "display_period_ms": None,
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
        select_identities = event.get(
            "select_identities", [] if select_identity is None else [select_identity]
        )
        level_sequence = int(event.get("level_sequence", 0))
        selection_level = event.get("selection_level", "default")
        style_sequence = int(event.get("style_sequence", 0))
        representation = event.get("representation", "full")
        coloring = event.get("coloring", "strand")
        tool_sequence = int(event.get("tool_sequence", 0))
        tool_mode = event.get("tool_mode", "inspect")
        tool_action = event.get("tool_action", "activate")
        tool_target_identity = event.get("tool_target_identity")
        tool_target_kind = event.get("tool_target_kind", "none")
        tool_target_owner_tokens = event.get("tool_target_owner_tokens", [])
        raw_tool_config_sequence = event.get("tool_config_sequence", 0)
        if isinstance(raw_tool_config_sequence, bool) or not isinstance(
            raw_tool_config_sequence, int
        ):
            raise ValueError("invalid tool configuration sequence")
        tool_config_sequence = raw_tool_config_sequence
        tool_config = _parse_tool_config(
            event.get("tool_config"), tool_config_sequence
        )
        raw_plane_pick_sequence = event.get("plane_pick_sequence", 0)
        raw_plane_pick_config_sequence = event.get(
            "plane_pick_config_sequence", 0
        )
        if (
            isinstance(raw_plane_pick_sequence, bool)
            or not isinstance(raw_plane_pick_sequence, int)
            or isinstance(raw_plane_pick_config_sequence, bool)
            or not isinstance(raw_plane_pick_config_sequence, int)
        ):
            raise ValueError("invalid plane pick sequence")
        plane_pick_sequence = raw_plane_pick_sequence
        plane_pick_config_sequence = raw_plane_pick_config_sequence
        plane_pick_slot = event.get("plane_pick_slot")
        plane_pick_identity = event.get("plane_pick_identity")
        transform_sequence = int(event.get("transform_sequence", 0))
        transform_values = event.get(
            "transform_matrix",
            np.identity(4, dtype=float).flatten(order="F").tolist(),
        )
        ready_sequence = int(event.get("ready_sequence", 0))
        first_frame_at_ms = event.get("first_frame_at_ms")
        first_frame_cpu_ms = event.get("first_frame_cpu_ms")
        display_period_ms = event.get("display_period_ms")
        identities = (hover_identity, select_identity, tool_target_identity)
        if (
            sequence < 0
            or select_sequence < 0
            or level_sequence < 0
            or style_sequence < 0
            or tool_sequence < 0
            or tool_config_sequence < 0
            or plane_pick_sequence < 0
            or plane_pick_config_sequence < 0
            or transform_sequence < 0
            or ready_sequence < 0
            or any(
                value is not None and not isinstance(value, str) for value in identities
            )
            or not isinstance(select_identities, list)
            or len(select_identities) > 16
            or sum(
                len(value) for value in select_identities if isinstance(value, str)
            ) > 2048
            or any(
                not isinstance(value, str)
                or not value
                or len(value) > 2048
                or any(character.isspace() for character in value)
                for value in select_identities
            )
            or len(set(select_identities)) != len(select_identities)
            or (
                select_identity is None and select_identities
            )
            or (
                select_identity is not None and
                (not select_identities or select_identities[0] != select_identity)
            )
            or selection_level
            not in {"default", "cluster", "strand", "domain", "end", "xover", "base"}
            or representation not in {"cylinders", "full", "ballstick", "stick"}
            or coloring not in {"strand", "base", "cluster", "cpk"}
            or tool_mode not in {"inspect", "move_rotate", "extrude", "twist", "bend"}
            or tool_action not in {"activate", "preview", "confirm", "cancel", "undo"}
            or (
                plane_pick_sequence == 0
                and (
                    plane_pick_config_sequence != 0
                    or plane_pick_slot is not None
                    or plane_pick_identity is not None
                )
            )
            or (
                plane_pick_sequence > 0
                and (
                    plane_pick_config_sequence < 1
                    or plane_pick_config_sequence != tool_config_sequence
                    or plane_pick_slot not in {"a", "b"}
                    or not isinstance(plane_pick_identity, str)
                    or not plane_pick_identity
                    or len(plane_pick_identity) > 2048
                    or any(character.isspace() for character in plane_pick_identity)
                )
            )
            or tool_target_kind not in _VR_TOOL_CONFIG_TARGET_KINDS
            or not isinstance(tool_target_owner_tokens, list)
            or len(tool_target_owner_tokens) > 8
            or any(
                not isinstance(token, str)
                or not token
                or len(token) > 2048
                or any(character.isspace() for character in token)
                for token in tool_target_owner_tokens
            )
            or (
                tool_target_kind == "none"
                and (tool_target_identity is not None or tool_target_owner_tokens)
            )
            or (
                tool_target_kind != "none"
                and (
                    not isinstance(tool_target_identity, str)
                    or not tool_target_identity
                    or not tool_target_owner_tokens
                )
            )
            or not isinstance(transform_values, list)
            or len(transform_values) != 16
            or (
                ready_sequence == 0
                and any(
                    value is not None
                    for value in (
                        first_frame_at_ms,
                        first_frame_cpu_ms,
                        display_period_ms,
                    )
                )
            )
            or (
                ready_sequence > 0
                and (
                    not isinstance(first_frame_at_ms, (int, float))
                    or not isinstance(first_frame_cpu_ms, (int, float))
                    or not isinstance(display_period_ms, (int, float))
                    or not np.all(
                        np.isfinite(
                            [first_frame_at_ms, first_frame_cpu_ms, display_period_ms]
                        )
                    )
                    or not 0 < first_frame_at_ms < 1e15
                    or not 0 <= first_frame_cpu_ms < 1e6
                    or not 0 < display_period_ms < 1e6
                )
            )
        ):
            raise ValueError("invalid event record")
        if any(isinstance(value, str) and len(value) > 2048 for value in identities):
            raise ValueError("event identity is too large")
        view_transform = np.asarray(transform_values, dtype=float).reshape(
            (4, 4), order="F"
        )
        if (
            not np.all(np.isfinite(view_transform))
            or np.max(np.abs(view_transform)) > 1e9
            or not np.allclose(view_transform[3], [0, 0, 0, 1], atol=1e-5)
        ):
            raise ValueError("invalid transform matrix")
        view_rotation = np.asarray(
            state.get("view_rotation", np.identity(3)), dtype=float
        )
        if view_rotation.shape != (3, 3) or not np.all(np.isfinite(view_rotation)):
            raise ValueError("invalid launch view rotation")
        basis = np.identity(4, dtype=float)
        basis[:3, :3] = view_rotation
        nadoc_transform = np.linalg.inv(basis) @ view_transform @ basis
        return {
            "sequence": sequence,
            "hover_identity": hover_identity,
            "select_sequence": select_sequence,
            "select_identity": select_identity,
            "select_identities": select_identities,
            "level_sequence": level_sequence,
            "selection_level": selection_level,
            "style_sequence": style_sequence,
            "representation": representation,
            "coloring": coloring,
            "tool_sequence": tool_sequence,
            "tool_mode": tool_mode,
            "tool_action": tool_action,
            "tool_target_identity": tool_target_identity,
            "tool_target_kind": tool_target_kind,
            "tool_target_owner_tokens": tool_target_owner_tokens,
            "tool_config_sequence": tool_config_sequence,
            "tool_config": tool_config,
            "plane_pick_sequence": plane_pick_sequence,
            "plane_pick_config_sequence": plane_pick_config_sequence,
            "plane_pick_slot": plane_pick_slot,
            "plane_pick_identity": plane_pick_identity,
            "transform_sequence": transform_sequence,
            "transform_matrix": nadoc_transform.flatten(order="F").tolist(),
            "ready_sequence": ready_sequence,
            "first_frame_at_ms": first_frame_at_ms,
            "first_frame_cpu_ms": first_frame_cpu_ms,
            "display_period_ms": display_period_ms,
        }
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        # A truncate/write can briefly expose an incomplete record. Pollers keep
        # their prior sequence and recover on the next read.
        return {
            "sequence": 0,
            "hover_identity": None,
            "select_sequence": 0,
            "select_identity": None,
            "select_identities": [],
            "level_sequence": 0,
            "selection_level": "default",
            "style_sequence": 0,
            "representation": "full",
            "coloring": "strand",
            "tool_sequence": 0,
            "tool_mode": "inspect",
            "tool_action": "activate",
            "tool_target_identity": None,
            "tool_target_kind": "none",
            "tool_target_owner_tokens": [],
            "tool_config_sequence": 0,
            "tool_config": None,
            "plane_pick_sequence": 0,
            "plane_pick_config_sequence": 0,
            "plane_pick_slot": None,
            "plane_pick_identity": None,
            "transform_sequence": 0,
            "transform_matrix": np.identity(4, dtype=float).flatten(order="F").tolist(),
            "ready_sequence": 0,
            "first_frame_at_ms": None,
            "first_frame_cpu_ms": None,
            "display_period_ms": None,
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
    selected_identities = list(body.selected_identities) if body.accepted else []
    if body.accepted and body.selected and not selected_identities and identity != "-":
        selected_identities = [identity]
    selected_owner_tokens = list(body.selected_owner_tokens) if body.accepted else []
    if body.accepted and body.selected and not selected_owner_tokens and owner_tokens:
        selected_owner_tokens = [owner_tokens[0]]
    record = (
        f"NADOCVR_FEEDBACK 5 {body.select_sequence} "
        f"{int(body.accepted)} {int(body.selected)} "
        f"{body.selection_level} {selection_kind} {identity} {len(owner_tokens)}"
        + (f" {' '.join(owner_tokens)}" if owner_tokens else "")
        + f" {len(selected_identities)}"
        + (f" {' '.join(selected_identities)}" if selected_identities else "")
        + f" {len(selected_owner_tokens)}"
        + (f" {' '.join(selected_owner_tokens)}" if selected_owner_tokens else "")
        + "\n"
    )
    values = [identity, *owner_tokens, *selected_identities, *selected_owner_tokens]
    if (
        (body.selected and selection_kind == "none")
        or (body.selected and identity not in selected_identities)
        or len(set(selected_identities)) != len(selected_identities)
        or len(set(selected_owner_tokens)) != len(selected_owner_tokens)
        or sum(len(value) for value in selected_identities) > 2048
        or sum(len(value) for value in selected_owner_tokens) > 2048
        or len(record.encode()) > 4096
        or any(
            any(character.isspace() for character in value) or len(value) > 2048
            for value in values
        )
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
            raise HTTPException(
                503, detail="Could not acknowledge VR selection."
            ) from exc


@router.post("/vr/feedback")
def vr_feedback(body: VRFeedbackRequest, request: Request) -> dict:
    _require_local(request)
    _write_feedback(_read_state(), body)
    return {"acknowledged": True, "select_sequence": body.select_sequence}


def _write_tool_feedback(state: dict | None, body: VRToolFeedbackRequest) -> None:
    """Atomically return one exact browser-resolved tool locator to native VR."""
    if not state or not state.get("tool_feedback_path"):
        raise HTTPException(409, detail="Native VR is not running.")
    if (
        any(character.isspace() for character in body.target_identity)
        or body.target_kind != "end"
        or body.resolved != (body.reason == "resolved")
        or body.resolved != (
            body.face_position is not None
            and body.face_normal is not None
            and body.expanded_face_position is not None
            and body.expanded_face_normal is not None
        )
        or body.footprint_resolved != (
            body.preview_origin is not None
            and body.expanded_preview_origin is not None
            and body.footprint_lattice_type is not None
            and body.footprint_cell is not None
        )
        or (
            body.footprint_cell is not None
            and any(abs(value) > 1_000_000 for value in body.footprint_cell)
        )
        or (
            not body.resolved
            and (body.occupied or body.deformed or body.footprint_resolved)
        )
        or (
            not body.resolved
            and any(
                value is not None
                for value in (
                    body.face_position,
                    body.face_normal,
                    body.preview_origin,
                    body.expanded_face_position,
                    body.expanded_face_normal,
                    body.expanded_preview_origin,
                    body.footprint_lattice_type,
                    body.footprint_cell,
                )
            )
        )
    ):
        raise HTTPException(422, detail="Invalid VR tool feedback.")

    values: list[float] = []
    if body.resolved:
        rotation = np.asarray(state.get("view_rotation"), dtype=float)
        if rotation.shape != (3, 3) or not np.all(np.isfinite(rotation)):
            raise HTTPException(422, detail="Invalid VR tool feedback geometry.")

        def pose_values(position_value, normal_value, origin_value) -> list[float]:
            position = np.asarray(position_value, dtype=float)
            normal = np.asarray(normal_value, dtype=float)
            origin = np.asarray(origin_value if origin_value is not None else [], dtype=float)
            if (
                position.shape != (3,)
                or normal.shape != (3,)
                or not np.all(np.isfinite(position))
                or not np.all(np.isfinite(normal))
                or np.max(np.abs(position)) > 1e9
                or not 1e-9 < np.linalg.norm(normal) < 1e9
                or (
                    body.footprint_resolved
                    and (
                        origin.shape != (3,)
                        or not np.all(np.isfinite(origin))
                        or np.max(np.abs(origin)) > 1e9
                    )
                )
            ):
                raise HTTPException(422, detail="Invalid VR tool feedback geometry.")
            position = rotation @ position
            normal = rotation @ normal
            normal /= np.linalg.norm(normal)
            result = [*position.tolist(), *normal.tolist()]
            if body.footprint_resolved:
                result.extend((rotation @ origin).tolist())
            return result

        values = pose_values(
            body.face_position, body.face_normal, body.preview_origin
        )
        values.extend(
            pose_values(
                body.expanded_face_position,
                body.expanded_face_normal,
                body.expanded_preview_origin,
            )
        )

    record = (
        f"NADOCVR_TOOL_FEEDBACK 4 {body.tool_config_sequence} "
        f"{int(body.resolved)} {int(body.occupied)} {int(body.deformed)} "
        f"{int(body.footprint_resolved)} "
        f"{body.reason} {body.target_kind} {body.target_identity}"
        + (
            f" {body.footprint_lattice_type} {body.footprint_cell[0]} "
            f"{body.footprint_cell[1]}"
            if body.footprint_resolved and body.footprint_cell is not None
            else ""
        )
        + (" " + " ".join(f"{value:.17g}" for value in values) if values else "")
        + "\n"
    )
    if len(record.encode()) > 4096:
        raise HTTPException(422, detail="Invalid VR tool feedback.")
    path = Path(state["tool_feedback_path"])
    temporary = path.with_name(f"{path.name}.next")
    with _TOOL_FEEDBACK_LOCK:
        try:
            temporary.write_text(record)
            temporary.chmod(0o600)
            os.replace(temporary, path)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise HTTPException(
                503, detail="Could not publish VR tool locator."
            ) from exc


@router.post("/vr/tool-feedback")
def vr_tool_feedback(body: VRToolFeedbackRequest, request: Request) -> dict:
    _require_local(request)
    _write_tool_feedback(_read_state(), body)
    return {
        "acknowledged": True,
        "tool_config_sequence": body.tool_config_sequence,
    }


def _write_plane_feedback(state: dict | None, body: VRPlaneFeedbackRequest) -> None:
    """Atomically acknowledge one explicit native deformation-plane pick."""
    if not state or not state.get("plane_feedback_path"):
        raise HTTPException(409, detail="Native VR is not running.")
    if (
        any(character.isspace() for character in body.target_identity)
        or any(character.isspace() for character in body.picked_identity)
        or body.target_kind not in {"cluster", "end"}
        or body.resolved != (body.reason == "resolved")
        or body.resolved != (
            body.plane_bp is not None
            and body.plane_center is not None
            and body.plane_normal is not None
            and body.plane_half_extent_nm is not None
            and body.expanded_plane_center is not None
            and body.expanded_plane_normal is not None
            and body.expanded_plane_half_extent_nm is not None
        )
        or (
            not body.resolved
            and any(
                value is not None
                for value in (
                    body.plane_bp,
                    body.plane_center,
                    body.plane_normal,
                    body.plane_half_extent_nm,
                    body.expanded_plane_center,
                    body.expanded_plane_normal,
                    body.expanded_plane_half_extent_nm,
                )
            )
        )
    ):
        raise HTTPException(422, detail="Invalid VR deformation plane feedback.")

    values: list[float] = []
    if body.resolved:
        rotation = np.asarray(state.get("view_rotation"), dtype=float)
        if rotation.shape != (3, 3) or not np.all(np.isfinite(rotation)):
            raise HTTPException(
                422, detail="Invalid VR deformation plane feedback geometry."
            )

        def frame_values(center_value, normal_value, extent_value) -> list[float]:
            center = np.asarray(center_value, dtype=float)
            normal = np.asarray(normal_value, dtype=float)
            if (
                center.shape != (3,)
                or normal.shape != (3,)
                or not np.all(np.isfinite(center))
                or not np.all(np.isfinite(normal))
                or np.max(np.abs(center)) > 1e9
                or not 1e-9 < np.linalg.norm(normal) < 1e9
                or not np.isfinite(extent_value)
                or not 0 < extent_value <= 1e6
            ):
                raise HTTPException(
                    422, detail="Invalid VR deformation plane feedback geometry."
                )
            center = rotation @ center
            normal = rotation @ normal
            normal /= np.linalg.norm(normal)
            return [*center.tolist(), *normal.tolist(), extent_value]

        values = frame_values(
            body.plane_center, body.plane_normal, body.plane_half_extent_nm
        )
        values.extend(
            frame_values(
                body.expanded_plane_center,
                body.expanded_plane_normal,
                body.expanded_plane_half_extent_nm,
            )
        )

    record = (
        f"NADOCVR_PLANE_FEEDBACK 3 {body.plane_pick_sequence} "
        f"{body.tool_config_sequence} {int(body.resolved)} {body.reason} "
        f"{body.plane_slot} {body.target_kind} {body.target_identity} "
        f"{body.picked_identity}"
        + (
            f" {body.plane_bp} "
            + " ".join(f"{value:.17g}" for value in values)
            if body.resolved else ""
        )
        + "\n"
    )
    if len(record.encode()) > 4096:
        raise HTTPException(422, detail="Invalid VR deformation plane feedback.")
    path = Path(state["plane_feedback_path"])
    temporary = path.with_name(f"{path.name}.next")
    with _TOOL_FEEDBACK_LOCK:
        try:
            temporary.write_text(record)
            temporary.chmod(0o600)
            os.replace(temporary, path)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise HTTPException(
                503, detail="Could not acknowledge VR deformation plane."
            ) from exc


@router.post("/vr/plane-feedback")
def vr_plane_feedback(body: VRPlaneFeedbackRequest, request: Request) -> dict:
    _require_local(request)
    _write_plane_feedback(_read_state(), body)
    return {
        "acknowledged": True,
        "plane_pick_sequence": body.plane_pick_sequence,
        "tool_config_sequence": body.tool_config_sequence,
    }


def _write_preflight_feedback(
    state: dict | None, body: VRToolPreflightFeedbackRequest
) -> tuple[bool, int]:
    """Atomically publish one target-bound, read-only tool preflight verdict."""
    if not state or not state.get("preflight_feedback_path"):
        raise HTTPException(409, detail="Native VR is not running.")
    identity = body.target_identity or "-"
    compatible = (
        (body.target_kind == "none" and body.target_identity is None)
        or (
            body.target_kind != "none"
            and body.target_identity is not None
            and (
                (body.tool_mode == "extrude" and body.target_kind == "end")
                or (
                    body.tool_mode in {"twist", "bend"}
                    and body.target_kind in {"cluster", "end"}
                )
            )
        )
    )
    if (
        not compatible
        or any(character.isspace() for character in identity)
        or len(identity) > 2048
    ):
        raise HTTPException(422, detail="Invalid VR tool preflight feedback.")
    record = (
        f"NADOCVR_PREFLIGHT 2 {body.tool_config_sequence} "
        f"{body.preflight_sequence} {body.status} "
        f"{body.tool_mode} {body.target_kind} {identity} {body.reason}\n"
    )
    if len(record.encode()) > 4096:
        raise HTTPException(422, detail="Invalid VR tool preflight feedback.")
    path = Path(state["preflight_feedback_path"])
    temporary = path.with_name(f"{path.name}.next")
    with _TOOL_FEEDBACK_LOCK:
        try:
            try:
                current = path.read_text()
            except OSError:
                current = ""
            fields = current.split()
            if (
                len(fields) == 9
                and fields[0] == "NADOCVR_PREFLIGHT"
                and fields[1] == "2"
            ):
                try:
                    current_tool_config_sequence = int(fields[2])
                    current_sequence = int(fields[3])
                except ValueError:
                    current_tool_config_sequence = -1
                    current_sequence = -1
                if (
                    body.tool_config_sequence < current_tool_config_sequence
                    or (
                        body.tool_config_sequence == current_tool_config_sequence
                        and body.preflight_sequence <= current_sequence
                    )
                ):
                    return False, current_sequence
            temporary.write_text(record)
            temporary.chmod(0o600)
            os.replace(temporary, path)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise HTTPException(
                503, detail="Could not publish VR tool preflight."
            ) from exc
    return True, body.preflight_sequence


@router.post("/vr/tool-preflight-feedback")
def vr_tool_preflight_feedback(
    body: VRToolPreflightFeedbackRequest, request: Request
) -> dict:
    _require_local(request)
    published, current_sequence = _write_preflight_feedback(_read_state(), body)
    return {
        "acknowledged": True,
        "published": published,
        "preflight_sequence": body.preflight_sequence,
        "current_preflight_sequence": current_sequence,
        "tool_config_sequence": body.tool_config_sequence,
    }


def _write_tool_execution_feedback(
    state: dict | None, body: VRToolExecutionFeedbackRequest
) -> tuple[bool, int]:
    """Atomically publish one sequenced commit/undo acknowledgement."""
    if not state or not state.get("tool_execution_feedback_path"):
        raise HTTPException(409, detail="Native VR is not running.")
    entry_id = body.feature_log_entry_id or "-"
    if (
        body.target_kind == "none"
        or (body.status == "succeeded") != (body.feature_log_entry_id is not None)
        or any(
            any(character.isspace() for character in value)
            for value in (body.target_identity, entry_id)
        )
    ):
        raise HTTPException(422, detail="Invalid VR tool execution feedback.")
    record = (
        f"NADOCVR_TOOL_EXECUTION 1 {body.execution_sequence} "
        f"{body.tool_sequence} {body.tool_mode} {body.tool_action} "
        f"{body.target_kind} {body.target_identity} {body.status} "
        f"{body.reason} {entry_id}\n"
    )
    if len(record.encode()) > 4096:
        raise HTTPException(422, detail="Invalid VR tool execution feedback.")
    path = Path(state["tool_execution_feedback_path"])
    temporary = path.with_name(f"{path.name}.next")
    with _TOOL_EXECUTION_FEEDBACK_LOCK:
        try:
            try:
                current_fields = path.read_text().split()
                current_sequence = (
                    int(current_fields[2])
                    if len(current_fields) == 11
                    and current_fields[:2] == ["NADOCVR_TOOL_EXECUTION", "1"]
                    else 0
                )
            except (OSError, ValueError):
                current_sequence = 0
            if body.execution_sequence <= current_sequence:
                return False, current_sequence
            temporary.write_text(record)
            temporary.chmod(0o600)
            os.replace(temporary, path)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise HTTPException(
                503, detail="Could not acknowledge VR tool execution."
            ) from exc
    return True, body.execution_sequence


@router.post("/vr/tool-execution-feedback")
def vr_tool_execution_feedback(
    body: VRToolExecutionFeedbackRequest, request: Request
) -> dict:
    _require_local(request)
    published, current_sequence = _write_tool_execution_feedback(_read_state(), body)
    return {
        "acknowledged": True,
        "published": published,
        "execution_sequence": body.execution_sequence,
        "current_execution_sequence": current_sequence,
        "tool_sequence": body.tool_sequence,
    }


def _write_job_snapshot(
    rows: list[VRJobSnapshotRow], *, available: bool = True, total: int | None = None,
    sequence: int = 1, updated_at_ms: int | None = None,
    active_job_id: str | None = None, active_job_engine: str | None = None,
    representation: str = "full", coloring: str = "strand",
) -> Path:
    """Write the initial private, whitespace-safe native live-job feed."""
    if updated_at_ms is None:
        updated_at_ms = int(time.time() * 1000)
    with tempfile.NamedTemporaryFile(
        mode="w",
        prefix="nadoc-vr-jobs-",
        suffix=".txt",
        delete=False,
    ) as job_file:
        job_file.write(_job_snapshot_record(
            rows, available=available, total=total, sequence=sequence,
            updated_at_ms=updated_at_ms, active_job_id=active_job_id,
            active_job_engine=active_job_engine, representation=representation,
            coloring=coloring,
        ))
        job_path = Path(job_file.name)
    job_path.chmod(0o600)
    return job_path


def _visualization_snapshot_record(
    points: list[VRVisualizationPoint], *, sequence: int, mode: str,
    view_rotation: np.ndarray, representation: str = "full",
    coloring: str = "strand",
) -> str:
    """Serialize the live desktop display as a bounded, atomic native feed."""
    if not 1 <= sequence <= 2**53 - 1:
        raise ValueError("Invalid VR visualization sequence.")
    rotation = np.asarray(view_rotation, dtype=float)
    if rotation.shape != (3, 3) or not np.all(np.isfinite(rotation)):
        raise ValueError("Invalid VR visualization view rotation.")
    if representation not in {"cylinders", "full", "ballstick", "stick"} or coloring not in {
        "strand", "base", "cluster", "cpk",
    }:
        raise ValueError("Invalid VR visualization style.")
    seen: set[str] = set()
    lines = [
        f"NADOCVR_VISUALIZATION 3 {sequence} {mode} "
        f"{representation} {coloring} {len(points)}"
    ]
    for point in points:
        position = np.asarray(point.position, dtype=float)
        slab_values = (
            point.slab_center,
            point.slab_axis_x,
            point.slab_axis_y,
            point.slab_axis_z,
        )
        has_slab = all(value is not None for value in slab_values)
        if (
            point.owner_token in seen
            or any(character.isspace() for character in point.owner_token)
            or position.shape != (3,)
            or not np.all(np.isfinite(position))
            or np.max(np.abs(position)) > 1e9
            or (any(value is not None for value in slab_values) and not has_slab)
        ):
            raise ValueError("Invalid VR visualization point.")
        seen.add(point.owner_token)
        transformed = rotation @ position
        color = "-" if point.color is None else f"{point.color:06x}"
        if has_slab:
            vectors = [np.asarray(value, dtype=float) for value in slab_values]
            if any(value.shape != (3,) or not np.all(np.isfinite(value)) for value in vectors):
                raise ValueError("Invalid VR visualization slab frame.")
            center = rotation @ vectors[0]
            axes = [rotation @ value for value in vectors[1:]]
            values = " ".join(
                f"{component:.7g}"
                for vector in (center, *axes)
                for component in vector
            )
            lines.append(
                f"F {point.owner_token} "
                f"{transformed[0]:.7g} {transformed[1]:.7g} {transformed[2]:.7g} "
                f"{color} {values}"
            )
        else:
            lines.append(
                f"V {point.owner_token} "
                f"{transformed[0]:.7g} {transformed[1]:.7g} {transformed[2]:.7g} "
                f"{color}"
            )
    return "\n".join(lines) + "\n"


def _write_visualization_snapshot(
    points: list[VRVisualizationPoint], *, mode: str, view_rotation: np.ndarray,
    representation: str = "full", coloring: str = "strand",
) -> Path:
    with tempfile.NamedTemporaryFile(
        mode="w", prefix="nadoc-vr-visualization-", suffix=".txt", delete=False,
    ) as visualization_file:
        visualization_file.write(
            _visualization_snapshot_record(
                points, sequence=1, mode=mode, view_rotation=view_rotation,
                representation=representation, coloring=coloring,
            )
        )
        path = Path(visualization_file.name)
    path.chmod(0o600)
    return path


def _publish_visualization_feedback(
    state: dict | None,
    body: VRJobsFeedbackRequest | VRVisualizationFeedbackRequest,
) -> int:
    if not state or not state.get("visualization_path"):
        raise HTTPException(409, detail="Native VR is not running.")
    path = Path(state["visualization_path"])
    temporary = path.with_name(f"{path.name}.next")
    with _VISUALIZATION_FEEDBACK_LOCK:
        try:
            current_record = path.read_text()
            header = current_record.splitlines()[0].split()
            legacy_header = (
                len(header) == 5
                and header[0] == "NADOCVR_VISUALIZATION"
                and header[1] in {"1", "2"}
            )
            current_header = (
                len(header) == 7
                and header[:2] == ["NADOCVR_VISUALIZATION", "3"]
            )
            if not legacy_header and not current_header:
                raise ValueError("invalid VR visualization header")
            current_sequence = int(header[2])
            sequence = current_sequence + 1
            record = _visualization_snapshot_record(
                body.visualization_points,
                sequence=sequence,
                mode=body.visualization_mode,
                view_rotation=np.asarray(state["view_rotation"], dtype=float),
                representation=body.representation,
                coloring=body.coloring,
            )
            current_payload = current_record.split("\n", 1)[1]
            next_payload = record.split("\n", 1)[1]
            current_style = (
                (header[4], header[5]) if current_header else ("full", "strand")
            )
            if (
                header[3] == body.visualization_mode
                and current_style == (body.representation, body.coloring)
                and current_payload == next_payload
            ):
                return current_sequence
            temporary.write_text(record)
            temporary.chmod(0o600)
            os.replace(temporary, path)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            temporary.unlink(missing_ok=True)
            raise HTTPException(
                503, detail="Could not publish VR visualization."
            ) from exc
    return sequence


def _job_snapshot_record(
    rows: list[VRJobSnapshotRow], *, available: bool, total: int | None,
    sequence: int, updated_at_ms: int, active_job_id: str | None = None,
    active_job_engine: str | None = None, representation: str = "full",
    coloring: str = "strand",
) -> str:
    """Serialize one bounded feed revision for atomic publication."""
    resolved_total = len(rows) if total is None else total
    if not 1 <= sequence <= 2**53 - 1 or not 0 < updated_at_ms < 10**15:
        raise ValueError("Invalid VR job feed sequence or timestamp.")
    active_pair = (active_job_engine, active_job_id)
    active_present = active_pair != (None, None)
    if (
        resolved_total < len(rows)
        or (not available and (rows or resolved_total or active_present))
        or (active_job_engine is None) != (active_job_id is None)
        or (active_present and not any(
            row.engine == active_job_engine and row.job_id == active_job_id
            for row in rows
        ))
        or representation not in {"cylinders", "full", "ballstick", "stick"}
        or coloring not in {"strand", "base", "cluster", "cpk"}
    ):
        raise ValueError("Invalid VR job feed availability or total.")
    lines = [
        f"NADOCVR_JOBS 3 {sequence} {len(rows)} {int(available)} "
        f"{resolved_total} {updated_at_ms} "
        f"{quote(active_job_engine or '-', safe='')} "
        f"{quote(active_job_id or '-', safe='')} {representation} {coloring}"
    ]
    for row in rows:
        fields = (
            row.depth,
            row.progress_permille,
            int(row.viewable),
            int(row.stale),
            int(row.archived),
            quote(row.engine, safe=""),
            quote(row.status, safe=""),
            quote(row.job_id, safe=""),
            quote(row.parent_job_id or "-", safe=""),
            quote(row.label, safe=""),
            quote(row.status_text, safe=""),
        )
        lines.append("J " + " ".join(map(str, fields)))
    return "\n".join(lines) + "\n"


def _publish_job_feedback(
    state: dict | None, body: VRJobsFeedbackRequest, *, now_ms: int | None = None,
) -> int:
    """Atomically replace the running viewer feed with a newer complete record."""
    if not state or not state.get("job_path"):
        raise HTTPException(409, detail="Native VR is not running.")
    if (
        body.jobs_snapshot_total < len(body.jobs)
        or (body.active_job_engine is None) != (body.active_job_id is None)
        or (
            body.active_job_id is not None
            and not any(
                row.engine == body.active_job_engine
                and row.job_id == body.active_job_id
                for row in body.jobs
            )
        )
    ):
        raise HTTPException(422, detail="Invalid VR job snapshot total.")
    path = Path(state["job_path"])
    temporary = path.with_name(f"{path.name}.next")
    with _JOB_FEEDBACK_LOCK:
        try:
            header = path.read_text().splitlines()[0].split()
            if len(header) == 11 and header[:2] == ["NADOCVR_JOBS", "3"]:
                current_sequence = int(header[2])
            elif len(header) == 7 and header[:2] == ["NADOCVR_JOBS", "2"]:
                current_sequence = int(header[2])
            elif len(header) == 5 and header[:2] == ["NADOCVR_JOBS", "1"]:
                current_sequence = 0
            else:
                raise ValueError("invalid VR job feed header")
            sequence = current_sequence + 1
            record = _job_snapshot_record(
                body.jobs,
                available=True,
                total=body.jobs_snapshot_total,
                sequence=sequence,
                updated_at_ms=(
                    now_ms if now_ms is not None else int(time.time() * 1000)
                ),
                active_job_id=body.active_job_id,
                active_job_engine=body.active_job_engine,
                representation=body.representation,
                coloring=body.coloring,
            )
            temporary.write_text(record)
            temporary.chmod(0o600)
            os.replace(temporary, path)
        except (OSError, ValueError, IndexError) as exc:
            temporary.unlink(missing_ok=True)
            raise HTTPException(503, detail="Could not publish VR job status.") from exc
    return sequence


@router.post("/vr/jobs-feedback")
def vr_jobs_feedback(body: VRJobsFeedbackRequest, request: Request) -> dict:
    _require_local(request)
    state = _read_state()
    sequence = _publish_job_feedback(state, body)
    visualization_sequence = _publish_visualization_feedback(state, body)
    return {
        "acknowledged": True,
        "sequence": sequence,
        "visualization_sequence": visualization_sequence,
    }


@router.post("/vr/visualization-feedback")
def vr_visualization_feedback(
    body: VRVisualizationFeedbackRequest, request: Request,
) -> dict:
    """Publish only the desktop display overlay; native job navigation is archived."""
    _require_local(request)
    sequence = _publish_visualization_feedback(_read_state(), body)
    return {"acknowledged": True, "visualization_sequence": sequence}


def _viewer_command(
    scene_path: Path,
    event_path: Path,
    feedback_path: Path,
    tool_feedback_path: Path,
    plane_feedback_path: Path,
    preflight_feedback_path: Path,
    tool_execution_feedback_path: Path,
    job_path: Path,
    visualization_path: Path,
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
        "--tool-feedback",
        str(tool_feedback_path),
        "--plane-feedback",
        str(plane_feedback_path),
        "--preflight-feedback",
        str(preflight_feedback_path),
        "--tool-execution-feedback",
        str(tool_execution_feedback_path),
        "--jobs",
        str(job_path),
        "--visualization",
        str(visualization_path),
    ]
    for token in body.selected_owner_tokens:
        command.extend(["--selected-owner", token])
    command.extend(["--selected-kind", body.selected_selection_kind])
    return command


def _write_scene_snapshot(
    scene_text: str | None = None,
    *,
    producer: Callable[[Callable[[str], None]], None] | None = None,
) -> Path:
    """Write one private gzip snapshot from text or a constant-memory line source."""
    if (scene_text is None) == (producer is None):
        raise ValueError("Provide exactly one VR scene source")
    with tempfile.NamedTemporaryFile(
        mode="wb",
        prefix="nadoc-vr-",
        suffix=".nadocvr.gz",
        delete=False,
    ) as scene_file:
        scene_path = Path(scene_file.name)
    try:
        with gzip.open(
            scene_path,
            mode="wt",
            compresslevel=1,
            encoding="utf-8",
            newline="\n",
        ) as compressed:
            if scene_text is not None:
                for offset in range(0, len(scene_text), 1 << 20):
                    compressed.write(scene_text[offset : offset + (1 << 20)])
            else:
                pending: list[str] = []
                pending_size = 0

                def write_line(line: str) -> None:
                    nonlocal pending_size
                    pending.append(line)
                    pending_size += len(line) + 1
                    if pending_size >= 1 << 20:
                        compressed.write("\n".join(pending) + "\n")
                        pending.clear()
                        pending_size = 0

                assert producer is not None
                producer(write_line)
                if pending:
                    compressed.write("\n".join(pending) + "\n")
        scene_path.chmod(0o600)
        return scene_path
    except OSError as exc:
        scene_path.unlink(missing_ok=True)
        raise HTTPException(503, detail="Could not write the VR scene snapshot.") from exc
    except Exception:
        scene_path.unlink(missing_ok=True)
        raise


@router.post("/vr/runtime/start")
def start_vr_runtime(request: Request) -> dict:
    _require_local(request)
    return {
        **_start_steamvr(),
        "desktop_hint": (
            "Launch NADOC VR, open its controller menu, and select Desktop. "
            "The Vive System button and SteamVR Desktop remain available as a fallback."
        ),
        "log_path": str(_STEAMVR_LOG_PATH),
    }


@router.post("/vr/launch")
def launch_vr(body: VRLaunchRequest, request: Request) -> dict:
    _require_local(request)
    launch_requested_at = time.time()
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
    if (
        (not body.jobs_snapshot_available and (body.jobs or body.jobs_snapshot_total))
        or body.jobs_snapshot_total < len(body.jobs)
        or (body.active_job_engine is None) != (body.active_job_id is None)
        or (
            body.active_job_id is not None
            and not any(
                row.engine == body.active_job_engine
                and row.job_id == body.active_job_id
                for row in body.jobs
            )
        )
    ):
        raise HTTPException(422, detail="Invalid VR job snapshot availability or total.")

    # Starting SteamVR through the Steam client (rather than incidentally through
    # xrCreateInstance) keeps Dashboard/Desktop available after the NADOC scene exits.
    _start_steamvr()

    with _STATE_LOCK:
        running = _read_state()
        if running:
            return _status_payload()
        _ensure_viewer_built()
        snapshot_started_at = time.time()
        scene_path = _write_scene_snapshot(
            producer=lambda write_line: _snapshot(body, line_writer=write_line)
        )
        snapshot_ready_at = time.time()
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
                f'"style_sequence":0,"representation":"{body.representation}",'
                f'"coloring":"{body.coloring}",'
                '"tool_sequence":0,"tool_mode":"inspect",'
                '"tool_action":"activate","transform_sequence":0,'
                '"transform_matrix":[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1],'
                '"ready_sequence":0,"first_frame_at_ms":null,'
                '"first_frame_cpu_ms":null,"display_period_ms":null}'
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
                f"NADOCVR_FEEDBACK 2 0 0 0 {body.selection_level} - 0\n"
            )
            feedback_path = Path(feedback_file.name)
        feedback_path.chmod(0o600)
        with tempfile.NamedTemporaryFile(
            mode="w",
            prefix="nadoc-vr-tool-feedback-",
            suffix=".txt",
            delete=False,
        ) as tool_feedback_file:
            tool_feedback_file.write(
                "NADOCVR_TOOL_FEEDBACK 2 0 0 0 0 0 unresolved none -\n"
            )
            tool_feedback_path = Path(tool_feedback_file.name)
        tool_feedback_path.chmod(0o600)
        with tempfile.NamedTemporaryFile(
            mode="w",
            prefix="nadoc-vr-plane-feedback-",
            suffix=".txt",
            delete=False,
        ) as plane_feedback_file:
            plane_feedback_file.write(
                "NADOCVR_PLANE_FEEDBACK 1 0 0 0 stale_target a end - -\n"
            )
            plane_feedback_path = Path(plane_feedback_file.name)
        plane_feedback_path.chmod(0o600)
        with tempfile.NamedTemporaryFile(
            mode="w",
            prefix="nadoc-vr-preflight-feedback-",
            suffix=".txt",
            delete=False,
        ) as preflight_feedback_file:
            preflight_feedback_file.write(
                "NADOCVR_PREFLIGHT 2 0 0 error extrude none - waiting\n"
            )
            preflight_feedback_path = Path(preflight_feedback_file.name)
        preflight_feedback_path.chmod(0o600)
        with tempfile.NamedTemporaryFile(
            mode="w",
            prefix="nadoc-vr-tool-execution-feedback-",
            suffix=".txt",
            delete=False,
        ) as tool_execution_feedback_file:
            tool_execution_feedback_file.write(
                "NADOCVR_TOOL_EXECUTION 1 0 0 move_rotate confirm none - "
                "refused waiting -\n"
            )
            tool_execution_feedback_path = Path(tool_execution_feedback_file.name)
        tool_execution_feedback_path.chmod(0o600)
        job_path = _write_job_snapshot(
            body.jobs,
            available=body.jobs_snapshot_available,
            total=body.jobs_snapshot_total,
            active_job_id=body.active_job_id,
            active_job_engine=body.active_job_engine,
            representation=body.representation,
            coloring=body.coloring,
        )
        view_rotation = _view_rotation(body.camera)
        visualization_path = _write_visualization_snapshot(
            body.visualization_points,
            mode=body.visualization_mode,
            view_rotation=view_rotation,
            representation=body.representation,
            coloring=body.coloring,
        )

        log = _LOG_PATH.open("ab")
        try:
            process = subprocess.Popen(
                _viewer_command(
                    scene_path, event_path, feedback_path, tool_feedback_path,
                    plane_feedback_path, preflight_feedback_path,
                    tool_execution_feedback_path, job_path,
                    visualization_path, body
                ),
                cwd=_REPO_ROOT,
                env=_build_environment(),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
            )
            process_started_at = time.time()
        except OSError as exc:
            scene_path.unlink(missing_ok=True)
            event_path.unlink(missing_ok=True)
            feedback_path.unlink(missing_ok=True)
            tool_feedback_path.unlink(missing_ok=True)
            plane_feedback_path.unlink(missing_ok=True)
            preflight_feedback_path.unlink(missing_ok=True)
            tool_execution_feedback_path.unlink(missing_ok=True)
            job_path.unlink(missing_ok=True)
            visualization_path.unlink(missing_ok=True)
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
            tool_feedback_path.unlink(missing_ok=True)
            plane_feedback_path.unlink(missing_ok=True)
            preflight_feedback_path.unlink(missing_ok=True)
            tool_execution_feedback_path.unlink(missing_ok=True)
            job_path.unlink(missing_ok=True)
            visualization_path.unlink(missing_ok=True)
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
            "tool_feedback_path": str(tool_feedback_path),
            "plane_feedback_path": str(plane_feedback_path),
            "preflight_feedback_path": str(preflight_feedback_path),
            "tool_execution_feedback_path": str(tool_execution_feedback_path),
            "job_path": str(job_path),
            "visualization_path": str(visualization_path),
            "started_at": process_started_at,
            "launch_requested_at": launch_requested_at,
            "browser_requested_at": (
                body.browser_requested_at_ms / 1000.0
                if body.browser_requested_at_ms is not None
                else None
            ),
            "job_snapshot_ms": body.job_snapshot_ms,
            "snapshot_started_at": snapshot_started_at,
            "snapshot_ready_at": snapshot_ready_at,
            "process_started_at": process_started_at,
            "view_rotation": view_rotation.tolist(),
        }
        _write_state(state)
        threading.Thread(
            target=_cleanup_after_process,
            args=(
                process, scene_path, event_path, feedback_path, tool_feedback_path,
                plane_feedback_path, preflight_feedback_path,
                tool_execution_feedback_path, job_path, visualization_path,
            ),
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
