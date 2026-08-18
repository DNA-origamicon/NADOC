"""Cluster auto-detection — pure topology/geometry clustering of a Design's helices.

Extracted verbatim from ``backend/api/crud.py``'s "Internal helpers" block
(carve-up Refactor #34). These functions take a ``Design`` and return a new
``Design`` with ``cluster_transforms`` populated; they touch no API/state layer
and perform no file IO, so they live in ``backend/core`` (the dependency arrow is
api → core, never the reverse).

Public entry points (imported back by crud.py):
  - ``_cluster_bundle_regions`` — one cluster per lattice-connected region of a
    freshly-built bundle (Onshape-style disjoint-sketch → separate body).
  - ``_autodetect_clusters`` — produce both scaffold-routing + geometry clusters.

The other three (``_cluster_by_lattice_neighbors``, ``_cluster_by_scaffold_routing``,
``_geometry_clusters_multi_scaffold``) are module-private helpers of
``_autodetect_clusters`` (no caller outside this module).

NOTE: ``_ensure_default_cluster`` stays in crud.py — it calls
``design_state.set_design_silent`` (api-state) and is shared cross-region.
"""

from backend.core.models import Design, LatticeType, StrandType


def _cluster_bundle_regions(design: Design) -> Design:
    """Assign one cluster per lattice-connected region of a freshly-built bundle.

    Onshape-style "extrude disjoint sketches → separate part bodies": when a
    bundle's cells form two or more lattice-disconnected groups (e.g. the two
    arms of a hinge separated by an empty row gap), each group becomes its own
    cluster so it can be posed and hull-rendered independently.

    A single connected region keeps the historical behaviour exactly: ONE
    cluster named "Cluster 1" with ``is_default=True`` (identical to
    ``_ensure_default_cluster``), so deformation arm-scoping, assembly sorting
    and the hull whole-part skip all behave as before. Only multi-region
    bundles produce multiple ``is_default=False`` clusters.

    Pure function — returns a new Design with ``cluster_transforms`` set. A
    no-op (returns ``design`` unchanged) if clusters already exist or there are
    no clusterable helices. Adjacency uses canonical crossover neighbours; a
    fresh bundle carries no crossovers or forced ligations, so this is pure
    lattice adjacency.
    """
    if design.cluster_transforms or not design.helices:
        return design
    from backend.core.models import ClusterRigidTransform
    from backend.core.crossover_positions import crossover_neighbor
    from backend.core.constants import HC_CROSSOVER_PERIOD, SQ_CROSSOVER_PERIOD

    ref_ids = design.reference_helix_ids()
    gridded = [
        h for h in design.helices if h.grid_pos is not None and h.id not in ref_ids
    ]
    if not gridded:
        return design  # nothing clusterable; _ensure_default_cluster handles it

    cell_to_id: dict[tuple[int, int], str] = {
        (h.grid_pos[0], h.grid_pos[1]): h.id for h in gridded
    }
    helix_ids = {h.id for h in gridded}
    period = (
        HC_CROSSOVER_PERIOD
        if design.lattice_type == LatticeType.HONEYCOMB
        else SQ_CROSSOVER_PERIOD
    )

    adj: dict[str, set[str]] = {hid: set() for hid in helix_ids}
    for h in gridded:
        row, col = h.grid_pos
        for is_scaf in (False, True):
            for idx in range(period):
                nb = crossover_neighbor(
                    design.lattice_type, row, col, idx, is_scaffold=is_scaf
                )
                if nb is not None and nb in cell_to_id:
                    nb_id = cell_to_id[nb]
                    if nb_id != h.id:
                        adj[h.id].add(nb_id)
                        adj[nb_id].add(h.id)

    visited: set[str] = set()
    components: list[list[str]] = []
    for hid in helix_ids:
        if hid in visited:
            continue
        comp: list[str] = []
        queue = [hid]
        visited.add(hid)
        while queue:
            cur = queue.pop(0)
            comp.append(cur)
            for nb in adj[cur]:
                if nb not in visited:
                    visited.add(nb)
                    queue.append(nb)
        components.append(sorted(comp))

    # One connected region → leave clusters empty so the downstream
    # _ensure_default_cluster builds the single is_default umbrella, exactly as
    # before (preserves deformation/assembly/hull fallback behaviour).
    if len(components) <= 1:
        return design

    components.sort(key=lambda c: c[0])
    clusters = [
        ClusterRigidTransform(
            name=f"Cluster {n}", is_default=False, auto_created=True, helix_ids=hids
        )
        for n, hids in enumerate(components, start=1)
    ]
    return design.copy_with(cluster_transforms=clusters)


def _cluster_by_lattice_neighbors(design: Design) -> Design:
    """Assign helices to clusters in three phases.

    Phase 1 — exclusive-scaffold helices cluster by same-scaffold lattice adjacency:
      Among scaffold-bearing helices, those that appear in EXACTLY ONE scaffold
      strand ("exclusive" helices) form Phase-1 clusters.  Two exclusive helices
      are connected if they are lattice-adjacent AND belong to the same scaffold
      strand.  Scaffold-strand identity is the module boundary: helices from two
      different scaffold loops cannot be merged, even if physically adjacent.

      ForcedLigation-only edges (no canonical Crossover between that pair) are
      removed, treating the forced connection as a cluster/joint boundary.

      Fallback: if there are no scaffold strands, all helices are treated as
      exclusive to one pseudo-strand (plain lattice-adjacency clustering).

    Phase 2 — bridge helices form independent connector clusters:
      Helices shared between 2+ scaffold strands are never absorbed into a
      Phase-1 cluster.  They cluster among themselves by lattice adjacency,
      producing one or more "connector" clusters that can be moved/articulated
      independently.  FL-only edges are also removed here.

    Phase 3 — scaffold-less helices absorbed by crossover majority:
      Helices on NO scaffold strand are each assigned to the Phase-1 or Phase-2
      cluster with which they share the most canonical crossovers.  Helices with
      no qualifying crossovers group among themselves by lattice adjacency.

    Helices without grid_pos are skipped.
    Clusters are named "Cluster 1", "Cluster 2", … sorted by minimum helix ID.
    """
    from backend.core.models import ClusterRigidTransform, ForcedLigation  # noqa: F401
    from backend.core.crossover_positions import crossover_neighbor
    from backend.core.constants import HC_CROSSOVER_PERIOD, SQ_CROSSOVER_PERIOD

    gridded = [h for h in design.helices if h.grid_pos is not None]
    if not gridded:
        return design

    cell_to_id: dict[tuple[int, int], str] = {
        (h.grid_pos[0], h.grid_pos[1]): h.id for h in gridded
    }
    period = (
        HC_CROSSOVER_PERIOD
        if design.lattice_type == LatticeType.HONEYCOMB
        else SQ_CROSSOVER_PERIOD
    )

    crossover_pairs: set[frozenset] = {
        frozenset({xo.half_a.helix_id, xo.half_b.helix_id}) for xo in design.crossovers
    }
    fl_pairs: set[frozenset] = {
        frozenset({fl.three_prime_helix_id, fl.five_prime_helix_id})
        for fl in design.forced_ligations
    }

    def _lattice_adj(helix_ids: set[str]) -> dict[str, set[str]]:
        """Build lattice-adjacency graph restricted to helix_ids, removing FL-only edges."""
        adj: dict[str, set[str]] = {hid: set() for hid in helix_ids}
        for h in gridded:
            if h.id not in helix_ids:
                continue
            row, col = h.grid_pos
            for is_scaf in (False, True):
                for idx in range(period):
                    nb = crossover_neighbor(
                        design.lattice_type, row, col, idx, is_scaffold=is_scaf
                    )
                    if nb is not None and nb in cell_to_id:
                        nb_id = cell_to_id[nb]
                        if nb_id in helix_ids and nb_id != h.id:
                            pair = frozenset({h.id, nb_id})
                            if pair not in fl_pairs or pair in crossover_pairs:
                                adj[h.id].add(nb_id)
                                adj[nb_id].add(h.id)
        return adj

    def _connected_components(
        helix_ids: set[str], adj: dict[str, set[str]]
    ) -> list[list[str]]:
        visited: set[str] = set()
        comps: list[list[str]] = []
        for hid in helix_ids:
            if hid in visited:
                continue
            comp: list[str] = []
            q = [hid]
            visited.add(hid)
            while q:
                cur = q.pop(0)
                comp.append(cur)
                for nb in adj[cur]:
                    if nb not in visited:
                        visited.add(nb)
                        q.append(nb)
            comps.append(comp)
        return comps

    # ── Phase 1: exclusive-scaffold lattice adjacency ─────────────────────────

    # Only scaffold strands that span at least this many distinct helices are
    # treated as "module scaffolds" — smaller fragments (overhangs, connectors,
    # cadnano import artefacts) are ignored for module-boundary purposes.
    _MIN_MODULE_HELICES = 3

    # Build per-helix set of *module* scaffold indices (ignoring tiny fragments).
    h_to_scaf: dict[str, set[int]] = {}
    for i, s in enumerate(design.strands):
        if s.strand_type != StrandType.SCAFFOLD:
            continue
        unique_helices = {d.helix_id for d in s.domains}
        if len(unique_helices) < _MIN_MODULE_HELICES:
            continue  # tiny fragment — not a module boundary
        for hid in unique_helices:
            h_to_scaf.setdefault(hid, set()).add(i)

    if h_to_scaf:
        # Exclusive: helix on exactly one module scaffold strand.
        exclusive: dict[str, int] = {
            hid: next(iter(scafs))
            for hid, scafs in h_to_scaf.items()
            if len(scafs) == 1
        }
        phase1_ids: set[str] = set(exclusive.keys())
        bridge_ids: set[str] = {
            hid for hid, scafs in h_to_scaf.items() if len(scafs) > 1
        }
    else:
        # No module scaffold strands: treat all gridded helices as one pseudo-scaffold.
        exclusive = {h.id: 0 for h in gridded}
        phase1_ids = {h.id for h in gridded}
        bridge_ids = set()

    # Same-scaffold lattice adjacency only.
    p1_adj = _lattice_adj(phase1_ids)
    for hid in list(p1_adj.keys()):
        p1_adj[hid] = {nb for nb in p1_adj[hid] if exclusive.get(nb) == exclusive[hid]}

    components: list[list[str]] = _connected_components(phase1_ids, p1_adj)

    # ── Phase 2: domain-level assignment of bridge helices ────────────────────
    # Bridge helices are split between scaffold clusters at the bp boundary where
    # one module scaffold ends and the other begins.  Each domain on a bridge
    # helix is assigned to the Phase-1 cluster of the scaffold that covers the
    # majority of that domain's bp range.  No separate "connector" cluster is
    # created; instead domain_ids on the Phase-1 clusters carry the bridge refs.

    from backend.core.models import DomainRef as _DR

    # helix_to_comp: Phase-1 exclusive helices only (reused in Phase 3).
    helix_to_comp: dict[str, int] = {
        hid: i for i, comp in enumerate(components) for hid in comp
    }

    # scaf_cov[bridge_hid][scaf_idx] = (lo, hi) merged across all scaffold domains
    # of that module scaffold on that bridge helix.
    scaf_cov: dict[str, dict[int, tuple[int, int]]] = {}
    for i, s in enumerate(design.strands):
        if s.strand_type != StrandType.SCAFFOLD:
            continue
        unique_h = {d.helix_id for d in s.domains}
        if len(unique_h) < _MIN_MODULE_HELICES:
            continue
        for d in s.domains:
            if d.helix_id not in bridge_ids:
                continue
            lo, hi = min(d.start_bp, d.end_bp), max(d.start_bp, d.end_bp)
            sc = scaf_cov.setdefault(d.helix_id, {})
            if i in sc:
                old_lo, old_hi = sc[i]
                sc[i] = (min(lo, old_lo), max(hi, old_hi))
            else:
                sc[i] = (lo, hi)

    # scaf_to_cis[scaf_idx] = list of Phase-1 component indices that belong to
    # that module scaffold (usually exactly one).
    scaf_to_cis: dict[int, list[int]] = {}
    for hid, scaf_idx in exclusive.items():
        ci = helix_to_comp[hid]
        scaf_to_cis.setdefault(scaf_idx, [])
        if ci not in scaf_to_cis[scaf_idx]:
            scaf_to_cis[scaf_idx].append(ci)

    comp_domain_ids: dict[int, list] = {i: [] for i in range(len(components))}
    bridge_ci_map: dict[str, set[int]] = {}  # bridge_hid → comp indices that own it

    # Pre-build per-bridge-helix domain lookup to avoid O(n_strands) scan per bridge.
    bridge_domains: dict[str, list[tuple[int, int]]] = {hid: [] for hid in bridge_ids}
    for si, strand in enumerate(design.strands):
        for di, dom in enumerate(strand.domains):
            if dom.helix_id in bridge_ids:
                bridge_domains[dom.helix_id].append((si, di))

    for bridge_h in gridded:
        if bridge_h.id not in bridge_ids:
            continue
        cov = scaf_cov.get(bridge_h.id, {})
        if not cov:
            continue

        for si, di in bridge_domains[bridge_h.id]:
            strand = design.strands[si]
            dom = strand.domains[di]
            dom_lo = min(dom.start_bp, dom.end_bp)
            dom_hi = max(dom.start_bp, dom.end_bp)

            # Find the module scaffold covering the most of this domain's bp range.
            best_scaf, best_overlap = None, 0
            for scaf_idx, (clo, chi) in cov.items():
                overlap = max(0, min(dom_hi, chi) - max(dom_lo, clo))
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_scaf = scaf_idx

            if best_scaf is None:
                continue

            # Map to Phase-1 component, using crossover count when ambiguous.
            ci_list = scaf_to_cis.get(best_scaf, [])
            if not ci_list:
                continue
            if len(ci_list) == 1:
                best_ci = ci_list[0]
            else:
                comp_xo: dict[int, int] = {}
                for xo in design.crossovers:
                    if xo.half_a.helix_id == bridge_h.id:
                        partner = xo.half_b.helix_id
                    elif xo.half_b.helix_id == bridge_h.id:
                        partner = xo.half_a.helix_id
                    else:
                        continue
                    if partner in helix_to_comp and helix_to_comp[partner] in ci_list:
                        cxo = helix_to_comp[partner]
                        comp_xo[cxo] = comp_xo.get(cxo, 0) + 1
                best_ci = (
                    max(comp_xo, key=lambda c: comp_xo[c]) if comp_xo else ci_list[0]
                )

            comp_domain_ids[best_ci].append(_DR(strand_id=strand.id, domain_index=di))
            bridge_ci_map.setdefault(bridge_h.id, set()).add(best_ci)

    # ── Phase 3: absorb scaffold-less helices by crossover majority ────────────
    # Only crossovers to Phase-1 exclusive helices are used; orphan helices with
    # no Phase-1 crossover partners are grouped by lattice adjacency.

    orphan_helices = [
        h for h in gridded if h.id not in phase1_ids and h.id not in bridge_ids
    ]
    absorbed: dict[str, int] = {}
    unconnected: list = []

    for h in orphan_helices:
        comp_xo: dict[int, int] = {}
        for xo in design.crossovers:
            if xo.half_a.helix_id == h.id:
                partner = xo.half_b.helix_id
            elif xo.half_b.helix_id == h.id:
                partner = xo.half_a.helix_id
            else:
                continue
            if partner in helix_to_comp:
                ci = helix_to_comp[partner]
                comp_xo[ci] = comp_xo.get(ci, 0) + 1
        if comp_xo:
            absorbed[h.id] = max(comp_xo, key=lambda ci: comp_xo[ci])
        else:
            unconnected.append(h)

    # Unconnected orphans group among themselves by lattice adjacency.
    unconn_groups: list[list[str]] = []
    if unconnected:
        unconn_ids = {h.id for h in unconnected}
        u_adj = _lattice_adj(unconn_ids)
        unconn_groups = _connected_components(unconn_ids, u_adj)

    # ── Rebuild final components ───────────────────────────────────────────────

    comp_helices: dict[int, list[str]] = {
        i: list(comp) for i, comp in enumerate(components)
    }
    # Add bridge helix IDs to every cluster that has domain refs on them.
    for bridge_hid, ci_set in bridge_ci_map.items():
        for ci in ci_set:
            if bridge_hid not in comp_helices[ci]:
                comp_helices[ci].append(bridge_hid)
    for hid, ci in absorbed.items():
        comp_helices[ci].append(hid)
    offset = len(components)
    for i, grp in enumerate(unconn_groups):
        comp_helices[offset + i] = grp

    # Sort clusters by minimum helix id, preserving domain_ids pairing.
    indexed = [(ci, sorted(comp_helices[ci])) for ci in comp_helices]
    indexed.sort(key=lambda x: x[1][0] if x[1] else "")
    clusters = [
        ClusterRigidTransform(
            name=f"Cluster {n}",
            is_default=False,
            auto_created=True,
            helix_ids=hids,
            domain_ids=comp_domain_ids.get(ci, []),
        )
        for n, (ci, hids) in enumerate(indexed, start=1)
    ]
    return design.copy_with(cluster_transforms=clusters)


def _cluster_by_scaffold_routing(design: Design) -> Design:
    """Create one cluster per module scaffold strand (topology-based).

    Each cluster contains the scaffold strand's helices and all non-scaffold
    domains that pair with it, determined by bp-range overlap on the same helix.
    Bridge helices (shared by 2+ module scaffolds) are split at domain level via
    DomainRef entries so both clusters can coexist on the same helix.

    Orphan helices (not visited by any scaffold) are absorbed into the scaffold
    cluster with which they share the most canonical crossovers.

    Falls back to _cluster_by_lattice_neighbors when no module scaffold is
    detected (scaffold-less designs or all-tiny-fragment imports).
    """
    from backend.core.models import ClusterRigidTransform, DomainRef as _DR

    _MIN_MODULE_HELICES = 3

    gridded = [h for h in design.helices if h.grid_pos is not None]
    if not gridded:
        return design

    # ── Identify module scaffolds ─────────────────────────────────────────────
    module_scaffolds: list[int] = []
    for i, s in enumerate(design.strands):
        if s.strand_type != StrandType.SCAFFOLD:
            continue
        if len({d.helix_id for d in s.domains}) >= _MIN_MODULE_HELICES:
            module_scaffolds.append(i)

    if not module_scaffolds:
        return design.copy_with(cluster_transforms=[])

    # ── Build bp coverage per scaffold per helix ──────────────────────────────
    scaf_cov: dict[int, dict[str, tuple[int, int]]] = {
        si: {} for si in module_scaffolds
    }
    scaf_helix_ids: dict[int, set[str]] = {si: set() for si in module_scaffolds}

    for si in module_scaffolds:
        s = design.strands[si]
        for d in s.domains:
            hid = d.helix_id
            scaf_helix_ids[si].add(hid)
            lo, hi = min(d.start_bp, d.end_bp), max(d.start_bp, d.end_bp)
            if hid in scaf_cov[si]:
                olo, ohi = scaf_cov[si][hid]
                scaf_cov[si][hid] = (min(lo, olo), max(hi, ohi))
            else:
                scaf_cov[si][hid] = (lo, hi)

    # ── Classify helices as exclusive or bridge ───────────────────────────────
    h_to_scaf: dict[str, set[int]] = {}
    for si in module_scaffolds:
        for hid in scaf_helix_ids[si]:
            h_to_scaf.setdefault(hid, set()).add(si)

    bridge_ids: set[str] = {hid for hid, scafs in h_to_scaf.items() if len(scafs) > 1}

    # ── Initialize cluster structures ─────────────────────────────────────────
    cluster_helix_ids: dict[int, set[str]] = {
        si: set(scaf_helix_ids[si]) for si in module_scaffolds
    }
    cluster_domain_ids: dict[int, list] = {si: [] for si in module_scaffolds}

    # Scaffold's own domains on bridge helices need explicit DomainRef entries.
    for si in module_scaffolds:
        s = design.strands[si]
        for di, d in enumerate(s.domains):
            if d.helix_id in bridge_ids:
                cluster_domain_ids[si].append(_DR(strand_id=s.id, domain_index=di))

    # ── Assign non-scaffold domains by majority scaffold bp overlap ───────────
    for si2, strand in enumerate(design.strands):
        if strand.is_scaffold:
            continue
        for di, dom in enumerate(strand.domains):
            hid = dom.helix_id
            if hid not in h_to_scaf:
                continue  # helix not visited by any module scaffold
            dom_lo = min(dom.start_bp, dom.end_bp)
            dom_hi = max(dom.start_bp, dom.end_bp)

            best_si, best_overlap = None, 0
            for si_cand in h_to_scaf[hid]:
                cov = scaf_cov[si_cand].get(hid)
                if cov is None:
                    continue
                clo, chi = cov
                overlap = max(0, min(dom_hi, chi) - max(dom_lo, clo))
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_si = si_cand

            if best_si is None:
                continue

            if hid in bridge_ids:
                # Bridge helix: domain ref needed to disambiguate between clusters.
                cluster_domain_ids[best_si].append(
                    _DR(strand_id=strand.id, domain_index=di)
                )
            # Exclusive helix: implicitly covered by helix_ids — no DomainRef needed.

    # ── Absorb orphan helices (no scaffold) by crossover majority ─────────────
    for h in gridded:
        if h.id in h_to_scaf:
            continue
        xo_counts: dict[int, int] = {}
        for xo in design.crossovers:
            if xo.half_a.helix_id == h.id:
                partner = xo.half_b.helix_id
            elif xo.half_b.helix_id == h.id:
                partner = xo.half_a.helix_id
            else:
                continue
            for si in module_scaffolds:
                if partner in cluster_helix_ids[si]:
                    xo_counts[si] = xo_counts.get(si, 0) + 1
                    break
        if xo_counts:
            best_si = max(xo_counts, key=lambda si: xo_counts[si])
            cluster_helix_ids[best_si].add(h.id)

    # ── Build ClusterRigidTransform objects ───────────────────────────────────
    scaffolds_sorted = sorted(
        module_scaffolds,
        key=lambda si: (
            sorted(cluster_helix_ids[si])[0] if cluster_helix_ids[si] else ""
        ),
    )
    clusters = [
        ClusterRigidTransform(
            name=f"Scaffold Cluster {n}",
            is_default=False,
            auto_created=True,
            helix_ids=sorted(cluster_helix_ids[si]),
            domain_ids=cluster_domain_ids[si],
        )
        for n, si in enumerate(scaffolds_sorted, start=1)
    ]
    return design.copy_with(cluster_transforms=clusters)


def _geometry_clusters_multi_scaffold(design: Design) -> Design:
    """Geometry clusters for designs with 2+ module scaffolds.

    One cluster per module scaffold.  Unlike scaffold clusters, bridge helices
    (shared by multiple scaffolds) are assigned WHOLE to whichever scaffold has
    the most bp coverage on them — no domain_ids split.  This keeps each scaffold's
    entire structural territory as one rigid-body geometry cluster.
    """
    from backend.core.models import ClusterRigidTransform

    _MIN_MODULE_HELICES = 3
    gridded = [h for h in design.helices if h.grid_pos is not None]

    module_scaffolds: list[int] = [
        i
        for i, s in enumerate(design.strands)
        if s.is_scaffold and len({d.helix_id for d in s.domains}) >= _MIN_MODULE_HELICES
    ]

    scaf_cov: dict[int, dict[str, tuple[int, int]]] = {
        si: {} for si in module_scaffolds
    }
    scaf_helix_ids: dict[int, set[str]] = {si: set() for si in module_scaffolds}
    for si in module_scaffolds:
        for d in design.strands[si].domains:
            hid = d.helix_id
            scaf_helix_ids[si].add(hid)
            lo, hi = min(d.start_bp, d.end_bp), max(d.start_bp, d.end_bp)
            if hid in scaf_cov[si]:
                olo, ohi = scaf_cov[si][hid]
                scaf_cov[si][hid] = (min(lo, olo), max(hi, ohi))
            else:
                scaf_cov[si][hid] = (lo, hi)

    h_to_scaf: dict[str, set[int]] = {}
    for si in module_scaffolds:
        for hid in scaf_helix_ids[si]:
            h_to_scaf.setdefault(hid, set()).add(si)

    bridge_ids: set[str] = {hid for hid, scafs in h_to_scaf.items() if len(scafs) > 1}

    # Start with each scaffold's exclusive helices only.
    cluster_helix_ids: dict[int, set[str]] = {
        si: {hid for hid in scaf_helix_ids[si] if hid not in bridge_ids}
        for si in module_scaffolds
    }

    # Assign each bridge helix WHOLE to the scaffold with the most bp coverage.
    for hid in bridge_ids:
        best_si, best_len = None, 0
        for si in h_to_scaf.get(hid, set()):
            cov = scaf_cov[si].get(hid)
            if cov:
                length = cov[1] - cov[0]
                if length > best_len:
                    best_len = length
                    best_si = si
        if best_si is not None:
            cluster_helix_ids[best_si].add(hid)

    # Absorb orphan helices (not visited by any module scaffold) by crossover majority.
    for h in gridded:
        if h.id in h_to_scaf:
            continue
        xo_counts: dict[int, int] = {}
        for xo in design.crossovers:
            if xo.half_a.helix_id == h.id:
                partner = xo.half_b.helix_id
            elif xo.half_b.helix_id == h.id:
                partner = xo.half_a.helix_id
            else:
                continue
            for si in module_scaffolds:
                if partner in cluster_helix_ids[si]:
                    xo_counts[si] = xo_counts.get(si, 0) + 1
                    break
        if xo_counts:
            best_si = max(xo_counts, key=lambda si: xo_counts[si])
            cluster_helix_ids[best_si].add(h.id)

    scaffolds_sorted = sorted(
        module_scaffolds,
        key=lambda si: (
            sorted(cluster_helix_ids[si])[0] if cluster_helix_ids[si] else ""
        ),
    )
    clusters = [
        ClusterRigidTransform(
            name=f"Geometry Cluster {n}",
            is_default=False,
            auto_created=True,
            helix_ids=sorted(cluster_helix_ids[si]),
            domain_ids=[],
        )
        for n, si in enumerate(scaffolds_sorted, start=1)
    ]
    return design.copy_with(cluster_transforms=clusters)


def _autodetect_clusters(design: Design) -> Design:
    """Produce both scaffold-routing clusters and geometry clusters.

    Scaffold clusters (one per module scaffold, with domain_ids for bridge helices)
    are named "Scaffold Cluster N".

    Geometry clusters are named "Geometry Cluster N" and use different rules
    depending on scaffold count:
      - 0 or 1 module scaffold: lattice-adjacency with FL-only edge removal
        (same rigid-body rules as the hinge — finds structural sub-segments).
      - 2+ module scaffolds: one cluster per scaffold, bridge helices assigned
        WHOLE to the scaffold with the most bp coverage (no domain_ids split).

    Both sets are always produced and combined into design.cluster_transforms.
    """
    _MIN_MODULE_HELICES = 3
    n_module_scaffolds = sum(
        1
        for s in design.strands
        if s.is_scaffold and len({d.helix_id for d in s.domains}) >= _MIN_MODULE_HELICES
    )

    scaf_design = _cluster_by_scaffold_routing(design)
    scaffold_clusters = list(scaf_design.cluster_transforms)

    if n_module_scaffolds >= 2:
        geo_design = _geometry_clusters_multi_scaffold(design)
        geometry_clusters = list(geo_design.cluster_transforms)
    else:
        geo_design = _cluster_by_lattice_neighbors(design)
        geometry_clusters = [
            ct.model_copy(update={"name": f"Geometry Cluster {n}"})
            for n, ct in enumerate(geo_design.cluster_transforms, start=1)
        ]

    return design.copy_with(cluster_transforms=scaffold_clusters + geometry_clusters)


def repair_empty_auto_clusters(design: Design) -> Design:
    """Rebuild membership for the legacy/corrupt all-empty auto-cluster state.

    Some imported designs retained the autodetected cluster names and display
    metadata after reference extraction, but lost every ``helix_ids`` and
    ``domain_ids`` entry.  Their non-empty cluster array then prevented the
    ordinary default-cluster bootstrap, leaving cluster coloring/selection with
    no resolvable members.  Repair only this unambiguous state; any user cluster
    or any surviving membership makes the function a no-op.
    """
    existing = list(design.cluster_transforms)
    if not existing or any(
        not c.auto_created or c.helix_ids or c.domain_ids for c in existing
    ):
        return design

    detected = _autodetect_clusters(
        design.copy_with(cluster_transforms=[])
    ).cluster_transforms
    reference_helices = design.reference_helix_ids()
    domain_helix = {
        (strand.id, index): domain.helix_id
        for strand in design.strands
        for index, domain in enumerate(strand.domains)
    }
    old_by_name = {cluster.name: cluster for cluster in existing}
    repaired = []
    for cluster in detected:
        helix_ids = [hid for hid in cluster.helix_ids if hid not in reference_helices]
        domain_ids = [
            ref for ref in cluster.domain_ids
            if domain_helix.get((ref.strand_id, ref.domain_index)) not in reference_helices
        ]
        if not helix_ids and not domain_ids:
            continue
        old = old_by_name.get(cluster.name)
        updates = {"helix_ids": helix_ids, "domain_ids": domain_ids}
        if old is not None:
            updates.update({
                "id": old.id,
                "color": old.color,
                "opacity": old.opacity,
                "translation": old.translation,
                "rotation": old.rotation,
                "pivot": old.pivot,
            })
        repaired.append(cluster.model_copy(update=updates))
    return design.copy_with(cluster_transforms=repaired)
