"""Reviewed recognition of authored definitions whose editable inputs are bad.

Recognition is neither executable schema admission nor dependency resolution.
The shared planner still checks exact expectations, protected identity and final
native schema; only complete root regeneration can produce a candidate.
"""

from dataclasses import dataclass

from backend.api.part_nanoparticle_commands import CreateRequest, DeleteRequest, PatchRequest
from backend.core.part_operation_input import validate_operation_input


@dataclass(frozen=True)
class RepairContract:
    family: str
    inputs_valid: bool


_GOLD = {
    "nanoparticle-create": CreateRequest,
    "nanoparticle-patch": PatchRequest,
    "nanoparticle-delete": DeleteRequest,
}
_BASE_FIELDS = frozenset({"_proof_version", "nanoparticle_version", "nanoparticle_id"})
_REVIEWED_FIELDS = {
    "nanoparticle-create": _BASE_FIELDS | {"diameter_nm"},
    "nanoparticle-patch": _BASE_FIELDS | {"diameter_nm", "pose", "gizmo_move", "coating"},
    "nanoparticle-delete": _BASE_FIELDS,
}
_OTHER_PARTICLES = frozenset({"coating_version", "thiol_version", "quantum_dot_version"})


def recognize_gold_inputs(kind, params):
    """Recognize only an exact unscoped gold v1 envelope, without repairing it.

    Existing diameter/pose fields are masked solely for schema classification.
    Neither these probe values nor Pydantic defaults leave this function. Missing
    fields are never inserted, and all other inputs retain the native schema checks,
    including output identity, versions, gizmo structure and absent coating.
    """
    model = _GOLD.get(kind)
    if (model is None or type(params) is not dict or "_generated_scope" in params
            or _OTHER_PARTICLES.intersection(params)):
        return None
    try:
        validate_operation_input(params)
        # A future native schema expansion requires a separate repair review;
        # accepting a new field could otherwise add unprotected output identity.
        if {field.alias or name for name, field in model.model_fields.items()} != _REVIEWED_FIELDS[kind]:
            return None
        if any(type(params.get(key)) is not int or params[key] != 1
               for key in ("_proof_version", "nanoparticle_version")):
            return None
        values = {key: value for key, value in params.items() if key != "_generator"}
        # Native constraints still own every unchanged envelope value; the
        # inventory above only detects an unreviewed schema expansion.
        probe = dict(values)
        if "diameter_nm" in probe:
            probe["diameter_nm"] = 1.0
        if kind == "nanoparticle-patch" and "pose" in probe:
            probe["pose"] = None
        model.model_validate(probe)
        try:
            model.model_validate(values)
        except ValueError:
            return RepairContract("source-free-gold-v1", inputs_valid=False)
        return RepairContract("source-free-gold-v1", inputs_valid=True)
    except (TypeError, ValueError):
        return None


def recognizes_invalid_inputs(kind, params):
    """Planner callback. No generic kind-only or numerical/source fallback."""
    return recognize_gold_inputs(kind, params) is not None
