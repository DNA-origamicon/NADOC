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
from backend.api import part_nanoparticle_connection_commands as pending_commands


KINDS = frozenset({"nanoparticle-patch"})
MAX_PENDING_VERSIONS = 128


class PatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    proof_version: Annotated[StrictInt, Field(ge=1, le=1)] = Field(alias="_proof_version")
    nanoparticle_version: StrictInt = Field(ge=1, le=1)
    thiol_version: StrictInt = Field(ge=1, le=1)
    nanoparticle_id: _Id
    conjugation_ids: list[_Id] = Field(min_length=1, max_length=MAX_HANDLES)
    pending_connection_version_ids: list[_Id] = Field(default_factory=list, max_length=MAX_PENDING_VERSIONS)
    diameter_nm: _Diameter | None = None
    pose: list[_Number] | None = Field(default=None, min_length=16, max_length=16)
    gizmo_move: GizmoMove | None = None
    coating: None = None

    @field_validator("conjugation_ids", "pending_connection_version_ids")
    @classmethod
    def unique_selection(cls, value, info):
        if len(set(value)) != len(value):
            raise ValueError(f"{info.field_name} must be unique")
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
    has_versions = bool(design.nanoparticle_connection_versions)
    if has_versions and not pending_commands._record_count_bounded(design):
        return False
    particles = [item for item in design.nanoparticles if item.id == identity]
    if len(particles) != 1:
        return True  # Locked builder emits the structured reference failure.
    owned = [item for item in design.nanoparticle_conjugations if item.nanoparticle_id == identity]
    versions = [item for item in design.nanoparticle_connection_versions if item.nanoparticle_id == identity]
    if (not _source_free(particles[0]) or not owned
            or any(record.bound_overhang_id is not None for item in owned for record in item.surface_strands)
            or len(versions) > MAX_PENDING_VERSIONS
            or any(not pending_commands._pending(item) or item.nanoparticle_attach is None
                   or item.target_attach is None for item in versions)
            or sum(len(item.surface_strands) for item in owned) > MAX_HANDLES):
        return False
    try:
        if has_versions:
            index = pending_commands._prepare_source(design).index
        else:
            index, _ = identity_index(design)
        selected = resolve_owned_handles(design, identity, [item.id for item in owned], index,
                                         parameter="conjugation_ids")
    except ReferenceResolutionError:
        return True  # Broken supported ownership must never become legacy work.
    except (NotImplementedError, CommandContractError):
        return False
    return _bounded_bases(index, selected) and (has_versions or typed_ownership_supported(design))


def build(kind, design, params):
    command = parse_command(kind, params)
    particle = _target(design, command.nanoparticle_id)
    if not _source_free(particle):
        _fail("Native thiol motion requires an uncoated, source-free gold particle",
              "nanoparticle", particle.id, ["nanoparticle_id"])
    if design.nanoparticle_connection_versions or command.pending_connection_version_ids:
        prepared = pending_commands._prepare_source(design)
        index = prepared.index
    else:
        prepared = None
        index, _ = identity_index(design)
    selected = resolve_owned_handles(design, particle.id, command.conjugation_ids, index,
                                     parameter="conjugation_ids")
    if not _bounded_bases(index, selected):
        raise ProofBudgetExceeded("Native thiol motion admits at most 50,000 owned nucleotides")
    if prepared is not None:
        selected |= pending_commands.validate_pending_selection(design, particle.id,
            command.pending_connection_version_ids, prepared, selected)
    check_incoming(design, selected, parameter="conjugation_ids")
    return replace_gold_nanosphere(design, particle.id, diameter_nm=command.diameter_nm,
        pose=command.pose, gizmo_move=command.gizmo_move.model_dump() if command.gizmo_move else None)


def record(kind, label, inputs):
    """Capture current ownership together with the locked native input prefix."""
    from backend.api import state

    params = {**inputs, "_proof_version": 1, "nanoparticle_version": 1, "thiol_version": 1}

    def native(design):
        try:
            if design.nanoparticle_connection_versions and not pending_commands._record_count_bounded(design):
                raise CommandContractError("Pending motion source exceeds its reference allowance",
                                           code="unsupported_np_connection_source")
            params["conjugation_ids"] = [item.id for item in design.nanoparticle_conjugations
                                         if item.nanoparticle_id == params["nanoparticle_id"]]
            params["pending_connection_version_ids"] = [item.id for item in design.nanoparticle_connection_versions
                                                       if item.nanoparticle_id == params["nanoparticle_id"]]
            # The recorder appends in place; do not append its row to the old
            # source's log through the native helper's retained list alias.
            return build(kind, design, params).copy_with(feature_log=list(design.feature_log))
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
