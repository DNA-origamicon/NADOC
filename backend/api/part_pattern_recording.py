"""Closed native pattern choices and thin shared-host entry points."""

import json

from fastapi import HTTPException

from backend.api.part_native_commands import PATTERN_COMMANDS
from backend.api.pattern_features import CircularPatternBody, LinearPatternBody
from backend.core.part_operation_input import validate_operation_input


def _refuse(message, *, code="pattern_conflict", status=409):
    raise HTTPException(status, detail={"code": code, "detail": message})


def _inputs(kind, inputs, *, previous=None):
    """Own JSON choices; identity/version slots always come from the host/row."""
    from backend.core.part_pattern_organization import parse_organization_copy

    if type(kind) is not str or kind not in PATTERN_COMMANDS or type(inputs) is not dict:
        _refuse("Select a supported native pattern", code="invalid_pattern_input", status=422)
    validate_operation_input(inputs)
    schema = CircularPatternBody if kind == "circular-pattern" else LinearPatternBody
    fields = {field.alias or name for name, field in schema.model_fields.items()
              if name not in {"expected_revision", "expected_design_id"}}
    identities = {"history_seed", "_proof_version"}
    if set(inputs) - fields - (identities if previous is not None else set()):
        _refuse("Pattern input has unknown fields", code="invalid_pattern_input", status=422)
    if previous is not None:
        if any(key in inputs and inputs[key] != previous.get(key) for key in identities):
            _refuse("Pattern output identities and proof version cannot be changed")
        merged = {key: value for key, value in previous.items() if key in fields}
        merged.update({key: value for key, value in inputs.items() if key in fields})
    else:
        merged = inputs
    validate_operation_input(merged)
    body = schema.model_validate_json(json.dumps(merged, allow_nan=False))
    normalized = body.model_dump(mode="json", by_alias=True,
                                 exclude={"expected_revision", "expected_design_id"})
    contract = parse_organization_copy(normalized.get("_organization_copy"))
    if contract is None:
        _refuse("Choose copied groups explicitly, including an empty list for none",
                code="organization_copy_required", status=422)
    return normalized


def create(kind, inputs, *, expected_design_id, expected_revision, cancelled=None):
    from backend.api.part_ordinary_recipe_recording import run_pattern

    return run_pattern(kind, inputs, expected_design_id=expected_design_id,
                       expected_revision=expected_revision, cancelled=cancelled)


def edit(index, params, *, expected_feature_id, expected_design_id, expected_revision, cancelled=None):
    from backend.api.part_ordinary_recipe_recording import run_pattern

    return run_pattern(None, params, index=index, expected_feature_id=expected_feature_id,
                       expected_design_id=expected_design_id, expected_revision=expected_revision,
                       cancelled=cancelled)
