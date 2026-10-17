"""Duplex authoring adapters and pairing readouts.

Native graph commands own validation and deterministic replay. Relaxation
migrates in the next lifecycle increment.
"""

from time import time
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import ValidationError

from backend.api import state as design_state
from backend.api.crud import _design_response
from backend.api.part_duplex_commands import (
    ConnectDuplexBody,
    CreateDuplexBody,
    DuplexEndBody,  # noqa: F401 — compatibility for existing Python callers
    DuplexReferenceError,
    PatchDuplexBody,
    build,
    find_duplex,
    prepare_command,
)
from backend.core.duplex import (
    classify_duplex_pairing,
    overhang_pairing_map,
)
from backend.core.models import Design, Duplex

router = APIRouter()


def _find(design: Design, duplex_id: str) -> Duplex:
    try:
        return find_duplex(design, duplex_id)
    except DuplexReferenceError as exc:
        raise HTTPException(exc.http_status, detail=exc.as_issue()) from exc


def _record(kind: str, label: str, values: dict) -> dict:
    params = {**values, "history_seed": str(uuid4()), "_proof_version": 1}
    if kind in {"duplex-create", "duplex-connect"}:
        params.update(duplex_id=str(uuid4()), created_at=time())

    def apply(design):
        # Selection and publication share the transaction's revision lock.
        params.update(prepare_command(kind, design, params))
        return build(kind, design, params)

    try:
        updated, report, entry = design_state.mutate_with_feature_log(kind, label, params, apply)
    except DuplexReferenceError as exc:
        raise HTTPException(exc.http_status, detail=exc.as_issue()) from exc
    except (ValidationError, ValueError) as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    response = _design_response(updated, report)
    if kind in {"duplex-create", "duplex-connect"}:
        response["duplex_id"] = entry.params["duplex_id"]
    return response


@router.get("/design/duplexes", status_code=200)
def list_duplexes() -> dict:
    design = design_state.get_or_404()
    return {"duplexes": [d.model_dump() for d in design.duplexes]}


@router.post("/design/duplexes", status_code=201)
def create_duplex(body: CreateDuplexBody) -> dict:
    return _record("duplex-create", "Create duplex", body.model_dump(mode="json", exclude_unset=True))


@router.post("/design/duplexes/connect", status_code=201)
def connect_duplex(body: ConnectDuplexBody) -> dict:
    return _record("duplex-connect", "Connect duplex", body.model_dump(mode="json", exclude_unset=True))


@router.post("/design/duplexes/sync-from-bindings", status_code=200)
def sync_from_bindings() -> dict:
    """Capture currently missing binding pairs as an explicit native feature."""
    return _record("duplex-sync-bindings", "Sync duplexes from bindings", {})


@router.patch("/design/duplexes/{duplex_id}", status_code=200)
def patch_duplex(duplex_id: str, body: PatchDuplexBody) -> dict:
    return _record("duplex-patch", "Edit duplex", {
        **body.model_dump(mode="json", exclude_unset=True), "duplex_id": duplex_id,
    })


@router.delete("/design/duplexes/{duplex_id}", status_code=200)
def delete_duplex(duplex_id: str) -> dict:
    return _record("duplex-delete", "Delete duplex", {"duplex_id": duplex_id})


@router.post("/design/duplexes/{duplex_id}/relax", status_code=200)
def relax_duplex(duplex_id: str) -> dict:
    """Settle a bound DIRECT duplex's geometry — the Proposal-B equivalent of
    ``relax_overhang_binding`` for a duplex that has NO legacy ``OverhangBinding``
    (e.g. a DIFFERENT-length root-to-root pair, which ``connect_duplex`` relocated
    via ``relocate_duplex`` instead of creating a binding).

    Resolves driver/driven overhang ids from the duplex's ``driver`` field and runs
    the SAME proven solve (``direct_relax.relax_direct_binding``): swing the driver's
    overhang duplex about its root (persisted as the driver's ``OverhangSpec.rotation``,
    the driven tip co-rotates) + cluster kinematics (rotate the connecting joint(s), else
    rigid-translate the driven root cluster) so the driven overhang's stretched tip↔root
    backbone bond closes to one bond length. The duplex stays bound.
    """
    from backend.core.direct_relax import relax_direct_binding
    from backend.core.validator import validate_design
    from backend.api.crud import _design_response_with_geometry

    design = design_state.get_or_404()
    dx = _find(design, duplex_id)
    if not dx.bound:
        raise HTTPException(
            422,
            detail=(
                f"Duplex {duplex_id!r} is not bound — connect/apply it first so the "
                f"driven overhang is relocated before relaxing."
            ),
        )
    driver_oh_id = dx.right.overhang_id if dx.driver == "right" else dx.left.overhang_id
    driven_oh_id = dx.left.overhang_id if dx.driver == "right" else dx.right.overhang_id
    try:
        updated, info = relax_direct_binding(design, driver_oh_id, driven_oh_id)
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(422, detail=f"relax_duplex failed: {exc!r}")

    design_state.set_design(updated)
    report = validate_design(updated)
    payload = _design_response_with_geometry(updated, report)
    payload["relax_info"] = info
    return payload


@router.get("/design/duplexes/{duplex_id}/pairing", status_code=200)
def get_duplex_pairing(duplex_id: str) -> dict:
    design = design_state.get_or_404()
    dx = _find(design, duplex_id)
    return classify_duplex_pairing(design, dx)


@router.get("/design/overhangs/{overhang_id}/pairing-map", status_code=200)
def get_overhang_pairing_map(overhang_id: str) -> dict:
    design = design_state.get_or_404()
    if not any(o.id == overhang_id for o in design.overhangs):
        raise HTTPException(404, detail=f"Overhang {overhang_id!r} not found.")
    # JSON keys must be strings.
    return {
        "overhang_id": overhang_id,
        "pairing_map": {
            str(bp): st for bp, st in overhang_pairing_map(design, overhang_id).items()
        },
    }
