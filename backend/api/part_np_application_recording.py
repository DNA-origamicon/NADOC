"""Record bounded nanoparticle application inside the existing document lock.

Structural classification may retain compatibility dispatch. After selection,
output binding and all native work either publish once or fail in the existing
recorder; they never switch to a second implementation.
"""

from time import time
from uuid import uuid4

from fastapi import HTTPException

from backend.api import part_nanoparticle_connection_commands as pending
from backend.api import part_np_application_commands as application
from backend.core.nanoparticle_connections import next_version_name
from backend.core.part_command_errors import CommandContractError


def try_record_locked(kind, particle_id, choices, *, session, source, version_id=None, version=None):
    """Called only by the lock-owning ordinary connection dispatcher."""
    from backend.api import state
    from backend.api.feature_recording import record_feature

    creating = kind == "nanoparticle-connection-version-create"
    deleting = kind == "nanoparticle-connection-version-delete"
    action = ("create" if creating else "delete" if deleting else
              "rename" if choices.get("applied") is None else
              "apply" if choices["applied"] else "unapply")
    applying = action in {"create", "apply"}
    try:
        if len(source.nanoparticle_connection_versions) > application.MAX_VERSIONS:
            application._unsupported("Native nanoparticle application exceeds its version allowance")
        prepared = application._prepare_source(source)
        if not creating:
            selected = pending._resolve(prepared.index, "nanoparticle_connection_version", version_id, "version_id")
            if selected is not version:
                raise CommandContractError("Application version changed before selection", code="source_changed")
            if version.nanoparticle_id != particle_id:
                pending._fail("Application version belongs to another particle", "nanoparticle", particle_id,
                              "nanoparticle_id")
        pending._resolve(prepared.index, "nanoparticle", particle_id, "nanoparticle_id")
        strand_id = choices["strand_id"] if creating else version.strand_id
        overhang_id = choices["overhang_id"] if creating else version.overhang_id
        owners = [item for item in source.nanoparticle_conjugations if item.nanoparticle_id == particle_id
                  and any(record.strand_id == strand_id for record in item.surface_strands)]
        if len(owners) != 1:
            pending._fail("Nanoparticle handle ownership is missing or ambiguous", "strand", strand_id,
                          "strand_id", missing=not owners)
        owner = owners[0]
        handles = [item for item in owner.surface_strands if item.strand_id == strand_id]
        if len(handles) != 1:
            pending._fail("Nanoparticle handle ownership is ambiguous", "strand", strand_id, "strand_id")
        name = None
        if not deleting:
            name = ((choices.get("name") or "").strip() or
                    (next_version_name(source, particle_id, strand_id, overhang_id) if creating else version.name))
            if len(name) > 256:
                application._unsupported("Native nanoparticle application exceeds its name allowance")
        inputs = application._SelectionInputs(action=action, nanoparticle_id=particle_id,
            conjugation_id=owner.id, strand_id=strand_id, overhang_id=overhang_id,
            handle_overhang_id=handles[0].overhang_id, version_id=None if creating else version.id,
            prior_duplex_id=None if creating else version.duplex_id,
            conflict_version_ids=tuple(item.id for item in source.nanoparticle_connection_versions
                if item.id != version_id and (item.strand_id == strand_id or item.overhang_id == overhang_id)),
            direct_variant=choices.get("direct_variant", "end-to-root") if creating else None)
        selection = application._select_inputs(source, inputs, prepared)
    except CommandContractError as error:
        if error.code in {"unsupported_np_application_source", "unsupported_np_connection_source"}:
            return None
        raise

    # Structural fallback ends here. Defaults are allocated only for an admitted
    # selection, and the final command owns every generated identity and time.
    values = {"_proof_version": 1, "nanoparticle_connection_version": 1,
        "nanoparticle_application_version": 1, "history_seed": str(uuid4()),
        "nanoparticle_id": particle_id, "conjugation_id": inputs.conjugation_id,
        "strand_id": strand_id, "overhang_id": overhang_id,
        "handle_overhang_id": inputs.handle_overhang_id,
        "version_id": str(uuid4()) if creating else version.id,
        "prior_duplex_id": inputs.prior_duplex_id,
        "conflict_version_ids": list(inputs.conflict_version_ids)}
    if creating:
        values.update(name=name, created_at=time(), connection_type=choices.get("connection_type", "direct"),
                      direct_variant=inputs.direct_variant, applied=True)
    elif not deleting:
        values["name"] = name
        if action != "rename":
            values["applied"] = applying
    if applying:
        values.update(duplex_id=str(uuid4()), duplex_created_at=time())
    body = application.parse_command(kind, values)
    bound = application._bind_command(kind, source, body, selection)

    def native(design):
        if state._session() is not session or session.design is not source or design is not source:
            raise HTTPException(409, detail="Nanoparticle application source changed before recording.")
        result = application._materialize(design, bound)
        return result.copy_with(feature_log=list(design.feature_log))

    return record_feature(session, kind, f"{action.capitalize()} nanoparticle connection", values, native)
