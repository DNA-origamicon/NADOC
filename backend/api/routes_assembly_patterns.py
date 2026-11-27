"""Assembly-owned pattern commands using the same parameters as part patterns."""

import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.api import assembly_state
from backend.api.assembly import (
    _apply_assembly_mutation_with_feature_log,
    _assembly_response,
)
from backend.api.pattern_features import (
    LinearPatternBody,
    CircularPatternBody,
    pattern_label,
)
from backend.core.assembly_patterns import pattern_assembly

router = APIRouter()


class AssemblyPatternBody(BaseModel):
    instance_ids: list[str] = Field(min_length=1)
    parameters: dict
    expected_assembly_id: str
    expected_revision: int = Field(ge=0)
    expected_feature_ids: list[str]


def validate_parameters(kind, parameters, ids):
    schema = LinearPatternBody if kind == "linear-pattern" else CircularPatternBody
    validated = schema.model_validate(
        {**parameters, "cluster_ids": ids, "cluster_id": ids[0]}
    )
    return validated.model_dump(
        exclude={
            "cluster_id",
            "cluster_ids",
            "expected_revision",
            "expected_design_id",
            "organization_copy",
        }
    )


def create_pattern(kind, body):
    assembly = assembly_state.get_or_404()
    if (
        assembly_state.revision() != body.expected_revision
        or assembly.id != body.expected_assembly_id
        or [e.id for e in assembly.feature_log] != body.expected_feature_ids
        or assembly.feature_log_cursor != -1
    ):
        raise HTTPException(409, "The assembly changed. Reopen the pattern tool.")
    try:
        params = validate_parameters(kind, body.parameters, body.instance_ids)
        params.update(instance_ids=body.instance_ids, id_seed=str(uuid.uuid4()))
        mutated = pattern_assembly(assembly, f"assembly-{kind}", params)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    result = _apply_assembly_mutation_with_feature_log(
        mutated,
        op_kind=f"assembly-{kind}",
        label=pattern_label(kind, params),
        params=params,
    )
    return _assembly_response(result)


@router.post("/assembly/linear-pattern")
def linear_pattern(body: AssemblyPatternBody):
    return create_pattern("linear-pattern", body)


@router.post("/assembly/circular-pattern")
def circular_pattern(body: AssemblyPatternBody):
    return create_pattern("circular-pattern", body)


def edit_pattern(assembly, index, overrides):
    """Transactional suffix replay; failed dependent copies leave the document intact."""
    from backend.api.assembly import _REPLAYABLE_OP_KINDS, _replay_assembly_op

    entries = assembly.feature_log[index:]
    if any(e.op_kind not in _REPLAYABLE_OP_KINDS for e in entries):
        raise HTTPException(
            422, "A later feature cannot be replayed. Revert it before editing."
        )
    previous = assembly_state.lookup_pre_state(assembly.feature_log, index)
    log = list(assembly.feature_log[:index])
    previous = previous.model_copy(
        update={"feature_log": log, "feature_log_cursor": -1}
    )
    for offset, entry in enumerate(entries):
        params = dict(entry.params)
        if offset == 0:
            try:
                validated = validate_parameters(
                    entry.op_kind.removeprefix("assembly-"),
                    {**params, **overrides},
                    params["instance_ids"],
                )
            except ValueError as error:
                raise HTTPException(422, str(error)) from error
            params = {
                **validated,
                "instance_ids": params["instance_ids"],
                "id_seed": params["id_seed"],
            }
        replayed = _replay_assembly_op(previous, entry.op_kind, params)
        pre, pre_size = assembly_state.encode_assembly_snapshot(previous)
        post, post_size = assembly_state.encode_assembly_snapshot(replayed)
        label = (
            pattern_label(entry.op_kind.removeprefix("assembly-"), params)
            if offset == 0
            else entry.label
        )
        log = log + [
            entry.model_copy(
                update=dict(
                    params=params,
                    label=label,
                    design_snapshot_gz_b64=pre,
                    snapshot_size_bytes=pre_size,
                    post_state_gz_b64=post,
                    post_state_size_bytes=post_size,
                    evicted=False,
                    diff_added_b64="",
                    diff_removed_ids=[],
                    diff_modified_b64="",
                    pre_state_from_previous=False,
                )
            )
        ]
        previous = replayed.model_copy(
            update={"feature_log": log, "feature_log_cursor": -1}
        )
    assembly_state.set_assembly(previous)
    return _assembly_response(previous)
