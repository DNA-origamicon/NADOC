"""Input-only pending ordinary-overhang candidates; no materialization authority.

The three closed actions reuse overhang-bulk without changing numerical model
pins. Applied versions and legacy request shapes retain their compatibility path.
"""

from dataclasses import dataclass
from math import isfinite
from time import time
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator

from backend.core.connection_versions import assign_default_names, clean_sequence
from backend.core.models import ConnectionVersion
from backend.core.part_command_errors import CommandContractError, ReferenceResolutionError
from backend.core.part_operation_input import MAX_OPERATION_BYTES, MAX_OPERATION_NODES, validate_operation_input


CREATE = "connection-version-create"
PATCH = "connection-version-patch"
DELETE = "connection-version-delete"
ACTIONS = frozenset({CREATE, PATCH, DELETE})
_Id = Annotated[str, Field(strict=True, min_length=1, max_length=256)]
_Name = Annotated[str, Field(strict=True, max_length=256)]
_Sequence = Annotated[str, Field(strict=True, max_length=16_384)]
_Bridge = Annotated[StrictInt, Field(ge=0, le=50_000)]
_Type = Literal[
    "end-to-root", "root-to-root", "root-to-root-indirect", "end-to-end-indirect",
    "root-to-root-ssdna-linker", "end-to-end-ssdna-linker",
    "end-to-root-ssdna-linker", "root-to-end-ssdna-linker",
    "root-to-root-dsdna-linker", "end-to-end-dsdna-linker",
    "end-to-root-dsdna-linker", "root-to-end-dsdna-linker",
]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    proof_version: Annotated[StrictInt, Field(ge=1, le=1)] = Field(alias="_proof_version")
    connection_version_contract: Annotated[StrictInt, Field(ge=1, le=1)]
    version_id: _Id
    overhang_a_id: _Id
    overhang_b_id: _Id


class CreateRequest(_Input):
    action: Literal["connection-version-create"]
    name: _Name
    created_at: Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]
    connection_type: _Type
    overhang_a_seq: _Sequence | None
    overhang_b_seq: _Sequence | None
    bridge_length: _Bridge
    bridge_seq: _Sequence | None
    applied: StrictBool

    @field_validator("applied")
    @classmethod
    def pending_only(cls, value):
        if value:
            raise ValueError("Pending candidate creation requires applied=false")
        return value


class Patch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: _Name | None = None
    connection_type: _Type | None = None
    overhang_a_seq: _Sequence | None = None
    overhang_b_seq: _Sequence | None = None
    bridge_length: _Bridge | None = None
    bridge_seq: _Sequence | None = None


class PatchRequest(_Input):
    action: Literal["connection-version-patch"]
    patch: Patch


class DeleteRequest(_Input):
    action: Literal["connection-version-delete"]


def parse_command(params):
    validate_operation_input(params)
    if not is_pending_action(params):
        raise ValueError("Unsupported pending connection action")
    model = {CREATE: CreateRequest, PATCH: PatchRequest, DELETE: DeleteRequest}.get(params["action"])
    if model is None:
        raise ValueError("Unsupported pending connection action")
    return model.model_validate(params)


def is_pending_action(params):
    return type(params) is dict and type(params.get("action")) is str and params["action"] in ACTIONS


def metadata_policy(kind, params):
    """Closed shared policy; a malformed claimed new action raises before work."""
    if kind != "overhang-bulk" or not is_pending_action(params):
        return False
    parse_command(params)
    return True


def is_metadata_command(kind, params):
    """Safe classification; marker presence alone never skips postprocessing."""
    try:
        return metadata_policy(kind, params)
    except ValueError:
        return False


def _fail(detail, kind, identity, parameter, *, missing=False):
    raise ReferenceResolutionError(detail, code="missing_reference" if missing else "invalid_selection",
        references=[{"kind": kind, "identity": identity, "parameter_path": [parameter]}])


def _resolve(index, identity, kind, parameter):
    value = index.get(identity)
    if value is None:
        _fail("Selected pending connection input is missing", kind, identity, parameter, missing=True)
    return value


@dataclass(frozen=True, slots=True)
class _Inventory:
    source: object
    overhangs: dict
    versions: dict


def _inventory(design):
    """Bound only metadata used by exact selection/default naming before hashing.

    No geometry, saved topology, atom arrays or unrelated ownership is traversed.
    ConnectionVersion currently has no typed incoming owners outside this list.
    """
    if 2 * len(design.overhangs) + 6 * len(design.connection_versions) > MAX_OPERATION_NODES:
        raise CommandContractError("Pending connection metadata exceeds its structural allowance",
                                   code="unsupported_connection_version_source")
    size, indices = 0, []
    for rows, kind, fields in ((design.overhangs, "overhang", ("id",)),
                              (design.connection_versions, "connection_version",
                               ("id", "overhang_a_id", "overhang_b_id", "name"))):
        index = {}
        for row in rows:
            for field in fields:
                value = getattr(row, field)
                if type(value) is not str or len(value) > 256 or (field != "name" and not value):
                    raise CommandContractError("Pending connection source has unsupported metadata",
                                               code="unsupported_connection_version_source")
                size += 16 + 4 * len(value)
                if size > MAX_OPERATION_BYTES:
                    raise CommandContractError("Pending connection metadata exceeds its byte allowance",
                                               code="unsupported_connection_version_source")
            if kind == "connection_version" and (
                    type(row.created_at) not in {int, float}
                    or (type(row.created_at) is int and row.created_at.bit_length() > 64)
                    or not isfinite(row.created_at)):
                raise CommandContractError("Pending connection creation order is not finite",
                                           code="unsupported_connection_version_source")
            if row.id in index:
                _fail("Pending connection identity is ambiguous", kind, row.id,
                      "version_id" if kind == "connection_version" else "overhang_a_id")
            index[row.id] = row
        indices.append(index)
    return _Inventory(design, *indices)


def _build(design, body, inventory):
    if inventory.source is not design:
        raise CommandContractError("Pending connection preparation belongs to another source", code="source_changed")
    version = None
    if body.action != CREATE:
        version = _resolve(inventory.versions, body.version_id, "connection_version", "version_id")
        if version.applied:
            _fail("Native pending edits cannot alter an applied connection", "connection_version", version.id, "version_id")
        for field in ("overhang_a_id", "overhang_b_id"):
            if getattr(version, field) != getattr(body, field):
                _fail("Selected pending connection endpoint changed", "overhang", getattr(body, field), field)
    elif body.version_id in inventory.versions:
        _fail("Pending connection output identity already exists", "connection_version", body.version_id, "version_id")
    for field in ("overhang_a_id", "overhang_b_id"):
        selected = _resolve(inventory.overhangs, getattr(body, field), "overhang", field)
        if selected.auxiliary_endpoint:
            _fail("Pending ordinary connections require ordinary overhangs", "overhang", selected.id, field)
    if body.overhang_a_id == body.overhang_b_id:
        _fail("A pending connection needs two distinct overhangs", "overhang", body.overhang_b_id, "overhang_b_id")

    if body.action == CREATE:
        version = ConnectionVersion(id=body.version_id, name=body.name.strip(), created_at=body.created_at,
            overhang_a_id=body.overhang_a_id, overhang_b_id=body.overhang_b_id,
            connection_type=body.connection_type, overhang_a_seq=clean_sequence(body.overhang_a_seq),
            overhang_b_seq=clean_sequence(body.overhang_b_seq), bridge_length=body.bridge_length,
            bridge_seq=clean_sequence(body.bridge_seq), applied=False)
        # The unchanged helper can name earlier blank legacy rows too. Copy those
        # mutable records first; existing applied/topology state remains untouched.
        result = design.copy_with(connection_versions=[*[v.model_copy() for v in design.connection_versions], version])
        assign_default_names(result)
        return result
    if body.action == DELETE:
        return design.copy_with(connection_versions=[v for v in design.connection_versions if v.id != version.id])
    patch, updates = body.patch.model_dump(exclude_unset=True), {}
    if (patch.get("name") or "").strip():
        updates["name"] = patch["name"].strip()
    if patch.get("connection_type"):
        updates["connection_type"] = patch["connection_type"]
    for field in ("overhang_a_seq", "overhang_b_seq", "bridge_seq"):
        if field in patch:
            updates[field] = clean_sequence(patch[field])
    if patch.get("bridge_length") is not None:
        updates["bridge_length"] = patch["bridge_length"]
    return design.copy_with(connection_versions=[v.model_copy(update=updates) if v.id == version.id else v
                                                  for v in design.connection_versions])


def build(design, params):
    return _build(design, parse_command(params), _inventory(design))


def try_record(action, choices, *, version_id=None):
    """Select, freeze defaults and record under the existing document lock.

    Only unsupported compatibility scope returns None. A native reference or
    publication failure is explicit and never falls back after evaluation.
    """
    from backend.api import state
    from backend.api.feature_recording import record_feature

    try:
        with state._lock:
            state._require_compatibility_write("pending_connection_version")
            session = state._session()
            source = session.design
            if source is None:
                raise HTTPException(404, detail="No active design.")
            try:
                inventory = _inventory(source)
            except ReferenceResolutionError:
                raise
            except CommandContractError:
                return None
            version = None if action == CREATE else _resolve(
                inventory.versions, version_id, "connection_version", "version_id")
            if (version is not None and version.applied) or choices.get("applied"):
                return None
            if action == PATCH and "applied" in choices:
                return None  # Preserve explicit compatibility flag changes.
            values = {"_proof_version": 1, "connection_version_contract": 1, "action": action,
                "version_id": version_id or "pending", "overhang_a_id": choices.get("overhang_a_id") if version is None else version.overhang_a_id,
                "overhang_b_id": choices.get("overhang_b_id") if version is None else version.overhang_b_id}
            if action == CREATE:
                values.update(name=(choices.get("name") or "").strip(), created_at=0.0,
                    connection_type=choices.get("connection_type"), overhang_a_seq=choices.get("overhang_a_seq"),
                    overhang_b_seq=choices.get("overhang_b_seq"), bridge_seq=choices.get("bridge_seq"),
                    bridge_length=max(0, int(choices.get("bridge_length") or 0)), applied=False)
            elif action == PATCH:
                values["patch"] = dict(choices)
                if values["patch"].get("bridge_length") is not None:
                    values["patch"]["bridge_length"] = max(0, values["patch"]["bridge_length"])
            try:
                parse_command(values)
            except ValueError:
                return None
            if any(inventory.overhangs.get(values[field]) is not None
                   and inventory.overhangs[values[field]].auxiliary_endpoint
                   for field in ("overhang_a_id", "overhang_b_id")):
                return None
            state._assert_active_loadout_editable(source)
            if action == CREATE:
                values.update(version_id=str(uuid4()), created_at=time())
            body = parse_command(values)

            def native(design):
                if session.design is not source or design is not source:
                    raise HTTPException(409, detail="Pending connection source changed before recording.")
                return _build(design, body, inventory).copy_with(feature_log=list(design.feature_log))

            label = {CREATE: "Create", PATCH: "Edit", DELETE: "Delete"}[action] + " pending connection"
            return record_feature(session, "overhang-bulk", label, values, native)
    except ReferenceResolutionError as error:
        raise HTTPException(404 if error.code == "missing_reference" else 422, detail=error.as_issue()) from error
    except (CommandContractError, ValueError) as error:
        raise HTTPException(422, detail=error.as_issue() if isinstance(error, CommandContractError) else str(error)) from error
