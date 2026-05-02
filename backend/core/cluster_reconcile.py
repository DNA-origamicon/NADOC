"""
Incremental cluster membership reconciliation.

After a topology mutation (add helix, place crossover, nick, ligate, extrude
overhang, etc.), this module repairs cluster membership so that:

  * New helices/domains are added to the cluster of their nearest existing
    neighbor and therefore inherit that cluster's translation/rotation/pivot.
  * Stale ``DomainRef`` entries (strand_id gone, domain_index out of range)
    are dropped.
  * Existing cluster membership the user manually edited is preserved.
  * Cluster transforms (translation/rotation/pivot) are never modified.
  * Clusters are never created, deleted, split, or merged.

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
    new_domain_origins:
        List of ``(new_ref, parent_ref)`` pairs. Used as a tie-breaker when a
        new domain's bp range overlaps two clusters' claims equally.
    deleted_strand_ids / deleted_helix_ids:
        Diagnostic only; the reconciler computes these from set diffs.
    """

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
    if design_before is None or not design_before.cluster_transforms:
        return design_after
    if not design_after.cluster_transforms:
        return design_after

    rep = report or EMPTY_REPORT

    coverage = _build_coverage_map(design_before)
    domain_level_cluster_ids = {
        cid for cid, helix_map in coverage.items()
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
            cluster.model_copy(update={
                "helix_ids": helix_ids,
                "domain_ids": domain_ids,
            })
        )

    return design_after.model_copy(update={"cluster_transforms": updated_clusters})


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
        cluster_cov: dict[str, _HelixClaim] = {hid: "whole" for hid in cluster.helix_ids}

        if cluster.domain_ids:
            ranges_by_helix: dict[str, list[tuple[int, int]]] = {}
            for dr in cluster.domain_ids:
                strand = strand_by_id.get(dr.strand_id)
                if strand is None or dr.domain_index < 0 or dr.domain_index >= len(strand.domains):
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
      helix belongs to. Origin = report hint, else lattice-neighbour majority,
      else None (orphan). If origin is orphan, new helix is orphan.
    * Helix in design_before only (deleted): dropped from all clusters.
    """
    after_helix_ids = {h.id for h in design_after.helices}
    before_helix_ids = {h.id for h in design_before.helices}

    helix_membership_before: dict[str, set[str]] = {}
    for cluster in design_before.cluster_transforms:
        for hid in cluster.helix_ids:
            helix_membership_before.setdefault(hid, set()).add(cluster.id)

    new_helices = after_helix_ids - before_helix_ids
    new_helix_targets: dict[str, set[str]] = {}
    for new_hid in new_helices:
        if new_hid in report.new_helix_origins:
            origin = report.new_helix_origins[new_hid]
            # Explicit None means the route wants this helix orphaned
            # regardless of lattice neighbours.
        else:
            origin = _infer_origin_via_lattice_neighbors(new_hid, design_after, before_helix_ids)
        if origin is not None and origin in helix_membership_before:
            new_helix_targets[new_hid] = helix_membership_before[origin]
        else:
            new_helix_targets[new_hid] = set()  # orphan

    result: dict[str, list[str]] = {}
    for cluster in design_before.cluster_transforms:
        kept = [hid for hid in cluster.helix_ids if hid in after_helix_ids]
        for new_hid, target_cids in new_helix_targets.items():
            if cluster.id in target_cids and new_hid not in kept:
                kept.append(new_hid)
        result[cluster.id] = kept

    return result


def _infer_origin_via_lattice_neighbors(
    new_hid: str,
    design_after: Design,
    candidate_helix_ids: set[str],
) -> Optional[str]:
    """Return the existing helix closest in lattice grid_pos to ``new_hid``.

    Considers only helices in ``candidate_helix_ids`` (typically the helices
    that existed pre-mutation). Returns ``None`` if no candidate has a known
    grid_pos within Manhattan distance 2.
    """
    new_helix = next((h for h in design_after.helices if h.id == new_hid), None)
    if new_helix is None or new_helix.grid_pos is None:
        return None

    new_row, new_col = new_helix.grid_pos
    best: Optional[tuple[int, str]] = None
    for h in design_after.helices:
        if h.id == new_hid or h.id not in candidate_helix_ids:
            continue
        if h.grid_pos is None:
            continue
        dist = abs(h.grid_pos[0] - new_row) + abs(h.grid_pos[1] - new_col)
        if dist > 2:
            continue
        if best is None or dist < best[0] or (dist == best[0] and h.id < best[1]):
            best = (dist, h.id)
    return best[1] if best else None


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
                for (clo, chi) in claim:
                    ov_lo = max(lo, clo)
                    ov_hi = min(hi, chi)
                    if ov_hi >= ov_lo:
                        total += (ov_hi - ov_lo + 1)
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
