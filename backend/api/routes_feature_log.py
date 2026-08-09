"""
API layer — feature-log seek / geometry-preview route handlers (extracted from crud.py).

This module hosts the read-only "scrub the feature-log timeline and serialise
the resulting geometry" endpoints — the interactive slider seek plus the three
stateless animation pre-bake batch routes. They were factored out of ``crud.py``
following the same template as ``routes_camera_poses.py`` (Refactor 13-B) /
``routes_loop_skip.py`` (10-F).

These four share one reason to change: the **seek-then-serialise-geometry**
contract. They all call the shared seek engine ``_seek_feature_log`` (which
stays in crud.py — it is L4-blocked on the builder/replay engine and is also
called cross-file from assembly.py, so it is shared infrastructure imported
back, NOT cluster-bespoke logic). The *mutating* feature-log routes
(delete / edit / revert / rollback) deliberately STAY in crud.py: they are
welded to the bespoke builder+replay engine (``_edit_dispatch_run`` → the
``_build_*`` builders, ``_replay_minor_op``, ``_topology_substitute``) and
cannot reach bespoke-B=0 without dragging the builders out too.

Routes
------
  POST /design/features/seek            — slider seek; replays log to a position (undo)
  POST /design/features/geometry-batch  — stateless multi-position compact geometry
  POST /design/features/atomistic-batch — stateless multi-position atom positions
  POST /design/features/surface-batch   — stateless multi-position surface meshes

URLs are unchanged from their previous home in crud.py. Mounting is done in
``backend/api/main.py`` via ``app.include_router(...)``.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter
from fastapi.responses import ORJSONResponse
from pydantic import BaseModel

from backend.api import state as design_state

# Shared kernel/infra helpers that stay in crud.py and are imported back
# (same convention as routes_camera_poses.py / routes_loop_skip.py):
#   _seek_feature_log              — the feature-log replay/seek ENGINE; L4-blocked
#                                    (calls the _build_* builders via _replay_minor_op
#                                    + design_state) AND shared cross-file with
#                                    assembly.py → leave-and-import-back (L13), exempt.
#   _design_replace_response       — the undo/redo/seek response builder (_design_*
#                                    response family, shared kernel) → exempt.
#   _compact_geometry_for_design   — geometry-kernel compaction wrapper (sibling of
#                                    _design_response_with_geometry, calls
#                                    _geometry_for_design) → exempt kernel.
#   _TimingTrace                   — cross-cutting Server-Timing utility used by 6+
#                                    crud handlers → exempt shared utility.
from backend.api.crud import (
    _compact_geometry_for_design,
    _design_replace_response,
    _seek_feature_log,
    _TimingTrace,
)
from backend.core.deformation import deformed_helix_axes

router = APIRouter()


class SeekFeaturesBody(BaseModel):
    position: int  # -2 = empty (no features); -1 = end (all active); ≥0 = index of last active entry
    sub_position: Optional[int] = None
    """Mid-cluster sub-position. None → cluster's post-state (all children active).
    -2 → cluster's pre-state (no children active). 0..M-1 → first sub_position+1
    children active. Honored only when ``position`` indexes a RoutingClusterLogEntry."""


@router.post("/design/features/seek", status_code=200)
def seek_features(body: SeekFeaturesBody):
    """Replay the feature log up to the given position, updating derived geometry fields.

    Pushes to the undo stack so seek can be undone via Ctrl+Z.
    position = -1 means seek to end (restore all features).

    Response shape mirrors undo/redo:
      • cluster-only diff_kind when the seek changes only cluster_transforms
        (common when slider-scrubbing through cluster_op entries) — frontend
        applies a delta in-place via _applyClusterUndoRedoDeltas, no backend
        geometry recompute beyond what _seek_feature_log already did.
      • Embedded full-geometry response otherwise — saves the legacy
        getGeometry() second round-trip the slider previously paid on every
        click.

    Per-step wall-clock is exposed in the ``Server-Timing`` response header
    so the frontend (`_request` in client.js) can log it next to the network
    round-trip time.
    """
    from backend.core.validator import validate_design

    trace = _TimingTrace()
    # _seek_feature_log is copy-on-write: it returns a new Design and never mutates
    # its input.  Retaining the current object as the response-diff baseline avoids
    # a full deep copy of every helix, strand, snapshot and loadout on each slider
    # notch — a major cost on large designs.
    with trace.step("get_prev"):
        prev = design_state.get_or_404()
    with trace.step("seek_log"):
        updated = _seek_feature_log(prev, body.position, body.sub_position)
    with trace.step("commit_state"):
        design_state.set_design(updated)
    with trace.step("validate"):
        report = validate_design(updated)
    with trace.step("response"):
        payload = _design_replace_response(prev, updated, report, trace=trace)
    return trace.attach(ORJSONResponse(payload))


class GeometryBatchBody(BaseModel):
    positions: list[int]  # e.g. [-2, 0, 1, -1]; duplicates ignored


@router.post("/design/features/geometry-batch", status_code=200)
def geometry_batch(body: GeometryBatchBody) -> dict:
    """Return pre-computed geometry for multiple feature-log positions in one call.

    Stateless — does NOT change the active design cursor or push to the undo stack.
    Used by the animation player to pre-bake keyframe states before playback so that
    all geometry interpolation is client-side and frame-accurate.

    Geometry is shipped in COMPACT per-helix-per-direction parallel-array form
    (``nucleotides_compact``) — ~50% smaller wire and ~50% faster to parse than
    the legacy per-nuc dict list. Frontend ``animation_player`` re-materialises
    the lookup maps it actually needs (posMap / bnMap / strandSet / helixSet).

    Returns: { "<position>": { nucleotides_compact, helix_axes }, ... }
    """
    design = design_state.get_or_404()
    result: dict[str, dict] = {}
    for position in set(body.positions):
        d = _seek_feature_log(design, position)
        result[str(position)] = {
            "nucleotides_compact": _compact_geometry_for_design(
                d, junction_balance=True
            ),
            "helix_axes": deformed_helix_axes(d),
        }
    return result


@router.post("/design/features/atomistic-batch", status_code=200)
def atomistic_batch(body: GeometryBatchBody) -> dict:
    """Return flat atom-position arrays for multiple feature-log positions in one call.

    Stateless — does NOT change the active design cursor or push to the undo stack.
    Used by the animation player to pre-bake atomistic states before playback.

    Returns: { "<position>": [x0,y0,z0, x1,y1,z1, ...], ... }
    Positions are indexed by atom serial (same order as GET /design/atomistic).
    """
    from backend.core.atomistic import build_atomistic_model, atomistic_positions_flat

    design = design_state.get_or_404()
    result: dict[str, list] = {}
    for position in set(body.positions):
        d = _seek_feature_log(design, position)
        model = build_atomistic_model(d)
        result[str(position)] = atomistic_positions_flat(model)
    return result


class SurfaceBatchBody(BaseModel):
    positions: list[int]
    color_mode: str = "strand"
    probe_radius: float = 0.28
    grid_spacing: float = 0.20
    radius_inflate: float = 1.30
    smooth: int = 15


@router.post("/design/features/surface-batch", status_code=200)
def surface_batch(body: SurfaceBatchBody) -> dict:
    """Return full mesh data for multiple feature-log positions in one call.

    Stateless — does NOT change the active design cursor or push to the undo stack.
    Used by the animation player to pre-bake surface states before playback.

    Returns { "<position>": { vertices, faces, vertex_colors? }, ... }.
    Both vertices and faces are included because different feature-log positions can
    produce different marching-cubes topologies (different vertex counts), so the
    frontend needs to rebuild the geometry buffer when topology changes mid-animation.

    When color_mode='strand', per-vertex RGB triples are included so the surface
    mesh keeps its strand-coloured look through topology rebuilds during animation
    playback — without this, _rebuildTopology has nothing to attach as a color
    attribute and would fall back to uniform grey.
    """
    from backend.core.atomistic import build_atomistic_model
    from backend.core.surface import compute_surface, smooth_mesh, surface_to_json

    design = design_state.get_or_404()
    result: dict[str, dict] = {}
    for position in set(body.positions):
        d = _seek_feature_log(design, position)
        model = build_atomistic_model(d)
        mesh = compute_surface(
            model.atoms,
            grid_spacing=body.grid_spacing,
            probe_radius=body.probe_radius,
            radius_scale=1.2 * body.radius_inflate,
        )
        mesh = smooth_mesh(mesh, iterations=body.smooth)
        verts = [round(float(v), 5) for v in mesh.vertices.ravel()]
        faces = [int(f) for f in mesh.faces.ravel()]
        entry: dict = {"vertices": verts, "faces": faces}
        if body.color_mode == "strand":
            full = surface_to_json(mesh, d, color_mode="strand")
            vc = full.get("vertex_colors")
            if vc:
                # 4 decimals is more than enough for 8-bit display precision and
                # keeps the bake payload compact for many-keyframe animations.
                entry["vertex_colors"] = [round(float(c), 4) for c in vc]
        result[str(position)] = entry
    return result
