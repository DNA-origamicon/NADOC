"""Rigid movement and resizing of a bounded unbound radial thiol particle.

All positions and coverage metadata come from the unchanged native particle
replacement helper. Explicit current conjugation selectors protect the full
owned handle graph; no generated coordinates or identities become inputs.
"""

from typing import Annotated

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

from backend.api.part_nanoparticle_commands import GizmoMove, _Diameter, _Id, _Number
from backend.api.part_thiol_commands import (
    MAX_BASES, MAX_HANDLES, _fail, _source_free, _target, check_incoming,
    resolve_owned_handles, typed_ownership_supported,
)
from backend.core.nanoparticle import replace_gold_nanosphere
from backend.core.part_command_errors import CommandContractError, ReferenceResolutionError
from backend.core.part_history_proof import ProofBudgetExceeded
from backend.core.part_scope_references import identity_index


KINDS = frozenset({"nanoparticle-patch"})


class PatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    proof_version: Annotated[StrictInt, Field(ge=1, le=1)] = Field(alias="_proof_version")
    nanoparticle_version: StrictInt = Field(ge=1, le=1)
    thiol_version: StrictInt = Field(ge=1, le=1)
    nanoparticle_id: _Id
    conjugation_ids: list[_Id] = Field(min_length=1, max_length=MAX_HANDLES)
    diameter_nm: _Diameter | None = None
    pose: list[_Number] | None = Field(default=None, min_length=16, max_length=16)
    gizmo_move: GizmoMove | None = None
    coating: None = None

    @field_validator("conjugation_ids")
    @classmethod
    def unique_selection(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("conjugation_ids must be unique")
        return value


def parse_command(kind, params):
    if kind not in KINDS:
        raise ValueError("Unsupported native thiol particle patch")
    return PatchRequest.model_validate(params)


def resources(kind, params):
    parse_command(kind, params)
    return {"sources": (), "imports": False}


def _bounded_bases(index, selected):
    # No nucleotide expansion: ownership admission already requires the whole
    # backing domain, so its helix span is the exact selected base count.
    return sum(index[key].length_bp for key in selected if key[0] == "helix") <= MAX_BASES


def native_route_eligible(design, identity):
    """Preserve larger/coupled/opaque legacy routes before native evaluation."""
    particles = [item for item in design.nanoparticles if item.id == identity]
    if len(particles) != 1:
        return True  # Locked builder emits the structured reference failure.
    owned = [item for item in design.nanoparticle_conjugations if item.nanoparticle_id == identity]
    if (not _source_free(particles[0]) or not owned
            or any(record.bound_overhang_id is not None for item in owned for record in item.surface_strands)
            or any(item.nanoparticle_id == identity for item in design.nanoparticle_connection_versions)
            or sum(len(item.surface_strands) for item in owned) > MAX_HANDLES):
        return False
    try:
        index, _ = identity_index(design)
        selected = resolve_owned_handles(design, identity, [item.id for item in owned], index,
                                         parameter="conjugation_ids")
    except ReferenceResolutionError:
        return True  # Broken supported ownership must never become legacy work.
    except (NotImplementedError, CommandContractError):
        return False
    return _bounded_bases(index, selected) and typed_ownership_supported(design)


def build(kind, design, params):
    command = parse_command(kind, params)
    particle = _target(design, command.nanoparticle_id)
    if not _source_free(particle):
        _fail("Native thiol motion requires an uncoated, source-free gold particle",
              "nanoparticle", particle.id, ["nanoparticle_id"])
    if any(item.nanoparticle_id == particle.id for item in design.nanoparticle_connection_versions):
        _fail("Native thiol motion does not admit nanoparticle connection ownership",
              "nanoparticle", particle.id, ["nanoparticle_id"])
    index, _ = identity_index(design)
    selected = resolve_owned_handles(design, particle.id, command.conjugation_ids, index,
                                     parameter="conjugation_ids")
    if not _bounded_bases(index, selected):
        raise ProofBudgetExceeded("Native thiol motion admits at most 50,000 owned nucleotides")
    check_incoming(design, selected, parameter="conjugation_ids")
    return replace_gold_nanosphere(design, particle.id, diameter_nm=command.diameter_nm,
        pose=command.pose, gizmo_move=command.gizmo_move.model_dump() if command.gizmo_move else None)


def record(kind, label, inputs):
    """Capture current ownership together with the locked native input prefix."""
    from backend.api import state

    params = {**inputs, "_proof_version": 1, "nanoparticle_version": 1, "thiol_version": 1}

    def native(design):
        params["conjugation_ids"] = [item.id for item in design.nanoparticle_conjugations
                                     if item.nanoparticle_id == params["nanoparticle_id"]]
        try:
            return build(kind, design, params)
        except ReferenceResolutionError as error:
            raise HTTPException(404 if error.code == "missing_reference" else 422,
                                detail=error.as_issue()) from error
        except CommandContractError as error:
            raise HTTPException(422, detail=error.as_issue()) from error
        except ProofBudgetExceeded as error:
            raise HTTPException(413, detail={"code": "source_limit", "detail": str(error)}) from error
        except ValueError as error:
            raise HTTPException(422, detail=str(error)) from error

    return state.mutate_with_feature_log(kind, label, params, native)
