"""Relaxation, status, and authored-pose HTTP endpoints."""

from typing import Literal, Optional

import numpy as np
from fastapi import APIRouter, HTTPException
from fastapi.responses import ORJSONResponse
from pydantic import BaseModel

from backend.api import state as design_state
from backend.api.crud import (
    BindingDisplayPoseBody,
    _TimingTrace,
    _design_replace_response,
    _design_response,
    _design_response_with_geometry,
    _geometry_for_design,
)
from backend.core.bond_relax import (
    cluster_pair_for_bond_relax as _cluster_pair_for_bond_relax,
)
from backend.core.models import Design

router = APIRouter()


@router.post("/design/overhang-bindings/{binding_id}/relax", status_code=200)
def relax_overhang_binding(binding_id: str) -> dict:
    """Settle a DIRECT binding's geometry — UNIFIED for root-to-root AND
    end-to-root (2026-06-30).

    A direct connection relocated the driven overhang's tip onto the driver's
    helix on apply, leaving the driven tip↔root backbone bond stretched across
    helices. This closes that bond to one backbone-bond length (~0.67 nm) by
    swinging the driver's overhang duplex about its root (persisted as the
    driver's OverhangSpec.rotation; the driven tip co-rotates) plus cluster
    kinematics (rotate the connecting joint(s), else rigid-translate the driven
    root cluster). Same rigid body → swing only. The binding stays bound — there
    is no longer an unbind/rebind dance.
    """
    from backend.core.direct_relax import relax_direct_binding
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    binding = next((b for b in design.overhang_bindings if b.id == binding_id), None)
    if binding is None:
        raise HTTPException(404, detail=f"Overhang binding {binding_id!r} not found.")

    driver_oh_id = binding.driver_oh_id or binding.overhang_a_id
    driven_oh_id = binding.driven_oh_id or binding.overhang_b_id
    try:
        updated, info = relax_direct_binding(design, driver_oh_id, driven_oh_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, detail=f"relax_overhang_binding failed: {exc!r}")

    design_state.set_design(updated)
    report = validate_design(updated)
    payload = _design_response_with_geometry(updated, report)
    payload["relax_info"] = info
    return payload


@router.patch("/design/overhang-connections/{conn_id}/display-pose", status_code=200)
def patch_connection_display_pose(conn_id: str, body: BindingDisplayPoseBody) -> dict:
    """Authored display-only hinge angles for a LINKER (animation driver).

    Sets `unbound_angle_deg` / `bound_angle_deg` and auto-detects + stores
    `target_joint_id` (the single ClusterJoint connecting the two clusters the
    linker spans). Annotation-only — never modifies the linker topology, bridge,
    or any joint window; read solely by the display/animation layer.
    """
    from backend.core.linker_relax import _overhang_owning_cluster_id

    design = design_state.get_or_404()
    target = next((c for c in design.overhang_connections if c.id == conn_id), None)
    if target is None:
        raise HTTPException(404, detail=f"Overhang connection {conn_id!r} not found.")

    patch = body.model_dump(exclude_unset=True)

    # Auto-detect the spanning joint: the single ClusterJoint whose cluster is
    # one of the two clusters the linker's overhangs belong to.
    auto_joint = target.target_joint_id
    if auto_joint is None:
        ca = _overhang_owning_cluster_id(design, target.overhang_a_id)
        cb = _overhang_owning_cluster_id(design, target.overhang_b_id)
        cands = [j for j in design.cluster_joints if j.cluster_id in (ca, cb)]
        if len(cands) == 1:
            auto_joint = cands[0].id

    def _fn(d: Design) -> None:
        c = next((cc for cc in d.overhang_connections if cc.id == conn_id), None)
        if c is None:
            return
        if "unbound_angle_deg" in patch:
            c.unbound_angle_deg = patch["unbound_angle_deg"]
        if "bound_angle_deg" in patch:
            c.bound_angle_deg = patch["bound_angle_deg"]
        if auto_joint is not None:
            c.target_joint_id = auto_joint

    updated, report = design_state.mutate_and_validate(_fn)
    return _design_response(updated, report)


@router.get("/ssdna-fjc-lookup", status_code=200)
def get_ssdna_fjc_lookup() -> dict:
    """Pre-computed ssDNA freely-jointed-chain lookup.

    Served as a static JSON snapshot of ``backend/data/ssdna_fjc_lookup.json``
    so the frontend can fetch the table once on init and render ss linker
    bridges in their natural FJC random-walk shape (instead of a smooth
    Bezier chord between anchors). Body shape: ``{metadata, entries}``;
    ``entries[str(n_bp)]`` holds ``positions`` (canonical: first bead at
    origin, last bead on +x axis at R_ee), ``r_ee_nm``, ``rg_achieved_nm``,
    etc. See ``backend/core/ssdna_fjc.py`` for accessor docs.
    """
    from backend.core import ssdna_fjc

    return ssdna_fjc.dump_all()


@router.get("/design/overhang-connections/{conn_id}/relax-status", status_code=200)
def get_overhang_connection_relax_status(conn_id: str) -> dict:
    """Lightweight DOF check used by the linker context menu so it can render
    "Relax Linker" enabled or grayed out without an optimization round-trip."""
    from backend.core.linker_relax import dof_topology

    design = design_state.get_or_404()
    conn = next((c for c in design.overhang_connections if c.id == conn_id), None)
    if conn is None:
        raise HTTPException(404, detail=f"Overhang connection {conn_id!r} not found.")
    topo = dof_topology(design, conn)
    # Both ds and ss linkers can relax now (ds: chord → duplex visualLength;
    # ss: chord → mean R_ee from the FJC lookup table). The topology gate
    # (1-DOF or explicit multi-DOF) is the same for both.
    available = topo["status"] == "ok" and topo["n_dof"] == 1
    reason = topo["reason"]
    return {
        "available": available,
        "reason": reason,
        "n_dof": topo["n_dof"],
        "linker_type": conn.linker_type,
    }


class RelaxLinkerRequest(BaseModel):
    """Optional joint selection + ss-linker bin selection + kinematic limits.

    ``joint_ids``: omit (or send empty) for the 1-DOF auto-pick path;
    provide an explicit list for multi-DOF.

    ``bin_index``: ss linker only — which pre-baked FJC R_ee histogram bin
    to render. Values 0..hist_bins-1 (typically 0..39); the loader walks
    to the nearest occupied bin when empty. Omit to keep the connection's
    current ``bridge_bin_index``.

    ``r_ee_min_nm`` / ``r_ee_max_nm``: ss linker only — kinematic limits
    captured from the modal's range thumbs on the R_ee histogram. Stored
    on the connection for downstream simulation / animation use.
    """

    joint_ids: Optional[list[str]] = None
    bin_index: Optional[int] = None
    r_ee_min_nm: Optional[float] = None
    r_ee_max_nm: Optional[float] = None


@router.post("/design/overhang-connections/{conn_id}/relax", status_code=200)
def relax_overhang_connection(conn_id: str, body: RelaxLinkerRequest | None = None):
    """Optimize joint angles so the linker's connector arcs collapse.

    Requires a dsDNA linker. Two paths:

      1. ``body.joint_ids`` is None or empty → 1-DOF auto-pick: backend
         requires exactly one joint between the two overhangs' clusters.
      2. ``body.joint_ids`` is a non-empty list → multi-DOF: each joint's
         owning cluster rotates around its axis; angles optimized jointly.

    Each touched cluster gets a ClusterOpLogEntry so every angle change is
    undoable individually through the feature-log timeline.

    Response shape is the standard ``_design_replace_response`` picker, so
    typical relax operations (which only mutate cluster_transforms) take
    the lean ``cluster_only`` fast path — no full geometry recompute, no
    multi-MB JSON. ``relax_info`` always rides along.
    """
    from backend.core.linker_relax import (
        dof_topology,
        relax_linker,
        relax_ss_linker,
    )
    from backend.core.validator import validate_design

    trace = _TimingTrace()
    with trace.step("clone_prev"):
        design = design_state.get_or_404()
        prev = design.model_copy(deep=True)
    conn = next((c for c in design.overhang_connections if c.id == conn_id), None)
    if conn is None:
        raise HTTPException(404, detail=f"Overhang connection {conn_id!r} not found.")

    selected = body.joint_ids if (body and body.joint_ids) else None

    if selected is None:
        with trace.step("dof_topology"):
            topo = dof_topology(design, conn)
        if topo["status"] != "ok" or topo["n_dof"] != 1:
            raise HTTPException(
                400, detail=topo["reason"] or "Relax requires exactly 1 DOF."
            )

    try:
        with trace.step("relax_linker"):
            if conn.linker_type == "ss":
                bin_index = body.bin_index if body is not None else None
                r_ee_min_nm = body.r_ee_min_nm if body is not None else None
                r_ee_max_nm = body.r_ee_max_nm if body is not None else None
                updated, info = relax_ss_linker(
                    design,
                    conn,
                    selected,
                    bin_index=bin_index,
                    r_ee_min_nm=r_ee_min_nm,
                    r_ee_max_nm=r_ee_max_nm,
                )
            else:
                updated, info = relax_linker(design, conn, selected)
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc))
    with trace.step("commit_state"):
        design_state.set_design(updated)
    with trace.step("validate"):
        report = validate_design(updated)
    with trace.step("response"):
        payload = _design_replace_response(prev, updated, report, trace=trace)
        payload["relax_info"] = info
    return trace.attach(ORJSONResponse(payload))


# ── Generic Relax Bond (any stretched backbone bond) ─────────────────────────
#
# One endpoint serves crossovers, forced ligations, linker connector arcs,
# and intra-strand cross-helix arcs. The caller identifies the bond by
# type + record id (for record-backed types) or by half-edge (the two
# nucleotide endpoints). Backend resolves to (anchor_a, anchor_b,
# cluster_a_id, cluster_b_id, target_nm) and delegates to
# ``backend.core.bond_relax.relax_bond``.


class RelaxBondEndpoint(BaseModel):
    """One end of a generic bond — a nucleotide's (helix, bp, direction)
    triple. ``strand_id`` is optional but used as a tiebreaker when the
    same slot is occupied by multiple strands (e.g. duplex regions).
    """

    helix_id: str
    bp_index: int
    direction: Literal["FORWARD", "REVERSE"]
    strand_id: Optional[str] = None


class RelaxBondRequest(BaseModel):
    """Request body for ``POST /design/relax-bond``.

    Identify the bond by EITHER a record id (``bond_id``, for record-backed
    types — crossover, ligation, linker_arc) OR by the two nucleotide
    endpoints (``side_a`` + ``side_b``). At least one of the two paths
    must resolve; the backend prefers the record path when both supplied.

    ``side_to_move`` is required when no joints connect the two endpoint
    clusters (0-DOF rigid translate); ignored for 1-DOF / N-DOF cases.

    ``joint_ids`` optionally pins which joints to optimise (intersected
    with the candidate set; subset must be on either endpoint's cluster).
    None / empty = auto-pick (all joints connecting the two clusters).

    ``target_nm`` overrides the type-default chord target (B-DNA backbone
    bond ~0.67 nm for crossovers and intra-strand arcs; 0 for ligations
    and the direct-binding pre-bind line; duplex/FJC for linker arcs).
    """

    bond_type: Literal["crossover", "ligation", "linker_arc", "strand_arc"]
    bond_id: Optional[str] = None
    linker_side: Optional[Literal["a", "b"]] = None
    side_a: Optional[RelaxBondEndpoint] = None
    side_b: Optional[RelaxBondEndpoint] = None
    side_to_move: Optional[Literal["a", "b"]] = None
    joint_ids: Optional[list[str]] = None
    target_nm: Optional[float] = None


# Type-default chord targets (overridable by request.target_nm).
_BOND_TYPE_DEFAULT_TARGET_NM: dict[str, float] = {
    "crossover": 0.13,  # tight nuc-to-nuc gap (was 0.67 = B-DNA backbone bond)
    "ligation": 0.0,  # the two endpoints should coincide
    "linker_arc": 0.67,  # bridge boundary → anchor gap
    "strand_arc": 0.67,  # generic cross-helix backbone bond
}


def _resolve_bond_anchor_from_endpoint(
    geometry: list[dict],
    endpoint: RelaxBondEndpoint,
) -> np.ndarray:
    """Look up the nucleotide at (helix, bp, direction) in *geometry* and
    return its backbone position. 422 if not found."""
    # Tighten match on strand_id only when the caller provided one (so the
    # request can ignore strand_id for inter-strand connections like
    # ligations across different strand_ids).
    match = None
    for n in geometry:
        if n.get("helix_id") != endpoint.helix_id:
            continue
        if n.get("bp_index") != endpoint.bp_index:
            continue
        if n.get("direction") != endpoint.direction:
            continue
        if endpoint.strand_id and n.get("strand_id") != endpoint.strand_id:
            continue
        match = n
        break
    if match is None:
        raise HTTPException(
            422,
            detail=(
                f"relax_bond: no nucleotide found at helix={endpoint.helix_id!r}, "
                f"bp={endpoint.bp_index}, direction={endpoint.direction}"
            ),
        )
    pos = match.get("backbone_position") or match.get("base_position")
    if pos is None:
        raise HTTPException(
            422, detail=("relax_bond: nucleotide has no backbone position.")
        )
    return np.asarray(pos, dtype=float)


def _cluster_id_for_helix(design: Design, helix_id: str) -> Optional[str]:
    """Return the (helix-level) cluster id containing *helix_id*. Falls back
    to None if the helix is orphaned (no cluster owns it)."""
    for ct in design.cluster_transforms:
        if helix_id in ct.helix_ids:
            return ct.id
    return None


def _resolve_relax_bond_request(
    design: Design,
    body: RelaxBondRequest,
    geometry: list[dict],
) -> tuple[np.ndarray, np.ndarray, str, str, float, str]:
    """Resolve (anchor_a, anchor_b, cluster_a, cluster_b, target_nm,
    source_tag) for a bond-relax request, dispatching on bond_type.

    Raises HTTPException(422) with a descriptive message on any failure.
    """
    target_nm = body.target_nm
    if target_nm is None:
        target_nm = _BOND_TYPE_DEFAULT_TARGET_NM[body.bond_type]
    source_tag = f"bond-relax:{body.bond_type}"

    # ── Record-backed types: prefer bond_id resolution ───────────────────
    if body.bond_type == "crossover" and body.bond_id:
        xo = next((x for x in design.crossovers if x.id == body.bond_id), None)
        if xo is None:
            raise HTTPException(404, detail=(f"crossover {body.bond_id!r} not found."))
        side_a = RelaxBondEndpoint(
            helix_id=xo.half_a.helix_id,
            bp_index=xo.half_a.index,
            direction=xo.half_a.strand.value,
        )
        side_b = RelaxBondEndpoint(
            helix_id=xo.half_b.helix_id,
            bp_index=xo.half_b.index,
            direction=xo.half_b.strand.value,
        )
    elif body.bond_type == "ligation" and body.bond_id:
        fl = next((f for f in design.forced_ligations if f.id == body.bond_id), None)
        if fl is None:
            raise HTTPException(
                404, detail=(f"forced ligation {body.bond_id!r} not found.")
            )
        side_a = RelaxBondEndpoint(
            helix_id=fl.three_prime_helix_id,
            bp_index=fl.three_prime_bp,
            direction=fl.three_prime_direction.value,
        )
        side_b = RelaxBondEndpoint(
            helix_id=fl.five_prime_helix_id,
            bp_index=fl.five_prime_bp,
            direction=fl.five_prime_direction.value,
        )
    elif body.bond_type == "linker_arc" and body.bond_id:
        # linker_arc identifies a SINGLE connector arc: (conn_id, side a|b).
        # Side "a" = OH-A anchor ↔ bridge boundary on the ``__lnk__/__a``
        # complement; side "b" symmetric for OH-B. We resolve to the two
        # nuc endpoints of that single arc.
        if body.linker_side not in ("a", "b"):
            raise HTTPException(
                422, detail=("relax_bond: linker_arc requires linker_side='a' or 'b'.")
            )
        conn = next(
            (c for c in design.overhang_connections if c.id == body.bond_id),
            None,
        )
        if conn is None:
            raise HTTPException(
                404, detail=(f"overhang connection {body.bond_id!r} not found.")
            )
        side_a, side_b = _resolve_linker_arc_endpoints(
            design, conn, body.linker_side, geometry
        )
    else:
        # Half-edge addressing.
        if body.side_a is None or body.side_b is None:
            raise HTTPException(
                422,
                detail=(
                    "relax_bond: must provide either bond_id (with linker_side "
                    "for linker_arc) or side_a + side_b half-edge endpoints."
                ),
            )
        side_a = body.side_a
        side_b = body.side_b

    anchor_a = _resolve_bond_anchor_from_endpoint(geometry, side_a)
    anchor_b = _resolve_bond_anchor_from_endpoint(geometry, side_b)

    cluster_a_id, cluster_b_id = _cluster_pair_for_bond_relax(
        design,
        side_a.helix_id,
        side_b.helix_id,
    )
    if cluster_a_id is None or cluster_b_id is None:
        raise HTTPException(
            422,
            detail=("relax_bond: one or both endpoint helices are not in a cluster."),
        )

    return anchor_a, anchor_b, cluster_a_id, cluster_b_id, target_nm, source_tag


def _resolve_linker_arc_endpoints(
    design: Design,
    conn,
    linker_side: str,
    geometry: list[dict],
) -> tuple[RelaxBondEndpoint, RelaxBondEndpoint]:
    """Return the two nuc endpoints of a single linker connector arc.

    Side "a": OH-A's attach anchor ↔ bridge boundary nuc on strand
    ``__lnk__<conn_id>__a`` (or ``__s`` for ss linkers).
    Side "b": OH-B's analog.

    Falls back to scanning geometry for the strand-id-matched bridge bp
    when the precise boundary identification isn't trivially derivable.
    """
    from backend.core.lattice import _find_overhang_domain

    oh = next(
        (
            o
            for o in design.overhangs
            if o.id
            == (conn.overhang_a_id if linker_side == "a" else conn.overhang_b_id)
        ),
        None,
    )
    if oh is None:
        raise HTTPException(
            422, detail=(f"relax_bond: linker_arc side {linker_side!r} OH not found.")
        )
    attach = conn.overhang_a_attach if linker_side == "a" else conn.overhang_b_attach
    oh_domain = _find_overhang_domain(design, oh.id)
    if oh_domain is None:
        raise HTTPException(
            422,
            detail=(
                f"relax_bond: linker_arc side {linker_side!r} OH domain not found."
            ),
        )
    # OH-end attach bp = the attach-side end of the OH's domain.
    if attach == "root":
        attach_bp = oh_domain.start_bp
    else:
        attach_bp = oh_domain.end_bp
    oh_endpoint = RelaxBondEndpoint(
        helix_id=oh_domain.helix_id,
        bp_index=attach_bp,
        direction=oh_domain.direction.value,
    )

    # Bridge-boundary endpoint: the first/last bp of the linker bridge
    # strand on the virtual ``__lnk__`` helix (or its ss equivalent).
    # We scan geometry for the bridge nuc whose strand_id matches the
    # linker strand for this side.
    suffix = "a" if linker_side == "a" else ("b" if conn.linker_type == "ds" else "s")
    bridge_strand_id = f"__lnk__{conn.id}__{suffix}"
    bridge_nucs = [
        n
        for n in geometry
        if n.get("strand_id") == bridge_strand_id
        and n.get("helix_id", "").startswith(f"__lnk__{conn.id}")
    ]
    if not bridge_nucs:
        raise HTTPException(
            422,
            detail=(
                f"relax_bond: no bridge nucleotides found for linker "
                f"{conn.id!r} side {linker_side!r}."
            ),
        )
    # Side "a" arc reaches the bridge bp closest to side A — the lowest bp
    # on a ds bridge with comp-first-a (linker strand traverses
    # [complement_a, bridge_forward]). The opposite side is bp L-1. Pick
    # by linker_side: a → min bp, b → max bp.
    bridge_nucs.sort(key=lambda n: n.get("bp_index", 0))
    bridge_nuc = bridge_nucs[0] if linker_side == "a" else bridge_nucs[-1]
    bridge_endpoint = RelaxBondEndpoint(
        helix_id=bridge_nuc["helix_id"],
        bp_index=bridge_nuc["bp_index"],
        direction=bridge_nuc.get("direction", "FORWARD"),
    )
    return oh_endpoint, bridge_endpoint


@router.post("/design/relax-bond", status_code=200)
def relax_bond_endpoint(body: RelaxBondRequest) -> dict:
    """Generic relax for any stretched backbone bond.

    Resolves the bond's two endpoints + their owning clusters, then runs:

      * 0-DOF (no joints between clusters): rigidly translate the cluster
        named by ``side_to_move`` so its anchor closes onto the fixed side.
      * 1-DOF (one joint): rotate the joint's owning cluster.
      * N-DOF (multiple joints): Powell over all qualifying joints
        (intersected with ``joint_ids`` if provided).

    Same-cluster bonds are refused (422) — no relaxation is possible.
    """
    from backend.core.bond_relax import relax_bond as core_relax_bond
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    prev = design.model_copy(deep=True)

    geometry = _geometry_for_design(design)
    (anchor_a, anchor_b, cluster_a_id, cluster_b_id, target_nm, source_tag) = (
        _resolve_relax_bond_request(design, body, geometry)
    )

    try:
        updated, info = core_relax_bond(
            design,
            anchor_a=anchor_a,
            anchor_b=anchor_b,
            cluster_a_id=cluster_a_id,
            cluster_b_id=cluster_b_id,
            target_nm=target_nm,
            side_to_move=body.side_to_move,
            joint_ids=body.joint_ids,
            source_tag=source_tag,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, detail=f"relax_bond failed: {exc!r}")

    design_state.set_design(updated)

    report = validate_design(updated)
    payload = _design_replace_response(prev, updated, report)
    payload["relax_info"] = info
    return payload


# ── OverhangBinding endpoints (Phase 5) ─────────────────────────────────────
#
# Bindings record a Watson-Crick sub-domain↔sub-domain pairing. Flipping a
# binding's `bound` flag locks the connecting ClusterJoint to the duplex-
# satisfying angle until the binding is released. See `OverhangBinding` in
# backend/core/models.py for the data model, and `backend.core.binding_relax`
# for the locked-angle computation.
