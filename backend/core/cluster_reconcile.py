"""
Incremental cluster membership reconciliation.

After a topology mutation (add helix, place crossover, nick, ligate, extrude
overhang, etc.), this module repairs cluster membership so that:

  * New lattice components inherit a canonical neighbor or explicit parent
    cluster, including its translation/rotation/pivot.
  * Stale ``DomainRef`` entries (strand_id gone, domain_index out of range)
    are dropped.
  * Existing cluster membership the user manually edited is preserved.
  * Cluster transforms (translation/rotation/pivot) are never modified.
  * Existing clusters are never deleted, split, or merged. Extrusion can opt
    into creating clusters for disconnected new lattice components.

The reconciler is a pure function:

    reconcile_cluster_membership(design_before, design_after, report=None) -> Design

The optional ``MutationReport`` lets pipelines hint at strand renames and
new-helix parents; without it the reconciler falls back to bp-range overlap
and lattice-neighbour proximity, which handles the common cases robustly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Union

from backend.core.models import (
    ClusterRigidTransform,
    Design,
    DomainRef,
    Strand,
)


# ── Public types ──────────────────────────────────────────────────────────────


@dataclass
class MutationReport:
    """Optional hints from a mutation pipeline to the reconciler.

    All fields are optional. A pipeline that fills any of them disambiguates
    the corresponding edge case; absent fields fall back to bp-range / lattice
    heuristics.

    Fields
    ------
    strand_id_renames:
        Map of pre-mutation ``strand_id`` to post-mutation ``strand_id`` for
        strands that were renamed in-place (e.g. ligation absorbing strand B
        into strand A's id, or nick splitting A into A and ``A_..._r``).
        The reconciler does not actually need this — it rebuilds DomainRefs
        from scratch by bp-range overlap — but pipelines may populate it for
        clarity.
    new_helix_origins:
        Map ``new_helix_id -> parent_helix_id``. The new helix inherits every
        cluster the parent belongs to. If parent is orphaned the new helix is
        also orphaned. Pass ``parent_helix_id=None`` to explicitly orphan a
        new helix even if it has lattice-adjacent neighbours (e.g. virtual
        linker bridge helices).
    cluster_disconnected:
        Create clusters for unassigned new lattice components (extrusion opt-in).
        Explicit parents and explicit orphans are excluded from creation.
    new_domain_origins:
        List of ``(new_ref, parent_ref)`` pairs. Used as a tie-breaker when a
        new domain's bp range overlaps two clusters' claims equally.
    deleted_strand_ids / deleted_helix_ids:
        Diagnostic only; the reconciler computes these from set diffs.
    """

    cluster_disconnected: bool = False
    strand_id_renames: dict[str, str] = field(default_factory=dict)
    new_helix_origins: dict[str, Optional[str]] = field(default_factory=dict)
    new_domain_origins: list[tuple[DomainRef, DomainRef]] = field(default_factory=list)
    deleted_strand_ids: set[str] = field(default_factory=set)
    deleted_helix_ids: set[str] = field(default_factory=set)


EMPTY_REPORT = MutationReport()


# ── Public API ────────────────────────────────────────────────────────────────


def reconcile_cluster_membership(
    design_before: Optional[Design],
    design_after: Design,
    report: Optional[MutationReport] = None,
) -> Design:
    """Repair cluster membership after a mutation.

    Returns a new Design with updated ``cluster_transforms``. Never mutates
    inputs. ``design_before`` may be ``None`` (e.g. on first import) — in
    that case the call is a no-op.
    """
    rep = report or EMPTY_REPORT
    if design_before is None:
        return design_after
    from backend.core.cluster_components import cluster_unassigned_components
    eligible = {h.id for h in design_after.helices} - {h.id for h in design_before.helices}
    eligible -= rep.new_helix_origins.keys()  # explicit parents/orphans remain authoritative
    def finish(result):
        return cluster_unassigned_components(result, eligible) if rep.cluster_disconnected else result
    if not design_before.cluster_transforms or not design_after.cluster_transforms:
        return finish(design_after)

    coverage = _build_coverage_map(design_before)
    domain_level_cluster_ids = {
        cid
        for cid, helix_map in coverage.items()
        if any(claim != "whole" for claim in helix_map.values())
    }

    new_helix_ids_by_cluster = _compute_helix_membership(
        design_before, design_after, rep
    )

    helix_ids_before_by_cluster: dict[str, set[str]] = {
        c.id: set(c.helix_ids) for c in design_before.cluster_transforms
    }

    new_domain_ids_by_cluster = _compute_domain_membership(
        design_after,
        coverage,
        new_helix_ids_by_cluster,
        helix_ids_before_by_cluster,
        domain_level_cluster_ids,
        rep,
    )

    updated_clusters: list[ClusterRigidTransform] = []
    for cluster in design_after.cluster_transforms:
        if cluster.id not in coverage:
            updated_clusters.append(cluster)
            continue

        helix_ids = new_helix_ids_by_cluster.get(cluster.id, list(cluster.helix_ids))
        if cluster.id in domain_level_cluster_ids:
            domain_ids = new_domain_ids_by_cluster.get(cluster.id, [])
        else:
            domain_ids = []

        updated_clusters.append(
            cluster.model_copy(
                update={
                    "helix_ids": helix_ids,
                    "domain_ids": domain_ids,
                }
            )
        )

    return finish(design_after.model_copy(update={"cluster_transforms": updated_clusters}))


# ── Coverage map ──────────────────────────────────────────────────────────────


_HelixClaim = Union[str, list[tuple[int, int]]]
"""Per-helix claim: ``"whole"`` for full-helix coverage, or a list of
``(lo_bp, hi_bp)`` tuples for explicit domain-level coverage.

Direction is intentionally excluded — the autodetect "non-scaffold majority
overlap" rule adds cross-direction staple domains to a scaffold cluster, so
the cluster's bp coverage spans both directions.  The deformation pipeline
then re-applies direction filtering per DomainRef when masking nucleotides,
which is unrelated to membership matching here.
"""


def _build_coverage_map(design: Design) -> dict[str, dict[str, _HelixClaim]]:
    """Build per-cluster, per-helix bp-range coverage from a design.

    For each cluster:
      * Every helix in ``cluster.helix_ids`` starts as ``"whole"``.
      * If the cluster has ``domain_ids``, those override ``"whole"`` to
        explicit ``(lo, hi)`` tuples on the helices the DomainRefs point to.
        Helices in ``helix_ids`` without any DomainRef stay ``"whole"`` (the
        "exclusive helix in mixed cluster" pattern).
    """
    strand_by_id: dict[str, Strand] = {s.id: s for s in design.strands}
    coverage: dict[str, dict[str, _HelixClaim]] = {}

    for cluster in design.cluster_transforms:
        cluster_cov: dict[str, _HelixClaim] = {
            hid: "whole" for hid in cluster.helix_ids
        }

        if cluster.domain_ids:
            ranges_by_helix: dict[str, list[tuple[int, int]]] = {}
            for dr in cluster.domain_ids:
                strand = strand_by_id.get(dr.strand_id)
                if (
                    strand is None
                    or dr.domain_index < 0
                    or dr.domain_index >= len(strand.domains)
                ):
                    continue
                dom = strand.domains[dr.domain_index]
                lo = min(dom.start_bp, dom.end_bp)
                hi = max(dom.start_bp, dom.end_bp)
                ranges_by_helix.setdefault(dom.helix_id, []).append((lo, hi))
            for hid, ranges in ranges_by_helix.items():
                cluster_cov[hid] = ranges

        coverage[cluster.id] = cluster_cov

    return coverage


# ── Helix membership ──────────────────────────────────────────────────────────


def _compute_helix_membership(
    design_before: Design,
    design_after: Design,
    report: MutationReport,
) -> dict[str, list[str]]:
    """Compute updated helix_ids per cluster.

    Rules
    -----
    * Helix that exists in both designs: keeps its current cluster membership
      (preserving manual edits, including manual orphans).
    * Helix in design_after only (new): inherits every cluster its origin
      helix belongs to. Origin = report hint, else a canonical lattice-component neighbor,
      else None (orphan). If origin is orphan, new helix is orphan.
    * Helix in design_before only (deleted): dropped from all clusters.
    """
    after_helix_ids = {h.id for h in design_after.helices}
    before_helix_ids = {h.id for h in design_before.helices}
    helix_membership_before: dict[str, set[str]] = {}
    for cluster in design_before.cluster_transforms:
        for hid in cluster.helix_ids:
            helix_membership_before.setdefault(hid, set()).add(cluster.id)

    from backend.core.cluster_components import lattice_cluster_graph, lattice_components
    graph = lattice_cluster_graph(design_after)
    new_helices = after_helix_ids - before_helix_ids
    inferred = {}
    # Propagate an existing neighbor through an entire new component, so only
    # touching cells are not accidentally inherited while the far side is orphaned.
    explicit_orphans = {hid for hid, parent in report.new_helix_origins.items() if parent is None}
    automatic = new_helices - explicit_orphans
    for component in lattice_components(graph, automatic):
        neighbors = set().union(*(graph[hid] for hid in component)) & before_helix_ids
        neighbors.update(report.new_helix_origins[hid] for hid in component
                         if report.new_helix_origins.get(hid) in before_helix_ids)
        claimed_neighbors = {hid for hid in neighbors if helix_membership_before.get(hid)}
        origin = min(claimed_neighbors or neighbors) if neighbors else None
        for hid in component:
            inferred[hid] = origin
    new_helix_targets: dict[str, set[str]] = {}
    for new_hid in sorted(new_helices):
        origin = report.new_helix_origins.get(new_hid) if new_hid in report.new_helix_origins else inferred.get(new_hid)
        new_helix_targets[new_hid] = set(helix_membership_before.get(origin, ()))
        helix = next(h for h in design_after.helices if h.id == new_hid)
        if helix.lattice_frame_id is not None:
            frame = next(f for f in design_after.lattice_frames if f.id == helix.lattice_frame_id)
            new_helix_targets[new_hid].add(frame.placement_cluster_id)

    result: dict[str, list[str]] = {}
    for cluster in design_before.cluster_transforms:
        kept = [
            hid
            for hid in cluster.helix_ids
            if hid in after_helix_ids
        ]
        for new_hid, target_cids in new_helix_targets.items():
            if (
                cluster.id in target_cids
                and new_hid not in kept
            ):
                kept.append(new_hid)
        result[cluster.id] = kept

    return result


def _infer_origin_via_lattice_neighbors(
    new_hid: str,
    design_after: Design,
    candidate_helix_ids: set[str],
) -> Optional[str]:
    """Return a canonical lattice neighbor in the same frame, if present."""
    from backend.core.cluster_components import lattice_cluster_graph
    neighbors = lattice_cluster_graph(design_after).get(new_hid, set()) & candidate_helix_ids
    return min(neighbors) if neighbors else None


# ── Domain membership ─────────────────────────────────────────────────────────


def _compute_domain_membership(
    design_after: Design,
    coverage: dict[str, dict[str, _HelixClaim]],
    helix_ids_by_cluster: dict[str, list[str]],
    helix_ids_before_by_cluster: dict[str, set[str]],
    domain_level_cluster_ids: set[str],
    report: MutationReport,
) -> dict[str, list[DomainRef]]:
    """Rebuild ``domain_ids`` for each domain-level cluster from scratch.

    Two-pass:

    Pass 1 — newly-inherited helices.  When a helix joins a domain-level
    cluster (it's in helix_ids_after but not helix_ids_before), the cluster
    claims every domain on that helix.  This matches the prior inline
    behaviour where overhang extrude added a DomainRef for the new domain on
    the new helix.  It also future-proofs against later strands sharing that
    helix being unintentionally swept up by the "exclusive helix fallback".

    Pass 2 — domains on pre-existing helices.  Bp-range overlap with each
    cluster's claim on that helix; largest overlap wins; ties broken by
    sorted cluster id.  Helices with a ``"whole"`` claim contribute no new
    DomainRefs (deformation falls back to whole-helix transform).
    """
    if not domain_level_cluster_ids:
        return {}

    new_refs_by_cluster: dict[str, list[DomainRef]] = {
        cid: [] for cid in domain_level_cluster_ids
    }

    newly_inherited_by_cluster: dict[str, set[str]] = {}
    for cid in domain_level_cluster_ids:
        before = helix_ids_before_by_cluster.get(cid, set())
        after = set(helix_ids_by_cluster.get(cid, []))
        newly_inherited_by_cluster[cid] = after - before

    domain_assigned: set[tuple[str, int]] = set()

    for strand in design_after.strands:
        for di, dom in enumerate(strand.domains):
            for cid in domain_level_cluster_ids:
                if dom.helix_id in newly_inherited_by_cluster[cid]:
                    new_refs_by_cluster[cid].append(
                        DomainRef(strand_id=strand.id, domain_index=di)
                    )
                    domain_assigned.add((strand.id, di))
                    break

    for strand in design_after.strands:
        for di, dom in enumerate(strand.domains):
            if (strand.id, di) in domain_assigned:
                continue
            hid = dom.helix_id
            lo = min(dom.start_bp, dom.end_bp)
            hi = max(dom.start_bp, dom.end_bp)

            candidates: list[tuple[int, str]] = []
            for cid in domain_level_cluster_ids:
                if hid not in helix_ids_by_cluster.get(cid, []):
                    continue
                claim = coverage[cid].get(hid)
                if claim is None or claim == "whole":
                    continue
                total = 0
                for clo, chi in claim:
                    ov_lo = max(lo, clo)
                    ov_hi = min(hi, chi)
                    if ov_hi >= ov_lo:
                        total += ov_hi - ov_lo + 1
                if total > 0:
                    candidates.append((total, cid))

            if not candidates:
                continue

            max_overlap = max(c[0] for c in candidates)
            tied = sorted(cid for ov, cid in candidates if ov == max_overlap)
            chosen = tied[0]
            new_refs_by_cluster[chosen].append(
                DomainRef(strand_id=strand.id, domain_index=di)
            )

    return new_refs_by_cluster
