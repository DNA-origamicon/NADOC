"""Overhang structural actions, selected explicitly rather than inferred from labels."""

from fastapi import HTTPException
from backend.core.models import Design, Domain
from backend.api.part_binding_commands import ACTIONS as BINDING_ACTIONS
from backend.api.part_subdomain_commands import ACTIONS as SUBDOMAIN_ACTIONS

ACTIONS = (
    BINDING_ACTIONS
    | SUBDOMAIN_ACTIONS
    | frozenset(
        {
            "clear-all",
            "delete-selected",
            "convert-to-binder",
            "convert-to-scaffold",
            "generate-binder",
            "generate-sequences",
            "sub-domain-generate-random",
        }
    )
)


def delete_selected(design, body):
    from backend.api.crud import _delete_linker_connections_from_design
    from backend.core.binding_drivers import (
        apply_driver_to_joint as _apply_driver_to_joint,
        select_driver_for_joint as _select_driver_for_joint,
        first_claimant_for_joint as _first_claimant_for_joint,
    )
    from backend.core.lattice import _overhang_chain_descendants

    requested_ids = {oid for oid in body.overhang_ids if oid}
    existing_ids = {o.id for o in design.overhangs}
    target_ids = requested_ids & existing_ids
    if not target_ids:
        raise HTTPException(404, detail="No selected overhangs were found.")

    expanded_ids = set(target_ids)
    for oid in list(target_ids):
        expanded_ids.update(_overhang_chain_descendants(design, oid))

    def _build(d: Design) -> Design:
        conn_ids = {
            c.id
            for c in d.overhang_connections
            if c.overhang_a_id in expanded_ids or c.overhang_b_id in expanded_ids
        }
        out = _delete_linker_connections_from_design(d, conn_ids)
        remove_binding_ids = {
            b.id
            for b in out.overhang_bindings
            if b.overhang_a_id in expanded_ids or b.overhang_b_id in expanded_ids
        }
        bindings = list(out.overhang_bindings)
        affected_joint_ids = {
            b.target_joint_id
            for b in bindings
            if b.id in remove_binding_ids and b.target_joint_id is not None
        }
        fallback_windows: dict[str, tuple[float, float]] = {}
        for jid in affected_joint_ids:
            removed = [
                b
                for b in bindings
                if b.id in remove_binding_ids and b.target_joint_id == jid
            ]
            removed.sort(key=lambda b: (b.created_at, b.id))
            snapshot_src = next(
                (
                    b
                    for b in removed
                    if b.prior_min_angle_deg is not None
                    and b.prior_max_angle_deg is not None
                ),
                None,
            )
            if snapshot_src is None:
                continue
            fallback_windows[jid] = (
                snapshot_src.prior_min_angle_deg,
                snapshot_src.prior_max_angle_deg,
            )
            heirs = [
                b
                for b in bindings
                if b.id not in remove_binding_ids and b.target_joint_id == jid
            ]
            heirs.sort(key=lambda b: (b.created_at, b.id))
            if heirs:
                heir = heirs[0]
                if (
                    heir.prior_min_angle_deg is None
                    and heir.prior_max_angle_deg is None
                ):
                    new_heir = heir.model_copy(
                        update={
                            "prior_min_angle_deg": snapshot_src.prior_min_angle_deg,
                            "prior_max_angle_deg": snapshot_src.prior_max_angle_deg,
                        }
                    )
                    bindings = [new_heir if b.id == heir.id else b for b in bindings]

        def _domain_len(dm: Domain) -> int:
            return abs(int(dm.end_bp) - int(dm.start_bp)) + 1

        new_strands = []
        for strand in out.strands:
            new_domains = []
            seq_parts: list[str] = []
            seq_offset = 0
            has_exact_sequence = strand.sequence is not None and len(
                strand.sequence
            ) == sum(_domain_len(dm) for dm in strand.domains)
            for dm in strand.domains:
                n = _domain_len(dm)
                if dm.overhang_id in expanded_ids:
                    seq_offset += n
                    continue
                new_domains.append(dm)
                if has_exact_sequence:
                    seq_parts.append(strand.sequence[seq_offset : seq_offset + n])
                seq_offset += n
            if not new_domains:
                continue
            updates: dict = {"domains": new_domains}
            if has_exact_sequence:
                updates["sequence"] = "".join(seq_parts)
            new_strands.append(strand.model_copy(update=updates))

        covered_helix_ids = {
            dm.helix_id for strand in new_strands for dm in strand.domains
        }
        new_helices = [h for h in out.helices if h.id in covered_helix_ids]

        slot_cov: dict[str, list[tuple[int, int]]] = {}
        for strand in new_strands:
            for dm in strand.domains:
                key = f"{dm.helix_id}_{dm.direction}"
                lo = min(dm.start_bp, dm.end_bp)
                hi = max(dm.start_bp, dm.end_bp)
                slot_cov.setdefault(key, []).append((lo, hi))

        def _covered(helix_id: str, bp: int, direction: str) -> bool:
            return any(
                lo <= bp <= hi for lo, hi in slot_cov.get(f"{helix_id}_{direction}", [])
            )

        new_crossovers = [
            xo
            for xo in out.crossovers
            if _covered(xo.half_a.helix_id, xo.half_a.index, xo.half_a.strand)
            and _covered(xo.half_b.helix_id, xo.half_b.index, xo.half_b.strand)
        ]

        new_bindings = [b for b in bindings if b.id not in remove_binding_ids]
        new_overhangs = [o for o in out.overhangs if o.id not in expanded_ids]
        out = out.model_copy(
            update={
                "strands": new_strands,
                "helices": new_helices,
                "crossovers": new_crossovers,
                "overhangs": new_overhangs,
                "overhang_bindings": new_bindings,
            }
        )
        for jid in affected_joint_ids:
            out = _apply_driver_to_joint(out, jid)
            if (
                _select_driver_for_joint(out, jid) is None
                and _first_claimant_for_joint(out, jid) is None
            ):
                fallback = fallback_windows.get(jid)
                if fallback is not None:
                    min_angle, max_angle = fallback
                    out = out.model_copy(
                        update={
                            "cluster_joints": [
                                j.model_copy(
                                    update={
                                        "min_angle_deg": min_angle,
                                        "max_angle_deg": max_angle,
                                    }
                                )
                                if j.id == jid
                                else j
                                for j in out.cluster_joints
                            ],
                        }
                    )
        return out

    return _build(design)


def clear(design):
    def _build(d: Design) -> Design:
        new_strands = [
            s.model_copy(
                update={
                    "domains": [
                        dm.model_copy(update={"overhang_id": None}) for dm in s.domains
                    ]
                }
            )
            for s in d.strands
        ]
        return d.model_copy(update={"strands": new_strands, "overhangs": []})

    return _build(design)


def generated_sequence(design, oid, sequence, *, boundaries=False, sub_domain_id=None):
    from backend.api.crud import (
        _find_ovhg_or_404,
        _replace_ovhg,
        _compute_sub_domain_annotations,
    )
    from backend.core.overhang_sequence_screen import OverhangSequenceScreen
    from backend.core.overhang_ops import (
        _apply_boundary_hairpin_warnings,
        _ovhg_domain_lengths,
    )

    spec = _find_ovhg_or_404(design, oid)
    if len(sequence) != _ovhg_domain_lengths(design).get(oid) or any(
        base not in "ACGTN" for base in sequence
    ):
        raise ValueError("Selected sequence no longer matches its overhang")
    if sub_domain_id:
        sd = next((s for s in spec.sub_domains if s.id == sub_domain_id), None)
        if sd is None:
            raise ValueError("Missing subdomain sequence target")
        override = sequence[sd.start_bp_offset : sd.start_bp_offset + sd.length_bp]
        ann = _compute_sub_domain_annotations(
            override, na_mM=design.tm_settings.na_mM, conc_nM=design.tm_settings.conc_nM
        )
        spec = spec.model_copy(
            update={
                "sub_domains": [
                    s.model_copy(update={"sequence_override": override, **ann})
                    if s.id == sd.id
                    else s
                    for s in spec.sub_domains
                ]
            }
        )
        design = _replace_ovhg(design, spec)
    updated = OverhangSequenceScreen(design, spec).apply(sequence)
    return _apply_boundary_hairpin_warnings(updated, oid) if boundaries else updated


def build(design, params):
    from backend.api import crud
    from backend.core.lattice import (
        convert_strand_to_binder,
        convert_binder_to_scaffold,
        make_binder_for_overhang,
    )

    action = params["action"]
    if action in BINDING_ACTIONS:
        from backend.api.part_binding_commands import build as binding

        return binding(design, params)
    if action in SUBDOMAIN_ACTIONS:
        from backend.api.part_subdomain_commands import build as subdomain

        return subdomain(design, params)
    if action == "clear-all":
        return clear(design)
    if action == "delete-selected":
        return delete_selected(
            design, crud.OverhangBatchDeleteRequest.model_validate(params)
        )
    if action == "convert-to-binder":
        return convert_strand_to_binder(design, params["strand_id"])
    if action == "convert-to-scaffold":
        return convert_binder_to_scaffold(design, params["strand_id"])
    if action == "generate-binder":
        return make_binder_for_overhang(
            design, params["overhang_id"], strand_id=params["_strand_id"]
        )
    if action == "generate-sequences":
        for oid, sequence in params["sequences"].items():
            design = generated_sequence(design, oid, sequence)
        return design
    if action == "sub-domain-generate-random":
        return generated_sequence(
            design,
            params["overhang_id"],
            params["sequence"],
            boundaries=True,
            sub_domain_id=params["sub_domain_id"],
        )
    raise NotImplementedError(action)
