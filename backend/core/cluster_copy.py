"""Cluster copy/paste — extract a cluster selection, graft it back at a lattice offset.

The user hand-routes a motif (a folded corner, a hinge, a particular crossover
pattern) inside one or more clusters, then Ctrl+C / Ctrl+V to repeat or tile it.

**The invariant that makes this correct.**  A helix's FORWARD/REVERSE polarity is
``(row + col) % 2`` (:func:`lattice.scaffold_direction_for_cell`), and crossover
legality is a table lookup keyed on ``(is_forward, bp_index % period)``
(:func:`crossover_positions.crossover_neighbor`, period 21 honeycomb / 32 square).
Therefore:

    an EVEN-parity grid shift ``(Δrow + Δcol) % 2 == 0``, with ``Δbp == 0``,
    preserves every copied helix's polarity AND lands every copied crossover
    on a legal site.

Both halves of that are enforced here: ``Δbp`` does not exist as a parameter (bp
indices are copied verbatim), and :func:`graft_cluster_subdesign` raises on an
odd-parity shift.  Note the parity check is *independent* of the footprint guard
inherited from :mod:`primitive_placement`: honeycomb's ``y`` depends on
``(row+col)`` parity so an odd shift visibly distorts the footprint and trips that
guard, but SQUARE lattice positions are linear — an odd square shift sails through
the footprint guard while silently inverting every helix's polarity.

Two phases, because the id remap needs the destination and the truncation does not:

* :func:`extract_cluster_subdesign` — *what* to copy, in SOURCE coordinates.
  Structural truncation lives here (it renumbers ``domain_index``, which
  ``DomainRef`` points at).
* :func:`graft_cluster_subdesign` — *where* it lands.  Rigid translation, full id
  remap, additive merge.

Three-Layer note: both are **topological** writes (an allowed edit) and strictly
additive — the host's existing strand graph is never mutated.  A cluster's
``translation``/``rotation``/``pivot`` are display-layer pose metadata that ride
along unchanged (the pivot is shifted by the same rigid world vector as the
helices, so the copy is posed identically to the source).

This is the **service** shape: pure, HTTP-free; ``backend.core`` imports nothing
from ``backend.api``.  The commit wrapper is the ``/design/cluster-paste`` route.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Sequence

from backend.core.models import (
    ClusterRigidTransform,
    DeformationOp,
    Design,
    Domain,
    DomainRef,
    Strand,
)
from backend.core.primitive_placement import (
    _fresh_id,
    _world_delta,
    detect_plane,
    primitive_anchor_cell,
    translate_design,
)

_EPS = 1e-6


@dataclass
class ClusterCopyReport:
    """What the extract actually copied — surfaced to the user after a paste."""

    requested_cluster_ids: list[str] = field(default_factory=list)
    closure_cluster_ids: list[str] = field(default_factory=list)
    auto_added_cluster_ids: list[str] = field(default_factory=list)
    copied_helix_ids: list[str] = field(default_factory=list)
    truncated_strand_count: int = 0
    dropped_boundary_crossovers: int = 0
    dropped_boundary_fls: int = 0


# ── closure ───────────────────────────────────────────────────────────────────


def cluster_closure(
    cluster_ids: Sequence[str], clusters: Sequence[ClusterRigidTransform]
) -> tuple[list[str], list[str]]:
    """Transitively close a cluster selection over ``parent_cluster_id``, BOTH ways.

    A child cluster's transform is expressed in its parent's REST frame, so a child
    without its parent is meaningless; a parent without its children loses the
    sub-poses.  Selecting either end therefore pulls in the other.

    Returns ``(closure_ids, auto_added_ids)`` — both in stable design order.
    """
    by_id = {c.id: c for c in clusters}
    unknown = [cid for cid in cluster_ids if cid not in by_id]
    if unknown:
        raise ValueError(f"unknown cluster id(s): {', '.join(sorted(unknown))}")

    children: dict[str, list[str]] = {}
    for c in clusters:
        if c.parent_cluster_id is not None:
            children.setdefault(c.parent_cluster_id, []).append(c.id)

    requested = set(cluster_ids)
    closure = set(cluster_ids)
    stack = list(cluster_ids)
    while stack:
        cid = stack.pop()
        parent = by_id[cid].parent_cluster_id
        if parent is not None and parent not in closure:
            closure.add(parent)
            stack.append(parent)
        for child in children.get(cid, []):
            if child not in closure:
                closure.add(child)
                stack.append(child)

    ordered = [c.id for c in clusters if c.id in closure]
    auto_added = [cid for cid in ordered if cid not in requested]
    return ordered, auto_added


# ── extract ───────────────────────────────────────────────────────────────────


def extract_cluster_subdesign(
    design: Design, cluster_ids: Sequence[str]
) -> tuple[Design, ClusterCopyReport]:
    """Carve a self-contained sub-``Design`` out of ``design`` for ``cluster_ids``.

    In SOURCE coordinates — ids and bp indices are untouched;
    :func:`graft_cluster_subdesign` rewrites them.

    Copied: the closure's helices, their strands **truncated at the cluster
    boundary**, internal-only crossovers and forced ligations, scoped
    deformations, and the closure's cluster transforms.

    Strand sequences are deliberately NOT copied (``sequence=None``): identical
    staple sequences would cross-hybridize with the original.  A convenient
    side-effect is that truncation never has to slice a sequence string.

    Raises ``ValueError`` if the selection is empty, names an unknown cluster, or
    lands on a helix carrying content this graft cannot yet place verbatim
    (overhangs / extensions — refused rather than silently dropped, which would
    leave dangling ``Domain.overhang_id`` references).
    """
    if not cluster_ids:
        raise ValueError("no clusters selected to copy")

    closure_ids, auto_added = cluster_closure(cluster_ids, design.cluster_transforms)
    closure = [c for c in design.cluster_transforms if c.id in set(closure_ids)]

    reference_helices = design.reference_helix_ids()
    copied: set[str] = set()
    for c in closure:
        copied.update(hid for hid in c.helix_ids if hid not in reference_helices)
    if not copied:
        raise ValueError("the selected cluster(s) contain no copyable helices")

    _refuse_unsupported(design, copied)

    helices = [h.model_copy(deep=True) for h in design.helices if h.id in copied]

    strands, split_map, truncated = _truncate_strands(design, copied)

    crossovers = [
        x.model_copy(deep=True)
        for x in design.crossovers
        if x.half_a.helix_id in copied and x.half_b.helix_id in copied
    ]
    fls = [
        fl.model_copy(deep=True)
        for fl in design.forced_ligations
        if fl.three_prime_helix_id in copied and fl.five_prime_helix_id in copied
    ]

    deformations = _scoped_deformations(design, copied, set(closure_ids))
    clusters = _rebuild_clusters(closure, copied, split_map)

    sub = Design(
        lattice_type=design.lattice_type,
        helices=helices,
        strands=strands,
        crossovers=crossovers,
        forced_ligations=fls,
        deformations=deformations,
        cluster_transforms=clusters,
    )
    report = ClusterCopyReport(
        requested_cluster_ids=list(cluster_ids),
        closure_cluster_ids=closure_ids,
        auto_added_cluster_ids=auto_added,
        copied_helix_ids=sorted(copied),
        truncated_strand_count=truncated,
        dropped_boundary_crossovers=len(
            [
                x
                for x in design.crossovers
                if (x.half_a.helix_id in copied) != (x.half_b.helix_id in copied)
            ]
        ),
        dropped_boundary_fls=len(
            [
                fl
                for fl in design.forced_ligations
                if (fl.three_prime_helix_id in copied)
                != (fl.five_prime_helix_id in copied)
            ]
        ),
    )
    return sub, report


def _refuse_unsupported(design: Design, copied: set[str]) -> None:
    """Refuse content the graft cannot yet carry, rather than silently dropping it.

    Dropping an ``OverhangSpec`` while keeping its backing ``Domain`` would leave a
    dangling ``Domain.overhang_id`` and silently render an ssDNA overhang as duplex.
    """
    ohs = [o.id for o in design.overhangs if o.helix_id in copied]
    if ohs:
        raise ValueError(
            f"cluster selection carries {len(ohs)} overhang(s) — copying overhangs, "
            "extensions and linkers is not supported yet"
        )
    strand_ids = {
        s.id
        for s in design.strands
        if any(dm.helix_id in copied for dm in s.domains)
    }
    exts = [e.id for e in design.extensions if e.strand_id in strand_ids]
    if exts:
        raise ValueError(
            f"cluster selection carries {len(exts)} strand extension(s) — copying "
            "overhangs, extensions and linkers is not supported yet"
        )


def _truncate_strands(
    design: Design, copied: set[str]
) -> tuple[list[Strand], dict[tuple[str, int], tuple[str, int]], int]:
    """Split each strand into its maximal runs of copied-helix domains.

    A staple straddling the cluster boundary becomes a shorter strand ending at the
    boundary; the scaffold becomes a free fragment with its own 5′/3′ ends.

    Returns ``(fragments, split_map, truncated_count)`` where ``split_map`` maps
    ``(orig_strand_id, orig_domain_index) -> (fragment_strand_id, new_domain_index)``.
    That map is load-bearing: truncation RENUMBERS ``domain_index``, and both
    ``DomainRef`` (domain-level clusters) and ``FlexibleSegmentMark`` index into a
    strand's domain list by position.
    """
    fragments: list[Strand] = []
    split_map: dict[tuple[str, int], tuple[str, int]] = {}
    truncated = 0

    for strand in design.strands:
        runs: list[list[int]] = []
        current: list[int] = []
        for idx, dom in enumerate(strand.domains):
            if dom.helix_id in copied:
                current.append(idx)
            elif current:
                runs.append(current)
                current = []
        if current:
            runs.append(current)

        if not runs:
            continue
        # One run spanning every domain == the whole strand survived intact.
        if not (len(runs) == 1 and len(runs[0]) == len(strand.domains)):
            truncated += 1

        for run in runs:
            frag_id = str(uuid.uuid4())
            domains: list[Domain] = []
            for new_idx, orig_idx in enumerate(run):
                split_map[(strand.id, orig_idx)] = (frag_id, new_idx)
                domains.append(strand.domains[orig_idx].model_copy(deep=True))
            fragments.append(
                strand.model_copy(
                    deep=True,
                    update={"id": frag_id, "domains": domains, "sequence": None},
                )
            )

    return fragments, split_map, truncated


def _scoped_deformations(
    design: Design, copied: set[str], closure_ids: set[str]
) -> list[DeformationOp]:
    """Keep deformations scoped to the copied clusters / helices, filtered to them.

    ``plane_a_bp`` / ``plane_b_bp`` are carried verbatim — Δbp is always 0.
    """
    out: list[DeformationOp] = []
    for op in design.deformations:
        scoped_by_cluster = bool(set(op.cluster_ids) & closure_ids)
        scoped_by_helix = bool(op.affected_helix_ids) and set(
            op.affected_helix_ids
        ) <= copied
        if not (scoped_by_cluster or scoped_by_helix):
            continue
        helix_ids = [h for h in op.affected_helix_ids if h in copied]
        if not helix_ids:
            continue
        out.append(
            op.model_copy(
                deep=True,
                update={
                    "affected_helix_ids": helix_ids,
                    "cluster_ids": [c for c in op.cluster_ids if c in closure_ids],
                },
            )
        )
    return out


def _rebuild_clusters(
    closure: list[ClusterRigidTransform],
    copied: set[str],
    split_map: dict[tuple[str, int], tuple[str, int]],
) -> list[ClusterRigidTransform]:
    """Rebuild the closure's clusters against the truncated strands.

    ``is_default`` is always cleared: a copy is never the auto-created catch-all.
    ``DomainRef``s pointing at domains that truncation dropped are dropped too.
    ``pivot`` stays in source coordinates; the graft shifts it.
    """
    out: list[ClusterRigidTransform] = []
    for c in closure:
        domain_ids: list[DomainRef] = []
        for ref in c.domain_ids:
            mapped = split_map.get((ref.strand_id, ref.domain_index))
            if mapped is None:
                continue  # the domain did not survive truncation
            frag_id, new_idx = mapped
            domain_ids.append(DomainRef(strand_id=frag_id, domain_index=new_idx))
        out.append(
            c.model_copy(
                deep=True,
                update={
                    "is_default": False,
                    "helix_ids": [h for h in c.helix_ids if h in copied],
                    "domain_ids": domain_ids,
                    # Overhangs are not copied yet, so a duplex driver can't survive.
                    "overhang_duplex_driver_id": None,
                },
            )
        )
    return out


# ── graft ─────────────────────────────────────────────────────────────────────


def graft_cluster_subdesign(
    host: Design, sub: Design, *, grid_delta: tuple[int, int]
) -> tuple[Design, list[str]]:
    """Return ``host`` + a rigidly-translated, id-remapped copy of ``sub``.

    ``grid_delta`` is ``(Δrow, Δcol)``; ``Δbp`` is implicitly 0.  Every helix moves
    by the one rigid lattice vector that shift implies, so the pasted sub-structure
    is an exact rigid copy.  Cluster poses ride along with their pivots shifted by
    the same world vector, so a posed source pastes as an identically-posed copy.

    Returns ``(new_design, pasted_helix_ids)``.  The pasted helix ids are what the
    caller feeds to ``MutationReport.new_helix_origins`` as explicit orphans —
    without that, ``reconcile_cluster_membership`` sweeps them into a
    lattice-adjacent host cluster (they are within Manhattan distance 2 of the
    source) and the copy ends up double-owned.

    Raises ``ValueError`` on: an odd-parity shift; a lattice mismatch; an empty
    sub-design; a non-rigid honeycomb footprint shift; or a destination cell the
    host already occupies.
    """
    if not sub.helices:
        raise ValueError("nothing to paste (no helices in the copied selection)")

    d_row, d_col = grid_delta
    if (d_row + d_col) % 2 != 0:
        raise ValueError(
            f"paste offset (Δrow={d_row}, Δcol={d_col}) has odd parity, which flips "
            "every helix's FORWARD/REVERSE polarity and moves every crossover off "
            "its allowed bp phase; choose an offset whose (Δrow + Δcol) is even"
        )
    if (d_row, d_col) == (0, 0):
        raise ValueError("paste offset is zero; the copy would collide with the source")

    lattice = sub.lattice_type
    if host.helices and host.lattice_type != lattice:
        raise ValueError(
            f"cannot paste a {lattice} cluster into a {host.lattice_type} design"
        )

    plane = detect_plane(sub)
    src_anchor = primitive_anchor_cell(sub)
    dst_anchor = (src_anchor[0] + d_row, src_anchor[1] + d_col)
    world_delta = _world_delta(src_anchor, dst_anchor, lattice)

    # Rigid-translation + collision guards, per helix.  The rigid check is
    # belt-and-braces for honeycomb (an odd shift already raised above); the
    # collision check is the real gate.
    occupied = {h.grid_pos for h in host.helices if h.grid_pos is not None}
    for h in sub.helices:
        gp = h.grid_pos
        if gp is None:
            raise ValueError(f"helix {h.id!r} has no lattice position; cannot paste")
        new_gp = (gp[0] + d_row, gp[1] + d_col)
        per_cell = _world_delta(gp, new_gp, lattice)
        if (
            abs(per_cell[0] - world_delta[0]) > _EPS
            or abs(per_cell[1] - world_delta[1]) > _EPS
        ):
            raise ValueError(
                "paste would distort the footprint (a non-rigid lattice shift); "
                "choose a shape-preserving offset"
            )
        if new_gp in occupied:
            raise ValueError(
                f"paste collides with existing DNA at cell {new_gp}; move to a clear spot"
            )

    # ── id remap tables ───────────────────────────────────────────────────────
    used_h = {h.id for h in host.helices}
    used_s = {s.id for s in host.strands}
    used_c = {c.id for c in host.cluster_transforms}

    hmap: dict[str, str] = {}
    for h in sub.helices:
        gp = h.grid_pos
        assert gp is not None  # guarded above
        base = f"h_{plane}_{gp[0] + d_row}_{gp[1] + d_col}"
        nid = _fresh_id(base, used_h)
        used_h.add(nid)
        hmap[h.id] = nid

    smap: dict[str, str] = {}
    for s in sub.strands:
        nid = _fresh_id(s.id, used_s)
        used_s.add(nid)
        smap[s.id] = nid

    cmap: dict[str, str] = {}
    for c in sub.cluster_transforms:
        nid = _fresh_id(c.id, used_c)
        used_c.add(nid)
        cmap[c.id] = nid

    # ── translate + remap ─────────────────────────────────────────────────────
    translated = translate_design(sub, grid_delta, world_delta, plane)
    placed_helices = [
        h.model_copy(update={"id": hmap[orig.id]})
        for orig, h in zip(sub.helices, translated.helices)
    ]

    placed_strands = [
        s.model_copy(
            update={
                "id": smap[s.id],
                "domains": [
                    dm.model_copy(update={"helix_id": hmap[dm.helix_id]})
                    for dm in s.domains
                ],
            }
        )
        for s in sub.strands
    ]

    placed_crossovers = [
        x.model_copy(
            update={
                "id": str(uuid.uuid4()),
                "half_a": x.half_a.model_copy(
                    update={"helix_id": hmap[x.half_a.helix_id]}
                ),
                "half_b": x.half_b.model_copy(
                    update={"helix_id": hmap[x.half_b.helix_id]}
                ),
            }
        )
        for x in sub.crossovers
    ]

    placed_fls = [
        fl.model_copy(
            update={
                "id": str(uuid.uuid4()),
                "three_prime_helix_id": hmap[fl.three_prime_helix_id],
                "five_prime_helix_id": hmap[fl.five_prime_helix_id],
            }
        )
        for fl in sub.forced_ligations
    ]

    placed_deformations = [
        op.model_copy(
            update={
                "id": str(uuid.uuid4()),
                "affected_helix_ids": [hmap[h] for h in op.affected_helix_ids],
                "cluster_ids": [cmap[c] for c in op.cluster_ids if c in cmap],
            }
        )
        for op in sub.deformations
    ]

    placed_clusters = []
    for c in sub.cluster_transforms:
        missing = [ref.strand_id for ref in c.domain_ids if ref.strand_id not in smap]
        if missing:
            raise ValueError("cluster names a strand the copy did not produce")
        placed_clusters.append(
            c.model_copy(
                update={
                    "id": cmap[c.id],
                    "helix_ids": [hmap[h] for h in c.helix_ids],
                    "domain_ids": [
                        ref.model_copy(update={"strand_id": smap[ref.strand_id]})
                        for ref in c.domain_ids
                    ],
                    "parent_cluster_id": (
                        cmap[c.parent_cluster_id]
                        if c.parent_cluster_id in cmap
                        else None
                    ),
                    "pivot": _shift_pivot(c.pivot, world_delta, plane),
                }
            )
        )

    result = host.model_copy(deep=True)
    result.helices = list(result.helices) + placed_helices
    result.strands = list(result.strands) + placed_strands
    result.crossovers = list(result.crossovers) + placed_crossovers
    result.forced_ligations = list(result.forced_ligations) + placed_fls
    result.deformations = list(result.deformations) + placed_deformations
    result.cluster_transforms = list(result.cluster_transforms) + placed_clusters
    if not host.helices:
        result.lattice_type = lattice

    return result, [hmap[h.id] for h in sub.helices]


_PLANE_AXES: dict[str, tuple[int, int]] = {"XY": (0, 1), "XZ": (0, 2), "YZ": (1, 2)}


def _shift_pivot(
    pivot: list[float], world_delta: tuple[float, float], plane: str
) -> list[float]:
    """Shift a cluster pivot by the same in-plane world vector as its helices.

    Keeps a posed copy's rotation centre in the right place — without this the copy
    would rotate about the SOURCE's pivot and fly off.
    """
    out = list(pivot)
    a, b = _PLANE_AXES[plane]
    out[a] += world_delta[0]
    out[b] += world_delta[1]
    return out


def paste_clusters(
    design: Design, cluster_ids: Sequence[str], grid_delta: tuple[int, int]
) -> tuple[Design, list[str], ClusterCopyReport]:
    """Extract + graft in one call.  Returns ``(design, pasted_helix_ids, report)``."""
    sub, report = extract_cluster_subdesign(design, cluster_ids)
    grafted, pasted_helix_ids = graft_cluster_subdesign(
        design, sub, grid_delta=grid_delta
    )
    return grafted, pasted_helix_ids, report
