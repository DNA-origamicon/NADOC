"""Pure derivation + caching of an assembly instance's display-geometry inputs.

This is the HTTP-free service kernel behind the assembly geometry routers
(``routes_assembly_geometry`` / ``routes_assembly_frames``). It owns three
concerns, all pure (``backend/core`` never imports ``backend/api``):

* **Geometry-result LRU** — ``_GEO_CACHE`` keyed by a stable per-instance key,
  so the expensive ``_geometry_for_design`` pipeline is not re-run on
  undo/redo, reassembly rebuilds, or tab switches back to the same instance.
* **Cache-key compute** — ``geo_cache_key`` turns a ``PartInstance`` (its
  ``source`` + ``cluster_transform_overrides``) into a stable string, or
  ``None`` when the instance is not cacheable. The workspace directory is an
  **explicit parameter** (not a module global) so the api layer's
  monkeypatch-able ``_WORKSPACE_DIR`` remains the single source of truth.
* **Override merge** — ``merge_cluster_overrides`` folds an instance's
  assembly-scoped ``cluster_transform_overrides`` onto a loaded design's
  ``cluster_transforms`` (the pure half of ``_design_with_instance_overrides``;
  the file-IO load itself stays in the api layer, L4-blocked on ``HTTPException``).

Extracted from ``backend/api/assembly.py`` (router carve-up Refactor #49).
"""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # avoid a runtime import cycle cost; types only
    from backend.core.models import Design, PartInstance


# Geometry result cache: {cache_key: {"nucleotides": [...], "helix_axes": [...], ...}}
_GEO_CACHE: "OrderedDict[str, dict]" = OrderedDict()
_GEO_CACHE_MAX = 16


def geo_cache_key(inst: "PartInstance", workspace_dir: Path | None) -> str | None:
    """Return a stable cache key for an instance's geometry, or None if not cacheable."""
    overrides = inst.cluster_transform_overrides or []
    try:
        ov_str = json.dumps(
            [co.model_dump() for co in overrides],
            sort_keys=True, separators=(',', ':'),
        )
    except Exception:
        return None
    ov_hash = hashlib.sha256(ov_str.encode()).hexdigest()[:12] if overrides else ''

    src = inst.source
    if src.type == 'file':
        p = Path(src.path)
        if not p.is_absolute():
            for base in filter(None, [workspace_dir]):
                candidate = (base / p).resolve()
                if candidate.is_file():
                    p = candidate
                    break
            else:
                return None
        if not p.is_file():
            return None
        mtime_ns = p.stat().st_mtime_ns
        return f"f:{p}:{mtime_ns}:{ov_hash}"
    elif src.type == 'inline' and src.design:
        return f"i:{src.design.id}:{ov_hash}"
    return None


def geo_cache_get(key: str) -> dict | None:
    if key not in _GEO_CACHE:
        return None
    _GEO_CACHE.move_to_end(key)
    return _GEO_CACHE[key]


def geo_cache_set(key: str, value: dict) -> None:
    if key in _GEO_CACHE:
        _GEO_CACHE.move_to_end(key)
    _GEO_CACHE[key] = value
    while len(_GEO_CACHE) > _GEO_CACHE_MAX:
        _GEO_CACHE.popitem(last=False)


def clear_geo_cache() -> None:
    """Drop all cached geometry (called when an instance's source design changes)."""
    _GEO_CACHE.clear()


def merge_cluster_overrides(design: "Design", overrides) -> "Design":
    """Return ``design`` with assembly-scoped cluster-transform overrides merged in.

    ``overrides`` is an instance's ``cluster_transform_overrides`` list. Each
    override replaces the design's same-id ``cluster_transform``; overrides with
    ids absent from the design are appended. Returns ``design`` unchanged (no
    copy) when there are no overrides — the common case.
    """
    if not overrides:
        return design
    by_id = {ct.id: ct for ct in overrides}
    merged = [by_id.get(ct.id, ct) for ct in design.cluster_transforms]
    existing = {ct.id for ct in merged}
    merged.extend(ct for ct in overrides if ct.id not in existing)
    return design.copy_with(cluster_transforms=merged)
