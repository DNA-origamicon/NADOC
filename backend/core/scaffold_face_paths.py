"""Scaffold paths constrained by actual free faces of continuous tracks.

Lateral lattice adjacency alone does not make an end turn possible. A track
that continues past its neighbor's end has no free terminus there. These
planners retain the lattice graph but constrain the edges used for end turns.
They only inspect topology and never change the design.
"""

from __future__ import annotations


_PATH_VISIT_BUDGET = 100_000


def _single_intervals(ids, coverage):
    if any(len(coverage.get(hid, [])) != 1 for hid in ids):
        return None
    return {hid: (coverage[hid][0]["lo"], coverage[hid][0]["hi"]) for hid in ids}


def _search_path(ids, adj, *, close_cycle, max_visits, pair_adj=None):
    """Bounded deterministic DFS, including directed face graphs.

    ``pair_adj`` constrains edges 0→1, 2→3, ... of a seamed path. Other
    edges use ``adj``. Exhaustion returns None, without claiming impossibility.
    """
    vertices = set(ids)
    if len(vertices) < 2:
        return None
    local = {hid: set(adj.get(hid, set())) & vertices for hid in vertices}
    incoming = {hid: set() for hid in vertices}
    for hid, neighbors in local.items():
        for nb in neighbors:
            incoming[nb].add(hid)
    if close_cycle and any(not local[h] or not incoming[h] for h in vertices):
        return None
    if pair_adj is not None:
        if len(vertices) % 2 or any(not pair_adj[h] for h in vertices):
            return None
        key = lambda hid: (len(pair_adj[hid]), len(local[hid]), hid)
    else:
        key = lambda hid: (len(local[hid]), len(incoming[hid]), hid)
    starters = sorted(vertices, key=key)
    # A cycle can be rotated to any start; retrying starts wastes the budget.
    if close_cycle:
        starters = starters[:1]
    remaining = set(vertices)
    path = []
    visits = 0

    def visit(hid):
        nonlocal visits
        visits += 1
        if visits > max_visits:
            return False
        path.append(hid)
        remaining.remove(hid)
        if not remaining:
            found = not close_cycle or path[0] in local[hid]
            if found:
                return True
        else:
            # All unvisited nodes must still be reachable from the current end.
            reachable = {hid}
            pending = [hid]
            while pending:
                here = pending.pop()
                for nb in (local[here] & remaining) - reachable:
                    reachable.add(nb)
                    pending.append(nb)
            viable = remaining <= reachable
            if viable and close_cycle:
                sources = remaining | {hid}
                targets = remaining | {path[0]}
                viable = all(
                    incoming[nb] & sources and local[nb] & targets
                    for nb in remaining
                )
            if viable and pair_adj is not None:
                # Each as-yet-unpaired helix needs a partner with both faces
                # matching. At odd path lengths the current end is unpaired.
                unpaired = remaining | ({hid} if len(path) % 2 else set())
                viable = all(pair_adj[nb] & unpaired for nb in unpaired)
            if viable:
                edges = pair_adj if pair_adj is not None and len(path) % 2 else local
                for nb in sorted(edges[hid] & remaining, key=key):
                    if visit(nb):
                        return True
                    if visits >= max_visits:
                        break
        remaining.add(hid)
        path.pop()
        return False

    for start in starters:
        if visit(start):
            return list(path)
        if visits >= max_visits:
            break
    return None


def seamless_face_path(
    ids: list[str],
    adj: dict[str, set[str]],
    coverage: dict[str, list[dict]],
    forward_by_id: dict[str, bool],
    *,
    close_cycle: bool = True,
    max_visits: int = _PATH_VISIT_BUDGET,
) -> list[str] | None:
    """Visit every track once using only turns at shared actual free faces.

    A forward scaffold exits at the high face; a reverse scaffold exits at
    the low face. Thus admissible transitions form a *directed* graph even
    though the underlying lattice neighbor graph is undirected.
    """
    spans = _single_intervals(ids, coverage)
    if spans is None:
        return None
    vertices = set(ids)
    turns = {
        hid: {
            nb
            for nb in adj.get(hid, set()) & vertices
            if forward_by_id[hid] != forward_by_id[nb]
            and spans[hid][1 if forward_by_id[hid] else 0]
            == spans[nb][1 if forward_by_id[hid] else 0]
        }
        for hid in ids
    }
    return _search_path(ids, turns, close_cycle=close_cycle, max_visits=max_visits)


def seamed_face_path(
    ids: list[str],
    adj: dict[str, set[str]],
    coverage: dict[str, list[dict]],
    *,
    max_visits: int = _PATH_VISIT_BUDGET,
) -> list[str] | None:
    """Visit all tracks with matching near/far faces for every end-turn pair.

    Path edges 0→1, 2→3, ... receive both end turns and therefore need equal
    low *and* high faces. Edges 1→2, 3→4, ... receive interior seam junctions
    and may join different spans whenever the supplied lattice graph allows it.
    """
    spans = _single_intervals(ids, coverage)
    if spans is None:
        return None
    vertices = set(ids)
    pairs = {
        hid: {nb for nb in adj.get(hid, set()) & vertices if spans[hid] == spans[nb]}
        for hid in ids
    }
    return _search_path(
        ids, adj, close_cycle=False, max_visits=max_visits, pair_adj=pairs
    )
