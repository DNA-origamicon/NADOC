"""Pattern request schemas, creation, and transactional feature editing."""

from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field, ValidationError

from backend.api import state
from backend.core.circular_pattern import create_circular_pattern
from backend.core.linear_pattern import create_linear_pattern
from backend.core.models import Design


class CircularPatternBody(BaseModel):
    cluster_id: str
    instances: int = Field(ge=1, le=128, strict=True)
    total_angle: float = Field(gt=0, le=360, allow_inf_nan=False)
    axis_point: list[float] = Field(min_length=3, max_length=3)
    axis_direction: list[float] = Field(min_length=3, max_length=3)
    expected_revision: int | None = None


class LinearPatternBody(BaseModel):
    cluster_ids: list[str] = Field(min_length=1)
    instances: int = Field(ge=1, le=128, strict=True)
    spacing: float = Field(allow_inf_nan=False)
    direction: Literal["X", "Y", "Z", "Custom"] = "X"
    vector: list[float] = Field(
        default_factory=lambda: [1, 0, 0], min_length=3, max_length=3
    )
    two_dimensional: bool = False
    instances2: int = Field(default=2, ge=1, le=128, strict=True)
    spacing2: float = Field(default=10, allow_inf_nan=False)
    direction2: Literal["X", "Y", "Z", "Custom"] = "Y"
    vector2: list[float] = Field(
        default_factory=lambda: [0, 1, 0], min_length=3, max_length=3
    )
    expected_revision: int | None = None


def build_pattern(kind, design, params, *, id_seed=None):
    schema, builder = (
        (CircularPatternBody, create_circular_pattern)
        if kind == "circular-pattern"
        else (LinearPatternBody, create_linear_pattern)
    )
    body = schema.model_validate(params)
    return builder(
        design, **body.model_dump(exclude={"expected_revision"}), id_seed=id_seed
    )


def pattern_label(kind, params):
    if kind == "circular-pattern":
        return f"Circular pattern: {params['instances']} instances · {params['total_angle']:g}°"

    def direction_label(suffix=""):
        direction = params[f"direction{suffix}"]
        if direction == "Custom":
            direction += (
                " (" + ", ".join(f"{v:g}" for v in params[f"vector{suffix}"]) + ")"
            )
        return direction

    counts = f"{params['instances']}"
    axes = f"{direction_label()} {params['spacing']:g} nm"
    if params.get("two_dimensional"):
        counts += f" × {params['instances2']}"
        axes += f", {direction_label('2')} {params['spacing2']:g} nm"
    return f"Linear pattern: {counts} instances · {axes}"


# Only these collections are created by the shared pattern copy engine.
PATTERN_FIELDS = (
    "helices",
    "strands",
    "crossovers",
    "forced_ligations",
    "lattice_frames",
    "cluster_transforms",
    "deformations",
)


def _remap(value, aliases):
    if isinstance(value, str):
        return aliases.get(value, value)
    if isinstance(value, list):
        return [_remap(v, aliases) for v in value]
    if isinstance(value, dict):
        return {k: _remap(v, aliases) for k, v in value.items()}
    return value


def edit_pattern_feature(design, index, params):
    """Replace the pattern's contribution, retaining IDs and independent later work.

    Rebuild the old parameters with the same deterministic key space as the new
    parameters to recover IDs even for legacy circular patterns with random IDs.
    Later snapshots are rebased only when independent of the edited copies.
    """
    from backend.api.crud import _build_entry_info, _seek_feature_log

    entry = design.feature_log[index]
    if entry.evicted or not entry.design_snapshot_gz_b64 or not entry.post_state_gz_b64:
        raise HTTPException(
            410, detail="Pattern snapshots were evicted; cannot edit this feature"
        )
    before = state.decode_design_snapshot(entry.design_snapshot_gz_b64)
    old = state.decode_design_snapshot(entry.post_state_gz_b64)
    params = {**entry.params, **params}
    try:
        schema = (
            CircularPatternBody
            if entry.op_kind == "circular-pattern"
            else LinearPatternBody
        )
        params = schema.model_validate(params).model_dump(exclude={"expected_revision"})
        replay, _, _ = build_pattern(
            entry.op_kind, before, entry.params, id_seed=entry.id
        )
        new, _, _ = build_pattern(entry.op_kind, before, params, id_seed=entry.id)
    except (ValidationError, ValueError) as exc:
        raise HTTPException(400, detail=str(exc)) from exc
    aliases, owned = {}, {}
    for field in PATTERN_FIELDS:
        prior = {item.id for item in getattr(before, field)}
        recorded = [item for item in getattr(old, field) if item.id not in prior]
        generated = [item for item in getattr(replay, field) if item.id not in prior]
        if len(recorded) != len(generated):
            raise HTTPException(
                409,
                detail="Pattern source cannot be reconstructed from its saved snapshot",
            )
        aliases.update({a.id: b.id for a, b in zip(generated, recorded, strict=True)})
        owned[field] = {item.id: item for item in recorded}
    new = Design.model_validate(_remap(new.model_dump(mode="json"), aliases))
    replacements = {}
    for field in PATTERN_FIELDS:
        prior = {item.id for item in getattr(before, field)}
        replacements[field] = {
            item.id: item for item in getattr(new, field) if item.id not in prior
        }
    owned_ids = set().union(*(set(items) for items in owned.values()))
    removed_ids = owned_ids - set().union(
        *(set(items) for items in replacements.values())
    )
    for later in design.feature_log[index + 1 :]:
        info = _build_entry_info(later, design)
        # Absolute cluster moves/deformations remain valid when their copies survive.
        affected = (
            owned_ids
            if later.feature_type in {"snapshot", "routing-cluster"}
            else removed_ids
        )
        if info.targets is None or info.targets & affected:
            raise HTTPException(
                409,
                detail="A later feature depends on these pattern copies. Revert that feature before editing this pattern.",
            )

    def rebase(target):
        changes = {}
        for field in PATTERN_FIELDS:
            items, seen = [], set()
            for item in getattr(target, field):
                if item.id not in owned[field]:
                    items.append(item)
                elif item.id in replacements[field]:
                    # Preserve later name/color/absolute pose edits on surviving copies.
                    original = owned[field][item.id]
                    override = {
                        key: getattr(item, key)
                        for key in type(item).model_fields
                        if getattr(item, key) != getattr(original, key)
                    }
                    items.append(
                        replacements[field][item.id].model_copy(update=override)
                    )
                seen.add(item.id)
            items.extend(
                item
                for iid, item in replacements[field].items()
                if iid not in owned[field] and iid not in seen
            )
            changes[field] = items
        return target.copy_with(**changes)

    post_b64, post_size = state.encode_design_snapshot(new)
    log = list(design.feature_log)
    log[index] = entry.model_copy(
        update={
            "params": params,
            "label": pattern_label(entry.op_kind, params),
            "post_state_gz_b64": post_b64,
            "post_state_size_bytes": post_size,
        }
    )
    for j in range(index + 1, len(log)):
        later = log[j]
        changes = {}
        for payload, size in (
            ("design_snapshot_gz_b64", "snapshot_size_bytes"),
            ("pre_state_gz_b64", "pre_state_size_bytes"),
            ("post_state_gz_b64", "post_state_size_bytes"),
        ):
            if getattr(later, payload, None):
                changes[payload], changes[size] = state.encode_design_snapshot(
                    rebase(state.decode_design_snapshot(getattr(later, payload)))
                )
        log[j] = later.model_copy(update=changes)
    # Start from the complete history even when the UI was scrubbed to an earlier step.
    full = _seek_feature_log(design, -1)
    return _seek_feature_log(rebase(full).copy_with(feature_log=log), -1)
