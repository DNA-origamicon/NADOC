"""
API layer — per-instance + whole-assembly **geometry** route handlers
(extracted from assembly.py).

These six routes are read-only: they resolve a PartInstance's base Design (or
all visible instances at once) and compute its geometry — nucleotide positions,
bend centers, all-atom model, molecular surface — in the instance's local frame.
The frontend applies each instance's placement transform via its Three.js Group
matrix. They never mutate the assembly; that single read-only "derive geometry
for display" reason-to-change is what makes them a cohesive unit.

Routes
------
  GET /assembly/instances/{id}/design               — base Design (no overrides)
  GET /assembly/instances/{id}/geometry             — nucleotide geometry (overrides applied)
  GET /assembly/instances/{id}/bend-centers         — one connector per bend op
  GET /assembly/instances/{id}/atomistic-geometry   — heavy-atom all-atom model
  GET /assembly/instances/{id}/surface-geometry     — triangulated molecular surface
  GET /assembly/geometry                            — batch geometry, all visible instances (dedup by source)

Back-imports (raw-B=6, all shared read-kernel / cache infrastructure, bespoke-B=0):
``_find_instance`` (the trivial instance lookup, 7+ shared callers),
``_assembly_source_path`` / ``_load_design_from_source`` / ``_design_with_instance_overrides``
(file-IO design-load infra, L4-blocked from core, 3-7 shared callers each),
``_display_design`` (shared cross-region display shim, also used by the polymerize
router), and ``_geo_cache_key`` (api shim threading the monkeypatch-able
``_WORKSPACE_DIR`` into the pure key fn). The pure LRU ``geo_cache_get`` /
``geo_cache_set`` are imported DIRECTLY from ``backend.core.assembly_geometry``
(Refactor #49), not back from the god-file — they have no workspace dependency.
The geometry math itself (``_geometry_for_design``, ``deformed_helix_axes``,
``build_atomistic_model``, ``compute_surface``, …) is imported function-locally
from ``backend.api.crud`` / ``backend.core`` exactly as it was in assembly.py —
not back from the god-file.

URLs are unchanged from their previous home in assembly.py. Mounting is done in
``backend/api/main.py`` via ``app.include_router(...)``.
"""

from __future__ import annotations

from fastapi import APIRouter

from backend.api import assembly_state
from backend.api.assembly import (
    _assembly_source_path,
    _design_with_instance_overrides,
    _display_design,
    _find_instance,
    _geo_cache_key,
    _load_design_from_source,
)
from backend.core.assembly_geometry import (
    geo_cache_get as _geo_cache_get,
    geo_cache_set as _geo_cache_set,
)

router = APIRouter()


@router.get("/assembly/instances/{instance_id}/design", status_code=200)
def get_instance_design(instance_id: str) -> dict:
    """Resolve and return the base Design for a PartInstance (without cluster_transform_overrides).

    Used by the part-context editor and cluster panel — they need the source design as
    authored, not the assembly-level override positions.  For geometry rendering use the
    /geometry endpoint which applies overrides and includes "design" in the response.
    """
    assembly = assembly_state.get_or_404()
    inst     = _find_instance(assembly, instance_id)
    design   = _load_design_from_source(inst.source, _assembly_source_path(assembly))
    return {"design": design.to_dict()}


@router.get("/assembly/instances/{instance_id}/geometry", status_code=200)
def get_instance_geometry(instance_id: str) -> dict:
    """
    Compute and return nucleotide geometry for a PartInstance's Design.

    Geometry is returned in the instance's local frame (transform NOT applied).
    The frontend applies the Mat4x4 transform to the Three.js Group matrix.
    Uses the same _geometry_for_design / deformed_helix_axes functions as the
    main design geometry endpoint.

    Response shape: ``{ nucleotides_compact, helix_axes, design }``. The
    compact wire format is ~50% smaller than the dict-per-nuc form and
    parses ~50% faster in the browser — substantial when a single instance
    is a 60k-bp origami.

    Response includes "design" (with cluster_transform_overrides applied) so
    callers do not need a separate /design request.
    """
    from backend.api.crud import _geometry_for_design, _compact_geometry_from_nucleotides, _inject_joint_world_axes
    from backend.core.deformation import deformed_helix_axes, _apply_ovhg_rotations_to_axes
    assembly = assembly_state.get_or_404()
    inst     = _find_instance(assembly, instance_id)

    key    = _geo_cache_key(inst)
    cached = _geo_cache_get(key) if key else None
    if cached:
        return {
            "nucleotides_compact": _compact_geometry_from_nucleotides(cached["nucleotides"]),
            "helix_axes":          cached["helix_axes"],
            "design":              cached.get("design"),
        }

    design      = _display_design(_design_with_instance_overrides(inst))
    nucleotides = _geometry_for_design(design)
    axes        = deformed_helix_axes(design)
    _apply_ovhg_rotations_to_axes(design, axes, nucleotides)
    design_dict = design.to_dict()
    # Derive world-space cluster-joint axes (axis_origin / axis_direction) from the
    # local-frame storage, same as the design-view GET. Without this the assembly
    # part-joint drag reads undefined joint.axis_origin and throws.
    _inject_joint_world_axes(design_dict)
    if key:
        _geo_cache_set(key, {"nucleotides": nucleotides, "helix_axes": axes,
                             "design": design_dict})
    return {
        "nucleotides_compact": _compact_geometry_from_nucleotides(nucleotides),
        "helix_axes":          axes,
        "design":              design_dict,
    }


@router.get("/assembly/instances/{instance_id}/bend-centers", status_code=200)
def get_instance_bend_centers(instance_id: str) -> dict:
    """
    Return one connector per bend op for this part instance, at the bend's
    center of curvature with its normal along the bend axis.

    Used by the assembly editor's Define-Mate flow to expose bend centers as
    pickable connectors (CAD-style "mate two arcs by their circle centers").

    Geometry is in the instance's local frame — frontend applies the instance
    placement transform exactly like for blunt-end connectors.

    Response: ``{ bend_centers: [{label, position, normal, cluster_id, bend_index, radius_nm}] }``
    """
    from backend.core.deformation import compute_bend_centers
    assembly = assembly_state.get_or_404()
    inst     = _find_instance(assembly, instance_id)
    design   = _display_design(_design_with_instance_overrides(inst, _assembly_source_path(assembly)))
    return {"bend_centers": compute_bend_centers(design)}


@router.get("/assembly/instances/{instance_id}/atomistic-geometry", status_code=200)
def get_instance_atomistic_geometry(instance_id: str) -> dict:
    """
    Compute and return the heavy-atom all-atom model for a PartInstance's design.

    Geometry is returned in the instance's local frame — same convention as
    /assembly/instances/{id}/geometry.  The frontend applies the instance
    placement transform via the Three.js Group matrix.

    Response: { atoms: [...], bonds: [[i,j], ...], element_meta: {...} }
    Same schema as GET /api/design/atomistic.
    """
    from backend.core.atomistic import build_atomistic_model, atomistic_to_json
    assembly = assembly_state.get_or_404()
    inst     = _find_instance(assembly, instance_id)
    design   = _display_design(_load_design_from_source(inst.source))
    return atomistic_to_json(build_atomistic_model(design))


@router.get("/assembly/instances/{instance_id}/surface-geometry", status_code=200)
def get_instance_surface_geometry(
    instance_id:    str,
    color_mode:     str   = "strand",
    grid_spacing:   float = 0.20,
    probe_radius:   float = 0.28,
    radius_inflate: float = 1.30,
    smooth:         int   = 15,
) -> dict:
    """
    Compute and return a triangulated molecular surface for a PartInstance's design.

    Geometry is returned in the instance's local frame — same convention as
    /assembly/instances/{id}/atomistic-geometry; the frontend instances the mesh
    at each placement transform.  Defaults match GET /api/design/surface
    (radius_inflate=1.30, smooth=15) so the visual matches the design view and
    the STL export.

    Response: { vertices, faces, vertex_colors, stats } — same schema as
    GET /api/design/surface.
    """
    import time
    from backend.core.atomistic import build_atomistic_model
    from backend.core.surface import compute_surface, smooth_mesh, surface_to_json
    assembly = assembly_state.get_or_404()
    inst     = _find_instance(assembly, instance_id)
    design   = _display_design(_load_design_from_source(inst.source))
    model    = build_atomistic_model(design)
    t0   = time.perf_counter()
    mesh = compute_surface(
        model.atoms,
        grid_spacing=grid_spacing,
        probe_radius=probe_radius,
        radius_scale=1.2 * radius_inflate,
    )
    mesh = smooth_mesh(mesh, iterations=smooth)
    t_ms = (time.perf_counter() - t0) * 1000.0
    return surface_to_json(mesh, design, color_mode=color_mode, t_ms=t_ms)


@router.get("/assembly/geometry", status_code=200)
def get_assembly_geometry() -> dict:
    """
    Batch geometry for all visible instances in one request.

    **Response shape (Phase-3 dedup):**
    ```
    {
      "sources":   { "<srcKey>": { "nucleotides_compact": {...}, "helix_axes": [...], "design": {...} } },
      "instances": { "<instId>": "<srcKey>", ... },
      "errors":    { "<instId>": "<message>", ... }   # only for instances that failed
    }
    ```

    Two N-clone instances of the same part share **one** source entry.
    The compact wire format is ~50% smaller than the per-nuc dict form
    and parses proportionally faster.

    Invisible instances are omitted. The per-instance route
    ``/assembly/instances/{id}/geometry`` is unchanged in shape (it returns
    one ``nucleotides_compact`` directly).
    """
    from backend.api.crud import _geometry_for_design, _compact_geometry_from_nucleotides
    from backend.core.deformation import deformed_helix_axes, _apply_ovhg_rotations_to_axes
    assembly = assembly_state.get_or_404()
    sources:        dict[str, dict] = {}
    instance_to_src: dict[str, str] = {}
    errors:         dict[str, str]  = {}

    def _source_key_for(inst) -> str:
        # Reuse the geometry-cache key (file path + mtime suffix, or
        # inline-design id, plus cluster-transform overrides hash) so two
        # instances of the same part with no overrides share one source.
        return _geo_cache_key(inst) or f"inst:{inst.id}"

    for inst in assembly.instances:
        if not inst.visible:
            continue
        try:
            src_key = _source_key_for(inst)
            instance_to_src[inst.id] = src_key
            if src_key in sources:
                continue  # already computed for an earlier identical-source instance

            key    = _geo_cache_key(inst)
            cached = _geo_cache_get(key) if key else None
            if cached:
                sources[src_key] = {
                    "nucleotides_compact": _compact_geometry_from_nucleotides(cached["nucleotides"]),
                    "helix_axes":          cached["helix_axes"],
                    "design":              cached.get("design"),
                }
                continue

            design      = _display_design(_design_with_instance_overrides(inst))
            nucleotides = _geometry_for_design(design)
            axes        = deformed_helix_axes(design)
            _apply_ovhg_rotations_to_axes(design, axes, nucleotides)
            design_dict = design.to_dict()
            if key:
                _geo_cache_set(key, {
                    "nucleotides": nucleotides,
                    "helix_axes":  axes,
                    "design":      design_dict,
                })
            sources[src_key] = {
                "nucleotides_compact": _compact_geometry_from_nucleotides(nucleotides),
                "helix_axes":          axes,
                "design":              design_dict,
            }
        except Exception as exc:
            errors[inst.id] = str(exc)
    return {"sources": sources, "instances": instance_to_src, "errors": errors}
