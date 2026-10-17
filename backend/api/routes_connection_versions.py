"""CRUD and atomic materialization routes for connection versions."""

from typing import Optional

from fastapi import APIRouter, HTTPException

from backend.api import state as design_state
from backend.api.connection_version_direct import (
    create_bound_binding,
    materialize_direct,
)
from backend.api.crud import (
    _design_response,
    _design_response_with_geometry,
)
from backend.api.overhang_patch import OverhangPatchRequest, _build_overhang_patch
from backend.api.schemas_connection_versions import (
    ConnectionVersionCreateRequest,
    ConnectionVersionPatchRequest,
)
from backend.core.connection_versions import (
    assign_default_names,
    clean_sequence,
    enforce_applied_mutex,
)
from backend.core.models import (
    ConnectionVersion,
    Design,
    OverhangConnection,
)
from backend.core.overhang_ops import _ovhg_backing_length
from backend.core.render_diff import _local_changed_helices, _strand_occupancy

# Compatibility for existing headless Python callers.
_cv_create_bound_binding = create_bound_binding

router = APIRouter()

# Internal rollout only; whole-request latency must be qualified before enabling.
OWNED_FINITE_CONNECTION_APPLY_ENABLED = False
OWNED_COMBINED_CONNECTION_APPLY_ENABLED = False
NATIVE_LINKER_V2_ENABLED = False
NATIVE_LINKER_V3_ENABLED = False
NATIVE_CONNECTION_OWNER_SELECTION_ENABLED = False
NATIVE_DIRECT_APPLY_ENABLED = False
NATIVE_DIRECT_CONNECT_ENABLED = False


@router.post("/design/connection-versions", status_code=201)
def create_connection_version(body: ConnectionVersionCreateRequest) -> dict:
    from backend.api.part_connection_organized_routes import try_response
    if (response := try_response('create', body.model_dump())) is not None:
        return response
    from backend.api.part_connection_version_commands import CREATE, try_record
    recorded = try_record(CREATE, body.model_dump())
    if recorded is not None:
        updated, report, _entry = recorded
        return _design_response(updated, report)
    design = design_state.get_or_404()
    overhang_ids = {overhang.id for overhang in design.overhangs}
    for overhang_id in (body.overhang_a_id, body.overhang_b_id):
        if overhang_id not in overhang_ids:
            raise HTTPException(404, detail=f"Overhang {overhang_id!r} not found.")
    if body.overhang_a_id == body.overhang_b_id:
        raise HTTPException(
            400, detail="A connection version needs two distinct overhangs."
        )
    version = ConnectionVersion(
        name=(body.name or "").strip(),
        overhang_a_id=body.overhang_a_id,
        overhang_b_id=body.overhang_b_id,
        connection_type=body.connection_type,
        overhang_a_seq=clean_sequence(body.overhang_a_seq),
        overhang_b_seq=clean_sequence(body.overhang_b_seq),
        bridge_length=max(0, int(body.bridge_length or 0)),
        bridge_seq=clean_sequence(body.bridge_seq),
        applied=bool(body.applied),
    )

    def mutate(candidate: Design) -> None:
        candidate.connection_versions = [*candidate.connection_versions, version]
        enforce_applied_mutex(candidate, version.id)
        assign_default_names(candidate)

    updated, report = design_state.mutate_and_validate(mutate)
    return _design_response(updated, report)


@router.patch("/design/connection-versions/{version_id}", status_code=200)
def patch_connection_version(
    version_id: str, body: ConnectionVersionPatchRequest
) -> dict:
    from backend.api.part_connection_organized_routes import try_response
    if (response := try_response('patch', body.model_dump(exclude_unset=True), version_id=version_id)) is not None:
        return response
    from backend.api.part_connection_version_commands import PATCH, try_record
    recorded = try_record(PATCH, body.model_dump(exclude_unset=True), version_id=version_id)
    if recorded is not None:
        updated, report, _entry = recorded
        return _design_response(updated, report)
    design = design_state.get_or_404()
    if not any(version.id == version_id for version in design.connection_versions):
        raise HTTPException(404, detail=f"Connection version {version_id!r} not found.")
    patch = body.model_dump(exclude_unset=True)

    def mutate(candidate: Design) -> None:
        version = next(
            (item for item in candidate.connection_versions if item.id == version_id),
            None,
        )
        if version is None:
            return
        if "name" in patch and (patch["name"] or "").strip():
            version.name = patch["name"].strip()
        if "connection_type" in patch and patch["connection_type"]:
            version.connection_type = patch["connection_type"]
        if "overhang_a_seq" in patch:
            version.overhang_a_seq = clean_sequence(patch["overhang_a_seq"])
        if "overhang_b_seq" in patch:
            version.overhang_b_seq = clean_sequence(patch["overhang_b_seq"])
        if "bridge_length" in patch and patch["bridge_length"] is not None:
            version.bridge_length = max(0, int(patch["bridge_length"]))
        if "bridge_seq" in patch:
            version.bridge_seq = clean_sequence(patch["bridge_seq"])
        if "applied" in patch and patch["applied"] is not None:
            version.applied = bool(patch["applied"])
            if version.applied:
                enforce_applied_mutex(candidate, version.id)

    updated, report = design_state.mutate_and_validate(mutate)
    return _design_response(updated, report)


@router.delete("/design/connection-versions/{version_id}", status_code=200)
def delete_connection_version(version_id: str) -> dict:
    from backend.api.part_connection_organized_routes import try_response
    if (response := try_response('delete', version_id=version_id)) is not None:
        return response
    from backend.api.part_connection_version_commands import DELETE, try_record
    recorded = try_record(DELETE, {}, version_id=version_id)
    if recorded is not None:
        updated, report, _entry = recorded
        return _design_response(updated, report)
    design = design_state.get_or_404()
    if not any(version.id == version_id for version in design.connection_versions):
        raise HTTPException(404, detail=f"Connection version {version_id!r} not found.")

    def mutate(candidate: Design) -> None:
        candidate.connection_versions = [
            version
            for version in candidate.connection_versions
            if version.id != version_id
        ]

    updated, report = design_state.mutate_and_validate(mutate)
    return _design_response(updated, report)


def _cv_sequence_for_live_overhang(
    d: Design, overhang_id: str, seq: Optional[str]
) -> Optional[str]:
    """Return *seq* adjusted to the overhang's current backing-domain length.

    Connection versions remember sequence content, but the live overhang geometry
    can change later via free-end resize. Applying a stale version must not use
    an old sequence length to resize the user's current geometry back.
    """
    cleaned = clean_sequence(seq)
    if cleaned is None:
        return None
    live_len = _ovhg_backing_length(d, overhang_id)
    if live_len is None:
        ov = next((o for o in d.overhangs if o.id == overhang_id), None)
        live_len = sum(sd.length_bp for sd in (ov.sub_domains or [])) if ov else None
    if live_len is None or live_len <= 0:
        return cleaned
    if len(cleaned) == live_len:
        return cleaned
    if len(cleaned) > live_len:
        return cleaned[:live_len]
    return cleaned + ("N" * (live_len - len(cleaned)))


# ── Connection-version mapping helpers (mirror frontend ct_icons.js) ───────────


def _cv_attach_pair(t: str):
    if isinstance(t, str):
        if t.startswith("end-to-root"):
            return ("free_end", "root")
        if t.startswith("root-to-end"):
            return ("root", "free_end")
        if t.startswith("root-to-root"):
            return ("root", "root")
        if t.startswith("end-to-end"):
            return ("free_end", "free_end")
    return ("root", "root")


def _cv_is_direct(t: str) -> bool:
    return t in ("end-to-root", "root-to-root")


def _cv_is_indirect(t: str) -> bool:
    return t in ("root-to-root-indirect", "end-to-end-indirect")


def _cv_linker_type(t: str) -> str:
    return "ds" if (isinstance(t, str) and "dsdna" in t) else "ss"


def _apply_connection_version_impl(
    version_id: str, *, new_version: ConnectionVersion | None = None
) -> dict:
    if (NATIVE_DIRECT_APPLY_ENABLED or NATIVE_CONNECTION_OWNER_SELECTION_ENABLED) and new_version is None:
        from backend.api.part_connection_direct_recording import try_record as try_direct
        recorded = try_direct(version_id, owner_selection=NATIVE_CONNECTION_OWNER_SELECTION_ENABLED)
        if recorded is not None:
            source, updated, report, _entry = recorded
            return _connection_apply_response(source, updated, report)
    if (OWNED_FINITE_CONNECTION_APPLY_ENABLED or NATIVE_LINKER_V2_ENABLED or NATIVE_LINKER_V3_ENABLED or NATIVE_CONNECTION_OWNER_SELECTION_ENABLED) and new_version is None:
        from backend.api.part_connection_application_commands import try_record
        recorded = try_record(version_id, contract_version=4 if NATIVE_CONNECTION_OWNER_SELECTION_ENABLED else 3 if NATIVE_LINKER_V3_ENABLED else 2 if NATIVE_LINKER_V2_ENABLED else 1)
        if recorded is not None:
            source, updated, report, _entry = recorded
            return _connection_apply_response(source, updated, report)
    return _apply_connection_version_legacy(version_id, new_version=new_version)


def _apply_connection_version_legacy(
    version_id: str, *, new_version: ConnectionVersion | None = None
) -> dict:
    """Materialize a candidate version ATOMICALLY (one undo): set both overhang
    sequences (resizing each overhang to the sequence length), tear down the
    pair's current OverhangConnection / OverhangBinding, and (re)create the
    version's connection type (linker with bridge, or a direct binding). Marks
    the version ``applied`` and clears ``applied`` on the pair's other versions.

    This is the backend replacement for the v1 frontend-orchestrated apply — it
    handles overhang LENGTH + sequence + connection-type changes in one step.
    """
    from backend.api.connection_version_teardown import remove_conflicts
    from backend.core.cluster_reconcile import MutationReport
    from backend.core.lattice import (
        generate_linker_topology,
        assign_overhang_connection_names,
    )

    design = design_state.get_or_404()
    v = new_version or next(
        (x for x in design.connection_versions if x.id == version_id), None
    )
    if v is None:
        raise HTTPException(404, detail=f"Connection version {version_id!r} not found.")
    a_id, b_id, vtype = v.overhang_a_id, v.overhang_b_id, v.connection_type
    direct = _cv_is_direct(vtype)
    indirect = _cv_is_indirect(vtype)
    attach_a, attach_b = _cv_attach_pair(vtype)
    bridge_seq = (v.bridge_seq or "").upper().strip() or None
    a_label = next((o.label for o in design.overhangs if o.id == a_id), a_id[:8])
    b_label = next((o.label for o in design.overhangs if o.id == b_id), b_id[:8])

    def _fn(d: Design):
        from backend.api.part_source_bound_route import require_current
        require_current()  # A staged HTTP fallback retains its captured source.
        # First-time Connect supplies a not-yet-persisted version so candidate
        # creation and materialization share ONE undo snapshot. Add it only
        # inside the logged mutation; Undo then restores the truly pre-Connect
        # design instead of leaving a draft version/sidebar group behind.
        if new_version is not None:
            # Pydantic applies update values after deep-copying the model.
            # Detach these records explicitly before default naming mutates them;
            # a held source must remain unchanged even if publication fails.
            d = d.model_copy(
                update={"connection_versions": [
                    *(v.model_copy() for v in d.connection_versions), new_version.model_copy()
                ]},
                deep=True,
            )
            assign_default_names(d)
        # Restore the prior connection before editing sequences: a driven domain
        # may still share the driver's host until its relocation is reverted.
        d = remove_conflicts(d, (a_id, b_id))
        # 1. Sequences: patch each overhang, but preserve the live geometry
        #    length. A version can be created, then the user can drag-resize one
        #    of its overhangs before applying; the captured sequence length must
        #    not snap the overhang back to its old size.
        applied_a_seq = _cv_sequence_for_live_overhang(d, a_id, v.overhang_a_seq)
        applied_b_seq = _cv_sequence_for_live_overhang(d, b_id, v.overhang_b_seq)
        if applied_a_seq:
            d = _build_overhang_patch(
                d, a_id, OverhangPatchRequest(sequence=applied_a_seq)
            )[0]
        if applied_b_seq:
            d = _build_overhang_patch(
                d, b_id, OverhangPatchRequest(sequence=applied_b_seq)
            )[0]

        def _involves(x):
            return bool({a_id, b_id}.intersection((x.overhang_a_id, x.overhang_b_id)))

        # 3. Create the version's connection type.
        report = None
        bridge_helix_ids: list[str] = []
        if direct:
            d = materialize_direct(d, a_id, b_id, attach_a, attach_b, vtype)
        else:
            conn = OverhangConnection(
                overhang_a_id=a_id,
                overhang_a_attach=attach_a,
                overhang_b_id=b_id,
                overhang_b_attach=attach_b,
                linker_type=_cv_linker_type(vtype),
                length_value=0 if indirect else max(1, int(v.bridge_length or 1)),
                length_unit="bp",
                bridge_sequence=bridge_seq,
            )
            d = assign_overhang_connection_names(
                d.model_copy(
                    update={"overhang_connections": [*d.overhang_connections, conn]}
                )
            )
            d = generate_linker_topology(d, conn)
            bridge_helix_ids.append(f"__lnk__{conn.id}")
            report = MutationReport(new_helix_origins={f"__lnk__{conn.id}": None})
        # 3b. Auto-assign so the materialized connection's complement / binder
        #     domains (binds_overhang_id) carry real reverse-complement bases for
        #     simulation — no-op until the scaffold is sequenced. Targeted to the
        #     pair's own strands, their binders and any new __lnk__ bridge helix,
        #     so hand-typed sequences elsewhere in the design are left alone.
        from backend.core.sequences import (
            overhang_dependent_strand_ids,
            reassign_strands,
        )

        affected = overhang_dependent_strand_ids(
            d, [a_id, b_id], extra_helix_ids=bridge_helix_ids
        )
        d = reassign_strands(d, affected)
        # 4. Mark this version applied; clear `applied` on every version that
        #    shares either overhang (mirrors the topology teardown in step 2).
        d = d.model_copy(
            update={
                "connection_versions": [
                    ver.model_copy(
                        update={
                            "applied": ver.id == version_id,
                            **(
                                {"overhang_a_seq": applied_a_seq}
                                if ver.id == version_id and applied_a_seq
                                else {}
                            ),
                            **(
                                {"overhang_b_seq": applied_b_seq}
                                if ver.id == version_id and applied_b_seq
                                else {}
                            ),
                        }
                    )
                    if (ver.id == version_id or _involves(ver))
                    else ver
                    for ver in d.connection_versions
                ]
            }
        )
        return (d, report) if report else d

    updated, report, _entry = design_state.mutate_with_feature_log(
        op_kind="overhang-bulk",
        label=f"Apply version {v.name or v.id[:8]} ({a_label}↔{b_label})",
        params={"version_id": version_id, "connection_type": vtype},
        fn=_fn,
    )
    return _connection_apply_response(design, updated, report)


def _connection_apply_response(design, updated, report):
    # Preserve the existing occupancy-based response selection. Connection-list
    # changes (including finite Apply) currently require full geometry; other
    # local cases may use the established partial merge protocol.
    changed = _local_changed_helices(
        _strand_occupancy(design), _strand_occupancy(updated)
    )
    if changed is not None:
        return _design_response_with_geometry(
            updated,
            report,
            changed_helix_ids=changed,
            compact_deformed=True,
            partial_axes=True,
        )
    return _design_response_with_geometry(updated, report)


def apply_connection_version(version_id: str) -> dict:
    from backend.api.part_connection_organized_routes import try_response
    if (response := try_response('apply', version_id=version_id)) is not None:
        return response
    return _apply_connection_version_impl(version_id)


def create_and_apply_connection_version(body: ConnectionVersionCreateRequest) -> dict:
    """Create and materialize a first-time connection as one undoable action."""
    from backend.api.part_connection_organized_routes import try_response
    if (response := try_response('connect', body.model_dump())) is not None:
        return response
    if NATIVE_DIRECT_CONNECT_ENABLED or NATIVE_CONNECTION_OWNER_SELECTION_ENABLED:
        from backend.api.part_connection_direct_recording import try_record_connect
        recorded = try_record_connect(body.model_dump(), owner_selection=NATIVE_CONNECTION_OWNER_SELECTION_ENABLED)
        if recorded is not None:
            source, updated, report, _entry = recorded
            return _connection_apply_response(source, updated, report)
    if OWNED_COMBINED_CONNECTION_APPLY_ENABLED or NATIVE_LINKER_V2_ENABLED or NATIVE_LINKER_V3_ENABLED or NATIVE_CONNECTION_OWNER_SELECTION_ENABLED:
        from backend.api.part_connection_composition_commands import try_record
        recorded = try_record(body.model_dump(), contract_version=4 if NATIVE_CONNECTION_OWNER_SELECTION_ENABLED else 3 if NATIVE_LINKER_V3_ENABLED else 2 if NATIVE_LINKER_V2_ENABLED else 1)
        if recorded is not None:
            source, updated, report, _entry = recorded
            return _connection_apply_response(source, updated, report)
    design = design_state.get_or_404()
    ids = {o.id for o in design.overhangs}
    for oid in (body.overhang_a_id, body.overhang_b_id):
        if oid not in ids:
            raise HTTPException(404, detail=f"Overhang {oid!r} not found.")
    if body.overhang_a_id == body.overhang_b_id:
        raise HTTPException(400, detail="A connection needs two distinct overhangs.")
    version = ConnectionVersion(
        name=(body.name or "").strip(),
        overhang_a_id=body.overhang_a_id,
        overhang_b_id=body.overhang_b_id,
        connection_type=body.connection_type,
        overhang_a_seq=clean_sequence(body.overhang_a_seq),
        overhang_b_seq=clean_sequence(body.overhang_b_seq),
        bridge_length=max(0, int(body.bridge_length or 0)),
        bridge_seq=clean_sequence(body.bridge_seq),
        applied=True,
    )
    return _apply_connection_version_impl(version.id, new_version=version)


from backend.api.part_connection_composition_route import ConnectRoute, ApplyRoute

router.add_api_route("/design/connection-versions/connect", create_and_apply_connection_version,
                     methods=["POST"], status_code=201, route_class_override=ConnectRoute)

router.add_api_route("/design/connection-versions/{version_id}/apply", apply_connection_version,
                     methods=["POST"], status_code=200, route_class_override=ApplyRoute)


def unapply_connection_version(version_id: str) -> dict:
    from backend.api.part_connection_organized_routes import try_response
    if (response := try_response('unapply', version_id=version_id)) is not None:
        return response
    from backend.api.part_connection_disconnect import record
    source, updated, report, _ = record(version_id)
    return _connection_apply_response(source, updated, report)


def disconnect_and_delete_connection_version(version_id: str) -> dict:
    from backend.api.part_connection_organized_routes import try_response
    if (response := try_response('disconnect_delete', version_id=version_id)) is not None:
        return response
    from backend.api.part_connection_disconnect import record
    source, updated, report, _ = record(version_id, delete_version=True)
    return _connection_apply_response(source, updated, report)


from backend.api.part_connection_composition_route import DisconnectRoute

router.add_api_route('/design/connection-versions/{version_id}/unapply', unapply_connection_version,
                     methods=['POST'], route_class_override=DisconnectRoute)
router.add_api_route('/design/connection-versions/{version_id}/disconnect-and-delete', disconnect_and_delete_connection_version,
                     methods=['POST'], route_class_override=DisconnectRoute)
