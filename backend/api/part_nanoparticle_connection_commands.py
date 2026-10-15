"""Pending NP candidate metadata, with exact native owner/reference inputs.

No applied topology, placement or relaxation is accepted here. Unrelated owners
are retained verbatim; in particular deletion performs no global binding sync.
"""

from time import time
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator

from backend.api.part_thiol_commands import MAX_HANDLES, resolve_owned_handles, typed_ownership_supported
from backend.core.models import NanoparticleConnectionVersion
from backend.core.nanoparticle_connections import connection_attaches, next_version_name, polarity_error
from backend.core.part_command_errors import CommandContractError, ReferenceResolutionError
from backend.core.part_operation_input import MAX_OPERATION_BYTES, MAX_OPERATION_NODES
from backend.core.part_scope_references import COLLECTIONS, SCHEMAS, identity_index


KINDS = frozenset({"nanoparticle-connection-version-create", "nanoparticle-connection-version-patch",
                   "nanoparticle-connection-version-delete"})
_Id = Annotated[str, Field(strict=True, min_length=1, max_length=256)]
_Name = Annotated[str, Field(strict=True, min_length=1, max_length=256)]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    proof_version: Annotated[StrictInt, Field(ge=1, le=1)] = Field(alias="_proof_version")
    nanoparticle_connection_version: StrictInt = Field(ge=1, le=1)
    nanoparticle_id: _Id
    conjugation_id: _Id
    strand_id: _Id
    overhang_id: _Id
    version_id: _Id

    @field_validator("name", check_fields=False)
    @classmethod
    def nonblank_name(cls, value):
        if not value.strip():
            raise ValueError("Candidate name must not be blank")
        return value


class CreateRequest(_Input):
    name: _Name
    created_at: Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]
    connection_type: Literal["direct"]
    direct_variant: Literal["end-to-root", "root-to-root"]
    applied: StrictBool

    @field_validator("applied")
    @classmethod
    def pending_only(cls, value):
        if value:
            raise ValueError("Native candidate creation requires applied=false")
        return value


class PatchRequest(_Input):
    name: _Name


class DeleteRequest(_Input):
    pass


def parse_command(kind, params):
    model = {"nanoparticle-connection-version-create": CreateRequest,
             "nanoparticle-connection-version-patch": PatchRequest,
             "nanoparticle-connection-version-delete": DeleteRequest}.get(kind)
    if model is None:
        raise ValueError("Unsupported pending nanoparticle connection command")
    return model.model_validate(params)


def _fail(detail, kind, identity, parameter, *, missing=False):
    raise ReferenceResolutionError(detail, code="missing_reference" if missing else "invalid_selection",
        references=[{"kind": kind, "identity": identity, "parameter_path": [parameter]}])


def _resolve(index, kind, identity, parameter):
    value = index.get((kind, identity))
    if value is None:
        _fail("Selected nanoparticle connection resource is missing", kind, identity, parameter, missing=True)
    return value


def _pending(version):
    return (not version.applied and not version.relaxed and version.duplex_id is None
            and version.residual_nm is None and version.constraint_root_nm is None
            and version.constraint_radius_nm is None)


def _source_free(particle):
    return (particle.kind == "gold_nanosphere" and particle.quantum_dot is None
            and particle.coating is None and not particle.biotin_dna)


def _record_count_bounded(design):
    # Collection lengths are constant-time; do this before searching any
    # candidate/particle or constructing an ownership selection list.
    return sum(len(getattr(design, field)) for field in COLLECTIONS) <= MAX_OPERATION_NODES


def _bounded(design):
    # Count only the shared reference descriptors, including nested owners and
    # saved codecs, before those codecs parse/index anything. Plain atom arrays,
    # coordinates and user text are not reference work. Do not deduplicate aliases:
    # the typed resolver visits each occurrence too. This is a conservative work
    # allowance, not authoring capture, semantic validation or a time guarantee.
    pending = [(getattr(design, field), 0) for field in COLLECTIONS]
    nodes, size = 0, 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        size += 16
        if nodes > MAX_OPERATION_NODES or depth > 64 or size > MAX_OPERATION_BYTES:
            return False
        schema = SCHEMAS.get(type(item))
        if schema is not None:
            fields = schema.refs.keys() | schema.children | schema.special
            if schema.identity:
                fields = fields | {"id"}
            children = [getattr(item, field) for field in fields]
        elif type(item) in {list, tuple}:
            children = item
        elif type(item) is dict:
            if nodes + len(pending) + 2 * len(item) > MAX_OPERATION_NODES:
                return False
            children = [*item.keys(), *item.values()]
        elif type(item) is str:
            size += 4 * len(item)
            if size > MAX_OPERATION_BYTES:
                return False
            continue
        else:
            continue  # Scalar syntax/unsupported models remain resolver-owned.
        if nodes + len(pending) + len(children) > MAX_OPERATION_NODES:
            return False
        pending.extend((child, depth + 1) for child in children)
    return True


def build(kind, design, params):
    body = parse_command(kind, params)
    if not _bounded(design):
        raise CommandContractError("Pending connection source exceeds its reference allowance",
                                   code="unsupported_np_connection_source")
    if not typed_ownership_supported(design):
        raise CommandContractError("Pending connection source has unsupported reference ownership",
                                   code="unsupported_np_connection_source")
    index, _ = identity_index(design)
    version = None
    if kind != "nanoparticle-connection-version-create":
        version = _resolve(index, "nanoparticle_connection_version", body.version_id, "version_id")
        if not _pending(version):
            _fail("Native pending command cannot change applied or retained connection state",
                  "nanoparticle_connection_version", version.id, "version_id")
        for parameter, resource in (("nanoparticle_id", "nanoparticle"), ("strand_id", "strand"),
                                    ("overhang_id", "overhang")):
            if getattr(version, parameter) != getattr(body, parameter):
                _fail("Pending version no longer has the selected owner or endpoint", resource,
                      getattr(body, parameter), parameter)
    elif ("nanoparticle_connection_version", body.version_id) in index:
        _fail("Connection output identity already exists", "nanoparticle_connection_version", body.version_id, "version_id")
    particle = _resolve(index, "nanoparticle", body.nanoparticle_id, "nanoparticle_id")
    owner = _resolve(index, "nanoparticle_conjugation", body.conjugation_id, "conjugation_id")
    strand = _resolve(index, "strand", body.strand_id, "strand_id")
    target = _resolve(index, "overhang", body.overhang_id, "overhang_id")
    if not _source_free(particle):
        _fail("Pending native connections require source-free uncoated gold", "nanoparticle", particle.id, "nanoparticle_id")
    if owner.nanoparticle_id != particle.id:
        _fail("Selected conjugation belongs to a different particle", "nanoparticle_conjugation", owner.id, "conjugation_id")
    if not any(item.strand_id == strand.id for item in owner.surface_strands):
        _fail("Selected strand is not owned by the selected conjugation", "strand", strand.id, "strand_id")
    # Resolve complete radial ownership, without its separate destructive
    # incoming-consumer guard: adding metadata does not remove those handles.
    try:
        resolve_owned_handles(design, particle.id, [owner.id], index, parameter="conjugation_id")
    except ReferenceResolutionError as error:
        # The shared removal/motion resolver accepts a list selector; this
        # contract deliberately selects one owner with a scalar identity.
        raise ReferenceResolutionError(str(error), code=error.code, references=[
            {**reference, "parameter_path": ["conjugation_id"]}
            for reference in error.references]) from error
    if target.auxiliary_endpoint or target.strand_id == strand.id:
        _fail("Target must be an ordinary non-nanoparticle overhang", "overhang", target.id, "overhang_id")
    backing = [(item, domain) for item in design.strands for domain in item.domains if domain.overhang_id == target.id]
    if (len(backing) != 1 or backing[0][0].id != target.strand_id
            or backing[0][1].helix_id != target.helix_id or ("helix", target.helix_id) not in index):
        _fail("Target overhang must have one consistent live backing domain", "overhang", target.id, "overhang_id")
    variant = body.direct_variant if version is None else version.direct_variant
    error = polarity_error(design, owner, target.id, variant)
    if error:
        detail, parameter = error
        _fail(detail, "overhang", target.id, parameter)
    attaches = connection_attaches(owner, variant)
    if version is not None and (version.nanoparticle_attach, version.target_attach) != attaches:
        _fail("Pending version endpoint mapping disagrees with its owner", "nanoparticle_connection_version", version.id, "version_id")
    if version is None:
        version = NanoparticleConnectionVersion(id=body.version_id, name=body.name, created_at=body.created_at,
            nanoparticle_id=particle.id, strand_id=strand.id, overhang_id=target.id,
            connection_type=body.connection_type, direct_variant=variant,
            nanoparticle_attach=attaches[0], target_attach=attaches[1])
        versions = [*design.nanoparticle_connection_versions, version]
    elif kind == "nanoparticle-connection-version-patch":
        versions = [item.model_copy(update={"name": body.name}) if item.id == version.id else item
                    for item in design.nanoparticle_connection_versions]
    else:
        versions = [item for item in design.nanoparticle_connection_versions if item.id != version.id]
    return design.copy_with(nanoparticle_connection_versions=versions)


def _route_eligible(design, particle_id, version, choices):
    if not _record_count_bounded(design):
        return False
    particle = next((item for item in design.nanoparticles if item.id == particle_id), None)
    if particle is not None and not _source_free(particle):
        return False
    if choices.get("applied") is not None and (version is not None or choices["applied"]):
        return False
    if version is not None and not _pending(version):
        return False
    if version is not None and (version.nanoparticle_attach is None or version.target_attach is None):
        return False  # Old unspecified endpoint metadata remains a legacy receipt.
    owners = [item for item in design.nanoparticle_conjugations if item.nanoparticle_id == particle_id]
    if (len(owners) > 1 or not _bounded(design)
            or sum(len(item.surface_strands) for item in owners) > MAX_HANDLES
            or any(record.bound_overhang_id is not None for item in owners for record in item.surface_strands)
            or len((choices.get("name") or "").strip()) > 256):
        return False
    return typed_ownership_supported(design)


def try_record(kind, particle_id, choices, *, version_id=None, expected_revision=None):
    """One lock-owned eligibility/selection/recording transaction, or legacy scope.

    No privately prepared command survives a lock release. Only unsupported
    scope returns None; selected native reference/build failures never fall back.
    """
    from backend.api import state
    from backend.api.feature_recording import record_feature

    try:
        with state._lock:
            state._require_compatibility_write("pending_np_connection")
            session = state._session()
            source = session.design
            if source is None:
                raise HTTPException(404, detail="No active design.")
            if expected_revision is not None and session.revision != expected_revision:
                raise HTTPException(409, detail="Design changed before pending connection creation.")
            if not _record_count_bounded(source):
                return None
            version = next((item for item in source.nanoparticle_connection_versions if item.id == version_id), None)
            if not _route_eligible(source, particle_id, version, choices):
                return None
            state._assert_active_loadout_editable(source)
            if not any(item.id == particle_id for item in source.nanoparticles):
                _fail("Selected nanoparticle is missing", "nanoparticle", particle_id, "nanoparticle_id", missing=True)
            if kind != "nanoparticle-connection-version-create" and version is None:
                _fail("Selected connection version is missing", "nanoparticle_connection_version", version_id, "version_id", missing=True)
            strand_id = choices["strand_id"] if version is None else version.strand_id
            overhang_id = choices["overhang_id"] if version is None else version.overhang_id
            owners = [item for item in source.nanoparticle_conjugations if item.nanoparticle_id == particle_id
                      and any(record.strand_id == strand_id for record in item.surface_strands)]
            if len(owners) != 1:
                _fail("Nanoparticle handle ownership is missing or ambiguous", "strand", strand_id, "strand_id", missing=not owners)
            values = {"_proof_version": 1, "nanoparticle_connection_version": 1,
                "nanoparticle_id": particle_id, "conjugation_id": owners[0].id,
                "strand_id": strand_id, "overhang_id": overhang_id,
                "version_id": version_id or str(uuid4())}
            if kind == "nanoparticle-connection-version-create":
                values.update(name=(choices.get("name") or "").strip() or next_version_name(source, particle_id, strand_id, overhang_id),
                    created_at=time(), connection_type=choices.get("connection_type", "direct"),
                    direct_variant=choices.get("direct_variant", "end-to-root"), applied=False)
            elif kind == "nanoparticle-connection-version-patch":
                values["name"] = (choices.get("name") or "").strip() or version.name
            label = {"nanoparticle-connection-version-create": "Create", "nanoparticle-connection-version-patch": "Rename",
                     "nanoparticle-connection-version-delete": "Delete"}[kind] + " nanoparticle connection"

            def native(design):
                if session.design is not source or design is not source:
                    raise HTTPException(409, detail="Pending connection source changed before recording.")
                # The recorder appends its row in place. Keep that append off
                # the source's list while retaining unchanged authoring models.
                return build(kind, design, values).copy_with(feature_log=list(design.feature_log))

            return record_feature(session, kind, label, values, native)
    except ReferenceResolutionError as error:
        raise HTTPException(404 if error.code == "missing_reference" else 422, detail=error.as_issue()) from error
    except (CommandContractError, ValueError) as error:
        raise HTTPException(422, detail=error.as_issue() if isinstance(error, CommandContractError) else str(error)) from error
