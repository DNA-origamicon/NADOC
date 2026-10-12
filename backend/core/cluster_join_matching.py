"""Maximum simultaneous Join connections with exact routing/clearance constraints."""

from collections import defaultdict

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix
from scipy.spatial import cKDTree

from backend.core.cluster_join import _key
from backend.core.models import Direction
from backend.core.sequences import domain_bp_range


def endpoint(port, side):
    return tuple(port[side][k] for k in ("helix_id", "bp_index", "direction"))


class JoinRoutes:
    """Original domain pieces and all possible directed edge exchanges.

    Each fixed scaffold keeps its original 5' root. The moving scaffold's buried
    nick closes. Subtour cuts exclude detached cycles without discarding otherwise
    usable attachment pairs or restricting discovery to a single fixed scaffold.
    """

    def __init__(self, hosts, donor, candidates):
        cuts = {endpoint(p, "from") for pair in candidates for p in pair[:2]}
        self.domains, self.base, self.roots = [], {}, {}
        for strand in [*hosts, donor]:
            begin = len(self.domains)
            for dm in strand.domains:
                start = dm.start_bp
                for bp in domain_bp_range(dm):
                    if _key(dm, bp) in cuts or bp == dm.end_bp:
                        self.domains.append(
                            dm.model_copy(update={"start_bp": start, "end_bp": bp})
                        )
                        start = bp + (1 if dm.direction == Direction.FORWARD else -1)
            end = len(self.domains)
            self.base.update({i: i + 1 for i in range(begin, end - 1)})
            self.base[end - 1] = begin if strand.id == donor.id else None
            if strand.id != donor.id:
                self.roots[strand.id] = begin
        ends = {_key(dm, dm.end_bp): i for i, dm in enumerate(self.domains)}
        starts = {_key(dm, dm.start_bp): i for i, dm in enumerate(self.domains)}
        self.exchanges, self.cutters = [], defaultdict(list)
        for i, (p, q, *_) in enumerate(candidates):
            edges = [
                (ends[endpoint(p, "from")], starts[endpoint(q, "to")]),
                (ends[endpoint(q, "from")], starts[endpoint(p, "to")]),
            ]
            self.exchanges.append(edges)
            for source, _ in edges:
                self.cutters[source].append(i)

    def trace(self, indices):
        successors, labels = dict(self.base), {}
        for i in indices:
            for leg, (a, b) in enumerate(self.exchanges[i]):
                successors[a] = b
                labels[a] = (i, leg)
        visited, paths = set(), {}
        for sid, root in self.roots.items():
            path, node = [], root
            while node is not None and node not in visited:
                visited.add(node)
                path.append(self.domains[node])
                if node in labels:
                    path.append(labels[node])
                node = successors[node]
            if node is not None:
                raise ValueError("Join reused a scaffold attachment edge.")
            paths[sid] = path
        cycles = []
        remaining = set(self.base) - visited
        while remaining:
            nodes, node = set(), min(remaining)
            while node is not None and node not in nodes:
                nodes.add(node)
                node = successors[node]
            cycles.append(nodes)
            remaining.difference_update(nodes)
        return paths, cycles

    def escape_cut(self, nodes):
        """At least one live directed edge must leave a detached component."""
        constant, coefficients = 0, defaultdict(int)
        for a in nodes:
            if self.base[a] not in nodes:
                constant += 1
                for i in self.cutters[a]:
                    coefficients[i] -= 1
        for i, edges in enumerate(self.exchanges):
            coefficients[i] += sum(a in nodes and b not in nodes for a, b in edges)
        return {i: v for i, v in coefficients.items() if v}, 1 - constant


def maximum_connections(candidates, routes=None):
    """Maximize joint count, then prefer short connections among maximum sets.

    Individual candidates have already passed occupied-DNA clearance. Pairwise
    ssDNA collision conflicts and attachment reuse are binary constraints. Lazy
    subtour cuts enforce complete linear routes. A result is returned only after
    the solver certifies optimality; no greedy trimming or count cap is used.
    """
    count = len(candidates)
    if not count:
        return [], {}
    rows, lower, upper = [], [], []
    ports = defaultdict(set)
    for i, pair in enumerate(candidates):
        for port in pair[:2]:
            # Physical directed edges, rather than display IDs, define reuse.
            ports[endpoint(port, "from"), "out"].add(i)
            ports[endpoint(port, "to"), "in"].add(i)
    for indices in ports.values():
        rows.append({i: 1 for i in indices})
        lower.append(-np.inf)
        upper.append(1)
    particles, owners = [], []
    for i, pair in enumerate(candidates):
        for bridge in pair[3]:
            particles.extend(bridge["points"][1:-1])
            owners.extend([i] * (len(bridge["points"]) - 2))
    if particles:
        conflicts = {
            tuple(sorted((owners[a], owners[b])))
            for a, b in cKDTree(particles).query_pairs(0.30 - 1e-10)
            if owners[a] != owners[b]
        }
        for a, b in sorted(conflicts):
            rows.append({a: 1, b: 1})
            lower.append(-np.inf)
            upper.append(1)
    # A unit of cardinality outweighs every possible distance difference.
    distances = np.asarray([pair[2] for pair in candidates])
    objective = -np.ones(count) + distances / ((count + 1) * (max(distances) + 1))
    seen = set()
    while True:
        ri, ci, values = [], [], []
        for row_index, row in enumerate(rows):
            for col, value in row.items():
                ri.append(row_index)
                ci.append(col)
                values.append(value)
        matrix = coo_matrix((values, (ri, ci)), shape=(len(rows), count)).tocsc()
        result = milp(
            objective,
            integrality=np.ones(count),
            bounds=Bounds(0, 1),
            constraints=LinearConstraint(matrix, lower, upper),
            options={"mip_rel_gap": 0},
        )
        if result.status == 2:
            return [], {}
        if not result.success:
            raise ValueError(
                "The complete connection search did not finish; preview again."
            )
        indices = np.flatnonzero(result.x > 0.5).tolist()
        if routes is None:
            return indices, {}
        paths, cycles = routes.trace(indices)
        if not cycles:
            return indices, paths
        for cycle in cycles:
            signature = frozenset(cycle)
            if signature in seen:
                raise ValueError("Connection routing could not be resolved reliably.")
            seen.add(signature)
            row, bound = routes.escape_cut(cycle)
            rows.append(row)
            lower.append(bound)
            upper.append(np.inf)
