"""Proposal-B overhang **Duplex** helpers (Phase 0).

A :class:`~backend.core.models.Duplex` is a register-bearing hybridization edge
between two overhang stretches, expressed in helix bp coordinates (see
``memory/project_overhang_duplex_foundation.md``). Phase 0 ships only:

  * coordinate conversion (overhang 5'→3' offset ↔ helix bp), mirroring
    ``backend.core.sequences``;
  * ``synthesize_duplexes_from_bindings`` — a STANDALONE migration from the
    legacy :class:`~backend.core.models.OverhangBinding` records. It is NOT wired
    into load yet (keeping Phase 0 behavior-neutral); later phases invoke it.

The per-base Watson-Crick classifier (paired / mismatch / unpaired) lands in
Phase 1 alongside the CRUD router.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from backend.core.models import (
    Design, Domain, Duplex, DuplexEnd, OverhangBinding, SubDomain,
    _overhang_backing_domain,
)

_COMPLEMENT = {'A': 'T', 'T': 'A', 'C': 'G', 'G': 'C'}


def offset_to_bp(domain: Domain, offset: int) -> int:
    """Helix bp of the overhang base at 5'→3' ``offset`` (0 = 5' base).

    Mirrors ``backend.core.sequences``' overhang mapping exactly:
    ``bp = domain.start_bp + offset * sign(domain.end_bp - domain.start_bp)``.
    """
    step = 1 if domain.end_bp >= domain.start_bp else -1
    return domain.start_bp + offset * step


def bp_to_offset(domain: Domain, bp: int) -> int:
    """Inverse of :func:`offset_to_bp` — 5'→3' offset of a helix ``bp``."""
    step = 1 if domain.end_bp >= domain.start_bp else -1
    return (bp - domain.start_bp) * step


def subdomain_end(domain: Domain, sub_domain: SubDomain, length: int,
                  overhang_id: str) -> DuplexEnd:
    """Build a :class:`DuplexEnd` covering ``length`` bases of ``sub_domain``,
    starting at its 5' base. ``start_bp`` is the 5' base, ``end_bp`` the 3' base
    (order encodes polarity)."""
    start_bp = offset_to_bp(domain, sub_domain.start_bp_offset)
    end_bp = offset_to_bp(domain, sub_domain.start_bp_offset + length - 1)
    return DuplexEnd(overhang_id=overhang_id, start_bp=start_bp, end_bp=end_bp)


def _driver_side(binding: OverhangBinding) -> str:
    """Map a legacy binding's ``driver_oh_id`` onto the Duplex ``left``/``right``
    axis. Defaults to ``'left'`` when the binding predates the field."""
    if binding.driver_oh_id and binding.driver_oh_id == binding.overhang_b_id:
        return 'right'
    return 'left'


def synthesize_duplexes_from_bindings(design: Design) -> List[Duplex]:
    """Convert every legacy :class:`OverhangBinding` into an equivalent
    :class:`Duplex`. Pure — returns a new list, does not mutate ``design``.

    Each binding pairs one sub-domain of overhang A with one of overhang B. The
    duplex length is the (equal, by the old invariant) sub-domain length; ``min``
    is used defensively. Bindings whose sub-domains no longer resolve are skipped
    (a stale binding is harmless, matching the load validators' leniency).
    """
    sd_lookup: dict[str, tuple[str, SubDomain]] = {}
    for ovhg in design.overhangs:
        for sd in ovhg.sub_domains:
            sd_lookup[sd.id] = (ovhg.id, sd)

    out: List[Duplex] = []
    for i, b in enumerate(design.overhang_bindings):
        res_a = sd_lookup.get(b.sub_domain_a_id)
        res_b = sd_lookup.get(b.sub_domain_b_id)
        if res_a is None or res_b is None:
            continue
        oid_a, sd_a = res_a
        oid_b, sd_b = res_b
        _, dom_a = _overhang_backing_domain(design, oid_a)
        _, dom_b = _overhang_backing_domain(design, oid_b)
        if dom_a is None or dom_b is None:
            continue
        length = min(sd_a.length_bp, sd_b.length_bp)
        if length <= 0:
            continue
        out.append(Duplex(
            name=b.name or f"D{i + 1}",
            created_at=b.created_at,
            left=subdomain_end(dom_a, sd_a, length, oid_a),
            right=subdomain_end(dom_b, sd_b, length, oid_b),
            driver=_driver_side(b),
            bound=b.bound,
            binding_mode=b.binding_mode,
            allow_n_wildcard=b.allow_n_wildcard,
            target_joint_id=b.target_joint_id,
            locked_angle_deg=b.locked_angle_deg,
            connection_type=b.connection_type,
        ))
    return out


# ── Phase 1: per-base pairing classifier + coverage (the display/oracle read) ──

def _wc_base(a: Optional[str], b: Optional[str], allow_n: bool) -> bool:
    """True if bases ``a``/``b`` are Watson-Crick complementary. ``N`` is a
    wildcard iff ``allow_n`` — matching the ``OverhangBinding`` convention (an
    unsequenced overhang assembles to N, so allow_n lets it pass like the legacy
    binding path skips unresolvable sequences)."""
    if a is None or b is None:
        return False
    a, b = a.upper(), b.upper()
    if allow_n and (a == 'N' or b == 'N'):
        return True
    return _COMPLEMENT.get(a) == b


def overhang_offset_bases(design: Design, overhang_id: str) -> List[str]:
    """Assembled overhang bases 5'→3' (sub-domain overrides → parent slice → N),
    length == the backing-domain length. Mirrors the frontend
    ``assembleOverhangSequence(ovhg, overhangDomainLength(...))``."""
    from backend.core.sequences import _assemble_overhang_5to3
    spec = next((o for o in design.overhangs if o.id == overhang_id), None)
    _, dom = _overhang_backing_domain(design, overhang_id)
    if spec is None or dom is None:
        return []
    domain_len = abs(dom.end_bp - dom.start_bp) + 1
    return list(_assemble_overhang_5to3(spec, domain_len))


def classify_antiparallel(left_dom, right_dom, left_end, right_end,
                          left_bases: List[str], right_bases: List[str],
                          allow_n: bool) -> dict:
    """Per-base antiparallel WC walk: ``left_end`` walked 5'→3' against
    ``right_end`` walked 3'→5'. The shared kernel for BOTH the per-design
    (:func:`classify_duplex_pairing`) and the cross-part assembly classifiers —
    the two differ ONLY in that the cross-part case sources ``right_dom`` /
    ``right_bases`` from a different :class:`Design`. ``left_end`` / ``right_end``
    are any duck-typed ``.start_bp`` / ``.length``-bearing end (``DuplexEnd`` or
    ``AssemblyDuplexEnd``). Do NOT reimplement this walk elsewhere."""
    L = left_end.length
    positions: List[dict] = []
    n_comp = 0
    if left_dom is not None and right_dom is not None:
        left_off0 = bp_to_offset(left_dom, left_end.start_bp)     # 5' base of left
        right_off0 = bp_to_offset(right_dom, right_end.start_bp)  # 5' base of right
        for i in range(L):
            l_off = left_off0 + i
            r_off = right_off0 + (L - 1 - i)   # antiparallel: left 5' ↔ right 3'
            l_base = left_bases[l_off] if 0 <= l_off < len(left_bases) else 'N'
            r_base = right_bases[r_off] if 0 <= r_off < len(right_bases) else 'N'
            comp = _wc_base(l_base, r_base, allow_n)
            n_comp += 1 if comp else 0
            positions.append({
                "offset": i,
                "left_bp": offset_to_bp(left_dom, l_off),
                "right_bp": offset_to_bp(right_dom, r_off),
                "left_base": l_base,
                "right_base": r_base,
                "complementary": comp,
            })
    return {
        "length": L,
        "positions": positions,
        "n_complementary": n_comp,
        "n_mismatch": len(positions) - n_comp,
    }


def classify_duplex_pairing(design: Design, duplex: Duplex) -> dict:
    """Per-base classification of one duplex, walked 5'→3' along ``left`` against
    ``right`` walked 3'→5' (antiparallel). Returns::

        { "length": L,
          "positions": [ {offset, left_bp, right_bp, left_base, right_base,
                          complementary} ... ],   # 5'→3' along left
          "n_complementary": int, "n_mismatch": int }

    Every position is either complementary (paired) or a mismatch — bases OUTSIDE
    any duplex are the toehold/unpaired remainder, reported by
    :func:`overhang_pairing_map`. Bulges are out of scope (equal-length ends).
    """
    _, left_dom = _overhang_backing_domain(design, duplex.left.overhang_id)
    _, right_dom = _overhang_backing_domain(design, duplex.right.overhang_id)
    left_bases = overhang_offset_bases(design, duplex.left.overhang_id)
    right_bases = overhang_offset_bases(design, duplex.right.overhang_id)
    return classify_antiparallel(
        left_dom, right_dom, duplex.left, duplex.right,
        left_bases, right_bases, duplex.allow_n_wildcard,
    )


def overhang_pairing_map(design: Design, overhang_id: str) -> Dict[int, str]:
    """bp → ``'paired'`` | ``'mismatch'`` | ``'unpaired'`` for every bp of an
    overhang's backing domain, aggregating ALL duplexes that touch it
    (multivalency). Uncovered bp are ``'unpaired'`` — a maximal unpaired run is a
    toehold. This is the coverage oracle for the sidebar / cadnano display."""
    _, dom = _overhang_backing_domain(design, overhang_id)
    if dom is None:
        return {}
    lo, hi = sorted((dom.start_bp, dom.end_bp))
    result: Dict[int, str] = {bp: 'unpaired' for bp in range(lo, hi + 1)}
    for dx in design.duplexes:
        if dx.left.overhang_id != overhang_id and dx.right.overhang_id != overhang_id:
            continue
        cls = classify_duplex_pairing(design, dx)
        for p in cls["positions"]:
            for side_id, bp in ((dx.left.overhang_id, p["left_bp"]),
                                (dx.right.overhang_id, p["right_bp"])):
                if side_id == overhang_id and bp in result:
                    result[bp] = 'paired' if p["complementary"] else 'mismatch'
    return result


def duplex_wc_ok(design: Design, duplex: Duplex) -> tuple[bool, str]:
    """Watson-Crick gate kept for Phase 1 (user: "keep the WC validator for now").
    A duplex is acceptable iff no position is a REAL mismatch — N positions pass
    when ``allow_n_wildcard`` (an all-N unsequenced overhang is fine, matching the
    binding path). Returns ``(ok, reason)``. Flip this off later to allow
    mismatched-register kinetics designs (Q3)."""
    cls = classify_duplex_pairing(design, duplex)
    for p in cls["positions"]:
        if not p["complementary"]:
            return False, (
                f"position {p['offset']} ({p['left_base']}/{p['right_base']}) "
                f"is not Watson-Crick complementary"
            )
    return True, ""


def smallest_unused_duplex_name(design: Design) -> str:
    used = {d.name for d in design.duplexes if d.name}
    n = 1
    while f"D{n}" in used:
        n += 1
    return f"D{n}"


def longest_driver(design: Design, left: DuplexEnd, right: DuplexEnd) -> str:
    """Default driver = the LONGER overhang's side (Q4: longest overhang drives;
    the shorter partner rides its helix). Ties → 'left'."""
    la = overhang_domain_length(design, left.overhang_id)
    lb = overhang_domain_length(design, right.overhang_id)
    return 'right' if lb > la else 'left'


def overhang_domain_length(design: Design, overhang_id: str) -> int:
    _, dom = _overhang_backing_domain(design, overhang_id)
    return 0 if dom is None else abs(dom.end_bp - dom.start_bp) + 1


def connect_register(design: Design, oh_a_id: str, attach_a: str,
                     oh_b_id: str, attach_b: str) -> tuple[DuplexEnd, DuplexEnd]:
    """Compute the register for CONNECTING two overhangs at their attach ends —
    the producer for a fresh duplex. MECHANICAL (no polarity reasoning): reuses the
    same `_sub_domain_at_attach` + `subdomain_end` construction as the validated
    binding→duplex migration, so it inherits its polarity. Honors the
    length-preservation invariant: ``length = min(attach sub-domain lengths)``, no
    resize of either overhang; the longer overhang keeps its excess as a toehold.

    ``attach_*`` is ``'root'`` (embedded 5' end) or ``'free_end'`` (protruding 3'
    tip). Raises ``ValueError`` on unresolved overhang / missing sub-domain / domain.
    """
    from backend.core.models import _sub_domain_at_attach
    sd_a_id = _sub_domain_at_attach(design, oh_a_id, attach_a)
    sd_b_id = _sub_domain_at_attach(design, oh_b_id, attach_b)
    if sd_a_id is None or sd_b_id is None:
        raise ValueError("both overhangs need at least one sub-domain to connect")
    ov_a = next((o for o in design.overhangs if o.id == oh_a_id), None)
    ov_b = next((o for o in design.overhangs if o.id == oh_b_id), None)
    if ov_a is None or ov_b is None:
        raise ValueError("both overhangs must resolve")
    sd_a = next(s for s in ov_a.sub_domains if s.id == sd_a_id)
    sd_b = next(s for s in ov_b.sub_domains if s.id == sd_b_id)
    _, dom_a = _overhang_backing_domain(design, oh_a_id)
    _, dom_b = _overhang_backing_domain(design, oh_b_id)
    if dom_a is None or dom_b is None:
        raise ValueError("both overhangs need a backing domain")
    length = min(sd_a.length_bp, sd_b.length_bp)
    if length <= 0:
        raise ValueError("attach sub-domain has zero length")
    return (subdomain_end(dom_a, sd_a, length, oh_a_id),
            subdomain_end(dom_b, sd_b, length, oh_b_id))


def _first_sub_domain_id(design: Design, overhang_id: str) -> Optional[str]:
    ov = next((o for o in design.overhangs if o.id == overhang_id), None)
    return ov.sub_domains[0].id if ov and ov.sub_domains else None


def relocate_duplex(design: Design, duplex: Duplex) -> Design:
    """Phase 4b geometry (#1): relocate the DRIVEN overhang's ENTIRE domain onto the
    DRIVER's helix at the duplex's PAIRED-WINDOW bp range — so a different-length
    duplex (no equal-length binding) forms the duplex in 3D + cadnano. Reuses the
    PROVEN ``compute_bind_topology`` / ``apply_bind_topology`` (a transient binding
    carries the overhang ids; the target range comes from the driver-side duplex
    register, so the short driven isn't stretched to the long driver). Stores the
    pre-relocation snapshot on the duplex (`prior_driven_topology`) + marks it bound.
    Pure. Raises HTTPException(422) from the underlying compute on malformed input."""
    from backend.core.binding_relax import compute_bind_topology, apply_bind_topology
    from backend.core.models import OverhangBinding as _OB

    driver_end = duplex.left if duplex.driver == 'left' else duplex.right
    driven_end = duplex.right if duplex.driver == 'left' else duplex.left
    sd_a = _first_sub_domain_id(design, driver_end.overhang_id) or 'a'
    sd_b = _first_sub_domain_id(design, driven_end.overhang_id) or 'b'
    transient = _OB(
        name='__duplex_reloc__', sub_domain_a_id=sd_a, sub_domain_b_id=sd_b,
        overhang_a_id=driver_end.overhang_id, overhang_b_id=driven_end.overhang_id,
        driver_oh_id=driver_end.overhang_id, driven_oh_id=driven_end.overhang_id,
    )
    topo = compute_bind_topology(
        design, transient, driver_side='a',
        # Antiparallel onto the driver's paired window (mirror the full-domain swap:
        # target_start = window 3' bp, target_end = window 5' bp).
        target_start_override=driver_end.end_bp,
        target_end_override=driver_end.start_bp,
    )
    out = apply_bind_topology(design, topo)
    new_dux = [d.model_copy(update={'prior_driven_topology': topo.snapshot, 'bound': True})
               if d.id == duplex.id else d for d in out.duplexes]
    out = out.model_copy(update={'duplexes': new_dux})

    # Re-seat at the oriented midpoint + promote onto a child DUPLEX cluster — same as the
    # equal-length binding path (`_cv_create_bound_binding`), so a different-length duplex is
    # also a sidebar-listed, gizmo-movable, drift-free cluster. [[overhang-duplex-cluster]].
    from backend.core.direct_relax import duplex_midpoint_placement
    from backend.core.duplex_cluster import materialize_duplex_cluster
    driver_oh = driver_end.overhang_id
    out = out.model_copy(update={'overhangs': [
        o.model_copy(update={'rotation': [0.0, 0.0, 0.0, 1.0], 'translation': [0.0, 0.0, 0.0]})
        if o.id == driver_oh else o for o in out.overhangs]})
    placement = duplex_midpoint_placement(out, driver_oh, driven_end.overhang_id)
    if placement is not None:
        rot, trans = placement
        out = out.model_copy(update={'overhangs': [
            o.model_copy(update={'rotation': rot, 'translation': trans})
            if o.id == driver_oh else o for o in out.overhangs]})
    out, _cid = materialize_duplex_cluster(out, driver_oh)
    return out


def revert_duplex_relocation(design: Design, duplex: Duplex) -> Design:
    """Undo :func:`relocate_duplex` from the stored snapshot (restore the driven
    helix + domain). No-op when the duplex wasn't relocated."""
    from backend.core.binding_relax import revert_bind_topology
    if not duplex.prior_driven_topology:
        return design
    out = revert_bind_topology(design, duplex.prior_driven_topology)
    new_dux = [d.model_copy(update={'prior_driven_topology': None, 'bound': False})
               if d.id == duplex.id else d for d in out.duplexes]
    return out.model_copy(update={'duplexes': new_dux})


def shift_duplex_ends(design: Design, deltas: Dict[str, int]) -> Design:
    """After a whole-domain MOVE (cadnano drag), shift every duplex end on the
    moved overhangs by ``deltas[overhang_id]`` bp — so the SAME bases stay paired
    (register preserved; Q1: moving an overhang must not change WHICH bases pair).
    Ends on un-moved overhangs are untouched. Pure."""
    if not design.duplexes or not deltas:
        return design
    changed = False
    new: List[Duplex] = []
    for dx in design.duplexes:
        upd = {}
        for side in ('left', 'right'):
            end = getattr(dx, side)
            d = deltas.get(end.overhang_id)
            if d:
                upd[side] = end.model_copy(update={
                    'start_bp': end.start_bp + d, 'end_bp': end.end_bp + d})
                changed = True
        new.append(dx.model_copy(update=upd) if upd else dx)
    return design.model_copy(update={'duplexes': new}) if changed else design


def drop_invalid_duplexes(design: Design) -> Design:
    """Drop any duplex whose end no longer fits its backing domain — the defensive
    floor that keeps a cadnano domain edit (resize/move) from BREAKING the whole
    design when a register falls out of range. Pure. (The full register-preserving
    slide on the applied shared helix is Phase 4.)"""
    if not design.duplexes:
        return design
    keep: List[Duplex] = []
    for dx in design.duplexes:
        ok = True
        for end in (dx.left, dx.right):
            _, dom = _overhang_backing_domain(design, end.overhang_id)
            if dom is None:
                ok = False
                break
            lo, hi = sorted((dom.start_bp, dom.end_bp))
            e_lo, e_hi = sorted((end.start_bp, end.end_bp))
            if e_lo < lo or e_hi > hi:
                ok = False
                break
        if ok:
            keep.append(dx)
    return design if len(keep) == len(design.duplexes) else design.model_copy(update={'duplexes': keep})


def sync_duplexes_from_bindings(design: Design) -> Design:
    """Idempotently ensure every legacy ``OverhangBinding`` pair also has a display
    ``Duplex`` (live equivalent of the load-time `_derive_duplexes_if_empty`).
    Skips pairs that already carry a duplex; assigns fresh unique names. Used after
    a live Connect so the graph populates without a reload."""
    existing = {frozenset({dx.left.overhang_id, dx.right.overhang_id}) for dx in design.duplexes}
    additions: List[Duplex] = []
    d = design
    for dx in synthesize_duplexes_from_bindings(design):
        pair = frozenset({dx.left.overhang_id, dx.right.overhang_id})
        if pair in existing:
            continue
        existing.add(pair)
        named = dx.model_copy(update={"name": smallest_unused_duplex_name(
            d.model_copy(update={"duplexes": [*d.duplexes, *additions]}))})
        additions.append(named)
    if not additions:
        return design
    return design.model_copy(update={"duplexes": [*design.duplexes, *additions]})


def summarize_duplexes(design: Design) -> dict:
    """Headless oracle: a compact readout of the whole duplex graph — per-duplex
    paired/mismatch counts and per-overhang paired/mismatch/toehold bp totals.
    Used by automation + tests to assert a register produces the intended
    pairing without any UI."""
    per_duplex = []
    for dx in design.duplexes:
        cls = classify_duplex_pairing(design, dx)
        per_duplex.append({
            "id": dx.id, "name": dx.name, "driver": dx.driver, "bound": dx.bound,
            "length": cls["length"],
            "n_complementary": cls["n_complementary"],
            "n_mismatch": cls["n_mismatch"],
        })
    per_overhang = {}
    touched = {e.overhang_id for dx in design.duplexes for e in (dx.left, dx.right)}
    for oid in sorted(touched):
        cov = overhang_pairing_map(design, oid)
        vals = list(cov.values())
        per_overhang[oid] = {
            "paired": vals.count('paired'),
            "mismatch": vals.count('mismatch'),
            "toehold": vals.count('unpaired'),
        }
    return {"duplexes": per_duplex, "overhangs": per_overhang}
