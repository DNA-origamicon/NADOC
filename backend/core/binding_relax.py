"""Bind-topology solver for OverhangBinding records.

When the user flips an OverhangBinding's ``bound`` flag from False → True,
the driven overhang's strand domain is **relocated** onto the driver's
helix, sharing the driver's OH bp range with opposite direction —
mirroring the linker complement-domain pattern. The driven helix is
deleted (no strand references it any more); on unbind it is recreated
from a snapshot stored on the binding.

This replaces the earlier cluster-pose-move approach. The new geometry is
"free" because the driven OH's domain literally lives on the driver's
helix now, so it inherits the driver's cluster transform natively.

Public entry point:

    compute_bind_topology(design, binding) -> BindTopology

  Raises ``HTTPException(422)`` for unsupported configurations:
   * same cluster on both sides (no relocation makes sense);
   * neither overhang is in any cluster;
   * either OH's strand domain cannot be located.

For backwards compatibility with the Phase-5 joint-lock path, this module
also exposes ``compute_locked_angle(design, binding, geometry)`` (1-DOF
joint angle for the bound duplex pose) — used by the PATCH endpoint to
collapse ``ClusterJoint.min_angle_deg = max_angle_deg = locked`` when the
two clusters are connected by exactly one joint.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

import numpy as np
from fastapi import HTTPException

from backend.core.linker_relax import (
    _optimize_angle,
    _overhang_owning_cluster_id,
)
from backend.core.models import (
    Crossover,
    Design,
    Direction,
    Domain,
    ForcedLigation,
    Helix,
    OverhangBinding,
    Strand,
    _local_to_world_joint,
)


# ── Result payload ──────────────────────────────────────────────────────────

@dataclass
class BindTopology:
    """Result of compute_bind_topology.

    Describes the surgical edit to apply on bind:
      * Move ``strands[strand_id].domains[domain_index]`` to
        ``(target_helix_id, target_start_bp..target_end_bp, target_direction)``.
      * Move ``OverhangSpec[driven_oh_id].helix_id`` to ``target_helix_id``.
      * Remove the driven helix from ``design.helices``.
      * Remove or rewrite crossovers that reference the driven helix.

    Plus a snapshot dict that ``OverhangBinding.prior_driven_topology``
    persists for unbind restoration.
    """
    driver_oh_id: str
    driven_oh_id: str
    driver_side: str  # 'a' or 'b'
    strand_id: str
    domain_index: int
    target_helix_id: str
    target_start_bp: int
    target_end_bp: int
    target_direction: 'Direction'
    snapshot: Dict[str, Any]
    # ForcedLigation that REPLACES the relocated overhang-extrude crossover (the
    # root↔tip backbone bond). After relocation the crossover's halves sit on
    # non-adjacent helices at mismatched bp — an INVALID lattice crossover — so the
    # bond is represented as a ForcedLigation (drawn correctly in 3D + cadnano).
    # None for the legacy single-domain / no-crossover case (keeps the rewrite path).
    forced_ligation: Optional['ForcedLigation'] = None


# ── Helpers ─────────────────────────────────────────────────────────────────


def _sub_domain_junction_anchor(
    design: Design,
    sub_domain_id: str,
    nucs: list[dict],
) -> tuple[np.ndarray | None, np.ndarray | None, str | None]:
    """Return (anchor_position, base_normal, parent_overhang_id) for the bp
    at the JUNCTION-side end of *sub_domain_id*. Used by the legacy 1-DOF
    locked-angle path."""
    parent_ovhg = None
    target_sd = None
    for ovhg in design.overhangs:
        for sd in ovhg.sub_domains:
            if sd.id == sub_domain_id:
                parent_ovhg = ovhg
                target_sd = sd
                break
        if parent_ovhg is not None:
            break
    if parent_ovhg is None or target_sd is None:
        return None, None, None

    oh_nucs = [n for n in nucs if n.get("overhang_id") == parent_ovhg.id]
    if not oh_nucs:
        return None, None, parent_ovhg.id

    oh_sorted = sorted(oh_nucs, key=lambda n: n.get("bp_index") or 0)
    idx = max(0, min(len(oh_sorted) - 1, target_sd.start_bp_offset))
    nuc = oh_sorted[idx]
    pos = nuc.get("backbone_position") or nuc.get("base_position")
    bn = nuc.get("base_normal")
    return (
        np.asarray(pos, dtype=float) if pos is not None else None,
        np.asarray(bn, dtype=float) if bn is not None else None,
        parent_ovhg.id,
    )


def _resolve_driver_side(
    design: Design,
    binding: OverhangBinding,
    cluster_a: Optional[str],
    cluster_b: Optional[str],
) -> str:
    """Driver = the side WHOSE HELIX STAYS. Convention:
    if exactly one side's cluster has joints → the joint-free side is the
    driver (its anchor doesn't move). Both- or neither-joints → side A is
    the driver. The driven side's domain relocates onto the driver's helix
    and the driven helix is removed."""
    has_joint_a = any(
        j.cluster_id == cluster_a for j in design.cluster_joints
    ) if cluster_a is not None else False
    has_joint_b = any(
        j.cluster_id == cluster_b for j in design.cluster_joints
    ) if cluster_b is not None else False
    if has_joint_a and not has_joint_b:
        return 'b'
    if has_joint_b and not has_joint_a:
        return 'a'
    return 'a'


def _find_oh_strand_and_domain(
    design: Design,
    overhang_id: str,
) -> tuple[Strand, int, Domain]:
    """Return (strand, domain_index, domain) for the strand domain tagged
    with ``overhang_id``. Raises HTTPException(422) if not found."""
    for strand in design.strands:
        for i, dom in enumerate(strand.domains):
            if dom.overhang_id == overhang_id:
                return strand, i, dom
    raise HTTPException(422, detail=(
        f"OverhangBinding: no strand domain has overhang_id={overhang_id!r}; "
        f"the overhang may be malformed or already relocated."
    ))


def _crossovers_on_helix(
    design: Design,
    helix_id: str,
) -> list[tuple[int, Crossover]]:
    """Return (index, crossover) pairs for crossovers touching *helix_id*."""
    return [
        (i, xo) for i, xo in enumerate(design.crossovers)
        if xo.half_a.helix_id == helix_id or xo.half_b.helix_id == helix_id
    ]


def _half_in_range(half, helix_id: str, lo: int, hi: int) -> bool:
    """True iff `half` sits on `helix_id` at a bp index inside [lo, hi].
    Used to scope crossover rewriting to a SINGLE overhang's bp range when
    the underlying helix may host multiple overhangs."""
    return (
        half.helix_id == helix_id
        and lo <= int(half.index) <= hi
    )


# ── Public entry point — topology relocation ────────────────────────────────


def compute_bind_topology(
    design: Design,
    binding: OverhangBinding,
    *,
    driver_side: Optional[str] = None,
    target_start_override: Optional[int] = None,
    target_end_override: Optional[int] = None,
) -> BindTopology:
    """Describe the topology edit for binding *binding*.

    Resolves driver/driven, locates the driven OH's strand domain, and
    returns the relocation target + a snapshot blob (driven helix +
    pre-bind domain values + affected crossovers) that the caller persists
    on ``binding.prior_driven_topology`` so unbind can restore.

    ``driver_side`` ('a' | 'b') forces which overhang HOSTS the duplex,
    overriding the joint heuristic. The unified direct-apply path passes the
    attach-derived driver (end-to-root → A hosts); the legacy root-to-root
    bound-toggle leaves it ``None`` to keep the heuristic. When forced, the
    same-cluster guard is relaxed — relocation is a pure topology move that is
    valid even within one rigid body (the later relax just becomes swing-only).

    Raises ``HTTPException(422)`` when:
      * either overhang is unrouted (not on any cluster);
      * both overhangs share a cluster AND ``driver_side`` is None (heuristic
        path — relocation target would be ambiguous);
      * a strand-domain anchor for either OH cannot be found.
    """
    # Find the two OHs.
    oh_a = next((o for o in design.overhangs if o.id == binding.overhang_a_id), None)
    oh_b = next((o for o in design.overhangs if o.id == binding.overhang_b_id), None)
    if oh_a is None or oh_b is None:
        raise HTTPException(422, detail=(
            f"OverhangBinding {binding.id}: overhangs do not resolve."
        ))

    # Cluster checks only constrain the HEURISTIC driver pick. When the caller
    # forces ``driver_side`` (the unified direct-apply path), relocation is a pure
    # topology move — valid with no clusters or a single shared cluster — so we skip
    # them entirely.
    if driver_side not in ('a', 'b'):
        cluster_a = _overhang_owning_cluster_id(design, oh_a.id)
        cluster_b = _overhang_owning_cluster_id(design, oh_b.id)
        if cluster_a is None or cluster_b is None:
            raise HTTPException(422, detail=(
                "Binding endpoints are not owned by any cluster — bind requires "
                "both overhangs to be in clusters."
            ))
        if cluster_a == cluster_b:
            raise HTTPException(422, detail=(
                "Binding spans a single rigid body — both overhangs sit on the "
                "same cluster, so no relocation is possible."
            ))
        driver_side = _resolve_driver_side(design, binding, cluster_a, cluster_b)
    driver_oh = oh_a if driver_side == 'a' else oh_b
    driven_oh = oh_b if driver_side == 'a' else oh_a

    # Locate the driver's OH domain — sets the target (helix + bp range).
    driver_strand, driver_di, driver_dom = _find_oh_strand_and_domain(design, driver_oh.id)
    driven_strand, driven_di, driven_dom = _find_oh_strand_and_domain(design, driven_oh.id)

    target_helix_id = driver_dom.helix_id
    # Antiparallel pairing — flip the direction AND swap start/end. The
    # relocated strand traverses the SAME bp range as the driver but in
    # the opposite 5'→3' order. NADOC's Domain convention encodes 5'→3'
    # traversal via (start_bp, end_bp) plus `direction`:
    #
    #   FORWARD : start_bp < end_bp  (5' at start_bp, 3' at end_bp,
    #                                 strand goes through +bp axis)
    #   REVERSE : start_bp > end_bp  (5' at start_bp, 3' at end_bp,
    #                                 strand goes through −bp axis)
    #
    # So flipping direction alone (without swapping start/end) produces
    # an inconsistent domain (e.g. FORWARD with start > end) — the
    # renderer can't locate the 5' nucleotide reliably and crossover-bp
    # mapping lands at the wrong end of the OH. The swap restores the
    # invariant.
    target_direction = (
        Direction.REVERSE if driver_dom.direction == Direction.FORWARD
        else Direction.FORWARD
    )
    target_start_bp = driver_dom.end_bp
    target_end_bp = driver_dom.start_bp
    # DIFFERENT-length duplex: relocate the driven's whole domain onto only the
    # driver's PAIRED-WINDOW bp range (from the duplex register), not the driver's
    # full domain — so a short driven doesn't get stretched to the long driver's
    # length. Caller passes the window (already the antiparallel start/end).
    if target_start_override is not None and target_end_override is not None:
        target_start_bp = target_start_override
        target_end_bp = target_end_override

    # Snapshot the driven side's pre-bind topology for unbind restoration.
    driven_helix = next((h for h in design.helices if h.id == driven_oh.helix_id), None)
    if driven_helix is None:
        raise HTTPException(422, detail=(
            f"OverhangBinding {binding.id}: driven OH helix "
            f"{driven_oh.helix_id!r} not found."
        ))
    driven_helix_dict = driven_helix.model_dump(mode='json')

    # Crossovers whose half lies on the driven OH helix *within the
    # driven OH's bp range* — snapshot for unbind, rewrite on bind. We
    # explicitly do NOT include crossovers that touch the helix at bps
    # OUTSIDE the OH's range, because the OH helix may host MULTIPLE
    # overhangs (e.g. an OH-5p at bp 199 and an OH-3p at bp 200 share
    # one extruded helix). Each OH owns its own crossover at its own bp;
    # binding ONE of those OHs must not relocate the OTHER's crossover.
    lo = min(driven_dom.start_bp, driven_dom.end_bp)
    hi = max(driven_dom.start_bp, driven_dom.end_bp)
    xover_snapshots = [
        xo.model_dump(mode='json')
        for _i, xo in _crossovers_on_helix(design, driven_helix.id)
        if _half_in_range(xo.half_a, driven_helix.id, lo, hi)
        or _half_in_range(xo.half_b, driven_helix.id, lo, hi)
    ]

    snapshot: Dict[str, Any] = {
        "driver_oh_id": driver_oh.id,
        "driven_oh_id": driven_oh.id,
        "driven_helix": driven_helix_dict,
        "strand_id": driven_strand.id,
        "domain_index": driven_di,
        "prior_domain": {
            "helix_id": driven_dom.helix_id,
            "start_bp": driven_dom.start_bp,
            "end_bp": driven_dom.end_bp,
            "direction": driven_dom.direction.value,
        },
        "prior_ovhg_helix_id": driven_oh.helix_id,
        "crossovers": xover_snapshots,
    }

    # ForcedLigation for the relocated root↔tip junction. When the driven overhang
    # is a multi-domain (root → tip) staple AND it actually carries an overhang-
    # extrude crossover, relocation moves the tip onto the driver's (non-adjacent)
    # helix at the driver's bp range — so the old crossover would become an INVALID
    # lattice crossover (mismatched bp / non-adjacent helices). Represent the bond
    # as a ForcedLigation instead (3'→5' in strand order: earlier domain's end → later
    # domain's start), mirroring the convention POST /design/forced-ligation uses.
    relocate_fl = None
    n_dom = len(driven_strand.domains)
    if n_dom >= 2 and xover_snapshots:
        is_tip_last = driven_di == n_dom - 1
        root_dom = (driven_strand.domains[driven_di - 1] if is_tip_last
                    else driven_strand.domains[driven_di + 1])
        if is_tip_last:
            relocate_fl = ForcedLigation(
                three_prime_helix_id=root_dom.helix_id, three_prime_bp=root_dom.end_bp,
                three_prime_direction=root_dom.direction,
                five_prime_helix_id=target_helix_id, five_prime_bp=target_start_bp,
                five_prime_direction=target_direction)
        else:
            relocate_fl = ForcedLigation(
                three_prime_helix_id=target_helix_id, three_prime_bp=target_end_bp,
                three_prime_direction=target_direction,
                five_prime_helix_id=root_dom.helix_id, five_prime_bp=root_dom.start_bp,
                five_prime_direction=root_dom.direction)
        snapshot["forced_ligation"] = relocate_fl.model_dump(mode="json")

    return BindTopology(
        driver_oh_id=driver_oh.id,
        driven_oh_id=driven_oh.id,
        driver_side=driver_side,
        strand_id=driven_strand.id,
        domain_index=driven_di,
        target_helix_id=target_helix_id,
        target_start_bp=target_start_bp,
        target_end_bp=target_end_bp,
        target_direction=target_direction,
        snapshot=snapshot,
        forced_ligation=relocate_fl,
    )


def apply_bind_topology(design: Design, topology: BindTopology) -> Design:
    """Apply the surgical topology edit described by *topology*. Pure
    function — returns a new Design."""
    # 1) Rewrite the driven strand's domain to point at the driver helix.
    new_strands: list[Strand] = []
    for strand in design.strands:
        if strand.id != topology.strand_id:
            new_strands.append(strand)
            continue
        new_doms = list(strand.domains)
        old = new_doms[topology.domain_index]
        new_doms[topology.domain_index] = old.model_copy(update={
            "helix_id": topology.target_helix_id,
            "start_bp": topology.target_start_bp,
            "end_bp": topology.target_end_bp,
            "direction": topology.target_direction,
        })
        new_strands.append(strand.model_copy(update={"domains": new_doms}))

    # 2) Update the driven OverhangSpec.helix_id.
    new_overhangs = []
    for oh in design.overhangs:
        if oh.id == topology.driven_oh_id:
            new_overhangs.append(oh.model_copy(update={
                "helix_id": topology.target_helix_id,
            }))
        else:
            new_overhangs.append(oh)

    # 3) Delete the driven helix — but ONLY if no other strand domain
    #    still references it. One extruded OH helix can host multiple
    #    overhangs (e.g. OH-5p at bp 199 and OH-3p at bp 200 share one
    #    helix); binding ONE of them must not delete a helix the OTHER
    #    still occupies. We check against the NEW strands list (after
    #    step 1 rewrote the driven OH's domain off the helix) so the
    #    driven OH's own domain doesn't count as a remaining reference.
    driven_helix_id = topology.snapshot["prior_ovhg_helix_id"]
    still_referenced = any(
        dom.helix_id == driven_helix_id
        for strand in new_strands
        for dom in strand.domains
    )
    if still_referenced:
        new_helices = list(design.helices)
    else:
        new_helices = [h for h in design.helices if h.id != driven_helix_id]

    # 4) The relocated tip's overhang-extrude crossover(s) — those whose half lies
    #    on the driven helix WITHIN the driven OH's bp range. After relocation the
    #    tip sits on the driver's (non-adjacent) helix at a different bp, so the old
    #    crossover would be an INVALID lattice crossover.
    #
    #    * Multi-domain driven staple (a root↔tip junction exists) → DROP those
    #      crossovers and add the ForcedLigation that represents the same backbone
    #      bond (drawn correctly in 3D + cadnano). This is what the old end-to-root
    #      splice did, generalized to every direct relocation.
    #    * Legacy single-domain / no-FL case → fall back to the original rewrite
    #      (preserves the crossover record + its id).
    #
    #    SCOPE: crossovers OUTSIDE the OH's bp range are left untouched even when
    #    their half is on the same OH helix — one extruded helix may host MULTIPLE
    #    overhangs; binding just ONE must not touch the OTHER's crossover.
    prior_domain = topology.snapshot["prior_domain"]
    prior_lo = min(int(prior_domain["start_bp"]), int(prior_domain["end_bp"]))
    prior_hi = max(int(prior_domain["start_bp"]), int(prior_domain["end_bp"]))

    def _in_oh_range(xo: Crossover) -> bool:
        return (_half_in_range(xo.half_a, driven_helix_id, prior_lo, prior_hi)
                or _half_in_range(xo.half_b, driven_helix_id, prior_lo, prior_hi))

    new_forced = list(design.forced_ligations)
    if topology.forced_ligation is not None:
        new_crossovers = [xo for xo in design.crossovers if not _in_oh_range(xo)]
        new_forced.append(topology.forced_ligation)
    else:
        new_crossovers = []
        for xo in design.crossovers:
            new_ha = xo.half_a
            new_hb = xo.half_b
            if _half_in_range(xo.half_a, driven_helix_id, prior_lo, prior_hi):
                new_ha = _rewrite_half_to_driver(xo.half_a, driven_helix_id, topology, prior_domain)
            if _half_in_range(xo.half_b, driven_helix_id, prior_lo, prior_hi):
                new_hb = _rewrite_half_to_driver(xo.half_b, driven_helix_id, topology, prior_domain)
            if new_ha is xo.half_a and new_hb is xo.half_b:
                new_crossovers.append(xo)
            else:
                new_crossovers.append(xo.model_copy(update={"half_a": new_ha, "half_b": new_hb}))

    return design.model_copy(update={
        "strands": new_strands,
        "overhangs": new_overhangs,
        "helices": new_helices,
        "crossovers": new_crossovers,
        "forced_ligations": new_forced,
    })


def _rewrite_half_to_driver(
    half,
    driven_helix_id: str,
    topology: BindTopology,
    prior_domain: Dict[str, Any],
):
    """If `half` was on the driven helix, return a new HalfCrossover
    pointing at the driver helix at the corresponding bp on the relocated
    domain. Otherwise return `half` unchanged (identity-preserving).
    """
    if half.helix_id != driven_helix_id:
        return half
    # Map old index to relocated bp by matching which end of the prior
    # domain it was at. (Crossovers placed by make_overhang_extrude sit at
    # one bp end of the OH's domain.) Fall back to proportional mapping if
    # the old index isn't at either named endpoint.
    prior_start = int(prior_domain["start_bp"])
    prior_end   = int(prior_domain["end_bp"])
    target_start = topology.target_start_bp
    target_end   = topology.target_end_bp
    if half.index == prior_end:
        new_index = target_end
    elif half.index == prior_start:
        new_index = target_start
    else:
        prior_lo = min(prior_start, prior_end)
        prior_hi = max(prior_start, prior_end)
        target_lo = min(target_start, target_end)
        target_hi = max(target_start, target_end)
        if prior_hi == prior_lo:
            new_index = target_lo
        else:
            frac = (half.index - prior_lo) / (prior_hi - prior_lo)
            new_index = int(round(target_lo + frac * (target_hi - target_lo)))
    return half.model_copy(update={
        "helix_id": topology.target_helix_id,
        "index":    new_index,
        "strand":   topology.target_direction,
    })


def revert_bind_topology(design: Design, snapshot: Dict[str, Any]) -> Design:
    """Reverse a bind by restoring the driven helix + the OH's domain +
    crossovers from *snapshot*. Pure function — returns a new Design."""
    if not snapshot:
        return design

    # 1) Recreate the driven helix.
    driven_helix = Helix.model_validate(snapshot["driven_helix"])
    # Idempotency: if a helix with this id already exists, don't double-add.
    if not any(h.id == driven_helix.id for h in design.helices):
        new_helices = list(design.helices) + [driven_helix]
    else:
        new_helices = list(design.helices)

    # 2) Restore the driven strand's domain to its pre-bind state.
    prior_dom = snapshot["prior_domain"]
    target_strand_id = snapshot["strand_id"]
    target_domain_index = snapshot["domain_index"]
    new_strands: list[Strand] = []
    for strand in design.strands:
        if strand.id != target_strand_id:
            new_strands.append(strand)
            continue
        new_doms = list(strand.domains)
        if 0 <= target_domain_index < len(new_doms):
            old = new_doms[target_domain_index]
            new_doms[target_domain_index] = old.model_copy(update={
                "helix_id": prior_dom["helix_id"],
                "start_bp": prior_dom["start_bp"],
                "end_bp":   prior_dom["end_bp"],
                "direction": Direction(prior_dom["direction"]),
            })
        new_strands.append(strand.model_copy(update={"domains": new_doms}))

    # 3) Restore the driven OverhangSpec.helix_id, and zero the DRIVER's midpoint
    #    placement (rotation + translation). Apply seated the duplex like a bridge by
    #    writing BOTH onto the driver; they only positioned the now-reverted duplex, so
    #    leaving them stale would leave the driver overhang rotated/shifted with no
    #    duplex. (Direct connections start from an un-rotated overhang, so resetting to
    #    identity restores the pre-apply pose.)
    prior_ovhg_helix_id = snapshot["prior_ovhg_helix_id"]
    driver_oh_id = snapshot.get("driver_oh_id")
    new_overhangs = []
    for oh in design.overhangs:
        if oh.id == snapshot["driven_oh_id"]:
            new_overhangs.append(oh.model_copy(update={
                "helix_id": prior_ovhg_helix_id,
            }))
        elif oh.id == driver_oh_id:
            new_overhangs.append(oh.model_copy(update={
                "rotation": [0.0, 0.0, 0.0, 1.0],
                "translation": [0.0, 0.0, 0.0],
            }))
        else:
            new_overhangs.append(oh)

    # 4) Restore crossovers that we REWROTE on bind. Each snapshot entry
    #    carries the original `id`, so we look up the live crossover by id
    #    and replace it with the snapshotted (pre-bind) shape. If a
    #    snapshotted crossover is missing from the live design (e.g. user
    #    deleted it while bound), append it defensively.
    snapshot_xovers_by_id: Dict[str, Crossover] = {}
    for xo_dict in snapshot.get("crossovers", []):
        xo = Crossover.model_validate(xo_dict)
        snapshot_xovers_by_id[xo.id] = xo
    restored_xovers = []
    for xo in design.crossovers:
        if xo.id in snapshot_xovers_by_id:
            restored_xovers.append(snapshot_xovers_by_id.pop(xo.id))
        else:
            restored_xovers.append(xo)
    # Any snapshot crossovers not matched above get appended. (On a multi-domain
    # bind the crossover was DROPPED in favour of a ForcedLigation, so its snapshot
    # entry lands here.)
    for sxo in snapshot_xovers_by_id.values():
        restored_xovers.append(sxo)

    # 5) Remove the relocate ForcedLigation we added on bind (if any), so unbind
    #    restores the pre-bind topology exactly.
    new_forced = design.forced_ligations
    fl_dict = snapshot.get("forced_ligation")
    if fl_dict is not None:
        fl_id = fl_dict.get("id")
        new_forced = [fl for fl in design.forced_ligations if fl.id != fl_id]

    # Drop the auto-created duplex CLUSTER for this driver — the pose it carried is being
    # torn down with the binding (the driver OverhangSpec was reset to identity above).
    # [[overhang-duplex-cluster]] P1b.
    driver = snapshot.get("driver_oh_id")
    new_clusters = [c for c in design.cluster_transforms
                    if c.overhang_duplex_driver_id != driver] if driver else design.cluster_transforms

    return design.model_copy(update={
        "helices": new_helices,
        "strands": new_strands,
        "overhangs": new_overhangs,
        "crossovers": restored_xovers,
        "forced_ligations": new_forced,
        "cluster_transforms": new_clusters,
    })


# ── Backwards-compatible 1-DOF joint-angle path ─────────────────────────────


def compute_locked_angle(
    design: Design,
    binding: OverhangBinding,
    geometry: list[dict],
) -> float:
    """Phase-5 path preserved: return the joint angle (in DEGREES) that
    closes the bound duplex chord, for the 1-DOF case.

    Used by the PATCH endpoint to collapse ``ClusterJoint.min_angle_deg =
    max_angle_deg = locked`` so the joint can't be dragged out of the
    bound pose by gizmo / animation.

    Raises ``HTTPException(422)`` for 0-DOF or N-DOF cases — those callers
    should rely on topology relocation alone (no joint lock applies).
    """
    sd_lookup: dict[str, tuple[Any, Any]] = {}
    for ovhg in design.overhangs:
        for sd in ovhg.sub_domains:
            sd_lookup[sd.id] = (ovhg, sd)
    res_a = sd_lookup.get(binding.sub_domain_a_id)
    res_b = sd_lookup.get(binding.sub_domain_b_id)
    if res_a is None or res_b is None:
        raise HTTPException(422, detail=(
            f"OverhangBinding {binding.id}: sub_domains do not resolve."
        ))
    ovhg_a, sd_a = res_a
    ovhg_b, sd_b = res_b
    cluster_a = _overhang_owning_cluster_id(design, ovhg_a.id)
    cluster_b = _overhang_owning_cluster_id(design, ovhg_b.id)
    if cluster_a is None or cluster_b is None:
        raise HTTPException(422, detail=(
            "Binding endpoints are not owned by any cluster."
        ))
    if cluster_a == cluster_b:
        raise HTTPException(422, detail=(
            "Binding spans a single rigid body."
        ))

    candidates = [
        j for j in design.cluster_joints
        if j.cluster_id == cluster_a or j.cluster_id == cluster_b
    ]
    if binding.target_joint_id is not None:
        candidates = [j for j in candidates if j.id == binding.target_joint_id]
    if not candidates:
        raise HTTPException(422, detail=(
            "compute_locked_angle: no joints between the two clusters "
            "(0-DOF binding has no joint to lock)."
        ))
    if len(candidates) > 1:
        raise HTTPException(422, detail=(
            "compute_locked_angle: N-DOF binding (multiple joints) has no "
            "single angle to lock."
        ))
    joint = candidates[0]

    cts_by_id = {c.id: c for c in design.cluster_transforms}
    ct = cts_by_id.get(joint.cluster_id)
    world_origin, world_dir = _local_to_world_joint(
        joint.local_axis_origin, joint.local_axis_direction, ct,
    )
    axis = np.asarray(world_dir, dtype=float)
    norm = float(np.linalg.norm(axis))
    if norm < 1e-9:
        raise HTTPException(422, detail=(
            f"Joint {joint.id} axis is degenerate."
        ))
    axis = axis / norm
    origin = np.asarray(world_origin, dtype=float)

    p_a, n_a, _ = _sub_domain_junction_anchor(design, binding.sub_domain_a_id, geometry)
    p_b, n_b, _ = _sub_domain_junction_anchor(design, binding.sub_domain_b_id, geometry)
    if p_a is None or p_b is None:
        raise HTTPException(422, detail=(
            "Could not resolve sub-domain anchor positions from geometry."
        ))

    moving_is_a = (joint.cluster_id == cluster_a)
    moving_anchor = p_a if moving_is_a else p_b
    moving_normal = n_a if moving_is_a else n_b
    fixed_anchor = p_b if moving_is_a else p_a
    fixed_normal = n_b if moving_is_a else n_a

    base_count = max(1, int(sd_a.length_bp))
    theta_min = float(joint.min_angle_deg) * np.pi / 180.0
    theta_max = float(joint.max_angle_deg) * np.pi / 180.0
    theta_rad = _optimize_angle(
        moving_anchor, moving_normal,
        fixed_anchor, fixed_normal,
        moving_is_a, origin, axis, base_count,
        True, True,
        theta_min=theta_min, theta_max=theta_max,
    )
    return float(theta_rad * 180.0 / np.pi)
