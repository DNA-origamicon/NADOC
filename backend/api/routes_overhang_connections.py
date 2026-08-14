"""CRUD routes for topology-backed overhang linker connections."""

from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.api import state as design_state
from backend.api.crud import _design_response
from backend.core.models import Design, OverhangConnection
from backend.core.overhang_ops import (
    _check_linker_compatibility,
    _overhang_end,
    _used_overhang_ends,
)

router = APIRouter()


class OverhangConnectionCreateRequest(BaseModel):
    overhang_a_id: str
    overhang_a_attach: Literal["root", "free_end"]
    overhang_b_id: str
    overhang_b_attach: Literal["root", "free_end"]
    linker_type: Literal["ss", "ds"]
    length_value: float
    length_unit: Literal["bp", "nm"]
    name: Optional[str] = None  # auto-assigned L1/L2/… if omitted
    # Optional bridge sequence supplied by the Connection Types tab's bridge
    # text box. When provided, it's stitched into the linker strand(s) after
    # topology creation: ss strand sequence = [comp_a, bridge, comp_b];
    # ds strand __a = [comp_a, bridge]; ds strand __b uses RC(bridge) so the
    # two halves pair on the virtual helix. Complement portions come from the
    # bound overhang sequence (RC), or N×L when the overhang has none.
    bridge_sequence: Optional[str] = None


class OverhangConnectionPatchRequest(BaseModel):
    name: Optional[str] = None
    length_value: Optional[float] = None
    length_unit: Optional[Literal["bp", "nm"]] = None
    # Sentinel-style update for the linker's bridge_sequence: omit the field
    # to leave it untouched; pass an empty string ("") to clear it; pass a
    # non-empty string to assign. Uppercased + stripped server-side; only
    # ACGTN characters survive.
    bridge_sequence: Optional[str] = None


@router.post("/design/overhang-connections", status_code=201)
def create_overhang_connection(body: OverhangConnectionCreateRequest) -> dict:
    """Append a new metadata-only OverhangConnection to the active design.

    Validates that both referenced overhangs exist, are distinct, and that the
    end-type / attach-type / linker-type combination is physically feasible.
    Does not modify any strand topology — purely a user-defined annotation.
    """
    from backend.core.lattice import (
        assign_overhang_connection_names,
        generate_linker_topology,
    )

    design = design_state.get_or_404()

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

    a_label = next(
        (o.label for o in design.overhangs if o.id == body.overhang_a_id),
        body.overhang_a_id[:10],
    )
    b_label = next(
        (o.label for o in design.overhangs if o.id == body.overhang_b_id),
        body.overhang_b_id[:10],
    )
    label = f"Linker {body.linker_type} {a_label}↔{b_label} ({body.length_value:g} {body.length_unit})"

    updated, report, _entry = design_state.mutate_with_feature_log(
        op_kind="linker-add",
        label=label,
        params=body.model_dump(mode="json"),
        fn=_fn,
    )
    return _design_response(updated, report)


@router.patch("/design/overhang-connections/{conn_id}", status_code=200)
def patch_overhang_connection(
    conn_id: str, body: OverhangConnectionPatchRequest
) -> dict:
    """Update name / length_value / length_unit on an existing connection.

    Changing length_value or length_unit auto-rebuilds the linker topology
    (the old strand(s) and virtual helix are stripped and regenerated against
    the new length). Other fields (overhangs, attach points, linker_type) are
    immutable through this endpoint — to change them, delete and re-create.
    """
    from backend.core.lattice import (
        generate_linker_topology,
        remove_linker_topology,
    )

    design = design_state.get_or_404()
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
    updated, report = design_state.replace_with_reconcile(updated, mreport)
    return _design_response(updated, report)


@router.delete("/design/overhang-connections/{conn_id}", status_code=200)
def delete_overhang_connection(conn_id: str) -> dict:
    """Remove a single OverhangConnection by id, plus its linker topology.

    Emits a `linker-delete` SnapshotLogEntry so the deletion shows up on the
    feature-log timeline alongside the linker's `linker-add` entry — keeps
    the Overhangs Manager and the feature log in sync (any change in either
    surface is visible in the timeline). Reverting the delete entry brings
    the linker back exactly as it was.
    """
    from backend.core.lattice import remove_linker_topology

    design = design_state.get_or_404()
    conn = next((c for c in design.overhang_connections if c.id == conn_id), None)
    if conn is None:
        raise HTTPException(404, detail=f"Overhang connection {conn_id!r} not found.")

    a_label = next(
        (o.label for o in design.overhangs if o.id == conn.overhang_a_id),
        conn.overhang_a_id[:10],
    )
    b_label = next(
        (o.label for o in design.overhangs if o.id == conn.overhang_b_id),
        conn.overhang_b_id[:10],
    )
    label = f"Delete linker {conn.name or conn.id[:8]} ({a_label}↔{b_label})"

    def _fn(d: Design) -> Design:
        new_list = [c for c in d.overhang_connections if c.id != conn_id]
        nxt = d.model_copy(update={"overhang_connections": new_list})
        return remove_linker_topology(nxt, conn_id)

    updated, report, _entry = design_state.mutate_with_feature_log(
        op_kind="linker-delete",
        label=label,
        params={
            "conn_id": conn_id,
            "linker_type": conn.linker_type,
            "overhang_a_id": conn.overhang_a_id,
            "overhang_b_id": conn.overhang_b_id,
        },
        fn=_fn,
    )
    return _design_response(updated, report)
