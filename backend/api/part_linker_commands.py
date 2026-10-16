"""Native part linker lifecycle, including authored length edits."""

from fastapi import HTTPException
from backend.core.models import Design, OverhangConnection
from backend.core.overhang_ops import (
    _check_linker_compatibility,
    _overhang_end,
    _used_overhang_ends,
)

KINDS = frozenset({"linker-add", "linker-patch", "linker-delete"})


def create(design, body, identity):
    from backend.core.lattice import (
        assign_overhang_connection_names,
        generate_linker_topology,
    )

    if body.overhang_a_id == body.overhang_b_id:
        raise HTTPException(400, detail="overhang_a_id and overhang_b_id must differ.")
    # Allow length_value == 0 for indirect connection types (shared linker
    # strand → no user-controllable bridge nucleotides).
    if body.length_value < 0:
        raise HTTPException(400, detail="length_value must be non-negative.")
    existing_ids = {o.id for o in design.overhangs}
    for ovhg_id in (body.overhang_a_id, body.overhang_b_id):
        if ovhg_id not in existing_ids:
            raise HTTPException(404, detail=f"Overhang {ovhg_id!r} not found.")

    err = _check_linker_compatibility(
        _overhang_end(body.overhang_a_id),
        _overhang_end(body.overhang_b_id),
        body.overhang_a_attach,
        body.overhang_b_attach,
        body.linker_type,
    )
    if err:
        raise HTTPException(400, detail=err)

    # Per-end uniqueness: a (overhang, attach) pair can only be in one connection.
    used = _used_overhang_ends(design)
    for ovhg_id, attach in (
        (body.overhang_a_id, body.overhang_a_attach),
        (body.overhang_b_id, body.overhang_b_attach),
    ):
        if (ovhg_id, attach) in used:
            attach_label = "free end" if attach == "free_end" else "root"
            raise HTTPException(
                400,
                detail=f"Overhang {ovhg_id!r} is already linked at its {attach_label}.",
            )

    bridge_seq = (body.bridge_sequence or "").upper().strip() or None
    conn = OverhangConnection(
        id=identity,
        name=body.name,
        overhang_a_id=body.overhang_a_id,
        overhang_a_attach=body.overhang_a_attach,
        overhang_b_id=body.overhang_b_id,
        overhang_b_attach=body.overhang_b_attach,
        linker_type=body.linker_type,
        length_value=body.length_value,
        length_unit=body.length_unit,
        bridge_sequence=bridge_seq,
    )

    from backend.core.cluster_reconcile import MutationReport

    bridge_id = f"__lnk__{conn.id}"

    def _fn(d: Design):
        nxt = d.model_copy(
            update={"overhang_connections": [*d.overhang_connections, conn]}
        )
        nxt = assign_overhang_connection_names(nxt)
        nxt = generate_linker_topology(nxt, conn)
        # Auto-assign so the new linker complement (binds_overhang_id) carries the
        # real reverse-complement of its overhang for simulation — no-op until the
        # scaffold is sequenced. Targeted to the two overhangs' own strands, their
        # binders, and the strands on the new __lnk__ bridge helix, so a hand-typed
        # sequence on an unrelated staple survives the connection.
        from backend.core.sequences import (
            overhang_dependent_strand_ids,
            reassign_strands,
        )

        affected = overhang_dependent_strand_ids(
            nxt, [conn.overhang_a_id, conn.overhang_b_id], extra_helix_ids=[bridge_id]
        )
        nxt = reassign_strands(nxt, affected)
        # The virtual __lnk__ bridge helix is invisible to clustering — orphan it
        # so the reconciler doesn't pull it into a cluster via lattice proximity.
        return nxt, MutationReport(new_helix_origins={bridge_id: None})

    return _fn(design)


def patch(design, conn_id, body):
    from backend.core.lattice import (
        generate_linker_topology,
        remove_linker_topology,
    )

    target = next((c for c in design.overhang_connections if c.id == conn_id), None)
    if target is None:
        raise HTTPException(404, detail=f"Overhang connection {conn_id!r} not found.")

    patch = body.model_dump(exclude_unset=True)
    if "name" in patch:
        new_name = (patch["name"] or "").strip()
        if not new_name:
            raise HTTPException(400, detail="name must be a non-empty string.")
        clash = next(
            (
                c
                for c in design.overhang_connections
                if c.id != conn_id and c.name == new_name
            ),
            None,
        )
        if clash is not None:
            raise HTTPException(
                400, detail=f"Connection name {new_name!r} is already in use."
            )
        patch["name"] = new_name
    if (
        "length_value" in patch
        and patch["length_value"] is not None
        and patch["length_value"] < 0
    ):
        raise HTTPException(400, detail="length_value must be non-negative.")
    # bridge_sequence: "" → clear, "ACGT…" → assign (uppercased, ACGTN only),
    # omitted → leave untouched. Run this BEFORE the `if v is not None` filter
    # below so an explicit clear isn't silently dropped.
    bridge_clear = False
    if "bridge_sequence" in patch:
        raw = patch["bridge_sequence"]
        if raw is None or raw == "":
            bridge_clear = True
            del patch["bridge_sequence"]
        else:
            cleaned = "".join(ch for ch in str(raw).upper() if ch in "ACGTN")
            patch["bridge_sequence"] = cleaned or None
            if patch["bridge_sequence"] is None:
                bridge_clear = True
                del patch["bridge_sequence"]

    new_target = target.model_copy(
        update={k: v for k, v in patch.items() if v is not None}
    )
    if bridge_clear:
        new_target = new_target.model_copy(update={"bridge_sequence": None})
    new_list = [
        new_target if c.id == conn_id else c for c in design.overhang_connections
    ]
    updated = design.model_copy(update={"overhang_connections": new_list})

    # Auto-rebuild the linker topology if length changed (length_value or unit).
    length_changed = (
        "length_value" in patch and new_target.length_value != target.length_value
    ) or ("length_unit" in patch and new_target.length_unit != target.length_unit)
    if length_changed:
        # Capture the EXISTING complement-domain (binding) bp ranges so they
        # survive the bridge regeneration. Without this, the user's manually-
        # resized binding domains would snap back to the overhang's full
        # length on every linker bridge resize. Each strand may have ONE
        # complement (ds case) or TWO (ss case: complementA + complementB).
        bridge_helix_id = f"__lnk__{conn_id}"
        # strand_id → list of {helix_id, start_bp, end_bp, direction}, in
        # 5'→3' order matching how _make_complement_domain produced them.
        prev_complements: dict[str, list[dict]] = {}
        for strand in updated.strands:
            if not strand.id.startswith(bridge_helix_id + "__"):
                continue
            comps = [
                {
                    "helix_id": d.helix_id,
                    "start_bp": d.start_bp,
                    "end_bp": d.end_bp,
                    "direction": d.direction,
                }
                for d in strand.domains
                if d.helix_id != bridge_helix_id
            ]
            if comps:
                prev_complements[strand.id] = comps

        updated = remove_linker_topology(updated, conn_id)
        updated = generate_linker_topology(updated, new_target)

        # Restore the user-set complement-domain bp ranges on the regenerated
        # strands. Match snapshot complements to new domains by `helix_id`
        # (each helix id appears at most once per strand because each strand
        # touches each overhang helix at most once).
        if prev_complements:
            new_strands = []
            for strand in updated.strands:
                snaps = prev_complements.get(strand.id)
                if not snaps:
                    new_strands.append(strand)
                    continue
                snap_by_helix = {s["helix_id"]: s for s in snaps}
                patched_doms = []
                for d in strand.domains:
                    s = (
                        snap_by_helix.get(d.helix_id)
                        if d.helix_id != bridge_helix_id
                        else None
                    )
                    if s is not None:
                        patched_doms.append(
                            d.model_copy(
                                update={
                                    "start_bp": s["start_bp"],
                                    "end_bp": s["end_bp"],
                                    "direction": s["direction"],
                                }
                            )
                        )
                    else:
                        patched_doms.append(d)
                new_strands.append(
                    strand.model_copy(
                        update={
                            "domains": patched_doms,
                            "sequence": None,  # length may have changed; clear
                        }
                    )
                )
            updated = updated.model_copy(update={"strands": new_strands})

    from backend.core.cluster_reconcile import MutationReport

    bridge_id = f"__lnk__{conn_id}"
    mreport = MutationReport(new_helix_origins={bridge_id: None})
    return updated, mreport


def delete(design, conn_id):
    from backend.core.lattice import remove_linker_topology

    conn = next((c for c in design.overhang_connections if c.id == conn_id), None)
    if conn is None:
        raise HTTPException(404, detail=f"Overhang connection {conn_id!r} not found.")

    def _fn(d: Design) -> Design:
        new_list = [c for c in d.overhang_connections if c.id != conn_id]
        nxt = d.model_copy(update={"overhang_connections": new_list})
        return remove_linker_topology(nxt, conn_id)

    return _fn(design)


def build(kind, design, params):
    from backend.api.routes_overhang_connections import (
        OverhangConnectionCreateRequest,
        OverhangConnectionPatchRequest,
    )

    if kind == "linker-add":
        return create(
            design,
            OverhangConnectionCreateRequest.model_validate(params),
            params["conn_id"],
        )
    if kind == "linker-patch":
        return patch(
            design,
            params["conn_id"],
            OverhangConnectionPatchRequest.model_validate(params),
        )
    return delete(design, params["conn_id"])
