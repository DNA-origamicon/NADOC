"""Frame-aware lattice components and additive cluster repair.

These helpers change membership only; existing poses and topology are untouched.
"""

from collections import defaultdict
import json
from uuid import NAMESPACE_URL, uuid5

from backend.core.constants import HC_CROSSOVER_PERIOD, SQ_CROSSOVER_PERIOD
from backend.core.crossover_positions import crossover_neighbor
from backend.core.models import ClusterRigidTransform, Design, LatticeType


def lattice_cluster_graph(design: Design) -> dict[str, set[str]]:
    """Canonical lattice edges, separated by frame and legacy axial direction.

    Keep every helix at a cell (continuations may share cells). Reference and
    virtual linker helices are not movable lattice bodies. Forced-ligation-only
    edges remain articulation boundaries, matching geometry autodetection.
    """
    refs = design.reference_helix_ids()
    helices = [
        h
        for h in design.helices
        if h.grid_pos is not None
        and h.id not in refs
        and not h.id.startswith("__lnk__")
    ]
    cells = defaultdict(list)
    keys = {}
    for h in helices:
        if h.lattice_frame_id is not None:
            frame = ("frame", h.lattice_frame_id)
        else:
            delta = [getattr(h.axis_end, a) - getattr(h.axis_start, a) for a in "xyz"]
            length = sum(v * v for v in delta) ** 0.5
            direction = (
                tuple(round(v / length, 6) for v in delta) if length else (0, 0, 0)
            )
            # Parallel and antiparallel helices share the same cross-section.
            if next((v for v in direction if v), 0) < 0:
                direction = tuple(-v for v in direction)
            frame = ("legacy", direction)
        keys[h.id] = frame
        cells[(frame, *h.grid_pos)].append(h.id)
    graph = {h.id: set() for h in helices}
    canonical = {
        frozenset((x.half_a.helix_id, x.half_b.helix_id)) for x in design.crossovers
    }
    forced = {
        frozenset((x.three_prime_helix_id, x.five_prime_helix_id))
        for x in design.forced_ligations
    }
    period = (
        HC_CROSSOVER_PERIOD
        if design.lattice_type == LatticeType.HONEYCOMB
        else SQ_CROSSOVER_PERIOD
    )
    for h in helices:
        for scaffold in (False, True):
            for index in range(period):
                cell = crossover_neighbor(
                    design.lattice_type, *h.grid_pos, index, is_scaffold=scaffold
                )
                if cell is None:
                    continue
                for other in cells.get((keys[h.id], *cell), ()):
                    pair = frozenset((h.id, other))
                    if other != h.id and (pair not in forced or pair in canonical):
                        graph[h.id].add(other)
                        graph[other].add(h.id)
    return graph


def lattice_components(graph: dict[str, set[str]], ids: set[str]) -> list[list[str]]:
    """Deterministic connected components, including isolated single helices."""
    unseen = set(ids) & graph.keys()
    result = []
    while unseen:
        seed = min(unseen)
        unseen.remove(seed)
        component, stack = [], [seed]
        while stack:
            node = stack.pop()
            component.append(node)
            neighbors = graph[node] & unseen
            unseen.difference_update(neighbors)
            stack.extend(sorted(neighbors))
        result.append(sorted(component))
    return result


def cluster_unassigned_components(
    design: Design, eligible: set[str] | None = None
) -> Design:
    """Append identity-pose clusters for unassigned lattice components.

    Explicit repair considers all eligible lattice helices. Authoring supplies
    only new helices, leaving intentional old orphans alone. IDs are stable for
    feature replay. Domain-only claims also count as existing membership.
    """
    claimed = {hid for c in design.cluster_transforms for hid in c.helix_ids}
    domains = {
        (s.id, i): d.helix_id for s in design.strands for i, d in enumerate(s.domains)
    }
    claimed.update(
        domains.get((r.strand_id, r.domain_index))
        for c in design.cluster_transforms
        for r in c.domain_ids
    )
    graph = lattice_cluster_graph(design)
    candidates = graph.keys() - claimed
    if eligible is not None:
        candidates &= eligible
    groups = lattice_components(graph, candidates)
    if not groups:
        return design
    clusters = list(design.cluster_transforms)
    names = {c.name for c in clusters}
    for group in groups:
        number = 1
        while f"Cluster {number}" in names:
            number += 1
        name = f"Cluster {number}"
        names.add(name)
        key = json.dumps([design.id, group])
        clusters.append(
            ClusterRigidTransform(
                id=str(uuid5(NAMESPACE_URL, "nadoc:lattice-component:" + key)),
                name=name,
                auto_created=True,
                is_default=False,
                helix_ids=group,
            )
        )
    return design.model_copy(update={"cluster_transforms": clusters})


def repair_removed_auto_cluster_membership(
    before: Design, after: Design, removed_ids: set[str]
) -> Design:
    """Keep surviving extrusions grouped when history removes their auto group.

    Only identity-pose automatically created groups can be reconstructed without
    changing placement; explicit groups and transformed groups keep dependencies.
    """
    eligible = {
        hid
        for c in before.cluster_transforms
        if c.id in removed_ids
        and c.auto_created
        and not c.domain_ids
        and c.parent_cluster_id is None
        and c.translation == [0.0, 0.0, 0.0]
        and c.rotation == [0.0, 0.0, 0.0, 1.0]
        for hid in c.helix_ids
        if hid not in removed_ids
    }
    return cluster_unassigned_components(after, eligible) if eligible else after
