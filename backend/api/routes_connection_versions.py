"""CRUD and atomic materialization routes for connection versions."""

from typing import Optional

from fastapi import APIRouter, HTTPException

from backend.api import state as design_state
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
    Duplex,
    OverhangBinding,
    OverhangConnection,
)
from backend.core.overhang_ops import _ovhg_backing_length
from backend.core.render_diff import _local_changed_helices, _strand_occupancy

router = APIRouter()


@router.post("/design/connection-versions", status_code=201)
def create_connection_version(body: ConnectionVersionCreateRequest) -> dict:
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


def _cv_sub_domain_at_attach(d: Design, ovhg_id: str, attach: str):
    ov = next((o for o in d.overhangs if o.id == ovhg_id), None)
    if ov is None or not ov.sub_domains:
        return None
    ordered = sorted(ov.sub_domains, key=lambda sd: sd.start_bp_offset or 0)
    return (ordered[0] if attach == "root" else ordered[-1]).id


def _cv_create_bound_binding(
    d: Design, a_id: str, b_id: str, attach_a: str, attach_b: str, connection_type: str
) -> Design:
    """Materialize a DIRECT connection (root-to-root OR end-to-root) as a single
    non-consuming `OverhangBinding`, relocated on apply so the duplex renders
    immediately and overhang B's embedded-strand bond is left stretched.

    Unified path (2026-06-30, replaces the end-to-root binder splice): A is the
    driver (its helix HOSTS the duplex), B is the driven side (its tip domain is
    relocated onto A's helix, antiparallel — `compute_bind_topology`/`apply_bind_topology`).
    Neither overhang is consumed; both stay in `design.overhangs`. The bound flag is
    set but NO cluster relax runs, so the cross-helix root↔tip bond is visibly
    stretched until the user hits Relax.
    """
    from backend.core.binding_relax import apply_bind_topology, compute_bind_topology

    sd_a = _cv_sub_domain_at_attach(d, a_id, attach_a)
    sd_b = _cv_sub_domain_at_attach(d, b_id, attach_b)
    if not (sd_a and sd_b):
        return d  # no sub-domains → can't bind (mirrors the old direct silent-skip)

    # Length-preservation: a direct binding relocates one WHOLE tip domain onto the
    # other, so it requires equal-length attach sub-domains. DIFFERENT-length
    # overhangs are represented by the Duplex (paired window + toehold) — skip the
    # binding here (its unequal-length record would fail validation anyway; the
    # binding-based geometry for different lengths is deferred). The duplex is
    # created separately by the frontend's _ensureDuplexForPair.
    def _sd_len(sd_id: str) -> Optional[int]:
        for o in d.overhangs:
            for sd in o.sub_domains or []:
                if sd.id == sd_id:
                    return sd.length_bp
        return None

    if _sd_len(sd_a) != _sd_len(sd_b):
        return d

    used = {b.name for b in d.overhang_bindings}
    n = 1
    while f"B{n}" in used:
        n += 1
    binding = OverhangBinding(
        name=f"B{n}",
        sub_domain_a_id=sd_a,
        sub_domain_b_id=sd_b,
        overhang_a_id=a_id,
        overhang_b_id=b_id,
        driver_oh_id=a_id,
        driven_oh_id=b_id,
        connection_type=connection_type,
        bound=True,
    )
    topology = compute_bind_topology(d, binding, driver_side="a")
    binding = binding.model_copy(update={"prior_driven_topology": topology.snapshot})
    d = d.model_copy(update={"overhang_bindings": [*d.overhang_bindings, binding]})
    d = apply_bind_topology(d, topology)

    # Re-seat the relocated duplex like a linker bridge: ORIENTED along and CENTERED
    # on the chord between its two embedded-staple connections (A's root junction and
    # B's root junction), so both root bonds share the stretch symmetrically and are
    # minimized. Persisted as the DRIVER's OverhangSpec.rotation + translation so the
    # whole duplex (driver overhang + co-moving driven tip partner) transforms rigidly
    # at geometry time. Zero both first so the placement is measured against the
    # freshly-relocated (un-seated, identity) geometry, then store the result.
    from backend.core.direct_relax import duplex_midpoint_placement

    d = d.model_copy(
        update={
            "overhangs": [
                o.model_copy(
                    update={
                        "rotation": [0.0, 0.0, 0.0, 1.0],
                        "translation": [0.0, 0.0, 0.0],
                    }
                )
                if o.id == a_id
                else o
                for o in d.overhangs
            ]
        }
    )
    placement = duplex_midpoint_placement(d, a_id, b_id)
    if placement is not None:
        rot, trans = placement
        d = d.model_copy(
            update={
                "overhangs": [
                    o.model_copy(update={"rotation": rot, "translation": trans})
                    if o.id == a_id
                    else o
                    for o in d.overhangs
                ]
            }
        )
    # Promote the just-placed pose onto a first-class child DUPLEX cluster (sidebar-listed,
    # gizmo-movable, drift-free) — geometry+axis neutral (proven on 2x2_OH_test).
    # [[overhang-duplex-cluster]] P1b.
    from backend.core.duplex_cluster import materialize_duplex_cluster

    d, _cid = materialize_duplex_cluster(d, a_id)
    return d


def _apply_connection_version_impl(
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
    from backend.core.binding_relax import revert_bind_topology
    from backend.core.cluster_reconcile import MutationReport
    from backend.core.lattice import (
        generate_linker_topology,
        remove_linker_topology,
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
        # First-time Connect supplies a not-yet-persisted version so candidate
        # creation and materialization share ONE undo snapshot. Add it only
        # inside the logged mutation; Undo then restores the truly pre-Connect
        # design instead of leaving a draft version/sidebar group behind.
        if new_version is not None:
            d = d.model_copy(
                update={"connection_versions": [*d.connection_versions, new_version]},
                deep=True,
            )
            assign_default_names(d)
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

        # 2. Tear down EVERY materialized connection / binding that shares either
        #    overhang — an overhang can be in only one applied connection, so any
        #    prior one involving a_id or b_id (even with a third overhang) is
        #    unapplied here before the new one is created.
        def _involves(x):
            return a_id in (x.overhang_a_id, x.overhang_b_id) or b_id in (
                x.overhang_a_id,
                x.overhang_b_id,
            )

        for c in list(d.overhang_connections):
            if _involves(c):
                d = remove_linker_topology(
                    d.model_copy(
                        update={
                            "overhang_connections": [
                                x for x in d.overhang_connections if x.id != c.id
                            ]
                        }
                    ),
                    c.id,
                )
        # Bound direct bindings relocated the driven OH's domain — revert that
        # relocation (restore the driven helix + domain + crossovers) BEFORE dropping
        # the binding, else the relocated domain is orphaned on the driver helix.
        for bd in [b for b in d.overhang_bindings if _involves(b)]:
            if bd.bound and bd.prior_driven_topology:
                d = revert_bind_topology(d, bd.prior_driven_topology)
        d = d.model_copy(
            update={
                "overhang_bindings": [
                    b for b in d.overhang_bindings if not _involves(b)
                ]
            }
        )
        # 3. Create the version's connection type.
        report = None
        bridge_helix_ids: list[str] = []
        if direct:
            # BOTH root-to-root and end-to-root: one non-consuming bound binding,
            # relocated on apply (duplex forms now; B's embedded-strand bond left
            # stretched). The only per-type difference is the attach pair. (Replaces
            # the end-to-root binder splice that consumed B — removed 2026-06-30.)
            d = _cv_create_bound_binding(d, a_id, b_id, attach_a, attach_b, vtype)
            # A display Duplex is part of the connection itself. Keep it inside
            # this snapshot so one Undo removes both the binding and the entry
            # shown by the Linkers/Bindings UI. The old frontend follow-up POST
            # was outside the feature log and therefore survived undo.
            pair = {a_id, b_id}
            if not any(
                {dx.left.overhang_id, dx.right.overhang_id} == pair
                for dx in d.duplexes
            ):
                from backend.core.duplex import (
                    connect_register,
                    longest_driver,
                    relocate_duplex,
                    smallest_unused_duplex_name,
                )

                left, right = connect_register(d, a_id, attach_a, b_id, attach_b)
                dx = Duplex(
                    name=smallest_unused_duplex_name(d),
                    left=left,
                    right=right,
                    driver=longest_driver(d, left, right),
                    allow_n_wildcard=True,
                    connection_type=vtype,
                )
                d = d.model_copy(update={"duplexes": [*d.duplexes, dx]}, deep=True)
                # Different-length pairs have no legacy OverhangBinding; their
                # driven-domain relocation belongs to this same atomic action.
                if not any(
                    {b.overhang_a_id, b.overhang_b_id} == pair
                    for b in d.overhang_bindings
                ):
                    d = relocate_duplex(d, dx)
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
    # A connection apply is local even on very large designs. Returning full
    # geometry made VoltronCoreArm OH49↔OH50 rebuild all 67 helices in the
    # browser: ~10 s request + ~37 s parse/store/scene work. Derive the exact
    # occupancy footprint (including the driven helix removed by relocation)
    # and use the established partial merge protocol so the renderer replaces
    # only those helices. The full fallback remains for a non-local diff.
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


@router.post("/design/connection-versions/{version_id}/apply", status_code=200)
def apply_connection_version(version_id: str) -> dict:
    return _apply_connection_version_impl(version_id)


@router.post("/design/connection-versions/connect", status_code=201)
def create_and_apply_connection_version(body: ConnectionVersionCreateRequest) -> dict:
    """Create and materialize a first-time connection as one undoable action."""
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
