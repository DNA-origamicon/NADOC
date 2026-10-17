"""Source-free, uncoated gold particle recipes using the existing native builders.

Decorations and attachment ownership require their own contracts. Their legacy
routes remain available, but cannot enter this narrowly versioned executor.
"""

from typing import Annotated

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, model_validator

from backend.core.nanoparticle import create_gold_nanosphere, replace_gold_nanosphere
from backend.core.part_command_errors import ReferenceResolutionError


KINDS = frozenset({"nanoparticle-create", "nanoparticle-patch", "nanoparticle-delete"})
_Id = Annotated[str, Field(strict=True, min_length=1, max_length=256)]
_Number = Annotated[float, Field(strict=True, allow_inf_nan=False)]
_Diameter = Annotated[_Number, Field(gt=0, le=1000)]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proof_version: Annotated[StrictInt, Field(ge=1, le=1)] = Field(alias="_proof_version")
    nanoparticle_version: StrictInt = Field(ge=1, le=1)
    nanoparticle_id: _Id


class CreateRequest(_Input):
    diameter_nm: _Diameter


class GizmoMove(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pivot: list[_Number] = Field(min_length=3, max_length=3)
    translation: list[_Number] = Field(min_length=3, max_length=3)
    rotation: list[_Number] = Field(min_length=4, max_length=4)
    preconstrained: StrictBool = False

    @model_validator(mode="after")
    def rotation_exists(self):
        if not any(self.rotation):
            raise ValueError("Gizmo rotation must have a nonzero quaternion")
        return self


class PatchRequest(_Input):
    diameter_nm: _Diameter | None = None
    pose: list[_Number] | None = Field(default=None, min_length=16, max_length=16)
    gizmo_move: GizmoMove | None = None
    # Explicitly removing an already absent coating is an authored native no-op.
    coating: None = None


class DeleteRequest(_Input):
    pass


def parse_command(kind, params):
    if "thiol_version" in params:
        from backend.api.part_thiol_patch_commands import parse_command as parse_thiol_patch
        return parse_thiol_patch(kind, params)
    if "quantum_dot_version" in params:
        from backend.api.part_quantum_dot_commands import parse_command as parse_quantum_dot
        return parse_quantum_dot(kind, params)
    model = {"nanoparticle-create": CreateRequest, "nanoparticle-patch": PatchRequest,
             "nanoparticle-delete": DeleteRequest}.get(kind)
    if model is None:
        raise ValueError("Unsupported source-free nanoparticle command")
    return model.model_validate(params)


def resources(kind, params):
    if "thiol_version" in params:
        from backend.api.part_thiol_patch_commands import resources as thiol_resources
        return thiol_resources(kind, params)
    if "quantum_dot_version" in params:
        from backend.api.part_quantum_dot_commands import resources as quantum_dot_resources
        return quantum_dot_resources(kind, params)
    parse_command(kind, params)
    return {"sources": (), "imports": False}


def _fail(detail, identity, *, missing=False):
    raise ReferenceResolutionError(detail,
        code="missing_reference" if missing else "invalid_selection",
        references=[{"kind": "nanoparticle", "identity": identity,
                     "parameter_path": ["nanoparticle_id"]}])


def _incoming_owner(design, identity):
    # These are the complete direct nanoparticle references in the typed part
    # schema. Duplex ends refer to overhangs; ownership of their NP surface ends
    # passes through these records or the particle's biotin_dna declaration.
    return any(item.nanoparticle_id == identity for item in design.nanoparticle_conjugations) or any(
        item.nanoparticle_id == identity for item in design.nanoparticle_connection_versions)


def source_free_target(design, identity):
    """Route eligibility only; the executor rechecks against its locked input."""
    matches = [item for item in design.nanoparticles if item.id == identity]
    if len(matches) != 1:
        _fail("Nanoparticle target is missing or ambiguous", identity, missing=not matches)
    particle = matches[0]
    return (particle.kind == "gold_nanosphere" and particle.quantum_dot is None
            and particle.coating is None and not particle.biotin_dna
            and not _incoming_owner(design, identity))


def route_source_free_target(design, identity):
    try:
        return source_free_target(design, identity)
    except ReferenceResolutionError as error:
        raise HTTPException(404 if error.code == "missing_reference" else 422,
                            detail=error.as_issue()) from error


def build(kind, design, params, *, resolver=None):
    if "thiol_version" in params:
        from backend.api.part_thiol_patch_commands import build as build_thiol_patch
        return build_thiol_patch(kind, design, params)
    if "quantum_dot_version" in params:
        from backend.api.part_quantum_dot_commands import build as build_quantum_dot
        return build_quantum_dot(kind, design, params, resolver=resolver)
    body = parse_command(kind, params)
    identity = body.nanoparticle_id
    if kind == "nanoparticle-create":
        if any(item.id == identity for item in design.nanoparticles) or _incoming_owner(design, identity):
            _fail("Nanoparticle output identity already exists or has dependent ownership", identity)
        particle = create_gold_nanosphere(body.diameter_nm, nanoparticle_id=identity)
        return design.copy_with(nanoparticles=[*design.nanoparticles, particle])
    if not source_free_target(design, identity):
        _fail("This native command requires an uncoated gold particle without DNA or connection ownership", identity)
    if kind == "nanoparticle-patch":
        return replace_gold_nanosphere(design, identity, diameter_nm=body.diameter_nm,
            pose=body.pose, gizmo_move=body.gizmo_move.model_dump() if body.gizmo_move else None)
    return design.copy_with(nanoparticles=[item for item in design.nanoparticles if item.id != identity])


def record(kind, label, inputs):
    """Thin live adapter: evaluate and record under the shared atomic state lock."""
    from backend.api import state

    params = {**inputs, "_proof_version": 1, "nanoparticle_version": 1}

    def native(design):
        try:
            return build(kind, design, params)
        except ReferenceResolutionError as error:
            raise HTTPException(404 if error.code == "missing_reference" else 422,
                                detail=error.as_issue()) from error
        except ValueError as error:
            raise HTTPException(422, detail=str(error)) from error

    return state.mutate_with_feature_log(kind, label, params, native)
