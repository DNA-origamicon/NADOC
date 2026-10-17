"""Input-defined ordinary connection metadata; no materialization authority.

V1 retains pending-only semantics. V2 records applied metadata and exact sibling
flag changes, without rebuilding or disconnecting geometry. Ordinary v2 rollout
is private until the complete connection lifecycle is qualified.
"""

from dataclasses import dataclass
from math import isfinite
from time import time
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator

from backend.core.connection_versions import assign_default_names, clean_sequence, pair_key
from backend.core.models import ConnectionVersion
from backend.core.part_command_errors import CommandContractError, ReferenceResolutionError
from backend.core.part_operation_input import MAX_OPERATION_BYTES, MAX_OPERATION_NODES, validate_operation_input


APPLIED_METADATA_ENABLED = False

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


class MetadataSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    connection_version_contract: Annotated[StrictInt, Field(ge=2, le=2)]
    affected_version_ids: list[_Id] = Field(max_length=128)

    @field_validator("affected_version_ids")
    @classmethod
    def unique_affected(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("Affected version identities must be unique")
        return value


class CreateMetadataRequest(CreateRequest, MetadataSelection):
    connection_version_contract: Annotated[StrictInt, Field(ge=2, le=2)]

    @field_validator("applied")
    @classmethod
    def pending_only(cls, value):
        # This is a saved metadata flag, not materialization authority.
        return value


class MetadataPatch(Patch):
    applied: StrictBool | None = None


class PatchMetadataRequest(PatchRequest, MetadataSelection):
    connection_version_contract: Annotated[StrictInt, Field(ge=2, le=2)]
    patch: MetadataPatch


class DeleteMetadataRequest(DeleteRequest, MetadataSelection):
    connection_version_contract: Annotated[StrictInt, Field(ge=2, le=2)]


def affected_versions(design, values):
    """Exact ordered metadata footprint; call after bounded inventory admission."""
    action = values["action"]
    applied = values.get("applied") if action == CREATE else values.get("patch", {}).get("applied")
    pair = pair_key(values["overhang_a_id"], values["overhang_b_id"])
    return [v.id for v in design.connection_versions
            if (action != CREATE and v.id == values["version_id"])
            or (applied is True and pair_key(v.overhang_a_id, v.overhang_b_id) == pair)]


def parse_command(params):
    validate_operation_input(params)
    if not is_pending_action(params):
        raise ValueError("Unsupported pending connection action")
    marker = params.get("connection_version_contract")
    models = ({CREATE: CreateMetadataRequest, PATCH: PatchMetadataRequest, DELETE: DeleteMetadataRequest}
              if type(marker) is int and marker == 2 else
              {CREATE: CreateRequest, PATCH: PatchRequest, DELETE: DeleteRequest})
    model = models.get(params["action"])
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


@dataclass(frozen=True, slots=True)
class _Selection:
    source: object
    action: str
    endpoints: tuple[str, str]
    version: ConnectionVersion | None


@dataclass(frozen=True, slots=True)
class _Prepared:
    selection: _Selection
    body: CreateRequest | PatchRequest | DeleteRequest


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


def _select(design, body, inventory):
    """Resolve inputs before identity allocation or any whole-design work."""
    if inventory.source is not design:
        raise CommandContractError("Pending connection preparation belongs to another source", code="source_changed")
    version = None
    if body.action != CREATE:
        version = _resolve(inventory.versions, body.version_id, "connection_version", "version_id")
        if version.applied and body.connection_version_contract == 1:
            _fail("Native pending edits cannot alter an applied connection", "connection_version", version.id, "version_id")
        for field in ("overhang_a_id", "overhang_b_id"):
            if getattr(version, field) != getattr(body, field):
                _fail("Selected pending connection endpoint changed", "overhang", getattr(body, field), field)
    for field in ("overhang_a_id", "overhang_b_id"):
        selected = _resolve(inventory.overhangs, getattr(body, field), "overhang", field)
        if selected.auxiliary_endpoint:
            _fail("Pending ordinary connections require ordinary overhangs", "overhang", selected.id, field)
    if body.overhang_a_id == body.overhang_b_id:
        _fail("A pending connection needs two distinct overhangs", "overhang", body.overhang_b_id, "overhang_b_id")
    if body.connection_version_contract == 2:
        actual = affected_versions(design, body.model_dump(by_alias=True))
        if body.affected_version_ids != actual:
            _fail("Metadata mutation requires the exact ordered affected version set",
                  "connection_version", body.version_id, "affected_version_ids")
    return _Selection(design, body.action, (body.overhang_a_id, body.overhang_b_id), version)


def _bind(body, selection, inventory):
    """Bind a parsed definition to exact selected inputs, including output ID.

    Creation may allocate its ID/time after selecting valid endpoints. Everything
    here remains private to the same source/lock; this is not cached authority.
    """
    if (inventory.source is not selection.source or body.action != selection.action
            or (body.overhang_a_id, body.overhang_b_id) != selection.endpoints
            or (selection.version is not None and body.version_id != selection.version.id)):
        raise CommandContractError("Pending connection preparation belongs to another selection", code="source_changed")
    if body.action == CREATE and body.version_id in inventory.versions:
        _fail("Pending connection output identity already exists", "connection_version", body.version_id, "version_id")
    return _Prepared(selection, body)


def _build(design, prepared):
    if prepared.selection.source is not design:
        raise CommandContractError("Pending connection preparation belongs to another source", code="source_changed")
    body, version = prepared.body, prepared.selection.version

    if body.action == CREATE:
        version = ConnectionVersion(id=body.version_id, name=body.name.strip(), created_at=body.created_at,
            overhang_a_id=body.overhang_a_id, overhang_b_id=body.overhang_b_id,
            connection_type=body.connection_type, overhang_a_seq=clean_sequence(body.overhang_a_seq),
            overhang_b_seq=clean_sequence(body.overhang_b_seq), bridge_length=body.bridge_length,
            bridge_seq=clean_sequence(body.bridge_seq), applied=body.applied)
        # The unchanged helper can name earlier blank legacy rows too. Copy those
        # mutable records first; existing applied/topology state remains untouched.
        result = design.copy_with(connection_versions=[*[v.model_copy() for v in design.connection_versions], version])
        assign_default_names(result)
        return _metadata_mutex(result, body, body.applied)
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
    if body.connection_version_contract == 2 and patch.get("applied") is not None:
        updates["applied"] = patch["applied"]
    result = design.copy_with(connection_versions=[v.model_copy(update=updates) if v.id == version.id else v
                                                   for v in design.connection_versions])
    return _metadata_mutex(result, body, patch.get("applied"))


def _metadata_mutex(design, body, applied):
    if body.connection_version_contract != 2 or applied is not True:
        return design
    affected = set(body.affected_version_ids) - {body.version_id}
    return design.copy_with(connection_versions=[v.model_copy(update={"applied": False})
        if v.id in affected else v for v in design.connection_versions])


def build(design, params):
    body, inventory = parse_command(params), _inventory(design)
    return _build(design, _bind(body, _select(design, body, inventory), inventory))


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
            if not APPLIED_METADATA_ENABLED and ((version is not None and version.applied) or choices.get("applied")):
                return None
            if not APPLIED_METADATA_ENABLED and action == PATCH and "applied" in choices:
                return None  # Preserve explicit compatibility flag changes.
            values = {"_proof_version": 1, "connection_version_contract": 2 if APPLIED_METADATA_ENABLED else 1, "action": action,
                "version_id": version_id or "pending", "overhang_a_id": choices.get("overhang_a_id") if version is None else version.overhang_a_id,
                "overhang_b_id": choices.get("overhang_b_id") if version is None else version.overhang_b_id}
            if action == CREATE:
                values.update(name=(choices.get("name") or "").strip(), created_at=0.0,
                    connection_type=choices.get("connection_type"), overhang_a_seq=choices.get("overhang_a_seq"),
                    overhang_b_seq=choices.get("overhang_b_seq"), bridge_seq=choices.get("bridge_seq"),
                    bridge_length=max(0, int(choices.get("bridge_length") or 0)), applied=bool(choices.get("applied")))
            elif action == PATCH:
                values["patch"] = dict(choices)
                if values["patch"].get("bridge_length") is not None:
                    values["patch"]["bridge_length"] = max(0, values["patch"]["bridge_length"])
            if APPLIED_METADATA_ENABLED:
                values["affected_version_ids"] = affected_versions(source, values)
                if source.feature_log_cursor != -1 or source.feature_log_sub_cursor is not None:
                    raise HTTPException(409, detail="Return to the latest feature before editing connection metadata.")
            try:
                body = parse_command(values)
            except ValueError:
                return None
            if any(inventory.overhangs.get(values[field]) is not None
                   and inventory.overhangs[values[field]].auxiliary_endpoint
                   for field in ("overhang_a_id", "overhang_b_id")):
                return None
            state._assert_active_loadout_editable(source)
            selected = _select(source, body, inventory)
            if action == CREATE:
                values.update(version_id=str(uuid4()), created_at=time())
                body = parse_command(values)
            prepared = _bind(body, selected, inventory)

            def native(design):
                if session.design is not source or design is not source:
                    raise HTTPException(409, detail="Pending connection source changed before recording.")
                return _build(design, prepared).copy_with(feature_log=list(design.feature_log))

            label = {CREATE: "Create", PATCH: "Edit", DELETE: "Delete"}[action] + (" connection metadata" if APPLIED_METADATA_ENABLED else " pending connection")
            return record_feature(session, "overhang-bulk", label, values, native)
    except ReferenceResolutionError as error:
        raise HTTPException(404 if error.code == "missing_reference" else 422, detail=error.as_issue()) from error
    except (CommandContractError, ValueError) as error:
        raise HTTPException(422, detail=error.as_issue() if isinstance(error, CommandContractError) else str(error)) from error
