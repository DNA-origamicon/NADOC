"""Persistence API for representation-independent nucleotide poses."""

from __future__ import annotations

from typing import Literal, Optional

import numpy as np

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.api import state as design_state
from backend.api.crud import _design_response, _design_response_with_geometry
from backend.core.models import Direction, NucleotideTransform

router = APIRouter()


class NucleotideTransformBody(BaseModel):
    kind: Literal["base", "extra_base"]
    helix_id: Optional[str] = None
    bp_index: Optional[int] = None
    direction: Optional[Direction] = None
    copy_k: int = Field(0, ge=0)
    crossover_id: Optional[str] = None
    extra_base_k: Optional[int] = Field(None, ge=0)
    pivot: list[float] = Field(min_length=3, max_length=3)
    translation: list[float] = Field(min_length=3, max_length=3)
    rotation: list[float] = Field(min_length=4, max_length=4)
    display_slab_offset: Optional[list[float]] = Field(None, min_length=3, max_length=3)
    display_slab_rotation: Optional[list[float]] = Field(None, min_length=4, max_length=4)
    compose: bool = False


def _quat_matrix(q: list[float]) -> np.ndarray:
    x, y, z, w = q
    return np.array([
        [1 - 2*(y*y + z*z), 2*(x*y - z*w), 2*(x*z + y*w)],
        [2*(x*y + z*w), 1 - 2*(x*x + z*z), 2*(y*z - x*w)],
        [2*(x*z - y*w), 2*(y*z + x*w), 1 - 2*(x*x + y*y)],
    ])


def _compose(existing: NucleotideTransform, delta: NucleotideTransform) -> NucleotideTransform:
    """Return delta(existing(p)) as one origin-pivoted rigid transform."""
    re, rd = _quat_matrix(existing.rotation), _quat_matrix(delta.rotation)
    pe, pd = np.asarray(existing.pivot), np.asarray(delta.pivot)
    be = pe - re @ pe + np.asarray(existing.translation)
    bd = pd - rd @ pd + np.asarray(delta.translation)
    r = rd @ re
    b = rd @ be + bd
    # matrix -> quaternion, using scipy's well-tested convention already used by NADOC.
    from scipy.spatial.transform import Rotation
    q = Rotation.from_matrix(r).as_quat().tolist()
    return delta.model_copy(update={
        "pivot": [0.0, 0.0, 0.0], "translation": b.tolist(), "rotation": q,
        "display_slab_offset": existing.display_slab_offset or delta.display_slab_offset,
        "display_slab_rotation": existing.display_slab_rotation or delta.display_slab_rotation,
    })


def _target_exists(design, transform: NucleotideTransform) -> bool:
    if transform.kind == "extra_base":
        connectors = [*design.crossovers, *design.forced_ligations]
        owner = next((x for x in connectors if x.id == transform.crossover_id), None)
        return owner is not None and transform.extra_base_k < len(owner.extra_bases or "")
    helix = next((h for h in design.helices if h.id == transform.helix_id), None)
    if helix is None or transform.bp_index < helix.bp_start or transform.bp_index >= helix.bp_start + helix.length_bp:
        return False
    from backend.core.sequences import domain_bp_range
    present = any(
        domain.helix_id == transform.helix_id
        and domain.direction == transform.direction
        and transform.bp_index in domain_bp_range(domain)
        for strand in design.strands for domain in strand.domains
    )
    if not present:
        return False
    if transform.copy_k == 0:
        return True
    loop_skip = next((ls for ls in helix.loop_skips if ls.bp_index == transform.bp_index), None)
    return loop_skip is not None and transform.copy_k <= max(0, loop_skip.delta)


@router.put("/design/nucleotide-transform", status_code=200)
def put_nucleotide_transform(body: NucleotideTransformBody) -> dict:
    """Create or replace the pose for one residue and push one undo step."""
    transform = NucleotideTransform(**body.model_dump(exclude={"compose"}))
    design = design_state.get_or_404()
    if not _target_exists(design, transform):
        raise HTTPException(404, detail="The nucleotide transform target does not exist in this design.")

    def apply(current):
        nonlocal transform
        transforms = list(current.nucleotide_transforms)
        idx = next((i for i, item in enumerate(transforms) if item.target_key() == transform.target_key()), None)
        if idx is None:
            transforms.append(transform)
        else:
            transform.id = transforms[idx].id
            if body.compose:
                transform = _compose(transforms[idx], transform)
            transforms[idx] = transform
        return current.copy_with(nucleotide_transforms=transforms)

    target = transform.target_key()
    updated, report, _entry = design_state.mutate_with_feature_log(
        "nucleotide-transform",
        f"Move/rotate nucleotide: {target}",
        {"target": list(target), "compose": body.compose},
        apply,
    )
    if transform.kind == "base":
        # apply_nucleotide_transforms_to_geometry bakes "base"-kind poses into
        # _geometry_for_helices' output (design_geometry.py) — the one real
        # helix genuinely needs its geometry re-shipped.
        return _design_response_with_geometry(
            updated, report, changed_helix_ids=[transform.helix_id],
        )
    # "extra_base" transforms are explicitly excluded from that bake-in
    # (design_geometry.py filters to kind == "base" only) — the pose is
    # applied client-side from design.nucleotide_transforms, same
    # geometry_unchanged/skipGeometry contract as the extra-bases routes.
    payload = _design_response(updated, report)
    payload["geometry_unchanged"] = True
    return payload


@router.delete("/design/nucleotide-transform/{transform_id}", status_code=200)
def delete_nucleotide_transform(transform_id: str) -> dict:
    """Remove one saved residue pose and push one undo step."""
    design = design_state.get_or_404()
    existing = next((t for t in design.nucleotide_transforms if t.id == transform_id), None)
    transforms = [t for t in design.nucleotide_transforms if t.id != transform_id]
    if len(transforms) == len(design.nucleotide_transforms):
        raise HTTPException(404, detail=f"Nucleotide transform {transform_id!r} not found.")
    updated, report, _entry = design_state.mutate_with_feature_log(
        "nucleotide-transform-delete",
        f"Reset nucleotide pose: {existing.target_key()}",
        {"transform_id": transform_id, "target": list(existing.target_key())},
        lambda current: current.copy_with(
            nucleotide_transforms=[t for t in current.nucleotide_transforms if t.id != transform_id]
        ),
    )
    # See put_nucleotide_transform: only "base"-kind poses are baked into real
    # helix geometry.
    if existing.kind == "base":
        return _design_response_with_geometry(
            updated, report, changed_helix_ids=[existing.helix_id],
        )
    payload = _design_response(updated, report)
    payload["geometry_unchanged"] = True
    return payload
