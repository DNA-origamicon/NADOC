"""Shared native direct construction with optional recorded identity and time.

This is materialization, not source admission or a registered feature contract.
No solver, placement arithmetic or molecular choice is reimplemented here.
"""

from math import isfinite
from typing import Optional

from backend.core.feature_identity import identity_factory
from backend.core.models import Design, Duplex, OverhangBinding


def _identity(history_seed, created_at):
    if history_seed is None and created_at is None:
        return None
    if (not isinstance(history_seed, str) or type(created_at) not in (int, float)
            or not isfinite(created_at) or created_at < 0):
        raise ValueError("Direct construction requires a UUID seed and finite nonnegative creation time")
    return identity_factory(history_seed)


def _sub_domain_at_attach(d: Design, ovhg_id: str, attach: str):
    ov = next((o for o in d.overhangs if o.id == ovhg_id), None)
    if ov is None or not ov.sub_domains:
        return None
    ordered = sorted(ov.sub_domains, key=lambda sd: sd.start_bp_offset or 0)
    return (ordered[0] if attach == "root" else ordered[-1]).id


def create_bound_binding(
    d: Design, a_id: str, b_id: str, attach_a: str, attach_b: str, connection_type: str,
    *, history_seed: str | None = None, created_at: float | None = None,
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

    identifier = _identity(history_seed, created_at)
    duplex_id = identifier("connection-duplex", []) if identifier else None
    sd_a = _sub_domain_at_attach(d, a_id, attach_a)
    sd_b = _sub_domain_at_attach(d, b_id, attach_b)
    if not (sd_a and sd_b):
        return d  # no sub-domains → can't bind (mirrors the old direct silent-skip)

    # Length-preservation: a direct binding relocates one WHOLE tip domain onto the
    # other, so it requires equal-length attach sub-domains. DIFFERENT-length
    # overhangs are represented by the Duplex (paired window + toehold) — skip the
    # binding here (its unequal-length record would fail validation anyway; the
    # binding-based geometry for different lengths is deferred). The duplex is
    # created by materialize_direct in this same transaction.
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
        **({"id": identifier("connection-binding", []), "created_at": created_at} if identifier else {}),
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
    topology = compute_bind_topology(d, binding, driver_side="a",
        forced_ligation_id=identifier("duplex-ligation", [duplex_id]) if identifier else None)
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

    d, _cid = materialize_duplex_cluster(d, a_id,
        cluster_id=identifier("duplex-cluster", [duplex_id]) if identifier else None)
    return d


def materialize_direct(d, a_id, b_id, attach_a, attach_b, connection_type,
                       *, history_seed=None, created_at=None):
    """Create native binding/display owners; unequal lengths use Duplex relocation.

    Callers own conflict teardown, input validation and sequence assignment.
    Saved recipes must supply identity/time together. Ordinary legacy callers
    retain their existing random allocation until a complete contract is admitted.
    """
    from backend.core.duplex import (
        connect_register, longest_driver, relocate_duplex, smallest_unused_duplex_name,
    )

    identifier = _identity(history_seed, created_at)
    d = create_bound_binding(d, a_id, b_id, attach_a, attach_b, connection_type,
                             history_seed=history_seed, created_at=created_at)
    pair = {a_id, b_id}
    if any({dx.left.overhang_id, dx.right.overhang_id} == pair for dx in d.duplexes):
        return d
    left, right = connect_register(d, a_id, attach_a, b_id, attach_b)
    duplex = Duplex(
        **({"id": identifier("connection-duplex", []), "created_at": created_at} if identifier else {}),
        name=smallest_unused_duplex_name(d), left=left, right=right,
        driver=longest_driver(d, left, right), allow_n_wildcard=True,
        connection_type=connection_type,
    )
    d = d.model_copy(update={"duplexes": [*d.duplexes, duplex]}, deep=True)
    if not any({b.overhang_a_id, b.overhang_b_id} == pair for b in d.overhang_bindings):
        d = relocate_duplex(d, duplex, identity_seed=history_seed)
    return d
