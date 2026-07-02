"""API layer — Proposal-B **Duplex** route handlers (Phase 1).

The register-bearing overhang pairing graph (see
``memory/project_overhang_duplex_foundation.md``). These endpoints create / edit /
delete :class:`~backend.core.models.Duplex` edges and read back the per-base
pairing classification. They coexist with the legacy ``/design/overhang-bindings``
routes (retired only in Phase 6).

Routes
------
  GET    /design/duplexes                    — list all duplexes
  POST   /design/duplexes                    — create a duplex (register + driver)
  PATCH  /design/duplexes/{id}               — edit register / driver / bound / name
  DELETE /design/duplexes/{id}               — remove a duplex
  POST   /design/duplexes/{id}/relax         — settle a bound direct duplex's geometry
  GET    /design/duplexes/{id}/pairing       — per-base classification (oracle read)
  GET    /design/overhangs/{id}/pairing-map  — bp → paired/mismatch/toehold coverage

Validation deliberately KEEPS the Watson-Crick gate for now (user decision) — a
real mismatch in the register is rejected 422; N positions pass under
``allow_n_wildcard``. Bulges are out of scope (equal-length ends, enforced on the
model). The one integrity invariant — no bp pairs twice on an overhang — is a 409.
"""
from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ValidationError

from backend.api import state as design_state
from backend.api.crud import _design_response
from backend.core.duplex import (
    duplex_wc_ok, smallest_unused_duplex_name, classify_duplex_pairing,
    overhang_pairing_map, connect_register, longest_driver,
    sync_duplexes_from_bindings,
)
from backend.core.models import Design, Duplex, DuplexEnd, _overhang_backing_domain

router = APIRouter()


class DuplexEndBody(BaseModel):
    overhang_id: str
    start_bp: int
    end_bp: int


class CreateDuplexBody(BaseModel):
    left: DuplexEndBody
    right: DuplexEndBody
    driver: Literal['left', 'right'] = 'left'
    bound: bool = False
    binding_mode: Literal['duplex', 'toehold'] = 'duplex'
    allow_n_wildcard: bool = True
    connection_type: Optional[str] = None


class PatchDuplexBody(BaseModel):
    left: Optional[DuplexEndBody] = None
    right: Optional[DuplexEndBody] = None
    driver: Optional[Literal['left', 'right']] = None
    bound: Optional[bool] = None
    name: Optional[str] = None


def _end(body: DuplexEndBody) -> DuplexEnd:
    return DuplexEnd(overhang_id=body.overhang_id, start_bp=body.start_bp, end_bp=body.end_bp)


def _validate_placement(design: Design, dx: Duplex, *, ignore_id: Optional[str] = None) -> None:
    """Pre-flight the HTTP-meaningful failures so clients get 404/422/409 instead
    of a 500 from the model validator. Mirrors ``Design._validate_duplexes`` but
    with typed status codes + the WC gate."""
    overhang_ids = {o.id for o in design.overhangs}
    # Claimed bp per overhang from OTHER duplexes (for the double-pairing 409).
    claimed: dict[str, set] = {}
    for other in design.duplexes:
        if other.id == ignore_id:
            continue
        for e in (other.left, other.right):
            claimed.setdefault(e.overhang_id, set()).update(e.covered_bp())

    for side, end in (('left', dx.left), ('right', dx.right)):
        if end.overhang_id not in overhang_ids:
            raise HTTPException(404, detail=f"{side} overhang {end.overhang_id!r} not found.")
        _, dom = _overhang_backing_domain(design, end.overhang_id)
        if dom is None:
            raise HTTPException(404, detail=f"{side} overhang {end.overhang_id} has no backing domain.")
        lo, hi = sorted((dom.start_bp, dom.end_bp))
        e_lo, e_hi = sorted((end.start_bp, end.end_bp))
        if e_lo < lo or e_hi > hi:
            raise HTTPException(422, detail=(
                f"{side} bp interval [{end.start_bp}, {end.end_bp}] is outside "
                f"overhang {end.overhang_id}'s backing domain [{lo}, {hi}]."
            ))
        overlap = claimed.get(end.overhang_id, set()) & end.covered_bp()
        if overlap:
            raise HTTPException(409, detail=(
                f"bp {sorted(overlap)} on overhang {end.overhang_id} are already "
                f"paired by another duplex (a base has at most one partner)."
            ))

    ok, reason = duplex_wc_ok(design, dx)
    if not ok:
        raise HTTPException(422, detail=f"duplex register is not complementary: {reason}.")


def _find(design: Design, duplex_id: str) -> Duplex:
    dx = next((d for d in design.duplexes if d.id == duplex_id), None)
    if dx is None:
        raise HTTPException(404, detail=f"Duplex {duplex_id!r} not found.")
    return dx


def _propagate_driver_to_binding(design: Design, duplex: Duplex) -> Design:
    """#4 (Phase 4a): record the user's duplex driver choice on the linked
    ``OverhangBinding``'s ``driver_oh_id`` / ``driven_oh_id`` so the EXISTING,
    proven relax (``relax_overhang_binding`` reads exactly those fields) honors it
    on the next apply/relax. No geometry is moved here — live re-placement when
    FLIPPING an already-bound driver needs a revert+re-apply and is Phase 4b."""
    driver_oh = duplex.left.overhang_id if duplex.driver == 'left' else duplex.right.overhang_id
    driven_oh = duplex.right.overhang_id if duplex.driver == 'left' else duplex.left.overhang_id
    pair = {duplex.left.overhang_id, duplex.right.overhang_id}
    changed = False
    new_bindings = []
    for b in design.overhang_bindings:
        if ({b.overhang_a_id, b.overhang_b_id} == pair
                and (b.driver_oh_id != driver_oh or b.driven_oh_id != driven_oh)):
            new_bindings.append(b.model_copy(update={
                "driver_oh_id": driver_oh, "driven_oh_id": driven_oh}))
            changed = True
        else:
            new_bindings.append(b)
    return design.model_copy(update={"overhang_bindings": new_bindings}) if changed else design


@router.get("/design/duplexes", status_code=200)
def list_duplexes() -> dict:
    design = design_state.get_or_404()
    return {"duplexes": [d.model_dump() for d in design.duplexes]}


@router.post("/design/duplexes", status_code=201)
def create_duplex(body: CreateDuplexBody) -> dict:
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    try:
        dx = Duplex(
            name=smallest_unused_duplex_name(design),
            left=_end(body.left), right=_end(body.right),
            driver=body.driver, bound=body.bound, binding_mode=body.binding_mode,
            allow_n_wildcard=body.allow_n_wildcard, connection_type=body.connection_type,
        )
    except ValidationError as e:
        raise HTTPException(422, detail=str(e))
    _validate_placement(design, dx)

    updated = design.model_copy(update={"duplexes": [*design.duplexes, dx]}, deep=True)
    design_state.set_design(updated)
    report = validate_design(updated)
    resp = _design_response(updated, report)
    resp["duplex_id"] = dx.id
    return resp


class ConnectDuplexBody(BaseModel):
    overhang_a_id: str
    overhang_a_attach: Literal['root', 'free_end'] = 'free_end'
    overhang_b_id: str
    overhang_b_attach: Literal['root', 'free_end'] = 'root'
    driver: Optional[Literal['left', 'right']] = None
    allow_n_wildcard: bool = True


@router.post("/design/duplexes/connect", status_code=201)
def connect_duplex(body: ConnectDuplexBody) -> dict:
    """Producer: create a display duplex CONNECTING two overhangs at their attach
    ends. Register is computed mechanically (length = min, no resize — the longer
    overhang keeps its toehold). Idempotent per pair (409 if already connected)."""
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    for dx in design.duplexes:
        if {dx.left.overhang_id, dx.right.overhang_id} == {body.overhang_a_id, body.overhang_b_id}:
            raise HTTPException(409, detail="these overhangs are already connected by a duplex.")
    try:
        left, right = connect_register(
            design, body.overhang_a_id, body.overhang_a_attach,
            body.overhang_b_id, body.overhang_b_attach,
        )
    except ValueError as e:
        raise HTTPException(422, detail=str(e))
    driver = body.driver or longest_driver(design, left, right)
    try:
        dx = Duplex(name=smallest_unused_duplex_name(design), left=left, right=right,
                    driver=driver, allow_n_wildcard=body.allow_n_wildcard)
    except ValidationError as e:
        raise HTTPException(422, detail=str(e))
    _validate_placement(design, dx)

    updated = design.model_copy(update={"duplexes": [*design.duplexes, dx]}, deep=True)
    # DIFFERENT-length (or otherwise binding-less) pair → relocate the driven's
    # domain onto the driver's helix so the duplex forms in 3D + cadnano (Phase 4b).
    # Equal-length pairs already have an OverhangBinding doing this → skip.
    pair = {dx.left.overhang_id, dx.right.overhang_id}
    has_binding = any({b.overhang_a_id, b.overhang_b_id} == pair for b in updated.overhang_bindings)
    if not has_binding:
        from backend.core.duplex import relocate_duplex
        try:
            fresh = next(d for d in updated.duplexes if d.id == dx.id)
            updated = relocate_duplex(updated, fresh)
        except Exception:
            pass  # relocation best-effort; the duplex/display still exists
    design_state.set_design(updated)
    report = validate_design(updated)
    resp = _design_response(updated, report)
    resp["duplex_id"] = dx.id
    return resp


@router.post("/design/duplexes/sync-from-bindings", status_code=200)
def sync_from_bindings() -> dict:
    """Ensure every legacy OverhangBinding pair also has a display duplex (live
    equivalent of derive-on-load). Idempotent; called after a Connect."""
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    updated = sync_duplexes_from_bindings(design)
    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


@router.patch("/design/duplexes/{duplex_id}", status_code=200)
def patch_duplex(duplex_id: str, body: PatchDuplexBody) -> dict:
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    current = _find(design, duplex_id)
    patch = body.model_dump(exclude_unset=True)

    update: dict = {}
    if 'left' in patch and patch['left'] is not None:
        update['left'] = _end(body.left)
    if 'right' in patch and patch['right'] is not None:
        update['right'] = _end(body.right)
    if 'driver' in patch:
        update['driver'] = body.driver
    if 'bound' in patch:
        update['bound'] = body.bound
    if 'name' in patch:
        new_name = (body.name or '').strip()
        if not new_name:
            raise HTTPException(422, detail="name must be non-empty.")
        update['name'] = new_name

    try:
        candidate = current.model_copy(update=update, deep=True)
    except ValidationError as e:
        raise HTTPException(422, detail=str(e))
    if 'left' in update or 'right' in update:
        _validate_placement(design, candidate, ignore_id=duplex_id)

    new_list = [candidate if d.id == duplex_id else d for d in design.duplexes]
    updated = design.model_copy(update={"duplexes": new_list}, deep=True)
    if 'driver' in update:
        updated = _propagate_driver_to_binding(updated, candidate)
        # If the linked binding is bound, RE-PLACE its geometry for the new driver
        # (revert + re-bind via the proven machinery), so the toggle moves the model.
        from backend.api.crud import reapply_binding_driver
        pair = {candidate.left.overhang_id, candidate.right.overhang_id}
        linked = next((bb for bb in updated.overhang_bindings
                       if {bb.overhang_a_id, bb.overhang_b_id} == pair), None)
        if linked is not None:
            updated = reapply_binding_driver(updated, linked.id)
    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


@router.delete("/design/duplexes/{duplex_id}", status_code=200)
def delete_duplex(duplex_id: str) -> dict:
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    _find(design, duplex_id)
    new_list = [d for d in design.duplexes if d.id != duplex_id]
    updated = design.model_copy(update={"duplexes": new_list}, deep=True)
    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


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
        raise HTTPException(422, detail=(
            f"Duplex {duplex_id!r} is not bound — connect/apply it first so the "
            f"driven overhang is relocated before relaxing."))
    driver_oh_id = dx.right.overhang_id if dx.driver == 'right' else dx.left.overhang_id
    driven_oh_id = dx.left.overhang_id if dx.driver == 'right' else dx.right.overhang_id
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
    return {"overhang_id": overhang_id,
            "pairing_map": {str(bp): st for bp, st in overhang_pairing_map(design, overhang_id).items()}}
