"""Render fast-path diff kernel (carve-up service push #47).

Pure model comparison: two ``Design`` snapshots in → a bool / list / field-name
out. These classify how cheaply the frontend can update after an undo / redo /
feature-log seek, driving the response fast paths in ``crud.py``'s
``_design_replace_response``:

  • ``_diff_is_cluster_only`` — the two designs differ ONLY in cluster
    rotation/translation → ship a compact ``cluster_diffs`` delta the renderer
    applies in place, no geometry recompute, no scene rebuild.
  • ``_cluster_diff_payload`` — emit the per-cluster delta records for that path.
  • ``_topology_diff_field`` / ``_topology_unchanged`` — the renderer's
    structural inventory is invariant → ship compact per-nuc positions instead
    of forcing a full scene rebuild; the field name tags the perf trace when it
    rejects.
  • ``_strand_occupancy`` / ``_local_changed_helices`` (carve-up #50) — the
    partial-geometry path for a POSITION-PRESERVING topology edit (nick, merge,
    relabel): snapshot strand occupancy before and after, diff it to the set of
    helices whose nucleotides can actually have moved, and reship only those.
    ``None`` means "can't express this edit partially — send full geometry".

Distinct from ``backend.core.design_diff`` (the Fine-Routing id-keyed *content*
diff used for per-sub-step revert/delete) — that reconstructs intermediate
cluster states; this one only *classifies* the cheapest render path.

These were marooned in ``backend/api/crud.py``'s "Internal helpers" block; they
touch no api-layer state (no ``design_state``, no ``HTTPException``), so they
belong in ``backend/core``. ``crud.py`` re-exports them under their original
underscore names so the cross-file/test callers that do
``from backend.api.crud import _topology_diff_field`` keep working unchanged.

One reason to change: how NADOC decides whether two design snapshots differ
cheaply enough (cluster-only / positions-only) to skip the full geometry
recompute + scene rebuild.

``backend/core`` must never import ``backend/api`` (L4) — both designs arrive as
explicit arguments.
"""

from __future__ import annotations

from backend.core.models import Design  # noqa: F401  (string annotation in signatures)


def _diff_is_cluster_only(prev: "Design", new: "Design") -> bool:
    """True iff prev and new differ ONLY in cluster_transforms' rotation /
    translation (no add/remove/structural/pivot change). Used by undo/redo
    to take a Plan-B-style fast path that avoids the full geometry recompute
    and the frontend scene rebuild.

    Cluster_joints are allowed to differ because they move with cluster
    transforms by design.

    Pivot equality is required because the frontend's delta-transform math
    (which composes the existing applyClusterTransform call to step from
    the OLD cluster transform's world position to the NEW one) only holds
    when the pivot is unchanged. If pivots differ, the math would need to
    re-resolve via the straight-position basis — fall back to the full
    geometry refetch path in that rare case.
    """
    structural = [
        "helices",
        "strands",
        "crossovers",
        "forced_ligations",
        "deformations",
        "extensions",
        "overhangs",
        "overhang_connections",
        "photoproduct_junctions",
    ]
    for f in structural:
        if getattr(prev, f) != getattr(new, f):
            return False
    if len(prev.cluster_transforms) != len(new.cluster_transforms):
        return False
    if prev.cluster_transforms == new.cluster_transforms:
        return False  # nothing changed at all — let the regular path handle it
    by_id_prev = {ct.id: ct for ct in prev.cluster_transforms}
    by_id_new = {ct.id: ct for ct in new.cluster_transforms}
    if set(by_id_prev) != set(by_id_new):
        return False  # cluster added or removed
    for cid, p_ct in by_id_prev.items():
        n_ct = by_id_new[cid]
        if p_ct.helix_ids != n_ct.helix_ids:
            return False
        if p_ct.domain_ids != n_ct.domain_ids:
            return False
        if p_ct.name != n_ct.name:
            return False
        if p_ct.is_default != n_ct.is_default:
            return False
        if p_ct.pivot != n_ct.pivot:
            return False  # frontend delta math requires this
    return True


def _cluster_diff_payload(prev: "Design", new: "Design") -> list[dict]:
    """For each cluster whose translation / rotation / pivot changed
    between *prev* and *new*, emit a record the frontend can use to
    apply the delta to the renderer's bead/slab/cone/axis matrices
    in-place. Caller is responsible for ensuring `_diff_is_cluster_only`
    holds — this helper just emits the records.
    """
    by_id_prev = {ct.id: ct for ct in prev.cluster_transforms}
    out = []
    for n_ct in new.cluster_transforms:
        p_ct = by_id_prev.get(n_ct.id)
        if p_ct is None:
            continue
        if (
            p_ct.translation == n_ct.translation
            and p_ct.rotation == n_ct.rotation
            and p_ct.pivot == n_ct.pivot
        ):
            continue
        out.append(
            {
                "cluster_id": n_ct.id,
                "helix_ids": list(n_ct.helix_ids),
                "old_translation": list(p_ct.translation),
                "old_rotation": list(p_ct.rotation),
                "old_pivot": list(p_ct.pivot),
                "new_translation": list(n_ct.translation),
                "new_rotation": list(n_ct.rotation),
                "new_pivot": list(n_ct.pivot),
            }
        )
    return out


def _topology_unchanged(prev: "Design", new: "Design") -> bool:
    """True iff the renderer's structural inventory (mesh/cone/slab counts,
    axis-tube curvature, helix lengths) is invariant between prev and new.

    The frontend's ``positions_only`` fast path mutates per-nuc positions in
    place WITHOUT a full design_renderer rebuild, so anything that would force
    a rebuild must be excluded here:

      • Helix add/remove or axis change → mesh count / curvature change.
      • Strand domain change → which bps have nucs.
      • Crossover/extension/overhang change → adds or removes nucs.
      • DEFORMATION add/remove/edit → can flip a helix between straight and
        curved, which requires rebuilding the axis tube geometry.

    Cluster transforms ARE allowed to differ — they just translate/rotate
    existing meshes without changing topology or curvature.
    """
    return _topology_diff_field(prev, new) is None


def _topology_diff_field(prev: "Design", new: "Design") -> str | None:
    """If the topology check rejects, return the name of the field that
    differs. ``None`` means topology IS unchanged. Used to attach a more
    informative ``path:full_geometry(<reason>)`` tag to the perf trace so
    you can see at a glance why positions_only didn't fire."""
    if prev.helices != new.helices:
        return "helices"
    if prev.strands != new.strands:
        return "strands"
    if prev.crossovers != new.crossovers:
        return "crossovers"
    if prev.extensions != new.extensions:
        return "extensions"
    if prev.overhang_connections != new.overhang_connections:
        return "overhang_connections"
    if prev.overhangs != new.overhangs:
        return "overhangs"
    if prev.forced_ligations != new.forced_ligations:
        return "forced_ligations"
    if prev.photoproduct_junctions != new.photoproduct_junctions:
        return "photoproduct_junctions"
    if prev.deformations != new.deformations:
        return "deformations"
    # Flexible-segment marks change per-bead `is_flexible_segment` (which beads
    # render rigid vs. as a bowed arc) and carve the helix axis — the
    # positions_only fast path ships neither, so force full geometry. Without
    # this, undo/redo/seek of a mark leaves beads excluded with a stale flag and
    # no arc → the segment vanishes.
    if prev.flexible_segment_marks != new.flexible_segment_marks:
        return "flexible_segment_marks"
    return None


def _strand_occupancy(design: Design) -> dict:
    """Mutation-proof snapshot of what each strand occupies, plus the synthetic-
    geometry inputs (extensions, ds-linker connections). Captures plain values,
    so it stays valid even if *design* is later mutated in place. Cheap —
    topology only, no geometry compute. Pair with :func:`_local_changed_helices`
    to drive the partial-geometry fast path for position-preserving edits.
    """
    return {
        "sig": {
            s.id: (
                s.strand_type,
                tuple(
                    (d.helix_id, d.start_bp, d.end_bp, d.direction, d.overhang_id)
                    for d in s.domains
                ),
            )
            for s in design.strands
        },
        "helices": {
            s.id: frozenset(d.helix_id for d in s.domains) for s in design.strands
        },
        "ext": {e.id: e.model_dump(mode="json") for e in design.extensions},
        "conns": {c.id: c.model_dump(mode="json") for c in design.overhang_connections},
    }


def _local_changed_helices(before: dict, after: dict) -> list[str] | None:
    """Helix IDs to reship via the partial-geometry fast path for a
    POSITION-PRESERVING topology edit (add / remove / relabel of strands — never
    a move). Both args are :func:`_strand_occupancy` snapshots, pre- and post-edit.

    Returns ``None`` — fall back to full geometry — when the edit can't be
    expressed partially: it touched synthetic geometry (extensions or ds-linker
    bridges, both emitted only in full mode), OR nothing occupancy-changed (an
    empty changed-list would trip the frontend's full-replacement branch and
    wipe the scene).

    A helix's nucleotides change only if some strand's occupancy on it changes,
    so we diff strand signatures and union the domain helices of every differing
    strand across BOTH snapshots (a split fragment keeps helices that leave the
    original strand id; a merge's absorbed id contributes its old helices).
    """
    b_sig, a_sig = before["sig"], after["sig"]
    changed = {
        sid for sid in b_sig.keys() | a_sig.keys() if b_sig.get(sid) != a_sig.get(sid)
    }
    if not changed:
        return None
    # Changed extension/linker definitions still require a full response. Stable
    # extensions owned by a changed strand are safe: include their synthetic IDs
    # so the partial geometry path recomputes only those terminal arcs.
    if before["ext"] != after["ext"] or before["conns"] != after["conns"]:
        return None
    affected_ext_ids = {
        eid
        for eid, ext in (before["ext"] | after["ext"]).items()
        if ext["strand_id"] in changed
    }
    helices: set[str] = set()
    for sid in changed:
        helices |= before["helices"].get(sid, frozenset())
        helices |= after["helices"].get(sid, frozenset())
    return list(helices) + [f"__ext_{eid}" for eid in affected_ext_ids]
