"""Pending version metadata beside one exactly selected applied NP connection.

The existing native restoration validates radial ownership privately. Only the
selected version metadata is returned; live placement and ownership stay exact.
"""

from types import SimpleNamespace
from time import time
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel, Field, StrictInt

from backend.api import part_nanoparticle_connection_commands as pending
from backend.api import part_np_application_commands as application
from backend.core.nanoparticle_connections import ConnectionApplicationError
from backend.core.part_command_errors import CommandContractError, ReferenceResolutionError
from backend.core.part_scope_references import identity_index


class _Context(BaseModel):
    nanoparticle_pending_context_version: StrictInt = Field(ge=1, le=1)
    active_version_id: pending._Id
    active_duplex_id: pending._Id


class CreateRequest(_Context, pending.CreateRequest):
    pass


class PatchRequest(_Context, pending.PatchRequest):
    pass


class DeleteRequest(_Context, pending.DeleteRequest):
    pass


def parse_command(kind, params):
    model = {"nanoparticle-connection-version-create": CreateRequest,
             "nanoparticle-connection-version-patch": PatchRequest,
             "nanoparticle-connection-version-delete": DeleteRequest}.get(kind)
    if model is None:
        raise ValueError("Unsupported pending nanoparticle context command")
    return model.model_validate(params)


def _select(design, kind, inputs):
    """Bounded structural classification before restoration or output defaults."""
    prepared = application._prepare_source(design)
    index = prepared.index
    particle = pending._resolve(index, "nanoparticle", inputs.nanoparticle_id, "nanoparticle_id")
    strand = pending._resolve(index, "strand", inputs.strand_id, "strand_id")
    target = pending._resolve(index, "overhang", inputs.overhang_id, "overhang_id")
    owners = [owner for owner in design.nanoparticle_conjugations if owner.nanoparticle_id == particle.id]
    if len(owners) != 1:
        application._unsupported("Pending alternatives require one native conjugation owner")
    owner = owners[0]
    if len(owner.surface_strands) > application.MAX_APPLICATION_HANDLES:
        application._unsupported("Pending alternatives currently admit at most 16 handles")
    count = len(design.nanoparticle_connection_versions)
    if count > application.MAX_VERSIONS or (kind == "nanoparticle-connection-version-create" and count == application.MAX_VERSIONS):
        application._unsupported("Pending alternatives exceed the version allowance")
    if hasattr(inputs, "active_version_id"):
        expected = pending._resolve(index, "nanoparticle_connection_version", inputs.active_version_id, "active_version_id")
        if not expected.applied or expected.nanoparticle_id != particle.id:
            pending._fail("Selected context is no longer the particle's active connection",
                          "nanoparticle_connection_version", expected.id, "active_version_id")
    active = [version for version in design.nanoparticle_connection_versions
              if version.nanoparticle_id == particle.id and version.applied]
    if len(active) != 1:
        application._unsupported("Pending alternatives require exactly one active version")
    active = active[0]
    if getattr(inputs, "active_version_id", active.id) != active.id:
        pending._fail("Pending metadata must select the exact active connection",
            "nanoparticle_connection_version", inputs.active_version_id, "active_version_id",
            missing=("nanoparticle_connection_version", inputs.active_version_id) not in index)
    if getattr(inputs, "active_duplex_id", active.duplex_id) != active.duplex_id:
        pending._fail("Pending metadata must select the exact active duplex", "duplex",
                      inputs.active_duplex_id, "active_duplex_id",
                      missing=("duplex", inputs.active_duplex_id) not in index)
    if getattr(inputs, "conjugation_id", owner.id) != owner.id:
        pending._fail("Pending metadata selects a different conjugation owner",
                      "nanoparticle_conjugation", inputs.conjugation_id, "conjugation_id")
    selected = None
    if kind != "nanoparticle-connection-version-create":
        selected = pending._resolve(index, "nanoparticle_connection_version", inputs.version_id, "version_id")
        if not pending._pending(selected):
            pending._fail("Pending metadata cannot modify the active connection",
                          "nanoparticle_connection_version", selected.id, "version_id")
        for field, resource in (("nanoparticle_id", "nanoparticle"), ("strand_id", "strand"), ("overhang_id", "overhang")):
            if getattr(selected, field) != getattr(inputs, field):
                pending._fail("Pending metadata owner or endpoint changed", resource,
                              getattr(inputs, field), field)
    variant = inputs.direct_variant if selected is None else selected.direct_variant
    pending._validate_endpoint(index, owner, strand, target, variant,
        pending._target_backings(design, {target.id}).get(target.id, ()), version=selected)
    application._classify_legacy_shared_target(design, particle.id, target.id)
    try:
        application._restoration(design, index, owner, active)
    except ReferenceResolutionError as error:
        raise ReferenceResolutionError(str(error), code=error.code, references=[
            {**reference, "parameter_path": ["active_duplex_id"]}
            for reference in error.references]) from error
    return prepared, owner, active


def _build_selected(kind, design, body, selection):
    prepared, owner, active = selection
    if prepared.source is not design or (body.conjugation_id, body.active_version_id, body.active_duplex_id) != (
            owner.id, active.id, active.duplex_id):
        raise CommandContractError("Pending context changed before recording", code="source_changed")
    # This is the established exact restoration, without fitting or new poses.
    # Nothing from the private restored topology becomes a published field.
    try:
        radial = application.set_version_applied(design, active.id, False)
    except (HTTPException, ConnectionApplicationError) as error:
        pending._fail(str(error.detail), "duplex", body.active_duplex_id, "active_duplex_id")
    radial_prepared = pending._PreparedSource(radial, identity_index(radial)[0])
    values = body.model_dump(by_alias=True, exclude={
        "nanoparticle_pending_context_version", "active_version_id", "active_duplex_id"})
    plain = pending.parse_command(kind, values)
    changed = pending._build_prepared(kind, radial, plain, radial_prepared)
    if kind == "nanoparticle-connection-version-create":
        added = next(item for item in changed.nanoparticle_connection_versions if item.id == body.version_id)
        versions = [*design.nanoparticle_connection_versions, added]
    elif kind == "nanoparticle-connection-version-patch":
        updated = next(item for item in changed.nanoparticle_connection_versions if item.id == body.version_id)
        versions = [updated if item.id == body.version_id else item for item in design.nanoparticle_connection_versions]
    else:
        versions = [item for item in design.nanoparticle_connection_versions if item.id != body.version_id]
    return design.copy_with(nanoparticle_connection_versions=versions)


def build(kind, design, params):
    body = parse_command(kind, params)
    return _build_selected(kind, design, body, _select(design, kind, body))


def try_record_locked(kind, particle_id, choices, *, session, source, version_id=None, version=None):
    """Use the existing recorder and its sole lock; no second publication path."""
    from backend.api import state
    from backend.api.feature_recording import record_feature

    creating = kind == "nanoparticle-connection-version-create"
    if len((choices.get("name") or "").strip()) > 256:
        return None
    if not creating and version is None:
        pending._fail("Selected connection version is missing", "nanoparticle_connection_version",
                      version_id, "version_id", missing=True)
    strand_id = choices["strand_id"] if creating else version.strand_id
    overhang_id = choices["overhang_id"] if creating else version.overhang_id
    inputs = SimpleNamespace(nanoparticle_id=particle_id, strand_id=strand_id, overhang_id=overhang_id,
        version_id=version_id, direct_variant=choices.get("direct_variant", "end-to-root"))
    try:
        selection = _select(source, kind, inputs)
    except CommandContractError as error:
        if error.code in {"unsupported_np_application_source", "unsupported_np_connection_source"}:
            return None
        raise
    _, owner, active = selection
    values = {"_proof_version": 1, "nanoparticle_connection_version": 1,
        "nanoparticle_pending_context_version": 1, "nanoparticle_id": particle_id,
        "conjugation_id": owner.id, "strand_id": strand_id, "overhang_id": overhang_id,
        "version_id": str(uuid4()) if creating else version.id,
        "active_version_id": active.id, "active_duplex_id": active.duplex_id}
    if creating:
        values.update(name=(choices.get("name") or "").strip() or pending.next_version_name(
            source, particle_id, strand_id, overhang_id), created_at=time(),
            connection_type=choices.get("connection_type", "direct"), direct_variant=inputs.direct_variant, applied=False)
    elif kind == "nanoparticle-connection-version-patch":
        values["name"] = (choices.get("name") or "").strip() or version.name
    body = parse_command(kind, values)

    def native(design):
        if state._session() is not session or session.design is not source or design is not source:
            raise HTTPException(409, detail="Pending context source changed before recording.")
        return _build_selected(kind, design, body, selection).copy_with(feature_log=list(design.feature_log))

    label = {"nanoparticle-connection-version-create": "Create", "nanoparticle-connection-version-patch": "Rename",
             "nanoparticle-connection-version-delete": "Delete"}[kind]
    return record_feature(session, kind, f"{label} nanoparticle connection", values, native)
